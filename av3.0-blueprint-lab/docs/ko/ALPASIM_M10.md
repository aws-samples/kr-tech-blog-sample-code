# AlpaSim (M10) — EC2에서 호스팅되는 실제 폐루프 평가

**상태:** M10은 실제 **AlpaSim** 시뮬레이터([NVlabs/alpasim](https://github.com/NVlabs/alpasim),
Apache-2.0)로 Alpamayo 1.5 정책을 <strong>폐루프(closed-loop)</strong>로 평가합니다.
M5/M6/M9와 달리 AlpaSim은 **SageMaker Studio 노트북 내에서 실행될 수
없습니다** — ≥40 GB GPU가 필요한 gRPC 마이크로서비스의 Docker-Compose
플릿이기 때문입니다. 따라서 실제 시뮬레이션은 **GPU EC2 호스트**에서 실행되고,
M10 노트북(CPU)은 그것이 생성한 진짜 결과를 다운로드하여 시각화합니다.

**두 가지 모드(노트북이 자동 감지하며, 본인의 실행을 우선):**
1. **참가자 자체 실행** — 각 참가자는 관리자가 미리 프로비저닝한 GPU
   호스트에서 AlpaSim을 실행하며, **SSM**을 통해 접근하여 자신의
   `s3://<user-workspace>/users/<id>/m10/`에 씁니다. 진짜 "내가 직접 운전했다"
   경험이지만, **~$10.5/hr/host**, ≤16개 동시 실행(G-vCPU 할당량), 첫 빌드는
   수십 분에서 ~2–3시간. 참가자 가이드: `M10_PARTICIPANT_SSM_RUNBOOK.md`; 관리자
   프로비저닝 + IAM: `M10_MANUAL_TEST_RUNBOOK.md` Part C.
2. **관리자 레퍼런스 실행** — 관리자가 AlpaSim을 한 번 실행하여
   `s3://<shared>/m10-reference/`에 업로드하고; 모든 참가자가 **사용자당 GPU 비용
   $0**로 그 동일한 진짜 평가를 검사합니다. 참가자가 자신의 실행이 없을 때
   노트북의 폴백입니다.

둘 다 동일한 아티팩트 레이아웃을 씁니다; 동일한
`scripts/alpasim_ec2_setup.sh`가 둘 다를 지원합니다(출력 경로는
`PARTICIPANT_ID`/`M10_OUTPUT_PREFIX`/`OUTPUT_BUCKET` 환경변수로 선택 — 미설정 ⇒
레거시 관리자 `m10-reference/`).

## 이 모듈이 가지고 있던 핵심 문제

배포된 노트북은 **환각된 `alpasim` 패키지**(`import alpasim`,
`alpasim.env.NuRecEnvironment`, `alpasim.policy.PolicyWrapper.from_alpamayo`,
`alpasim.metrics.{CollisionMetric,RouteCompletionMetric,ComfortMetric,MetricAggregator}`)와
날조된 메트릭(`route_completion`, `comfort_score`)이 있는 조작된 gym 스타일
`env.reset()/env.step()` 루프를 임포트했습니다. 그중 어느 것도 존재하지
않습니다 — M5/M6의 가짜 `cosmos1` 및 M9의 가짜 `alpamayo`와 동일한 부류의
버그입니다. `pip install alpasim`은 존재하지 않습니다. 실제 인터페이스는
Docker Compose를 구동하는 **`alpasim_wizard` Hydra CLI**이며, 실제 메트릭은
`collision_at_fault`, `collision_rear`, `dist_to_gt_trajectory`, `offroad`입니다.

## M10이 노트북에서 실행될 수 없는 이유(그리고 M5/M6/M9는 가능했던 이유)

M5/M6/M9는 SageMaker Studio JupyterLab 앱이 **Docker 데몬이 없는 관리형
컨테이너**이기 때문에 정확히 그 이유로 인-프로세스 `uv` venv로 재구축되었습니다.
AlpaSim의 실행 모델은 근본적으로 다릅니다:

- 이는 **마이크로서비스** 세트입니다 — `renderer`(NuRec/NRE), `driver`(Alpamayo
  정책), `physics`, `runtime`, `controller` — 각각 **컨테이너**이며, gRPC로
  연결되고 **Docker Compose**로 구동됩니다(`run_method: DOCKER_COMPOSE`).
  `deploy=local`도 여전히 *로컬 컨테이너*를 의미하지, 컨테이너 없는 실행이
  아닙니다. 순수 Python 모드는 없습니다.
- **Alpamayo 1.5 driver는 ~40 GB VRAM이 필요**하며(CFG-nav 사용 시 ≥60 GB),
  NuRec renderer는 자체 VRAM과 함께 공존합니다.

노트북 셀은 `docker compose up`을 할 수 없으므로, M10은 다른 곳에서 실행됩니다.

## 우리가 사용하는 아키텍처: 관리자 실행 레퍼런스 평가

1. **관리자, 한 번, GPU EC2 호스트에서**(`scripts/alpasim_ec2_setup.sh`): 공유
   HF 캐시 복원(Alpamayo-1.5-10B + Cosmos-Reason2-8B, 이미 M9가 스테이징함),
   AlpaSim 클론, `source setup_local_env.sh`, `docker login nvcr.io`, 위저드
   실행, 그리고 진짜 출력을 `s3://<shared>/m10-reference/`에 업로드.
2. **참가자, M10 노트북에서(CPU `ml.t3.medium`)**: 레퍼런스 결과를 `aws s3 sync`하고
   실제 `metrics_results.txt` 테이블, 롤아웃별 `metrics.parquet`
   (`collision_at_fault`/`collision_rear`/`offroad`의 막대,
   `dist_to_gt_trajectory`의 히스토그램), AlpaSim 자체의
   `metrics_results.png`, 그리고 실제 평가 비디오를 시각화합니다.

이는 M9가 실행하는 바로 그 모델의 **진짜** 폐루프 평가입니다 — 시뮬레이션된
숫자가 아닙니다. 사용자별 시뮬레이션이 아니라 관리자 레퍼런스 실행으로 모든
곳에서 정직하게 표현됩니다.

## 정직한 M9 → M10 연결

AlpaSim은 M9의 예측 궤적 `.npy`를 **소비하지 않습니다**. 그것은 M9와 **동일한
`nvidia/Alpamayo-1.5-10B` 체크포인트**(공유 hf-cache에서)를 `driver=alpamayo1_5`
플러그인으로 로드하여 폐루프로 구동합니다. 따라서:

- **M9** = Alpamayo 모델이 궤적을 <strong>개루프(open-loop)</strong>로 예측(minADE).
- **M10** = **동일한 모델**이 AlpaSim에서 **폐루프**로 구동(안전 메트릭).

공유되는 아티팩트는 궤적 파일이 아니라 체크포인트입니다. 노트북은 이 출처를
표시하기 위해서만 M9의 `manifest.json`을 읽습니다.

## 인스턴스 & GPU 배치(리포지토리의 토폴로지 구성에서)

AlpaSim의 `topology` 구성은 서비스를 GPU에 고정합니다(`src/wizard/configs/topology/`):

| 토폴로지 | driver | renderer | physics | 실행 가능 대상 |
|---|---|---|---|---|
| `1gpu` | GPU 0 | GPU 0 | GPU 0 | **≥80 GB** 카드 하나(A100 80GB / H100) — driver ~40 GB + 공존 renderer |
| `2gpu` | GPU 0 (×3 replica) | GPU 1 | GPU 0+1 | **≥40 GB 카드 두 개** → **L40S 48 GB ×2 = g6e.12xlarge** |

24 GB 카드(A10G/L4)는 어느 토폴로지에서도 40 GB driver에 **맞지 않습니다** —
그리고 AlpaSim은 우리가 제어하지 않는 컨테이너로 driver를 실행하므로, M9의
`balanced-expert` 다중 24 GB 카드 트릭은 여기에 적용되지 않습니다.

> ### ⚠️ M10은 **≥2 GPU**가 필요합니다 — 그리고 인스턴스 이름의 숫자는 GPU 개수가 아닙니다
> `topology=2gpu`(기본값)는 renderer를 **GPU 1**에 배치하므로, 호스트는
> **최소 2개의 GPU**를 노출해야 합니다. g6e 패밀리에서 **더 큰 vCPU 크기가 더
> 많은 GPU를 의미하지 않습니다** — 세 개의 크기만 여러 GPU를 가집니다.
> "12xlarge보다 커 보인다"는 이유로 `g6e.16xlarge`를 고르면 **GPU 1개**를 얻고
> 실행이 시작 시 `Service renderer requested GPUs [1] but only 0 .. 0 are available`로
> 죽습니다.
>
> | g6e 크기 | GPU | vCPU | M10(2gpu)에 적합? |
> |---|---|---|---|
> | g6e.xlarge / 2xlarge / 4xlarge / 8xlarge | **1** | 4–32 | ❌ 단일 GPU |
> | **g6e.12xlarge** | **4** | 48 | ✅ **권장** |
> | g6e.16xlarge | **1** | 64 | ❌ 단일 GPU(더 큰 박스인데 여전히 GPU 1개!) |
> | g6e.24xlarge | **4** | 96 | ✅ (M10에는 과함) |
> | g6e.48xlarge | **8** | 192 | ✅ (과함) |
>
> 경험 법칙: **멀티 GPU g6e = 12xlarge(4), 24xlarge(4), 48xlarge(8)**. 그
> 외의 모든 크기 — 16xlarge 포함 — 는 **단일 GPU** 박스입니다. 실행 전에
> 확인하세요: `nvidia-smi --query-gpu=index,name,memory.total --format=csv`가
> **≥2**개 행을 나열해야 합니다.

- **권장(비용 최적): `g6e.12xlarge`(4× L40S 48 GB) + `topology=2gpu`**,
  온디맨드 ~$10.5/hr(레퍼런스 배포 예시 리전: us-west-2; 가격은 리전별로 다름).
- **안전한 폴백:** `p4de.24xlarge` / `p5.48xlarge`(80 GB 카드) + `topology=1gpu`
  (1gpu에는 단일 ≥80 GB 카드로 충분; 2gpu는 여전히 카드 두 개 필요).
- CFG-nav는 **꺼진** 상태(기본값)로 유지되어 driver가 ~40 GB에 맞습니다.

## 게이트된 종속성

- **HF:** `nvidia/Alpamayo-1.5-10B` + `nvidia/Cosmos-Reason2-8B`(공유 hf-cache에서
  오프라인 로드)와 **`nvidia/PhysicalAI-Autonomous-Vehicles-NuRec`** 데이터셋.
  ⚠️ **NuRec은 런타임에 다운로드되며 공유 오프라인 캐시에 없습니다**(모델과
  달리) — 따라서 `HF_TOKEN`은 `alpasim_ec2_setup.sh`의 **강한 요구사항**입니다
  (그렇지 않으면 프리플라이트가 `HF_TOKEN not set`으로 실패), 그리고 토큰의
  계정은 NuRec 라이선스를 수락한 상태여야 합니다(그렇지 않으면 `GatedRepoError`).
  **관리자 레퍼런스** 모드에서는 관리자가 자신의 토큰을 제공합니다; **참가자
  자체 실행** 모드에서는 **각 참가자가 자신의 토큰을 제공합니다** — 이것은
  "참가자에게 HF 토큰이 필요 없다"는 규칙이 성립하지 않는 유일한 지점입니다
  (`PREREQUISITES.md`와 `M10_PARTICIPANT_SSM_RUNBOOK.md` 참조).
- **NGC:** renderer 이미지 `nvcr.io/nvidia/nre/nre-ga:26.04`는 NGC에서
  풀합니다. NGC API 키(`https://org.ngc.nvidia.com/setup/api-key`)와 그 이미지에
  대한 접근 권한이 필요합니다. 이것은 **M10의 강한 게이트**입니다 —
  `alpasim_ec2_setup.sh`는 긴 빌드 전에 `docker manifest inspect`로 이를
  검증합니다.

## 관리자 일회성 시퀀스

Docker 지원 GPU 호스트(AWS **Deep Learning Base GPU AMI** — Docker + NVIDIA
Container Toolkit + driver ≥570 탑재)를 **인터넷 이그레스가 있는 퍼블릭
서브넷**에서 실행하고(랩 VPC는 격리되어 있음; 기본 VPC 사용), 그다음:

```bash
export HF_TOKEN=hf_xxx            # Alpamayo + Cosmos-Reason2 + NuRec accepted
export NGC_API_KEY=nvapi-xxx      # NGC access to nre-ga
# SHARED_BUCKET is deliberately NOT exported: the script derives
# av30lab-shared-data-<acct>-<region> from STS + IMDS and exits 1 if it cannot.
bash scripts/alpasim_ec2_setup.sh
# verify the m10-reference/ upload, then TERMINATE the instance.
```

스크립트: 프리플라이트(nvidia-smi / docker / NVIDIA runtime / uv / cargo) →
`$HF_HOME`으로 `hf-cache/hub` 복원 → AlpaSim 클론(고정됨) → NGC 로그인 +
`docker manifest inspect` 게이트 → `source setup_local_env.sh` →
`uv run alpasim_wizard deploy=local topology=2gpu driver=alpamayo1_5
scenes.scene_ids="['clipgt-01d503d4-449b-46fc-8d78-9085e70d3554']"
wizard.log_dir=$PWD/out eval.video.video_layouts=[REASONING_OVERLAY]` →
`aggregate/metrics_results.txt`, `rollouts/**/metrics.parquet`, 평가 `.mp4` 검증
→ `s3://<shared>/m10-reference/`에 업로드(`aggregate/`, `rollouts/`, `eval/eval.mp4`,
`run.json`).

레퍼런스 번들은 **공유** 버킷의 `hf-cache/`-형제 프리픽스 `m10-reference/` 아래에
작성됩니다: EC2 호스트의 관리자 자격 증명이 이를 씁니다; 참가자는 공유 버킷
전체를 읽습니다. (비용: g6e.12xlarge에서 ~$30 일회성; 참가자당 $0.)

## 실제 출력 아티팩트(노트북이 시각화하는 것)

- `aggregate/metrics_results.txt` — 형식화된 주행 점수 테이블(평균/표준편차/분위수).
- `aggregate/metrics_results.png` — AlpaSim의 시각적 요약.
- `rollouts/{scene}/{batch}/metrics.parquet` — 롤아웃별 메트릭
  (`collision_at_fault`, `collision_rear`, `dist_to_gt_trajectory`, `offroad`, …).
- `eval/eval.mp4` — Chain-of-Causation 오버레이가 있는 폐루프 롤아웃.
- `run.json` — 출처(driver, scene, topology, renderer 이미지, 인스턴스).

## 검증된 실행(2026-07-12, 레퍼런스 배포 예시 계정 <aws-account-id>)

**g6e.12xlarge**(4× L40S 46 GB), alpasim **v0.96.0** *(그 태그는 이후 상류에서 사라졌습니다. 현재 핀은 v2026.5이며 **미검증**입니다 — 아래 주석 참고)*, renderer
`nvcr.io/nvidia/nre/nre-ga:26.04`, scene
`clipgt-01d503d4-449b-46fc-8d78-9085e70d3554`, topology `m7_4gpu`(driver가 GPU
0에 단독)에서 `nvidia/Alpamayo-1.5-10B`의 실제 AlpaSim 폐루프 평가. Driver는 S3
hf-cache에서 Alpamayo를 **오프라인**으로 로드함(토큰 없음, 다운로드 없음).
진짜 주행 점수:

| 메트릭 | 값 |
|---|---|
| collision_any / collision_at_fault / collision_rear | 0.00 (충돌 없음) |
| offroad / offroad_or_collision | 0.00 |
| dist_to_gt_trajectory (max) | 4.37 m |
| dist_traveled_m (vs GT 73.77 m) | 78.12 m |
| progress_rel / progress | 0.92 / 1.00 (경로 사실상 완료) |
| min_distance_to_obstacle_m | 1.12 m |
| duration_frac_20s | 0.78 |

출력은 `s3://<shared>/m10-reference/`에 업로드됨(aggregate/, rollouts/,
추론 오버레이가 있는 eval/eval.mp4, run.json). 일회성 비용 ≈ $30(캐시 미스
첫 빌드를 포함한 몇 시간의 g6e.12xlarge).

### 실행을 연결하며 발견한 함정들(scripts/alpasim_ec2_setup.sh에서 수정됨)
- **SSM 셸의 `set -u` 하에서 `$HOME`이 바인딩되지 않음** → 초기에 `HOME=/root`를
  export.
- **`Mount point does not exist: data/drivers`** → 위저드가
  `data/{drivers,nre-artifacts/ego-hoods,trafficsim-models}`를 바인드
  마운트함; 먼저 `mkdir -p`하기.
- **Driver 401 게이트된 리포지토리** → 기본 `driver` 서비스에는 `environments`가
  없으므로 HF에 온라인으로 접근하려 함; `driver.environments` =
  `HF_TOKEN, HF_HOME, HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1`을 설정하는
  `deploy/local_m7.yaml`을 추가. (M9와 동일한 오프라인 캐시 교훈.)
- **CUDA OOM** → 기본 `topology=2gpu`는 GPU 0에 **세 개**의 driver 복제본을
  놓음; 세 개의 40 GB Alpamayo 복사본은 L40S에 맞지 않음. driver에게 GPU 0을
  단독으로 주는 커스텀 `topology=m7_4gpu`(renderer GPU 1, physics GPU 2,
  trafficsim GPU 3), 복제본 하나, 롤아웃 하나를 사용.

## 라이선스

Alpamayo-1.5-10B 가중치는 **비상업용**입니다(연구/평가 전용). AlpaSim 코드는
Apache-2.0입니다. NuRec 장면은 NVIDIA AV NuRec Dataset License 하에 있습니다.
M10 노트북은 이 고지를 표시합니다.

---

### 핀된 alpasim 태그 (워크숍 전에 읽으세요)

`scripts/alpasim_ec2_setup.sh`가 `ALPASIM_TAG`를 핀합니다(기본 `v2026.5`). 위에 기록된
실측 실행은 `alpasim-base-v0.96.0`을 썼는데 그 태그는 **이제 존재하지 않습니다** —
`git ls-remote --tags https://github.com/NVlabs/alpasim`은 `v2026.4`와 `v2026.5`만
반환합니다. 스크립트는 예전에 태그 미스 시 조용히 기본 브랜치로 떨어졌고, 그래서 실행이
움직이는 `main`을 쓸 수 있었습니다. 지금은 **크게 실패하고** 사용 가능한 태그를 출력합니다.

`v2026.5`에 대해 확인된 것: 이 스크립트가 건드리는 모든 상류 경로가 존재하고
(`deploy/local.yaml`, `driver/alpamayo1_5.yaml`, 6개 항목의 `topology/`,
`data/scenes/sim_scenes.csv`), 핀된 `SCENE_ID`가 916개 씬 CSV에 정확히 1회 나옵니다.
`main`은 그 씬을 2회 나열합니다.

**확인되지 않은 것**: `v2026.5`에서 M10을 실행한 기록이 없습니다. 행사 전에 관리자 EC2
호스트에서 한 번 돌리세요. 실패하면 `ALPASIM_TAG=v2026.4`(910개 씬, 핀된 씬 포함)를
시도하고, 기본 브랜치로 되돌리지는 마세요.
