# Alpamayo 1.5 (M9) — SMD 이미지에서의 실제 VLA 추론

**상태:** M9(Alpamayo 1.5, Vision-Language-Action 궤적 예측)는 SageMaker
Distribution(SMD) GPU 이미지에서 **엔드투엔드로 검증**되었습니다 —
`PhysicalAI-Autonomous-Vehicles` 데모 클립에 대한 실제 추론으로
Chain-of-Causation 설명과 예측된 ego 궤적을 생성합니다(검증된 클립에서
**minADE 0.375 m**). M5/M6와 마찬가지로 오프라인 S3 체크포인트 캐시와
사전 저장된 데모 클립을 통해 **참가자 HF 토큰 없이** 실행됩니다.

## 이 모듈이 가지고 있던 핵심 문제

배포된 노트북은 **존재하지 않는** **환각된 `alpamayo` 패키지**
(`from alpamayo.model import AlpamayoForConditionalGeneration`,
`alpamayo.inference.AlpamayoInferencePipeline`, `alpamayo.utils.load_frames_from_video`,
`pipeline.predict_trajectory` / `predict_trajectory_multicam` / `visual_qa`)를
임포트했습니다 — M5/M6의 가짜 `cosmos1`과 동일한 부류의 버그입니다.
`pip install alpamayo`는 존재하지 않습니다. 실제 워크플로우는 공식 리포지토리
[`NVlabs/alpamayo1.5`](https://github.com/NVlabs/alpamayo1.5), 패키지
`alpamayo1_5`(언더스코어)입니다.

M5/M6와 달리 Alpamayo는 **다른 스택**입니다: Python **3.12**(Cosmos는
3.10에 고정), torch 2.8, transformers 4.57.1, `physical-ai-av==0.2.0`,
**transformer-engine 없음**, 그리고 **flash-attn 제외**(SMD 이미지에서 소스
빌드가 실패함). 따라서 자체 venv와 자체 설정 경로를 가집니다.

## 실제 추론 흐름(검증됨)

```python
import torch, numpy as np
from alpamayo1_5 import helper
from alpamayo1_5.load_physical_aiavdataset import load_physical_aiavdataset  # admin only
from alpamayo1_5.models.alpamayo1_5 import Alpamayo1_5

data = load_physical_aiavdataset("030c760c-...", t0_us=5_100_000)   # gated dataset, online
messages = helper.create_message(frames=data["image_frames"].flatten(0, 1),
                                 camera_indices=data["camera_indices"])
model = Alpamayo1_5.from_pretrained("nvidia/Alpamayo-1.5-10B",
                                    dtype=torch.bfloat16,
                                    attn_implementation="sdpa").to("cuda")   # sdpa REQUIRED
processor = helper.get_processor(model.tokenizer)
inputs = processor.apply_chat_template(messages, tokenize=True,
    add_generation_prompt=False, continue_final_message=True,
    return_dict=True, return_tensors="pt")
mi = helper.to_device({"tokenized_data": inputs,
                       "ego_history_xyz": data["ego_history_xyz"],
                       "ego_history_rot": data["ego_history_rot"]}, "cuda")
pred_xyz, _, extra = model.sample_trajectories_from_data_with_vlm_rollout(
    data=mi, top_p=0.98, temperature=0.6, num_traj_samples=1,
    max_generation_length=256, return_extra=True)
# extra["cot"][0] = Chain-of-Causation reasoning; pred_xyz = trajectory;
# minADE vs data["ego_future_xyz"].
```

`attn_implementation="sdpa"`는 **필수**입니다: 리포지토리 기본값은
`flash_attention_2`인데, flash-attn이 설치되어 있지 않아 `ImportError`가
발생합니다.

## 결정적인 두 가지 오프라인 발견

M9는 M5/M6처럼 토큰 없이 실행되어야 하지만, 두 부분이 다르게 동작합니다:

1. **모델은 오프라인으로 로드됩니다 — hf-cache 사용(M5/M6와 동일).** `HF_TOKEN`을
   설정하지 않고 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`이면,
   `Alpamayo1_5.from_pretrained(...)` + `helper.get_processor`가 S3에서 복원된
   HF 캐시에서 **토큰 없이, 네트워크 없이** 로드됩니다 — `from_pretrained`가
   투명하게 가져오는 *숨겨진* VLM 백본 **`nvidia/Cosmos-Reason2-8B`**(Alpamayo의
   Qwen3-VL 베이스)를 포함해서요. 따라서 공유 `hf-cache/hub/` 트리는
   `models--nvidia--Alpamayo-1.5-10B`와
   `models--nvidia--Cosmos-Reason2-8B`를 **둘 다** 포함해야 합니다.

   > 이것이 바로 평면적인 `model-cache/alpamayo-1.5/` 복사본(원시 가중치만)이
   > 런타임에 **사용되지 않는** 이유입니다 — Reason2 백본이 없기 때문입니다.
   > `cache_models.sh`는 더 이상 이를 다운로드하지 않습니다.

2. **데이터는 오프라인으로 로드할 수 없습니다 — 대신 데모 클립을 사전 저장하세요.**
   `load_physical_aiavdataset`는 `PhysicalAIAVDatasetInterface`를 빌드하는데,
   그 `__init__`은 게이트된 `PhysicalAI-Autonomous-Vehicles` 데이터셋
   (`physical_ai_av/utils/hf_interface.py`)에 대해 무조건 `self.api.list_repo_refs()`를
   호출합니다. 이는 `HF_HUB_OFFLINE=1`을 무시하고 오류를 발생시킵니다:
   `OfflineModeIsEnabled: Cannot reach .../datasets/nvidia/PhysicalAI-Autonomous-Vehicles/refs`.
   따라서 **관리자**가 온라인으로 `load_physical_aiavdataset`를 한 번 실행하고
   그 결과 `data` 딕셔너리(~100 MB, 대부분 4-카메라 이미지 프레임)를 S3에
   `torch.save`합니다. **참가자** 노트북은 그 `.pt`를 `torch.load`만 하고
   **`physical_ai_av`를 절대 임포트하지 않습니다** — 토큰 제로, 네트워크 제로.

## `scripts/setup_cosmos_env.sh alpamayo`

Cosmos 설정 스크립트에 `alpamayo` 모드(`bash scripts/setup_cosmos_env.sh
alpamayo`)가 추가되었습니다. 공유 프리앰블(버킷 해석 + `$HF_HOME`으로의
`hf-cache/hub/` 복원)을 재사용하고 전용 `prepare_alpamayo()`를 추가합니다:

- `NVlabs/alpamayo1.5` 클론(Cosmos 리포지토리처럼 LFS 필터 비활성화);
- `uv venv a1_5 --python 3.12` 그다음
  `VIRTUAL_ENV=$venv uv sync --active --no-install-package flash-attn`;
- transformer-engine `.so`-심링크 / `CUDA_HOME` / `ldconfig` 단계 **건너뛰기**
  (Alpamayo에는 TE가 없음 — torch 2.8의 번들 CUDA가 잘 로드됨);
- `alpamayo_env.sh` 작성. 이는 `a1_5` venv를 활성화하고, 소스된 cosmos 환경에서
  누출된 **모든 `CUDA_HOME`/`LD_LIBRARY_PATH`를 지우며**,
  `$HF_HOME/hub/models--nvidia--Alpamayo-*`가 있을 때 `HF_HUB_OFFLINE=1`을 켭니다.

`alpamayo`는 `both`의 일부가 **아닙니다**(`both`는 두 개의 Cosmos 리포지토리임) —
명시적으로 요청하세요.

## `scripts/alpamayo_infer.py`

노트북이 `bash -lc 'source alpamayo_env.sh && python scripts/alpamayo_infer.py
--clips ... --out ...'`를 통해 실행하는 커밋된 스크립트(리포지토리 CLI가 아님 —
실제 흐름은 맞춤형입니다). 모델을 **한 번** 로드하고, 데모 클립을 반복하며,
노트북 커널이 torch 없이 읽을 수 있는 평범한 아티팩트를 씁니다:
`<clip>_pred.npy`, `<clip>_gt.npy`, `<clip>_cot.txt`, 그리고 `metrics.json`
(클립당 minADE). 각 `.pt`를 `weights_only=False`로 로드합니다(torch 2.8은
기본값이 `True`인데, 이는 딕셔너리의 `int`/`str` 항목을 거부합니다).
이 방식은 파일을 unpickle하므로 그 안의 코드가 실행됩니다. 그래서 클립은 관리자 자격
증명으로만 쓸 수 있는 `hf-cache/alpamayo-demo/`에서만 가져와야 합니다
(아래 *관리자 일회성 설정* 참고).

