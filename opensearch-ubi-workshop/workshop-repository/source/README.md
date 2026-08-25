# VoltMall — OpenSearch UBI → LTR 엔드투엔드 샘플

기존 Amazon OpenSearch Service 도메인(OpenSearch 3.5, FGAC)에 연결하는
전자제품 이커머스 검색 랭킹 개선 참조 구현입니다.

> 참여자에게 권장하는 기본 배포 경로는 상위 `../infrastructure/workshop.yaml`입니다.
> 이 `source/` 경로는 기존 도메인, FGAC 역할, ml-commons 모델을 직접 연결하려는
> 고급 사용자가 아키텍처를 검토하거나 확장할 때 사용합니다.

사용자 행동(검색/노출/클릭/장바구니/구매)을 **UBI(User Behavior Insights)** 스키마로 수집하고
**OSI(OpenSearch Ingestion)** 로 실시간 색인 → **LLM-as-a-Judge**(OpenSearch에 등록된
Claude 모델)로 판단 데이터셋 생성 → **LTR 피처셋 + 피처 로깅** → **XGBoost LambdaMART**
학습 → **nDCG@10 / Recall@10** 평가 및 모델 승격까지 전 과정을 자동화합니다.

## 아키텍처

```
                 ┌────────────────────┐
   쇼핑객 ──────▶│ CloudFront (SPA)   │── /api/* ──▶ API Gateway ──▶ Lambda (FastAPI)
                 │  React VoltMall    │                                │        │
                 └────────────────────┘                                │        │ 검색 (BM25 / sltr 재랭킹)
                        ▲  UBI 이벤트(클릭/장바구니/구매)               │        ▼
                        └──────────────────────────────────────────────┤   ┌────────────────────┐
                                                     UBI query/event 전송   │ OpenSearch          │
                                                     (SigV4, osis)     │   │  기존 OpenSearch    │
                                                                       ▼   │  - ecom_products    │
                 ┌───────────────────────────┐   ubi_queries_ecom          │  - ubi_*_ecom       │
                 │ OSI: ecom-ubi-pipeline    │──▶ ubi_events_ecom     ────▶│  - ecom_judgments   │
                 │ http /ecom-ubi, 라우팅     │──▶ S3 아카이브/DLQ          │  - ecom_ltr_metrics │
                 └───────────────────────────┘                             │  - .ltrstore (LTR)  │
                                                                           │  - ml-commons Claude│
   Step Functions: ecom-ubi-ltr-pipeline  (Kubeflow 스타일 ML 파이프라인)    └────────────────────┘
   ┌──────────┐  ┌────────────┐  ┌──────────────┐  ┌────────────┐  ┌────────────┐
   │ Extract  │─▶│ Judgments  │─▶│ BuildFeatures │─▶│ Train      │─▶│ Evaluate   │
   │ UBI 집계  │  │ LLM 판정    │  │ 피처셋+로깅    │  │ XGBoost    │  │ nDCG/Recall│
   │ CTR 반영  │  │ (0~3 등급)  │  │ RankLib 생성  │  │ LambdaMART │  │ 모델 승격   │
   └──────────┘  └────────────┘  └──────────────┘  └────────────┘  └────────────┘
        │              │                │                │               │
        └──────────────┴────── S3: ecom-ubi-data-* (pipeline/<run_id>/…) ┘
```

## 데이터 흐름

1. **수집** — 프런트엔드 `ubi.js`가 impression/click/view/add_to_cart/purchase 이벤트를
   배치 전송. 검색 시 백엔드가 UBI query 레코드(`query_id`, `query_response_hit_ids` 포함)를
   서버측에서 기록. 모두 OSI HTTP 소스(`/ecom-ubi`)로 SigV4 전송되어
   `ubi_queries_ecom`/`ubi_events_ecom`에 실시간 색인 + S3 아카이브.
2. **Extract** — UBI 로그를 (쿼리, 상품) 단위로 집계(노출/클릭/장바구니/구매/CTR),
   상품 문서에 `ctr`·`cart_rate`·`popularity`(행동 기반) 필드 업데이트, 암묵적 판정
   (구매=3, 장바구니=2, 클릭≥2=2, 클릭1=1, 노출≥3&무클릭=0) 생성.
