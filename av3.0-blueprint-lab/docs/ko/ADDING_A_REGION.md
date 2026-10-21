# 리전 추가하기

같은 계정 안에서, 이미 운영 중인 리전을 건드리지 않고 다른 AWS 리전에 랩의
**두 번째 독립 사본**을 세우는 방법입니다.

이것은 멀티 리전 배포가 *아닙니다*. 각 리전은 자체 Studio 도메인, 버킷, API,
Cognito 풀, 대시보드, 예산을 갖는 독립된 랩입니다. AWS 계정 자체를 빼면 공유되는
것이 없습니다 — 그리고 바로 거기에 함정이 있습니다. 일부 AWS 네임스페이스는
리전별이 아니라 **계정 전역**이기 때문입니다.

아래 내용은 모두 운영 중인 `us-west-2` 옆에 `ap-northeast-2`를 배포하면서 계정
`<aws-account-id>`에서 실측한 것입니다. *(정가)*로 표시된 수치는 그 세션의 API 호출이
아니라 AWS 공개 요금표에서 가져온 값입니다.

---

## 0. 대상 리전이 정말 비어 있는가?

이것을 가장 먼저 하세요. 이 계정에서는 "빈 리전"이라는 전제가 이미 틀렸습니다 —
`ap-northeast-2`에는 무관한 `FAST-stack`이 올라가 있습니다.

```bash
export R=ap-northeast-2
# 계정 번호를 붙여넣지 말고 조회하세요: §3에서 이 값을 EXPECTED_ACCOUNT_ID로
# 내보내고, scripts/deploy.sh는 불일치 시 배포를 거부합니다("ERROR: account mismatch").
# 하드코딩하면 그 계정 소유자를 제외한 모든 사람이 차단됩니다.
export ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

aws cloudformation describe-stacks --region $R --stack-name Av30BlueprintLabStack
aws s3api list-buckets --query "Buckets[?ends_with(Name,'$R')].Name"
aws sagemaker list-domains --region $R
aws sagemaker list-apps --region $R --query 'Apps[?Status==`InService`]'   # billing NOW
aws efs describe-file-systems --region $R --query 'FileSystems[].Name'     # orphan source
aws apigateway get-account --region $R --query cloudwatchRoleArn           # see §3
aws iam get-role --role-name av30-alpasim-m7                              # account-global
```

각 항목이 중요한 이유:

- **S3 버킷 이름은 전역입니다.** 중단된 시도에서 남은 `av30lab-*-$ACCOUNT-$R` 버킷이
  있으면 `cdk deploy`가 버킷 생성 단계에서 실패합니다.
- **Studio는 리전별로 도메인마다 EFS 파일 시스템을 생성하며**, 일부 경로에서는 스택을
  삭제해도 살아남습니다. 이 계정에는 정확히 그렇게 생긴 고아 파일 시스템이 있습니다.
- **이미 `InService` 상태인 `ml.*` 앱은 지금 과금 중입니다** — 리전이 유휴 상태라고
  가정하기 전에 확인하세요.
- **`av30-alpasim-m7`**(M10의 IAM 역할 + 인스턴스 프로파일)은 **계정 전역이며 리전
  접미사가 없습니다**. 어디서든 M10을 실행하기 전에 아래 "알려진 함정"을 읽으세요.

---

## 1. CDK 부트스트랩

```bash
aws cloudformation describe-stacks --region $R --stack-name CDKToolkit >/dev/null 2>&1 \
  || npx cdk bootstrap aws://$ACCOUNT/$R
```

충돌 없음: 모든 부트스트랩 역할 이름에 `-{account}-{region}`이 붙습니다.

---

## 2. 할당량 (약 1주 전에 처리)

**범위: 할당량은 `(계정 × 리전)` 단위입니다.** 콘솔의 "Applied **account-level** quota
value" 열과 "Adjustability: **Account level**"은 "계정 전체에 값 하나"처럼 읽히지만,
그런 뜻이 아닙니다. 이 라벨들은 리전 범위 질문에 답하는 필드와 **다른 필드**를
표시하며, API는 그 둘을 명시적으로 구분합니다:

| 필드 | 이 필드가 답하는 질문 | 여기서의 값 |
|---|---|---|
| `QuotaAppliedAtLevel` | 계정 **대 리소스** — 콘솔이 라벨로 보여 주는 것 | `ACCOUNT` |
| `GlobalQuota` | 계정 전역 **대 리전별** | `false` |

`list-service-quotas --quota-applied-at-level`은 열거형 `[ALL, ACCOUNT, RESOURCE]`를
받고, 이 옵션의 도움말 자체가 "filters the response to return applied quota values for
the ACCOUNT, RESOURCE, or ALL levels"라고 말합니다. 즉 *account-level*은
*resource-level*의 반대(개별 리소스별이 아니라 계정 단위로 조정됨)이며, **콘솔이 지금
보여 주고 있는 리전 안에서의** 구분입니다. 리전 간 공유에 대해서는 아무 말도 하지
않습니다.

