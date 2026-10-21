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
  `av30lab-sagemaker-execution-role`을 공유하는 SageMaker Studio 도메인(사용자별 역할이
  아닙니다). 참가자 간 격리는 스페이스 소유자를 `${sagemaker:UserProfileName}`과 비교하는
  IAM 조건으로 이루어집니다 — `infra/av30_constructs/sagemaker.py`의 잔여 위험 주석 참조.
- **S3 버킷 2개** (이름은 **당신의** 계정 + 리전에서 파생됩니다 — 이 가이드의
  예시는 레퍼런스 배포인 계정 `<aws-account-id>` / `us-west-2`를 사용합니다.
  당신의 값으로 치환하세요 — §1.5 참고):
  - `av30lab-shared-data-<account>-<region>` — 모델, 데이터셋, 노트북 템플릿, M10 레퍼런스.
  - `av30lab-user-workspace-<account>-<region>` — 참가자당 `users/<id>/` 프리픽스 하나.

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
  `g6`, 그리고 선택적으로 `p4d`/`p5`)은 **모든** 리전에 있지는 않으며, 쿼터 승인은
  리전별입니다. GPU 용량이 풍부한 리전을 고르세요 — `us-west-2`(Oregon)와
  `us-east-1`(N. Virginia)이 가장 안전합니다. **특히 `ml.p5.48xlarge`는
  몇몇 리전에서만 제공됩니다(us-west-2 / us-east-1).**
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
Service Quotas 콘솔에서 "**Studio JupyterLab Apps running on**"을 검색하세요. 이것들은
**사용자 대시보드의 Instance Options**가 실제로 제공하는 인스턴스 타입(권장 + 대안)이라,
참가자는 이 집합에서만 고를 수 있습니다 — 아래 쿼터가 그 모든 것을
커버합니다. 쿼터 **코드는 리전에 무관**하며,
쿼터 **코드는 리전과 무관하지만**(us-west-2 / ap-northeast-2 / eu-west-1에서 동일함을 확인),
**값은 그렇지 않으며** 어떤 타입에 쿼터가 존재하는지조차 리전마다 다릅니다.

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
안 됐습니다. g5.12xlarge를 선호하는 이유는 쿼터와 가격입니다. 쿼터가 있다면 p4d/p5는 여전히
네이티브 해상도 / 전체 720p 경로로 남습니다.

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
| ml.m5.xlarge | L-77B8159A | 11 | ≥0 | CPU 대안(M12) |
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
| ml.g6.24xlarge | L-8ACE1754 | 2 | ≥0 | M2/M3/M5–M9 대안(4× L4, 96 GB) — g5.12xlarge와 기하 동일하나 더 비쌈; **ap-northeast-2에서 0** |
| ml.g6.48xlarge | L-125B7142 | 2 | ≥0 | M5/M6/M9 대안(8× L4) — **ap-northeast-2에서 0** |
| ml.g7e.2xlarge | L-7A3E0A2C | **0** | ≥0 | M2/M3/M5–M9 **가장 저렴한 네이티브 해상도 경로**(RTX PRO 6000 1장, 96 GB; **기본값 0 — 반드시 요청해야 함**) |
| ml.g7e.24xlarge | L-E481E4F8 | **0** | ≥0 | M5/M6/M9 대안(RTX PRO 6000 4장; **기본값 0**) |
| ml.p4d.24xlarge | L-AD63F1D2 | 2 | ≥2 | M5, M6, M9 네이티브 해상도 경로(8× A100; **기본값 0 — 반드시 요청해야 함**) |
| ml.p5.48xlarge | L-B41FBF28 | 1 | ≥0 | 헤비 모델 폴백(8× H100; **ap-northeast-2에서는 미판매**) |

