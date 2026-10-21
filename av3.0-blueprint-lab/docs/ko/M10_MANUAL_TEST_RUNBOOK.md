# M10 수작업 테스트 런북 (Part A: admin GPU 실행 → Part B: 참가자 노트북)

M10은 두 겹이다. **Part A** = admin이 GPU EC2에서 진짜 AlpaSim을 돌려 `m10-reference/`를
만드는 것(무겁고 1회성). **Part B** = 참가자가 CPU 노트북에서 그 결과를 시각화하는 것(가볍고
반복). "둘 다 순서대로"는 A로 참조 결과를 새로 만들고 → B로 그걸 노트북에서 보는 흐름이다.

> 레퍼런스 배포에서 이미 성공적으로 실행돼 `s3://av30lab-shared-data-<aws-account-id>-<region>/m10-reference/`
> 에 진짜 결과가 올라간 적이 있다. 그런 참조 결과가 이미 있으면 **Part B만 단독으로 돌려도 완전한
> 검증**이 된다. Part A는 "처음부터 다시 재현"을 원할 때만 필요하다(~$30, 2-3시간).

---

## 0. 자격증명 갱신 (둘 다 공통, 먼저)

로컬 세션 토큰이 만료됐다. **이 랩을 배포한 AWS 계정의 admin**으로 재로그인 후, 모든 aws
호출은 **6-env-unset 래퍼**로 감싼다(다른 계정의 자격증명이 섞여 새는 것을 방지).

> **⚠️ 이 단계를 건너뛰지 말 것.** 아래 `UN()`은 셸 **함수**다 — 이 뒤의 모든 `UN aws …`
> 명령이 이 함수에 의존한다. 정의하지 않고 A2/A3/C* 블록을 붙여넣으면
> `command not found: UN` 이 나고 (예: `AMI=` 가 빈 값) 이후 전부 실패한다.
> 셸 함수는 **현재 터미널 세션 안에서만** 유효하므로, **새 터미널을 열 때마다
> (또는 자격증명이 만료될 때마다) 이 블록을 다시 실행**해야 한다.

> **계정/리전은 하드코딩하지 않는다.** 아래에서 `ACCOUNT`를 `sts`로 자동 도출하고
> 버킷 이름을 거기서 파생한다 — 이 문서의 이후 모든 명령은 이 변수들을 쓰므로,
> **다른 AWS 계정/리전에서도 그대로** 동작한다. (문서 본문의 `<aws-account-id>` /
> `<region>`은 예시 자리표시자일 뿐이다.)

```bash
# Isengard/SSO 등 평소 쓰는 방식으로 로그인 후:
UN() { env -u AWS_PROFILE -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY \
             -u AWS_SESSION_TOKEN -u AWS_SHARED_CREDENTIALS_FILE -u AWS_CONFIG_FILE "$@"; }
UN aws sts get-caller-identity --query '[Account,Arn]' --output text
# → <당신의 계정 id>  arn:aws:...:assumed-role/...

# 이 랩이 배포된 계정/리전 → 이후 모든 블록이 쓰는 변수 (하드코딩 대신 여기서 한 번 정의)
export REGION=<region>                                    # 당신이 배포한 리전으로 (예: us-west-2)
export ACCOUNT=$(UN aws sts get-caller-identity --query Account --output text)
export SHARED_BUCKET=av30lab-shared-data-${ACCOUNT}-${REGION}       # 모델/데이터/노트북 템플릿 + m10-reference
export USER_BUCKET=av30lab-user-workspace-${ACCOUNT}-${REGION}      # 참가자별 users/<id>/ (Part C에서 사용)
echo "ACCOUNT=$ACCOUNT REGION=$REGION"
echo "SHARED_BUCKET=$SHARED_BUCKET"
```

---

# Part A — admin: GPU EC2에서 진짜 AlpaSim 재실행 (~$30, 선택)

## A1. 사전 준비물
- **HF 토큰**: Alpamayo-1.5-10B + Cosmos-Reason2-8B + PhysicalAI NuRec 데이터셋 라이선스가
  모두 승인된 토큰(admin 본인의 HF 계정으로 미리 승인해 둔다).
- **NGC API 키**: 사실 렌더러 이미지 `nvcr.io/nvidia/nre/nre-ga:26.04`는 **공개 pull 가능**
  (게이트0에서 확인)이라 키 없어도 됨. 스크립트가 키 없으면 anonymous pull로 폴백한다.