리전 범위임을 보여 주는 독립적인 증거 세 가지:

- <strong>`GlobalQuota`</strong>는 SageMaker 할당량 **2,258**개 전부에서 `false`입니다(페이지네이션
  전체를 센 값). 대조적으로 IAM은 23/23, Route 53은 9/9가 `true`이고, S3는 섞여
  있습니다 — `General purpose buckets`는 `true`인데 복제 관련 할당량은 `false`입니다.
- `QuotaArn`에 리전이 박혀 있으므로 서로 다른 리소스입니다:
  `arn:aws:servicequotas:us-west-2:…:sagemaker/L-8ACE1754` 대
  `arn:aws:servicequotas:ap-northeast-2:…:sagemaker/L-8ACE1754`.
- 같은 계정, 같은 코드인데 **적용값이 다르고**(2 대 0),
  `list-requested-service-quota-change-history` 스트림도 완전히 별개입니다 — 증설은
  리전별로 신청되고 승인됩니다.

따라서 리전 A에서 승인된 증설은 리전 B에 아무 영향이 없습니다. 할당량 **코드**는
공유되지만 **값, 신청 내역, 심지어 어떤 할당량이 존재하는지**는 공유되지 않습니다 —
`ml.g6.24xlarge for notebook instance usage`는 us-west-2에는 있고 ap-northeast-2에는
아예 없습니다("g6.24xlarge" 검색 결과 10건 대 9건).

### 이 랩이 실제로 제공하는 인스턴스 타입 실측값

| 할당량 (Studio JupyterLab apps) | 코드 | us-west-2 | ap-northeast-2 | 사용 모듈 |
|---|---|---|---|---|
| `ml.t3.medium` | `L-71FAF417` | 2500 | 2500 | 기본 워크스페이스 |
| `ml.g5.xlarge` | `L-988CE6C5` | 5 | 5 | M7 (Nerfstudio) |
| `ml.g5.12xlarge` | `L-8D2ED7BF` | 5 | 5 | M2/M3 |
| `ml.g5.24xlarge` | `L-F087CCFC` | 2 | 2 | M5/M6/M8/M9 대안 (24 GB 티어) |
| `ml.g5.48xlarge` | `L-83AB5D73` | 2 | 2 | M6 샤딩 |
| `ml.p4d.24xlarge` | `L-AD63F1D2` | 2 | **2** | 40 GB 티어 — 720p, guardrails ON |
| **`ml.g6.12xlarge`** | `L-962247BA` | 2 | **0** ⚠ | M2/M3 대안 |
| `ml.g6.24xlarge` | `L-8ACE1754` | 2 | **0** | 대시보드가 권장하지 않음(g5.12xlarge와 같은 티어인데 더 비쌈) |
| `ml.p5.48xlarge` | `L-B41FBF28` | 1 | **0** | 80 GB 티어 |
| `ml.m5.xlarge` *학습* | `L-CCE2AFA6` | 30 | 30 | M12 |
| `ml.m5.xlarge` *프로세싱* | `L-0307F515` | 16 | 16 | M11 |

> **쿼터만 한계가 아닙니다 — AZ 커버리지도 한계입니다.** Studio 앱은 도메인이 서브넷을
> 가진 가용 영역에서만 뜨고, GPU 타입은 모든 AZ에서 팔지 않습니다. 2026-09-25 이 계정에서
> `describe-instance-type-offerings --location-type availability-zone-id`로 실측
> (AZ *ID* 기준 — a/b/c *이름*은 계정마다 다른 AZ를 가리킵니다):
>
> | 리전 | g5.* 판매 AZ | p4d 판매 AZ | 도메인 접근(`max_azs` 수정 전) |
> |---|---|---|---|
> | ap-northeast-2 | apne2-az1, az3, az4 | apne2-az2, az4 | g5는 **3개 중 1개**. p4d는 g5와 **공유 AZ 0개** |
> | us-west-2 | usw2-az1, az2, az3 | 4개 전부 | 3개 중 2개 |
>
> `apne2-az2`는 g5도 g6도 하나도 안 팝니다. 이제 VPC가 모든 AZ에 서브넷을 만들어
> (`infra/av30_constructs/network.py`, `max_azs=99`) 구조적으로 해결되지만, **재배포**해야
> 적용되고 `check_quotas.py`는 아직 커버리지를 보고하지 않습니다. 따라서 "OK 5"로 표시된
> 타입도 앱 시작 시
> `EC2InsufficientCapacityError: … unavailable in supported availability zones [...]`로
> 실패할 수 있습니다. 쿼터 5 / 사용 0인 상태에서 세 타입 연속 그 실패를 실측했습니다.

**ap-northeast-2에서는 `g6`와 `g6e` 계열 전체가 0입니다** — 24xlarge만이 아닙니다.
`g7e`는 *두* 리전 모두 0입니다.