> **g7e는 선택 사항이며 이 랩에서 미검증입니다.** 이 계정의 `us-west-2`에서 6개
> `ml.g7e.*` Studio 쿼터가 모두 **0**입니다(`list-service-quotas`로 확인). 증설을
> 요청하기 전까지는 아무도 선택할 수 없습니다. 목록에 넣은 이유는 네이티브 해상도
> 티어로 가는 *가장 저렴한* 경로이기 때문입니다 — 96 GB 카드 1장이 시간당 약
> $4.20으로 `ml.p4d.24xlarge`(약 $25.25/시간)보다 싸고 24 GB 기본값(약 $8.34/시간)
> 보다도 저렴합니다. 다만 **이 랩에서 g7e로 엔드투엔드 실행한 모듈이 없습니다.**
> 쿼터를 받으면 방 전체에 안내하기 전에 사용자 1명으로 M5를 스모크 테스트하세요.
> 다른 g7e 사이즈(4xl/8xl/12xl/48xl)도 쿼터 코드가 있습니다(L-B7228EBF,
> L-0407753C, L-5F015F52, L-A48244DF). 단 대시보드에는 노출되지 않습니다.

방 규모 산정: 각 모듈의 **권장** 인스턴스를 동시 참가자 수 이상으로 요청하고,
사람들을 유도할 한두 개의 폴백에 대해서는 표에 표시된 최소치 이상을 요청하세요(용량
오류가 나면 대시보드에 대안이 표시됩니다). 모든 대안에 대해 쿼터가
**필요하지는 않습니다** — 실제로 방에 사용하도록 유도할 것만 필요합니다.
GPU 모듈을 **g5.12xlarge**로 표준화한다면(권장 — 무거운 모듈 권장값 중 us-west-2와
ap-northeast-2 양쪽에서 0이 아닌 유일한 타입), 그것만 인원수 이상으로
요청하면 되고 p4d/p5는 기본값으로 두어도 됩니다.

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


```bash
# Required env
export ADMIN_EMAIL="you@example.com"       # becomes the Cognito admin + SNS alert target
export REGION="us-west-2"                  # YOUR chosen region (§1.5) — passed explicitly below
export AWS_REGION="$REGION"                # the seeding scripts in §6 read this
export HF_TOKEN="hf_..."                    # for the caching steps in §6
# Optional: lock the admin dashboard to your IP
export ADMIN_IP_ALLOWLIST="203.0.113.0/24" # default 0.0.0.0/0

# One-time CDK bootstrap (per account+region)
cd infra && source .venv/bin/activate && pip install -r requirements.txt
npx cdk bootstrap aws://$(aws sts get-caller-identity --query Account --output text)/$REGION
cd ..

# Generate this region's instance rate table (REQUIRED — the Lambdas raise at import
# without it rather than quoting another region's prices)
./scripts/refresh_instance_rates.py --region "$REGION" --merge

# Deploy stack + build/upload both dashboards (~25 min). Region is explicit.
./scripts/deploy.sh --region "$REGION"
```

`deploy.sh`는 `ADMIN_EMAIL`과 `ADMIN_IP_ALLOWLIST`를 `--context`를 통해 CDK에 전달합니다
(**env 변수가 아님** — `deploy.sh`를 건너뛰고 `cdk deploy`를 직접 실행한다면
`--context admin_email=...`를 반드시 전달해야 하며, 그렇지 않으면 SNS 예산 경보가
플레이스홀더로 되돌아갑니다). 끝에서 **Admin Dashboard URL**과 **API endpoint**를 출력합니다.

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
> 참조가 S3에서 *읽는* 쪽이었고 쓰는 쪽이 없어서, 유일한 레시피가 아래 수동 절차였습니다.
> `cache_models.sh`는 대체가 아닙니다 — 다른 프리픽스(`model-cache/`)에 다른 레이아웃(평면
> `hf download --local-dir`, `models--org--name/snapshots/<sha>/…`이 아님)으로 씁니다.
>
> 결과적으로 두 가지가 실제로 물렸습니다:
> * **새 리전에는 재구축이 아니라 복사.** 시딩된 리전에서 버킷 간 `aws s3 sync`
>   ([ADDING_A_REGION.md](ADDING_A_REGION.md) §4). 2026-09-26에 ap-northeast-2를 `cache_models.sh`로
>   시딩했고 M5/M6/M9/M10이 죽은 상태로 출하됐습니다.
> * **추론하지 말고 검증.** `./scripts/check_seeding.sh --region <r>`가 런타임 glob이 테스트하는
>   `models--nvidia--*` 디렉터리 5개와 고정된 `tokenizer.pth` blob을 단정합니다.
>   `cache_models.sh`가 초록불로 끝난 것은 이 프리픽스에 대해 아무것도 증명하지 않습니다.

