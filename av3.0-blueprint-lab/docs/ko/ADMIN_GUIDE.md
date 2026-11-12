# AV 3.0 Blueprint Lab — 관리자 가이드

워크샵 관리자가 이벤트 **전, 중, 후**에 하는 모든 작업을 실제 수행 순서대로
정리했습니다. 참가자는 대시보드 링크만 있으면 됩니다(
[PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md) 참고). 나머지는 전부 관리자의 몫입니다.

> **황금률:** 무겁고, 게이트가 걸려 있고, GPU가 필요하고, 자격 증명이 얽힌 작업은 모두 관리자의 몫입니다.
> 아래 이벤트 전 체크리스트를 완료하면, 참가자는 **AWS 계정 없이, Hugging Face 토큰 없이, 라이선스 클릭 없이**
> 브라우저에서 M0–M12을 실행할 수 있습니다
> (유일한 예외는 선택 사항인 M10 자가 실행입니다 — §7 참고).

---

## 0. 무엇을 운영하는가

- **하나의 CDK 스택** (`Av30PlatformStack`) → VPC, KMS로 암호화된 S3(공유 + 사용자별
  워크스페이스), DynamoDB, Cognito, WAF, API Gateway + Lambda, CloudFront 대시보드 2개
  (관리자 + 사용자), 그리고 참가자 전원이 **하나의** 실행 역할
  `av30lab-sagemaker-execution-role-<region>`을 공유하는 SageMaker Studio 도메인(사용자별
  역할이 아닙니다). 이 역할로 무엇이 분리되고 무엇이 분리되지 않는지는 아래
  **참가자 격리**에 정리했습니다.
- **S3 버킷 2개** (이름은 **당신의** 계정 + 리전에서 파생됩니다 — 이 가이드의
  예시는 레퍼런스 배포인 계정 `<aws-account-id>` / `us-west-2`를 사용합니다.
  당신의 값으로 치환하세요 — §1.5 참고):
  - `av30lab-shared-data-<account>-<region>` — 모델, 데이터셋, 노트북 템플릿, M10 레퍼런스.
  - `av30lab-user-workspace-<account>-<region>` — 참가자당 `users/<id>/` 프리픽스 하나.

> **참가자 격리(신뢰 모델).** 참가자의 노트북, 터미널, 작업(job)은 모두 이 역할 하나로
> 실행됩니다. 참가자를 구분하는 값은 두 가지입니다. 도메인에
> `ExecutionRoleIdentityConfig = USER_PROFILE_NAME`이 설정되어 있어 SageMaker가 이 역할의
> 세션마다 `aws:SourceIdentity` = 사용자 프로필 이름(참가자 id, S3 프리픽스와 같은 값)을
> 붙이고, SageMaker API 호출에는 `${sagemaker:UserProfileName}`이 실립니다. 그래서 참가자는
> 다음 항목에서 자기 것에만 접근할 수 있습니다.
> - **S3 워크스페이스.** 워크스페이스 버킷의 읽기, 쓰기, 삭제, 목록 조회가
>   `users/${aws:SourceIdentity}/`로 제한됩니다. 다른 참가자의 노트북이나
>   `.av30-progress.env`(그 사람의 대시보드 토큰이 들어 있음)를 읽을 수 없고, 다른 참가자의
>   홈에 `.bashrc`나 IPython 시작 파일을 심을 수 없으며(앱은 시작할 때마다 `users/<id>/`를
>   홈으로 복사합니다), 다른 참가자의 산출물을 지울 수도 없습니다. source identity가 없는
>   세션은 `users/` 전체가 거부됩니다(fail-closed).
> - **M11 파이프라인과 M12 학습 작업**(`av30-data-pipeline-<id>`,
>   `av30-m12-distributed-<id>-*`).
> - **프라이빗 스페이스.** `UpdateSpace`와 Studio 자체의 presigned URL은 호출한 사람의
>   스페이스와 프로필로 제한됩니다.
>
> **여전히 공유되는 것.** 코호트는 서로를 공격하지 않는 사람들이라고 전제하고, 아래
> 위치에는 다른 참가자가 보거나 바꾸면 안 되는 것을 두지 마세요.
> - 스페이스, 앱, 프로필의 Describe/List: 누가 무엇을 실행 중인지 누구나 볼 수 있습니다.
> - `*`에 대한 `CreateApp`/`DeleteApp`: boto3를 쓰면 다른 참가자의 앱을 시작하거나 중지할
>   수 있습니다(좁힐 수 있는지는 §8의 4b 단계에서 판단합니다).
> - OpenSearch Serverless: `collection/*`에 `aoss:APIAccessAll`이 허용되어 있고 M4의
>   data-access policy가 공유 역할을 principal로 지정하므로, 다른 참가자의 M4 컬렉션을
>   읽거나 바꿀 수 있습니다.
> - Processing job(`processing-job/*`): M11 단계 작업의 이름은 Pipelines 서비스가 프로필
>   없이 붙이므로, 다른 참가자의 단계 작업을 조회하거나 중지할 수 있습니다.
> - 학습 작업의 한 가지 예외: `av30-m12-distributed-<id>-*`는 id가 `<id>-<추가 문자>`인
>   프로필에도 일치합니다(예: `kim-abc123`과 `kim-abc123-q1w2e3`).
> - 공유 데이터 버킷은 누구나 읽을 수 있고, CloudWatch Logs `/aws/sagemaker/*`에는 누구나
>   쓸 수 있습니다(로그를 읽을 수 있는 참가자는 없습니다).
> - M10 자가 실행용 EC2 인스턴스 프로필(§7)을 만들었다면 `users/*/m10/*`에 쓸 수 있습니다.
> - 참가자 토큰은 만료되지 않고 교체 수단도 없습니다. 다시 발급하려면 사용자를 삭제한 뒤
>   새로 만드세요.
>
> 관리자도 같은 제한을 받습니다. Studio 앱에서는 관리자 자신의 프로필도 자기 프리픽스에만
> 접근합니다. 참가자 프리픽스는 워크스테이션에서 관리자 자격 증명으로 확인하세요.
>
> 이 모든 것은 SageMaker가 새 Studio의 JupyterLab 세션, 라이프사이클 스크립트, M11/M12
> 작업에 실제로 source identity를 붙인다는 전제 위에 있습니다. AWS 문서에 나와 있는
> 동작이지만 실제 배포로만 증명할 수 있으니, 새 스택마다 §8의 교차 사용자 확인을 실행하세요.
> 이 확인을 통과하면 §6.3의 전제 조건("사용자 워크스페이스 버킷이 사용자별로 격리된 뒤")이
> 이후에 쓰이는 파일에 대해 충족됩니다. 업그레이드 전에 관리자 프리픽스에 심어진 파일은 그대로
> 남으며, 이 경우는 §6.3에서 다룹니다.

> **이 가이드의 ID에 관한 참고.** `<aws-account-id>`나
> `us-west-2`가 보이는 곳(버킷 이름, ARN, 쿼터 "current" 값, CLI 예시)은 모두
> 레퍼런스 배포에서 가져온 것입니다. 스택에 **하드코딩되어 있지 않습니다** —
> 계정은 당신의 자격 증명에서, 리전은 배포 시점의 `$AWS_REGION`에서 가져옵니다(§5).
> §1.5에서 당신의 값을 고른 다음, 예시를 당신의 값으로
> 치환해서 읽으세요.
- **13개 노트북 M0–M12**. 대부분 참가자 셀프서비스이며, 일부는 일회성
  관리자 사전 작업(모델, 데이터셋, M10 레퍼런스 실행)이 필요합니다. §4의 매트릭스 참고.

---

## 1. 이벤트 전 타임라인

| 시점 | 작업 | 리드 타임이 필요한 이유 |
|---|---|---|
| **D−7** | GPU + 작업(job) 쿼터 증설 요청(§2) | 승인에 24–48시간, 때로는 그 이상 소요 |
| **D−7** | 관리자 계정에서 게이트된 HF 라이선스를 모두 수락(§3) | 즉시 처리되지만, 하나를 빠뜨리기 쉬움 |
| **D−3** | `cdk bootstrap` + `deploy.sh`(§5) | ~25분; 문제 수정할 여유 확보 |
| **D−3** | nuScenes 스테이징 + 모델 프리캐시 + HF 오프라인 캐시(§6) | 백그라운드 전송 30–90분 |
| **D−2** | M10을 사용한다면 EC2에서 M10 AlpaSim 레퍼런스 평가 실행(§6.4) | ~$30, GPU 박스에서 수십 분–2시간 |
| **D−1** | 노트북 템플릿 업로드, 사용자 1명 엔드투엔드 스모크 테스트(§8) | 프로비저닝/쿼터 누락 포착 |
| **D0** | 참가자 프로비저닝, 대시보드 링크 배포(§9), 모니터링(§10) | — |
| **D+0** | 사용자 삭제, **HF 토큰 폐기, NGC 키 로테이션**(§12) | 보안 위생 |

---

## 1.5. AWS 계정과 리전 선택하기 (가장 먼저 하세요)

이 플랫폼은 **계정 및 리전에 종속되지 않습니다** — 스택 어디에도 레퍼런스
계정(`<aws-account-id>`)이나 리전(`us-west-2`)을 고정하지 않습니다. 모든 것이 배포
시점에 파생됩니다: **계정**은 당신의 AWS 자격 증명에서, **리전**은 §5에서 export하는
`AWS_REGION`에서 옵니다. 쿼터를 요청하기(§2) 전에 둘 다 결정하세요. GPU 쿼터와
게이트된 모델 가용성은 계정별 **및** 리전별이기 때문입니다.

**계정 선택**
- **당신이 관리자인** 계정(또는 역할, Cognito 풀, CloudFront, VPC, SageMaker
  도메인을 생성할 IAM 권한이 있는 계정)을 사용하세요. `deploy.sh`는
  `cdk bootstrap`을 실행하며, 이는 계정+리전당 한 번 상승된 권한을 필요로 합니다.
- **전용 / 샌드박스** 계정을 선호하세요: 스택은 Studio 도메인,
  버킷, WAF를 생성하며, 티어다운(`scripts/teardown.sh`)은 계정이 무관한 프로덕션
  리소스와 공유되지 않을 때 가장 깔끔합니다.
- `deploy.sh`를 실행할 때 자격 증명이 가리키는 계정이 곧 배포되는 곳입니다.
  배포 전에 확인하세요:
  ```bash
  aws sts get-caller-identity --query Account --output text
  ```
  이 계정 id가 모든 버킷 이름과 ARN의 `<account>` 자리를 채웁니다.

**리전 선택** — 이것이 계정보다 더 중요합니다. GPU
용량과 모델 액세스를 게이팅하기 때문입니다:
- **GPU 가용성은 리전마다 다릅니다.** 이 랩이 사용하는 GPU 계열(`g5`,
  `g6`, 그리고 선택적으로 `p4d`)은 **모든** 리전에 있지는 않으며, 쿼터 승인은
  리전별입니다. GPU 용량이 풍부한 리전을 고르세요 — `us-west-2`(Oregon)와
  `us-east-1`(N. Virginia)이 가장 안전합니다.
- **레이턴시:** 참가자와 가까울수록 인터랙티브 Studio UI에 좋지만,
  둘 사이에서는 용량이 우선입니다 — GPU를 확보할 수 없는 리전은 쓸모없습니다.
- **데이터 레지던시 / 조직 정책:** 조직이 리전을 제한한다면, 위의 GPU 계열을
  여전히 갖춘 준수 리전을 고르세요.
