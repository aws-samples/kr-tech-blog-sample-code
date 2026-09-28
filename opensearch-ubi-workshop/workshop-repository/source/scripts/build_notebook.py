#!/usr/bin/env python3
"""Generates ltr_pipeline_workshop.ipynb (nbformat v4).

The notebook reimplements each Step-Functions LTR pipeline step directly in
Python cells (Option B) so workshop participants execute the real logic
(OpenSearch aggregations, ml-commons LLM judging, sltr feature logging,
XGBoost rank:ndcg training, live nDCG A/B) step-by-step and inspect results.
Data is passed between cells via in-memory variables (no S3 hop).
"""
import json
import os

cells = []


def md(src: str):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": src.strip("\n").splitlines(keepends=True)})


def code(src: str):
    cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
                  "source": src.strip("\n").splitlines(keepends=True)})


# ── 0. Title ─────────────────────────────────────────────────────────────
md(r"""
# VoltMall LTR 파이프라인 단계별 실습 (Learning to Rank)

이 노트북은 검색 관련성 파이프라인의 **5단계를 직접 실행**하며 결과를 확인하는 실습입니다.
`run_pipeline.sh`(Step Functions)가 한 번에 돌리는 것과 **동일한 로직**을, 각 단계를 눈으로 보며 수행합니다.

| 단계 | 내용 | 쓰는 곳 |
|---|---|---|
| 1. Extract | UBI 로그(쿼리·이벤트) 집계 → 암묵 판정 + 행동 피처 | `ecom_products`(ctr/cart_rate/…) |
| 2. Judge | 상위 쿼리 후보를 LLM(Claude)이 0~3 채점 + 암묵 판정 병합 | `ecom_judgments` |
| 3. Features | LTR 피처셋 생성 + `sltr` 피처 로깅 → 학습 데이터 | `_ltr/ecom` 피처셋 |
| 4. Train | XGBoost `rank:ndcg`(LambdaMART) 학습 → 모델 업로드 | `_ltr/ecom` 모델 |
| 5. Evaluate | baseline vs LTR nDCG@10 비교 → 우수 시 승격 | `ecom_ltr_metrics`, SSM |

> ⚠️ 이 노트북은 **실제 워크샵 인덱스에 씁니다**(파이프라인과 동일). 판정 단계는 Bedrock(Claude)을 호출하므로 소량 과금·수 분이 소요됩니다. 셀을 **위에서부터 순서대로** 실행하세요.
""")

# ── 1. Setup ─────────────────────────────────────────────────────────────
md(r"""
## 0단계: 설정 & OpenSearch 클라이언트

CloudFormation 출력에서 도메인 엔드포인트·판정 모델 ID를 읽고, 인스턴스 IAM 역할(SigV4)로 OpenSearch 클라이언트를 만듭니다.
""")

