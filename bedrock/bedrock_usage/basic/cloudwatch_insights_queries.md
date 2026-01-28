# CloudWatch Logs Insights 쿼리 모음

Bedrock Model Invocation Logs를 분석하기 위한 CloudWatch Logs Insights 쿼리 모음입니다.

## 📋 사전 준비

### 1. CloudWatch Logs 콘솔 접속
```
AWS Console → CloudWatch → Logs → Logs Insights
```

### 2. Log Group 선택
```
/aws/bedrock/modelinvocations
```

### 3. 시간 범위 설정
- 최근 1시간, 3시간, 1일 등 선택
- 또는 Custom으로 특정 시간 범위 지정

---

## 🔍 기본 쿼리

### 쿼리 1: 모든 로그 기본 확인
```sql
fields @timestamp,
       requestMetadata.application_name as Application,
       requestMetadata.application_id as AppID,
       requestMetadata.environment as Environment,
       modelId,
       input.inputTokenCount as InputTokens,
       output.outputTokenCount as OutputTokens
| sort @timestamp desc
| limit 100
```

**용도:** 최근 100개 요청의 기본 정보 확인

---

## 📊 애플리케이션별 분석

### 쿼리 2: 애플리케이션별 토큰 사용량 집계
```sql
fields @timestamp,
       requestMetadata.application_name as Application,
       input.inputTokenCount as InputTokens,
       output.outputTokenCount as OutputTokens
| stats sum(InputTokens) as TotalInputTokens,
        sum(OutputTokens) as TotalOutputTokens,
        sum(InputTokens + OutputTokens) as TotalTokens,
        count(*) as TotalRequests,
        avg(InputTokens + OutputTokens) as AvgTokensPerRequest
  by Application
| sort TotalTokens desc
```

**용도:** 어떤 애플리케이션이 가장 많은 토큰을 사용하는지 확인

**예상 결과:**
```
Application              | TotalInputTokens | TotalOutputTokens | TotalTokens | TotalRequests | AvgTokensPerRequest
-------------------------|------------------|-------------------|-------------|---------------|--------------------
CustomerServiceApp       | 15000            | 8500              | 23500       | 250           | 94
SalesAssistantApp        | 8200             | 4100              | 12300       | 120           | 102.5
DeveloperToolsApp        | 4500             | 2800              | 7300        | 80            | 91.25
```

---

### 쿼리 3: 특정 애플리케이션의 상세 정보
```sql
fields @timestamp,
       requestMetadata.application_name as Application,
       requestMetadata.tenant_id as Tenant,
       requestMetadata.user_id as User,
       input.inputTokenCount as InputTokens,
       output.outputTokenCount as OutputTokens
| filter requestMetadata.application_name = "CustomerServiceApp"
| sort @timestamp desc
| limit 50
```

**용도:** 특정 애플리케이션의 최근 활동 모니터링

---

### 쿼리 4: 애플리케이션 + 환경별 분석
```sql
fields requestMetadata.application_name as Application,
       requestMetadata.environment as Environment,
       input.inputTokenCount + output.outputTokenCount as TotalTokens
| stats sum(TotalTokens) as TokenUsage,
        count(*) as Requests,
        avg(TotalTokens) as AvgTokens
  by Application, Environment
| sort TokenUsage desc
```

**용도:** Production vs Development 환경 비용 비교

**예상 결과:**
```
Application          | Environment  | TokenUsage | Requests | AvgTokens
---------------------|--------------|------------|----------|----------
CustomerServiceApp   | production   | 20000      | 220      | 90.9
SalesAssistantApp    | production   | 10000      | 110      | 90.9
DeveloperToolsApp    | development  | 5000       | 60       | 83.3
```

---

## 👥 멀티테넌트 분석

