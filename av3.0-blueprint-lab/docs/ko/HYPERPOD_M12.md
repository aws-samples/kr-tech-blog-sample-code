# HyperPod (M12) — 실제 분산 학습 데모, 설계상 CPU

**상태:** M12는 **M3의 큐레이션된 캡션**에 대해 **실제 분산 PyTorch DDP 학습
작업**(SageMaker Training Job, `instance_count=2`)을 실행하고, 작업 자체의
아티팩트에서 **측정된** 에폭별 손실과 처리량을 시각화합니다. 시뮬레이션되는
것은 없습니다. 이는 HyperPod 클러스터가 **아닙니다** — 그것은 노트북이
프로비저닝할 수 없는 별도의 인프라입니다(아래 참조). M12는 HyperPod이 확장하는
*분산 학습 패턴*을 저렴한 CPU 인스턴스에서 시연합니다.

## M12가 무엇이었고, 이제 무엇인가

배포된 M12는 M5/M6/M9/M10처럼 **환각된 API 실패가 아니었습니다** — 모든 임포트와
AWS 호출이 실제였습니다(`sagemaker.pytorch.PyTorch`, `torch.distributed`,
`describe_training_job`). 그것의 문제는 달랐습니다:

| 배포된 M12 | 수정된 M12 |
|---|---|
| 제목은 "HyperPod"라고 했지만 평범한 SageMaker Training Job을 사용함 | 정직하게 표현됨: 분산 *패턴*, HyperPod = 개념(처음에 명시됨) |
| M3 입력을 선언했지만 결코 읽지 않음(`estimator.fit()`에 `inputs=`가 없음) | `fit(inputs={"training": …})`가 M3의 `curated_captions.json`을 마운트함; 스크립트는 실제 캡션에서 피처를 엔지니어링함 |
| 메트릭이 `np.random` 시뮬레이션이었음 | 작업의 실제 `training_log.json`에서 손실/처리량을 파싱함(rank-0이 씀) |
| `backend="nccl"` 하드코딩됨(GPU 필요) | `gloo`(CPU) / `nccl`(GPU)를 자동 선택하여 CPU **및** GPU에서 실행됨 |
| `ml.g5.xlarge` × 2 요청함(GPU 할당량 = 1 → 실패했을 것) | `ml.m5.xlarge` × 2(CPU 학습 할당량 이용 가능) |
| 비용이 하드코딩된 상수였음 | `BillableTimeInSeconds`에서 실제 데모 비용; HyperPod 비용은 명확히 "개념적"으로 표시됨 |

## 왜 CPU인가(그리고 왜 그것이 올바른 선택인가)

데모 모델은 작은 MLP(`QualityPredictor`, 8개의 엔지니어링된 피처)입니다.
교육 요점은 GPU 처리량이 아니라 **진짜 멀티 노드 `torch.distributed`
all-reduce**입니다 — 작은 모델은 GPU의 이점을 보여줄 수 없습니다. 따라서:

- **`ml.m5.xlarge` × 2, `gloo` 백엔드** — 실제 2-rank DDP:
  `init_process_group`, `DistributedSampler` 샤딩, `DDP` 그래디언트 all-reduce,
  rank-0 체크포인트. 그 모든 것이 실제로, 몇 푼으로 일어납니다.
- CPU 학습 할당량은 기본적으로 이용 가능합니다; 데모는 GPU가 필요 없습니다.

## CPU 대 GPU 트레이드오프(향후 GPU 실행을 위해)

**동일한 학습 스크립트**가 변경 없이 GPU/`nccl`로 실행됩니다 —
`torch.cuda.is_available()`를 감지하고 백엔드 + 디바이스를 선택합니다. GPU에서
M12를 실행하려면:

1. **GPU 학습 할당량을 올리세요.** 2026-07 사전 테스트 기준, 레퍼런스 랩
   계정에서(`us-west-2`; 여러분의 리전은 다를 수 있음 — 본인 할당량을 확인하세요):
   - `ml.g5.xlarge for training job usage` = **1**(할당량 코드 `L-B6D80D9C`,
     조정 가능) → 2-노드 작업을 위해 ≥2 요청. 승인은 ~며칠 걸립니다.
   - `ml.m5.xlarge for training job usage` = **30**(오늘 CPU가 작동하는 이유).