M5/M6/M9은 런타임에 HF의 **자체 캐시 레이아웃**을 통해 게이트된 체크포인트를 로드합니다
(M9은 숨겨진 Cosmos-Reason2-8B 백본도 가져옵니다). 이를 견고하게 채우는 방법:
당신의 관리자 토큰으로 **GPU JupyterLab 앱에서 M5, M6, M9을 각각 한 번씩 실행**한 뒤,
캐시 트리를 동기화하세요:
```bash
aws s3 sync /mnt/sagemaker-nvme/hf/hub s3://<shared>/hf-cache/hub/ --only-show-errors
```
`setup_cosmos_env.sh`는 이것을 `HF_HOME`으로 복원하고 `HF_HUB_OFFLINE=1`을 설정하므로,
참가자는 토큰 없이 오프라인으로 실행합니다. **M9은 데모 클립도 필요합니다**(그 데이터셋은
오프라인으로 읽을 수 없음):
```bash
source /mnt/sagemaker-nvme/cosmos-work/alpamayo_env.sh
unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE   # this save must be online
python scripts/alpamayo_save_clip.py --clip 030c760c-ae38-49aa-9ad8-f5650a545d26 \
  --t0-us 5100000 --out /mnt/sagemaker-nvme/m6_work/clips
aws s3 cp /mnt/sagemaker-nvme/m6_work/clips/030c760c-*.pt s3://<shared>/hf-cache/alpamayo-demo/
```
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

> **`scripts/patch_notebooks.py`에 관한 참고:** 이전 부트스트랩에서 사용하던 수동
> in-place `.ipynb` 트랜스포머입니다. **어떤 자동화(배포, CDK,
> 프로비저닝)에도 연결되어 있지 않습니다** — 리포의 `notebooks/*.ipynb`가 유일한
> 진실 공급원입니다. 이제 모든 모듈 항목이 `[]`(no-op)이며, 노트북이 기대 패턴에서
> 벗어나면 도구가 **하드 페일**하므로, 패치되지 않은 노트북을 조용히 배포하는 일은
> 절대 없습니다. 평소에는 실행할 일이 없습니다 — 노트북을 직접 편집하고
> §6.5를 통해 다시 동기화하세요. 그 노트북들이 의존하는 모듈 간 S3 계약은
> [DATA_CONTRACT.md](DATA_CONTRACT.md)에 있습니다.

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

1. Admin Dashboard → **Add User** → 테스트 이름 + 이메일 → **Provision**.
2. 성공 다이얼로그에서 **Participant Dashboard Link**를 복사하세요(내구성 있는
   `?userId=&token=` 링크 — 5분짜리 "Direct workspace URL"이 **아님**).
3. 그 링크를 새 브라우저에서 열면 → 12개 모듈 노드가 있는 Pipeline Map(M1~M12. M0은 개요 노트북이라 노드가 없습니다)이 렌더링됩니다.
4. **M2** 클릭 → **Instance Options** → 권장 `ml.g5.12xlarge`가 미리 선택됨 →
   **Apply & Restart** → **Open Workspace** → JupyterLab이 열립니다.
