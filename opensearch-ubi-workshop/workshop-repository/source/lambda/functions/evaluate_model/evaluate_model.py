"""Pipeline step 5 — live A/B evaluation + model promotion.

Runs the validation queries against the real ecom_products index twice —
baseline BM25 vs LTR-rescored (sltr) — and computes nDCG@10 / recall@10 from
the judgment set. If the LTR model does not lose to the baseline it is
"promoted" by writing its name to the SSM parameter the storefront backend
reads (search ?use_ltr=true then uses it).

Results land in the ecom_ltr_metrics index and S3.
"""
import json
import logging
import math
import os
from datetime import datetime, timezone

import boto3
from oscommon import os_client, s3_get_json, s3_put_json

logger = logging.getLogger()
logger.setLevel("INFO")

PRODUCTS_INDEX = os.environ["PRODUCTS_INDEX"]
METRICS_INDEX = os.environ["METRICS_INDEX"]
DATA_BUCKET = os.environ["DATA_BUCKET"]
LTR_STORE = os.environ.get("LTR_STORE", "_default_")
LTR_FEATURESET = os.environ.get("LTR_FEATURESET", "ecom_features")
LTR_MODEL_PARAM = os.environ["LTR_MODEL_PARAM"]

SEARCH_FIELDS = ["name^3", "series^2", "brand^1.5", "category^1.5", "model_no", "description", "tags"]
K = 10
# Retrieve a wide candidate pool, rescore it, then cut to top-K for the metric.
# (Retrieving only K==10 caps recall at the baseline's top-10 and gives the
# rescore no real candidates to reorder — the main offline/online gap cause.)
RETRIEVE_SIZE = int(os.environ.get("EVAL_RETRIEVE_SIZE", "100"))
# Keep the un-normalized XGBoost margin from dominating the BM25 base score.
# Must match the storefront (main.py) so the promoted blend == the served blend.
LTR_RESCORE_WEIGHT = float(os.environ.get("LTR_RESCORE_WEIGHT", "1.5"))


def baseline_body(query: str, size: int = RETRIEVE_SIZE) -> dict:
    return {
        "size": size,
        "_source": False,
        "query": {"multi_match": {"query": query, "fields": SEARCH_FIELDS, "type": "best_fields"}},
    }


def ltr_body(query: str, model: str, size: int = RETRIEVE_SIZE) -> dict:
    sltr = {"params": {"keywords": query}, "model": model}
    if LTR_STORE not in ("", "_default_"):
        sltr["store"] = LTR_STORE
    body = baseline_body(query, size)
    # blend must match the storefront backend (query_weight 1 / rescore weight)
    body["rescore"] = {
        "window_size": size,
        "query": {"rescore_query": {"sltr": sltr},
                  "query_weight": 1.0, "rescore_query_weight": LTR_RESCORE_WEIGHT,
                  "score_mode": "total"},
    }
    return body


def dcg(grades):
    return sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(grades))


def evaluate(client, queries: dict, model: str | None):
    """queries: {query_norm: {"query": str, "grades": {doc_id: grade}}}"""
    ndcgs, recalls, per_query = [], [], []
    for qn, info in queries.items():
        grades = info["grades"]
        ideal = dcg(sorted(grades.values(), reverse=True)[:K])
        total_rel = sum(1 for g in grades.values() if g >= 2)
        body = ltr_body(info["query"], model) if model else baseline_body(info["query"])
        try:
            resp = client.search(index=PRODUCTS_INDEX, body=body)
        except Exception as e:
            logger.warning("search failed for '%s': %s", info["query"], str(e)[:150])
            continue
        ranked_ids = [h["_id"] for h in resp["hits"]["hits"]][:K]
        ranked_grades = [grades.get(i, 0) for i in ranked_ids]
        row = {"query": info["query"]}
        if ideal > 0:
            n = dcg(ranked_grades) / ideal
            ndcgs.append(n)
            row["ndcg"] = round(n, 4)
        if total_rel > 0:
            r = sum(1 for i in ranked_ids if grades.get(i, 0) >= 2) / total_rel
            recalls.append(r)
            row["recall"] = round(r, 4)
        per_query.append(row)
    mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None
    return {"ndcg@10": mean(ndcgs), "recall@10": mean(recalls),
            "queries_evaluated": len(ndcgs)}, per_query


def handler(event, context):
    run_id = event["run_id"]
    model_name = event["model_name"]
    client = os_client()

    jb, jk = event["judgments_s3"].replace("s3://", "").split("/", 1)
    judgments = s3_get_json(jb, jk)
    vb, vk = event["val_queries_s3"].replace("s3://", "").split("/", 1)
    val_queries = set(s3_get_json(vb, vk))

    queries: dict = {}
    for j in judgments:
        qn = j["query_norm"]
        if val_queries and qn not in val_queries:
            continue
        q = queries.setdefault(qn, {"query": j["query"], "grades": {}})
        q["grades"][j["doc_id"]] = max(q["grades"].get(j["doc_id"], 0), int(j["grade"]))
    if not queries:
        raise RuntimeError("no validation queries with judgments")

    baseline, base_rows = evaluate(client, queries, model=None)
    ltr, ltr_rows = evaluate(client, queries, model=model_name)

    def lift(a, b):
        if a is None or b is None or a == 0:
            return None
        return round((b - a) / a * 100, 2)

    # Honest promotion gate: only promote when LTR actually matches/beats the
    # BM25 baseline online. If it does not, we intentionally do NOT create the
    # SSM model-name parameter, and the storefront LTR toggle correctly falls
    # back to BM25 — that is a valid workshop outcome to read from the metrics,
    # not a bug. (num_val_queries is small here, so treat results as directional.)
    if len(queries) < 15:
        logger.warning("num_val_queries=%d is low; nDCG is high-variance, "
                       "read promotion as directional", len(queries))
    improved = (ltr["ndcg@10"] or 0) >= (baseline["ndcg@10"] or 0)
    promoted = False
    if improved and model_name:
        boto3.client("ssm").put_parameter(
            Name=LTR_MODEL_PARAM, Value=model_name, Type="String", Overwrite=True)
        promoted = True
        logger.info("PROMOTED %s (ltr %.4f >= baseline %.4f)",
                    model_name, ltr["ndcg@10"] or 0, baseline["ndcg@10"] or 0)
    else:
        logger.info("NOT promoted: ltr nDCG@10 %.4f < baseline %.4f "
                    "(SSM %s not written; storefront stays on BM25)",
                    ltr["ndcg@10"] or 0, baseline["ndcg@10"] or 0, LTR_MODEL_PARAM)

    metrics = {
        "run_id": run_id,
        "model_name": model_name,
        "featureset": LTR_FEATURESET,
        "store": LTR_STORE,
        "k": K,
        "num_val_queries": len(queries),
        "baseline": baseline,
        "ltr": ltr,
        "lift_pct": {
            "ndcg@10": lift(baseline["ndcg@10"], ltr["ndcg@10"]),
            "recall@10": lift(baseline["recall@10"], ltr["recall@10"]),
        },
        "offline_metrics": event.get("offline_metrics"),
        "improved": improved,
        "promoted": promoted,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    client.index(index=METRICS_INDEX, body=metrics, refresh=True)
    s3_put_json(DATA_BUCKET, f"pipeline/{run_id}/metrics.json",
                {**metrics, "per_query": {"baseline": base_rows, "ltr": ltr_rows}})

    logger.info("evaluate done: %s", json.dumps(metrics, ensure_ascii=False)[:800])
    return metrics