code(r"""
import os, re, json, time, math, hashlib
from collections import defaultdict, Counter
from datetime import datetime, timezone

import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

REGION = os.environ.get("AWS_REGION") or boto3.Session().region_name or "ap-northeast-2"
STACK = "ubi-workshop"
ENV_NAME = "ubi-workshop"

cfn = boto3.client("cloudformation", region_name=REGION)
outs = {o["OutputKey"]: o["OutputValue"]
        for o in cfn.describe_stacks(StackName=STACK)["Stacks"][0]["Outputs"]}
OPENSEARCH_ENDPOINT = outs["OpenSearchDomainEndpoint"]
JUDGE_MODEL_ID = outs["JudgeModelId"]

# fixed names from the workshop template
PRODUCTS_INDEX   = "ecom_products"
UBI_QUERIES_INDEX = "ubi_queries_ecom"
UBI_EVENTS_INDEX  = "ubi_events_ecom"
JUDGMENTS_INDEX  = "ecom_judgments"
METRICS_INDEX    = "ecom_ltr_metrics"
LTR_STORE        = "ecom"
LTR_FEATURESET   = "ecom_features"
APPLICATION      = "voltmall"
LTR_MODEL_PARAM       = f"/{ENV_NAME}/ltr/model-name"          # storefront reads this (?use_ltr=true)
LTR_LAST_MODEL_PARAM  = f"/{ENV_NAME}/ltr/last-trained-model"

# same fields the storefront + pipeline use
SEARCH_FIELDS = ["name^3", "series^2", "brand^1.5", "category^1.5", "model_no", "description", "tags"]

_creds = boto3.Session().get_credentials()
_auth = AWS4Auth(_creds.access_key, _creds.secret_key, REGION, "es", session_token=_creds.token)
client = OpenSearch(hosts=[{"host": OPENSEARCH_ENDPOINT, "port": 443}], http_auth=_auth,
                    use_ssl=True, verify_certs=True, connection_class=RequestsHttpConnection,
                    timeout=60, max_retries=2, retry_on_timeout=True)

def norm_query(q):
    return re.sub(r"\s+", " ", (q or "").strip().lower())

def ltr_path(suffix):
    base = "/_ltr" if LTR_STORE in ("", "_default_") else f"/_ltr/{LTR_STORE}"
    return f"{base}{suffix}"

def scroll_all(index, body, limit=200000):
    body = dict(body); body.setdefault("size", 1000)
    resp = client.search(index=index, body=body, scroll="2m"); sid = resp.get("_scroll_id"); n = 0
    try:
        while True:
            hits = resp["hits"]["hits"]
            if not hits:
                break
            for h in hits:
                yield h; n += 1
                if n >= limit:
                    return
            resp = client.scroll(scroll_id=sid, scroll="2m"); sid = resp.get("_scroll_id")
    finally:
        try:
            client.clear_scroll(scroll_id=sid)
        except Exception:
            pass

RUN_ID = datetime.now(timezone.utc).strftime("run-%Y%m%d-%H%M%S")
print("region        :", REGION)
print("opensearch    :", OPENSEARCH_ENDPOINT)
print("judge model id:", JUDGE_MODEL_ID)
print("run id        :", RUN_ID)
print(client.cat.indices(index="ecom_*,ubi_*", params={"v": "true", "h": "index,docs.count,store.size", "s": "index"}))
""")

# ── 2. Extract ───────────────────────────────────────────────────────────
md(r"""
## 1단계: Extract — UBI 로그 집계 & 암묵 판정

`ubi_queries_ecom`(검색)와 `ubi_events_ecom`(노출·클릭·장바구니·구매)를 `query_id`로 join 해서
`(정규화 쿼리, 상품)` 쌍별 행동을 집계합니다. 여기서:
- **암묵 판정(implicit grade)**: 구매>0 → 3, 장바구니>0 → 2, 클릭≥2 → 2, 클릭=1 → 1, 노출≥3(클릭 없음) → 0
- **문서 행동 피처**를 `ecom_products`에 반영: `ctr`, `cart_rate`, `click_count`, `popularity`
""")

