#!/usr/bin/env python3
"""Realistic shopper simulation against the deployed VoltMall API.

Drives the SAME code path as the browser: POST /api/search (server logs the
UBI query to OSI) and POST /api/ubi/events (impressions/clicks/carts/
purchases). Click behaviour is position-biased and relevance-biased so the
collected UBI data contains a learnable ranking signal.

Usage:
  python3 scripts/simulate_traffic.py --base-url https://dxxxx.cloudfront.net \
      --sessions 300 [--seed 42]
"""
import argparse
import json
import math
import random
import time
import uuid

import requests

QUERY_POOL = [
    # (query, weight, relevance hints: tokens that make a product "wanted")
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
    ("75인치 TV", 4, {"category": "TV", "text": "75인치"}),
    ("게이밍 모니터", 8, {"category": "모니터", "text": "게이밍"}),
    ("4K 모니터", 5, {"category": "모니터", "text": "4K"}),
    ("미러리스 카메라", 6, {"category": "카메라", "text": "미러리스"}),
    ("소니 카메라", 5, {"brand": "소니", "category": "카메라"}),
    ("고프로", 4, {"brand": "고프로", "category": "카메라"}),
    ("플레이스테이션 5", 7, {"brand": "소니", "category": "게임/콘솔", "series": "플레이스테이션"}),
    ("닌텐도 스위치", 7, {"brand": "닌텐도", "category": "게임/콘솔"}),
    ("기계식 키보드", 7, {"category": "키보드/마우스", "text": "기계식"}),
    ("로지텍 마우스", 6, {"brand": "로지텍", "category": "키보드/마우스", "text": "마우스"}),
    ("무선 키보드", 4, {"category": "키보드/마우스", "text": "무선"}),
    ("비스포크 냉장고", 6, {"brand": "삼성전자", "category": "냉장고", "series": "비스포크"}),
    ("김치냉장고", 5, {"category": "냉장고", "text": "김치"}),
    ("드럼 세탁기", 6, {"category": "세탁기/건조기", "text": "드럼"}),
    ("LG 건조기", 5, {"brand": "LG전자", "category": "세탁기/건조기", "text": "건조기"}),
    ("에어컨", 7, {"category": "에어컨/공기청정기", "text": "에어컨"}),
    ("공기청정기", 7, {"category": "에어컨/공기청정기", "text": "공기청정기"}),
    ("다이슨 청소기", 7, {"brand": "다이슨", "category": "청소기"}),
    ("로봇청소기", 8, {"category": "청소기", "text": "로봇"}),
    ("무선 청소기", 5, {"category": "청소기", "text": "무선"}),
    ("에어프라이어", 6, {"category": "주방가전", "text": "에어프라이어"}),
    ("전기밥솥", 5, {"category": "주방가전", "text": "밥솥"}),
    ("커피머신", 4, {"category": "주방가전", "text": "커피"}),
    ("삼성 갤럭시 버즈", 5, {"brand": "삼성전자", "category": "이어폰/헤드폰", "series": "버즈"}),
    ("울트라와이드 모니터", 4, {"category": "모니터", "text": "울트라와이드"}),
    ("갤럭시북", 5, {"brand": "삼성전자", "category": "노트북", "series": "갤럭시북"}),
    ("LG 올레드 65인치", 4, {"brand": "LG전자", "category": "TV", "text": "올레드"}),
    ("스팀덱", 4, {"brand": "밸브", "category": "게임/콘솔", "series": "스팀덱"}),
    ("젠하이저 헤드폰", 3, {"brand": "젠하이저", "category": "이어폰/헤드폰"}),
    ("JBL 스피커", 5, {"brand": "JBL", "category": "스피커"}),
    ("마샬 스피커", 4, {"brand": "마샬", "category": "스피커"}),
    ("후지필름 카메라", 3, {"brand": "후지필름", "category": "카메라"}),
    ("오즈모 포켓", 3, {"brand": "DJI", "category": "카메라", "series": "오즈모"}),
    ("무접점 키보드", 4, {"category": "키보드/마우스", "text": "무접점"}),
    ("게이밍 마우스", 5, {"category": "키보드/마우스", "text": "게이밍 마우스"}),
    ("워시타워", 4, {"brand": "LG전자", "category": "세탁기/건조기", "series": "워시타워"}),
    ("삼성 비스포크 냉장고", 5, {"brand": "삼성전자", "category": "냉장고", "series": "비스포크"}),
    ("창문형 에어컨", 4, {"category": "에어컨/공기청정기", "text": "창문형"}),
    ("다이슨 공기청정기", 3, {"brand": "다이슨", "category": "에어컨/공기청정기"}),
    ("물걸레 로봇청소기", 4, {"category": "청소기", "text": "물걸레"}),
    ("발뮤다 토스터", 3, {"brand": "발뮤다", "category": "주방가전", "series": "더 토스터"}),
    ("쿠쿠 밥솥", 4, {"brand": "쿠쿠", "category": "주방가전", "text": "밥솥"}),
    ("식기세척기", 3, {"brand": "LG전자", "category": "주방가전", "text": "식기세척기"}),
    ("갤럭시 워치", 2, {"brand": "삼성전자", "category": "스마트폰", "text": "갤럭시"}),
    ("아이패드 프로", 4, {"brand": "Apple", "category": "태블릿", "series": "아이패드 프로"}),
    ("샤오미 패드", 3, {"brand": "샤오미", "category": "태블릿", "series": "패드"}),
    ("240Hz 모니터", 3, {"category": "모니터", "text": "240Hz"}),
]


