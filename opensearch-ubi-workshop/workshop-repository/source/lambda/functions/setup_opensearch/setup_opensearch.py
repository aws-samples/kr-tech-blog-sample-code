"""CFN custom resource: prepare indexes + seed the product catalog + LTR store.

Create/Update:
  - creates the five sample indexes with explicit mappings (idempotent)
  - bulk-loads data/products.json into ecom_products (id -> _id, upsert)
  - ensures the LTR feature store exists (skipped for the default store)
Delete: no-op (shared cluster — cleanup is manual, see scripts/99-cleanup.sh)
"""
import json
import logging
import os
import urllib.request

from oscommon import os_client

logger = logging.getLogger()
logger.setLevel("INFO")

PRODUCTS_INDEX = os.environ["PRODUCTS_INDEX"]
UBI_QUERIES_INDEX = os.environ["UBI_QUERIES_INDEX"]
UBI_EVENTS_INDEX = os.environ["UBI_EVENTS_INDEX"]
JUDGMENTS_INDEX = os.environ["JUDGMENTS_INDEX"]
METRICS_INDEX = os.environ["METRICS_INDEX"]
LTR_STORE = os.environ.get("LTR_STORE", "_default_")

KOREAN_ANALYSIS = {
    "analyzer": {
        "korean": {
            "type": "custom",
            "tokenizer": "nori_mixed",
            "filter": ["lowercase", "nori_readingform"],
        }
    },
    "tokenizer": {
        "nori_mixed": {"type": "nori_tokenizer", "decompound_mode": "mixed"}
    },
}

PRODUCTS_MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 1,
        "analysis": KOREAN_ANALYSIS,
    },
    "mappings": {
        "properties": {
            "name": {
                "type": "text",
                "analyzer": "korean",
                "fields": {
                    "keyword": {"type": "keyword"},
                    "std": {"type": "text", "analyzer": "standard"},
                },
            },
            "brand": {"type": "text", "analyzer": "korean", "fields": {"keyword": {"type": "keyword"}}},
            "category": {"type": "text", "analyzer": "korean", "fields": {"keyword": {"type": "keyword"}}},
            "series": {"type": "text", "analyzer": "korean", "fields": {"keyword": {"type": "keyword"}}},
            "model_no": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "description": {"type": "text", "analyzer": "korean"},
            "tags": {"type": "text", "analyzer": "korean", "fields": {"keyword": {"type": "keyword"}}},
            "specs": {"type": "object", "dynamic": True},
            "price": {"type": "long"},
            "currency": {"type": "keyword"},
            "rating": {"type": "float"},
            "review_count": {"type": "integer"},
            "popularity": {"type": "float"},
            "stock": {"type": "integer"},
            "release_year": {"type": "integer"},
            "emoji": {"type": "keyword"},
            # UBI-derived ranking signals, refreshed by the extract pipeline step
            "ctr": {"type": "float"},
            "cart_rate": {"type": "float"},
            "click_count": {"type": "integer"},
        }
    },
}

UBI_QUERIES_MAPPING = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 1},
    "mappings": {
        "properties": {
            "type": {"type": "keyword"},
            "application": {"type": "keyword"},
            "query_id": {"type": "keyword"},
            "client_id": {"type": "keyword"},
            "session_id": {"type": "keyword"},
            "user_query": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "query": {"type": "text"},
            "query_attributes": {"type": "object", "dynamic": True},
            "query_response_id": {"type": "keyword"},
            "query_response_hit_ids": {"type": "keyword"},
            "timestamp": {"type": "date"},
            "@timestamp": {"type": "date"},
        }
    },
}

UBI_EVENTS_MAPPING = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 1},
    "mappings": {
        "properties": {
            "type": {"type": "keyword"},
            "application": {"type": "keyword"},
            "action_name": {"type": "keyword"},
            "query_id": {"type": "keyword"},
            "client_id": {"type": "keyword"},
            "session_id": {"type": "keyword"},
            "message": {"type": "text"},
            "message_type": {"type": "keyword"},
            "timestamp": {"type": "date"},
            "@timestamp": {"type": "date"},
            "event_attributes": {
                "properties": {
                    "object": {
                        "properties": {
                            "object_id": {"type": "keyword"},
                            "object_id_field": {"type": "keyword"},
                            "name": {"type": "text"},
                            "description": {"type": "text"},
                            "object_detail": {"type": "object", "dynamic": True},
                        }
                    },
                    "position": {"properties": {"ordinal": {"type": "integer"}}},
                    "session_id": {"type": "keyword"},
                    "browser": {"type": "text"},
                    "dwell_time": {"type": "float"},
                    "result_count": {"type": "integer"},
                    "quantity": {"type": "integer"},
                }
            },
        }
    },
}