2. 노트북에서 `INSTANCE_TYPE = "ml.g5.xlarge"` 설정(cell-4). 다른 변경 없음 —
   스크립트가 자동으로 `nccl`과 `cuda`로 전환합니다.

| | CPU (`ml.m5.xlarge` × 2) | GPU (`ml.g5.xlarge` × 2) |
|---|---|---|
| 백엔드 | `gloo` | `nccl`(프로덕션 컬렉티브) |
| 할당량 (레퍼런스 배포 예시: us-west-2, 2026-07) | 30 — 지금 이용 가능 | 1 — 상향 필요(~며칠) |
| 비용 | ~$0.23/hr × 2 | ~$1.41/hr × 2 |
| DDP all-reduce 검증됨 | ✅ (gloo) | ✅ (nccl) |
| 데모 모델이 GPU로부터 이득 | 아니오(작은 MLP) | 아니오(작은 MLP) |

**결론:** 둘 다 "2개 노드가 실제로 분산 학습했다"를 증명합니다. GPU는 실제
`nccl` 경로만 추가합니다; 작은 모델은 어느 쪽으로도 속도 이점을 보이지
않습니다. CPU는 워크숍을 위한 실용적 선택이고; GPU는 할당량이 상향되면 문서화된
한 줄 전환입니다.

## 왜 실제 HyperPod은 노트북의 범위 밖인가

SageMaker HyperPod은 **영구 클러스터**로, `aws sagemaker create-cluster`(Slurm
또는 EKS 오케스트레이션)에 VPC/서브넷/보안 그룹, 공유 스토리지용 FSx for Lustre,
그리고 EFA 네트워킹을 더해 생성됩니다. 클러스터 생성만 해도 ~20분이 걸리고
클러스터는 그다음 계속 과금됩니다 — 이것은 노트북 셀이 아니라 장기 실행,
대규모 학습 인프라입니다. (개념적으로 M10의 AlpaSim이 노트북 밖의 GPU EC2
호스트에서 실행되는 것과 같은 이유입니다.) 또한 `ml.p4d.24xlarge for cluster
usage`와 `... for training job usage`가 이 랩 계정에서 둘 다 **0**이므로,
실제 HyperPod p4d 클러스터는 어차피 여기서 생성될 수 없습니다. 따라서 M12는
프로비저닝하는 대신 HyperPod이 확장하는 패턴을 가르치고 HyperPod의 부가 가치
(자동 노드 교체, FSx, Slurm/EKS 스케줄링, EFA/NCCL)를 설명합니다.

## 출력 아티팩트

- `users/<profile>/m12/training_metadata.json` — 작업 요약, 데이터 소스
  (`real_m3` | `synthetic`), 측정된 에폭별 메트릭, HyperPod 노트.
- `users/<profile>/m12/<job-name>/output/model.tar.gz` — 체크포인트 +
  `training_log.json`(노트북이 플롯하는 실제 메트릭).
- `users/<profile>/m12/input/curated_captions.json` — 학습 채널로 스테이징된
  M3 데이터(M3가 실행되었을 때만).

## 검증된 실행

**로컬 드라이런(2026-07-13, $0)** — 정확히 임베드된 `train_distributed.py`를,
M3의 실제 `curated_captions.json`(`ky-5-34x1bx`, 12개 캡션)에 대해 실제
2-프로세스 gloo DDP 작업(`torchrun --nproc_per_node=2`)으로 실행함:

```
Backend: gloo | world_size: 2 | nodes: 2
Dataset: REAL M3 captions | samples: 12 | feature_dim: 8
Epoch 1/5 | Loss: 0.134977 ...
Epoch 5/5 | Loss: 0.000053 | Throughput: 7 samples/s
Checkpoint + training_log.json saved
```