## A2. GPU 호스트 launch (수동 — launch 스크립트는 없음)

> **⚠️ 인스턴스는 반드시 GPU ≥2장. 이름의 숫자 ≠ GPU 개수.** 기본 topology(`2gpu`)는
> renderer를 **GPU 1**에 올리므로 **최소 2 GPU**가 필요하다. g6e 계열에서 **vCPU가 큰
> 사이즈라고 GPU가 더 많은 게 아니다** — 멀티-GPU는 **12xlarge(4), 24xlarge(4), 48xlarge(8)**
> 뿐이고, 그 외(**16xlarge 포함**)는 전부 **GPU 1장**이다. "16 > 12니까 더 크겠지"로
> `g6e.16xlarge`를 고르면 GPU 1장이라 실행 직전
> `Service renderer requested GPUs [1] but only 0 .. 0 are available` 로 죽는다.
>
> | g6e size | GPUs | vCPU | M10(2gpu) |
> |---|---|---|---|
> | xlarge / 2xlarge / 4xlarge / 8xlarge | **1** | 4–32 | ❌ |
> | **g6e.12xlarge** | **4** | 48 | ✅ **권장** |
> | g6e.16xlarge | **1** | 64 | ❌ (더 큰데 GPU는 1장!) |
> | g6e.24xlarge | **4** | 96 | ✅ (과함) |
> | g6e.48xlarge | **8** | 192 | ✅ (과함) |
>
> launch 후 반드시 확인: `nvidia-smi --query-gpu=index,name --format=csv` 가 **2줄 이상**.
> (80 GB 단일 카드 p4de/p5 는 `topology=1gpu`로 1장도 가능.)

게이트2 때 이 단계는 수동이었다. 아래를 순서대로:

```bash
# ⟸ 먼저 §0의 UN() 래퍼 + ACCOUNT/REGION/SHARED_BUCKET 변수를 정의했어야 함
#    (안 하면 'command not found: UN' 또는 빈 버킷 이름).
# (a) Deep Learning Base GPU AMI 최신 ID 조회 (Docker+NVIDIA toolkit+driver 내장)
AMI=$(UN aws ssm get-parameter --region $REGION \
  --name /aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-22.04/latest/ami-id \
  --query Parameter.Value --output text)
echo "AMI=$AMI"

# (b) 기본 VPC의 퍼블릭 서브넷 (랩 VPC는 isolated egress 불가 → default VPC 사용)
# 전제: 이 계정/리전에 default VPC + 퍼블릭 서브넷(map-public-ip-on-launch=true)이 있어야 함.
#   - 조직 계정 등 default VPC가 삭제됐거나 퍼블릭 서브넷이 없으면 VPC/SUBNET 이 'None'/빈 값이
#     되고, 아래 run-instances 가 알 수 없는 에러로 실패한다. 그 경우:
#       * 직접 지정: SUBNET=subnet-xxxx (IGW로 egress 되는 퍼블릭 서브넷), SG도 그 VPC 것으로
#       * 또는 `aws ec2 create-default-vpc --region $REGION` 로 default VPC 생성.
#   - Subnets[0] 는 첫 서브넷(=AZ 임의)이다. 그 AZ에 g6e.12xlarge 용량이 없으면 launch 가
#     InsufficientInstanceCapacity 로 실패할 수 있다 → 다른 AZ의 서브넷 id 로 SUBNET 을 바꿔 재시도.
VPC=$(UN aws ec2 describe-vpcs --region $REGION --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].VpcId' --output text)
SUBNET=$(UN aws ec2 describe-subnets --region $REGION \
  --filters Name=vpc-id,Values=$VPC Name=map-public-ip-on-launch,Values=true \
  --query 'Subnets[0].SubnetId' --output text)
echo "VPC=$VPC SUBNET=$SUBNET"
# VPC/SUBNET 이 None/빈 값이면 여기서 멈추고 위 주석대로 조치 (빈 채로 진행하면 run-instances 가 실패).
[ -n "$VPC" ] && [ "$VPC" != "None" ] && [ -n "$SUBNET" ] && [ "$SUBNET" != "None" ] \
  || { echo "ERROR: default VPC/퍼블릭 서브넷을 못 찾음 — 위 (b) 주석 참조 (직접 지정 또는 create-default-vpc)"; }

# (c) 보안그룹 (egress만 필요; SSM 접속이라 인바운드 불필요)
SG=$(UN aws ec2 create-security-group --region $REGION \
  --group-name av30-alpasim-m7 --description "M10 AlpaSim egress" \
  --vpc-id $VPC --query GroupId --output text)
# (인바운드 규칙 추가 안 함 — SSM Session Manager로 접속)

# (d) IAM instance-profile (랩계정에 없음 → 즉석 생성). hf-cache read + m10-reference write + KMS + SSM.
UN aws iam create-role --role-name av30-alpasim-m7-$REGION \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
UN aws iam attach-role-policy --role-name av30-alpasim-m7-$REGION \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
# 정책 JSON은 $SHARED_BUCKET 이 확장되도록 heredoc으로 만든다(single-quote면 확장 안 됨).
UN aws iam put-role-policy --role-name av30-alpasim-m7-$REGION --policy-name s3-hfcache-m7ref \
  --policy-document "$(cat <<JSON
{"Version":"2012-10-17","Statement":[
  {"Effect":"Allow","Action":["s3:GetObject","s3:ListBucket"],"Resource":["arn:aws:s3:::${SHARED_BUCKET}","arn:aws:s3:::${SHARED_BUCKET}/*"]},
  {"Effect":"Allow","Action":["s3:PutObject"],"Resource":"arn:aws:s3:::${SHARED_BUCKET}/m10-reference/*"},
  {"Effect":"Allow","Action":["kms:Decrypt","kms:GenerateDataKey"],"Resource":"*"}]}
JSON
)"
UN aws iam create-instance-profile --instance-profile-name av30-alpasim-m7-$REGION
UN aws iam add-role-to-instance-profile --instance-profile-name av30-alpasim-m7-$REGION --role-name av30-alpasim-m7-$REGION

> **IAM 이름에 `-$REGION` 접미사를 붙이는 이유.** IAM 역할·인스턴스 프로파일 이름은 **계정 전역**이다
> (위의 보안그룹은 VPC 단위이므로 접미사 없이 그대로 둔다). 접미사가 없으면 두 번째 리전의 M10 실행이
> `EntityAlreadyExists`로 실패하고, 더 심각하게는 아래 teardown 블록이 "다음 실행 시 이름 충돌을 막기
> 위해" 이를 무조건 삭제하므로 **어느 한 리전에서 M10을 teardown하면 다른 리전에서 실행 중인 GPU
> 호스트가 쓰는 역할이 지워진다**. 생성과 teardown 양쪽에 접미사를 붙이면 두 배포가 독립을 유지한다
> (이 랩의 모델: 배포당 한 리전 — `docs/en/ADDING_A_REGION.md` 참조).
sleep 15   # IAM 전파 대기

# (e) launch: g6e.12xlarge (4× L40S 48GB), gp3 300GB, 퍼블릭 IP
IID=$(UN aws ec2 run-instances --region $REGION \
  --image-id $AMI --instance-type g6e.12xlarge \
  --subnet-id $SUBNET --security-group-ids $SG --associate-public-ip-address \
  --iam-instance-profile Name=av30-alpasim-m7-$REGION \
  --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=300,VolumeType=gp3}' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=av30-alpasim-m7}]' \
  --query 'Instances[0].InstanceId' --output text)
echo "INSTANCE=$IID"
UN aws ec2 wait instance-status-ok --region $REGION --instance-ids $IID   # ~2-3분
```

## A3. 호스트에서 실행 (SSM Session Manager로 접속)
```bash
# ⟸ 먼저 §0의 UN() 래퍼 + REGION 변수를 정의했어야 함 (안 하면 'command not found: UN').
UN aws ssm start-session --region $REGION --target $IID
# --- 세션 안에서 (root) --- (여기부터는 GPU 호스트 위. 로컬 §0 변수는 없으므로 다시 정의)
sudo su -
export HF_TOKEN=hf_xxx                 # A1의 승인된 토큰
export NGC_API_KEY=nvapi-xxx           # 선택 (없으면 생략 — anonymous pull)
# 계정을 인스턴스 역할로 도출 → 버킷 이름 파생 (하드코딩 대신). 호스트엔 aws CLI 내장.
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export SHARED_BUCKET=av30lab-shared-data-${ACCOUNT}-${REGION}
# 스크립트 가져오기 (S3 스테이징본 사용):
aws s3 cp s3://$SHARED_BUCKET/notebook-templates/scripts/alpasim_ec2_setup.sh /root/
# ── 실행 (DETACHED 기본 — 아래 경고 참조) ─────────────────────────────────────
# setsid 로 세션에서 분리해 백그라운드 실행. SSM 세션이 끊겨도(재로그인/타임아웃)
# 죽지 않고, 로그는 리다이렉트라 버퍼 유실도 없다. 재접속 후 tail -f 로 다시 붙는다.
setsid bash /root/alpasim_ec2_setup.sh > /var/log/alpasim_m7.log 2>&1 &
echo "started PID $!"
tail -f /var/log/alpasim_m7.log   # Ctrl-C 로 빠져나와도 백그라운드 실행은 계속됨
```