4b. **스코프 IAM 조건이 실제로 해석되는지 확정(무료, ~1분).** 그 앱이 실행 중인 상태에서
   테스트 사용자로 Studio **자체**를 엽니다(딥링크가 아니라 Studio 콘솔). 스페이스 페이지에서
   **Run space**, 그다음 **Open JupyterLab**을 클릭하고, `sagemaker:UpdateSpace` /
   `sagemaker:CreatePresignedDomainUrl`에 대한 `AccessDenied`가 나는지 기록합니다.
   - **AccessDenied 없음** → `${sagemaker:DomainId}` / `${sagemaker:UserProfileName}`
     정책 변수가 런타임에 해석됩니다. 따라서 `CreateApp`/`DeleteApp`을 `resources=["*"]`에서
     같은 소유자 조건으로 좁힐 수 있습니다. `infra/av30_constructs/sagemaker.py`의
     `SageMakerStudioAppLifecycle` 문장에 붙은 주석을 보세요.
   - **AccessDenied 발생** → 이 계정에서는 해석되지 않습니다. `CreateApp`은 넓은 상태로
     두고, 참가자에게는 계속 대시보드 버튼을 쓰게 합니다.
5. **M1**(CPU)을 엔드투엔드로 실행한 뒤 **M2**(GPU)를 실행 — GPU 이미지가
   자동 선택되고 모델 캐시가 해석되는지 확인합니다.
6. M12/M11을 실행한다면, 테스트 사용자로 각각 한 번씩 실행하여 작업
   쿼터(§2b)와 IAM이 갖춰졌는지 확인하세요 — 실제 관리형 작업을 제출합니다.
7. 테스트 사용자를 **Delete**하세요(Users 탭 → Delete) — 앱/스페이스/프로필 + S3를 제거합니다.

---

## 9. 참가자 프로비저닝 (D0)

