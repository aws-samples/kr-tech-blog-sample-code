# M10 참가자 실행 가이드 — 내 GPU 호스트에서 진짜 AlpaSim 돌리기 (SSM)

> ## ⚠️ 먼저 읽어주세요 — 비용과 시간
> - 이 실행은 **admin이 당신 몫으로 띄워둔 GPU 서버(g6e.12xlarge)** 위에서 돌아갑니다.
>   그 서버는 **시간당 약 $10.5**가 과금됩니다.
> - **첫 빌드는 오래 걸립니다** — 수십 분에서 최대 2~3시간(코드 컴파일 + 컨테이너 이미지
>   다운로드 + NuRec 씬 다운로드). 노트북처럼 5분에 끝나지 않습니다.
> - **당신은 서버를 끌 수 없습니다.** 끝나면 **반드시 admin에게 "완료"를 알려** admin이
>   서버를 종료(terminate)하게 하세요. 안 알리면 요금이 계속 쌓입니다.
> - 이건 M10의 **선택적 고급 경로**입니다. 그냥 결과만 보고 싶다면 admin의 공유 참조
>   결과를 노트북에서 시각화하면 됩니다(이 문서 없이, CPU, $0) — [ALPASIM_M10.md](ALPASIM_M10.md).

M10은 두 겹입니다. **(1) 진짜 AlpaSim 실행**은 GPU 서버에서(이 문서), **(2) 결과 시각화**는
SageMaker CPU 노트북에서 합니다. AlpaSim은 Docker-Compose로 뜨는 gRPC 마이크로서비스 fleet이고
드라이버가 ≥40GB GPU를 쓰기 때문에, Docker 데몬이 없는 SageMaker Studio 노트북에서는 실행이
불가능합니다. 그래서 실행은 별도 GPU EC2 호스트에서 하고, 노트북은 그 결과를 내려받아 봅니다.

---

## 준비물
admin에게서 받는 것:
1. **AWS access key** (Access Key ID + Secret) — 당신 전용 IAM 사용자.
2. **당신의 GPU 인스턴스 ID** (`i-0abc...` 형식).