> **⚠️ `... | tee` (포그라운드) 로 돌리지 말 것 — 긴 실행에서 세션 끊기면 통째로 죽는다.**
> `bash setup.sh 2>&1 | tee log` 는 **SSM 세션에 붙어있는** 파이프라인이라, Claude Code
> 재로그인·네트워크 끊김·SSM 유휴 타임아웃이 오면 SIGHUP 으로 **파이프라인 전체(스크립트
> 포함)가 종료**되고, tee 버퍼에 있던 로그도 flush 안 돼 **로그 파일이 0바이트**가 될 수
> 있다(실제로 겪은 함정). 이 스크립트는 wizard 실행 + docker 컨테이너 기동까지 수십 분이
> 걸리므로 **반드시 위 `setsid` 방식**을 쓴다. (아주 짧게 포그라운드로 지켜볼 때만 tee.)
>
> **중단됐다가 재실행할 때** (프로세스/컨테이너 잔재 정리 후 재개 — clone/빌드/캐시는 남아
> 있어 빠르다):
> ```bash
> docker ps -aq | xargs -r docker rm -f    # 중단된 컨테이너 정리
> setsid bash /root/alpasim_ec2_setup.sh > /var/log/alpasim_m7.log 2>&1 &
> tail -f /var/log/alpasim_m7.log
> ```
스크립트가 하는 일: preflight(nvidia-smi/docker/uv/cargo) → hf-cache 복원 → alpasim clone
(tag v2026.5 — alpasim-base-v0.96.0은 상류에 더 이상 없음. 아래 참고) → NGC login(옵션)+이미지 접근 확인 → `source setup_local_env.sh`
→ mount 디렉토리 생성 → `deploy/local_m7.yaml`(driver HF-offline) + `topology/m7_4gpu.yaml`
(driver 단독 GPU0) 작성 → `uv run alpasim_wizard ...` 실행 → 결과 검증 → `s3://.../m10-reference/`
업로드. **첫 빌드는 오래 걸린다(protos 컴파일 + 이미지 pull + NuRec 씬 다운로드).**
재실행 시 clone/빌드/hf-cache/NuRec 씬은 남아 있어 wizard 단계부터라 훨씬 빠르다.

### 로그로 성공/실패 판정하기
`tail -f`가 더 이상 갱신되지 않으면 **성공(끝남) 또는 실패(중단)** 둘 중 하나다 — 로그
**마지막 부분**을 보고 가른다 (`tail -n 40 /var/log/alpasim_m7.log`).

- **✅ 성공**: 로그 끝에 스크립트의 완료 마커가 있다.
  ```
  runtime-0-1 exited with code 0            # eval 컨테이너가 0으로 정상 종료
  [verify] core outputs present.
  [upload] -> s3://.../m10-reference/ ...
  === DONE — genuine AlpaSim results uploaded to s3://.../m10-reference/ ===
  ```
  성공 시 `tail -f`가 멈추는 것은 **정상**이다(스크립트가 끝나 백그라운드 프로세스가 종료됨 —
  죽은 게 아니다). 최종 확정은 A4의 S3 확인(오늘 날짜).
  > 참고: 완료 직후 `renderer/physics/controller` 컨테이너가 `exited with code 143`(SIGTERM)/
  > `137`(SIGKILL)로 찍히는 건 **정상**이다 — 주 컨테이너(runtime)가 0으로 끝난 뒤 docker
  > compose가 나머지 서비스를 내리는 것. `runtime-0-1 exited with code 0` + `=== DONE ===`
  > 이 있으면 성공이다.

