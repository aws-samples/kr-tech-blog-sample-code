"""Pipeline step 3 — LTR featureset + feature logging -> RankLib training file.

- (re)creates the `ecom_features` featureset in the LTR store (13 features:
  lexical BM25 signals + price/rating/review priors + UBI behavioural
  signals ctr/cart_rate/popularity)
- for every judged (query, doc) pair, logs feature values with the LTR
  plugin's `sltr` query + `ltr_log` extension (training features == serving
  features, no train/serve skew)
- writes RankLib-format training data + featureset definition to S3
"""
import json
import logging
import os

from oscommon import os_client, s3_get_json, s3_put_json, s3_put_text

logger = logging.getLogger()
logger.setLevel("INFO")

PRODUCTS_INDEX = os.environ["PRODUCTS_INDEX"]
DATA_BUCKET = os.environ["DATA_BUCKET"]
LTR_STORE = os.environ.get("LTR_STORE", "_default_")
LTR_FEATURESET = os.environ.get("LTR_FEATURESET", "ecom_features")

SEARCH_FIELDS = ["name^3", "series^2", "brand^1.5", "category^1.5", "model_no", "description", "tags"]


def ltr_path(suffix: str) -> str:
    base = "/_ltr" if LTR_STORE in ("", "_default_") else f"/_ltr/{LTR_STORE}"
    return f"{base}{suffix}"


def match_feature(name: str, field: str) -> dict:
    return {
        "name": name,
        "params": ["keywords"],
        "template_language": "mustache",
        "template": {"match": {field: "{{keywords}}"}},
    }


def field_feature(name: str, field: str, modifier: str = "none", missing: float = 0) -> dict:
    return {
        "name": name,
        "params": [],
        "template_language": "mustache",
        "template": {
            "function_score": {
                "query": {"match_all": {}},
                "field_value_factor": {"field": field, "modifier": modifier, "missing": missing},
            }
        },
    }


FEATURES = [
    match_feature("name_bm25", "name"),
    {
        "name": "name_phrase",
        "params": ["keywords"],
        "template_language": "mustache",
        "template": {"match_phrase": {"name": {"query": "{{keywords}}", "slop": 1}}},
    },
    match_feature("series_bm25", "series"),
    match_feature("brand_bm25", "brand"),
    match_feature("category_bm25", "category"),
    match_feature("description_bm25", "description"),
    {
        "name": "overall_bm25",
        "params": ["keywords"],
        "template_language": "mustache",
        "template": {
            "multi_match": {"query": "{{keywords}}", "fields": SEARCH_FIELDS, "type": "best_fields"}
        },
    },
    field_feature("price_log", "price", "log1p", 1),
    field_feature("rating", "rating", "none", 3.5),
    field_feature("review_count_log", "review_count", "log1p", 0),
    field_feature("popularity", "popularity", "none", 0),
    field_feature("ctr", "ctr", "none", 0),
    field_feature("cart_rate", "cart_rate", "none", 0),
]
FEATURE_NAMES = [f["name"] for f in FEATURES]


def recreate_featureset(client) -> None:
    try:
        client.transport.perform_request("DELETE", ltr_path(f"/_featureset/{LTR_FEATURESET}"))
        logger.info("deleted existing featureset %s", LTR_FEATURESET)
    except Exception:
        pass
    client.transport.perform_request(
        "PUT",
        ltr_path(f"/_featureset/{LTR_FEATURESET}"),
        body={"featureset": {"name": LTR_FEATURESET, "features": FEATURES}},
    )
    logger.info("created featureset %s with %d features", LTR_FEATURESET, len(FEATURES))


def log_features(client, query: str, doc_ids: list[str]) -> dict[str, list[float]]:
    """Feature values for (query, doc_ids) via sltr feature logging."""
    sltr = {
        "_name": "logged_featureset",
        "featureset": LTR_FEATURESET,
        "params": {"keywords": query},
    }
    if LTR_STORE not in ("", "_default_"):
        sltr["store"] = LTR_STORE
    body = {
        "size": len(doc_ids),
        "query": {
            "bool": {
                "filter": [
                    {"terms": {"_id": doc_ids}},
                    {"sltr": sltr},
                ]
            }
        },
        "ext": {
            "ltr_log": {
                "log_specs": {
                    "name": "log_entry0",
                    "named_query": "logged_featureset",
                    "missing_as_zero": True,
                }
            }
        },
        "_source": False,
    }
    resp = client.search(index=PRODUCTS_INDEX, body=body)
    out = {}
    for h in resp["hits"]["hits"]:
        entries = (h.get("fields", {}).get("_ltrlog", [{}]) or [{}])[0].get("log_entry0", [])
        by_name = {e["name"]: e.get("value", 0.0) for e in entries}
        out[h["_id"]] = [float(by_name.get(n, 0.0) or 0.0) for n in FEATURE_NAMES]
    return out


def handler(event, context):
    run_id = event["run_id"]
    client = os_client()

    bucket, key = event["judgments_s3"].replace("s3://", "").split("/", 1)
    judgments = s3_get_json(bucket, key)
    if not judgments:
        raise RuntimeError("no judgments available — run more traffic first")

    recreate_featureset(client)

    by_query: dict[str, list[dict]] = {}
    for j in judgments:
        by_query.setdefault(j["query_norm"], []).append(j)

    qid_map: dict[str, int] = {}
    lines: list[str] = []
    pairs_logged = 0
    for qn, rows in sorted(by_query.items()):
        query_text = rows[0]["query"]
        doc_ids = sorted({r["doc_id"] for r in rows})
        try:
            feats = log_features(client, query_text, doc_ids)
        except Exception as e:
            logger.warning("feature logging failed for '%s': %s", query_text, str(e)[:200])
            continue
        if not feats:
            continue
        qid = qid_map.setdefault(qn, len(qid_map) + 1)
        grade_by_doc = {r["doc_id"]: r["grade"] for r in rows}
        for doc_id in doc_ids:
            vec = feats.get(doc_id)
            if vec is None:  # doc deleted since judgment
                continue
            fstr = " ".join(f"{i}:{v:.6f}" for i, v in enumerate(vec, 1))
            lines.append(f"{grade_by_doc[doc_id]} qid:{qid} {fstr} # {doc_id} {qn}")
            pairs_logged += 1

    if not lines:
        raise RuntimeError("feature logging produced no rows")

    prefix = f"pipeline/{run_id}"
    training_uri = s3_put_text(DATA_BUCKET, f"{prefix}/training.ranklib.txt", "\n".join(lines))
    featureset_uri = s3_put_json(DATA_BUCKET, f"{prefix}/featureset.json", {
        "store": LTR_STORE,
        "featureset": LTR_FEATURESET,
        "features": FEATURES,
        "feature_names": FEATURE_NAMES,
    })
    qid_uri = s3_put_json(DATA_BUCKET, f"{prefix}/qid_map.json",
                          [{"qid": v, "query_norm": k} for k, v in qid_map.items()])

    result = {
        "run_id": run_id,
        "options": event.get("options") or {},
        "featureset": LTR_FEATURESET,
        "store": LTR_STORE,
        "feature_count": len(FEATURES),
        "feature_names": FEATURE_NAMES,
        "num_queries": len(qid_map),
        "num_pairs": pairs_logged,
        "training_s3": training_uri,
        "featureset_s3": featureset_uri,
        "qid_map_s3": qid_uri,
        "judgments_s3": event["judgments_s3"],
    }
    logger.info("features done: %s", json.dumps(result, ensure_ascii=False))
    return result