`scripts/alpamayo_save_clip.py`는 그러한 `.pt` 파일을 생성하는 관리자 전용
동반 스크립트입니다(온라인, 토큰 사용).

## M9 노트북 흐름(재작성됨)

`notebooks/M9_Alpamayo_VLA_Inference.ipynb`(11개 셀):

1. **제목** + **라이선스**(비상업용 가중치) 마크다운.
2. **Config** — 프로필/버킷, NVMe 작업 디렉터리, `DEMO_CLIPS`, `HF_TOKEN`(선택).
3. **GPU 확인** — **디바이스당** 최대 ≥ 40 GB(모델은 `.to("cuda")`를 통해 단일
   디바이스에 로드되므로, GPU 전체 합계는 오해의 소지가 있습니다).
4. **Setup** — `setup_cosmos_env.sh alpamayo` 실행(멱등적).
5. **Input** — `hf-cache/alpamayo-demo/`에서 데모 `.pt`(들) 다운로드 +
   `alpamayo_infer.py` 찾기.
6. **Inference** — `a1_5` venv로 `bash -lc`, `alpamayo_infer.py` 실행.
7. **Visualize** — 예측 궤적 대 정답(ground-truth) 궤적 + 추론 내용 출력.
8. **Upload** — 출력 → `users/{profile}/m9/`; 매니페스트는 M10이 읽는 키
   (`model` / `modes_run` / `timestamp` / `results`)를 유지합니다.