- **❌ 실패/중단**: 로그 끝에 `=== DONE ===`가 **없고** 대신 다음 중 하나면 실패다.
  - `ERROR: ...` 로 끝남 (preflight 실패, 필수 출력 누락 등 — 스크립트가 exit).
  - `Error executing job` / `RuntimeError: ...` (wizard 실행 실패, 예: GPU 부족).
  - 로그가 **중간에서 뚝 끊김** + 프로세스도 없음 → 세션 끊김 등으로 중단됨
    (`ps aux | grep -E "[a]lpasim|[w]izard"` 로 프로세스 생존 확인; docker `docker ps`).
  → 원인을 고친 뒤 위 "중단됐다가 재실행" recipe로 재개.

빠르게 성공 여부만 확인:
```bash
grep -q "=== DONE" /var/log/alpasim_m7.log && echo "M10 성공 (S3 업로드 완료)" \
  || echo "M10 미완 — 로그 끝(tail -n 40)에서 ERROR/RuntimeError/중단 지점 확인"
```

## A4. 성공 확인 → **즉시 terminate** (과금 중단)
```bash
# ⟸ 먼저 §0의 UN() 래퍼 + SHARED_BUCKET/REGION 변수를 정의했어야 함.
# 로컬(자격증명)에서:
UN aws s3 ls s3://$SHARED_BUCKET/m10-reference/ --recursive --region $REGION
# aggregate/results-summary.json + metrics_results.{txt,png,parquet} + rollouts/**/metrics.parquet
# + eval/eval.mp4 + run.json 이 보이면 성공.

# !!! 반드시 정리 (안 하면 시간당 ~$10.5 계속 과금) !!!
UN aws ec2 terminate-instances --region $REGION --instance-ids $IID
UN aws ec2 wait instance-terminated --region $REGION --instance-ids $IID
# IAM/SG도 정리 (다음 실행 때 이름충돌 방지):
UN aws iam remove-role-from-instance-profile --instance-profile-name av30-alpasim-m7-$REGION --role-name av30-alpasim-m7-$REGION
UN aws iam delete-instance-profile --instance-profile-name av30-alpasim-m7-$REGION
UN aws iam delete-role-policy --role-name av30-alpasim-m7-$REGION --policy-name s3-hfcache-m7ref
UN aws iam detach-role-policy --role-name av30-alpasim-m7-$REGION --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
UN aws iam delete-role --role-name av30-alpasim-m7-$REGION
UN aws ec2 delete-security-group --region $REGION --group-id $SG
```

**⚠️ 최대 리스크 = terminate 망각.** 확인 즉시 종료할 것. (호스트에서 `shutdown -h +180`을
백업 가드로 걸어둘 수도 있다.)

---

# Part C — admin: 참가자별 자가실행 프로비저닝 (참가자가 직접 AlpaSim을 돌릴 때)

Part A는 admin이 **공유 참조 결과 1벌**(`m10-reference/`)을 만드는 것이다. 아래 Part C는
**참가자마다 자기 GPU 호스트에서 직접 AlpaSim을 돌리게** 할 때(참가자 실행 가이드 =
[M10_PARTICIPANT_SSM_RUNBOOK.md](M10_PARTICIPANT_SSM_RUNBOOK.md)) admin이 하는 사전 배선이다.

> **비용/상한 경고**: g6e.12xlarge = **48 vCPU/대**, ~**$10.5/hr/대**. G-vCPU quota 768 →
> **동시 최대 16대(=16명)**. launch 전 반드시 quota 확인:
> `UN aws service-quotas get-service-quota --region $REGION --service-code ec2 --quota-code L-DB2E81BA`

## C1. instance-profile 정책 확장 (참가자는 user-workspace에 씀)
Part A의 `av30-alpasim-m7` 인스턴스 역할은 `m10-reference/`에만 write한다. 참가자 자가실행은
`users/<id>/m10/`에 써야 하므로 정책을 확장한다(prefix 제한으로 여러 참가자 공유 가능):
```bash
# ⟸ 먼저 §0의 UN() 래퍼 + SHARED_BUCKET/USER_BUCKET 변수를 정의했어야 함.
UN aws iam put-role-policy --role-name av30-alpasim-m7-$REGION --policy-name s3-participant-m7 \
  --policy-document "$(cat <<JSON
{"Version":"2012-10-17","Statement":[
  {"Effect":"Allow","Action":["s3:GetObject","s3:ListBucket"],"Resource":["arn:aws:s3:::${SHARED_BUCKET}","arn:aws:s3:::${SHARED_BUCKET}/*"]},
  {"Effect":"Allow","Action":["s3:PutObject"],"Resource":"arn:aws:s3:::${USER_BUCKET}/users/*/m10/*"},
  {"Effect":"Allow","Action":["kms:Decrypt","kms:GenerateDataKey"],"Resource":"*"}]}
JSON
)"
```