3. **Judgments (LLM-as-a-Judge)** — 상위 쿼리별 후보 상품(BM25 top-k + 행동 발생 상품)을
   OpenSearch에 **이미 등록된 Bedrock Claude 모델**(ml-commons `_predict`)로 0~3 등급 판정.
   LLM 등급 우선 + 암묵 등급 보완 → `ecom_judgments` 색인 & S3 저장.
4. **BuildFeatures** — LTR 스토어(기본 스토어)에 13개 피처(`name_bm25`, `name_phrase`,
   `series/brand/category/description_bm25`, `overall_bm25`, `price_log`, `rating`,
   `review_count_log`, `popularity`, `ctr`, `cart_rate`)로 `ecom_features` **피처셋 생성**,
   `sltr` + `ltr_log` 피처 로깅으로 (쿼리,상품) 피처값 추출 → **RankLib 파일** 생성(S3).
   학습 피처 == 서빙 피처 (skew 없음).
5. **Train** — XGBoost `rank:ndcg`(LambdaMART 계열) 학습, 쿼리 단위 80/20 분할,
   early stopping, 오프라인 nDCG@10/Recall@10 산출 → `model/xgboost+json`으로 LTR 플러그인 업로드.
6. **Evaluate** — 검증 쿼리를 실제 인덱스에 **베이스라인 BM25 vs sltr 재랭킹**으로 각각 실행,
   판단 데이터셋 기준 nDCG@10/Recall@10 비교. 개선 시 SSM `/ecom-ubi/ltr/model-name` 갱신
   (스토어의 `LTR ON` 토글이 이 모델 사용) + `ecom_ltr_metrics` 색인.

## 배포

다음 값은 배포할 계정과 기존 도메인에서 직접 확인해야 합니다.

```bash
export AWS_REGION=ap-northeast-2
export OPENSEARCH_ENDPOINT='<domain endpoint host>'
export OPENSEARCH_DOMAIN_ARN='<domain ARN>'
export SHARED_OPENSEARCH_ROLE_ARN='<FGAC backend role로 매핑된 IAM role ARN>'
export JUDGE_MODEL_ID='<배포된 ml-commons judge model ID>'

./deploy.sh
```

`deploy.sh`는 기존 역할의 trust policy에 Lambda service principal statement를
추가합니다. 실행 전 변경 내용을 검토하고 별도의 실습 역할을 사용하세요.

배포 출력(`outputs.json`)의 `StoreUrl`(CloudFront)로 접속하면 쇼핑몰이 열립니다.
검색/클릭/장바구니/구매 시 우하단 **📡 UBI 패널**에서 실시간 이벤트를 확인할 수 있습니다.

### 트래픽 생성 + 파이프라인 실행

```bash
# 1) 시뮬레이션 트래픽 (실제 API 경로 그대로 사용)
python3 scripts/simulate_traffic.py --base-url https://<StoreUrl> --sessions 300

# 2) OSI 색인 대기 후 ML 파이프라인 실행 (Step Functions)
scripts/run_pipeline.sh
# 옵션: scripts/run_pipeline.sh '{"top_n_queries": 60, "max_queries": 40}'
```

완료 후 `ecom_ltr_metrics` 인덱스와 `s3://ecom-ubi-data-*/pipeline/<run_id>/metrics.json`에서
baseline vs LTR 지표를 확인하고, 스토어에서 **LTR ON** 토글로 재랭킹 결과를 비교하세요.

## 기존 도메인 연결 전제

