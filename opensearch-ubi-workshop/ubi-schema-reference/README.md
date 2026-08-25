# UBI 스키마 레퍼런스

## 1. 범위

UBI(User Behavior Insights)는 검색 요청과 그 이후의 사용자 행동을 공통 식별자로 연결하기 위한 데이터 모델입니다. 이 워크샵은 Amazon OpenSearch Service에서 UBI 형식의 두 인덱스를 직접 운영합니다.

| 인덱스 | 역할 | 기본 조인 키 |
|---|---|---|
| `ubi_queries_ecom` | 검색어, 반환 결과, 세션과 응답 메타데이터 | `query_id` |
| `ubi_events_ecom` | 클릭, 장바구니, 구매 등 후속 행동 | `query_id` |

공식 참고:

- [OpenSearch UBI index schemas](https://docs.opensearch.org/latest/search-plugins/ubi/schemas/)
- [Amazon OpenSearch Service에서 UBI 형식 데이터 수집](https://docs.opensearch.org/latest/search-plugins/ubi/ubi-aws-managed-services-tutorial/)

## 2. `ubi_queries_ecom`

| 필드 | 타입 | 필수도 | 설명 |
|---|---|---:|---|
| `query_id` | keyword | 필수 | Query와 Event를 연결하는 고유 ID |
| `user_query` | text + keyword | 필수 | 사용자가 입력한 검색어 |
| `application` | keyword | 필수 | 데이터 발생 애플리케이션. 워크샵 값은 `voltmall` |
| `query_response_id` | keyword | 권장 | 한 번의 검색 응답 ID |
| `query_response_hit_ids` | keyword[] | 필수 | 반환된 상품 문서 ID의 순서 보존 배열 |
| `client_id` | keyword | 권장 | 가명화된 클라이언트 ID |
| `session_id` | keyword | 권장 | 가명화된 검색 세션 ID |
| `timestamp` | date | 필수 | 검색 발생 시각 |
| `@timestamp` | date | 워크샵 확장 | Dashboards 시계열용 시각 |
| `query_attributes` | object | 워크샵 확장 | 검색 모드, 페이지, LTR 적용 여부 등 |
| `type` | keyword | 수집 확장 | OSIS 라우팅 값 `query` |

```json
{
  "type": "query",
  "application": "voltmall",
  "query_id": "a7678e42-0d84-4cc2-b48b-8fffd741dc01",
  "query_response_id": "fd96d297-9060-4fe3-98cf-098677fb88bf",
  "client_id": "client-7c139d",
  "session_id": "session-91a5d1",
  "user_query": "무선 이어폰",
  "query_response_hit_ids": ["P-1021", "P-0433", "P-0872"],
  "query_attributes": {
    "search_mode": "bm25",
    "ltr_used": false,
    "from": 0,
    "size": 20
  },
  "timestamp": "2026-08-25T01:20:33.104Z",
  "@timestamp": "2026-08-25T01:20:33.104Z"
}
```

## 3. `ubi_events_ecom`

| 필드 | 타입 | 필수도 | 설명 |
|---|---|---:|---|
| `action_name` | keyword | 필수 | `impression`, `click`, `view`, `add_to_cart`, `purchase` |
| `query_id` | keyword | 필수 | 원 검색의 `query_id` |
| `application` | keyword | 필수 | 워크샵 값 `voltmall` |
| `client_id` | keyword | 권장 | Query와 동일한 가명 클라이언트 ID |
| `session_id` | keyword | 권장 | Query와 동일한 가명 세션 ID |
| `event_attributes.object.object_id` | keyword | 객체 행동 시 필수 | `ecom_products` 문서 ID |
| `event_attributes.object.object_id_field` | keyword | 권장 | 객체 ID의 원본 필드명. 워크샵 값 `product_id` |
| `event_attributes.position.ordinal` | integer | 클릭 시 권장 | 결과 위치. 워크샵은 0부터 시작 |
| `event_attributes.quantity` | integer | 선택 | 장바구니·구매 수량 |
| `event_attributes.dwell_time` | float | 선택 | 체류 시간 |
| `timestamp` | date | 필수 | 이벤트 시각 |
| `@timestamp` | date | 워크샵 확장 | Dashboards 시계열용 시각 |
| `type` | keyword | 수집 확장 | OSIS 라우팅 값 `event` |

```json
{
  "type": "event",
  "application": "voltmall",
  "action_name": "click",
  "query_id": "a7678e42-0d84-4cc2-b48b-8fffd741dc01",
  "client_id": "client-7c139d",
  "session_id": "session-91a5d1",
  "event_attributes": {
    "position": { "ordinal": 1 },
    "object": {
      "object_id": "P-0433",
      "object_id_field": "product_id",
      "name": "갤럭시 버즈3"
    }
  },
  "timestamp": "2026-08-25T01:20:36.428Z",
  "@timestamp": "2026-08-25T01:20:36.428Z"
}
```

## 4. 워크샵 집계 규칙

### 노출 수

LTR 파이프라인의 `ExtractUbiData`는 각 Query 문서의 `query_response_hit_ids`에 포함된 상품을 1회 노출로 집계합니다.

```text
impressions(query, product)
  = product가 query_response_hit_ids에 포함된 Query 문서 수
```

이벤트 생성기가 기록하는 `action_name=impression` 문서는 대시보드의 행동 분포·시계열 관찰에 사용되지만, 현재 `ExtractUbiData`는 이를 CTR 분모에 더하지 않습니다. Query hit 배열과 impression 이벤트를 동시에 분모로 사용하면 이중 집계가 되므로 주의하세요.

### CTR과 장바구니율

```text
CTR(query, product) = clicks / impressions
product CTR         = product clicks / product impressions
cart_rate           = carts / clicks
```

`ExtractUbiData`는 상품별 값을 `ecom_products`의 다음 필드에 역기록합니다.

| 필드 | 설명 |
|---|---|
| `click_count` | 누적 클릭 수 |
| `ctr` | Query hit 배열 기반 노출 대비 클릭률 |
| `cart_rate` | 클릭 대비 장바구니 비율, 최대 1.0으로 제한 |
| `popularity` | 최대 클릭 상품 대비 정규화된 클릭 수 |

### 암묵적 판정

| 관측 행동 | `grade_implicit` |
|---|---:|
| 구매 1회 이상 | 3 |
| 장바구니 1회 이상 | 2 |
| 클릭 2회 이상 | 2 |
| 클릭 1회 | 1 |
| 노출 3회 이상, 클릭 없음 | 0 |
| 그 외 | 판정 보류 |

이 값은 노출·위치·브랜드 편향을 포함할 수 있으므로 LLM 판정과 데이터 Coverage를 함께 검토합니다.

## 5. 파생 인덱스

### `ecom_judgments`

| 필드 | 의미 |
|---|---|
| `run_id` | 파이프라인 실행 ID |
| `query`, `query_norm` | 원 검색어와 정규화 검색어 |
| `doc_id`, `product_name` | 판정 대상 상품 |
| `grade` | 최종 0~3 관련성 등급 |
| `grade_llm`, `grade_implicit` | LLM과 행동 기반 판정 |
| `source` | 최종 판정 출처/혼합 방식 |
| `impressions`, `clicks`, `carts`, `purchases`, `ctr` | 판단 근거 행동 통계 |

### `ecom_ltr_metrics`

| 필드 | 의미 |
|---|---|
| `baseline.ndcg@10` | BM25 nDCG@10 |
| `ltr.ndcg@10` | LTR rescore nDCG@10 |
| `baseline.recall@10`, `ltr.recall@10` | 판정된 관련 문서 Recall@10 |
| `lift_pct.ndcg@10`, `lift_pct.recall@10` | 기준 대비 향상률 |
| `promoted` | 모델 승격 여부 |
| `model_name`, `run_id`, `timestamp` | 모델·실행 추적 정보 |

## 6. 점검 쿼리

### 매핑 확인

```json
GET ubi_queries_ecom/_mapping
GET ubi_events_ecom/_mapping
```

### 행동 분포

```json
GET ubi_events_ecom/_search
{
  "size": 0,
  "aggs": {
    "actions": {
      "terms": { "field": "action_name", "size": 10 }
    }
  }
}
```

### 인기 검색어

```json
GET ubi_queries_ecom/_search
{
  "size": 0,
  "aggs": {
    "top_queries": {
      "terms": { "field": "user_query.keyword", "size": 20 }
    }
  }
}
```

### 위치별 클릭 분포

```json
GET ubi_events_ecom/_search
{
  "size": 0,
  "query": { "term": { "action_name": "click" } },
  "aggs": {
    "click_position": {
      "terms": {
        "field": "event_attributes.position.ordinal",
        "size": 20,
        "order": { "_key": "asc" }
      }
    }
  }
}
```

## 7. 데이터 품질 체크리스트

- `query_id`가 검색마다 고유한가
- Event의 `query_id`가 Query 문서에 존재하는가
- `query_response_hit_ids`의 순서가 실제 노출 순서와 같은가
- `object_id`가 `ecom_products`의 문서 `_id`와 일치하는가
- `position.ordinal`의 0-base/1-base 규칙이 모든 클라이언트에서 같은가
- 중복 전송에 대한 idempotency 또는 Event ID가 있는가
- 봇, 내부 사용자, 테스트 트래픽을 구분할 수 있는가
- `client_id`, `session_id`, 검색어에 개인정보가 포함되지 않도록 가명화·필터링하는가
- CTR을 계산할 때 Query hit 기반 노출과 impression 이벤트를 이중 집계하지 않는가
- 시간대, 지연 도착, 데이터 보존 기간이 분석 요구와 일치하는가