- **모델 + 데이터셋 스테이징은 리전 로컬입니다.** HF/모델 캐시와 nuScenes는
  **당신이 고른 리전의** 공유 버킷에 스테이징됩니다(§6); 나중에 리전을 옮기면
  다시 스테이징해야 합니다(`README.md`의 "Region portability" 참고).

**후보 리전이 필요한 용량을 갖췄는지 확인**한 뒤 확정하세요(어떤 계열에 대해
빈 출력이 나오면 그 리전에서 제공되지 않는 것입니다):
```bash
export AWS_REGION="us-west-2"     # your candidate
# GPU instance types offered for SageMaker Studio apps in this region:
aws service-quotas list-service-quotas --service-code sagemaker --region "$AWS_REGION" \
  --query "Quotas[?contains(QuotaName,'Studio JupyterLab Apps running on ml.g6') || contains(QuotaName,'Studio JupyterLab Apps running on ml.g5')].{Name:QuotaName,Current:Value,Code:QuotaCode}" \
  --output table
```

계정 + 리전이 정해지면 `AWS_REGION`을 export하고(§5 전체에서 사용),
§2의 쿼터를 **그 리전에서** 요청하고, 캐시를 **그 리전에**
스테이징하세요(§6). 나중에 둘 중 하나라도 변경하면 재부트스트랩, 재쿼터,
재스테이징을 뜻하니 — 지금 확정하세요.

---

## 2. 서비스 쿼터 (D−7에 요청)

두 종류의 쿼터가 중요합니다. README의 쿼터 표가 첫 번째를 다루며,
아래의 **작업(job) 쿼터**는 놓치기 쉽고 방 하나 전체 규모에서 M12/M11을 막습니다.

### 2a. Studio JupyterLab App 쿼터 (인터랙티브 노트북)
Service Quotas 콘솔에서 "**Studio JupyterLab Apps running on**"을 검색하세요. 아래 표는
**사용자 대시보드의 Instance Options**가 제공하는 타입(권장 + 대안) 그대로이고, API도 이
목록을 강제합니다. `cdk synth`가 `web/user/src/data/pipeline-config.ts`에서 목록을 읽어 이
리전이 판매하는 타입만 남기고, `change_instance`는 그 밖의 타입을 API로 직접 호출하더라도
실행 중인 앱을 건드리기 전에 400으로 거부합니다. Studio 안에서도 실행 역할이 같은 목록을
적용합니다(아래 참고). 목록을 바꾸려면 이 파일을 고친 뒤 스택을 다시 배포하세요. 쿼터 **코드는 리전과 무관하지만**(us-west-2 / ap-northeast-2 / eu-west-1에서
동일함을 확인), **값은 그렇지 않으며** 어떤 타입에 쿼터가 존재하는지조차 리전마다 다릅니다.

> **Studio에서도 같은 목록이 적용됩니다.** 참가자 실행 역할에는 명시적 Deny
> `DenyNonParticipantInstanceTypes`가 있습니다. `sagemaker:CreateApp`과
> `sagemaker:UpdateSpace`에서 요청한 `sagemaker:InstanceTypes`에 이 목록(과 JupyterServer
> 앱의 인스턴스 타입인 `system`) 밖의 값이 하나라도 있으면 거부합니다. synth가 API와 같은
> 목록으로 만들기 때문에, Studio의 **Run space**나 노트북의 boto3로 `ml.p5.48xlarge`를
> 요청해도 `AccessDenied`가 납니다. 이 Deny는 도메인의 모든 Studio 세션에 걸리며, 관리자
> 자신의 프로필도 예외가 아닙니다. API의 Lambda와 워크스테이션의 관리자 자격 증명(예:
> `scripts/grab_gpu_instance.py`)에는 영향이 없습니다. 배포 전부터 다른 타입으로 실행 중이던
> 앱은 그대로 계속 돕니다.
>
> **아직 실배포로 확인하지 못했습니다.** 이 Deny는 인스턴스 타입이 들어 있는 요청에만
> 적용됩니다. AWS 문서는 두 액션 모두에 이 키가 있다고 적고 있지만, 스페이스의
> `DefaultResourceSpec`만 바꾸는 `UpdateSpace`나 `ResourceSpec` 없이 보낸 `CreateApp`(스페이스
> 기본값을 씀)에서도 SageMaker가 이 키를 채우는지는 문서에 없습니다. 둘 다 채우지 않는다면
> "기본값을 바꾼 뒤 ResourceSpec 없이 시작"하는 방법으로 여전히 우회할 수 있고, 그때는 다시
> 쿼터만이 그 타입을 막습니다. 아래 점검이 스택에서 통과할 때까지는, 제공할 생각이 없는 타입의
> 쿼터를 요청하지 마세요(p4d 행 참고). 점검은 §8 7단계(그 스페이스를 어차피 지웁니다) 직전에,
> §8 테스트 사용자의 JupyterLab 터미널에서 실행합니다. 1번 점검이 아무것도 띄우지 않도록 앱은
> 켜 둔 채로 두세요. `ml.c5.large`는 목록에 없는 저렴한 타입입니다.
> ```bash
> DOMAIN_ID=$(python3 -c "import json;print(json.load(open('/opt/ml/metadata/resource-metadata.json'))['DomainId'])")
> SPACE="$USER_PROFILE-space"
> # 1. AccessDenied가 나와야 합니다. ResourceInUse가 나오면 Deny가 적용되지 않은 것입니다(아무것도 뜨지 않음).
> aws sagemaker create-app --domain-id "$DOMAIN_ID" --space-name "$SPACE" \
>   --app-type JupyterLab --app-name default --resource-spec InstanceType=ml.c5.large
> # 2. AccessDenied가 나와야 합니다. 다른 결과라면 이 요청에서는 키가 채워지지 않은 것입니다.
> aws sagemaker update-space --domain-id "$DOMAIN_ID" --space-name "$SPACE" \
>   --space-settings '{"JupyterLabAppSettings":{"DefaultResourceSpec":{"InstanceType":"ml.c5.large"}}}'
> ```
> 이어서 허용된 경로가 그대로 동작하는지 확인합니다. 목록에 있는 타입으로 Studio의
> **Run space**(§8 4b단계), 그리고 Studio 스페이스 페이지에서 스토리지 변경입니다. 둘 중
> 하나라도 *explicit deny*로 실패하면 `infra/av30_constructs/sagemaker.py`에서
> `DenyNonParticipantInstanceTypes` 문장을 지우고 다시 배포하세요. API의 상한은 이 문장과
> 무관하게 동작합니다.

**GPU 주력: `ml.g5.12xlarge`(4× A10G, 96 GB).** 대시보드가 이제 M2, M3와 무거운 네 모듈
(M5, M6, M8, M9)에 권장하는 타입이며, 근거는 모두 실측입니다. `ml.g6.24xlarge`와 기하 구조가
*동일*하고(`describe-instance-types`가 둘 다 4 GPU × 22,888 MiB로 보고하므로 모든 GPU당 VRAM
게이트가 같은 분기를 탑니다), 두 리전 모두에서 더 싸고($7.09 vs $8.34 — us-west-2,
$8.72 vs $10.26 — ap-northeast-2), 쿼터가 더 높고(us-west-2 5 vs 2, ap-northeast-2 5 vs **0**),
랩이 캡처한 통과 실행에서 닿을 수 있는 계열입니다. 무엇이 실측인지 정확히 적습니다.
`examples/notebooks-with-outputs.tar.gz`에는 이제 **4× NVIDIA A10G**(즉 g5.12xlarge 그
자체)에서 돌린 M0–M12 전 구간 실행이 담겨 있고, M9는 minADE 0.3779 `Status: PASS`입니다.
따라서 이 인스턴스 자체가 직접 실측이며, 더 이상 지오메트리 논증에 기대지 않습니다.
(이전 번들은 같은 파이프라인을 **4× NVIDIA L4**에서 M9 minADE 0.3805로 기록했고,
`docs/en/ALPAMAYO_M9.md:181-187`은 M9의 **8× A10G**(g5.48xlarge) 통과를 따로 기록합니다.
둘 다 여전히 실측이며, 다만 공개 번들의 내용이 아닐 뿐입니다.) 그 실행이 남긴 단서 하나:
M7의 novel-view 렌더는 `rc=1`로 끝나 **프레임 0개**를 냈습니다 — 학습은 완료됐고 렌더는
안 됐습니다. g5.12xlarge를 선호하는 이유는 쿼터와 가격입니다. 대시보드에서
네이티브 해상도 / 전체 720p로 가는 경로는 `ml.p4d.24xlarge` 하나뿐입니다. 쿼터를 요청하기 전에
아래 표의 p4d 행을 먼저 읽어 보세요.

> **아래 `us-west-2` 열은 당신의 리전이 아닙니다.** 쿼터는 (계정 × 리전) 단위 사실입니다:
> `ml.g6.*` 계열 전체가 ap-northeast-2에서 판매되지만 쿼터는 **0**이고, `ml.g7e.*`/`ml.p5.*`는
> 아예 판매되지 않습니다. 실제 값은 `./scripts/check_quotas.py --region <대상>`으로 확인하세요 —
> 부족한 항목마다 정확한 `request-service-quota-increase` 명령을 출력합니다. (쿼터 0인 타입은
> 이제 수락된 뒤 시작 실패하는 대신 대시보드가 앞단에서 거부합니다.)

| 인스턴스 | 쿼터 코드 | us-west-2 (2026-09) | 10인 방 최소치 | 대시보드에서의 역할 |
|---|---|---|---|---|
| ml.t3.medium | L-71FAF417 | 2500 | ≥20 | 모든 CPU 노트북(M0, M1, M10, M4, M12, M11)의 **권장** |
| ml.t3.large | L-2733D4D5 | 30 | ≥0 | CPU 대안 |
| ml.t3.xlarge | L-61F9C762 | 30 | ≥0 | CPU 대안(M1) |
| ml.m5.large | L-3BDCD216 | 11 | ≥0 | CPU 대안 |
| ml.m5.xlarge | L-77B8159A | 11 | ≥0 | CPU 대안(M4) |
| ml.g5.xlarge | L-988CE6C5 | 5 | ≥5 | M7(Nerfstudio)의 **권장** |
| ml.g5.2xlarge | L-F73C7DB9 | 5 | ≥0 | M7 대안 |
| ml.g5.4xlarge | L-81940D85 | 5 | ≥0 | M7 대안 |
| **ml.g5.12xlarge** | **L-8D2ED7BF** | **5** | **≥5** | **권장 주력 — M2, M3, M5, M6, M8, M9(4× A10G, 96 GB)** |
| ml.g5.24xlarge | L-F087CCFC | 2 | ≥1 | M2/M3/M5–M9 대안 |
| ml.g5.48xlarge | L-83AB5D73 | 2 | ≥1 | M2/M3/M5–M9 대안 / OOM 폴백 |
| ml.g6.xlarge | L-AABA5942 | 5 | ≥0 | M7 대안(L4) — **ap-northeast-2에서 0** |
| ml.g6.2xlarge | L-92D1521D | 5 | ≥0 | M7 대안(L4) — **ap-northeast-2에서 0** |
| ml.g6.4xlarge | L-692B8304 | 5 | ≥0 | M7 대안(L4) — **ap-northeast-2에서 0** |
| ml.g6.12xlarge | L-962247BA | 2 | ≥0 | M2/M3 용량 폴백(4× L4, 96 GB) — **ap-northeast-2에서 0** |
| ml.g6.24xlarge | L-8ACE1754 | 2 | ≥0 | M2/M3 대안(4× L4, 96 GB) — g5.12xlarge와 기하 동일하나 더 비쌈; **ap-northeast-2에서 0** |
| ml.p4d.24xlarge | L-AD63F1D2 | 2 | 0 (의도한 경우만 증설) | M2, M3, M5, M6, M8, M9 대안 — 유일한 네이티브 해상도 경로(8× A100, us-west-2 기준 약 $25.25/시간). **기본값은 0이며, 제공할 생각이 없다면 그대로 두세요** — 0이면 대시보드가 실행 중인 앱을 건드리기 전에 거부합니다 |