code(r"""
TOP_N_QUERIES = 40           # 상위 쿼리 수 (판정 대상 후보)
MIN_IMPRESSIONS_FOR_ZERO = 3 # 클릭 없이 grade 0을 주려면 필요한 최소 노출

queries, query_freq, query_text = {}, defaultdict(int), {}
for h in scroll_all(UBI_QUERIES_INDEX, {"query": {"term": {"application": APPLICATION}}}):
    src = h["_source"]; uq = src.get("user_query") or ""; qn = norm_query(uq)
    if not qn:
        continue
    queries[src.get("query_id")] = {"user_query": uq, "query_norm": qn,
                                     "hit_ids": src.get("query_response_hit_ids") or []}
    query_freq[qn] += 1; query_text.setdefault(qn, uq)

pair = defaultdict(lambda: {"impressions": 0, "clicks": 0, "carts": 0, "purchases": 0, "views": 0})
doc_stats = defaultdict(lambda: {"impressions": 0, "clicks": 0, "carts": 0, "purchases": 0})
for q in queries.values():
    for doc_id in q["hit_ids"]:
        pair[(q["query_norm"], doc_id)]["impressions"] += 1
        doc_stats[doc_id]["impressions"] += 1

n_events = 0
for h in scroll_all(UBI_EVENTS_INDEX, {"query": {"term": {"application": APPLICATION}}}):
    src = h["_source"]; action = src.get("action_name")
    if action not in ("click", "view", "add_to_cart", "purchase"):
        continue
    qinfo = queries.get(src.get("query_id"))
    if not qinfo:
        continue
    obj = (src.get("event_attributes") or {}).get("object") or {}
    doc_id = obj.get("object_id")
    if not doc_id:
        continue
    n_events += 1; qn = qinfo["query_norm"]
    key = "clicks" if action == "click" else ("carts" if action == "add_to_cart"
          else ("purchases" if action == "purchase" else "views"))
    pair[(qn, doc_id)][key] += 1
    if key in ("clicks", "carts", "purchases"):
        doc_stats[doc_id][key] += 1

stats_rows = []
for (qn, doc_id), s in pair.items():
    ctr = s["clicks"] / s["impressions"] if s["impressions"] else 0.0
    grade = None
    if s["purchases"] > 0:      grade = 3
    elif s["carts"] > 0:        grade = 2
    elif s["clicks"] >= 2:      grade = 2
    elif s["clicks"] == 1:      grade = 1
    elif s["impressions"] >= MIN_IMPRESSIONS_FOR_ZERO: grade = 0
    stats_rows.append({"query_norm": qn, "query": query_text.get(qn, qn), "doc_id": doc_id,
                       **s, "ctr": round(ctr, 4), "grade_implicit": grade})

# push document behavioural features back into ecom_products
if doc_stats:
    max_clicks = max(s["clicks"] for s in doc_stats.values()) or 1
    lines = []
    for doc_id, s in doc_stats.items():
        ctr = s["clicks"] / s["impressions"] if s["impressions"] else 0.0
        cart_rate = s["carts"] / s["clicks"] if s["clicks"] else 0.0
        lines.append(json.dumps({"update": {"_index": PRODUCTS_INDEX, "_id": doc_id}}))
        lines.append(json.dumps({"doc": {"ctr": round(ctr, 4),
                                         "cart_rate": round(min(cart_rate, 1.0), 4),
                                         "click_count": s["clicks"],
                                         "popularity": round(s["clicks"] / max_clicks, 4)}}))
    for i in range(0, len(lines), 1000):
        client.transport.perform_request("POST", "/_bulk", body="\n".join(lines[i:i+1000]) + "\n",
                                          headers={"content-type": "application/x-ndjson"})

top_queries = [{"query": query_text[qn], "query_norm": qn, "count": c}
               for qn, c in sorted(query_freq.items(), key=lambda kv: -kv[1])[:TOP_N_QUERIES]]
implicit_by_pair = {(r["query_norm"], r["doc_id"]): r for r in stats_rows}
behaviour_ids = {}
for r in stats_rows:
    if r["clicks"] or r["carts"] or r["purchases"]:
        behaviour_ids.setdefault(r["query_norm"], []).append(r["doc_id"])

hist = Counter(r["grade_implicit"] for r in stats_rows if r["grade_implicit"] is not None)
print(f"queries={len(queries)}  distinct_queries={len(query_freq)}  events={n_events}  pairs={len(pair)}")
print("implicit grade histogram (0..3):", {g: hist.get(g, 0) for g in (0, 1, 2, 3)})
print("top 10 queries:", [t["query"] for t in top_queries[:10]])
""")

# ── 3. Judge ─────────────────────────────────────────────────────────────
md(r"""
## 2단계: Judge — LLM(Claude) 관련성 판정

상위 쿼리마다 후보 상품(baseline 상위 + 행동 신호가 있는 상품)을 뽑아, OpenSearch **ml-commons**에 등록된
Claude 모델(`_predict`)로 0~3점 채점합니다. LLM 점수(`grade_llm`)가 있으면 그것을, 없으면 암묵 판정(`grade_implicit`)을 최종 grade로 사용해 `ecom_judgments`에 upsert 합니다.

> Bedrock 호출을 줄이려면 `MAX_QUERIES_JUDGE`를 작게 두세요(기본 12). 이미 채점된 쌍은 캐시로 재사용합니다.
""")