9. **비용.**
10. **검증 + 인라인 미리보기 + 다음 모듈(M10).**

워크숍 실행 비용을 낮게 유지하기 위해 기본값은 `DEMO_CLIPS = ["030c760c-..."]`
(클립 하나)입니다; 모두 실행하려면 스테이징된 다른 클립의 주석을 해제하세요.

## 관리자 일회성 설정

참가자가 M9을 실행하기 전에 공유 버킷에 두 가지가 있어야 합니다. `hf-cache/hub/` 아래의 Alpamayo
가중치와 `Cosmos-Reason2-8B` 백본, 그리고 `hf-cache/alpamayo-demo/` 아래의 데모 클립입니다.
**둘 다 관리자 워크스테이션에서 관리자 자격 증명으로 올리고, Studio 앱에서는 절대 올리지 않습니다.**
모든 참가자가 함께 쓰는 실행 역할은 의도적으로 공유 버킷에 전혀 쓸 수 없습니다. 모든 M9 커널이
데모 클립을 unpickle하므로, 클립을 바꿔치기할 수 있는 참가자는 다른 모든 참가자의 권한으로 코드를
실행할 수 있기 때문입니다([ADMIN_GUIDE.md](ADMIN_GUIDE.md) §6.3).

**가중치.** 첫 리전은 `scripts/cache_hf_tree.sh`, 그 뒤의 리전은 버킷 간 복사로 채웁니다(README
step 6b). 고정된 매니페스트(`scripts/hf_cache_manifest.tsv`)에는 `nvidia/Alpamayo-1.5-10B`와
`nvidia/Cosmos-Reason2-8B`가 들어 있습니다. 매니페스트에는 두 저장소의 `.no_exist` 마커도 기록되어
있어야 합니다. 온라인 로드로만 생기는 0바이트 파일인데, 이것이 없으면 `check_seeding.sh`가 두 저장소의
객체 수가 모자란다고(15/16, 17/22) 보고하고 실패합니다. 복사를 하면 마커도 함께 옮겨집니다. 매니페스트에
기록된 마커가 없는 첫 리전이라면, 아래의 추론 실행이 GPU 앱에서 마커를 만들고, ADMIN_GUIDE §6.3의
절차로 워크스테이션에서 기록하고 올립니다. 마커가 없을 때 M9이 오프라인에서 실제로 실패하는지는 아직
시험하지 않았습니다.

**데모 클립.** `a1_5` venv와 게이트된 `PhysicalAI-Autonomous-Vehicles` 데이터셋(온라인)이 필요해서
GPU 앱에서 만들고, 게시는 워크스테이션에서 합니다. 시딩된 리전에서 `hf-cache/`를 복사했다면 클립은
이미 들어 있으므로, 다시 게시하는 경우가 아니면 이 단계는 건너뛰세요(ADMIN_GUIDE §6.3).

**전제 조건.** 클립은 참가자 프로필이 하나도 없을 때, 또는 사용자 워크스페이스 버킷이 사용자별로
격리된 뒤에만 만드세요. 그 전에는 어떤 참가자든 `users/<your-profile>/`에 쓸 수 있고, 앱은 시작할
때마다 이 프리픽스를 홈 디렉터리로 복사합니다. 그러면 누군가 심어 둔 `.bashrc`나 IPython 시작 파일,
바꿔치기한 스크립트가 `.pt`와 그에 대해 출력되는 sha256을 모두 좌우할 수 있고, 여러분의 `HF_TOKEN`도 볼
수 있습니다. 이미 워크숍을 한 차례 운영한 스택이라면 먼저 참가자 프로필을 삭제하고, 새로 만든 본인
프로필을 쓰세요(ADMIN_GUIDE §6.3).