**그렇다고 서울이 GPU를 못 쓰는 것은 아닙니다.** `g5`는 전 범위가 제공되고
`p4d.24xlarge`는 이미 2로 승인되어 있어서, **할당량 신청을 전혀 하지 않고도** 오늘
당장 랩을 돌릴 수 있습니다. 대시보드가 권장하는 타입에 `g6`가 하나도 없기 때문입니다:
M2/M3과 무거운 네 모듈(M5/M6/M8/M9) 모두 `ml.g5.12xlarge`(서울 쿼터 5)를 기본값으로
쓰고, 대안이 `ml.g5.24xlarge`(같은 22.5 GB 티어, ~44% 더 비쌈), 품질 옵션이
`ml.p4d.24xlarge`(40 GB 티어)입니다. 네 모듈은 예전에 `ml.g6.24xlarge`(서울 쿼터 **0**)를
기본값으로 썼는데, 기하 구조가 동일하고(4 GPU × 22,888 MiB) 더 싸고 양쪽 리전에서
쿼터가 5인 `ml.g5.12xlarge`로 바뀌었습니다. 그래도 서울 가격은 us-west-2보다 ~23%
높다는 점은 감안하세요.

위 표를 읽는 대신 사전 점검(pre-flight)을 실행하세요 — 실시간 할당량을 조회하고,
생성된 요율 표와 교차 검증하며, 각 부족분이 영향을 주는 모듈을 알려 줍니다:

```bash
./scripts/check_quotas.py --region $R --participants 10
```

참가자 대시보드가 권장하는 타입 중 하나라도 실행할 수 없으면 0이 아닌 코드로
종료합니다. `deploy.sh`도 `cdk deploy` **전에** 이를 자동 실행합니다. 이 계정 실측 결과: **두 리전
모두 동시 5명까지 통과하고, 10명에서는 양쪽 다 통과하지 못합니다** — 한계는 양쪽 모두
`ml.g5.12xlarge` / `ml.g5.xlarge`의 쿼터 5로 동일하므로, 이 점에서 서울이 불리하지
않습니다. 이를 감안해 인원을 계획하거나, 그 두 타입의 할당량을 올리세요:

```bash
# Must be filed IN the target region. The script prints the exact code for each shortfall.
aws service-quotas request-service-quota-increase --region $R \
  --service-code sagemaker --quota-code L-8D2ED7BF --desired-value 10   # ml.g5.12xlarge
aws service-quotas request-service-quota-increase --region $R \
  --service-code sagemaker --quota-code L-988CE6C5 --desired-value 10   # ml.g5.xlarge
```

**신청하기 전에, 그 리전에서 해당 인스턴스가 Studio용으로 제공되기는 하는지
확인하세요.** 가용성은 리전별 *그리고 사용 유형별*입니다 — "그 계열이 리전에
있는가"는 잘못된 질문이며 오판을 부릅니다:

```bash
aws pricing get-products --region us-east-1 --service-code AmazonSageMaker \
  --filters Type=TERM_MATCH,Field=instanceType,Value=ml.g6.24xlarge \
            Type=TERM_MATCH,Field=regionCode,Value=$R \
            Type=TERM_MATCH,Field=platoinstancetype,Value=Studio-JupyterLab \
  --query 'length(PriceList)'
```

실측: `ap-northeast-2`는 실제로 `APN2-Studio:JupyterLab-ml.g6.24xlarge` 제품을
반환하므로 0인 할당량을 올릴 가치가 있습니다. **`eu-west-1`은 그 타입의 Studio 제품을
하나도 반환하지 않습니다** — 거기서 할당량을 신청해도 헛수고이므로 `g5` 경로로
돌리세요.

---

## 2.5. 이 리전의 요율 표 생성 — 배포 **전에**

**건너뛰지 말고, §3 뒤에 하지도 마세요.** 사전 생성된 리전은 다섯 개뿐입니다
(`ap-northeast-1`, `ap-northeast-2`, `eu-west-1`, `us-east-1`, `us-west-2`). 그 외
리전은 배포가 **성공한 뒤** API 전체가 500을 반환합니다.
`infra/lambda/shared/config.py`가 **모듈 import 시점**에 `INSTANCE_RATES`를 해석하기
때문입니다:

```python
INSTANCE_RATES = _rates_for_region(AWS_REGION)   # UnpricedRegionError 발생
```

15개 Lambda 핸들러 중 **14개**가 이 모듈을 import합니다 — `token_authorizer`와
`create_user`도 포함이라 **로그인조차 불가능합니다.** "엔드포인트 하나의 가격이 틀리는"
문제가 아닙니다.

```bash
./scripts/refresh_instance_rates.py --region $R --merge   # --merge 는 다른 리전을 보존
grep -c "\"$R\":" infra/lambda/shared/instance_rates.py  # 1 이 나와야 함
```

한 번의 조회로 **두 파일**을 씁니다: 위의 Lambda 에셋과 `scripts/av30_instance_rates.py`.
후자는 §4가 모든 참가자 워크스페이스로 동기화해 노트북 비용 셀이 **이 리전** 가격을
인용하게 합니다. 따라서 늦게 생성하면 §3 **과** §4를 다시 실행해야 합니다.

