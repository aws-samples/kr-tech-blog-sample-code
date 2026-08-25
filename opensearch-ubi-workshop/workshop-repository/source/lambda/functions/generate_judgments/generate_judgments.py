"""Pipeline step 2 — LLM-as-a-judge relevance judgments.

For the top UBI queries, candidate products (baseline top-k + products with
behavioural signals) are graded 0-3 by the Claude model that is already
registered in OpenSearch ml-commons (Bedrock connector). Falls back to calling
Bedrock directly if the ml-commons predict API fails.

LLM grades are combined with the implicit (behaviour-based) grades from step 1:
grade = grade_llm when available, otherwise grade_implicit. Judgments are
upserted into ecom_judgments and archived to S3.
"""
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

import boto3
from oscommon import norm_query, os_client, s3_get_json, s3_put_json

logger = logging.getLogger()
logger.setLevel("INFO")

PRODUCTS_INDEX = os.environ["PRODUCTS_INDEX"]
JUDGMENTS_INDEX = os.environ["JUDGMENTS_INDEX"]
DATA_BUCKET = os.environ["DATA_BUCKET"]
JUDGE_MODEL_ID = os.environ["JUDGE_MODEL_ID"]  # ml-commons model id
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
# Workshop Studio only allows Bedrock in us-west-2 / us-east-1, so the direct
# Bedrock fallback must target that region, not the Lambda's (domain) region.
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-west-2")

SEARCH_FIELDS = ["name^3", "series^2", "brand^1.5", "category^1.5", "model_no", "description", "tags"]
BATCH = 5  # products judged per LLM call

PROMPT_TEMPLATE = """당신은 한국 전자제품 이커머스 쇼핑몰의 검색 품질 평가 전문가입니다.
아래 검색어에 대해 각 상품의 관련성을 0~3점으로 평가하세요.

## 평가 기준
- 3 (완벽): 검색 의도에 정확히 부합하는 상품 (브랜드/카테고리/모델 모두 일치)
- 2 (좋음): 검색 의도를 충분히 만족시킬 수 있는 관련 상품
- 1 (약간 관련): 느슨하게 관련되어 있으나 좋은 결과는 아님
- 0 (무관): 검색 의도와 무관한 상품

## 검색어
"{query}"

## 상품 목록
{products}

## 지시사항
반드시 아래 형식의 JSON 배열만 출력하세요. 다른 텍스트는 출력하지 마세요.
[{{"id": "<상품ID>", "rating": <0-3>, "reason": "<한 문장 이유>"}}, ...]"""


def render_products(docs: list[dict]) -> str:
    lines = []
    for d in docs:
        lines.append(
            f"- id: {d['id']} | 상품명: {d.get('name')} | 카테고리: {d.get('category')} | "
            f"브랜드: {d.get('brand')} | 가격: {d.get('price'):,}원 | 설명: {str(d.get('description'))[:120]}"
        )
    return "\n".join(lines)


def call_judge_mlcommons(client, prompt: str) -> str:
    resp = client.transport.perform_request(
        "POST",
        f"/_plugins/_ml/models/{JUDGE_MODEL_ID}/_predict",
        body={"parameters": {"user_prompt": prompt}},
    )
    data = resp["inference_results"][0]["output"][0]["dataAsMap"]
    return data["output"]["message"]["content"][0]["text"]


def call_judge_bedrock(prompt: str) -> str:
    br = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
    resp = br.converse(
        modelId=BEDROCK_MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 1024, "temperature": 0.0},
    )
    return resp["output"]["message"]["content"][0]["text"]


def judge_batch(client, query: str, docs: list[dict]) -> dict[str, dict]:
    """Return {doc_id: {rating, reason}} for one LLM call, with retries."""
    prompt = PROMPT_TEMPLATE.format(query=query, products=render_products(docs))
    text, source = None, "mlcommons"
    for attempt in range(4):
        try:
            if attempt < 2:
                text = call_judge_mlcommons(client, prompt)
            else:
                source = "bedrock"
                text = call_judge_bedrock(prompt)
            break
        except Exception as e:
            logger.warning("judge attempt %d failed: %s", attempt, str(e)[:200])
            time.sleep(2 * (attempt + 1))
    if not text:
        return {}
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        logger.warning("unparseable judge output: %s", text[:200])
        return {}
    try:
        arr = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("bad JSON from judge: %s", text[:200])
        return {}
    out = {}
    valid_ids = {d["id"] for d in docs}
    for item in arr:
        did = str(item.get("id", ""))
        if did in valid_ids:
            try:
                rating = max(0, min(3, int(item.get("rating", 0))))
            except (TypeError, ValueError):
                continue
            out[did] = {"rating": rating, "reason": str(item.get("reason", ""))[:300], "via": source}
    return out


