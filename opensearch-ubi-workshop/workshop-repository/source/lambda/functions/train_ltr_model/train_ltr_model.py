"""Pipeline step 4 — train an XGBoost LambdaMART ranker and upload it to the
OpenSearch LTR plugin.

- parses the RankLib training file produced by feature logging
- deterministic query-level split (md5(query_norm) % 5 == 0 -> validation)
- xgboost objective rank:ndcg (LambdaMART-style listwise gradient boosting)
- offline metrics: nDCG@10 / recall@10 for the trained model vs the BM25
  baseline (overall_bm25 feature ordering) on the validation split
- uploads the model as model/xgboost+json to the LTR store
"""
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone

import boto3
import numpy as np
import xgboost as xgb
from oscommon import os_client, s3_get_json, s3_get_text, s3_put_json, s3_put_text

logger = logging.getLogger()
logger.setLevel("INFO")

DATA_BUCKET = os.environ["DATA_BUCKET"]
LTR_STORE = os.environ.get("LTR_STORE", "_default_")
LTR_FEATURESET = os.environ.get("LTR_FEATURESET", "ecom_features")


def ltr_path(suffix: str) -> str:
    base = "/_ltr" if LTR_STORE in ("", "_default_") else f"/_ltr/{LTR_STORE}"
    return f"{base}{suffix}"


def is_validation(query_norm: str) -> bool:
    return int(hashlib.md5(query_norm.encode("utf-8")).hexdigest(), 16) % 4 == 0


LINE_RE = re.compile(r"^(\d+)\s+qid:(\d+)\s+(.*?)\s*#\s*(\S+)\s+(.*)$")


def parse_ranklib(text: str):
    rows = []
    for line in text.strip().splitlines():
        m = LINE_RE.match(line.strip())
        if not m:
            continue
        grade, qid, feats, doc_id, qn = m.groups()
        vec = [0.0] * len(feats.split())
        for part in feats.split():
            idx, val = part.split(":")
            vec[int(idx) - 1] = float(val)
        rows.append({"grade": int(grade), "qid": int(qid), "features": vec,
                     "doc_id": doc_id, "query_norm": qn.strip()})
    return rows


def group_rows(rows):
    groups = {}
    for r in rows:
        groups.setdefault(r["query_norm"], []).append(r)
    return groups


def dcg(grades, k=10):
    return sum((2 ** g - 1) / np.log2(i + 2) for i, g in enumerate(grades[:k]))


def ndcg_at_k(ranked_grades, all_grades, k=10):
    ideal = dcg(sorted(all_grades, reverse=True), k)
    return dcg(ranked_grades, k) / ideal if ideal > 0 else None


def recall_at_k(ranked_grades, all_grades, k=10, rel=2):
    total_rel = sum(1 for g in all_grades if g >= rel)
    if total_rel == 0:
        return None
    return sum(1 for g in ranked_grades[:k] if g >= rel) / total_rel


def eval_split(groups, score_fn, k=10):
    """Mean offline nDCG@k / recall@k when each group is reordered by score_fn."""
    ndcgs, recalls = [], []
    for rows in groups.values():
        scored = sorted(rows, key=score_fn, reverse=True)
        ranked = [r["grade"] for r in scored]
        all_g = [r["grade"] for r in rows]
        n = ndcg_at_k(ranked, all_g, k)
        r = recall_at_k(ranked, all_g, k)
        if n is not None:
            ndcgs.append(n)
        if r is not None:
            recalls.append(r)
    return {
        f"ndcg@{k}": round(float(np.mean(ndcgs)), 4) if ndcgs else None,
        f"recall@{k}": round(float(np.mean(recalls)), 4) if recalls else None,
        "queries_scored": len(ndcgs),
    }