`pricing:GetProducts`(Price List API는 us-east-1에만 있어 스크립트가 거기를 호출하고
`$R`을 필터로 넘깁니다)와 쿼터 코드를 위한 `servicequotas:ListServiceQuotas`가 필요합니다.

---

## 3. 배포

```bash
export EXPECTED_ACCOUNT_ID=$ACCOUNT
export ADMIN_EMAIL=you@example.com
export ADMIN_IP_ALLOWLIST=1.2.3.4/32          # omit to allow all
./scripts/deploy.sh --region $R
```

`deploy.sh`가 `admin_email`, `admin_ip_allowlist`, `region` 컨텍스트를 대신 설정하고
`--context region=$R`로 고정하므로, `infra/app.py`가 방금 셸 가드가 확인한 리전과
다른 리전을 해석할 수 없습니다. 실측 소요 시간 **~3분**, 리소스 176개.

**새 리전에서는 다음을 설정하지 마세요:**

| 컨텍스트 / 환경 변수 | 설정하면 안 되는 이유 |
|---|---|
| `OWNER_TAG` | `Owner` 태그가 기본값과 다른 스택을 업데이트할 때만 씁니다. SageMaker는 도메인 **태그**를 교체가 필요한 속성으로 취급하므로, 불일치하면 Studio 도메인이 교체되고 그 EFS가 고아가 됩니다. `Owner` 태그가 다른 값으로 생성된 기존 스택을 업데이트할 때만 필요합니다 — `deploy.sh`가 불일치를 거부하고 다시 실행할 정확한 `OWNER_TAG=...` 명령을 출력합니다. |
| `HOSTED_UI_DOMAIN_EXISTS` | 여기서 가장 위험한 스위치입니다. Cognito hosted-UI 도메인 선언을 건너뛰어 **로그인 엔드포인트가 없는** 풀을 만듭니다. us-west-2에 이미 존재하는, 스택이 관리하지 않는 도메인 하나만을 위해 존재합니다. |
| `APIGW_ACCOUNT_ROLE` | `AWS::ApiGateway::Account`는 이름이 없는 **계정×리전당 싱글턴**이며 조건 없는 `PATCH /account`로 구현됩니다. 리전에 CloudWatch 역할이 이미 있으면(서울에는 `FAST-stack` 소유의 역할이 있습니다) 이 옵션을 켜는 순간 **다른 스택의 역할을 가로챕니다**. `aws apigateway get-account --region $R --query cloudwatchRoleArn`이 `None`을 반환할 때만 설정하세요. 기존 역할이 우리 것이 아니면 `deploy.sh`가 거부합니다. |

> **맨 `cdk deploy`가 아니라 `deploy.sh`를 쓰세요.** `admin_email`의 기본값이
> `placeholder@example.com`이므로, `-c admin_email=...`을 빠뜨린 `cdk deploy`는
> **알림 이메일을 자리표시자로 바꾸고 실제 구독을 삭제합니다** — *확인 완료된* 구독까지
> 포함해서입니다. 이 리전을 작업하며 정확히 그 일을 겪었습니다. 복구하려면 확인 클릭을
> 다시 해야 합니다. 재생성된 구독은 `PendingConfirmation` 상태로 돌아오기 때문입니다.
> 자리표시자 구독은 정리조차 할 수 없습니다
> (`Cannot delete a subscription which is pending confirmation. Detaching subscription
> from stack.`) — SNS가 ~3일 후 폐기할 때까지 남아 있습니다. 꼭 `cdk`를 직접 호출해야
> 한다면 항상 `-c admin_email=`을 넘기세요(us-west-2라면 `-c owner_tag=`와
> `-c hosted_ui_domain_exists=true`도 함께).

**새 Cognito 프리픽스는 필요하지 않습니다.** hosted-UI 프리픽스는 전역이 아니라
**리전**마다 고유합니다 — 리전이 호스트명 안에 들어 있기 때문입니다
(`<prefix>.auth.<region>.amazoncognito.com`). 이 계정에서 `av30lab-admin`은 us-west-2와
ap-northeast-2 *양쪽* 모두 ACTIVE이며, 서로 다른 풀을 가리킵니다. 아래 확인 결과가 그
리전에서 다른 계정이 선점했다고 말할 때만 `-c hosted_ui_prefix=...`로 재정의하세요:

```bash
aws cognito-idp describe-user-pool-domain --domain av30lab-admin --region $R
```

| 응답 | 의미 |
|---|---|
| 200, `DomainDescription`이 채워져 있음 | 이미 당신 것 |
| 200, `DomainDescription`이 **비어 있음** | 사용 가능 — 그대로 쓰세요 |
| `ResourceNotFoundException` | 그 리전에서 **다른 계정**이 선점 → 새 프리픽스를 고르세요 |

---

