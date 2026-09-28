#!/usr/bin/env python3
"""VoltMall 워크샵 - 더미 UBI 검색/클릭 트래픽 생성기.

수동 "검색 -> 클릭" 시나리오만으로는 LTR 학습에 필요한 클릭 볼륨이 부족할 수
있습니다. 이 스크립트는 현실적인 UBI 검색/이벤트 문서를 `ubi_queries_ecom` /
`ubi_events_ecom` 에 **추가(append)** 해서 행동 데이터를 늘립니다. 기존 데이터를
지우지 않으므로 수동 클릭 + 초기 시드 데이터에 그대로 누적됩니다.

문서 스키마는 스토어프론트/OSI 및 파이프라인 Extract 단계와 동일합니다.
  - query 문서: type=query, application, query_id, user_query,
    query_response_hit_ids(BM25 상위 상품 id 목록).
    Extract는 노출(impression)을 이 hit_ids 목록에서 계산합니다.
  - event 문서: type=event, action_name in {impression, click, add_to_cart,
    purchase}, query_id, event_attributes.object.object_id = 상품 _id.
  - 암묵 판정(Extract): purchase>0 -> 3, cart>0 -> 2, click>=2 -> 2,
    click==1 -> 1, 노출>=3 & 무클릭 -> 0.

실행 후에는 LTR 파이프라인(scripts/run_pipeline.sh)이나 노트북을 실행해야
늘어난 로그가 피처/판정/모델에 반영됩니다.

devbox(code-server 터미널) 사용법:
  source ~/workshop/.workshop-env
  python3 ~/workshop/generate_ubi_events.py --sessions 300
"""
import argparse
import json
import math
import os
import time
import uuid
import random

import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

REGION = os.environ.get("AWS_REGION") or boto3.Session().region_name or "ap-northeast-2"
ENV_NAME = os.environ.get("ENV_NAME", "ubi-workshop")  # 워크샵 템플릿의 리소스 이름 접두어

PRODUCTS_INDEX = "ecom_products"
UBI_QUERIES_INDEX = "ubi_queries_ecom"
UBI_EVENTS_INDEX = "ubi_events_ecom"
APPLICATION = "voltmall"
SEARCH_FIELDS = ["name^3", "series^2", "brand^1.5", "category^1.5", "model_no", "description", "tags"]

# (질의, 가중치, 관련성 힌트) - 스토어프론트 시드 트래픽과 동일한 풀.
# 힌트로 관련 상품에 클릭이 몰리도록 해서 LTR이 실제 신호를 학습하게 합니다.
QUERY_POOL = [
    ("삼성 노트북", 10, {"brand": "삼성전자", "category": "노트북"}),
    ("LG 그램", 8, {"brand": "LG전자", "category": "노트북", "series": "그램"}),
    ("맥북 프로", 7, {"brand": "Apple", "category": "노트북", "series": "맥북"}),
    ("게이밍 노트북", 6, {"category": "노트북", "text": "게이밍"}),
    ("갤럭시 스마트폰", 8, {"brand": "삼성전자", "category": "스마트폰"}),
    ("아이폰 16", 9, {"brand": "Apple", "category": "스마트폰", "series": "아이폰 16"}),
    ("아이패드", 6, {"brand": "Apple", "category": "태블릿"}),
    ("갤럭시탭", 5, {"brand": "삼성전자", "category": "태블릿"}),
    ("무선 이어폰", 10, {"category": "이어폰/헤드폰", "text": "무선"}),
    ("에어팟", 8, {"brand": "Apple", "category": "이어폰/헤드폰"}),
    ("소니 헤드폰", 6, {"brand": "소니", "category": "이어폰/헤드폰"}),
    ("노이즈캔슬링 헤드폰", 5, {"category": "이어폰/헤드폰", "text": "노이즈캔슬링"}),
    ("블루투스 스피커", 7, {"category": "스피커", "text": "블루투스"}),
    ("4K TV", 7, {"category": "TV", "text": "4K"}),
    ("올레드 TV", 6, {"brand": "LG전자", "category": "TV", "text": "올레드"}),
    ("게이밍 모니터", 8, {"category": "모니터", "text": "게이밍"}),
    ("미러리스 카메라", 6, {"category": "카메라", "text": "미러리스"}),
    ("플레이스테이션 5", 7, {"brand": "소니", "category": "게임/콘솔", "series": "플레이스테이션"}),
    ("닌텐도 스위치", 7, {"brand": "닌텐도", "category": "게임/콘솔"}),
    ("기계식 키보드", 7, {"category": "키보드/마우스", "text": "기계식"}),
    ("로지텍 마우스", 6, {"brand": "로지텍", "category": "키보드/마우스", "text": "마우스"}),
    ("비스포크 냉장고", 6, {"brand": "삼성전자", "category": "냉장고", "series": "비스포크"}),
    ("드럼 세탁기", 6, {"category": "세탁기/건조기", "text": "드럼"}),
    ("에어컨", 7, {"category": "에어컨/공기청정기", "text": "에어컨"}),
    ("공기청정기", 7, {"category": "에어컨/공기청정기", "text": "공기청정기"}),
    ("다이슨 청소기", 7, {"brand": "다이슨", "category": "청소기"}),
    ("로봇청소기", 8, {"category": "청소기", "text": "로봇"}),
    ("에어프라이어", 6, {"category": "주방가전", "text": "에어프라이어"}),
    ("전기밥솥", 5, {"category": "주방가전", "text": "밥솥"}),
    ("게이밍 마우스", 5, {"category": "키보드/마우스", "text": "게이밍 마우스"}),
]