> **제공하지 않는 타입: `ml.g7e.*`, `ml.p5.*`, `ml.g6.48xlarge`**, 그리고 표에 없는 모든
> 타입입니다. `change_instance`가 400으로 거부하므로 대시보드를 위해 쿼터를 받을 필요는
> 없습니다. g7e는 네이티브 해상도로 가는 가장 저렴한 경로(96 GB 카드 1장, 약 $4.20/시간)이지만
> ap-northeast-2에서는 Studio용으로 판매되지 않고 이 랩에서 실행해 본 모듈도 없어서 목록에
> 넣지 않았습니다. Studio에서도 이 타입들은 거부됩니다(위 참고). 점검 결과 Deny가 닿지 않는
> 경로가 있다면, 그 경로에서는 쿼터가 마지막 방어선입니다.

방 규모 산정: 각 모듈의 **권장** 인스턴스를 동시 참가자 수 이상으로 요청하고,
사람들을 유도할 한두 개의 폴백에 대해서는 표에 표시된 최소치 이상을 요청하세요(용량
오류가 나면 대시보드에 대안이 표시됩니다). 모든 대안에 대해 쿼터가
**필요하지는 않습니다** — 실제로 방에 사용하도록 유도할 것만 필요합니다.
GPU 모듈을 **g5.12xlarge**로 표준화한다면(권장 — 무거운 모듈 권장값 중 us-west-2와
ap-northeast-2 양쪽에서 0이 아닌 유일한 타입), 그것만 인원수 이상으로
요청하면 되고, p4d는 제공할 생각이 없다면 기본값 0으로 두세요.

### 2b. SageMaker **작업(job)** 쿼터 (M12 및 M11 — 사람들이 잊는 것들)
M12는 실제 **트레이닝 작업**을 제출하고 M11은 별도의 관리형 인스턴스(노트북의
인스턴스가 아님)에서 실제 **프로세싱 작업**을 실행합니다. 이들은 자체
쿼터가 있습니다:

| 쿼터 | 코드 | 검증된 값 (레퍼런스 배포 예시: us-west-2) | 필요한 곳 |
|---|---|---|---|
| **training** 작업 사용을 위한 ml.m5.xlarge | L-CCE2AFA6 | 30 | M12(≥2 필요 — 2노드 작업) |
| **processing** 작업 사용을 위한 ml.m5.xlarge | L-0307F515 | 16 | M11(≥1 필요 — 순차 3단계 DAG) |

둘 다 오늘 워크샵 필요치를 넉넉히 상회하지만 **확인하세요** — 어느 하나라도
당신의 계정에서 0이면, 노트북이 열리더라도 M12/M11은 작업 제출 시점에 실패합니다.
여기서 `ml.g5.*` **processing** 작업 쿼터는 0인데, M11은 설계상 CPU에서 실행되므로 괜찮습니다.

```bash
# Check everything at once:
aws service-quotas list-service-quotas --service-code sagemaker --region "$AWS_REGION" \
  --query "Quotas[?contains(QuotaName,'Studio JupyterLab Apps') || contains(QuotaName,'for training job') || contains(QuotaName,'for processing job')].{Name:QuotaName,Value:Value,Code:QuotaCode}" \
  --output table

# Request an increase (대시보드가 실제로 권장하는 두 타입을 10으로 — 만석 기준):
aws service-quotas request-service-quota-increase \
  --service-code sagemaker --quota-code L-8D2ED7BF --desired-value 10 --region "$AWS_REGION"   # ml.g5.12xlarge
aws service-quotas request-service-quota-increase \
  --service-code sagemaker --quota-code L-988CE6C5 --desired-value 10 --region "$AWS_REGION"   # ml.g5.xlarge
```

> 위의 쿼터 **코드**는 모든 리전에서 동일합니다. 실제로 배포할 곳에
> 용량을 요청하도록 **당신의** `$AWS_REGION`(§5)에 대해 실행하세요.
> GPU 가용성은 리전마다 다릅니다 — 선택은 §1.5 참고.

---

## 3. 게이트된 Hugging Face + NGC 라이선스 (D−7에 수락)

**당신의 관리자 HF 계정**에서 각 항목마다 "Agree and access repository"를 클릭하세요. 여기가
라이선스를 수락하는 유일한 곳입니다 — 참가자는 이것을 절대 보지 않습니다.

| 리포 | 필요한 곳 | 라이선스 |
|---|---|---|
| nvidia/Cosmos-Reason1-7B | M2 | NVIDIA Open Model (게이트 아님, 단 로그인 필요) |
| nvidia/Cosmos-Guardrail1 | M5, M6 | NVIDIA Open Model |
| nvidia/Cosmos-Transfer2.5-2B | M5 | NVIDIA Open Model |
| nvidia/Cosmos-Predict2.5-2B | M6 | NVIDIA Open Model |
| nvidia/Alpamayo-1.5-10B | M9, M10 | **비상업용**(연구/평가 전용) |
| nvidia/Cosmos-Reason2-8B | M9, M10 (숨겨진 Alpamayo 백본) | NVIDIA Open Model |
| nvidia/PhysicalAI-Autonomous-Vehicles | M9 (데모 클립) | NVIDIA AV Dataset (12개월 만료) |
| nvidia/PhysicalAI-Autonomous-Vehicles-NuRec | M10 (AlpaSim 장면) | NVIDIA AV NuRec Dataset |

**M10은 NGC도 필요합니다**(HF와 별개): NuRec 렌더러 이미지
`nvcr.io/nvidia/nre/nre-ga:26.04`. 키는
`https://org.ngc.nvidia.com/setup/api-key`에서 받으세요. (테스트에서는 이 이미지가
익명으로 풀 가능했지만, 바뀔 경우를 대비해 키를 준비해 두세요.)

> 모든 것을 수락했다면 `export HF_TOKEN=hf_...`를 한 번 설정하세요; §6에서 사용합니다.

---

## 4. 모듈별 관리자 사전 작업 매트릭스

이것이 가이드의 핵심입니다 — **어떤 모듈이 관리자 작업을 필요로 하고, 어떤 모듈이 스스로 실행되는가.**

| 모듈 | 컴퓨트 (참가자가 보는 것) | 필요한 관리자 사전 작업 | 문서 |
|---|---|---|---|
| M0 Overview | CPU t3.medium | 없음 | — |
| M1 Data Exploration | CPU t3.medium | nuScenes-mini 스테이징(§6.1) | — |
| M2 Cosmos Reason | GPU g5.12xlarge (또는 g6.24xlarge) | 모델을 `model-cache/`에 프리캐시(§6.2) | — |
| M3 Cosmos Curator | GPU g5.12xlarge (또는 g6.24xlarge) | (M2 출력 사용; 추가 캐시 없음) | — |
| M4 OpenSearch | CPU t3.medium | (M2 출력 사용; 추가 캐시 없음) | — |
| M5 Cosmos Transfer | GPU g5.12xlarge (720p는 p4d.24xlarge) | HF **오프라인 캐시**를 `hf-cache/hub/`로(§6.3) | [COSMOS_M5_M6.md](COSMOS_M5_M6.md) |
| M6 Cosmos Predict | GPU g5.12xlarge (네이티브는 p4d.24xlarge) | HF 오프라인 캐시(§6.3) | [COSMOS_M5_M6.md](COSMOS_M5_M6.md) |
| M7 Nerfstudio | GPU g5.xlarge (또는 g6.xlarge) | gsplat CUDA 빌드가 `scripts/setup_gsplat_env.sh`를 통해 세션마다 실행(§11) | 아래 §11 참고 |
| M8 Cosmos Reason SFT | GPU g5.12xlarge (또는 g6.24xlarge) | (M2의 `model-cache/cosmos-reason1/` 재사용; 추가 캐시 없음) | — |
| M9 Alpamayo VLA | GPU g5.12xlarge (또는 p4d.24xlarge) | HF 오프라인 캐시 **+ 데모 클립**(§6.3) | [ALPAMAYO_M9.md](ALPAMAYO_M9.md) |
| M10 AlpaSim | CPU t3.medium (비주얼라이저) | **EC2에서 레퍼런스 평가 1회 실행**(§6.4) | [ALPASIM_M10.md](ALPASIM_M10.md) |
| M11 Pipeline | CPU t3.medium (실제 SageMaker Pipeline 실행) | 없음 (작업 쿼터 §2b) | [PIPELINE_M11.md](PIPELINE_M11.md) |
| M12 HyperPod | CPU t3.medium (실제 DDP 작업 제출) | 없음 (작업 쿼터 §2b) | [HYPERPOD_M12.md](HYPERPOD_M12.md) |

**요점:** 필요한 일회성 관리자 캐시는 **nuScenes(M1) + model-cache
(M2) + hf-cache(M5/M6/M9) + M9 데모 클립**이며, M10을 실행한다면 여기에
**M10 레퍼런스 실행**이 추가됩니다. M12와 M11은 **캐시가 필요 없습니다** — §2b의 작업
쿼터만 있으면 됩니다.

---

### 4b. 실제 IAM 축소를 여는 1분 확인 (무료)

현재 공용 실행 역할에 `CreateApp` / `DeleteApp` 이 `resources=["*"]` 로 부여돼 있습니다. 즉 터미널을
가진 참가자가 CLI로 **남의** 스페이스에 앱을 만들거나 지울 수 있습니다(대시보드에는 그런 경로가
없습니다). `${sagemaker:UserProfileName}` 소유자 조건으로 좁히는 것이 해법인데, 그 정책 변수가
요청 시점에 실제로 치환되어야만 가능하고 **시뮬레이션으로는 알 수 없습니다**:

* `iam:SimulateCustomPolicy` 는 `${sagemaker:*}` 변수를 치환하지 **않습니다**. 변수가 들어간 모든
  케이스에 `implicitDeny` 를, 리터럴에는 `allowed` 를 돌려주므로 어느 쪽 증거도 되지 못합니다.
* Studio 밖에서 역할을 assume 해도 마찬가지입니다. 앱 컨텍스트가 없어 변수가 비고, `Resource` 안의
  미해결 변수는 아무것도 매칭하지 않아 fail-closed 로 떨어집니다. 역시 정보가 없습니다.

유일하게 믿을 수 있는 검사는 라이브 검사이고, 비용은 0입니다:

1. 참가자 스페이스를 **그 참가자로** 열고 **Run space**, 이어서 **Open JupyterLab** 을 클릭합니다.
2. **`AccessDenied` 가 없으면** ⇒ 요청 시점에 변수가 치환됨 ⇒ `infra/av30_constructs/sagemaker.py` 의
   `CreateApp`/`DeleteApp` 을 `resources=["*"]` 에서 `SageMakerOwnPrivateSpaceUpdate` 가 이미 쓰는
   소유자 조건으로 바꿔도 안전합니다.