본인 프로필의 GPU 앱에서, 관리자 `HF_TOKEN`
(`Alpamayo-1.5-10B`, 그 `Cosmos-Reason2-8B` 백본, 그리고 `PhysicalAI-Autonomous-Vehicles`에 대한
라이선스 수락됨)으로:

```bash
export HF_TOKEN=hf_xxx
bash scripts/setup_cosmos_env.sh alpamayo          # build the a1_5 venv (online)
source /mnt/sagemaker-nvme/cosmos-work/alpamayo_env.sh
unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE          # data prep MUST be online

# For each demo clip: save the data dict. It prints the sha256 — copy it by hand.
python scripts/alpamayo_save_clip.py --clip 030c760c-ae38-49aa-9ad8-f5650a545d26 \
    --t0-us 5100000 --out /mnt/sagemaker-nvme/m6_work/clips
# 새 클립으로 추론을 한 번 실행: 게시 전에 클립을 확인하고, .no_exist 마커도 만듭니다.
# 매니페스트에 기록된 마커가 없을 때만 필수이고, 그 밖에는 선택입니다(가중치 참고).
python scripts/alpamayo_infer.py \
    --clips /mnt/sagemaker-nvme/m6_work/clips/030c760c-ae38-49aa-9ad8-f5650a545d26.pt \
    --out /mnt/sagemaker-nvme/m6_work/out
# 마커가 필요할 때만: staging으로 옮깁니다(빈 파일이고, 쓰이는 것은 이름뿐입니다).
aws s3 sync /mnt/sagemaker-nvme/hf/hub "s3://$USER_BUCKET/users/$USER_PROFILE/staging/hub-markers/" \
    --exclude '*' --include '*/.no_exist/*' --exclude '*/snapshots/*'

# Move the .pt off the app: your own workspace prefix (or Download it instead).
aws s3 cp /mnt/sagemaker-nvme/m6_work/clips/030c760c-ae38-49aa-9ad8-f5650a545d26.pt \
    "s3://$USER_BUCKET/users/$USER_PROFILE/staging/"
```

그다음 관리자 워크스테이션에서 파일의 sha256이 옮겨 적은 값과 같은지 확인하고,
`s3://<shared>/hf-cache/alpamayo-demo/`에 업로드한 뒤 staging 사본을 지웁니다. 마커를 staging에
올렸다면 같은 단계에서 기록하고 업로드합니다. 정확한 명령은 ADMIN_GUIDE §6.3의 3단계에 있습니다.
참가자는 공유 버킷 전체를 읽으므로, `hf-cache/hub/` 트리와
`hf-cache/alpamayo-demo/*.pt` 둘 다 가져올 수 있습니다.

> **노트북 + 스크립트 스테이징**(`aws s3 sync notebooks/ scripts/ →
> notebook-templates/`)도 공유 버킷에 쓰는 다른 모든 작업과 마찬가지로 관리자
> 워크스테이션에서 실행합니다.

## 검증된 실행(레퍼런스 배포 예시: 계정 <aws-account-id>)

클립 `030c760c-ae38-49aa-9ad8-f5650a545d26 @ t0_us=5_100_000`; Chain-of-Causation
*"Nudge to the left to clear the construction equipment blocking the right side of
our lane."* (89자).

- **p5.48xlarge(H100 80 GB), 단일 GPU** (2026-07-10): `HF_TOKEN` 미설정 +
  `HF_HUB_OFFLINE=1`로 `MODEL+PROCESSOR OFFLINE LOAD OK`(5개 샤드)(모델 +
  캐시의 Cosmos-Reason2-8B 백본). **minADE 0.375 m.**
- **g5.48xlarge(8× A10G 24 GB), `balanced-expert`** (2026-07-12): `pinned 42
  action-stack keys -> cuda:0`, 오프라인(캐시 전용, 다운로드 없음). **minADE
  0.378 m** — H100 실행과 0.003 m 차이(아키텍처 간 bf16 연산 순서 차이; 허용
  오차 내에 충분히 있음).