code(r"""
MAX_QUERIES_JUDGE = 12   # 판정할 상위 쿼리 수 (LLM 호출량 조절)
JUDGE_TOP_K = 12         # 쿼리당 baseline 후보 수
JUDGE_CAP   = 18         # 쿼리당 총 후보 상한
BATCH       = 5          # LLM 1회 호출당 상품 수

PROMPT_TEMPLATE = '''당신은 한국 전자제품 이커머스 쇼핑몰의 검색 품질 평가 전문가입니다.
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
[{{"id": "<상품ID>", "rating": <0-3>, "reason": "<한 문장 이유>"}}, ...]'''

def render_products(docs):
    out = []
    for d in docs:
        price = d.get("price") or 0
        out.append(f"- id: {d['id']} | 상품명: {d.get('name')} | 카테고리: {d.get('category')} | "
                   f"브랜드: {d.get('brand')} | 가격: {price:,}원 | 설명: {str(d.get('description'))[:120]}")
    return "\n".join(out)

def call_judge_mlcommons(prompt):
    resp = client.transport.perform_request(
        "POST", f"/_plugins/_ml/models/{JUDGE_MODEL_ID}/_predict",
        body={"parameters": {"user_prompt": prompt}})
    data = resp["inference_results"][0]["output"][0]["dataAsMap"]
    return data["output"]["message"]["content"][0]["text"]

def judge_batch(query, docs):
    prompt = PROMPT_TEMPLATE.format(query=query, products=render_products(docs))
    text = None
    for attempt in range(3):
        try:
            text = call_judge_mlcommons(prompt); break
        except Exception as e:
            print("  judge retry", attempt, str(e)[:120]); time.sleep(2 * (attempt + 1))
    if not text:
        return {}
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return {}
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    valid = {d["id"] for d in docs}; out = {}
    for item in arr:
        did = str(item.get("id", ""))
        if did in valid:
            try:
                rating = max(0, min(3, int(item.get("rating", 0))))
            except (TypeError, ValueError):
                continue
            out[did] = {"rating": rating, "reason": str(item.get("reason", ""))[:300]}
    return out

def candidates_for(query, extra_ids):
    body = {"size": JUDGE_TOP_K,
            "query": {"multi_match": {"query": query, "fields": SEARCH_FIELDS, "type": "best_fields"}},
            "_source": ["name", "brand", "category", "price", "description"]}
    resp = client.search(index=PRODUCTS_INDEX, body=body)
    docs, seen = [], set()
    for h in resp["hits"]["hits"]:
        docs.append({"id": h["_id"], **h["_source"]}); seen.add(h["_id"])
    missing = [i for i in extra_ids if i not in seen][: max(0, JUDGE_CAP - len(docs))]
    if missing:
        for d in client.mget(index=PRODUCTS_INDEX, body={"ids": missing})["docs"]:
            if d.get("found"):
                s = d["_source"]
                docs.append({"id": d["_id"], "name": s.get("name"), "brand": s.get("brand"),
                             "category": s.get("category"), "price": s.get("price"),
                             "description": s.get("description")})
    return docs[:JUDGE_CAP]

# reuse already-graded pairs (cheap re-runs)
llm_cache = {}
try:
    for h in scroll_all(JUDGMENTS_INDEX, {"query": {"exists": {"field": "grade_llm"}},
                                          "_source": ["query_norm", "doc_id", "grade_llm", "reason"]}):
        s = h["_source"]
        if s.get("grade_llm") is not None:
            llm_cache[(s["query_norm"], s["doc_id"])] = {"rating": int(s["grade_llm"]), "reason": s.get("reason", "")}
except Exception:
    pass
print("cached LLM-graded pairs:", len(llm_cache))

judgments, llm_calls = [], 0
for tq in top_queries[:MAX_QUERIES_JUDGE]:
    query, qn = tq["query"], tq["query_norm"]
    docs = candidates_for(query, behaviour_ids.get(qn, []))
    if not docs:
        continue
    graded, to_grade = {}, []
    for d in docs:
        c = llm_cache.get((qn, d["id"]))
        (graded.__setitem__(d["id"], c) if c else to_grade.append(d))
    for i in range(0, len(to_grade), BATCH):
        graded.update(judge_batch(query, to_grade[i:i+BATCH])); llm_calls += 1
    for did in {d["id"] for d in docs}:
        llm = graded.get(did); imp = implicit_by_pair.get((qn, did), {})
        g_llm = llm["rating"] if llm else None
        g_imp = imp.get("grade_implicit")
        grade = g_llm if g_llm is not None else g_imp
        if grade is None:
            continue
        judgments.append({"run_id": RUN_ID, "query": query, "query_norm": qn, "doc_id": did,
                          "grade": int(grade), "grade_llm": g_llm, "grade_implicit": g_imp,
                          "source": ("llm+implicit" if (llm and g_imp is not None) else ("llm" if llm else "implicit")),
                          "reason": (llm or {}).get("reason", ""),
                          "model": JUDGE_MODEL_ID, "timestamp": datetime.now(timezone.utc).isoformat()})
    print(f"  judged '{query}': {len(docs)} candidates")

# include implicit-only pairs for queries not sent to the LLM
judged_pairs = {(j["query_norm"], j["doc_id"]) for j in judgments}
for r in stats_rows:
    if (r["query_norm"], r["doc_id"]) in judged_pairs or r.get("grade_implicit") is None:
        continue
    judgments.append({"run_id": RUN_ID, "query": r["query"], "query_norm": r["query_norm"],
                      "doc_id": r["doc_id"], "grade": int(r["grade_implicit"]), "grade_llm": None,
                      "grade_implicit": r["grade_implicit"], "source": "implicit", "reason": "",
                      "model": None, "timestamp": datetime.now(timezone.utc).isoformat()})

# upsert into ecom_judgments (deterministic id => idempotent)
lines = []
for j in judgments:
    lines.append(json.dumps({"index": {"_index": JUDGMENTS_INDEX, "_id": f"{j['query_norm']}::{j['doc_id']}"}}, ensure_ascii=False))
    lines.append(json.dumps(j, ensure_ascii=False))
for i in range(0, len(lines), 1000):
    client.transport.perform_request("POST", "/_bulk", body="\n".join(lines[i:i+1000]) + "\n",
                                      headers={"content-type": "application/x-ndjson"})
client.indices.refresh(index=JUDGMENTS_INDEX)

ghist = Counter(j["grade"] for j in judgments)
print(f"\nLLM calls={llm_calls}  judgments={len(judgments)}  grade histogram={ {g: ghist.get(g,0) for g in (0,1,2,3)} }")
for j in [x for x in judgments if x['grade_llm'] is not None][:5]:
    print(f"  [{j['grade']}] {j['query']} -> {j['doc_id']} : {j['reason'][:60]}")
""")