3. **`AccessDenied` 가 나면** 좁히지 **마세요**. 미해결 정책 변수는 fail-closed 이므로, 이 증거 없이
   조이면 참가자 전원이 자기 워크스페이스에서 락아웃됩니다.

실행했으면 결과를 여기에 기록해서 다음 관리자가 다시 유도하지 않게 하세요.

---

## 5. 플랫폼 배포 (D−3)

> **리전은 명시적이며, 재배포에는 가드가 걸려 있습니다.** `--region`을 넘기세요 — 배포 경로
> 어디에도 기본값이 없습니다. 기존 스택을 **업데이트**할 때 `deploy.sh`가 라이브 상태를 읽고
> 파괴적인 동작을 조용히 수행하는 대신 **거부**합니다: 스택의 `Owner` 태그가 바뀌는 배포
> (Studio 도메인이 교체되어 모든 참가자 워크스페이스가 사라지고 EFS가 고아가 됨)와,
> `HOSTED_UI_DOMAIN_EXISTS`의 잘못된 조합(이미 존재하는 비관리 Cognito 도메인을 선언하거나,
> 반대로 스택이 관리 중인 도메인을 삭제하게 되는 경우) 양쪽을 막습니다. 거부할 때마다 다시
> 실행할 정확한 명령을 출력합니다. **새 리전은 이 플래그가 전혀 필요 없습니다.**
> 리전을 **추가**하려면 [../en/ADDING_A_REGION.md](../en/ADDING_A_REGION.md) 를 보세요
> (한국어: [ADDING_A_REGION.md](ADDING_A_REGION.md)).

> **사용자별 S3 격리(§0) 이전에 배포한 스택을 업그레이드할 때: 먼저 모든 앱을 중지하세요.**
> 이 버전은 Studio 도메인의 `ExecutionRoleIdentityConfig`를 `USER_PROFILE_NAME`으로 바꾸는데,
> SageMaker는 도메인에 실행 중인 앱이 하나도 없을 때만 이 변경을 받아들입니다. 라이브 도메인에
> 아직 이 설정이 없으면 `deploy.sh`가 도메인의 앱 목록을 조회하고, `Deleted`나 `Failed`가 아닌
> 앱이 하나라도 있으면 앱마다 `delete-app` 명령을 출력하고 **배포를 거부합니다**. 스택, 도메인,
> 앱 목록 중 하나라도 조회하지 못해도 추측하지 않고 거부합니다. 앱을 중지해도 홈 볼륨과 S3
> 데이터는 유지되며, 도메인은 같은 자리에서 갱신됩니다(domain id 그대로). 그다음:
> - 참가자는 앱을 다시 시작합니다. 전환 전에 시작한 세션에는 source identity가 없어서 자기
>   `users/<id>/`에도 `AccessDenied`가 납니다(§13).
> - 예전 정책으로 이미 코호트를 운영한 스택이라면, 어떤 참가자든 다른 참가자의
>   `.av30-progress.env` 토큰을 복사해 갔을 수 있습니다. 신경 쓰인다면 해당 사용자를 삭제한 뒤
>   다시 만들어 토큰을 새로 발급하세요.
> - **이전 커밋을 재배포하는 방식으로 롤백하지 마세요.** trust policy 변경 이전의 커밋은
>   `sts:SetSourceIdentity`를 빼 버리는데, 도메인은 여전히 source identity를 요구하므로 앱과
>   작업 생성이 실패합니다. 롤백은 `execution_role_identity_config="DISABLED"`와 예전 S3
>   statement를 명시한 커밋으로 하고, trust statement는 그대로 두고, 모든 앱을 중지한 상태에서
>   배포하세요.
> - 아직 확인하지 못한 점: 이후 도메인을 바꾸는 배포(LCC 변경, `-c idle_timeout_minutes=...`)
>   때마다 모든 앱을 중지해야 하는지. 가드는 처음 전환할 때만 확인합니다. 그런 배포가 도메인
>   갱신 단계에서 실패하면 앱을 중지하고 다시 실행하세요.


```bash
# 필수 환경 변수
export ADMIN_EMAIL="you@example.com"       # Cognito 관리자 계정이자 SNS 알림 수신 주소
export REGION="us-west-2"                  # 직접 고른 리전(§1.5). 아래 명령에 명시적으로 넘깁니다
export AWS_REGION="$REGION"                # §6의 시딩 스크립트가 읽습니다
export HF_TOKEN="hf_..."                    # §6의 캐싱 단계에서 사용
# 선택: 관리자 API를 내 IP/CIDR로 제한(참가자 경로는 그대로 열려 있음)
export ADMIN_IP_ALLOWLIST="203.0.113.0/24" # 기본값 0.0.0.0/0 = WAF 없음

# CDK 부트스트랩(계정 + 리전당 1회)
cd infra && source .venv/bin/activate && pip install -r requirements.txt
npx cdk bootstrap aws://$(aws sts get-caller-identity --query Account --output text)/$REGION
cd ..

# 이 리전의 인스턴스 요금표 생성(필수 — 없으면 Lambda가 다른 리전 가격을 보여 주는 대신
# import 시점에 예외를 던집니다)
./scripts/refresh_instance_rates.py --region "$REGION" --merge

# 스택 배포 + 두 대시보드 빌드/업로드(~25분). 리전은 명시적으로 지정합니다.
./scripts/deploy.sh --region "$REGION"
```

`deploy.sh`는 `ADMIN_EMAIL`과 `ADMIN_IP_ALLOWLIST`를 `--context`를 통해 CDK에 전달합니다
(**env 변수가 아님** — `deploy.sh`를 건너뛰고 `cdk deploy`를 직접 실행한다면
`--context admin_email=...`를 반드시 전달해야 하며, 그렇지 않으면 SNS 예산 경보가
플레이스홀더로 되돌아갑니다). 끝에서 **Admin Dashboard URL**과 **API endpoint**를 출력합니다.

**`ADMIN_IP_ALLOWLIST`가 막는 범위.** 이 값을 지정하면 API Gateway 스테이지에 WAF WebACL이
붙고, 목록 밖 IP에서 오는 **관리자 API** 호출을 차단합니다. 참가자 경로
(`/presigned-url/{userId}`, `/sessions/{id}/instance-type|storage|progress|app-status`,
`/modules/{id}/instance-options`)는 어느 IP에서든 허용됩니다. 참가자 대시보드는 각 참가자의
브라우저에서 돌고, 노트북은 SageMaker가 관리하는 egress로 진행 상황을 보내기 때문입니다.
물론 이 경로들도 참가자 토큰이 있어야 호출됩니다. 두 CloudFront 배포에는 WAF가 없으므로, 목록 밖
IP에서도 관리자 대시보드와 Cognito 로그인 화면은 열립니다. 다만 데이터 호출은 모두
**"Failed to fetch"**로 실패하고, 브라우저 Network 탭에서 `OPTIONS` preflight가 **403**으로
보입니다. 관리자 호출은 항상 `Authorization`과 JSON `Content-Type`을 보내므로 브라우저가
매번 preflight를 하기 때문입니다. 해결하려면 내 IP를 목록에 추가하세요. **참가자나 SageMaker
IP 대역은 넣지 마세요.** 넣을 필요도 없고, 넣으면 그 주소들에서 관리자 API로 가는 길만 열립니다.

**어떤 IP를 넣어야 하나.** 터미널이 아니라 **브라우저**가 AWS로 나가는 주소를 넣으세요. 회사
프록시나 VPN을 쓰면 브라우저 트래픽이 다른 주소로 나가는 경우가 많습니다. 관리자 대시보드를 열
**브라우저에서** https://checkip.amazonaws.com 을 열어 확인하고, 관리자마다 접속할 모든
네트워크(사무실, VPN, 집)를 쉼표로 구분한 CIDR로 넣으세요. 프록시의 나가는 주소는 바뀔 수
있으며, 바뀌면 위의 "Failed to fetch" 증상이 나타납니다. 목록을 바꾸려면 새 값으로 `deploy.sh`를
다시 실행하면 IP set이 그 자리에서 갱신됩니다.

**이후 배포에서도 유지하기.** `ADMIN_IP_ALLOWLIST`를 비워 두면 `0.0.0.0/0`이 되어 WAF가
삭제됩니다. 그래서 스택에 이미 허용 목록이 있으면 `deploy.sh`는 이 변수 없이 실행되기를
**거부**하고, 다시 쓸 현재 목록을 보여 줍니다. 허용 목록을 일부러 없애려면
`ADMIN_IP_ALLOWLIST=0.0.0.0/0`을 명시하세요.

**관리자 로그인 생성**(사용자 이름은 이메일이어야 함 — Cognito가 이메일을
로그인 별칭으로 사용):
```bash
aws cognito-idp admin-create-user \
  --user-pool-id <POOL_ID_FROM_DEPLOY_OUTPUT> \
  --username "$ADMIN_EMAIL" \
  --user-attributes Name=email,Value=$ADMIN_EMAIL Name=email_verified,Value=true \
  --temporary-password 'TempPass1!' --region $AWS_REGION
```
관리자 대시보드에 로그인하면 새 비밀번호를 설정하도록 강제됩니다.

---

## 6. 일회성 데이터 + 모델 스테이징 (D−3 ~ −2)

이 모든 작업은 **공유** 버킷에 씁니다. 6.3/6.4 단계는 당신의 토큰으로 게이트된
리포에 접근할 수 있는 머신에서 실행해야 합니다.

### 6.1 nuScenes-mini (M1/M2/M7)
```bash
./scripts/stage_nuscenes.sh    # pulls the public AWS Open Data mirror → datasets/nuscenes-mini/
```

### 6.2 단순 모델 캐시 (M2/M3)
```bash
pip install huggingface_hub && hf auth login --token "$HF_TOKEN"
./scripts/cache_models.sh      # → s3://<shared>/model-cache/ (Cosmos-Reason1-7B, Transfer2.5, Predict2.5)
```

### 6.3 HF 오프라인 캐시 (M5/M6/M9) — "참가자 토큰 불필요" 트릭

> **`cache_models.sh`는 `hf-cache/hub/`를 만들지 않습니다** — `scripts/cache_hf_tree.sh`를 쓰세요.
> 2026-09-26까지는 이 레포의 무엇도 그 트리를 생산하지 못했습니다: `scripts/` 안의 모든 `hf-cache`
> 참조가 S3에서 *읽는* 쪽이었고 쓰는 쪽이 없어서, 유일한 레시피가 GPU 앱에서 하는 수동 절차였습니다
> (지금은 폐기했습니다. 아래 경고 참고). `cache_models.sh`는 대체가 아닙니다 — 다른 프리픽스
> (`model-cache/`)에 다른 레이아웃(평면 `hf download --local-dir`, `models--org--name/snapshots/<sha>/…`이
> 아님)으로 씁니다.
>
> 결과적으로 두 가지가 실제로 물렸습니다:
> * **새 리전에는 재구축이 아니라 복사.** 시딩된 리전에서 버킷 간 `aws s3 sync`
>   ([ADDING_A_REGION.md](ADDING_A_REGION.md) §4). 2026-09-26에 ap-northeast-2를 `cache_models.sh`로
>   시딩했고 M5/M6/M9/M10이 죽은 상태로 출하됐습니다.
> * **추론하지 말고 검증.** `./scripts/check_seeding.sh --region <r>`가 런타임 glob이 테스트하는
>   `models--nvidia--*` 디렉터리 5개와 고정된 `tokenizer.pth` blob을 단정합니다.
>   `cache_models.sh`가 초록불로 끝난 것은 이 프리픽스에 대해 아무것도 증명하지 않습니다.