## C2. 참가자별 GPU 인스턴스 launch (Part A2 재사용 + Participant 태그)
Part A2의 (e) `run-instances`에 참가자 태그를 추가한다(공유 SG/instance-profile 재사용):
```bash
# ⟸ 먼저 §0의 UN() 래퍼를 정의 + 자격증명 갱신해야 함 (안 하면 'command not found: UN').
PID=m10-test01     # 참가자 id
IID=$(UN aws ec2 run-instances --region $REGION \
  --image-id $AMI --instance-type g6e.12xlarge \
  --subnet-id $SUBNET --security-group-ids $SG --associate-public-ip-address \
  --iam-instance-profile Name=av30-alpasim-m7-$REGION \
  --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=300,VolumeType=gp3}' \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=av30-alpasim-$PID},{Key=Participant,Value=$PID}]" \
  --query 'Instances[0].InstanceId' --output text)
echo "$PID -> $IID"     # 이 매핑을 참가자에게 전달
UN aws ec2 wait instance-status-ok --region $REGION --instance-ids $IID
```

## C3. 참가자 SSM 자격증명 — 두 방식

### 옵션 1 — 참가자별 IAM user + exact-ARN (사전 테스트 / 소규모, 권장)
참가자당 IAM user를 만들고 **그 인스턴스 ID를 정책에 직접 박아** 자기 인스턴스에만 접속 허용.
`ssm:TerminateSession`은 **자기 세션 종료만** — 인스턴스 terminate는 불가(비용 사고 방지).
```bash
# ⟸ 먼저 §0의 UN() 래퍼를 정의 + 자격증명 갱신해야 함 (안 하면 'command not found: UN').
UN aws iam create-user --user-name $PID
# heredoc으로 $REGION/$ACCOUNT/$IID 는 확장하고, IAM 정책 변수 ${aws:...} 는 \$ 로 보존.
UN aws iam put-user-policy --user-name $PID --policy-name m10-ssm --policy-document "$(cat <<JSON
{
  "Version":"2012-10-17","Statement":[
   {"Sid":"StartOwnInstance","Effect":"Allow","Action":["ssm:StartSession"],
    "Resource":["arn:aws:ec2:${REGION}:${ACCOUNT}:instance/${IID}",
                "arn:aws:ssm:${REGION}:${ACCOUNT}:document/SSM-SessionManagerRunShell"]},
   {"Sid":"Describe","Effect":"Allow","Action":["ssm:DescribeSessions","ssm:GetConnectionStatus","ssm:DescribeInstanceProperties","ec2:DescribeInstances"],"Resource":"*"},
   {"Sid":"TerminateOwnSessionOnly","Effect":"Allow","Action":["ssm:TerminateSession","ssm:ResumeSession"],"Resource":["arn:aws:ssm:*:*:session/\${aws:userid}-*"]},
   {"Sid":"OpenChannel","Effect":"Allow","Action":["ssmmessages:OpenDataChannel","ssmmessages:CreateControlChannel","ssmmessages:CreateDataChannel","ssmmessages:OpenControlChannel"],"Resource":"*"}]}
JSON
)"
UN aws iam create-access-key --user-name $PID   # → 참가자에게 out-of-band 전달
```