JUDGMENTS_MAPPING = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 1},
    "mappings": {
        "properties": {
            "run_id": {"type": "keyword"},
            "query": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "query_norm": {"type": "keyword"},
            "doc_id": {"type": "keyword"},
            "product_name": {"type": "text"},
            "grade": {"type": "integer"},
            "grade_llm": {"type": "integer"},
            "grade_implicit": {"type": "integer"},
            "source": {"type": "keyword"},
            "reason": {"type": "text"},
            "impressions": {"type": "integer"},
            "clicks": {"type": "integer"},
            "carts": {"type": "integer"},
            "purchases": {"type": "integer"},
            "ctr": {"type": "float"},
            "model": {"type": "keyword"},
            "timestamp": {"type": "date"},
        }
    },
}

METRICS_MAPPING = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 1},
    "mappings": {"dynamic": True, "properties": {
        "run_id": {"type": "keyword"},
        "model_name": {"type": "keyword"},
        "timestamp": {"type": "date"},
        "promoted": {"type": "boolean"},
    }},
}


def ensure_index(client, name: str, body: dict) -> str:
    if client.indices.exists(index=name):
        return "exists"
    try:
        client.indices.create(index=name, body=body)
        return "created"
    except Exception as e:  # racing / already exists
        if "resource_already_exists" in str(e):
            return "exists"
        raise


def seed_products(client) -> int:
    with open(os.path.join(os.path.dirname(__file__), "products.json"), encoding="utf-8") as f:
        products = json.load(f)
    lines = []
    for p in products:
        lines.append(json.dumps({"index": {"_index": PRODUCTS_INDEX, "_id": p["id"]}}, ensure_ascii=False))
        lines.append(json.dumps(p, ensure_ascii=False))
    # chunked bulk
    total = 0
    chunk = 500  # action+source pairs
    for i in range(0, len(lines), chunk * 2):
        payload = "\n".join(lines[i:i + chunk * 2]) + "\n"
        resp = client.transport.perform_request(
            "POST", "/_bulk", body=payload, headers={"content-type": "application/x-ndjson"}
        )
        if resp.get("errors"):
            errs = [it for it in resp["items"] if it.get("index", {}).get("status", 200) >= 300][:3]
            raise RuntimeError(f"bulk errors: {json.dumps(errs)[:500]}")
        total += len(resp["items"])
    client.indices.refresh(index=PRODUCTS_INDEX)
    return total


def ensure_ltr_store(client) -> str:
    path = "/_ltr" if LTR_STORE in ("", "_default_") else f"/_ltr/{LTR_STORE}"
    try:
        client.transport.perform_request("GET", path)
        return "exists"
    except Exception:
        pass
    client.transport.perform_request("PUT", path)
    return "created"


def do_setup() -> dict:
    client = os_client()
    result = {
        PRODUCTS_INDEX: ensure_index(client, PRODUCTS_INDEX, PRODUCTS_MAPPING),
        UBI_QUERIES_INDEX: ensure_index(client, UBI_QUERIES_INDEX, UBI_QUERIES_MAPPING),
        UBI_EVENTS_INDEX: ensure_index(client, UBI_EVENTS_INDEX, UBI_EVENTS_MAPPING),
        JUDGMENTS_INDEX: ensure_index(client, JUDGMENTS_INDEX, JUDGMENTS_MAPPING),
        METRICS_INDEX: ensure_index(client, METRICS_INDEX, METRICS_MAPPING),
    }
    result["products_seeded"] = seed_products(client)
    result["ltr_store"] = ensure_ltr_store(client)
    return result


def send_response(event, context, status: str, data: dict, reason: str = "") -> None:
    body = json.dumps({
        "Status": status,
        "Reason": (reason or "ok")[:400] + f" | logs: {context.log_stream_name}",
        "PhysicalResourceId": f"ecom-ubi-setup-{os.environ.get('PRODUCTS_INDEX', 'x')}",
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        "Data": {k: str(v) for k, v in list(data.items())[:10]},
    }).encode("utf-8")
    req = urllib.request.Request(event["ResponseURL"], data=body, method="PUT",
                                 headers={"content-type": ""})
    urllib.request.urlopen(req, timeout=30)


def handler(event, context):
    logger.info("event: %s", json.dumps(event)[:1000])
    try:
        if event.get("RequestType") == "Delete":
            send_response(event, context, "SUCCESS", {"note": "indexes retained (shared cluster)"})
            return
        result = do_setup()
        logger.info("setup result: %s", json.dumps(result, ensure_ascii=False))
        send_response(event, context, "SUCCESS", result)
    except Exception as e:
        logger.exception("setup failed")
        send_response(event, context, "FAILED", {}, reason=str(e))