당신이 미리 준비하는 것 (**필수**):
3. **당신의 Hugging Face 토큰** (`hf_...`). AlpaSim이 런타임에 게이트 NuRec 씬
   (`nvidia/PhysicalAI-Autonomous-Vehicles-NuRec`)을 다운로드하는데, 이 데이터셋은 admin의
   공유 오프라인 캐시에 **없어서**(모델과 달리) 당신 토큰이 필요합니다. 미리:
   - HF 계정 + 토큰 생성 (`https://huggingface.co/settings/tokens`)
   - [`nvidia/PhysicalAI-Autonomous-Vehicles-NuRec`](https://huggingface.co/datasets/nvidia/PhysicalAI-Autonomous-Vehicles-NuRec)
     에서 라이선스 동의("Agree and access repository")
   - (선택) `nvidia/Alpamayo-1.5-10B`, `nvidia/Cosmos-Reason2-8B` 도 동의해두면 안전 — 다만
     이 둘은 admin이 hf-cache에 넣어둬서 대개 오프라인으로 로드됩니다.

admin이 1·2를 out-of-band(슬랙/메일 등)로 전달합니다. 3은 당신 것이니 남에게 공유하지 마세요.

---

## 1. 자격증명 설정 + 확인
로컬 터미널(또는 CloudShell)에서:
```bash
export AWS_ACCESS_KEY_ID=<받은 키>
export AWS_SECRET_ACCESS_KEY=<받은 시크릿>
export REGION=us-west-2   # 레퍼런스 배포 리전; admin이 배포한 리전으로 교체
export AWS_DEFAULT_REGION=$REGION
aws sts get-caller-identity
export ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
# → 당신 IAM user ARN (arn:aws:iam::<account>:user/m7-<your-id>)가 나오면 정상 (레퍼런스 배포 예시: <aws-account-id>)
```
> Session Manager 플러그인이 필요합니다(대부분 설치돼 있음). 없으면:
> https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html

## 2. GPU 호스트에 SSM으로 접속
```bash
aws ssm start-session --target <your-instance-id> --region $AWS_DEFAULT_REGION
```
- 접속되면 셸 프롬프트가 뜹니다. (SSH 키·인바운드 포트 불필요 — SSM이 처리)
- **다른 사람 인스턴스 ID**로는 접속되지 않습니다(`AccessDenied`) — 정상입니다.

## 3. 세션 안에서 AlpaSim 실행
> ⚠️ **각 `export`는 반드시 한 줄씩.** `A=1 B=2`처럼 export 없이 쓰거나 붙여넣다 줄이 쪼개지면
> 변수가 스크립트(자식 프로세스)에 전달되지 않아 preflight가 `HF_TOKEN not set`으로 실패하거나
> 결과가 엉뚱한 경로로 갑니다. 아래처럼 `export VAR=값`을 줄마다 쓰세요.
```bash
sudo su -
export PARTICIPANT_ID=<your-id>
export M10_OUTPUT_PREFIX=users/<your-id>/m10
export OUTPUT_BUCKET=av30lab-user-workspace-$ACCOUNT-$REGION
export SHARED_BUCKET=av30lab-shared-data-$ACCOUNT-$REGION
export HF_TOKEN=hf_xxx          # 필수 — 게이트 NuRec 씬 다운로드용 (준비물 3번)

# 전달 확인 (스크립트 돌리기 전 반드시): 5개가 다 보이고 tok_len이 0이 아니어야 함
env | grep -E 'PARTICIPANT_ID|M10_OUTPUT_PREFIX|OUTPUT_BUCKET|SHARED_BUCKET'; echo "tok_len=${#HF_TOKEN}"

# 스크립트 받아서 백그라운드(detached)로 실행 + 로그 실시간 보기
aws s3 cp s3://$SHARED_BUCKET/notebook-templates/scripts/alpasim_ec2_setup.sh /root/
setsid bash /root/alpasim_ec2_setup.sh > /var/log/m7.log 2>&1 &
tail -f /var/log/m7.log
```
- 로그 초반에 `[s3] participant self-run: id=<your-id> output=s3://…/users/<your-id>/m10/`가
  보여야 per-user 경로로 가는 것입니다. `admin reference run`이 보이면 위 env가 전달 안 된 것 —
  Ctrl-C 후 export를 다시 하고 재실행하세요.
- `setsid ... &` 로 띄우면 SSM 세션이 끊겨도 계속 돕니다. `tail -f`는 Ctrl-C로 빠져나와도
  실행에는 영향 없습니다(로그만 그만 봄).
- **오래 걸립니다.** 로그가 멈춘 것처럼 보여도 이미지 pull/씬 다운로드 중일 수 있습니다.

## 4. 성공 확인
실행은 수십 분 걸린다. **`tail -f`가 더 이상 갱신되지 않으면 끝난 것** — 성공(완료)인지
실패(중단)인지는 로그 **마지막 부분**(`tail -n 40 /var/log/m7.log`)으로 가른다.

**✅ 성공**: 로그 끝에 완료 마커가 있다.
```
runtime-0-1 exited with code 0
[verify] core outputs present.
=== DONE — genuine AlpaSim results uploaded to s3://av30lab-user-workspace-.../users/<id>/m10/ ===
>>> Participant <id>: results are in ...
```
- 성공 시 `tail -f`가 멈추는 건 **정상**(스크립트가 끝난 것 — 죽은 게 아니다).
- 완료 직후 `renderer/physics/controller` 컨테이너가 `exited with code 143`(또는 `137`)로
  찍히는 것도 **정상**이다(주 컨테이너가 0으로 끝난 뒤 나머지를 정리). `runtime-0-1 exited
  with code 0` + `=== DONE ===`가 있으면 성공.

**❌ 실패/중단**: `=== DONE`가 **없고** 대신 로그 끝이 `ERROR:` / `RuntimeError` /
`CUDA out of memory` / `HF_TOKEN not set` 이거나, 중간에서 뚝 끊겼다 → 아래 **문제 해결** 표
참조. (SSM 세션이 끊겨도 setsid 실행은 안 죽으니, 재접속해 `tail -f /var/log/m7.log`로 다시 붙으면 된다.)

빠른 판정:
```bash
grep -q "=== DONE" /var/log/m7.log && echo "성공 (S3 업로드 완료)" \
  || echo "미완 — tail -n 40 /var/log/m7.log 에서 ERROR/RuntimeError/끊긴 지점 확인 → 문제 해결 표"
```

직접 확인(세션 안 또는 로컬에서):
```bash
# 새 로컬 셸이면 ACCOUNT 다시 도출 (§3 세션 안이면 이미 export돼 있음)
ACCOUNT=${ACCOUNT:-$(aws sts get-caller-identity --query Account --output text)}
aws s3 ls s3://av30lab-user-workspace-$ACCOUNT-$REGION/users/<your-id>/m10/ --recursive
# aggregate/results-summary.json, rollouts/**/metrics.parquet, eval/eval.mp4, run.json 이 보이면 OK
```

## 5. ⚠️ admin에게 완료 통보 → admin이 서버 종료
당신은 인스턴스를 끌 권한이 없습니다(비용 사고 방지). **"m7-<id> 완료"** 를 admin에게 알리세요.
admin이 확인 후 `terminate-instances`로 종료하고 과금을 멈춥니다.

## 6. SageMaker 노트북에서 내 결과 시각화 (CPU)
1. 참가자 대시보드 → **M10 노드**(인스턴스는 `ml.t3.medium` CPU 그대로) → **Open Workspace**
2. `M10_AlpaSim_ClosedLoop.ipynb` 열고 **Run All**
3. 노트북이 `users/<your-id>/m10/`를 자동 감지해 **당신의** 결과를 시각화합니다
   (cell-2가 `Result source: your own EC2 run` 출력). 없으면 admin 공유 참조로 폴백.

**통과 기준**: cell-5에 driving score(collision_at_fault 등), cell-9에 **PASS** + headline.

---

## 문제 해결
| 증상 | 원인 / 조치 |
|---|---|
| `aws sts get-caller-identity` 실패 | 키 오타/만료 → admin에게 재발급 요청 |
| `start-session` → AccessDenied | 인스턴스 ID가 당신 것이 아님 → admin에게 올바른 ID 확인 |
| `SessionManagerPlugin not found` | 위 링크로 플러그인 설치 |
| 로그에 `CUDA out of memory` | admin에게 알림(토폴로지 조정 필요) |
| 로그에 `HF_TOKEN not set` / preflight 실패 | 3단계 `export HF_TOKEN=hf_…`을 안 했거나 export가 안 됨 → `echo tok_len=${#HF_TOKEN}`로 확인 후 재실행(준비물 3번) |
| 로그에 `401` / `GatedRepoError` (NuRec) | HF 토큰이 NuRec 데이터셋 라이선스 미동의 → 준비물 3번 링크에서 "Agree and access" 후 재실행 |
| 로그가 `admin reference run`으로 시작 | env가 스크립트에 전달 안 됨(export 누락/줄 쪼개짐) → 3단계 env 다시 export 후 재실행 |
| 노트북 cell-4 `not found` | 3~4단계가 아직 성공 안 함 → 로그 확인 후 재실행 |
| 다 됐는데 서버가 안 꺼짐 | admin만 종료 가능 → admin에게 통보 |

관리자용 프로비저닝·IAM·정리 절차: [M10_MANUAL_TEST_RUNBOOK.md](M10_MANUAL_TEST_RUNBOOK.md).