### 옵션 2 — ABAC 태그 매칭 (실제 워크숍 / N명)
정책 1벌만 만들고 **태그 일치**로 격리(인스턴스 ID 안 박음). user의 principal tag
`Participant=<id>`와 인스턴스 `Tag Participant=<id>`가 같아야 접속. C2에서 이미 인스턴스 태그를
붙였으니 user 쪽만:
```bash
# ⟸ 먼저 §0의 UN() 래퍼를 정의 + 자격증명 갱신해야 함 (안 하면 'command not found: UN').
UN aws iam create-user --user-name $PID --tags Key=Participant,Value=$PID
# heredoc으로 $REGION/$ACCOUNT 는 확장, IAM 정책 변수 ${aws:...} 는 \$ 로 보존.
UN aws iam put-user-policy --user-name $PID --policy-name m10-ssm-abac --policy-document "$(cat <<JSON
{
  "Version":"2012-10-17","Statement":[
   {"Sid":"StartTaggedInstance","Effect":"Allow","Action":["ssm:StartSession"],
    "Resource":"arn:aws:ec2:${REGION}:${ACCOUNT}:instance/*",
    "Condition":{"StringEquals":{"ssm:resourceTag/Participant":"\${aws:PrincipalTag/Participant}"}}},
   {"Sid":"StartDoc","Effect":"Allow","Action":["ssm:StartSession"],"Resource":"arn:aws:ssm:${REGION}:${ACCOUNT}:document/SSM-SessionManagerRunShell"},
   {"Sid":"Describe","Effect":"Allow","Action":["ssm:DescribeSessions","ssm:GetConnectionStatus","ssm:DescribeInstanceProperties","ec2:DescribeInstances"],"Resource":"*"},
   {"Sid":"TerminateOwnSessionOnly","Effect":"Allow","Action":["ssm:TerminateSession","ssm:ResumeSession"],"Resource":["arn:aws:ssm:*:*:session/\${aws:userid}-*"]},
   {"Sid":"OpenChannel","Effect":"Allow","Action":["ssmmessages:OpenDataChannel","ssmmessages:CreateControlChannel","ssmmessages:CreateDataChannel","ssmmessages:OpenControlChannel"],"Resource":"*"}]}
JSON
)"
UN aws iam create-access-key --user-name $PID
```
> (대안 옵션 3 — 장기 access key 없이) 위 정책을 세션 정책으로 감싼 `sts get-federation-token`
> (≤36h) 임시 자격증명. 유출 위험 최소지만 발급 절차가 더 복잡 — 보안 엄격 환경에서.

## C4. 음성 테스트 (배선 검증, 필수)
발급한 참가자 키로(admin 키 아님) 격리가 실제로 걸리는지 확인:
```bash
# 참가자 키를 export한 셸에서:
REGION=us-west-2   # (참가자 셸엔 §0 변수가 없으므로 여기서 정의; 배포 리전으로)
aws ssm start-session --target $IID --region $REGION          # ✓ 성공해야
aws ssm start-session --target <다른-인스턴스> --region $REGION # ✗ AccessDenied 여야
aws ec2 terminate-instances --instance-ids $IID --region $REGION # ✗ 거부 여야 (참가자는 종료 불가)
```

## C5. 참가자 실행 → 완료 통보 → admin 정리
- 참가자는 [M10_PARTICIPANT_SSM_RUNBOOK.md](M10_PARTICIPANT_SSM_RUNBOOK.md)를 따라 실행하고
  결과를 `users/<id>/m10/`에 올린 뒤 **완료를 통보**한다.
- admin은 통보받는 즉시 정리(태그로 일괄 조회 가능):
```bash
# ⟸ 먼저 §0의 UN() 래퍼를 정의 + 자격증명 갱신해야 함 (안 하면 'command not found: UN').
# 특정 참가자 종료
UN aws ec2 terminate-instances --region $REGION --instance-ids $IID
# 남은 참가자 인스턴스 일괄 조회
UN aws ec2 describe-instances --region $REGION \
  --filters "Name=tag:Participant,Values=*" "Name=instance-state-name,Values=running,pending" \
  --query 'Reservations[].Instances[].[InstanceId,Tags[?Key==`Participant`]|[0].Value]' --output text
# IAM user 정리 (키 먼저 삭제)
UN aws iam list-access-keys --user-name $PID --query 'AccessKeyMetadata[].AccessKeyId' --output text \
  | tr '\t' '\n' | while read k; do UN aws iam delete-access-key --user-name $PID --access-key-id "$k"; done
UN aws iam delete-user-policy --user-name $PID --policy-name m10-ssm 2>/dev/null || \
  UN aws iam delete-user-policy --user-name $PID --policy-name m10-ssm-abac 2>/dev/null
UN aws iam delete-user --user-name $PID
```

**⚠️ 최대 리스크 = 참가자 인스턴스 종료 망각.** 참가자는 못 끄므로 admin이 전담. Part A4의
공유 SG/instance-profile은 모든 참가자 인스턴스가 종료된 뒤 마지막에 정리.

---

# Part B — 참가자: Studio CPU 노트북에서 M10 시각화 (~$0, 5분)