def relevance(p, hints):
    """상품이 질의 힌트에 얼마나 맞는지 0.02~1.0 점수로 환산."""
    score = 0.0
    if hints.get("category") and p.get("category") == hints["category"]:
        score += 0.45
    else:
        return 0.02
    if hints.get("brand"):
        score += 0.3 if p.get("brand") == hints["brand"] else -0.1
    if hints.get("series") and hints["series"] in (p.get("series") or ""):
        score += 0.2
    if hints.get("text"):
        blob = f"{p.get('name', '')} {p.get('description', '')} {' '.join(p.get('tags', []) or [])}"
        score += 0.2 if hints["text"] in blob else 0.0
    return max(0.02, min(1.0, score))


def click_chain(rng, rel):
    """클릭 -> (관련성 비례) 장바구니 -> 구매 로 이어지는 행동 체인."""
    actions = ["click"]
    if rng.random() < 0.45 * rel:
        actions.append("add_to_cart")
        if rng.random() < 0.5 * rel:
            actions.append("purchase")
    return actions


def resolve_endpoint():
    ep = os.environ.get("OPENSEARCH_ENDPOINT")
    if ep:
        return ep.replace("https://", "").rstrip("/")
    return (boto3.client("opensearch", region_name=REGION)
            .describe_domain(DomainName=f"{ENV_NAME}-search")["DomainStatus"]["Endpoint"])


def make_client():
    ep = resolve_endpoint()
    user = os.environ.get("DASHBOARDS_USER", "admin")
    pw = os.environ.get("DASHBOARDS_PASS", "")
    if pw:
        http_auth = (user, pw)
        mode = "basic (master user)"
    else:
        creds = boto3.Session().get_credentials()
        http_auth = AWS4Auth(creds.access_key, creds.secret_key, REGION, "es",
                             session_token=creds.token)
        mode = "sigv4 (iam role)"
    client = OpenSearch(hosts=[{"host": ep, "port": 443}], http_auth=http_auth,
                        use_ssl=True, verify_certs=True, connection_class=RequestsHttpConnection,
                        timeout=60, max_retries=2, retry_on_timeout=True)
    print(f"opensearch : {ep}")
    print(f"auth       : {mode}")
    return client


def bulk_flush(client, lines, chunk=1000):
    """ndjson 라인(2줄=1문서)을 청크 단위로 _bulk. chunk는 짝수여야 문서가 안 쪼개짐."""
    errors = 0
    for i in range(0, len(lines), chunk):
        body = "\n".join(lines[i:i + chunk]) + "\n"
        resp = client.bulk(body=body)
        if resp.get("errors"):
            errors += sum(1 for it in resp["items"]
                          if next(iter(it.values())).get("status", 500) >= 300)
    return errors


