# nDCG / CTR OpenSearch Dashboards 템플릿

## 파일

- [`voltmall-ubi-ltr.ndjson`](voltmall-ubi-ltr.ndjson): OpenSearch Dashboards Saved Objects

포함 객체:

- 인덱스 패턴 5개
- 시각화 8개
- 대시보드 1개: `VoltMall · UBI → LTR 대시보드`

## 데이터 소스

| 인덱스 패턴 | 대시보드 용도 |
|---|---|
| `ubi_queries_ecom*` | 총 검색 수, 인기 검색어 |
| `ubi_events_ecom*` | action 분포, 이벤트 시계열 |
| `ecom_products*` | 클릭 수, CTR, 장바구니율, 카테고리별 CTR |
| `ecom_judgments*` | 판정 등급과 source 분포 |
| `ecom_ltr_metrics*` | BM25/LTR nDCG@10과 향상률 |

## 임포트 방법

### UI

1. OpenSearch Dashboards에 로그인합니다.
2. **Stack Management → Saved Objects**로 이동합니다.
3. **Import**를 선택합니다.
4. `voltmall-ubi-ltr.ndjson`을 업로드합니다.
5. 충돌 시 기존 객체 덮어쓰기를 선택합니다.

### API

`DASHBOARDS_URL`은 `https://.../_dashboards`처럼 Dashboards base path까지 포함해야 합니다.

```bash
export DASHBOARDS_URL='https://your-domain.ap-northeast-2.es.amazonaws.com/_dashboards'
export DASHBOARDS_USER='admin'
read -s -p 'Dashboards password: ' DASHBOARDS_PASSWORD
echo

curl --fail-with-body \
  -u "${DASHBOARDS_USER}:${DASHBOARDS_PASSWORD}" \
  -X POST \
  "${DASHBOARDS_URL}/api/saved_objects/_import?overwrite=true" \
  -H 'osd-xsrf: true' \
  --form file=@voltmall-ubi-ltr.ndjson
```

## 패널 해석

| 패널 | 읽는 방법 |
|---|---|
| 총 검색 수 | UBI Query 문서 수. 고유 사용자 수가 아님 |
| LTR vs BM25 | 최신 `ecom_ltr_metrics` 문서의 nDCG@10과 향상률 |
| UBI 액션 분포 | `impression`, `click`, `add_to_cart`, `purchase` 이벤트 수 |
| 행동 이벤트 추이 | 시간별 이벤트 수와 action 구성 |
| 인기 검색어 | `user_query.keyword` 빈도 |
| 클릭 상위 상품 | `ecom_products.click_count`, `ctr`, `cart_rate` |
| 카테고리별 평균 CTR | 상품 문서에 역기록된 CTR의 카테고리 평균 |
| 판정 등급 분포 | 최종 grade와 판정 source별 문서 수 |

## 지표 경계

- nDCG@10은 판정 목록을 기준으로 상위 결과 순서의 품질을 평가합니다. 판정 Coverage와 편향을 함께 확인하세요.
- 대시보드 CTR은 `ubi_events_ecom`에서 즉석 계산하지 않습니다. LTR 파이프라인이 Query hit 배열과 클릭 이벤트를 집계해 `ecom_products.ctr`에 기록한 값을 표시합니다.
- 카테고리별 평균 CTR은 상품별 CTR의 단순 평균입니다. 트래픽 가중 CTR이 필요하면 Query/Event 원천 데이터로 별도 집계하세요.
- `impression` 이벤트 수와 LTR용 노출 분모는 동일하지 않을 수 있습니다. 현재 LTR 집계의 노출은 `query_response_hit_ids` 기준입니다.
- 오프라인 nDCG 상승만으로 모델을 전면 배포하지 마세요. 온라인 A/B 실험의 주문율, 오류율, 지연 시간, 이탈률을 함께 확인합니다.

## 문제 해결

### `Could not locate that index-pattern-field`

1. 대상 인덱스와 매핑이 생성되었는지 확인합니다.
2. Index Pattern에서 필드 목록을 새로고침합니다.
3. `ecom_ltr_metrics`가 비어 있으면 LTR 파이프라인을 한 번 실행합니다.

### 패널이 비어 있음

```json
GET _cat/indices/ubi_*_ecom,ecom_*?v&h=index,docs.count
```

시간 필터를 넓히고 `@timestamp`가 올바른 날짜 형식인지 확인합니다.

### nDCG는 보이지만 CTR이 0

`ExtractUbiData` 이후 상품 통계가 갱신되었는지 확인합니다.

```json
GET ecom_products/_search
{
  "size": 5,
  "sort": [{ "click_count": "desc" }],
  "_source": ["name", "click_count", "ctr", "cart_rate"]
}
```

## 공식 참고

- [OpenSearch Dashboards dashboard 생성](https://docs.opensearch.org/latest/dashboards/dashboard/dash-tutorial/)
- [Search Relevance Workbench 검색 품질 평가](https://docs.opensearch.org/latest/search-plugins/search-relevance/evaluate-search-quality/)