### 쿼리 5: 테넌트별 사용량 분석
```sql
fields @timestamp,
       requestMetadata.tenant_id as Tenant,
       requestMetadata.application_name as Application,
       input.inputTokenCount + output.outputTokenCount as Tokens
| filter requestMetadata.tenant_id like /tenant-/
| stats sum(Tokens) as TotalTokens,
        count(*) as Requests,
        avg(Tokens) as AvgTokensPerRequest
  by Tenant, Application
| sort TotalTokens desc
```

**용도:** SaaS 비즈니스에서 고객별 사용량 추적 (차지백/쇼백)

---

### 쿼리 6: Top 10 Heavy Users
```sql
fields requestMetadata.tenant_id as Tenant,
       requestMetadata.user_id as User,
       input.inputTokenCount + output.outputTokenCount as Tokens
| stats sum(Tokens) as TotalTokens,
        count(*) as RequestCount
  by Tenant, User
| sort TotalTokens desc
| limit 10
```

**용도:** 가장 많이 사용하는 사용자 식별

---

## 💰 비용 센터별 분석

### 쿼리 7: 비용 센터(Cost Center)별 집계
```sql
fields requestMetadata.cost_center as CostCenter,
       requestMetadata.team as Team,
       input.inputTokenCount + output.outputTokenCount as Tokens
| stats sum(Tokens) as TotalTokens,
        count(*) as Requests
  by CostCenter, Team
| sort TotalTokens desc
```

**용도:** 부서별 비용 배분 및 예산 관리

**예상 결과:**
```
CostCenter | Team              | TotalTokens | Requests
-----------|-------------------|-------------|----------
CS-123     | customer-support  | 23500       | 250
SALES-456  | sales             | 12300       | 120
ENG-789    | engineering       | 7300        | 80
```

---

## 📈 시계열 분석

### 쿼리 8: 시간대별 사용량 트렌드
```sql
fields @timestamp,
       requestMetadata.application_name as Application,
       input.inputTokenCount + output.outputTokenCount as Tokens
| stats sum(Tokens) as TotalTokens,
        count(*) as Requests
  by bin(1h) as Hour, Application
| sort Hour desc
```

**용도:** 피크 시간대 식별, 용량 계획

---

### 쿼리 9: 일별 사용량 추이
```sql
fields @timestamp,
       requestMetadata.application_name as Application,
       input.inputTokenCount + output.outputTokenCount as Tokens
| stats sum(Tokens) as DailyTokens,
        count(*) as DailyRequests
  by bin(1d) as Day, Application
| sort Day desc
```

**용도:** 일일 사용량 모니터링 및 이상 탐지

---

## 🔎 고급 필터링

### 쿼리 10: 특정 조건 조합 필터링
```sql
fields @timestamp,
       requestMetadata.application_name as App,
       requestMetadata.environment as Env,
       requestMetadata.tenant_id as Tenant,
       input.inputTokenCount + output.outputTokenCount as Tokens
| filter requestMetadata.environment = "production"
  and requestMetadata.application_name = "CustomerServiceApp"
  and (input.inputTokenCount + output.outputTokenCount) > 100
| stats sum(Tokens) as TotalTokens,
        count(*) as HighUsageRequests,
        avg(Tokens) as AvgTokens
  by Tenant
| sort TotalTokens desc
```

**용도:** 프로덕션 환경에서 높은 토큰을 사용하는 요청 찾기

---

### 쿼리 11: 에러 또는 이상 탐지
```sql
fields @timestamp,
       requestMetadata.application_name as App,
       requestMetadata.user_id as User,
       input.inputTokenCount as Input,
       output.outputTokenCount as Output
| filter input.inputTokenCount > 5000 or output.outputTokenCount > 5000
| sort @timestamp desc
```

**용도:** 비정상적으로 큰 요청 식별

---

## 🔄 IAM Role과 함께 분석

### 쿼리 13: IAM Role + RequestMetadata 결합 분석
```sql
fields @timestamp,
       identity.arn as IAMRole,
       requestMetadata.application_name as App,
       requestMetadata.tenant_id as Tenant,
       input.inputTokenCount + output.outputTokens as Tokens
| stats sum(Tokens) as TotalTokens,
        count(*) as Requests
  by IAMRole, App, Tenant
| sort TotalTokens desc
```