**단일 사용자:** Admin Dashboard → **Add User** → 이름 + 이메일 → **Provision**.
**Participant Dashboard Link**(내구성 있음, 만료 없음)를 전달하세요. Users
테이블에는 사용자별 복사 버튼이 있는 **Dashboard Link** 열이 있습니다.

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
  제시하는 대안 중 아무거나 고르라고 알리세요 — 목록은 이미 이 리전이 판매하는
  타입으로 걸러져 있고, 쿼터가 0인 타입은 수락되지 않고 설명과 함께 거부됩니다.
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
| M12 작업이 제출에서 실패 (`CreateTrainingJob`에 `AccessDeniedException`) | exec-role의 training-job ARN 프리픽스가 노트북 `JOB_NAME`과 일치해야 합니다. 모듈 재번호로 HyperPod가 M9→M12로 옮겨져 노트북은 `av30-m12-distributed-*`를 제출하는데, 그 수정 이전 배포는 여전히 `av30-m9-*`만 허용해 모든 제출이 거부됩니다. m5.xlarge **작업** 쿼터(§2b)는 별개의 드문 원인입니다 — 에러를 먼저 보세요: `AccessDenied`는 IAM 프리픽스, `ResourceLimitExceeded`는 쿼터. |
| GPU 인스턴스에서 참가자 "No GPU detected" | CPU 이미지가 선택됨 — Instance Options로 다시 Apply. |
| M5/M6/M9 설정 셀이 "this region has no usable offline HuggingFace cache and no HF_TOKEN"으로 멈춤(exit 2) | 이 리전에 `hf-cache/hub/`가 시딩되지 않음(§6.3). 시딩 후 `./scripts/check_seeding.sh --region <r>`. 이 메시지는 *고쳐진* 동작입니다 — 2026-09-26 전에는 같은 조건이 침묵이었고, 설정 셀이 "environment ready"를 출력한 뒤 M5가 `torchrun`에서 4초 만에 `ChildFailedError`로 죽으며 CUDA out-of-memory를 지목했습니다. 아직 그 옛 형태가 보이면 참가자가 낡은 스테이징 `setup_cosmos_env.sh`를 쓰는 중입니다. |
| M5/M6/M9이 `Local entry not found … offline mode is enabled`로 실패 | 복원된 캐시가 **부분적**입니다. 중단된 `aws s3 sync`가 흔한 원인이고 — **같은 sync를 다시 돌리세요**, 이어서 없거나 크기가 다른 것을 재복사합니다. `sync`가 못 잡는 건 크기는 맞고 내용이 틀린 객체입니다(size+mtime 비교). `check_seeding.sh --source-region <seeded>`가 CRC64 불일치를 보고하면 그 객체만 지우고 다시 sync하세요. |
| M9이 클립 로드에 실패 | 데모 `.pt`가 `hf-cache/alpamayo-demo/`에 업로드되지 않음(§6.3). |
| M10 노트북이 아무것도 표시하지 않음(cell-4 가 "No M10 AlpaSim results found in S3" 발생) | `m10-reference/` 레퍼런스 평가가 실행되지 않음(§6.4). |
| M10 의 메트릭·그래프는 나오는데 **비디오만** 빈 화면 | **번들 누락이 아니며 §6.4 를 재실행하지 말 것.** 코덱 문제다: AlpaSim 렌더러가 MPEG-4 Part 2 로 쓰고 Chrome/Firefox/Edge 는 이를 디코딩하지 못한다. cell-7 이 찾은 코덱을 출력한다. GPU 호스트 없이 그 객체 하나만 H.264 로 교체하면 된다: `aws s3 cp s3://$SHARED_BUCKET/m10-reference/eval/eval.mp4 .` 후 `ffmpeg -i eval.mp4 -vf scale=1280:-2 -c:v libx264 -pix_fmt yuv420p -movflags +faststart -an eval_h264.mp4` 를 돌려 `m10-reference/eval/eval.mp4` 로 덮어쓴다. `scripts/alpasim_ec2_setup.sh` 는 이제 업로드 시점에 변환하므로, 그 변경 이후에 만든 번들은 이미 H.264 다. |
| M4 검색 데모가 **같은 캡션을 여러 번** 랭크하고, 인덱스 셀이 삭제에서 `403 authorization_exception` 을 출력 | 컬렉션의 데이터 액세스 정책이 **`aoss:DeleteIndex`** 부여 이전 것이어서 M4 가 인덱스를 비울 수 없습니다. AOSS 는 호출자 지정 `_id` 를 거부하므로 `index()` 는 항상 INSERT — 재실행마다 전체 사본이 추가됩니다(실측: 캡션 24개에 문서 24 → 48 → 72 → 96 → 120). 참가자 역할은 정책을 고칠 수 없습니다: `aoss:UpdateAccessPolicy` 를 일부러 주지 않았는데, `collection/*` 범위에서는 한 참가자가 다른 참가자의 컬렉션에 접근할 수 있게 되기 때문입니다. admin 자격증명으로 **컬렉션과 데이터 정책을 둘 다** 삭제하세요(정책이 남으면 그게 옛 정책입니다). 그 뒤 참가자가 Run All 하면 M4 가 권한 포함해 재생성합니다: `aws opensearchserverless list-collections --region $REGION --query 'collectionSummaries[?starts_with(name,\`av30-semantic-\`)].[id,name]' --output text` → `aws opensearchserverless delete-collection --id <id> --region $REGION` → `aws opensearchserverless delete-access-policy --name <name>-access --type data --region $REGION`. |
| M7 트레이닝 셀이 gsplat에서 실패 | M7 셀 3(`scripts/setup_gsplat_env.sh`) 재실행 — CUDA 빌드는 세션별이며 앱 재시작 시 리셋됨. §11. |
| SNS 예산 경보가 placeholder@example.com으로 감 | `--context admin_email` 없이 배포됨 — `deploy.sh`로 재배포. |
| 참가자 링크가 "Demo Mode"를 표시 | 맨 URL을 열었음; 전체 `?userId=&token=` 링크를 다시 보내세요. |
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