| 항목 | 내용 |
|------|------|
| FGAC | `SHARED_OPENSEARCH_ROLE_ARN` 역할이 대상 도메인의 필요한 backend role에 이미 매핑되어 있어야 합니다. `scripts/00-prepare-iam.sh`는 기존 trust statement를 보존하면서 Lambda assume-role statement를 추가합니다. |
| LLM Judge | `JUDGE_MODEL_ID`로 전달한 ml-commons 모델이 배포 상태이고 `user_prompt` 기반 판정 계약을 지원해야 합니다. |
| LTR 스토어 | 전용 스토어 `ecom`(`.ltrstore_ecom`) 사용 — 공유 클러스터의 기본 스토어와 격리 |
| LTR 적용 방식 | rescore 블렌드 `query_weight=1, rescore_query_weight=1.5` — 평가·서빙·워크숍 예제를 같은 값으로 통일 |
| 학습 설정 | XGBoost `rank:ndcg`, eta 0.08, depth 4, **고정 100라운드** — 검증 쿼리 수십 개 수준에서는 per-round early stopping이 노이즈로 2~4트리에서 조기 종료되어 비활성화 |
| 인덱스 | `ecom_products`(450개 전자제품, nori 한국어 분석기), `ubi_queries_ecom`, `ubi_events_ecom`, `ecom_judgments`, `ecom_ltr_metrics` |

## 실측 결과 (2026-07-03, run-20260703-021019)

시뮬레이션 트래픽 2회(약 1,200 검색 / 3,500 클릭 / 975 장바구니 / 363 구매, 고유 쿼리 63개),
판단 데이터셋 1,241건(LLM+행동 혼합) 기준 검증 쿼리 11개 라이브 평가:

| 지표 | 베이스라인 BM25 | LTR 재랭킹 | 개선 |
|------|-----------------|-----------|------|
| nDCG@10 | 0.8533 | **0.8949** | **+4.9%** |
| Recall@10 | 0.8118 | **0.8524** | **+5.0%** |

정성 예시 — `"무선 이어폰"` 검색 top5:

| LTR OFF (BM25) | LTR ON (승격 모델) |
|----------------|-------------------|
| 1. [청소기] 샤오미 무선청소기 G11 | 1. [이어폰/헤드폰] 소니 링크버즈 S |
| 2. [청소기] 샤오미 무선청소기 G11 | 2. [이어폰/헤드폰] 갤럭시 버즈3 |
| 3. [청소기] 샤오미 무선청소기 G11 | 3. [이어폰/헤드폰] 에어팟 맥스 |
| 4. [청소기] 샤오미 무선청소기 G11 | 4. [이어폰/헤드폰] 젠하이저 모멘텀 4 |
| 5. [청소기] 로보락 Q레보 | 5. [이어폰/헤드폰] QCY 멜로버즈 프로 |

"무선"이 청소기·마우스에 광범위하게 매칭되는 어휘 한계를, UBI 클릭 행동 + LLM 판정으로
학습한 모델이 카테고리 시그널(ctr/cart_rate 포함 13개 피처)로 교정한 사례입니다.

## OpenSearch Dashboards

`dashboards/voltmall-ubi-ltr.ndjson`에 인덱스 패턴 5개 + 시각화 8개 + 대시보드 1개가 들어 있습니다.
`python3 scripts/build_dashboard.py`로 재생성하며, 아래 중 하나로 임포트합니다.

- **UI**: Dashboards → Stack Management → Saved Objects → Import
- **API(SigV4)**: `POST /_dashboards/api/saved_objects/_import?overwrite=true` (multipart `file=`, 헤더 `osd-xsrf: true`)

대시보드 패널: 총 검색수 / LTR vs BM25 nDCG·향상% / 액션 분포(도넛) / 행동 이벤트 추이(스택) /
인기 검색어 Top20 / 클릭 상위 상품(CTR·장바구니율) / 카테고리별 평균 CTR / 판정 등급 분포(source별).
데이터 소스 인덱스는 `ubi_queries_ecom`, `ubi_events_ecom`, `ecom_products`, `ecom_judgments`, `ecom_ltr_metrics`.
> 참고: FGAC라 브라우저 조회는 내부 마스터 유저 로그인이 필요합니다(임포트는 로컬 IAM SigV4로 수행 가능).

## 네이티브 Search Relevance Workbench와의 관계