def last_trained_model() -> str | None:
    try:
        resp = boto3.client("ssm").get_parameter(
            Name=os.environ.get("LTR_LAST_MODEL_PARAM", "/ecom-ubi/ltr/last-trained-model"))
        v = resp["Parameter"]["Value"].strip()
        return v or None
    except Exception:
        return None


def candidates_for(client, query: str, extra_ids: list[str], top_k: int, cap: int,
                   ltr_model: str | None) -> list[dict]:
    body = {
        "size": top_k,
        "query": {"multi_match": {"query": query, "fields": SEARCH_FIELDS, "type": "best_fields"}},
        "_source": ["name", "brand", "category", "price", "description"],
    }
    resp = client.search(index=PRODUCTS_INDEX, body=body)
    docs, seen = [], set()
    for h in resp["hits"]["hits"]:
        docs.append({"id": h["_id"], **h["_source"]})
        seen.add(h["_id"])

    # docs the (last trained) LTR model would surface — judging them removes the
    # "unjudged docs look like grade 0" bias in the live evaluation
    if ltr_model:
        ltr_body = dict(body)
        ltr_body["size"] = top_k
        sltr = {"params": {"keywords": query}, "model": ltr_model}
        store = os.environ.get("LTR_STORE", "_default_")
        if store not in ("", "_default_"):
            sltr["store"] = store
        ltr_body["rescore"] = {
            "window_size": 100,
            "query": {"rescore_query": {"sltr": sltr},
                      "query_weight": 1.0, "rescore_query_weight": 1.5},
        }
        try:
            lresp = client.search(index=PRODUCTS_INDEX, body=ltr_body)
            for h in lresp["hits"]["hits"]:
                if h["_id"] not in seen and len(docs) < cap:
                    docs.append({"id": h["_id"], **h["_source"]})
                    seen.add(h["_id"])
        except Exception as e:
            logger.warning("ltr candidate fetch failed: %s", str(e)[:120])

    missing = [i for i in extra_ids if i not in seen][: max(0, cap - len(docs))]
    if missing:
        mresp = client.mget(index=PRODUCTS_INDEX, body={"ids": missing})
        for d in mresp["docs"]:
            if d.get("found"):
                src = d["_source"]
                docs.append({"id": d["_id"], "name": src.get("name"), "brand": src.get("brand"),
                             "category": src.get("category"), "price": src.get("price"),
                             "description": src.get("description")})
    return docs[:cap]


def existing_llm_judgments(client) -> dict:
    """(query_norm, doc_id) -> {rating, reason} for pairs already graded by the LLM."""
    out = {}
    try:
        from oscommon import scroll_all
        for h in scroll_all(client, JUDGMENTS_INDEX,
                            {"query": {"exists": {"field": "grade_llm"}},
                             "_source": ["query_norm", "doc_id", "grade_llm", "reason"]}):
            s = h["_source"]
            if s.get("grade_llm") is not None:
                out[(s["query_norm"], s["doc_id"])] = {
                    "rating": int(s["grade_llm"]), "reason": s.get("reason", ""), "via": "cache"}
    except Exception as e:
        logger.warning("existing judgment fetch failed: %s", str(e)[:120])
    return out