# ── 4. Features ──────────────────────────────────────────────────────────
md(r"""
## 3단계: Features — LTR 피처셋 + `sltr` 피처 로깅

LTR 스토어 `ecom`에 `ecom_features` 피처셋(13개: 어휘 BM25 신호 + 가격/평점/리뷰 prior + 행동 신호 ctr/cart_rate/popularity)을
(재)생성하고, 판정된 `(쿼리, 상품)` 쌍마다 `sltr` 피처 로깅으로 **학습·서빙 동일 피처**를 추출합니다.
""")

code(r"""
def match_feature(name, field):
    return {"name": name, "params": ["keywords"], "template_language": "mustache",
            "template": {"match": {field: "{{keywords}}"}}}

def field_feature(name, field, modifier="none", missing=0):
    return {"name": name, "params": [], "template_language": "mustache",
            "template": {"function_score": {"query": {"match_all": {}},
                         "field_value_factor": {"field": field, "modifier": modifier, "missing": missing}}}}

FEATURES = [
    match_feature("name_bm25", "name"),
    {"name": "name_phrase", "params": ["keywords"], "template_language": "mustache",
     "template": {"match_phrase": {"name": {"query": "{{keywords}}", "slop": 1}}}},
    match_feature("series_bm25", "series"),
    match_feature("brand_bm25", "brand"),
    match_feature("category_bm25", "category"),
    match_feature("description_bm25", "description"),
    {"name": "overall_bm25", "params": ["keywords"], "template_language": "mustache",
     "template": {"multi_match": {"query": "{{keywords}}", "fields": SEARCH_FIELDS, "type": "best_fields"}}},
    field_feature("price_log", "price", "log1p", 1),
    field_feature("rating", "rating", "none", 3.5),
    field_feature("review_count_log", "review_count", "log1p", 0),
    field_feature("popularity", "popularity", "none", 0),
    field_feature("ctr", "ctr", "none", 0),
    field_feature("cart_rate", "cart_rate", "none", 0),
]
FEATURE_NAMES = [f["name"] for f in FEATURES]

# (re)create the featureset
try:
    client.transport.perform_request("DELETE", ltr_path(f"/_featureset/{LTR_FEATURESET}"))
except Exception:
    pass
client.transport.perform_request("PUT", ltr_path(f"/_featureset/{LTR_FEATURESET}"),
                                 body={"featureset": {"name": LTR_FEATURESET, "features": FEATURES}})
print(f"featureset '{LTR_FEATURESET}' created with {len(FEATURES)} features:", FEATURE_NAMES)

def log_features(query, doc_ids):
    sltr = {"_name": "logged_featureset", "featureset": LTR_FEATURESET, "params": {"keywords": query}}
    if LTR_STORE not in ("", "_default_"):
        sltr["store"] = LTR_STORE
    body = {"size": len(doc_ids),
            "query": {"bool": {"filter": [{"terms": {"_id": doc_ids}}, {"sltr": sltr}]}},
            "ext": {"ltr_log": {"log_specs": {"name": "log_entry0", "named_query": "logged_featureset",
                                              "missing_as_zero": True}}},
            "_source": False}
    resp = client.search(index=PRODUCTS_INDEX, body=body)
    out = {}
    for h in resp["hits"]["hits"]:
        entries = (h.get("fields", {}).get("_ltrlog", [{}]) or [{}])[0].get("log_entry0", [])
        by_name = {e["name"]: e.get("value", 0.0) for e in entries}
        out[h["_id"]] = [float(by_name.get(n, 0.0) or 0.0) for n in FEATURE_NAMES]
    return out

by_query = defaultdict(list)
for j in judgments:
    by_query[j["query_norm"]].append(j)

training_rows, qid_map = [], {}
for qn, rows in sorted(by_query.items()):
    doc_ids = sorted({r["doc_id"] for r in rows})
    feats = log_features(rows[0]["query"], doc_ids)
    if not feats:
        continue
    qid = qid_map.setdefault(qn, len(qid_map) + 1)
    grade_by_doc = {r["doc_id"]: r["grade"] for r in rows}
    for doc_id in doc_ids:
        vec = feats.get(doc_id)
        if vec is None:
            continue
        training_rows.append({"grade": grade_by_doc[doc_id], "qid": qid, "features": vec,
                              "doc_id": doc_id, "query_norm": qn})

print(f"queries={len(qid_map)}  training pairs={len(training_rows)}")
if training_rows:
    ex = training_rows[0]
    print("example row: grade=%d qid=%d doc=%s" % (ex["grade"], ex["qid"], ex["doc_id"]))
    print("  features:", {n: round(v, 3) for n, v in zip(FEATURE_NAMES, ex["features"])})
""")