이 도메인은 `search-relevance` 플러그인(Workbench)이 켜져 있어 **Query Sets / Judgments /
Search Configurations / Experiments** API를 쓸 수 있습니다. 이 데모가 커스텀 Lambda로 구현한 이유와 경계:

| 단계 | 네이티브 Workbench | 이 데모(커스텀) |
|---|---|---|
| 쿼리셋 | Query Sets (pptss 샘플링은 표준 `ubi_queries` 대상) | Extract가 `ubi_queries_ecom`에서 상위 쿼리 집계 |
| 판정 | UBI(COEC)·LLM·Import Judgment | LLM(Claude)+암묵(행동) 혼합 → `ecom_judgments` |
| 평가 | Experiments (nDCG 등) | Evaluate가 라이브 BM25 vs LTR nDCG/Recall |
| **피처로깅·모델학습·서빙** | **없음** | **`sltr`+`ltr_log` → XGBoost LambdaMART → LTR 업로드/재랭킹** |

핵심: Workbench는 쿼리셋·판정·**평가**까지만 다루고 **LTR 모델 학습/서빙은 하지 않습니다** — 그게 이 파이프라인의
본체(4·5단계)입니다. 또한 실측 결과, 이 클러스터에서 네이티브 UBI(COEC) 판정은 impression 이벤트가
쿼리당 1건 집계형이라 순위별 기대클릭 분모가 없어 0건을 반환했고, 네이티브 LLM 판정도 일반 등록된 Claude
커넥터의 입출력이 Workbench 판정 계약과 달라 0건이었습니다(별도 세팅 필요). 반면 이미 클러스터에 존재하는
`IMPORT_JUDGMENT`("Claude Sonnet 4.5 Judgments")처럼, **외부에서 판정을 계산해 Import**하는 패턴이 실무적으로
흔하며 이 데모의 `generate_judgments` Lambda가 바로 그 역할을 합니다. 원하면 `ecom_judgments`를
Workbench로 Import해 Experiment nDCG 스코어보드로도 쓸 수 있습니다.

## 비용 주의

- **OSI 파이프라인**: 최소 1 OCU 상시 과금(월 ~$170). 데모 후 `aws osis stop-pipeline --pipeline-name ecom-ubi-pipeline`으로 중지 가능
- CloudFront/Lambda/API GW/S3/Step Functions: 사용량 기반(데모 수준 ~$1-5)
- Bedrock Claude: 파이프라인 실행당 판정 쿼리 수 × 배치 수 (기본 설정 ~120 호출, ~$1-3)

## 정리(청소)

```bash
npx cdk destroy --all

export OPENSEARCH_ENDPOINT='<domain endpoint host>'
export CONFIRM_DELETE=DELETE_ECOM_UBI
export SHARED_OPENSEARCH_ROLE_NAME='<shared role name>'
export REVERT_SHARED_ROLE_TRUST=true
bash scripts/99-cleanup.sh
```

`99-cleanup.sh`는 대상 도메인의 `ecom_*`, `ubi_*_ecom`, 전용 LTR 모델과
피처셋을 삭제합니다. 엔드포인트와 삭제 확인 문자열을 검토한 뒤 실행하세요.

## Kubeflow 등 외부 ML 파이프라인으로 확장

Step Functions 파이프라인의 각 단계는 S3 아티팩트(`pipeline/<run_id>/…`)로 느슨하게 결합되어
있어 그대로 Kubeflow Pipelines/SageMaker Pipelines 컴포넌트로 치환할 수 있습니다:

1. `training.ranklib.txt`(피처 로깅 산출물)를 입력으로 받는 학습 컴포넌트 작성
   (`lambda/functions/train_ltr_model/train_ltr_model.py`의 `parse_ranklib`/학습 로직 재사용)
2. 학습된 모델을 `POST /_ltr/_featureset/ecom_features/_createmodel`로 업로드
3. `evaluate_model.py` 로직으로 온라인 A/B 지표 산출 → 개선 시 SSM 파라미터 갱신

RankLib 파일은 표준 포맷이므로 RankLib(자바), LightGBM(`lambdarank`) 등으로도 학습 가능합니다.