이게 참가자가 실제로 겪는 경험이고, 게이트3의 "실제 Studio 환경" 갭을 메운다.

## B1. 참가자 대시보드 열기
1. admin 대시보드에서 테스트용 유저의 **participant dashboard link** 확보
   (`https://<user-dashboard>.cloudfront.net/?userId=<id>&token=<token>`).
   없으면 admin 대시보드 → Users → Provision으로 새 유저 하나 만들면 링크가 나온다.
2. 브라우저로 그 링크 열기 → Pipeline Map 표시.

## B2. 인스턴스 = CPU 확인 (M10은 GPU 불필요)
- M10 노트는 **`ml.t3.medium`(CPU)** 에서 돈다. 워크스페이스 기본이 t3.medium이므로
  **인스턴스 변경 불필요**. (M9에서 GPU로 올렸다면, M10 전에 Instance Options → t3.medium으로
  되돌리는 게 비용상 바람직 — GPU에서도 돌긴 하지만 낭비.)

## B3. 워크스페이스 열고 노트북 실행
1. 대시보드 우상단 **Open Workspace** → JupyterLab 탭.
2. 파일 브라우저에서 **`M10_AlpaSim_ClosedLoop.ipynb`** 열기.
3. **Run ▸ Run All Cells** (또는 Shift+Enter로 위→아래).

## B4. 통과 기준 (각 셀이 이렇게 나와야 함)
| 셀 | 기대 출력 |
|---|---|
| cell-2 config | Profile/Reference eval/M9 provenance 경로 출력 |
| cell-3 provenance | M9 manifest 있으면 open-loop minADE 표시, 없으면 "stand alone"(둘 다 정상) |
| cell-4 download | `aws s3 sync m10-reference/` → 아티팩트 목록(aggregate/, rollouts/, eval/, run.json) |
| cell-5 parse | AlpaSim 집계표 verbatim + 11개 driving score(collision 0.00, dist_to_gt 4.37m, progress 0.92) + "Per-rollout time-series: N rows" |
| cell-6 viz | metrics_results.png 인라인 + safety-rate 막대 + dist_to_gt_trajectory 시계열 |
| cell-7 video | eval.mp4 (~0.5MB, H.264 1280px) 인라인 재생 |
| cell-8 cost | CPU 정직한 프레이밍 + reference run 메타(g6e.12xlarge/m7_4gpu) |
| cell-9 validation | 4개 체크 OK → **PASS** + headline "no at-fault collisions, no off-road, route progress 0.92" + PIPELINE COMPLETE |

## B5. 흔한 실패 → 원인
| 증상 | 원인/해결 |
|---|---|
| cell-4 `M10 reference eval not found in S3` | m10-reference/ 미업로드 → Part A 먼저(또는 기존 번들 확인) |
| cell-4 download failed / AccessDenied | 실행역할이 shared 버킷 read 권한 없음 → 이미 있음(정상). 없으면 IAM 확인 |
| cell-7 video 빈 화면/미표시 | **파일 누락이 아니라 코덱 문제.** AlpaSim 렌더러가 MPEG-4 Part 2(`mpeg4`)로 쓰고 Chrome/Firefox/Edge는 이를 디코딩하지 못함 — 브라우저가 조용히 실패하며 이는 파이썬 예외가 아니므로 어떤 try/except도 잡지 못함. `ffprobe -show_entries stream=codec_name eval/eval.mp4` 로 확인. 근본 수정 완료: `alpasim_ec2_setup.sh` 가 업로드 전 H.264로 변환(호스트에 동작하는 ffmpeg가 없으면 그 사실을 출력), cell-7은 죽은 플레이어 대신 코덱을 출력함. 비필수 — 메트릭만으로도 PASS |
| STS/import 에러 | CPU 커널에 pandas/matplotlib 기본 포함 — 안 되면 첫 셀에서 `%pip install pandas matplotlib` |

---

## 참고: 로컬 사전검증 이미 완료
게이트3에서 노트북 셀 4-9의 **실제 소스**를 로컬 venv(pandas 2.3.3)로 라이브 S3 번들에 대해
실행 → 전부 PASS 확인함. Part B는 그것을 실제 Studio 환경에서 재확인하는 단계다(데이터 경로는
동일 소스라 이미 검증됨; 남은 것은 커널/네트워크/UI 렌더링 차이뿐).