def relevance(product: dict, hints: dict) -> float:
    """0..1 heuristic 'true' relevance of a product for the simulated intent."""
    score = 0.0
    if hints.get("category") and product.get("category") == hints["category"]:
        score += 0.45
    else:
        return 0.02  # wrong category: almost never interesting
    if hints.get("brand"):
        score += 0.3 if product.get("brand") == hints["brand"] else -0.1
    if hints.get("series") and hints["series"] in (product.get("series") or ""):
        score += 0.2
    if hints.get("text"):
        blob = f"{product.get('name','')} {product.get('description','')} {' '.join(product.get('tags',[]))}"
        score += 0.2 if hints["text"] in blob else 0.0
    return max(0.02, min(1.0, score))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--sessions", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--sleep", type=float, default=0.05)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    base = args.base_url.rstrip("/")

    queries, weights, hints_list = zip(*[(q, w, h) for q, w, h in QUERY_POOL])
    sess = requests.Session()

    totals = {"search": 0, "impression": 0, "click": 0, "add_to_cart": 0, "purchase": 0, "errors": 0}
    t0 = time.time()
    for s in range(args.sessions):
        client_id = f"CLIENT-sim-{rng.randint(1, 80):03d}"   # 80 recurring users
        session_id = f"SESSION-{uuid.uuid4()}"
        n_searches = rng.choice([1, 1, 1, 2, 2, 3])
        for _ in range(n_searches):
            qi = rng.choices(range(len(queries)), weights=weights)[0]
            query, hints = queries[qi], hints_list[qi]
            try:
                resp = sess.post(f"{base}/api/search", json={
                    "query": query, "size": 20,
                    "client_id": client_id, "session_id": session_id,
                }, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                totals["errors"] += 1
                print(f"search error: {e}")
                time.sleep(1)
                continue
            totals["search"] += 1
            query_id = data["query_id"]
            hits = data["hits"]
            events = [{
                "action_name": "impression", "query_id": query_id,
                "client_id": client_id, "session_id": session_id,
                "timestamp": int(time.time() * 1000),
                "message": f"{len(hits)}개 결과 노출",
                "event_attributes": {"result_count": len(hits), "session_id": session_id},
            }]
            totals["impression"] += 1

            # position-biased, relevance-biased clicks
            for pos, product in enumerate(hits):
                p_examine = 0.9 / math.log2(pos + 2.2)          # position bias
                p_click = p_examine * (0.15 + 0.8 * relevance(product, hints))
                if rng.random() >= p_click:
                    continue
                attrs = {
                    "session_id": session_id,
                    "position": {"ordinal": pos},
                    "object": {"object_id": product["id"], "object_id_field": "product_id",
                               "name": product.get("name"),
                               "object_detail": {"price": product.get("price"),
                                                  "brand": product.get("brand"),
                                                  "category": product.get("category")}},
                    "dwell_time": round(rng.uniform(2, 45), 1),
                }
                events.append({
                    "action_name": "click", "query_id": query_id,
                    "client_id": client_id, "session_id": session_id,
                    "timestamp": int(time.time() * 1000),
                    "message": f"{pos}번 위치 {product['id']} 클릭",
                    "event_attributes": attrs,
                })
                totals["click"] += 1
                rel = relevance(product, hints)
                if rng.random() < 0.45 * rel:
                    events.append({**events[-1], "action_name": "add_to_cart",
                                   "message": f"{product['id']} 장바구니",
                                   "timestamp": int(time.time() * 1000)})
                    totals["add_to_cart"] += 1
                    if rng.random() < 0.5 * rel:
                        events.append({**events[-1], "action_name": "purchase",
                                       "message": f"{product['id']} 구매",
                                       "timestamp": int(time.time() * 1000)})
                        totals["purchase"] += 1
            try:
                r = sess.post(f"{base}/api/ubi/events", json=events, timeout=15)
                r.raise_for_status()
            except Exception as e:
                totals["errors"] += 1
                print(f"events error: {e}")
            time.sleep(args.sleep)
        if (s + 1) % 25 == 0:
            print(f"[{s+1}/{args.sessions}] {json.dumps(totals, ensure_ascii=False)}")
    print(f"done in {time.time()-t0:.0f}s: {json.dumps(totals, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
