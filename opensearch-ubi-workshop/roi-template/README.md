# 검색 품질 ROI 산출 템플릿

## 제공 파일

| 파일 | 용도 |
|---|---|
| [`roi-calculator.html`](roi-calculator.html) | 브라우저에서 실행하는 ROI 계산기, 의사결정 요약, CSV 내보내기 |
| [`experiment-result-template.csv`](experiment-result-template.csv) | A/B 실험 원시 집계 입력 표준 |
| [`roi-input-template.csv`](roi-input-template.csv) | 재무·비용 가정 공유용 입력 표준 |
| [`roi-decision-brief-template.md`](roi-decision-brief-template.md) | 엔지니어링 리드/PM 승인 문서 템플릿 |

## 사용 방법

1. `roi-calculator.html`을 Chrome, Edge, Safari에서 엽니다. 서버가 필요 없습니다.
2. 동일 기간과 동일 트래픽 배정 규칙으로 측정한 Baseline/Candidate 검색 노출, 클릭, 주문을 입력합니다.
3. 월간 검색량, 평균 주문 금액, 매출총이익률, 구현·운영 비용을 입력합니다.
4. nDCG는 품질 gate와 진단 정보로 기록합니다. 매출 계산식에는 직접 곱하지 않습니다.
5. 통계 신호, 월 순효과, 회수기간, 분석 기간 ROI를 확인합니다.
6. **CSV 내보내기**와 **인쇄/PDF**를 사용해 의사결정 자료를 보관합니다.

## 계산 원칙

```text
검색당 주문율 = orders / search impressions
월 증분 주문 = 월 검색량 × (Candidate 주문율 - Baseline 주문율)
월 증분 매출 = 월 증분 주문 × 평균 주문 금액
월 증분 매출총이익 = 월 증분 매출 × 매출총이익률
월 생산성 절감 = 절감 시간 × 시간당 loaded cost
조정 월 효익 = (증분 매출총이익 + 생산성 절감) × rollout × confidence haircut
총 비용 = 일회성 구현 비용 + 월 운영비 × 분석 개월
ROI = (분석 기간 총 효익 - 총 비용) / 총 비용
```

## 왜 nDCG를 매출로 직접 환산하지 않는가

nDCG는 Judgment를 기준으로 결과 순서가 얼마나 좋은지 보여 주지만, 사용자의 클릭·구매 반응과 선형 관계라는 보장은 없습니다. 따라서 이 템플릿은 nDCG를 릴리스 gate로 보여 주되, 재무 효과는 온라인 실험의 검색당 주문율 차이로 계산합니다.

## 의사결정 권장 기준

- 품질: nDCG와 주요 Query slice가 악화되지 않음
- 사용자: 검색당 주문율 또는 조직이 선택한 북극성 지표 개선
- 통계: 충분한 샘플과 사전 정의된 실험 기간을 충족
- 안정성: P95 검색 지연, 오류율, zero-result rate가 guardrail 내
- 경제성: 보수적 confidence haircut 적용 후 ROI와 회수기간이 기준 충족
- 운영성: 모니터링, rollback, 모델/검색 설정 버전 추적 가능

계산기의 p-value는 빠른 검토용 정규 근사치입니다. 실험 중간에 반복 확인했거나 세그먼트를 많이 비교했다면 전문 실험 플랫폼 또는 통계 검토가 필요합니다.
