# 워크샵 셋업 가이드

## 1. 배포 전 확인

### 공통

- 코어 인프라 리전: `ap-northeast-2`
- 기본 스택 이름: `ubi-workshop`
- 선택형 devbox 스택 이름: `ubi-workshop-devbox`
- 배포 시간 예상: 코어 약 20~30분, 삭제 약 15~25분
- CloudFormation이 사용자 지정 이름의 IAM 리소스를 만들 수 있도록 `CAPABILITY_NAMED_IAM` 승인이 필요합니다.

### Amazon Bedrock 모델 액세스

현재 코어 템플릿의 `BedrockRegion` 기본값은 `us-west-2`입니다. 다음 모델을 사용할 수 있어야 합니다.

- `amazon.titan-embed-text-v2:0`
- `us.anthropic.claude-sonnet-4-5-20250929-v1:0` 추론 프로파일

계정 정책이나 이벤트 환경이 `us-west-2`를 허용하지 않으면 템플릿의 허용 리전과 모델 ID를 진행자와 먼저 확인하세요.

## 2. 개인 AWS 계정 빠른 배포

### 코어 스택

[Launch Stack — `ubi-workshop`](https://ap-northeast-2.console.aws.amazon.com/cloudformation/home?region=ap-northeast-2#/stacks/create/review?templateURL=https://ws-assets-prod-iad-r-icn-ced060f0d38bc0b0.s3.ap-northeast-2.amazonaws.com/84a951c0-83b7-4d48-accc-eb318fc538ba/templates/workshop.yaml&stackName=ubi-workshop&param_AssetsBucketName=ws-assets-prod-iad-r-icn-ced060f0d38bc0b0&param_AssetsPrefix=84a951c0-83b7-4d48-accc-eb318fc538ba/assets/)

1. 리전이 서울 `ap-northeast-2`인지 확인합니다.
2. 스택 이름 `ubi-workshop`과 미리 입력된 `AssetsBucketName`, `AssetsPrefix`를 확인합니다.
3. `MasterUserPassword`를 이 실습에서만 사용할 강한 임시 암호로 덮어씁니다. 공개 Launch Stack 템플릿에 교육용 기본값이 보이더라도 그대로 사용하지 마세요.
4. 나머지 교육용 기본 파라미터를 검토합니다.
5. IAM 리소스 생성 승인 체크박스를 선택합니다.
6. 스택을 생성하고 `CREATE_COMPLETE`를 기다립니다.

### 선택형 code-server devbox

코어 스택이 완료된 뒤 배포합니다.

[Launch Stack — `ubi-workshop-devbox`](https://ap-northeast-2.console.aws.amazon.com/cloudformation/home?region=ap-northeast-2#/stacks/create/review?templateURL=https://ws-assets-prod-iad-r-icn-ced060f0d38bc0b0.s3.ap-northeast-2.amazonaws.com/84a951c0-83b7-4d48-accc-eb318fc538ba/templates/workshop-devbox.yaml&stackName=ubi-workshop-devbox&param_AssetsBucketName=ws-assets-prod-iad-r-icn-ced060f0d38bc0b0)

devbox의 `MasterUserPassword`에는 코어 스택에 입력한 것과 같은 값을 사용합니다. devbox는 브라우저 기반 VS Code, Jupyter 노트북, AWS CLI 실행 환경을 제공합니다. 로컬 개발 환경이 이미 있으면 생략할 수 있습니다.

## 3. 출력값 확인

CloudFormation 콘솔에서 `ubi-workshop`의 **Outputs**를 확인합니다.

| 출력 | 사용 위치 |
|---|---|
| `StorefrontURL` | VoltMall 검색 및 행동 이벤트 생성 |
| `DashboardsURL` | OpenSearch Dashboards 접속 |
| `DashboardsUsername`, `DashboardsPassword` | 교육용 FGAC 로그인 |
| `OpenSearchDomainEndpoint` | Dev Tools, 스크립트, API 진단 |
| `StateMachineArn` | LTR Step Functions 파이프라인 실행 |
| `UbiIngestUrl` | OSIS UBI 수집 엔드포인트 |

devbox를 배포했다면 `ubi-workshop-devbox`의 `DevboxURL`과 `DevboxPasswordCLI`도 확인합니다.

## 4. 배포 검증

### 스토어프론트

1. `StorefrontURL`을 엽니다.
2. 상품 목록이 보이는지 확인합니다.
3. `무선 이어폰`, `게이밍 노트북`을 검색합니다.
4. 검색 결과를 클릭하고 장바구니와 구매 행동을 발생시킵니다.

### OpenSearch Dashboards Dev Tools

```json
GET _cluster/health
```

```json
GET _cat/indices/ecom_*,ubi_*_ecom?v&h=health,index,docs.count,store.size
```

```json
GET _plugins/_ml/models/_search
{
  "query": { "exists": { "field": "connector_id" } },
  "_source": ["name", "model_state"]
}
```

```json
GET _plugins/_search_relevance/query_sets
GET _plugins/_search_relevance/judgments
GET _plugins/_search_relevance/search_configurations
```

정상 기준:

- 클러스터 상태가 `green` 또는 `yellow`
- `ecom_products`, `ubi_queries_ecom`, `ubi_events_ecom`, `ecom_judgments`가 존재
- Titan 임베딩과 Claude 판정 커넥터가 `DEPLOYED`
- Query Set, Judgment, BM25/Semantic/Hybrid Search Configuration이 존재
- 배포 직후 Experiment가 비어 있어도 정상. 실습에서 직접 생성합니다.

## 5. 실습 실행

devbox의 워크스페이스 또는 이 저장소의 `hands-on/`을 사용합니다.

```bash
python3 generate_ubi_events.py
bash run_pipeline.sh
```

또는 `ltr_pipeline_workshop.ipynb`를 열어 단계별로 실행합니다.

파이프라인 순서:

```text
ExtractUbiData
  → GenerateJudgments
  → BuildFeatures
  → TrainModel
  → EvaluateModel
```

평가 결과는 `ecom_ltr_metrics`에 기록됩니다.

```json
GET ecom_ltr_metrics/_search
{
  "size": 5,
  "sort": [{ "timestamp": "desc" }]
}
```

## 6. 대시보드

배포 시 대시보드가 자동 임포트됩니다. 보이지 않으면 `../dashboards/README.md`를 따라 `voltmall-ubi-ltr.ndjson`을 수동 임포트합니다.

## 7. 종료 및 비용 정리

개인 계정에서는 devbox를 먼저 삭제하고 코어를 삭제합니다.

```bash
REGION=ap-northeast-2

aws cloudformation delete-stack \
  --region "$REGION" \
  --stack-name ubi-workshop-devbox

aws cloudformation wait stack-delete-complete \
  --region "$REGION" \
  --stack-name ubi-workshop-devbox
```

코어 스택의 S3 버킷이 비어 있지 않으면 먼저 비웁니다. 계정 ID를 자동으로 구합니다.

```bash
REGION=ap-northeast-2
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

for BUCKET in \
  "ubi-workshop-site-${REGION}-${ACCOUNT_ID}" \
  "ubi-workshop-data-${REGION}-${ACCOUNT_ID}" \
  "ubi-workshop-dlq-${REGION}-${ACCOUNT_ID}"; do
  aws s3 rm "s3://${BUCKET}" --recursive --region "$REGION" || true
done

aws cloudformation delete-stack \
  --region "$REGION" \
  --stack-name ubi-workshop

aws cloudformation wait stack-delete-complete \
  --region "$REGION" \
  --stack-name ubi-workshop
```

자체 빌드용 에셋 버킷을 별도로 만들었다면 그 버킷도 삭제합니다. 마지막으로 OpenSearch 도메인, OSIS 파이프라인, S3, Lambda, Step Functions, IAM 역할이 남아 있지 않은지 확인합니다.

## 8. 전체 소스에서 재빌드하는 고급 경로

`source/`는 CDK 원본과 빌드 스크립트를 포함하지만, 이 참여자 패키지는 `node_modules`, CDK 출력, Lambda ZIP, 프런트엔드 `dist`를 포함하지 않습니다.

```bash
cd source
npm ci
npm run build

cd webapp-frontend
npm ci
npm run build
```

이후 `source/scripts/build.sh`와 CDK 구성을 검토해 자체 에셋 버킷 및 계정 환경에 맞게 배포하세요. 소스를 수정했다면 공개 Workshop Studio 에셋을 그대로 참조하지 말고, 수정된 모든 Lambda·레이어·프런트엔드 파일을 자체 버킷에 일관되게 스테이징해야 합니다.