M5/M6/M9은 런타임에 HF의 **자체 캐시 레이아웃**을 통해 게이트된 체크포인트를 로드합니다
(M9은 숨겨진 Cosmos-Reason2-8B 백본도 가져옵니다). `setup_cosmos_env.sh`가 `hf-cache/hub/`를
`HF_HOME`으로 복원하고 `HF_HUB_OFFLINE=1`을 설정하므로, 참가자는 토큰 없이 오프라인으로 실행합니다.
시딩은 **관리자 워크스테이션에서 관리자 자격 증명으로** 합니다:
```bash
# 두 번째 리전부터: 이미 동작하는 리전에서 바이트 그대로 복사 (README step 6b).
aws s3 sync s3://av30lab-shared-data-<account>-<seeded-region>/hf-cache/ \
            s3://<shared>/hf-cache/ --source-region <seeded-region> --region "$AWS_REGION"
# 첫 리전: 고정된 매니페스트로 트리를 만듦 (GPU 불필요, 스크래치 ~65 GiB).
AWS_REGION="$AWS_REGION" HF_TOKEN=hf_... ./scripts/cache_hf_tree.sh
./scripts/check_seeding.sh --region "$AWS_REGION"
```

**`.no_exist` 마커 (M9).** `check_seeding.sh`는 `Alpamayo-1.5-10B`와 `Cosmos-Reason2-8B` 아래에
있는 0바이트 `models--*/.no_exist/<revision>/<file>` 파일 몇 개도 함께 셉니다. HuggingFace는
*온라인* 로드 중에 어떤 파일이 업스트림에 없다는 것을 확인하면 이 파일을 남깁니다. 다운로드로는
생기지 않으므로, `cache_hf_tree.sh`는 `scripts/hf_cache_manifest.tsv`에 `no_exist` 행으로 기록된
마커만 만듭니다. 버킷 간 복사를 하면 마커도 함께 옮겨집니다. 매니페스트에 기록된 마커가 없으면
`cache_hf_tree.sh`만으로 만든 트리는 두 저장소의 객체 수가 각각 15/16, 17/22로 나오고 검사가
실패합니다. 마커가 없을 때 M9이 오프라인에서 실제로 실패하는지는 아직 시험하지 않았기 때문에, 검사는
계속 마커를 셉니다. 마커를 한 번 기록한 다음 마커만 올리세요(토큰도, 다운로드도 필요 없습니다):
```bash
# 마커가 있는 트리에서 기록 (예: 예전 GPU 앱 절차로 시딩한 리전, read-only 조회):
aws s3 ls s3://av30lab-shared-data-<account>-<seeded-region>/hf-cache/hub/ --recursive \
  --region <seeded-region> | ./scripts/cache_hf_tree.sh --record-markers
AWS_REGION="$AWS_REGION" ./scripts/cache_hf_tree.sh --markers-only
```
그런 트리가 없으면 본인 GPU 앱에서 M9을 온라인으로 한 번 실행해 마커를 만듭니다. 아래 클립 절차의
1단계와 3단계를 보세요. `--record-markers`는 키 이름만 읽고 객체 내용은 읽지 않습니다. 비어 있지
않은 마커나, 매니페스트가 내려받는 파일을 가리게 되는 마커는 거부하고, 매니페스트가 고정하지 않은
리비전은 건너뜁니다. 갱신된 매니페스트는 본인 저장소 사본에 커밋해 두세요. 그러면 다음 첫 리전부터는
`cache_hf_tree.sh`가 마커까지 바로 만듭니다.

> **Studio 터미널에서 `hf-cache/`에 쓰지 말고, 관리자 AWS 키를 Studio 터미널에 붙여넣지도 마세요.**
> 이 가이드의 예전 버전은 GPU JupyterLab 앱에서 캐시를 올렸고, 그러려면 SageMaker 실행 역할이
> `hf-cache/*`에 쓸 수 있어야 했습니다. 그런데 이 역할은 모든 참가자가 함께 쓰고, 모든 참가자의
> 커널이 이 프리픽스를 로드합니다. M9은 `hf-cache/alpamayo-demo/*.pt`를
> `torch.load(weights_only=False)`로 여는데, 이는 파일을 unpickle하므로 그 안의 코드가 실행됩니다.
> 즉 참가자 한 명이 다른 모든 참가자의 권한으로 코드를 실행할 수 있었습니다. 이 쓰기 권한은
> 제거했으므로, 이제 Studio 앱에서 `hf-cache/`로 `aws s3 cp`/`sync`를 하면 의도대로 `AccessDenied`가
> 납니다. 이를 피하려고 관리자 키를 터미널에 넣는 것은 더 위험합니다. 앱의 홈 디렉터리는 시작할
> 때마다 S3의 `users/<profile>/`에서 동기화되므로, 거기에 심어 둔 `.bashrc`가 키를 가로챌 수 있습니다.

> **이 변경 이전에 배포한 스택을 업그레이드하는 경우.** 지금까지는 모든 참가자가 `hf-cache/*`에 쓸
> 수 있었으므로, 감사하기 전까지는 이 프리픽스를 믿지 마세요. 이 프리픽스에 의존하기 전에, 그리고 이
> 리전을 복사 원본으로 쓰기 전에 감사하세요. 복사하면 바꿔치기된 객체도 새 리전으로 그대로 넘어가고,
> `check_seeding.sh --source-region`은 두 리전을 서로 비교할 뿐이라 이를 알아채지 못합니다. 공유
> 버킷은 버전 관리가 켜져 있으므로, read-only 목록 조회만으로 모든 쓰기 기록을 볼 수 있습니다.
> read-only 자격 증명을 쓰세요:
> ```bash
> # 최신이 아닌 버전과 삭제 마커: 하나하나가 첫 업로드 이후에 일어난 쓰기입니다.
> aws s3api list-object-versions --bucket <shared> --prefix hf-cache/ --region <r> \
>   --query 'Versions[?IsLatest==`false`].[LastModified,Key]' --output text
> aws s3api list-object-versions --bucket <shared> --prefix hf-cache/ --region <r> \
>   --query 'DeleteMarkers[].[LastModified,Key]' --output text      # "None" = 삭제 없음
> # 현재 버전을 최신순으로: 처음 시딩한 시점 이후의 항목은 확인이 필요합니다.
> aws s3api list-object-versions --bucket <shared> --prefix hf-cache/ --region <r> \
>   --query 'Versions[?IsLatest].[LastModified,Key]' --output text | sort -r | head -20
> ```
> 걸린 항목은 모두 조사하세요. 가장 중요한 것은 로드하면 코드가 실행되는 pickle 형식 파일입니다.
> `alpamayo-demo/*.pt`, 그리고 hub 트리에 있는 Cosmos-Transfer2.5와 Cosmos-Predict2.5의
> `*_ema_bf16.pt`, Predict2.5의 `tokenizer.pth`, Guardrail1의 `safety_filter.pt`와
> `Resnet50_Final.pth`가 여기에 해당합니다. 감사 결과와 상관없이 `alpamayo-demo/*.pt`는 물려받지 말고
> 아래 절차로 다시 만들어 게시하세요. 객체 버전 삭제는 파괴적인 작업이므로, 하기 전에 별도로 승인을
> 받으세요.

**M9은 데모 클립도 필요합니다.** 그 데이터셋은 오프라인으로 읽을 수 없고, 클립은 GPU 앱의 `a1_5`
venv 안에서 만들어야 합니다. 그래서 클립을 *만드는* 일은 GPU 앱이, *게시하는* 일은 워크스테이션이
맡습니다. 참가자를 프로비저닝(§9)하기 전에 하세요. 시딩된 리전에서 `hf-cache/`를 복사했다면 클립도
함께 왔으므로(`check_seeding.sh`로 확인됩니다), 다시 게시하는 경우가 아니면 1-3단계는 건너뛰세요.
원본 리전이 이 변경 이전에 배포된 것이라면 한 번은 다시 게시하세요(위의 업그레이드 안내 참고).

**시작하기 전에, 어떤 참가자도 본인 워크스페이스에 쓸 수 없는지 확인하세요.** 클립은 참가자 프로필이
하나도 없을 때, 또는 사용자 워크스페이스 버킷이 사용자별로 격리된 뒤에만 만드세요. 그 전에는 모든
참가자가 함께 쓰는 실행 역할이 모든 `users/<profile>/` 프리픽스에 쓸 수 있고, 앱은 시작할 때마다
`users/<your-profile>/`을 홈 디렉터리로 복사합니다. 그러면 누군가 심어 둔 `.bashrc`나 IPython 시작
파일, 바꿔치기한 `scripts/alpamayo_save_clip.py`가 `.pt`와 그에 대해 출력되는 sha256을 모두 좌우할 수
있고, 여러분이 export한 `HF_TOKEN`도 볼 수 있습니다. 해시는 파일이 앱을 떠난 뒤에 바뀌지 않았다는
것만 증명합니다. 이미 워크숍을 한 차례 운영한 스택이라면 먼저 참가자 프로필을 삭제한 뒤, 새로 만든
본인 프로필을 쓰세요. 예전 프리픽스에 심어진 파일은 그대로 남아 있고, 같은 프로필 아래에 새 스페이스를
만들어도 그 프리픽스를 그대로 복사하기 때문입니다.

1. 본인 프로필의 GPU JupyterLab 앱에서, 라이선스(§3)를 수락한 계정의 `HF_TOKEN`으로:
   ```bash
   export HF_TOKEN=hf_...
   bash scripts/setup_cosmos_env.sh alpamayo     # build the a1_5 venv
   source /mnt/sagemaker-nvme/cosmos-work/alpamayo_env.sh
   unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE     # this save must be online
   python scripts/alpamayo_save_clip.py --clip 030c760c-ae38-49aa-9ad8-f5650a545d26 \
     --t0-us 5100000 --out /mnt/sagemaker-nvme/m6_work/clips
   ```
   스크립트는 마지막에 `sha256  <hash>  030c760c-….pt`를 출력합니다. **이 해시를 직접 옮겨 적어
   본인 메모에 보관하세요.** 클립 옆에 S3 파일로 저장하면 클립과 함께 바꿔치기될 수 있습니다.

   *`.no_exist` 마커가 필요한 경우에만(위 참고):* 같은 터미널에서 추론을 온라인으로 한 번 실행한 뒤,
   그때 생긴 마커를 staging으로 옮깁니다. 마커는 빈 파일이고, 쓰이는 것은 이름뿐입니다.
   ```bash
   python scripts/alpamayo_infer.py \
     --clips /mnt/sagemaker-nvme/m6_work/clips/030c760c-ae38-49aa-9ad8-f5650a545d26.pt \
     --out /mnt/sagemaker-nvme/m6_work/out
   aws s3 sync /mnt/sagemaker-nvme/hf/hub "s3://$USER_BUCKET/users/$USER_PROFILE/staging/hub-markers/" \
     --exclude '*' --include '*/.no_exist/*' --exclude '*/snapshots/*'
   ```
