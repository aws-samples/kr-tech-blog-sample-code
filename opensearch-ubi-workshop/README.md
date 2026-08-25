# OpenSearch UBI 검색 관련성 워크샵 참여자 Artifact

이 폴더는 워크샵 종료 후 참여자가 실습을 재현하고, UBI 데이터를 해석하고, 검색 품질을 운영 지표와 비즈니스 효과로 연결할 수 있도록 정리한 전달 패키지입니다.

## 포함 산출물

| 산출물 | 위치 | 용도 |
|---|---|---|
| 워크샵 GitHub 레포 + 셋업 가이드 | [`workshop-repository/`](workshop-repository/) | 개인 AWS 계정 배포, 실습 파일, 전체 CDK/Lambda/웹앱 소스 |
| UBI 스키마 레퍼런스 | [`ubi-schema-reference/`](ubi-schema-reference/) | Query/Event 스키마, 조인 키, 파생 지표, 데이터 품질 점검 |
| nDCG/CTR 대시보드 템플릿 | [`dashboards/`](dashboards/) | OpenSearch Dashboards Saved Objects 임포트 파일과 운영 가이드 |
| 검색 품질 ROI 산출 템플릿 | [`roi-template/`](roi-template/) | A/B 실험 결과를 매출·마진·비용·회수기간으로 환산 |

## 권장 사용 순서

1. [`workshop-repository/SETUP_GUIDE.md`](workshop-repository/SETUP_GUIDE.md)로 환경을 배포하고 검증합니다.
2. [`workshop-repository/hands-on/`](workshop-repository/hands-on/)의 노트북과 스크립트로 UBI → Judgment → LTR 파이프라인을 실행합니다.
3. [`ubi-schema-reference/README.md`](ubi-schema-reference/README.md)로 수집 필드와 CTR 계산 기준을 확인합니다.
4. [`dashboards/README.md`](dashboards/README.md)에 따라 대시보드를 임포트하고 nDCG/CTR을 관찰합니다.
5. [`roi-template/roi-calculator.html`](roi-template/roi-calculator.html)을 열어 실험 결과와 비용을 입력하고 의사결정 자료를 내보냅니다.

## 중요한 경계

- 이 패키지는 교육용 샘플입니다. 공개 엔드포인트, 임시 관리자 계정, 넓은 워크샵 권한을 그대로 프로덕션에 사용하지 마세요.
- nDCG 상승은 검색 순위 품질 신호이지 매출이 아닙니다. ROI는 반드시 통제된 A/B 실험에서 관측한 주문율 또는 CTR/전환율 변화로 계산하세요.
- 이 워크샵의 LTR 파이프라인은 노출 수를 `ubi_queries_ecom.query_response_hit_ids`에서 계산합니다. `impression` 이벤트는 대시보드 관찰용이며 LTR 집계의 분모가 아닙니다.
- 개인 AWS 계정에서 실습했다면 종료 후 코어와 devbox CloudFormation 스택 및 잔여 S3 데이터를 삭제하세요.

## 라이선스

이 폴더는 상위 `aws-samples/kr-tech-blog-sample-code` 저장소의 라이선스를 따릅니다.