**용도:** 인프라(Role) + 애플리케이션(Metadata) 이중 추적

---

## 📉 성능 분석

### 쿼리 14: 응답 크기 분석
```sql
fields @timestamp,
       requestMetadata.application_name as App,
       output.outputTokenCount as OutputTokens
| stats min(OutputTokens) as MinOutput,
        max(OutputTokens) as MaxOutput,
        avg(OutputTokens) as AvgOutput,
        pct(OutputTokens, 50) as MedianOutput,
        pct(OutputTokens, 95) as P95Output
  by App
```

**용도:** 응답 크기 분포 이해, 성능 최적화

---

## 💡 사용 팁

### CloudWatch Logs Insights 콘솔에서:

1. **쿼리 저장**
   - 자주 사용하는 쿼리는 "Save" 버튼으로 저장
   - 팀원과 공유 가능

2. **자동 새로고침**
   - 우측 상단에서 "Auto-refresh" 설정
   - 실시간 모니터링에 유용

3. **Export**
   - 쿼리 결과를 CSV로 Export 가능
   - 또는 CloudWatch Dashboard에 추가

4. **Visualization**
   - "Visualization" 탭에서 그래프로 시각화
   - Line chart, Bar chart 등 선택

---

## 🚨 알람 설정 예시

### CloudWatch Alarm 생성

**시나리오:** 특정 애플리케이션의 시간당 토큰 사용량이 10,000을 초과하면 알림

1. CloudWatch Logs Insights에서 쿼리 실행
2. "Create metric filter" 클릭
3. Metric 생성:
   - Metric Name: `BedrockTokenUsageHourly`
   - Dimension: `ApplicationName`
4. Alarm 생성:
   - Threshold: > 10000
   - Period: 1 hour
   - Action: SNS 토픽으로 이메일 발송

---

## 📊 CloudWatch Dashboard 구성 예시

### Dashboard JSON 템플릿

다음 위젯들을 포함하는 대시보드 생성 권장:

1. **전체 토큰 사용량 (Line Chart)**
   - 시간대별 총 토큰 사용량

2. **애플리케이션별 비교 (Pie Chart)**
   - 각 앱의 사용량 비율

3. **최근 요청 로그 (Log Table)**
   - 최근 20개 요청 실시간 표시

4. **비용 센터별 집계 (Bar Chart)**
   - 부서별 사용량 비교

---

## 🎓 다음 단계

### 1. Cost Explorer 연동
```
Cost Explorer에서 Bedrock 비용 확인
→ requestMetadata의 cost_center 태그와 매핑
```

### 2. Athena로 장기 분석
```
S3에 로그 저장 → Athena로 쿼리
→ 월별, 분기별 트렌드 분석
```

### 3. QuickSight 대시보드
```
Athena 데이터 소스 연결
→ QuickSight로 경영진 리포트 생성
```

---

## 📞 문제 해결

### 로그가 보이지 않는 경우:

1. **Bedrock Model Invocation Logging 활성화 확인**
   ```bash
   aws bedrock get-model-invocation-logging-configuration
   ```

2. **IAM 권한 확인**
   - `bedrock:InvokeModel` 권한
   - `logs:PutLogEvents` 권한

3. **로그 지연**
   - 로그가 CloudWatch에 나타나기까지 2-5분 소요 가능

### requestMetadata가 로그에 없는 경우:

- **InvokeModel API 사용 시**: requestMetadata 미지원
- **Converse API 사용**: requestMetadata 지원 ✅
- API를 Converse로 변경 필요

---

## 🔗 참고 자료

- [CloudWatch Logs Insights Query Syntax](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/CWL_QuerySyntax.html)
- [Bedrock Model Invocation Logging](https://docs.aws.amazon.com/bedrock/latest/userguide/model-invocation-logging.html)
- [Converse API Reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html)