## 4. 공유 버킷 시딩

**`AWS_REGION`을 항상 명시적으로 넘기세요.** 기본값에 맡기면 조용히 *첫 번째* 리전을
다시 시딩하기 때문에(대상 버킷을 `$REGION`의 CloudFormation 스택에서 해석합니다),
시딩 스크립트는 이제 이 값 없이는 실행을 거부합니다.

노트북 템플릿은 **필수**입니다 — 참가자에게 빈 워크스페이스를 넘기는 대신
프로비저닝이 의도적으로
`HTTP 500 "Notebook templates are not staged in this region"`으로 실패합니다:

```bash
SHARED=av30lab-shared-data-$ACCOUNT-$R
aws s3 sync notebooks/ "s3://$SHARED/notebook-templates/"        --region $R \
    --exclude "*__pycache__*" --exclude "*.pyc"
aws s3 sync scripts/   "s3://$SHARED/notebook-templates/scripts/" --region $R \
    --exclude "*__pycache__*" --exclude "*.pyc"
```

### 그다음 데이터 — 버킷 간 복사이며, 다시 내려받는 것이 아닙니다

`cache_models.sh`는 Hugging Face에서 받아오고(`HF_TOKEN`과 gated 리포마다 라이선스
동의가 필요합니다) 그다음에야 업로드합니다. **두 번째** 리전에서는 방향이 틀렸습니다 —
바이트는 이미 첫 번째 리전 버킷에 있습니다. 대신 리전 간 복사하세요. 토큰도 라이선스
단계도 필요 없고, 인터넷→내 PC→S3가 아니라 S3→S3입니다:

```bash
SRC=av30lab-shared-data-$ACCOUNT-us-west-2     # 이미 시딩된 리전
DST=av30lab-shared-data-$ACCOUNT-$R

# 큰 것부터 — 가장 오래 걸리는 작업이 먼저 시작됩니다. 각각 재개 가능하므로 다시 실행하면 이어서 끝냅니다.
aws s3 sync "s3://$SRC/model-cache/"   "s3://$DST/model-cache/"   --source-region us-west-2 --region $R
aws s3 sync "s3://$SRC/hf-cache/"      "s3://$DST/hf-cache/"      --source-region us-west-2 --region $R
aws s3 sync "s3://$SRC/datasets/"      "s3://$DST/datasets/"      --source-region us-west-2 --region $R
aws s3 sync "s3://$SRC/m10-reference/" "s3://$DST/m10-reference/" --source-region us-west-2 --region $R
```

복사해 올 시딩된 리전이 **없을 때만** `stage_nuscenes.sh` / `cache_models.sh`를 쓰세요:

```bash
AWS_REGION=$R ./scripts/stage_nuscenes.sh                      # 공개 미러, 토큰 불필요
AWS_REGION=$R HF_TOKEN=hf_... ./scripts/cache_models.sh        # 약 157 GiB 재다운로드
```

> **이 두 스크립트는 위 4줄 중 2줄만 대체합니다.** `cache_models.sh`는 `model-cache/`만,
> `stage_nuscenes.sh`는 `datasets/`만 씁니다. 둘 중 무엇도 `hf-cache/`를 만들지 못하고,
> 그 트리를 만드는 것은 **`scripts/cache_hf_tree.sh`** 입니다(관리자 `HF_TOKEN` 필요).
> `hf-cache/`는 HuggingFace *오프라인 캐시* 레이아웃(`models--org--name/snapshots/<sha>/…`)인데
> `cache_models.sh`는 `hf download --local-dir`의 평면 구조를 씁니다. `m10-reference/`도
> 생산 스크립트가 없으니 복사해야 합니다.
>
> 가정이 아닙니다. 2026-09-26에 ap-northeast-2를 위 블록 대신 `cache_models.sh`로 시딩했고,
> 스크립트는 깔끔하게 끝났고 `deploy.sh`도 성공을 보고했고 Day-1 스모크 테스트(M1 + M2 —
> 그 프리픽스가 커버하는 유일한 두 모듈)도 통과했는데, 리전은 **M5·M6·M9·M10이 실행되지 않는
> 상태로** 출하됐습니다. 참가자가 네 모듈 진행한 뒤에야 발견됐습니다. 아래 10번을 실행하세요.

us-west-2 원본 버킷에서 실측한 값:

| 프리픽스 | 크기 | 객체 수 | 없으면 깨지는 모듈 |
|---|---|---|---|
| `notebook-templates/` | 0.55 MiB | 31 | **전부** — 프로비저닝이 즉시 실패 |
| `datasets/` (nuScenes-mini) | 5.01 GiB | 31,225 | M1, M2, M3, M5, M6, M7, M8, M9 |
| `model-cache/` | 157.45 GiB | 1,707 | M2, M8 |
| `hf-cache/` | 115.00 GiB | 481 | M5, M6, M9 |
| `m10-reference/` | 0.03 GiB | 16 | M10 시각화 |
| **합계** | **277.49 GiB** | **33,457** | |