def handler(event, context):
    run_id = event["run_id"]
    options = event.get("options") or {}
    max_queries = int(options.get("max_queries", 60))
    top_k = int(options.get("judge_top_k", 12))
    cap = int(options.get("judge_cap", 18))

    client = os_client()
    top_queries = event.get("top_queries") or []
    stats_uri = event.get("stats_s3", "")
    bucket_key = stats_uri.replace("s3://", "").split("/", 1)
    stats_rows = s3_get_json(bucket_key[0], bucket_key[1]) if len(bucket_key) == 2 else []
    ltr_model = last_trained_model()
    llm_cache = existing_llm_judgments(client)
    logger.info("ltr candidate model=%s, cached LLM pairs=%d", ltr_model, len(llm_cache))

    implicit_by_pair = {}
    behaviour_ids = {}
    for row in stats_rows:
        qn = row["query_norm"]
        implicit_by_pair[(qn, row["doc_id"])] = row
        if row["clicks"] or row["carts"] or row["purchases"]:
            behaviour_ids.setdefault(qn, []).append(row["doc_id"])

    judgments = []
    llm_calls = 0
    queries_processed = 0
    for tq in top_queries[:max_queries]:
        query, qn = tq["query"], tq["query_norm"]
        try:
            docs = candidates_for(client, query, behaviour_ids.get(qn, []), top_k, cap, ltr_model)
        except Exception as e:
            logger.warning("candidate fetch failed for '%s': %s", query, str(e)[:150])
            continue
        if not docs:
            continue
        graded: dict[str, dict] = {}
        to_grade = []
        for d in docs:
            cached = llm_cache.get((qn, d["id"]))
            if cached:
                graded[d["id"]] = cached
            else:
                to_grade.append(d)
        for i in range(0, len(to_grade), BATCH):
            graded.update(judge_batch(client, query, to_grade[i:i + BATCH]))
            llm_calls += 1
        doc_names = {d["id"]: d.get("name") for d in docs}
        for did in {d["id"] for d in docs}:
            llm = graded.get(did)
            imp = implicit_by_pair.get((qn, did), {})
            grade_llm = llm["rating"] if llm else None
            grade_implicit = imp.get("grade_implicit")
            grade = grade_llm if grade_llm is not None else grade_implicit
            if grade is None:
                continue
            judgments.append({
                "run_id": run_id,
                "query": query,
                "query_norm": qn,
                "doc_id": did,
                "product_name": doc_names.get(did),
                "grade": int(grade),
                "grade_llm": grade_llm,
                "grade_implicit": grade_implicit,
                "source": ("llm+implicit" if (llm and grade_implicit is not None)
                           else ("llm" if llm else "implicit")),
                "reason": (llm or {}).get("reason", ""),
                "impressions": imp.get("impressions", 0),
                "clicks": imp.get("clicks", 0),
                "carts": imp.get("carts", 0),
                "purchases": imp.get("purchases", 0),
                "ctr": imp.get("ctr", 0.0),
                "model": JUDGE_MODEL_ID,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        queries_processed += 1

    # include implicit-only pairs for queries not judged by the LLM
    judged_pairs = {(j["query_norm"], j["doc_id"]) for j in judgments}
    for row in stats_rows:
        key = (row["query_norm"], row["doc_id"])
        if key in judged_pairs or row.get("grade_implicit") is None:
            continue
        judgments.append({
            "run_id": run_id,
            "query": row["query"],
            "query_norm": row["query_norm"],
            "doc_id": row["doc_id"],
            "product_name": None,
            "grade": int(row["grade_implicit"]),
            "grade_llm": None,
            "grade_implicit": row["grade_implicit"],
            "source": "implicit",
            "reason": "",
            "impressions": row.get("impressions", 0),
            "clicks": row.get("clicks", 0),
            "carts": row.get("carts", 0),
            "purchases": row.get("purchases", 0),
            "ctr": row.get("ctr", 0.0),
            "model": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # upsert into judgments index (deterministic ids keep re-runs idempotent)
    indexed = 0
    lines = []
    for j in judgments:
        _id = f"{j['query_norm']}::{j['doc_id']}"
        lines.append(json.dumps({"index": {"_index": JUDGMENTS_INDEX, "_id": _id}}, ensure_ascii=False))
        lines.append(json.dumps(j, ensure_ascii=False))
    for i in range(0, len(lines), 1000):
        payload = "\n".join(lines[i:i + 1000]) + "\n"
        resp = client.transport.perform_request(
            "POST", "/_bulk", body=payload, headers={"content-type": "application/x-ndjson"})
        indexed += sum(1 for it in resp["items"] if it.get("index", {}).get("status", 500) < 300)
    if judgments:
        client.indices.refresh(index=JUDGMENTS_INDEX)

    judgments_uri = s3_put_json(DATA_BUCKET, f"pipeline/{run_id}/judgments.json", judgments)

    result = {
        "run_id": run_id,
        "options": options,
        "queries_processed": queries_processed,
        "llm_calls": llm_calls,
        "judgment_count": len(judgments),
        "indexed": indexed,
        "judgments_s3": judgments_uri,
        "grade_histogram": {
            str(g): sum(1 for j in judgments if j["grade"] == g) for g in (0, 1, 2, 3)
        },
    }
    logger.info("judgments done: %s", json.dumps(result, ensure_ascii=False))
    return result
