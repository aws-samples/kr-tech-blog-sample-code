"""Pipeline step 1 — extract & aggregate UBI behaviour data.

- scrolls ubi_queries_ecom / ubi_events_ecom
- joins events to queries via query_id
- aggregates per (normalized query, doc): impressions / clicks / carts / purchases / CTR
- derives implicit judgments (purchase=3, cart=2, click>=2 -> 2, click=1,
  impressions>=MIN with no click -> 0)
- pushes doc-level ctr / cart_rate / click_count back into ecom_products
  (these are LTR features — "document CTR" from the UBI logs)
- writes stats + top queries to S3 and returns top queries in the payload
"""
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone

from oscommon import norm_query, os_client, s3_put_json, scroll_all

logger = logging.getLogger()
logger.setLevel("INFO")

UBI_QUERIES_INDEX = os.environ["UBI_QUERIES_INDEX"]
UBI_EVENTS_INDEX = os.environ["UBI_EVENTS_INDEX"]
PRODUCTS_INDEX = os.environ["PRODUCTS_INDEX"]
DATA_BUCKET = os.environ["DATA_BUCKET"]
APPLICATION = os.environ.get("APPLICATION", "voltmall")

MIN_IMPRESSIONS_FOR_ZERO = 3  # judged 0 only with enough evidence


def handler(event, context):
    run_id = event.get("run_id") or datetime.now(timezone.utc).strftime("run-%Y%m%d-%H%M%S")
    options = event.get("options") or {}
    top_n_queries = int(options.get("top_n_queries", 60))
    client = os_client()

    # ---- queries ----
    queries = {}  # query_id -> {user_query, hit_ids}
    query_freq = defaultdict(int)  # query_norm -> count
    query_text = {}  # query_norm -> a representative raw text
    for h in scroll_all(client, UBI_QUERIES_INDEX,
                        {"query": {"term": {"application": APPLICATION}}}):
        src = h["_source"]
        uq = src.get("user_query") or ""
        qn = norm_query(uq)
        if not qn:
            continue
        queries[src.get("query_id")] = {
            "user_query": uq,
            "query_norm": qn,
            "hit_ids": src.get("query_response_hit_ids") or [],
        }
        query_freq[qn] += 1
        query_text.setdefault(qn, uq)

    # ---- impressions from query hit lists ----
    pair = defaultdict(lambda: {"impressions": 0, "clicks": 0, "carts": 0, "purchases": 0, "views": 0})
    doc_stats = defaultdict(lambda: {"impressions": 0, "clicks": 0, "carts": 0, "purchases": 0})
    for q in queries.values():
        qn = q["query_norm"]
        for doc_id in q["hit_ids"]:
            pair[(qn, doc_id)]["impressions"] += 1
            doc_stats[doc_id]["impressions"] += 1

    # ---- events ----
    n_events = 0
    for h in scroll_all(client, UBI_EVENTS_INDEX,
                        {"query": {"term": {"application": APPLICATION}}}):
        src = h["_source"]
        action = src.get("action_name")
        if action not in ("click", "view", "add_to_cart", "purchase"):
            continue
        qinfo = queries.get(src.get("query_id"))
        if not qinfo:
            continue
        obj = (src.get("event_attributes") or {}).get("object") or {}
        doc_id = obj.get("object_id")
        if not doc_id:
            continue
        n_events += 1
        qn = qinfo["query_norm"]
        key = "clicks" if action == "click" else (
            "carts" if action == "add_to_cart" else (
                "purchases" if action == "purchase" else "views"))
        pair[(qn, doc_id)][key] += 1
        if key in ("clicks", "carts", "purchases"):
            doc_stats[doc_id][key] += 1

    # ---- implicit judgments + pair stats ----
    stats_rows = []
    implicit = []
    for (qn, doc_id), s in pair.items():
        ctr = s["clicks"] / s["impressions"] if s["impressions"] else 0.0
        grade = None
        if s["purchases"] > 0:
            grade = 3
        elif s["carts"] > 0:
            grade = 2
        elif s["clicks"] >= 2:
            grade = 2
        elif s["clicks"] == 1:
            grade = 1
        elif s["impressions"] >= MIN_IMPRESSIONS_FOR_ZERO:
            grade = 0
        row = {"query_norm": qn, "query": query_text.get(qn, qn), "doc_id": doc_id,
               **s, "ctr": round(ctr, 4), "grade_implicit": grade}
        stats_rows.append(row)
        if grade is not None:
            implicit.append(row)

    # ---- update product-level behavioural features ----
    updated = 0
    if doc_stats:
        max_clicks = max(s["clicks"] for s in doc_stats.values()) or 1
        lines = []
        for doc_id, s in doc_stats.items():
            ctr = s["clicks"] / s["impressions"] if s["impressions"] else 0.0
            cart_rate = s["carts"] / s["clicks"] if s["clicks"] else 0.0
            lines.append(json.dumps({"update": {"_index": PRODUCTS_INDEX, "_id": doc_id}}))
            lines.append(json.dumps({"doc": {
                "ctr": round(ctr, 4),
                "cart_rate": round(min(cart_rate, 1.0), 4),
                "click_count": s["clicks"],
                "popularity": round(s["clicks"] / max_clicks, 4),
            }}))
        for i in range(0, len(lines), 1000):
            payload = "\n".join(lines[i:i + 1000]) + "\n"
            resp = client.transport.perform_request(
                "POST", "/_bulk", body=payload, headers={"content-type": "application/x-ndjson"})
            updated += sum(1 for it in resp["items"]
                           if it.get("update", {}).get("status", 500) < 300)

    top_queries = [
        {"query": query_text[qn], "query_norm": qn, "count": c}
        for qn, c in sorted(query_freq.items(), key=lambda kv: -kv[1])[:top_n_queries]
    ]

    prefix = f"pipeline/{run_id}"
    stats_uri = s3_put_json(DATA_BUCKET, f"{prefix}/implicit_stats.json", stats_rows)
    s3_put_json(DATA_BUCKET, f"{prefix}/top_queries.json", top_queries)

    result = {
        "run_id": run_id,
        "options": options,
        "query_count": len(queries),
        "distinct_queries": len(query_freq),
        "event_count": n_events,
        "pair_count": len(pair),
        "implicit_judgment_count": len(implicit),
        "products_updated": updated,
        "stats_s3": stats_uri,
        "top_queries": top_queries,
    }
    logger.info("extract done: %s", json.dumps({k: v for k, v in result.items() if k != 'top_queries'}, ensure_ascii=False))
    return result