이는 중요한 부분들을 확인합니다: 진짜 2-rank `torch.distributed` 초기화 +
all-reduce(gloo), 실제 M3 캡션 수집(`dataset: real_m3`), 키가 노트북의 cell-6
파서와 일치하는 실제 에폭별 `training_log.json`, 그리고 로드 가능한 체크포인트
(`model_state_dict` + `optimizer_state_dict` + `final_loss`). 손실이
0.135 → 5.3e-5로 떨어짐 — 측정된 것이지 시뮬레이션이 아님.

**관리형 실행 검증됨(2026-07-14, Studio Run-All, 참가자 프로필 ky-5-34x1bx):**
**`ml.m5.xlarge`×2**에서 `estimator.fit()`이 완료됨 — `Training job completed`,
320 청구 초, **`Data source: real_m3`**(`training` 채널을 통해 M3의 큐레이션된
캡션으로 학습됨), 모델 아티팩트는
`users/ky-5-34x1bx/m12/.../output/model.tar.gz`에, 데모 비용 ~$0.02. 전체
M3→M12→메트릭 파이프라인이 실제 Studio 환경에서 엔드투엔드로 확인됨.

### 참가자 Run-All이 드러낸 여섯 개의 실제 버그(로컬에서는 재현 불가)
Studio 커널 + 관리형 학습 작업은 로컬 드라이런이 결코 마주칠 수 없는 일련의
문제를 노출했습니다:
1. **SDK v3 커널** — SageMaker Distribution은 Python SDK v3를 제공함(모듈식
   `sagemaker.core`/`sagemaker.train`, 최상위 `Session`이나
   `sagemaker.pytorch.PyTorch` 없음). 수정: cell-1이 v2를 고정함
   (`sagemaker>=2.257.2,<3`).
2. **v2/v3 인메모리 혼합** — pip이 파일을 교체하지만 커널은 v3를 임포트한 채로
   유지함(`cannot import name ModelMetrics`). 수정: cell-1이 v2 설치 후 커널을
   자동 재시작함(재시작 후 cell-1을 한 번 재실행).
3. SDK에서 **`torch_distributed`는 GPU/Trainium 전용**임 — CPU에서 거부됨
   (`ValueError: ... only for GPU and Trainium`). 수정: `distribution={"mpi":
   {"processes_per_host": 1}}` 사용.
4. **실행 역할 쓰기 범위가 `users/*`임** — estimator의 기본 코드 업로드가 버킷
   루트 `<job>/source/...`로 가는데 거부됨. 수정: `code_location=
   s3://<bucket>/users/<profile>/m12/code`.
5. **`iam:PassRole` + `sagemaker:CreateTrainingJob` 누락** — 실행 역할이 학습
   작업 제출이 아니라 Studio 앱 관리를 위해 만들어졌음. 수정:
   `infra/av30_constructs/sagemaker.py`에 범위가 지정된 `SageMakerTrainingJobs`
   (av30-m12-* ARN) + 자신 전용 `PassRole`
   (`iam:PassedToService=sagemaker.amazonaws.com`) 구문을 추가하고 배포함.
6. **MPI rank 순서 ≠ SM_HOSTS 순서 → 랑데부 행(hang).** 첫 CPU 시도는
   `SM_HOSTS`(정렬됨)에서 rank/master를 도출했지만, MPI의 rank-0 호스트는
   `algo-2`인 반면 `SM_HOSTS[0]`는 `algo-1`이어서 `dist.init_process_group`이
   "Waiting for orted process"에서 영원히 멈춤. 수정: **mpi4py**
   (`MPI.COMM_WORLD`)에서 rank/world_size를 읽고 rank-0 자신의 호스트명을
   `MASTER_ADDR`로 브로드캐스트함.

**GPU 참고는 여전히 적용됨:** `ml.g5.xlarge`에서는 distribution을
`torch_distributed`(torchrun)로 다시 전환하면 스크립트가 nccl을 자동
선택합니다; 위의 mpi4py 랑데부는 CPU 경로입니다.