- **g5에서 전체 노트북 Restart & Run All** (2026-07-12, 참가자 경로, HF 토큰
  없음): cell-3이 `balanced-expert`를 자동 선택, cell-6 minADE 0.3779 m, cell-10
  `Status: PASS`, 출력은 `users/<profile>/m9/`에 작성됨.

## 멀티 GPU(24 GB 카드) — `balanced-expert` 디바이스 맵

p4d/p5는 종종 용량 제약이 있습니다. M9는 **24 GB 멀티 GPU** 박스
(g5.48xlarge = 8× A10G 24 GB, g6.48xlarge = 8× L4 24 GB)에서도 실행되지만,
평범한 `device_map="auto"`로는 **안 됩니다**:

- **`auto`가 실패하는 이유.** Alpamayo1_5는 `_no_split_modules`를 정의하지
  않으므로, accelerate가 확산(diffusion) 액션 `expert`(`Qwen3VLTextModel`,
  ~2.3 B)를 GPU 전체에 분할합니다. 그러면
  `sample_trajectories_from_data_with_vlm_rollout`이 `device =
  input_ids.device`와 `self.diffusion.sample(device=device)`를 수행하고, 확산
  루프 내부에서 expert의 KV 캐시 `torch.cat`이 두 GPU의 텐서를 섞습니다 →
  `Expected all tensors to be on the same device (cuda:6 vs cuda:1)`.
- **단일 24 GB GPU가 실패하는 이유.** 전체 ~21 GB 모델이 A10G 하나를 채우고,
  그다음 VLM `generate` KV 캐시 증가로 OOM이 발생합니다.
- **해결책: `--device-map balanced-expert`** (`scripts/alpamayo_infer.py` 내).
  *실제* `hf_device_map`을 읽기 위해 `auto`로 한 번 로드한 다음, 전체 **액션
  스택**(`expert`, `diffusion`, `action_space`, `action_in_proj`,
  `action_out_proj`)을 **cuda:0**에 고정하고 큰 VLM은 다른 GPU들에 샤딩된
  상태로 두는 명시적 맵을 다시 빌드하며, VLM이 생성한 `past_key_values`를
  cuda:0으로 이동시키기 위해 `expert.forward`를 래핑합니다(accelerate는 Cache
  객체의 내부 텐서를 *자동으로* 이동하지 *않습니다*). 이제 전체 확산 롤아웃에
  대해 `device == cuda:0`이고 캐시는 자체 일관성을 갖습니다. cuda:0은 액션
  스택(~5 GB) + 이동된 캐시 + 확산 활성화(activations)만 보유합니다(총 ~10 GB,
  24 GB보다 충분히 아래). 40 GB 이상의 단일 GPU가 없을 때 노트북 cell-3이 이를
  자동으로 선택합니다.

## 인스턴스 / 비용 참고

- **p5.48xlarge(H100 80 GB)**(단일 GPU) 및 **g5.48xlarge(8× A10G 24 GB)**
  (`balanced-expert`, 아래 참조)에서 검증됨. 모델은 ~10.5 B 파라미터(~21 GB
  bf16)에 VLM 롤아웃 활성화를 더한 것입니다.
  - **단일 GPU ≥ 40 GB** (p5, p4d A100, g6e L40S 48 GB): 하나의 디바이스에
    로드됨(`.to("cuda")`), 검증된 경로. 이 가운데 참가자가 고를 수 있는 것은
    p4d뿐입니다. 대시보드 목록이 곧 서버 쪽 상한이고, p5와 g6e는 그 목록에 없습니다.
    p4d A100 40 GB는 맞아야 하지만 테스트되지 않은 하한선입니다; OOM이 발생하면
    `balanced-expert`를 강제하세요.
  - **24 GB 멀티 GPU** (g5, g6): `balanced-expert`가 VLM을 샤딩하고 액션 스택을
    cuda:0에 고정합니다. 이것은 **용량 헤지**입니다 — p4d를 사용할 수 없을
    때, M9는 여유가 있는 어떤 멀티 GPU 박스에서도 여전히 실행됩니다.
- 환경 + 체크포인트는 NVMe에 있으며 **앱 재시작 시 초기화됩니다**; 설정 셀은
  멱등적이고, 새 앱은 다시 다운로드하는 대신 S3에서 체크포인트를 복원합니다
  (빠름, 리전 내).

## 라이선스

Alpamayo-1.5-10B 가중치는 **비상업용**입니다(연구/평가 전용). M9와 M10 모두 이
고지를 표시합니다; 추론 코드는 Apache-2.0입니다.
