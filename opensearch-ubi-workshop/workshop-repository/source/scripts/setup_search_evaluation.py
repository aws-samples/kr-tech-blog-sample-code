#!/usr/bin/env python3
"""Populate the native OpenSearch Search Relevance Workbench for VoltMall.

The custom Step Functions pipeline logs LTR features, trains XGBoost, and serves
the sltr rescore. It does NOT touch the native Search Relevance Workbench. This
script fills that gap so the Workbench UI (Query Sets / Search Configurations /
Judgments / Experiments) is populated with real, self-consistent objects:

  1. Judgment  (IMPORT_JUDGMENT) <- ecom_judgments  (UBI-implicit + LLM grades)
  2. Query Set (manual)          <- top real UBI queries that have judgments
  3. Search Configurations       <- BM25 baseline  +  LTR (sltr rescore, store "ecom")
  4. Experiments (search eval)   <- POINTWISE_EVALUATION per config (nDCG/precision/MAP
                                    vs judgments)  +  PAIRWISE_COMPARISON (result overlap)

Why the alignment matters: a POINTWISE experiment scores each query-set query on
each search configuration, then looks the returned doc ids up in the judgment.
For the metrics to be non-zero, three things must line up — the query-set query
strings, the judgment's query strings, and the doc ids returned by the search
configs (ecom_products `_id` = P0xxx). This script builds all three from the same
source so they do.

Idempotent: VoltMall objects (name prefix "voltmall_") plus the earlier throwaway
"Claude Sonnet 4.5 Judgments ..." import are deleted and recreated on each run.
Auth = local default IAM via SigV4 (service "es"), same as the rest of the repo.

Usage:
  python3 scripts/setup_search_evaluation.py            # create + wait for metrics
  python3 scripts/setup_search_evaluation.py --no-wait  # create, don't poll experiments
"""
import argparse
import json
import os
import time

import boto3
from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection
from opensearchpy.exceptions import ConnectionError as OSConnectionError
from opensearchpy.exceptions import ConnectionTimeout

REGION = os.environ.get("AWS_REGION", "us-east-1")

PRODUCTS_INDEX = "ecom_products"
JUDGMENTS_INDEX = "ecom_judgments"
UBI_QUERIES_INDEX = "ubi_queries_ecom"
LTR_STORE = "ecom"
LTR_MODEL_PARAM = "/ecom-ubi/ltr/model-name"
SEARCH_FIELDS = ["name^3", "series^2", "brand^1.5", "category^1.5",
                 "model_no", "description", "tags"]

PREFIX = "voltmall_"
QUERYSET_NAME = PREFIX + "ubi_queryset"
JUDGMENT_NAME = PREFIX + "ubi_judgments"
SC_BM25_NAME = PREFIX + "bm25_baseline"
SC_LTR_NAME = PREFIX + "ltr_rescore"
# legacy throwaway objects from earlier manual testing that we own and clean up
LEGACY_JUDGMENT_PREFIXES = ("Claude Sonnet 4.5 Judgments",)

QUERYSET_SIZE = 30
EVAL_K = 10

SR = "/_plugins/_search_relevance"

client = None  # set by connect() in main() after the endpoint is resolved


def connect(endpoint):
    global client
    host = endpoint.replace("https://", "").replace("http://", "").rstrip("/")
    client = OpenSearch(
        hosts=[{"host": host, "port": 443}],
        http_auth=AWSV4SignerAuth(boto3.Session().get_credentials(), REGION, "es"),
        use_ssl=True, verify_certs=True,
        connection_class=RequestsHttpConnection, timeout=120,
    )
    return host


def req(method, path, body=None, retries=4):
    """Perform a request, retrying transient timeouts — this shared cluster is
    frequently slow and single requests can take >60s under load."""
    delay = 4
    for attempt in range(retries):
        try:
            return client.transport.perform_request(method, path, body=body)
        except (ConnectionTimeout, OSConnectionError) as e:
            if attempt == retries - 1:
                raise
            print(f"      (retry {attempt + 1}/{retries - 1} after {type(e).__name__})")
            time.sleep(delay)
            delay = min(delay * 2, 30)