# ── 5. Train ─────────────────────────────────────────────────────────────
md(r"""
## 4단계: Train — XGBoost `rank:ndcg` (LambdaMART)

피처 벡터로 리스트와이즈 랭킹 모델을 학습합니다. 쿼리 단위로 학습/검증을 나누고(`md5(query)%4==0` → 검증),
검증셋에서 **모델 vs BM25** 오프라인 nDCG@10을 비교한 뒤, 모델을 `model/xgboost+json`으로 LTR 스토어에 업로드합니다.

> `xgboost`, `numpy` 필요 (devbox에 설치되어 있어야 합니다).
""")

code(r"""
import numpy as np
import xgboost as xgb

def is_validation(qn):
    return int(hashlib.md5(qn.encode("utf-8")).hexdigest(), 16) % 4 == 0

def dcg(grades, k=10):
    return sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(grades[:k]))

def ndcg_at_k(ranked, all_g, k=10):
    ideal = dcg(sorted(all_g, reverse=True), k)
    return dcg(ranked, k) / ideal if ideal > 0 else None

groups = defaultdict(list)
for r in training_rows:
    groups[r["query_norm"]].append(r)
train_g = {q: rs for q, rs in groups.items() if not is_validation(q)}
val_g   = {q: rs for q, rs in groups.items() if is_validation(q)}
if len(val_g) < 4 or len(train_g) < 8:   # tiny dataset fallback: 75/25 by order
    items = sorted(groups.items()); cut = max(1, int(len(items) * 0.75))
    train_g, val_g = dict(items[:cut]), dict(items[cut:] or items[:1])
print(f"groups: train={len(train_g)} val={len(val_g)} rows={len(training_rows)}")

def to_dmatrix(g):
    X, y, sizes = [], [], []
    for q in sorted(g):
        rs = g[q]; sizes.append(len(rs))
        for r in rs:
            X.append(r["features"]); y.append(r["grade"])
    d = xgb.DMatrix(np.array(X, dtype=np.float32), label=np.array(y, dtype=np.float32),
                    feature_names=FEATURE_NAMES)
    d.set_group(sizes)
    return d

params = {"objective": "rank:ndcg", "eval_metric": ["ndcg@10"], "eta": 0.08, "max_depth": 4,
          "min_child_weight": 1, "subsample": 0.9, "colsample_bytree": 0.9,
          "lambdarank_pair_method": "topk", "lambdarank_num_pair_per_sample": 8}
booster = xgb.train(params, to_dmatrix(train_g), num_boost_round=100,
                    evals=[(to_dmatrix(train_g), "train"), (to_dmatrix(val_g), "val")], verbose_eval=25)
n_trees = booster.num_boosted_rounds()

# offline: model vs BM25 ordering on the validation split
bm25_idx = FEATURE_NAMES.index("overall_bm25")
base_ndcgs, model_ndcgs = [], []
for q, rs in val_g.items():
    all_g = [r["grade"] for r in rs]
    base_ranked = [r["grade"] for r in sorted(rs, key=lambda r: r["features"][bm25_idx], reverse=True)]
    dm = xgb.DMatrix(np.array([r["features"] for r in rs], dtype=np.float32), feature_names=FEATURE_NAMES)
    order = np.argsort(-booster.predict(dm, iteration_range=(0, n_trees)))
    model_ranked = [rs[i]["grade"] for i in order]
    nb, nm = ndcg_at_k(base_ranked, all_g), ndcg_at_k(model_ranked, all_g)
    if nb is not None: base_ndcgs.append(nb)
    if nm is not None: model_ndcgs.append(nm)
print(f"\noffline nDCG@10  BM25={np.mean(base_ndcgs):.4f}  model={np.mean(model_ndcgs):.4f}")
print("feature importance (gain):",
      {k: round(v, 2) for k, v in sorted(booster.get_score(importance_type='gain').items(), key=lambda kv: -kv[1])})

# upload the model to the LTR store
trees = booster.get_dump(dump_format="json")[:n_trees]
definition = "[" + ",".join(t.strip() for t in trees) + "]"
model_name = f"ecom-ltr-xgb-{RUN_ID.replace('_','-')[-24:].strip('-').lower()}"
try:
    client.transport.perform_request("DELETE", ltr_path(f"/_model/{model_name}"))
except Exception:
    pass
client.transport.perform_request("POST", ltr_path(f"/_featureset/{LTR_FEATURESET}/_createmodel"),
    body={"model": {"name": model_name, "model": {"type": "model/xgboost+json", "definition": definition}}})
val_queries = sorted(val_g.keys())
print(f"\nuploaded LTR model: {model_name}  ({len(trees)} trees)")
""")