def handler(event, context):
    run_id = event["run_id"]
    bucket, key = event["training_s3"].replace("s3://", "").split("/", 1)
    text = s3_get_text(bucket, key)
    fs_bucket, fs_key = event["featureset_s3"].replace("s3://", "").split("/", 1)
    feature_names = s3_get_json(fs_bucket, fs_key)["feature_names"]

    rows = parse_ranklib(text)
    if len(rows) < 20:
        raise RuntimeError(f"not enough training rows ({len(rows)}) — generate more traffic")

    groups = group_rows(rows)
    train_g = {q: r for q, r in groups.items() if not is_validation(q)}
    val_g = {q: r for q, r in groups.items() if is_validation(q)}
    if len(val_g) < 4 or len(train_g) < 8:  # tiny datasets: fall back to 75/25 by order
        items = sorted(groups.items())
        cut = max(1, int(len(items) * 0.75))
        train_g, val_g = dict(items[:cut]), dict(items[cut:] or items[:1])
    logger.info("groups: train=%d val=%d rows=%d", len(train_g), len(val_g), len(rows))

    def to_dmatrix(g):
        X, y, sizes = [], [], []
        for q in sorted(g):
            rs = g[q]
            sizes.append(len(rs))
            for r in rs:
                X.append(r["features"])
                y.append(r["grade"])
        d = xgb.DMatrix(np.array(X, dtype=np.float32), label=np.array(y, dtype=np.float32),
                        feature_names=feature_names)
        d.set_group(sizes)
        return d

    dtrain, dval = to_dmatrix(train_g), to_dmatrix(val_g)
    params = {
        "objective": "rank:ndcg",
        "eval_metric": ["ndcg@10"],
        "eta": 0.08,
        "max_depth": 4,
        "min_child_weight": 1,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "lambdarank_pair_method": "topk",
        "lambdarank_num_pair_per_sample": 8,
    }
    # per-round val ndcg on a few dozen queries is too noisy for early
    # stopping (it fired after 2-4 trees); a fixed, moderately regularized
    # 100 rounds measured best live
    num_rounds = int((event.get("options") or {}).get("num_boost_round", 100))
    booster = xgb.train(
        params, dtrain, num_boost_round=num_rounds,
        evals=[(dtrain, "train"), (dval, "val")],
        verbose_eval=25,
    )
    best_iter = None
    n_trees_used = booster.num_boosted_rounds()

    # offline metrics: model vs BM25-only ordering on validation groups.
    # scoring uses exactly the trees that will be uploaded (n_trees_used).
    bm25_idx = feature_names.index("overall_bm25")
    base_eval = eval_split(val_g, lambda r: r["features"][bm25_idx])

    mod_ndcgs, mod_recalls = [], []
    for q, rs in val_g.items():
        dm = xgb.DMatrix(np.array([r["features"] for r in rs], dtype=np.float32),
                         feature_names=feature_names)
        scores = booster.predict(dm, iteration_range=(0, n_trees_used))
        order = np.argsort(-scores)
        ranked = [rs[i]["grade"] for i in order]
        all_g = [r["grade"] for r in rs]
        n = ndcg_at_k(ranked, all_g)
        rc = recall_at_k(ranked, all_g)
        if n is not None:
            mod_ndcgs.append(n)
        if rc is not None:
            mod_recalls.append(rc)
    model_eval = {
        "ndcg@10": round(float(np.mean(mod_ndcgs)), 4) if mod_ndcgs else None,
        "recall@10": round(float(np.mean(mod_recalls)), 4) if mod_recalls else None,
        "queries_scored": len(mod_ndcgs),
    }

    # upload to the LTR plugin (only the trees up to the best iteration)
    trees = booster.get_dump(dump_format="json")[:n_trees_used]
    definition = "[" + ",".join(t.strip() for t in trees) + "]"
    short = run_id.replace(":", "").replace("_", "-")[-24:].strip("-").lower()
    model_name = f"ecom-ltr-xgb-{short}"
    client = os_client()
    try:
        client.transport.perform_request("DELETE", ltr_path(f"/_model/{model_name}"))
    except Exception:
        pass
    client.transport.perform_request(
        "POST",
        ltr_path(f"/_featureset/{LTR_FEATURESET}/_createmodel"),
        body={"model": {"name": model_name, "model": {"type": "model/xgboost+json",
                                                      "definition": definition}}},
    )
    logger.info("uploaded LTR model %s (%d trees)", model_name, len(trees))

    # remember the newest trained model (used by the next judgment run to add
    # LTR-surfaced candidates, independent of promotion)
    try:
        boto3.client("ssm").put_parameter(
            Name=os.environ.get("LTR_LAST_MODEL_PARAM", "/ecom-ubi/ltr/last-trained-model"),
            Value=model_name, Type="String", Overwrite=True)
    except Exception as e:
        logger.warning("ssm put last-trained-model failed: %s", str(e)[:120])

    prefix = f"pipeline/{run_id}"
    model_uri = s3_put_text(DATA_BUCKET, f"{prefix}/model.xgboost.json", definition)
    fi = booster.get_score(importance_type="gain")
    val_queries = sorted(val_g.keys())
    s3_put_json(DATA_BUCKET, f"{prefix}/val_queries.json", val_queries)
    offline = {
        "baseline_bm25": base_eval,
        "model": model_eval,
        "best_iteration": best_iter,
        "feature_importance_gain": {k: round(v, 3) for k, v in
                                    sorted(fi.items(), key=lambda kv: -kv[1])},
    }
    s3_put_json(DATA_BUCKET, f"{prefix}/offline_metrics.json", offline)

    result = {
        "run_id": run_id,
        "options": event.get("options") or {},
        "model_name": model_name,
        "featureset": LTR_FEATURESET,
        "store": LTR_STORE,
        "num_trees": len(trees),
        "train_queries": len(train_g),
        "val_queries": len(val_g),
        "rows": len(rows),
        "offline_metrics": offline,
        "model_s3": model_uri,
        "val_queries_s3": f"s3://{DATA_BUCKET}/{prefix}/val_queries.json",
        "judgments_s3": event["judgments_s3"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    logger.info("train done: %s", json.dumps(
        {k: v for k, v in result.items() if k != "offline_metrics"}, ensure_ascii=False))
    return result