def created_id(resp):
    for k, v in resp.items():
        if k.endswith("_id"):
            return v
    return resp.get("id")


def sr_list(kind):
    try:
        r = req("GET", f"{SR}/{kind}")
        return [(h["_id"], h.get("_source", {})) for h in r.get("hits", {}).get("hits", [])]
    except Exception as e:
        print(f"  ! list {kind} failed: {str(e)[:160]}")
        return []


def promoted_model():
    try:
        v = boto3.client("ssm", region_name=REGION).get_parameter(
            Name=LTR_MODEL_PARAM)["Parameter"]["Value"].strip()
        return v if v and v != "none" else None
    except Exception:
        return None


# ---------------------------------------------------------------- cleanup ----
def cleanup():
    ours_qs = [i for i, s in sr_list("query_sets") if str(s.get("name", "")).startswith(PREFIX)]
    ours_sc = [i for i, s in sr_list("search_configurations")
               if str(s.get("name", "")).startswith(PREFIX)]
    ours_ids = set(ours_qs) | set(ours_sc)

    # experiments first (they lock their search configs); match by reference
    for i, s in sr_list("experiments"):
        refs = set(s.get("searchConfigurationList", []) or []) | {s.get("querySetId")}
        if refs & ours_ids:
            try:
                req("DELETE", f"{SR}/experiments/{i}")
                print(f"  - deleted experiment {i}")
            except Exception as e:
                print(f"  ! del experiment {i}: {str(e)[:120]}")

    for kind, ids in (("search_configurations", ours_sc), ("query_sets", ours_qs)):
        for i in ids:
            try:
                req("DELETE", f"{SR}/{kind}/{i}")
                print(f"  - deleted {kind} {i}")
            except Exception as e:
                print(f"  ! del {kind} {i}: {str(e)[:120]}")

    for i, s in sr_list("judgments"):
        name = str(s.get("name", ""))
        if name.startswith(PREFIX) or any(name.startswith(p) for p in LEGACY_JUDGMENT_PREFIXES):
            try:
                req("DELETE", f"{SR}/judgments/{i}")
                print(f"  - deleted judgment {i} ({name})")
            except Exception as e:
                print(f"  ! del judgment {i}: {str(e)[:120]}")


# ------------------------------------------------------------ build inputs ----
def build_judgment_ratings():
    """Group ecom_judgments into judgmentRatings; max grade per (query, doc)."""
    r = req("GET", f"/{JUDGMENTS_INDEX}/_search",
            {"size": 5000, "query": {"match_all": {}},
             "_source": ["query", "doc_id", "grade"]})
    by_q = {}
    for h in r["hits"]["hits"]:
        s = h["_source"]
        q, d, g = s.get("query"), s.get("doc_id"), s.get("grade")
        if q is None or d is None or g is None:
            continue
        docs = by_q.setdefault(q, {})
        docs[d] = max(docs.get(d, -1), int(g))
    ratings = [{"query": q,
                "ratings": [{"rating": f"{g}.0", "docId": d} for d, g in docs.items()]}
               for q, docs in by_q.items()]
    return ratings, set(by_q.keys())


def pick_queries(judged):
    r = req("GET", f"/{UBI_QUERIES_INDEX}/_search",
            {"size": 0, "aggs": {"q": {"terms": {"field": "user_query.keyword", "size": 200}}}})
    freq = [b["key"] for b in r["aggregations"]["q"]["buckets"]]
    picked = [q for q in freq if q in judged][:QUERYSET_SIZE]
    for q in sorted(judged):  # top up from judged-but-not-in-UBI if short
        if len(picked) >= QUERYSET_SIZE:
            break
        if q not in picked:
            picked.append(q)
    return picked


def bm25_query():
    return json.dumps({"query": {"multi_match": {
        "query": "%SearchText%", "fields": SEARCH_FIELDS,
        "type": "best_fields", "operator": "or"}}}, ensure_ascii=False)


