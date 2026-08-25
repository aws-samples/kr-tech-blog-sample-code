# ml-commons 모델 테스트 쿼리

배포된 도메인의 Bedrock 커넥터 모델을 검증하는 쿼리 모음입니다. CloudFormation 스택 `ubi-workshop`의 Outputs에서 다음 값을 먼저 확인합니다.

- `DashboardsURL`
- `DashboardsUsername`, `DashboardsPassword`
- `OpenSearchDomainEndpoint`
- `JudgeModelId`
- `EmbedModelId`

아래 `<JUDGE_MODEL_ID>`, `<EMBED_MODEL_ID>`는 자신의 출력값으로 바꿉니다.

## 0. 등록된 모델 목록과 상태

```json
POST /_plugins/_ml/models/_search
{
  "size": 10,
  "_source": ["name", "model_state", "algorithm"],
  "query": { "exists": { "field": "connector_id" } }
}
```

## 1. Claude Sonnet 판정 모델

```json
POST /_plugins/_ml/models/<JUDGE_MODEL_ID>/_predict
{
  "parameters": {
    "user_prompt": "딱 OK 라고만 답하세요."
  }
}
```

응답의 `inference_results[0].output[0].dataAsMap.output.message.content[0].text`를 확인합니다.

## 2. 검색 관련성 판정 프롬프트

```json
POST /_plugins/_ml/models/<JUDGE_MODEL_ID>/_predict
{
  "parameters": {
    "user_prompt": "당신은 한국 전자제품 이커머스 검색 품질 평가 전문가입니다. 검색어 \"무선 이어폰\"에 대해 아래 상품들의 관련성을 0~3점으로 평가하고 JSON 배열로만 답하세요. 형식: [{\"id\":\"<상품ID>\",\"rating\":<0-3>,\"reason\":\"<이유>\"}]\n상품: - id: A | 소니 링크버즈 S 무선 이어폰 - id: B | 샤오미 무선청소기 G11"
  }
}
```

## 3. Titan v2 임베딩 모델

```json
POST /_plugins/_ml/models/<EMBED_MODEL_ID>/_predict
{
  "parameters": {
    "inputText": "무선 이어폰 노이즈 캔슬링"
  }
}
```

응답의 `inference_results[0].output[0].data`에 임베딩 벡터가 들어옵니다.

## 4. 상품과 UBI 데이터 확인

```json
POST /ecom_products/_search
{
  "size": 5,
  "_source": ["name", "category", "brand", "price"],
  "query": {
    "multi_match": {
      "query": "게이밍 노트북",
      "fields": ["name^3", "series^2", "brand^1.5", "category^1.5", "description"],
      "type": "best_fields"
    }
  }
}
```

```json
GET ubi_queries_ecom/_count
GET ubi_events_ecom/_count
GET ubi_queries_ecom/_search
```

## 5. 로컬 터미널에서 curl

```bash
export OPENSEARCH_ENDPOINT='<OpenSearchDomainEndpoint>'
export JUDGE_MODEL_ID='<JudgeModelId>'
export EMBED_MODEL_ID='<EmbedModelId>'
export DASHBOARDS_USER='admin'
read -s -p 'Dashboards password: ' DASHBOARDS_PASSWORD
echo

curl --fail-with-body \
  -u "${DASHBOARDS_USER}:${DASHBOARDS_PASSWORD}" \
  -H 'Content-Type: application/json' \
  -X POST "https://${OPENSEARCH_ENDPOINT}/_plugins/_ml/models/${JUDGE_MODEL_ID}/_predict" \
  -d '{"parameters":{"user_prompt":"딱 OK 라고만 답하세요."}}'

curl --fail-with-body \
  -u "${DASHBOARDS_USER}:${DASHBOARDS_PASSWORD}" \
  -H 'Content-Type: application/json' \
  -X POST "https://${OPENSEARCH_ENDPOINT}/_plugins/_ml/models/${EMBED_MODEL_ID}/_predict" \
  -d '{"parameters":{"inputText":"무선 이어폰"}}'
```