2. 다음 중 한 가지 방법으로 `.pt`를 앱 밖으로 옮깁니다:
   * `cp /mnt/sagemaker-nvme/m6_work/clips/030c760c-*.pt ~/` 후, JupyterLab 파일 브라우저에서
     파일을 우클릭해 **Download**; 또는
   * `aws s3 cp /mnt/sagemaker-nvme/m6_work/clips/030c760c-*.pt "s3://$USER_BUCKET/users/$USER_PROFILE/staging/"`
     (본인 워크스페이스 프리픽스입니다. 실행 역할은 여기에는 쓸 수 있지만 `hf-cache/`에는 쓸 수 없습니다).
3. 관리자 워크스테이션에서 관리자 자격 증명으로:
   ```bash
   CLIP=030c760c-ae38-49aa-9ad8-f5650a545d26.pt
   USERB=av30lab-user-workspace-<account>-$AWS_REGION
   aws s3 cp "s3://$USERB/users/<your-profile>/staging/$CLIP" . --region "$AWS_REGION"   # skip if downloaded
   shasum -a 256 "$CLIP"       # MUST equal the hash from step 1 (Linux: sha256sum "$CLIP")
   aws s3 cp "$CLIP" "s3://<shared>/hf-cache/alpamayo-demo/" --region "$AWS_REGION"
   aws s3 rm "s3://$USERB/users/<your-profile>/staging/$CLIP" --region "$AWS_REGION"
   # 1단계에서 .no_exist 마커를 staging에 올린 경우에만:
   aws s3 ls "s3://$USERB/users/<your-profile>/staging/hub-markers/" --recursive \
     --region "$AWS_REGION" | ./scripts/cache_hf_tree.sh --record-markers
   AWS_REGION="$AWS_REGION" ./scripts/cache_hf_tree.sh --markers-only
   aws s3 rm "s3://$USERB/users/<your-profile>/staging/hub-markers/" --recursive --region "$AWS_REGION"
   ./scripts/check_seeding.sh --region "$AWS_REGION"
   ```
   해시가 다르면 앱을 떠난 뒤에 파일이 바뀐 것입니다. 업로드하지 말고 클립을 다시 만드세요.

전체 순서: [COSMOS_M5_M6.md](COSMOS_M5_M6.md), [ALPAMAYO_M9.md](ALPAMAYO_M9.md).

### 6.4 M10 AlpaSim 레퍼런스 평가 (M10을 실행하는 경우에만)
AlpaSim은 ≥40 GB GPU가 필요한 Docker-Compose 마이크로서비스 시스템입니다 —
Studio 노트북에서는 **실행할 수 없습니다**. Docker가 가능한 GPU EC2 호스트에서 한 번 실행하세요:
```bash
# On a Deep Learning Base GPU AMI box (g6e.12xlarge, public subnet):
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export HF_TOKEN=hf_... NGC_API_KEY=nvapi-...
# Do NOT export SHARED_BUCKET: the script derives av30lab-shared-data-<acct>-<region>
# itself and exits 1 if it cannot. An exported value overrides that and, if it is
# missing the region suffix, silently targets a bucket that does not exist.
bash scripts/alpasim_ec2_setup.sh    # → uploads s3://<shared>/m10-reference/
# then TERMINATE the instance.
```
M10 노트북(CPU)은 모든 참가자를 위해 이 결과를 다운로드하고 시각화합니다.
일회성 ~$30; 참가자 비용 $0. 전체 세부 사항 + 선택적 참가자
자가 실행 경로: [ALPASIM_M10.md](ALPASIM_M10.md), [M10_MANUAL_TEST_RUNBOOK.md](M10_MANUAL_TEST_RUNBOOK.md).

### 6.5 노트북 템플릿 + 스크립트 업로드 (노트북 편집 후 맨 마지막에 실행)
```bash
# <shared> = av30lab-shared-data-<account>-<region>. $AWS_REGION 은 §5에서 export한 값 (또는: export AWS_REGION=...)
aws s3 sync notebooks/ s3://<shared>/notebook-templates/ --region "$AWS_REGION" \
    --exclude "*__pycache__*" --exclude "*.pyc"
aws s3 sync scripts/   s3://<shared>/notebook-templates/scripts/ --region "$AWS_REGION" \
    --exclude "*__pycache__*" --exclude "*.pyc"
```

> **재번호 이전 노트북이 이미 들어 있는 버킷에 다시 동기화하나요?**
> `aws s3 sync`는 삭제하지 않으므로 옛 이름(`M4_Cosmos_Transfer_…`,
> `M8_OpenSearch_…`, `M9_HyperPod_…`, `M10_Nerfstudio_…`)이 새 이름과 함께 남아
> 참가자에게 둘 다 보입니다. `--delete`는 **쓰지 마세요** — 이 동기화가 다시 채우지
> 않는 `notebook-templates/scripts/` 폴더까지 지워버립니다. 대신 옛 객체를 명시적으로
> 삭제하세요:
> ```bash
> for f in M4_Cosmos_Transfer_Augmentation M5_Cosmos_Predict_Synthesis \
>          M6_Alpamayo_VLA_Inference M7_AlpaSim_ClosedLoop \
>          M8_OpenSearch_Semantic_Search M9_HyperPod_Distributed_Training \
>          M10_Nerfstudio_3D_Reconstruction; do
>   aws s3 rm "s3://av30lab-shared-data-$ACCOUNT-$AWS_REGION/notebook-templates/$f.ipynb" \
>     --region "$AWS_REGION"
> done
> ```
> `teardown.sh` 후 새로 배포하는 경우에는 필요하지 않습니다.
이것들은 프로비저닝 시점에 각 사용자의 워크스페이스로 복사됩니다(그리고 노트북은
이 경로에서 스크립트를 다운로드하는 방식으로 폴백합니다). **노트북이나 스크립트를
변경할 때마다 다시 실행하세요** — 그렇지 않으면 참가자가 이전 버전을 받습니다.
이미 프로비저닝된 참가자는 JupyterLab 터미널에서 다시 동기화할 수 있습니다:
`aws s3 cp s3://<shared>/notebook-templates/<NB>.ipynb ~/`.

> **노트북 수정:** 리포의 `notebooks/*.ipynb`가 유일한 기준이므로 노트북을 직접 고친 뒤
> §6.5로 다시 동기화하면 되며, 노트북들이 의존하는 모듈 간 S3 계약은
> [DATA_CONTRACT.md](DATA_CONTRACT.md)에 정리되어 있습니다.

---

## 7. 선택 사항: M10 참가자 자가 실행 (고급)

기본적으로 모든 참가자는 당신의 M10 레퍼런스 평가(§6.4) 하나를 공유하며 토큰이
필요 없습니다. 대신 **각 참가자가 자신의 관리자 프로비저닝 GPU 호스트에서 SSM을 통해
직접 AlpaSim을 실행**하도록 하려면:
- 참가자당 GPU EC2 호스트를 사전 프로비저닝하고 최소 권한 SSM
  액세스(정확한 ARN 또는 ABAC)를 부여합니다. **참가자는 호스트를 종료할 수 없습니다 — 당신이 종료합니다**
  (비용 폭주 방지 장치).
- 각 참가자는 **자신의 HF 토큰**이 필요합니다(NuRec 데이터셋은 게이트되어 있고
  공유 캐시에 없습니다).
- 비용 ~$10.5/시간/호스트, G-vCPU 쿼터에 따라 동시 ≤16.

전체 런북: [M10_MANUAL_TEST_RUNBOOK.md](M10_MANUAL_TEST_RUNBOOK.md) Part C(관리자
프로비저닝 + IAM) 및 [M10_PARTICIPANT_SSM_RUNBOOK.md](M10_PARTICIPANT_SSM_RUNBOOK.md)
(참가자 단계). 이것은 옵트인이며, 표준 워크샵에서는 건너뛰세요.

---

## 8. 스모크 테스트 (D−1) — 사용자 1명이 엔드투엔드로 작동함을 증명

1. Admin Dashboard → **Add User** → 테스트 이름 + 이메일 → **Provision**. 테스트 사용자를
   하나 더(B) 만드세요. 4c 단계에서 비교할 상대가 필요합니다.
2. 성공 다이얼로그에서 **Participant Dashboard Link**를 복사하세요(내구성 있는
   `#userId=&token=` 링크 — 5분짜리 "Direct workspace URL"이 **아님**).
3. 그 링크를 새 브라우저에서 열면 → 12개 모듈 노드가 있는 Pipeline Map(M1~M12. M0은 개요 노트북이라 노드가 없습니다)이 렌더링되고,
   주소창에서 `#userId=…&token=…` 부분이 사라집니다.
4. **M2** 클릭 → **Instance Options** → 권장 `ml.g5.12xlarge`가 미리 선택됨 →
   **Apply & Restart** → **Open Workspace** → JupyterLab이 열립니다.
4b. **스코프 IAM 조건이 실제로 해석되는지 확정(무료, ~1분).** 그 앱이 실행 중인 상태에서
   테스트 사용자로 Studio **자체**를 엽니다(딥링크가 아니라 Studio 콘솔). 스페이스 페이지에서
   **Run space**, 그다음 **Open JupyterLab**을 클릭하고, `sagemaker:UpdateSpace` /
   `sagemaker:CreatePresignedDomainUrl`에 대한 `AccessDenied`가 나는지 기록합니다.
   메시지에 *explicit deny*가 들어 있다면 다른 문제입니다. 인스턴스 타입 Deny(§2a)에
   걸린 것이므로, 폼이 어떤 타입을 보냈는지 확인하세요.
   - **AccessDenied 없음** → `${sagemaker:DomainId}` / `${sagemaker:UserProfileName}`
     정책 변수가 런타임에 해석됩니다. 따라서 `CreateApp`/`DeleteApp`을 `resources=["*"]`에서
     같은 소유자 조건으로 좁힐 수 있습니다. `infra/av30_constructs/sagemaker.py`의
     `SageMakerStudioAppLifecycle` 문장에 붙은 주석을 보세요.
   - **AccessDenied 발생** → 이 계정에서는 해석되지 않습니다. `CreateApp`은 넓은 상태로
     두고, 참가자에게는 계속 대시보드 버튼을 쓰게 합니다.
4c. **사용자별 S3 격리 증명(새 스택마다 필수, §0).** 먼저 라이프사이클 스크립트 로그를
   확인합니다. CloudWatch Logs의 로그 그룹 `/aws/sagemaker/studio`에서 테스트 사용자 스페이스의
   스트림 중 이름이 `LifecycleConfigOnStart`로 끝나는 가장 최근 것을 엽니다.
   `Notebook bootstrap complete`가 있어야 하고 `WARN: notebook sync failed`나
   `AccessDenied`는 **없어야** 합니다. 동기화가 실패해도 앱은 멈추지 않기 때문에, 이 확인을
   하지 않으면 홈 디렉터리가 비어 있는 것으로만 보입니다. 다음으로 테스트 사용자의 JupyterLab
   터미널에서(`$USER_BUCKET`과 `$USER_PROFILE`이 설정되어 있습니다), 두 번째 테스트 사용자의
   id를 `<B-id>`에 넣어 실행합니다.
   ```bash
   aws s3 ls "s3://$USER_BUCKET/users/$USER_PROFILE/"                  # 성공: 자기 파일
   aws s3 ls "s3://$USER_BUCKET/users/<B-id>/"                         # AccessDenied
   aws s3 cp "s3://$USER_BUCKET/users/<B-id>/.av30-progress.env" -     # 403 / AccessDenied
   echo probe | aws s3 cp - "s3://$USER_BUCKET/users/<B-id>/probe.txt" # AccessDenied
   aws s3 rm "s3://$USER_BUCKET/users/<B-id>/M1_Data_Exploration.ipynb" # AccessDenied
   aws s3 ls "s3://$USER_BUCKET/"                                      # AccessDenied
   aws sagemaker describe-pipeline --pipeline-name "av30-data-pipeline-<B-id>"  # AccessDenied
   ```
   첫 줄이 성공한다는 것 자체가 세션에 올바른 source identity가 실려 있다는 증거입니다.
   source identity가 없으면 첫 줄도 거부됩니다. 첫 줄이 거부되면 §13을 보세요. AccessDenied로
   표시한 줄 중 하나라도 성공하면 이 스택은 격리되어 있지 않은 것이니 코호트를 프로비저닝하지
   마세요.