# --------------------------------------------------------------- experiment ----
def wait_experiment(exp_id, timeout=420):
    for _ in range(timeout // 8):
        r = req("GET", f"{SR}/experiments/{exp_id}")
        src = r["hits"]["hits"][0]["_source"]
        if src.get("status") != "PROCESSING":
            return src
        time.sleep(8)
    return req("GET", f"{SR}/experiments/{exp_id}")["hits"]["hits"][0]["_source"]


def summarize_pointwise(src, label):
    """Print mean of each metric across queries in a POINTWISE result."""
    results = src.get("results") or []
    agg = {}
    for row in results:
        metrics = row.get("metrics") or []
        for m in metrics:
            name = m.get("metric")
            val = m.get("value")
            if name is not None and isinstance(val, (int, float)):
                agg.setdefault(name, []).append(val)
    print(f"  [{label}] status={src.get('status')} queries={len(results)}")
    for name in sorted(agg):
        vals = agg[name]
        print(f"      {name:<16} mean={sum(vals) / len(vals):.4f}  (n={len(vals)})")
    if not agg and results:
        print("      (unrecognized results shape; raw first row below)")
        print("      " + json.dumps(results[0], ensure_ascii=False)[:400])
    return agg


# ---------------------------------------------------------------------- main ----
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", required=True,
                    help="OpenSearch domain host containing the workshop indexes")
    ap.add_argument("--no-wait", action="store_true", help="don't poll experiments to completion")
    args = ap.parse_args()

    host = connect(args.endpoint)
    model = promoted_model()
    print(f"endpoint: {host}")
    print(f"promoted LTR model: {model or '(none)'}")
    if model:
        print("note: SRW LTR config is skipped because OpenSearch 3.5 can fail to parse sltr rescore queries")

    print("\n[1/5] cleanup existing VoltMall/legacy Workbench objects")
    cleanup()

    print("\n[2/5] judgment (IMPORT_JUDGMENT) from ecom_judgments")
    ratings, judged = build_judgment_ratings()
    n_ratings = sum(len(r["ratings"]) for r in ratings)
    jresp = req("PUT", f"{SR}/judgments",
                {"name": JUDGMENT_NAME, "type": "IMPORT_JUDGMENT", "judgmentRatings": ratings})
    jid = created_id(jresp)
    print(f"  judgment id={jid}  queries={len(ratings)}  ratings={n_ratings}")

    print("\n[3/5] query set (manual) from top UBI queries with judgments")
    queries = pick_queries(judged)
    qresp = req("PUT", f"{SR}/query_sets",
                {"name": QUERYSET_NAME, "description": "Top real VoltMall UBI search queries",
                 "sampling": "manual",
                 "querySetQueries": [{"queryText": q} for q in queries]})
    qs_id = created_id(qresp)
    print(f"  query_set id={qs_id}  queries={len(queries)}")
    print("  " + ", ".join(queries[:12]) + (" ..." if len(queries) > 12 else ""))

    print("\n[4/5] search configurations")
    sc_bm25 = created_id(req("PUT", f"{SR}/search_configurations",
                             {"name": SC_BM25_NAME, "index": PRODUCTS_INDEX, "query": bm25_query()}))
    print(f"  bm25 baseline id={sc_bm25}")
    print("\n[5/5] experiments (search evaluation)")
    # Create and wait sequentially: this shared cluster bogs down when several
    # evaluations run at once (PUTs and even GETs start timing out). One at a
    # time keeps it responsive and lets each finish before the next starts.
    configs = [("bm25_baseline", sc_bm25)]
    summaries = {}
    for label, sc in configs:
        eid = created_id(req("PUT", f"{SR}/experiments",
                             {"querySetId": qs_id, "searchConfigurationList": [sc],
                              "judgmentList": [jid], "size": EVAL_K,
                              "type": "POINTWISE_EVALUATION"}))
        print(f"  pointwise[{label}] experiment id={eid}")
        if not args.no_wait:
            summaries[label] = summarize_pointwise(wait_experiment(eid), label)
    if args.no_wait:
        print("\ndone (experiments run asynchronously; open the Workbench to see metrics)")
        return

    b = summaries.get("bm25_baseline", {})
    print("\ndone")


if __name__ == "__main__":
    main()
