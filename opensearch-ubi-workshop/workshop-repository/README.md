# OpenSearch UBI → Search Relevance Workbench → LTR 워크샵

Amazon OpenSearch Service에서 검색 행동 데이터를 UBI 형식으로 수집하고, Search Relevance Workbench로 검색 품질을 비교하고, 행동·LLM 판정을 이용해 Learning to Rank 모델을 학습·평가하는 참여자용 샘플입니다.

## 빠른 시작

- 처음 배포하는 참여자: [`SETUP_GUIDE.md`](SETUP_GUIDE.md)
- 실습 노트북과 실행 스크립트: [`hands-on/`](hands-on/)
- 배포용 CloudFormation: [`infrastructure/`](infrastructure/)
- CDK, Lambda, React 전체 소스: [`source/`](source/)

## 워크샵 흐름

```text
VoltMall 검색/행동
  → ubi_queries_ecom + ubi_events_ecom
  → Query Set + Judgment + Search Configuration + Experiment
  → UBI 집계와 LLM 판정
  → LTR 피처 생성 및 LambdaMART 학습
  → BM25 vs LTR nDCG@10 / Recall@10 평가
  → 개선된 모델만 스토어프론트에 승격
```

## 폴더 설명

| 폴더 | 내용 |
|---|---|
| `infrastructure/` | 공개 사전 빌드 에셋을 사용하는 단일 코어 스택과 선택형 devbox 스택 |
| `hands-on/` | code-server 또는 로컬 환경에서 실행할 노트북, UBI 이벤트 생성기, 파이프라인 실행기 |
| `source/` | 원본 CDK 스택, Lambda 함수, 데이터 생성 도구, React 스토어프론트 소스 |

## 배포 경로 선택

1. **AWS 주최 이벤트**: Workshop Studio가 리소스를 자동 프로비저닝한 경우 진행자 안내에 따라 검증 단계부터 시작합니다.
2. **개인 AWS 계정**: `SETUP_GUIDE.md`의 Launch Stack 경로를 권장합니다. 소스 빌드가 필요 없습니다.
3. **고급 사용자**: `source/`를 검토·수정한 후 자체 에셋 버킷에 빌드 산출물을 올려 배포합니다. 공개 에셋과 수정 소스를 혼합하지 마세요.

## 프로덕션 사용 전 필수 변경

- OpenSearch 도메인을 VPC에 배치하고 네트워크 접근을 제한합니다.
- 임시 FGAC 관리자 계정과 고정 워크샵 암호를 제거하고 SSO/IAM 기반 접근으로 전환합니다.
- 워크샵용 IAM 권한을 최소 권한으로 축소합니다.
- UBI의 `client_id`, `session_id`를 가명화하고 개인정보·검색어 보존 정책을 수립합니다.
- A/B 실험, 모델 롤백, 데이터 품질, 비용, 알람에 대한 운영 절차를 추가합니다.