5. **M1**(CPU)을 엔드투엔드로 실행한 뒤 **M2**(GPU)를 실행 — GPU 이미지가
   자동 선택되고 모델 캐시가 해석되는지 확인합니다.
6. 테스트 사용자로 **M11**과 **M12**를 한 번씩 실행하세요. 실제 입력이 있도록 M1과 M3 다음에
   실행합니다. 작업 쿼터(§2b)와 IAM 확인 외에, source identity가 관리형 작업까지 전달되는지
   확인하는 방법은 이것뿐입니다. 전달되지 않으면 제출 단계가 아니라 작업 안에서, 파이프라인의
   1단계나 학습 작업이 S3 `AccessDenied`로 실패합니다.
7. 두 테스트 사용자를 모두 **Delete**하세요(Users 탭 → Delete) — 앱/스페이스/프로필 + S3를 제거합니다.

---

## 9. 참가자 프로비저닝 (D0)

**단일 사용자:** Admin Dashboard → **Add User** → 이름 + 이메일 → **Provision**.
**Participant Dashboard Link**(내구성 있음, 만료 없음)를 전달하세요. Users
테이블에는 사용자별 복사 버튼이 있는 **Dashboard Link** 열이 있습니다.

**이 링크는 bearer credential이므로 비밀번호처럼 다루세요.** 링크를 가진 사람은 사용자를
삭제하기 전까지(§12) 그 참가자의 워크스페이스를 열고 인스턴스를 바꿀 수 있습니다. 링크는
공용 채널이 아니라 참가자 본인에게 직접 보내세요.
- 토큰은 URL fragment(`#userId=…&token=…`)에 실립니다. 브라우저는 fragment를 서버로
  보내지 않으므로 CloudFront 로그나 `Referer` 헤더에 남지 않습니다.
- 대시보드는 페이지를 여는 즉시 토큰을 탭의 session storage로 옮기고 주소창에서
  지웁니다. 그래서 화면 공유나 복사한 URL에 토큰이 드러나지 않습니다. 새로고침해도
  로그인은 유지되지만, 열린 페이지를 새 탭으로 열거나 북마크한 주소로 열면 Demo Mode가
  됩니다. 참가자에게 원래 링크를 보관해 두었다가 다시 열라고 안내하세요.
- 예전에 `?userId=&token=` 형식으로 나눠 준 링크도 그대로 동작하고, 주소창에서도 같은
  방식으로 지워집니다. 토큰 자체는 바뀌지 않습니다(교체 기능 없음). 유출된 링크를 무효화하고
  참가자를 계속 참여시키려면 사용자를 삭제한 뒤(워크스페이스 파일도 함께 삭제됩니다) 다시
  프로비저닝하세요.

**대량(CSV):** Admin Dashboard → 대량 업로드. CSV에는
`name`과 `email` 열(대소문자 구분 없음)이 있는 헤더 행이 필요합니다. 프로비저닝은 병렬로
실행됩니다; 실패한 항목은 개별적으로 재시도하세요.

각 참가자는 다음을 받습니다: SageMaker 사용자 프로필 + 스페이스, 노트북
템플릿으로 시드된 `users/<id>/` S3 프리픽스, 개인 대시보드 링크.

**참가자에게 두 가지를 보내세요:**
- **이벤트 전** — [PRE_LEARNING_GUIDE.md](PRE_LEARNING_GUIDE.md)(개념 +
  선택적 심화 읽기, ~45–60분)를 보내 사전 맥락을 갖추고 오도록 합니다.
- **당일** — 대시보드 링크 + [PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md)
  (클릭별 런북).

---

## 10. 워크샵 중 — 모니터링 및 제어

- **Sessions 탭** — 누가 무엇을, 어떤 인스턴스에서, 어느 비용으로 실행 중인지 실시간 보기.
- **용량 오류**(`EC2InsufficientCapacityError`): 해당 모듈에 대해 Instance Options가
  제시하는 대안 중 아무거나 고르라고 알리세요. 패널은 어느 리전에서나 같은 목록을
  보여 주므로 걸러 내는 일은 API가 합니다. 이 리전이 판매하지 않거나 쿼터가 0인 타입은
  실행 중인 앱을 건드리기 전에 설명과 함께 거부됩니다.
  특정 폴백을 기억에 의존해 지정하지 마세요: `ml.g6.12xlarge`는 예전 조언이며
  ap-northeast-2에서 쿼터 0입니다. 이것은 용량 부족이지 쿼터 문제가 아닙니다.
- **인스턴스 변경이 조용히 일어나지 않은 경우.** 참가자가 인스턴스 변경이 아무
  일도 하지 않았다고 하면, 새 타입에서 앱 시작이 실패했고(대개
  `ResourceLimitExceeded` — 쿼터는 있지만 모든 슬롯이 사용 중) 이전 타입으로
  롤백되어 워크스페이스는 그대로 남아 있는 상태입니다. 이유는
  `GET /sessions/{id}/app-status`의 `lastInstanceChangeError`에 있습니다. 유휴
  세션을 강제 종료해 슬롯을 비우고 다시 시도하게 하세요.
- **비용 제어** — 일일 예산 알람이 SNS를 통해 `ADMIN_EMAIL`로 이메일을 보냅니다;
  유휴 JupyterLab 앱은 90분 후 자동 중지됩니다(`-c idle_timeout_minutes=<60..180>`로
  변경). 실행 중인 셀이나 터미널 작업은 활성으로 계산되므로 진행 중인 작업이
  중단되지 않습니다. Sessions 탭에서 어떤 세션이든 **강제 종료**할 수 있습니다. 유휴 GPU 박스를 주시하세요 —
  단가는 리전별이므로 자기 리전 값을 쓰세요: `ml.g5.12xlarge`(다섯 모듈의 기본값)는
  ap-northeast-2에서 **$8.72/시간**, us-west-2에서 $7.09이고, `ml.p4d.24xlarge`는
  ap-northeast-2에서 **$34.97/시간**, us-west-2에서 $25.25입니다.
  `infra/lambda/shared/instance_rates.py`에서 자기 리전을 확인하세요.
- **스토리지 비용은 참가자당이고 한 방향으로만 갑니다.** 모든 스페이스는 200 GB gp3 볼륨으로
  생성됩니다(`infra/av30_constructs/__init__.py`의 `DEFAULT_SPACE_STORAGE_GB`).
  ap-northeast-2 단가 $0.0912/GB-월 기준 **참가자당 월 ~$18.24**이며, 앱 실행 여부와 무관하게
  과금됩니다 — 유휴 타이머는 앱을 삭제하고 볼륨은 남깁니다. AWS는 스페이스 볼륨 **축소를
  허용하지 않고** 참가자가 늘릴 수는 있으므로(+50/+200, 상한 500 GB), 티어다운으로 스페이스를
  없앨 때까지 올라가기만 합니다.
- **GPU 이미지 알림** — 참가자가 GPU 인스턴스에서 "No GPU detected"를 보고하면,
  CPU 이미지를 실행한 것입니다; Instance Options → GPU 인스턴스 → Apply를 하면
  GPU 이미지가 다시 선택됩니다.

---

## 11. M7 Nerfstudio — gsplat 빌드 (세션별)

**M7의 트레이닝 셀은 미검증입니다 — 저장소가 스스로 모순합니다.** 이 절은 예전에 "M7은
이제 트레이닝을 합니다"라고 단정했습니다. 그런데 노트북 cell 0은 반대로 말하고("현재
이미지에서 실행되지 않음"), 두 주장이 같은 커밋에서 들어왔고, 캡처된 실행은 9개 셀 중
2개만 출력을 남겼습니다 — 즉 통과도 실패도 본 사람이 없습니다. `ml.g5.xlarge`로 한 번
실행하면(~$0.25, ~15분) 판정됩니다. `docs/en/TODO_M7_nerfstudio.md` 참고. 그때까지는
PARTICIPANT_GUIDE가 서술하는 선택적 개념 + 데이터 준비 데모로 취급하세요.

세션별 gsplat CUDA 빌드 이후 *의도된* 동작은 다음과 같습니다: `gsplat`은 순수 Python 휠을 제공하고 첫 사용 시 CUDA 커널을
소스에서 컴파일하지만, SageMaker Distribution 이미지의 conda CUDA dev
패키지가 불완전합니다. **`scripts/setup_gsplat_env.sh`**(M7 셀 3이 호출)가
전체 체인을 고칩니다: 누락된 dev 헤더를 설치하고, `nvcc`가 `cicc`를 찾도록 `nvvm`을
심링크하고, CUDA 헤더/라이브러리를 표준 `$CUDA_HOME` 경로로 미러링하고
(그래서 `ns-train`의 서브프로세스 안에서도 env 변수 없이 빌드가 작동함),
`gsplat==1.4.0`을 소스 빌드합니다.

- 이것은 <strong>일시적(ephemeral)</strong>입니다 — SMD 앱이 재시작 시 `/opt/conda`를 리셋하므로,
  설정 셀이 세션마다 다시 실행됩니다(콜드 시 ~3–5분, 이미 빌드되어 있으면 수초).
- 데모는 **합성 사인파 카메라 포즈**를 사용하므로, 트레이닝은 엔드투엔드로 실행되지만
  (진짜 Gaussian-Splatting 파이프라인) 재구성은 스모크 테스트이지
  계량적으로 정확한 장면은 아닙니다. 실제 nuScenes 캘리브레이션 연결이 다음 단계입니다.
- **M7 주의:** gsplat CUDA 빌드가
  `scripts/setup_gsplat_env.sh`를 통해 세션마다 실행됩니다; M7을 선택/데모 모듈로 취급하고
  최종 트레이닝 셀은 GPU 이미지의 CUDA 툴체인에 민감할 것으로 예상하세요.

---

## 12. 티어다운 및 이벤트 후 보안

- **원샷 티어다운:** <strong>`scripts/teardown.sh`</strong>가 관리자 AWS 자격 증명으로
  모든 것을 회수합니다. 기본은 드라이런(열거만 하고 아무것도 변경하지 않음);
  실제 실행은 `--yes`, 단일 사용자로 범위를 좁히려면 `--user <id>`, `cdk destroy`도 함께 하려면 `--destroy`.
  사용자당 app→space→profile→AOSS→S3→DDB 순서로 삭제하고(delete_user
  Lambda와 동일한 순서), 그다음 고아가 된 OpenSearch Serverless 컬렉션을 잡기 위해
  **전역 `av30-semantic-*` AOSS 스윕**을 실행하고(이들은 지속적으로 과금됩니다 — 스윕이
  안전망), `Participant`+`av30-alpasim-*` 태그가 붙은 GPU EC2
  호스트를 종료합니다. 끝에 수동 HF/NGC 키 폐기 체크리스트를 출력합니다.
- **단일 사용자를 인터랙티브하게 삭제:** Admin Dashboard → Users → **Delete**
  (한 번의 작업으로 동일한 의존성 순서).