`m8-lora-probe/`(1객체, 3 KiB)는 **의도적으로 제외**했습니다. 일회성 probe가 남긴 날짜 붙은
SageMaker 학습 잡 `sourcedir.tar.gz`이고 읽는 노트북이 없으며, 도달 불가한 프리픽스를 표에
올리면 표 전체를 참고용으로 읽게 만듭니다 — 그 독법이 `hf-cache/`를 건너뛰게 한 원인입니다.

추측이 아니라 노트북을 읽어서 확인한 사항: M5와 M6은 `scripts/setup_cosmos_env.sh`를
통해 `hf-cache/hub/`를 **간접적으로** 사용하므로, 두 노트북에서 프리픽스를 grep해도
나오지 않습니다. **없을 때 실제로 일어나는 일**(실측, ap-northeast-2, 2026-09-26 — 이전 서술은 두 군데가
틀렸습니다):

* `setup_cosmos_env.sh`는 이제 `=== STOP ===` 블록으로 멈추고 첫 줄이
  `Reason : no HF cache at <uri> (prefix does not exist in this region)` 입니다. `HF_TOKEN`이
  있으면 대신 진행하며 `[hf-cache] No usable offline cache (…)`를 남깁니다. 어느 쪽도 이전
  판이 grep하라고 했던 `WARNING: restore failed…`가 아닙니다 — 그건 항상 *다른* 분기
  (`aws s3 sync` 실패)였고, 그 문자열을 찾는 운영자는 아무것도 못 찾습니다.
* 수정 전에는 **참가자별 토큰 구하기가 아니라 침묵**이었습니다. 스크립트가 exit 0으로 끝나
  노트북이 "environment ready"를 출력하고, 15~20분 뒤 M5가 `torchrun` 안에서 4초 만에
  `ChildFailedError`로 죽는데 유일하게 보이는 조언이 CUDA out-of-memory였습니다. HuggingFace
  401은 캡처된 stderr에 있었지만 노트북이 출력한 25줄 창 밖이었습니다.
* 이제는 사용 가능한 캐시도 `HF_TOKEN`도 없으면 **시작 자체를 거부**하고(exit 2) 두 가지
  해결책을 알려줍니다. 즉 시딩되지 않은 리전은 GPU 시간을 쓰기 전에 몇 초 만에 실패합니다 —
  그래도 실패입니다. 프리픽스를 시딩하세요.

비용: ap-northeast-2에서 대략 **1회성 $5.73**(전송 + 요청)과 스토리지 **$6.94/month**
*(전송/요청 단가는 정가이며, 서울 스토리지 요율 $0.025/GB-mo는 API로 확인했습니다)*.

`stage_nuscenes.sh`는 `ap-northeast-1`의 공개 버킷 `s3://motional-nuscenes`에서
`--no-sign-request`로 가져오는데, 이는 의도된 동작이며 리전과 무관합니다.

> `aws s3 ls`는 **현재 객체만** 보고합니다. 새 버킷에 버저닝이 켜져 있으면 실제 과금
> 용량은 더 큽니다 — 이 계정에서는 이미 298 GB로 보고된 것이 실제로는 441.7 GB로
> 과금된 사례가 있습니다.

---

## 5. 검증 체크리스트

1. `aws cloudformation describe-stacks --region $R --stack-name Av30BlueprintLabStack`
   → `CREATE_COMPLETE`.
2. **예산이 $0.00이 아니라 그 리전을 실제로 측정하는지.** 이미 조용한 회귀를 한 번
   잡아낸, 바로 그 검사입니다:
   ```bash
   aws budgets describe-budget --account-id $ACCOUNT \
     --budget-name av30lab-daily-budget-$R \
     --query 'Budget.[CostFilters,CalculatedSpend.ActualSpend.Amount]'
   ```
   `CostFilters`는 반드시 `{"Region": ["<region-code>"]}`여야 합니다. 거기에 **표시
   이름**(`"Asia Pacific (Seoul)"`)을 넣어도 거부되지 않습니다 — 대신 아무것도
   매칭하지 않으므로 예산은 영원히 `0.0`으로 읽히고 절대 알람이 울리지 않습니다.
   Cost Explorer와 교차 확인하세요:
   ```bash
   aws ce get-cost-and-usage --time-period Start=$YDAY,End=$TODAY --granularity DAILY \
     --metrics UnblendedCost \
     --filter "{\"Dimensions\":{\"Key\":\"REGION\",\"Values\":[\"$R\"]}}"
   ```
   예산이 `0.0`인데 CE가 `> 0`이면 ⇒ 필터가 깨진 것입니다.