# ── 6. Evaluate ──────────────────────────────────────────────────────────
md(r"""
## 5단계: Evaluate — 실검색 baseline vs LTR + 승격

검증 쿼리를 실제 `ecom_products`에 두 번 질의합니다 — **baseline(BM25)** 과 **LTR(`sltr` rescore)** —
그리고 판정셋으로 nDCG@10 / recall@10을 계산합니다. LTR이 baseline 이상이면 SSM(`{ltr/model-name}`)에 모델명을 써서
**승격**합니다(스토어프론트 `?use_ltr=true`가 이 모델을 사용). 결과는 `ecom_ltr_metrics`에 기록됩니다.
""")

code(r"""
K = 10

def baseline_body(query, size=K):
    return {"size": size, "_source": False,
            "query": {"multi_match": {"query": query, "fields": SEARCH_FIELDS, "type": "best_fields"}}}

def ltr_body(query, model, size=K):
    sltr = {"params": {"keywords": query}, "model": model}
    if LTR_STORE not in ("", "_default_"):
        sltr["store"] = LTR_STORE
    b = baseline_body(query, size)
    b["rescore"] = {"window_size": 100, "query": {"rescore_query": {"sltr": sltr},
                    "query_weight": 1.0, "rescore_query_weight": 1.5}}
    return b

# judged grades for validation queries
qmap = {}
for j in judgments:
    qn = j["query_norm"]
    if val_queries and qn not in val_queries:
        continue
    q = qmap.setdefault(qn, {"query": j["query"], "grades": {}})
    q["grades"][j["doc_id"]] = max(q["grades"].get(j["doc_id"], 0), int(j["grade"]))

def evaluate(model):
    ndcgs, recalls = [], []
    for qn, info in qmap.items():
        grades = info["grades"]
        ideal = dcg(sorted(grades.values(), reverse=True)[:K])
        total_rel = sum(1 for g in grades.values() if g >= 2)
        body = ltr_body(info["query"], model) if model else baseline_body(info["query"])
        resp = client.search(index=PRODUCTS_INDEX, body=body)
        ranked_ids = [h["_id"] for h in resp["hits"]["hits"]][:K]
        if ideal > 0:
            ndcgs.append(dcg([grades.get(i, 0) for i in ranked_ids]) / ideal)
        if total_rel > 0:
            recalls.append(sum(1 for i in ranked_ids if grades.get(i, 0) >= 2) / total_rel)
    mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None
    return {"ndcg@10": mean(ndcgs), "recall@10": mean(recalls), "queries_evaluated": len(ndcgs)}

baseline = evaluate(None)
ltr = evaluate(model_name)
def lift(a, b):
    return round((b - a) / a * 100, 2) if (a and b is not None) else None

print(f"{'metric':<12}{'baseline':>12}{'LTR':>12}{'lift %':>10}")
for m in ("ndcg@10", "recall@10"):
    print(f"{m:<12}{str(baseline[m]):>12}{str(ltr[m]):>12}{str(lift(baseline[m], ltr[m])):>10}")

improved = (ltr["ndcg@10"] or 0) >= (baseline["ndcg@10"] or 0)
promoted = False
if improved:
    boto3.client("ssm", region_name=REGION).put_parameter(Name=LTR_MODEL_PARAM, Value=model_name,
                                                           Type="String", Overwrite=True)
    promoted = True
print(f"\nimproved={improved}  promoted={promoted}  (SSM {LTR_MODEL_PARAM} = {model_name if promoted else 'unchanged'})")

client.index(index=METRICS_INDEX, body={"run_id": RUN_ID, "model_name": model_name, "k": K,
             "num_val_queries": len(qmap), "baseline": baseline, "ltr": ltr,
             "lift_pct": {m: lift(baseline[m], ltr[m]) for m in ("ndcg@10", "recall@10")},
             "improved": improved, "promoted": promoted,
             "timestamp": datetime.now(timezone.utc).isoformat()}, refresh=True)
print("metrics written to", METRICS_INDEX)
""")