def main():
    ap = argparse.ArgumentParser(description="Append dummy UBI traffic for the VoltMall workshop.")
    ap.add_argument("--sessions", type=int, default=int(os.environ.get("SESSIONS", "300")),
                    help="생성할 세션 수 (기본 300)")
    ap.add_argument("--seed", type=int, default=None,
                    help="난수 시드. 생략하면 매 실행마다 새로운 트래픽을 만듭니다.")
    args = ap.parse_args()
    rng = random.Random(args.seed)

    client = make_client()

    # 상품 로드 (관련성 계산 + 클릭 이벤트 object_detail 용). 카탈로그가 2400건이라
    # size=1000이면 relevance 힌트(series/description/tags)가 일부 상품에서 누락되므로
    # 전체를 커버하도록 넉넉히 로드한다.
    resp = client.search(index=PRODUCTS_INDEX, body={
        "size": 5000, "query": {"match_all": {}},
        "_source": ["name", "brand", "category", "series", "description", "tags"]})
    products = {h["_id"]: h["_source"] for h in resp["hits"]["hits"]}
    if not products:
        raise SystemExit(f"'{PRODUCTS_INDEX}' 에 상품이 없습니다. 도메인/셋업이 준비됐는지 확인하세요.")
    print(f"products   : {len(products)}")

    # BM25 결과 캐시 (같은 질의를 수백 번 검색하므로 캐시로 왕복 최소화)
    bm25_cache = {}

    def bm25_search(query, size=20):
        if query in bm25_cache:
            return bm25_cache[query]
        r = client.search(index=PRODUCTS_INDEX, body={
            "size": size, "_source": ["name", "brand", "category"],
            "query": {"multi_match": {"query": query, "fields": SEARCH_FIELDS,
                                      "type": "best_fields", "operator": "or"}}})
        hits = [{"id": h["_id"], **h["_source"]} for h in r["hits"]["hits"]]
        bm25_cache[query] = hits
        return hits

    queries, weights, hints_list = zip(*QUERY_POOL)
    q_lines, e_lines = [], []
    ts = int(time.time() * 1000)  # 현재 epoch-ms 부터 시작 (신규 트래픽으로 누적)
    totals = {"search": 0, "click": 0, "cart": 0, "purchase": 0}

    for _ in range(args.sessions):
        client_id = f"CLIENT-gen-{rng.randint(1, 120):03d}"
        session_id = f"SESSION-{uuid.uuid4()}"
        for _ in range(rng.choice([1, 1, 1, 2, 2, 3])):  # 세션당 1~3회 검색
            qi = rng.choices(range(len(queries)), weights=weights)[0]
            query, hints = queries[qi], hints_list[qi]
            hits = bm25_search(query)
            if not hits:
                continue
            ts += rng.randint(1000, 5000)
            query_id = str(uuid.uuid4())
            hit_ids = [h["id"] for h in hits]
            totals["search"] += 1

            # query 문서 (Extract는 이 hit_ids 로 노출을 셈)
            q_lines.append(json.dumps({"index": {"_index": UBI_QUERIES_INDEX, "_id": query_id}}))
            q_lines.append(json.dumps({
                "type": "query", "application": APPLICATION, "query_id": query_id,
                "client_id": client_id, "session_id": session_id, "user_query": query,
                "query_response_id": str(uuid.uuid4()), "query_response_hit_ids": hit_ids,
                "timestamp": ts, "@timestamp": ts,
            }, ensure_ascii=False))

            # 결과 페이지 노출 이벤트 (참고용 - Extract는 hit_ids 로 노출을 집계)
            e_lines.append(json.dumps({"index": {"_index": UBI_EVENTS_INDEX}}))
            e_lines.append(json.dumps({
                "type": "event", "application": APPLICATION, "action_name": "impression",
                "query_id": query_id, "client_id": client_id, "session_id": session_id,
                "timestamp": ts, "@timestamp": ts,
                "event_attributes": {"result_count": len(hits), "session_id": session_id},
            }, ensure_ascii=False))

            # 위치 + 관련성 편향 클릭/장바구니/구매
            for pos, product in enumerate(hits):
                rel = relevance(products.get(product["id"], product), hints)
                p_examine = 0.9 / math.log2(pos + 2.2)  # 상위 결과일수록 더 잘 봄
                if rng.random() >= p_examine * (0.15 + 0.8 * rel):
                    continue
                for action in click_chain(rng, rel):
                    ts += rng.randint(500, 3000)
                    totals[{"click": "click", "add_to_cart": "cart", "purchase": "purchase"}[action]] += 1
                    e_lines.append(json.dumps({"index": {"_index": UBI_EVENTS_INDEX}}))
                    e_lines.append(json.dumps({
                        "type": "event", "application": APPLICATION, "action_name": action,
                        "query_id": query_id, "client_id": client_id, "session_id": session_id,
                        "timestamp": ts, "@timestamp": ts,
                        "event_attributes": {
                            "session_id": session_id, "position": {"ordinal": pos},
                            "object": {"object_id": product["id"], "object_id_field": "product_id",
                                       "name": product.get("name"),
                                       "object_detail": {"brand": product.get("brand"),
                                                         "category": product.get("category")}},
                        },
                    }, ensure_ascii=False))

    q_err = bulk_flush(client, q_lines)
    e_err = bulk_flush(client, e_lines)
    client.indices.refresh(index=f"{UBI_QUERIES_INDEX},{UBI_EVENTS_INDEX}")

    print("-" * 48)
    print(f"생성 완료: 검색 {totals['search']}건, 클릭 {totals['click']}, "
          f"장바구니 {totals['cart']}, 구매 {totals['purchase']}")
    if q_err or e_err:
        print(f"경고: bulk 색인 실패 문서 query={q_err}, event={e_err}")
    print(f"  {UBI_QUERIES_INDEX} / {UBI_EVENTS_INDEX} 에 누적되었습니다.")
    print("다음 단계: LTR 파이프라인(scripts/run_pipeline.sh)이나 노트북을 실행해 "
          "늘어난 로그를 피처/판정/모델에 반영하세요.")


if __name__ == "__main__":
    main()