- **삭제하거나 비활성화한 참가자가 바로 차단되지는 않습니다.** Delete를 누르거나
  `av30-sessions-v2` 테이블에서 사용자의 `status`를 `active`가 아닌 값으로 바꾸면 참가자의
  대시보드 토큰이 폐기됩니다. 다만 API Gateway가 token authorizer의 판정을 **최대 60초**
  캐시하므로, 그동안은 그 토큰으로 참가자 route를 계속 호출할 수 있습니다. Open Workspace,
  인스턴스 변경, 스토리지 확장은 핸들러가 `status`를 직접 확인하므로 즉시 거부됩니다.
  토큰을 바로 끊어야 한다면 삭제 직후 stage의 authorizer 캐시를 비우세요.

  ```bash
  API_ID=$(aws cloudformation describe-stacks --stack-name Av30BlueprintLabStack --region "$AWS_REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text | cut -d/ -f3 | cut -d. -f1)
  aws apigateway flush-stage-authorizers-cache --rest-api-id "$API_ID" --stage-name prod --region "$AWS_REGION"
  ```

  캐시는 모든 토큰에 대해 한꺼번에 비워지지만, 다른 참가자는 다음 요청에서 authorizer를
  한 번 더 거칠 뿐입니다. 이미 열려 있는 Studio 브라우저 세션은 이 캐시를 거치지 않습니다.
  그 세션은 Delete가 app, space, user profile을 지우면서 끝납니다.
- **스택 티어다운**(플랫폼이 임시라면): `scripts/teardown.sh
  --yes --destroy`, 또는 `cd infra && npx cdk destroy`. shared-data 버킷은
  RETAIN임에 유의하세요 — 이 버킷과 캐시된 모델은 destroy를 견디고 살아남으며 수동으로 비워야 합니다.
- **관리자 HF 토큰 `hf_...` 폐기** — 참가자가 접촉하는 것은 오직 S3 캐시뿐이므로,
  스테이징 이후에는 토큰이 필요 없습니다.
- M10을 사용했다면 **NGC API 키 로테이션**.
- 유휴 상태의 스택도 여전히 ~$80/월(NAT, VPC 엔드포인트, DynamoDB, CloudFront)의 비용이 듭니다 —
  끝났다면 destroy하세요.

---

## 13. 관리자 트러블슈팅 빠른 표

| 증상 | 원인 / 해결 |
|---|---|
| `ResourceLimitExceeded: ...Studio JupyterLab Apps... is 0` | GPU 앱 쿼터가 증설되지 않음 — §2a. |
| M12 작업이 제출에서 실패 (`CreateTrainingJob`에 `AccessDeniedException`) | 실행 역할은 `av30-m12-distributed-<자기 프로필>-*` 이름의 학습 작업만 허용하고(프로필은 세션의 source identity에서 옵니다), 노트북의 `JOB_NAME`이 여기에 맞아야 합니다. 어긋나는 경우는 두 가지입니다. M9→M12 재번호 이전의 배포는 여전히 `av30-m9-*`만 허용합니다. 또는 커널에 `USER_PROFILE`이 없어 `PROFILE`이 `default`로 대체되어 이름에 잘못된 프로필이 들어갑니다(라이프사이클 스크립트가 값을 넣도록 앱을 다시 시작하세요). m5.xlarge **작업** 쿼터(§2b)는 별개의 드문 원인입니다 — 에러를 먼저 보세요: `AccessDenied`는 IAM 이름 범위, `ResourceLimitExceeded`는 쿼터. |
| 사용자별 격리 업그레이드(§5) 후: 홈 디렉터리가 비어 있거나 노트북이 없음, `aws s3 ls s3://$USER_BUCKET/users/$USER_PROFILE/`가 `AccessDenied`, 또는 M11/M12 작업이 작업 안에서 S3 `AccessDenied`로 실패 | 세션에 source identity가 없어서 `users/${aws:SourceIdentity}/` 범위가 아무것도 가리키지 않습니다(fail-closed). 순서대로 확인하세요. (1) 도메인이 전환되기 전에 시작한 앱입니다: 중지했다가 다시 시작하세요. (2) 관리자 자격 증명으로 `aws sagemaker describe-domain --domain-id <id> --query DomainSettings.ExecutionRoleIdentityConfig`가 `USER_PROFILE_NAME`을 출력해야 하고, `aws iam get-role --role-name av30lab-sagemaker-execution-role-<region> --query Role.AssumeRolePolicyDocument`에 `sts:SetSourceIdentity`가 있어야 합니다. (3) 라이프사이클 스크립트의 `LifecycleConfigOnStart` 로그에서 동기화가 거부되었는지 봅니다(§8의 4c 단계). (4) 두 설정이 모두 맞는데도 새로 시작한 앱이나 작업이 계속 거부되면, 이 계정에서는 그 세션 유형에 source identity가 전달되지 않는 것입니다. §5의 방법으로 롤백하세요. S3 statement를 `users/*`로 넓히지 마세요. 모든 사람의 격리가 사라집니다. |
| GPU 인스턴스에서 참가자 "No GPU detected" | CPU 이미지가 선택됨 — Instance Options로 다시 Apply. |
| M5/M6/M9 설정 셀이 "this region has no usable offline HuggingFace cache and no HF_TOKEN"으로 멈춤(exit 2) | 이 리전에 `hf-cache/hub/`가 시딩되지 않음(§6.3). 시딩 후 `./scripts/check_seeding.sh --region <r>`. 이 메시지는 *고쳐진* 동작입니다 — 2026-09-26 전에는 같은 조건이 침묵이었고, 설정 셀이 "environment ready"를 출력한 뒤 M5가 `torchrun`에서 4초 만에 `ChildFailedError`로 죽으며 CUDA out-of-memory를 지목했습니다. 아직 그 옛 형태가 보이면 참가자가 낡은 스테이징 `setup_cosmos_env.sh`를 쓰는 중입니다. |
| M5/M6/M9이 `Local entry not found … offline mode is enabled`로 실패 | 복원된 캐시가 **부분적**입니다. 중단된 `aws s3 sync`가 흔한 원인이고 — **같은 sync를 다시 돌리세요**, 이어서 없거나 크기가 다른 것을 재복사합니다. `sync`가 못 잡는 건 크기는 맞고 내용이 틀린 객체입니다(size+mtime 비교). `check_seeding.sh --source-region <seeded>`가 CRC64 불일치를 보고하면 그 객체만 지우고 다시 sync하세요. |
| M9이 클립 로드에 실패 | 데모 `.pt`가 `hf-cache/alpamayo-demo/`에 업로드되지 않음(§6.3). |
| Studio 터미널에서 `hf-cache/`로 `aws s3 cp`/`sync`를 하면 `AccessDenied` | 정상입니다. 모든 참가자가 함께 쓰는 실행 역할에는 공유 버킷 쓰기 권한이 의도적으로 없습니다(§6.3). 시딩과 게시는 관리자 워크스테이션에서 하고, 관리자 키를 Studio 터미널에 붙여넣지 마세요. |
| M10 노트북이 아무것도 표시하지 않음(cell-4 가 "No M10 AlpaSim results found in S3" 발생) | `m10-reference/` 레퍼런스 평가가 실행되지 않음(§6.4). |
| M10 의 메트릭·그래프는 나오는데 **비디오만** 빈 화면 | **번들 누락이 아니며 §6.4 를 재실행하지 말 것.** 코덱 문제다: AlpaSim 렌더러가 MPEG-4 Part 2 로 쓰고 Chrome/Firefox/Edge 는 이를 디코딩하지 못한다. cell-7 이 찾은 코덱을 출력한다. GPU 호스트 없이 그 객체 하나만 H.264 로 교체하면 된다: `aws s3 cp s3://$SHARED_BUCKET/m10-reference/eval/eval.mp4 .` 후 `ffmpeg -i eval.mp4 -vf scale=1280:-2 -c:v libx264 -pix_fmt yuv420p -movflags +faststart -an eval_h264.mp4` 를 돌려 `m10-reference/eval/eval.mp4` 로 덮어쓴다. `scripts/alpasim_ec2_setup.sh` 는 이제 업로드 시점에 변환하므로, 그 변경 이후에 만든 번들은 이미 H.264 다. |
| M4 검색 데모가 **같은 캡션을 여러 번** 랭크하고, 인덱스 셀이 삭제에서 `403 authorization_exception` 을 출력 | 컬렉션의 데이터 액세스 정책이 **`aoss:DeleteIndex`** 부여 이전 것이어서 M4 가 인덱스를 비울 수 없습니다. AOSS 는 호출자 지정 `_id` 를 거부하므로 `index()` 는 항상 INSERT — 재실행마다 전체 사본이 추가됩니다(실측: 캡션 24개에 문서 24 → 48 → 72 → 96 → 120). 참가자 역할은 정책을 고칠 수 없습니다: `aoss:UpdateAccessPolicy` 를 일부러 주지 않았는데, `collection/*` 범위에서는 한 참가자가 다른 참가자의 컬렉션에 접근할 수 있게 되기 때문입니다. admin 자격증명으로 **컬렉션과 데이터 정책을 둘 다** 삭제하세요(정책이 남으면 그게 옛 정책입니다). 그 뒤 참가자가 Run All 하면 M4 가 권한 포함해 재생성합니다: `aws opensearchserverless list-collections --region $REGION --query 'collectionSummaries[?starts_with(name,\`av30-semantic-\`)].[id,name]' --output text` → `aws opensearchserverless delete-collection --id <id> --region $REGION` → `aws opensearchserverless delete-access-policy --name <name>-access --type data --region $REGION`. |
| M7 트레이닝 셀이 gsplat에서 실패 | M7 셀 3(`scripts/setup_gsplat_env.sh`) 재실행 — CUDA 빌드는 세션별이며 앱 재시작 시 리셋됨. §11. |
| SNS 예산 경보가 placeholder@example.com으로 감 | `--context admin_email` 없이 배포됨 — `deploy.sh`로 재배포. |
| 참가자 링크가 "Demo Mode"를 표시 | 맨 URL을 열었거나, 이미 열린 대시보드를 새 탭이나 북마크로 열었음(토큰은 페이지를 열 때 주소창에서 지워짐). 원래 `#userId=&token=` 링크를 다시 열게 하거나 다시 보내세요. |
| 대량 프로비저닝 부분 실패 | 실패한 행을 개별 재시도; `bulk_provision` CloudWatch 로그를 확인. |

---

## 관련 문서
- [PRE_LEARNING_GUIDE.md](PRE_LEARNING_GUIDE.md) — 이벤트 전에 참가자에게 보내세요.
- [PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md) — 당일 참가자에게 전달하세요.
- [PREREQUISITES.md](PREREQUISITES.md) — §3/§6 뒤에 있는 토큰/라이선스 세부 사항.
- 모듈 심화: [COSMOS_M5_M6.md](COSMOS_M5_M6.md), [ALPAMAYO_M9.md](ALPAMAYO_M9.md),
  [ALPASIM_M10.md](ALPASIM_M10.md), [HYPERPOD_M12.md](HYPERPOD_M12.md),
  [PIPELINE_M11.md](PIPELINE_M11.md).
- [ADDING_A_REGION.md](ADDING_A_REGION.md) — 독립적인 추가 리전 구축(쿼터, 데이터 적재,
  재배포에 필요한 컨텍스트).
- [README.md](../../README.md) — 전체 배포 + 아키텍처 레퍼런스.