# ── 7. Bonus ─────────────────────────────────────────────────────────────
md(r"""
## 보너스: 같은 쿼리, baseline vs LTR 결과 비교

방금 학습·승격한 모델이 실제 검색 결과를 어떻게 바꾸는지 눈으로 확인합니다. `QUERY`를 바꿔가며 실행해 보세요.
(3단계 load-data에서 본 "무선 이어폰" 같은 광범위 매칭 쿼리가 특히 흥미롭습니다.)
""")

code(r"""
QUERY = "무선 이어폰"

def show(title, body):
    resp = client.search(index=PRODUCTS_INDEX, body={**body, "_source": ["name", "category", "brand"]})
    print(f"\n=== {title} ===")
    for i, h in enumerate(resp["hits"]["hits"][:10], 1):
        s = h["_source"]
        print(f"{i:2d}. [{s.get('category'):<12}] {s.get('name')}")

show("Baseline (BM25)", baseline_body(QUERY))
show(f"LTR ({model_name})", ltr_body(QUERY, model_name))
""")

nb = {"cells": cells,
      "metadata": {"kernelspec": {"display_name": "Python 3 (ipykernel)", "language": "python", "name": "python3"},
                   "language_info": {"name": "python", "version": "3.12"}},
      "nbformat": 4, "nbformat_minor": 5}

out_path = os.path.join(os.path.dirname(__file__), "ltr_pipeline_workshop.ipynb")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)
print("wrote", out_path, "with", len(cells), "cells")