3. **예산 알림이 실제로 전달될 수 있는지.** 새 리전은 새 SNS 토픽을 뜻하고, 따라서
   **확인되지 않은 이메일 구독이 새로 생깁니다**. CloudFormation은 *요청*에 대해
   `CREATE_COMPLETE`를 보고하고, 재시도하지 않으며, SNS는 미확인 구독을 ~3일 후
   폐기합니다. `deploy.sh`가 경고합니다 — 무시하지 마세요.
   ```bash
   aws sns list-subscriptions-by-topic --region $R --topic-arn <topic> \
     --query 'Subscriptions[?Protocol==`email`].[Endpoint,SubscriptionArn]'
   ```
   `SubscriptionArn`이 `PendingConfirmation`이면 알람이 갈 곳이 없다는 뜻입니다.
4. SPA 설정은 리전 로컬입니다:
   `aws s3 cp s3://av30lab-admin-dashboard-$ACCOUNT-$R/config.json -`의 출력에 `$R`만
   등장해야 합니다.
5. `aws cognito-idp describe-user-pool-domain --domain av30lab-admin --region $R` →
   `ACTIVE`, 풀 id가 `$R`로 시작.
6. **요율 표는 배포 전(§2.5)에 생성되었고** 배포 후에도 남아 있는지:
   ```bash
   grep -c "\"$R\":" infra/lambda/shared/instance_rates.py   # 1 이 나와야 함
   ./scripts/check_quotas.py --region $R --participants <인원>
   ```
7. Cognito 관리자를 만들고, hosted UI로 로그인해 참가자 **1명**을 프로비저닝한 뒤,
   워크스페이스가 **비어 있지 않은지** 확인하세요(실측: 객체 **32**개 — 스테이징된
   템플릿 31개 + `.av30-progress.env`).
8. `aws apigateway get-account --region $R --query cloudwatchRoleArn`이 §0의 값에서
   변하지 않았는지.
9. **이미 있던 리전이 그대로인지:** 그 스택은 여전히 `UPDATE_COMPLETE`, 예산은 여전히
   존재, `apigateway get-account`도 그대로.

10. **데이터가 실제로 있는지 — 참가자를 만들기 전에 실행:**

    ```bash
    ./scripts/check_seeding.sh --region $R --source-region us-west-2
    ```

    반드시 exit 0 이어야 합니다. 1~9번은 **M5·M6·M9·M10이 실행되지 않는 리전에서도 전부
    통과합니다** — 2026-09-26 ap-northeast-2에서 정확히 그랬습니다 — 어느 항목도 §4가 복사하라고
    한 277.49 GiB의 바이트를 한 개도 검사하지 않기 때문입니다. 이 검사는 *존재*가 아니라 *트리
    모양*을 단정합니다: 런타임 glob이 실제로 테스트하는 `models--nvidia--*` 디렉터리 5개, Cosmos가
    고정한 커밋 sha의 `tokenizer.pth` blob, 그리고 `--source-region`을 주면 CRC64 체크섬과 객체 수
    대조까지. 존재만으로는 불충분합니다 — HuggingFace 오프라인 모드는 무결성 검사를 **전혀** 하지
    않아 0바이트 파일도 성공한 다운로드로 읽고, 중단된 `aws s3 sync`는 빈 프리픽스보다 **더
    나쁩니다**: 디렉터리 하나만 있어도 `HF_HUB_OFFLINE=1`이 켜지고, 그러면 여전히 없는
    체크포인트가 다운로드가 아니라 불투명한 `Local entry not found`로 바뀝니다.

### 저렴하고 정직한 스모크 테스트 ($1 훨씬 아래)

배포하고(§3), **`notebook-templates/`만** 시딩하고(0.55 MiB ≈ $0.00), 참가자 1명을
프로비저닝하고, **`ml.t3.medium` 하나**를 시작하고(할당량이 이미 2500), 체크리스트를
돌리고, 앱을 삭제한 뒤 `./scripts/teardown.sh --region $R`를 실행합니다.

이것으로 증명되는 것: 176개 리소스가 기존 리전과 나란히 생성된다는 점, Cognito
프리픽스가 실제로 공존한다는 점, 예산 이름과 필터, `ApiGateway::Account`를 건드리지
않았다는 점, SageMaker 이미지 계정 매핑이 실제 이미지로 해석된다는 점(앱이 정말로
시작됨), 로그인 엔드투엔드, 빈 버킷 가드, 그리고 리전 1이 영향을 받지 않았다는 점.

증명되지 **않는** 것: GPU 용량이나 할당량(`t3.medium`은 서울에서 할당량이 0인
`ml.g6.24xlarge`에 대해 아무것도 말해 주지 않습니다), 건너뛴 272 GiB가 존재하는지 —
없으므로 M2/M3/M5/M6/M9은 모델 로드에서 실패합니다, 동시성(사용자 1명은 10명이
아닙니다), 예산 알림이 실제로 전달되는지.

---

## 알려진 함정

**`INSTANCE_RATES`는 us-west-2 가격 스냅샷이며, 동시에 인스턴스 허용 목록 역할까지
합니다.** `infra/lambda/shared/config.py`는 리전을 키로 갖지 않는데,
`change_instance`는 그 키에서 `VALID_INSTANCE_TYPES`를 파생하고 `instance_options`는
그 키로 참가자 드롭다운을 만듭니다. 결과는 두 가지입니다:

| Studio-JupyterLab | us-west-2 | ap-northeast-2 | 표시값 |
|---|---|---|---|
| `ml.t3.medium` | $0.0500 | $0.0620 | −24% |
| `ml.g5.12xlarge` | $7.0900 | $8.7180 | −23% |
| `ml.g6.24xlarge` | $8.3440 | $10.2600 | −23% |

1. 서울에서는 참가자와 관리자에게 보이는 모든 비용이 ~23% **낮게** 읽힙니다 — 문서화된
   실패 모드가 "눈치채지 못한 지출"인 랩에서 방향이 잘못된 오차입니다.
2. 드롭다운이 리전으로 필터링되지 않으므로, 어떤 리전에 그 리전의 Studio에는 없는
   인스턴스(예: `eu-west-1`의 `ml.g6.24xlarge`)가 제시될 수 있고, 참가자별로 앱 시작
   시점에 실패합니다.

서울의 ~23% 차이가 균일한 것은 우연이며 규칙이 아닙니다 — 배수를 곱해 이것을
"고치려" 하지 말고, 표를 리전으로 키잉하세요.

**`av30-alpasim-m7`(M10)은 계정 전역이며 리전 접미사가 없습니다.** IAM 역할과 인스턴스
프로파일 이름은 계정 전역이므로, 두 번째 리전에서 M10을 실행하면
`EntityAlreadyExists`로 실패합니다. 더 나쁜 것은, M10 런북의 티어다운이 "다음 실행에서
이름 충돌을 막기 위해" 둘을 *조건 없이* 삭제한다는 점입니다 — 그래서 **어느 쪽** 리전이든
M10을 티어다운하면 다른 리전에서 실행 중인 GPU 호스트가 쓰고 있는 역할을 파괴합니다.
두 개 이상의 리전에서 M10을 실행하기 전에, 생성 시점*과* 티어다운 시점 양쪽에서 두 이름에
리전 접미사를 붙이세요. 현재 역할의 인라인 정책 또한 리전 세그먼트가 전혀 없는 버킷
이름을 지정하고 있어서, 지금의 버킷 이름과는 더 이상 일치하지 않습니다.

**`REGION_CONFIG` / `TARGET_REGIONS`는 설정하지 마세요.**
`infra/lambda/shared/config.py`에는 잠들어 있는 리전 간 컨트롤 플레인이 정의되어 있고,
`create_user` / `bulk_provision`은 이미 요청 본문의 `region` 필드를 받습니다. 두 환경
변수 모두 CDK가 설정하지 않으므로, 오늘은 모든 것이 단일 배포 리전으로 수렴합니다 —
이 문서가 설명하는 독립 사본 모델이 바로 그것입니다. 이들을 설정하면 두 개의 독립된
랩이 조용히 양쪽을 관리하는 하나의 컨트롤 플레인으로 바뀝니다.

**CloudFront 배포는 계정 전역 할당량입니다.** 리전마다 2개가 추가됩니다(여기에 카운트되지
않는 Cognito 관리형 2개가 더 붙습니다). 기본 한도가 200이므로 현실적인 위험은 없지만,
확인 명령은
`aws service-quotas get-service-quota --service-code cloudfront --quota-code L-24B04930`
입니다.

---

## 티어다운

```bash
./scripts/teardown.sh --region $R      # or AWS_REGION=$R ./scripts/teardown.sh
```

리전을 명시해야 하고, 확인 절차에서 `<account>/<region>`을 직접 입력해야 합니다 — 이전
스크립트는 `us-west-2`를 기본값으로 삼았고, 그래서 리전 B를 회수하려고 실행했는데 리전
A가 삭제될 수 있었습니다(옛 프롬프트는 계정 id만 물었고, 계정 id는 모든 리전에서
동일합니다). 그 후에는 CloudFormation이 하나도 추적하지 않는, 알려진 고아 리소스의
출처를 확인하세요:

```bash
aws efs describe-file-systems --region $R          # Studio's per-domain filesystem
aws ec2 describe-security-groups --region $R \
  --filters "Name=group-name,Values=security-group-for-*-nfs-*"
aws s3api list-buckets --query "Buckets[?ends_with(Name,'$R')].Name"
aws budgets describe-budgets --account-id $ACCOUNT --query "Budgets[].BudgetName"
```

Studio 도메인의 삭제 순서는 앱 → 스페이스 → **사용자 프로파일**(런타임에 생성되므로
스택이 소유하지 않습니다) → 스택입니다. 그 다음에는 남아 있는 EFS **마운트 타깃**이
서브넷을 붙잡고, SageMaker가 자동 생성한 NFS 보안 그룹(`security-group-for-{inbound,outbound}-nfs-<domainId>`,
서로를 tcp/988로 참조합니다)이 VPC를 붙잡습니다. 그룹을 삭제하기 전에 상호 참조를
해제하세요.
