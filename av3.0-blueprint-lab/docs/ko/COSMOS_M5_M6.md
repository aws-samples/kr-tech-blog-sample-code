# Cosmos Transfer / Predict (M5, M6) — SMD 이미지에서의 실제 추론

**상태:** M5(Cosmos Transfer 2.5, edge → weather)와 M6(Cosmos Predict 2.5,
video2world)는 둘 다 SageMaker Distribution(SMD) GPU 이미지에서 **엔드투엔드로
검증**되었습니다 — M5는 리포지토리 예제 + 실제 nuScenes CAM_FRONT 클립에서,
M6는 전체 JupyterLab "Restart & Run All"을 통해서. 이제 둘 다 오프라인 S3
체크포인트 캐시를 통해 **참가자 HF 토큰 없이** 실행됩니다(아래 "오프라인
체크포인트 캐시" 참조).

## 이 모듈들이 가지고 있던 핵심 문제

배포된 노트북은 **존재하지 않는** **환각된 `cosmos1` 패키지**
(`from cosmos1.models.diffusion.inference... import load_model_by_config`,
`WorldGenerationPipeline`, `cosmos1.utils.video_utils`)를 임포트했습니다.
`pip install cosmos-transfer2`는 존재하지 않습니다. 실제 워크플로우는:

1. 공식 리포지토리 `github.com/nvidia-cosmos/cosmos-transfer2.5` 클론.
2. `uv sync --extra=cu128 --python 3.10`(torch 2.7 + cu128, transformer-engine,
   megatron — 모두 **사전 빌드된** 휠, 소스 컴파일 없음).
3. `examples/inference.py -i <spec.json> -o <outdir> control:edge` 실행.

M7(gsplat은 SMD 이미지가 할 수 없는 소스 CUDA 컴파일이 필요)과 달리, **M5는
모두 사전 빌드되어** 있습니다 — 따라서 환경이 연결되면 그냥 작동하고, 스크립트를
통해 재현 가능합니다.

## `scripts/setup_cosmos_env.sh`

하나의 멱등적 스크립트가 인스턴스 NVMe(`/mnt/sagemaker-nvme`, p4d/p5에서
28 TB)에서 전체 설치를 수행하고 노트북이 소스하는 `cosmos_env.sh`를 씁니다.
우리가 발견해야 했던 모든 환경 수정을 인코딩합니다:

| # | 증상 | 근본 원인 | 스크립트의 수정 |
|---|---------|-----------|---------------|
| 1 | `ImportError: libGL.so.1` 그다음 `libgthread-2.0.so.0` | `opencv-python`(GUI 빌드)이 SMD 이미지에 없는 시스템 GL 라이브러리를 필요로 함 | `opencv-python-headless`만 유지 |
| 2 | `CalledProcessError: ldconfig -p \| grep libnvrtc` | transformer-engine `_load_nvrtc()`가 `ldconfig`를 실행함; pip CUDA 라이브러리가 링커 캐시에 없어 grep이 1로 종료되고 폴백 전에 크래시 | `CUDA_HOME`을 pip `nvidia/` 트리로 설정하여 TE의 재귀 glob이 `libnvrtc`를 먼저 찾도록 함 |
| 3 | `OSError: libcublas.so.12: cannot open shared object file` | TE가 버전이 붙은 SONAME을 `dlopen`함; pip CUDA 디렉터리가 로더 경로에 없음 | 모든 `nvidia/*/lib`를 `LD_LIBRARY_PATH`에 넣음 |
| 4 | `RuntimeError: Unable to dlopen libcudart.so` | TE가 **버전이 없는** 이름을 `dlopen`함; pip 휠은 `libcudart.so.12`만 제공 | `libX.so → libX.so.NN` 심링크 생성 |
| 5 | `Access denied. This repository requires approval` | Cosmos 체크포인트가 HuggingFace 게이트됨 | 라이선스를 수락한 계정에 대한 `HF_TOKEN`(아래) |
| 6 | `RuntimeError: Unable to parse string as hex hash value` | hf-xet 청크 다운로드 백엔드 버그 | `HF_HUB_DISABLE_XET=1` |

`ldconfig`(단계 3 인접)도 만전을 기하기 위해
`/etc/ld.so.conf.d/pip-nvidia-cuda.conf`를 통해 등록되지만, `cosmos_env.sh`의
`LD_LIBRARY_PATH`가 진짜 보장입니다(일부 SMD 앱 셸은 conf.d 파일을 집어오지
않았습니다).

### 게이트된 HuggingFace 리포지토리(HF 계정당 한 번 라이선스 수락)

- https://huggingface.co/nvidia/Cosmos-Guardrail1
- https://huggingface.co/nvidia/Cosmos-Transfer2.5-2B
- https://huggingface.co/nvidia/Cosmos-Reason1-7B  (프롬프트/가드레일 추론기로 사용)
- (M6) https://huggingface.co/nvidia/Cosmos-Predict2.5-2B

설정 셀을 실행하기 전에 `export HF_TOKEN=hf_xxx`를 설정하세요. **토큰을
커밋하지 마세요.** 토큰이 노출되면
https://huggingface.co/settings/tokens 에서 폐기하세요.

## M5 노트북 흐름(재작성됨)

`notebooks/M5_Cosmos_Transfer_Augmentation.ipynb`는 이제:

1. **Config** — 프로필/버킷, NVMe 작업 디렉터리, 날씨 프롬프트, `HF_TOKEN`.
2. **GPU 확인** — 24 GB 이상의 모든 GPU 박스(`total_memory`, `total_mem` 아님).
3. **Install** — `scripts/setup_cosmos_env.sh` 실행(멱등적; 새 앱의 첫 실행에서
   ~15-25분, 이후에는 거의 즉시).
4. **Build input** — `m1/manifest.json`을 읽고, 공유 버킷에서 나열된 nuScenes
   CAM_FRONT 프레임을 다운로드하여, 그중 ≤57개를 1280×704 @ 10 fps mp4로
   이어붙임.
5. **Build spec** — 날씨 조건당 JSON 하나; `control_path`를 **생략**하여
   Cosmos가 즉석에서 Canny edge 컨트롤을 계산하도록 함(`--video-path`만).
6. **Inference** — spec당 `examples/inference.py ... control:edge`(35개 확산
   단계; p4d/p5에서 클립당 ~3-5분).
7. **Upload** — 생성된 + edge-control mp4 + 소스 클립 + 매니페스트 → `m5/`.
8. **비용 + 검증 + 인라인 미리보기.**

워크숍 실행 비용을 낮게 유지하기 위해 기본값은 `CONDITIONS = ["rain"]`입니다;
모든 변형을 위해서는 `["rain","fog","night"]`로 확장하세요.

### 검증된 실행(2026-07-07, 레퍼런스 배포 예시 계정 <aws-account-id>)

- 리포지토리 예제: `robot_edge_spec.json` → `robot_edge.mp4`(3.8 MB, 35/35 단계).
- nuScenes: 57개 CAM_FRONT 프레임 → 자동 edge → `nuscenes_rain.mp4`
  (로그의 `{'edge': None}`이 즉석 edge를 확인; 35/35 단계, 실행 중인 GPU
  박스에서 ~4m38s).

## M6 (Cosmos Predict 2.5) — 검증됨

M6는 동일한 환각된 API(`WorldGenerationPipeline`)를 배포했습니다. 실제 경로는
형제 리포지토리 <strong>`github.com/nvidia-cosmos/cosmos-predict2.5`</strong>입니다 —
Transfer와 동일한 설치 형태(`cosmos-oss[cu128_torch27]`, `uv sync --extra=cu128`,
동일한 CUDA/opencv 수정)이지만 <strong>자체 `.venv`</strong>에 있는 **별도의** 최상위 패키지
(`cosmos_predict2`)입니다. 2026-07-09에 엔드투엔드로 검증됨(KY-5, p5.48xlarge,
H100×8).

- `scripts/setup_cosmos_env.sh`는 이제 인자를 받습니다: `transfer` | `predict` |
  `both`(기본값). `prepare_repo()`는 각 리포지토리를 자체 venv에 클론 +
  `uv sync`하고, 공유 수정을 적용하며, 스택별 환경 파일을 씁니다:
  **`cosmos_env.sh`**(Transfer/M5)와 **`cosmos_predict_env.sh`**(Predict/M6).
  M6는 후자를 소스합니다.
- M6 노트북(`notebooks/M6_Cosmos_Predict_Synthesis.ipynb`)이 실제 흐름으로
  재작성됨: 설정 실행(`predict`) → M5의 nuScenes 클립 재사용(`m5/source/`,
  없으면 M1에서 재빌드) → Video2World spec 빌드 →
  `examples/inference.py -i spec -o out --inference-type=video2world` → `m6/`에
  업로드.
- **Input spec**(Predict 2.5): `{"inference_type":"video2world", "name":..,
  "prompt":.., "input_path":<mp4>}`. `input_path`에 주의(Transfer의
  `video_path`가 아님). Base 2B는 `--experiment`/`--checkpoint-path`가 **필요
  없음**; 모드는 자동 감지됨(비디오 프레임 2개 이상 → video2world). 체크포인트
  (Cosmos-Predict2.5-2B/base/post-trained, Reason1.1-7B, Guardrail1)는 HF에서
  `HF_HOME`으로 자동 다운로드됩니다.
- **검증된 실행**: nuScenes CAM_FRONT 클립 → `near_collision` 프롬프트 →
  `Generating video with standard mode... 36/36 [~4m07s]` → `nuscenes_near_collision.mp4`.

### M6를 연결하며 발견한 두 가지 버그(setup_cosmos_env.sh에서 수정됨)
- **uv venv에는 `pip`이 없음.** 리팩터가 opencv 정리를 위해 잠시
  `"$venv/bin/python" -m pip`을 사용함 → `No module named pip`, 그래서 GUI
  `opencv-python`이 그대로 남아 `import cv2`가 `libgthread-2.0.so.0`에 부딪힘
  (M5와 동일한 libGL 계열). 수정: **`VIRTUAL_ENV=$venv uv pip ...`** 사용(uv
  venv에는 항상 `uv pip`이 있고, `pip`은 절대 없음).
- **git-lfs가 기본 SMD 셸 PATH에 없음** → `git clone` 체크아웃이 실패함
  (`git-lfs filter-process: git-lfs: not found`). 수정:
  `-c filter.lfs.smudge= -c filter.lfs.process= -c filter.lfs.required=false`로
  클론(코드 파일은 내려오고; LFS 예제 자산은 포인터로 남는데, 우리는 필요 없음).

## 오프라인 체크포인트 캐시 — 참가자 HF 토큰 없음

M5/M6의 `examples/inference.py`는 런타임에 Hugging Face 자체 캐시를 통해
게이트된 Cosmos 체크포인트를 풀합니다(`checkpoint_db` → `uvx hf download`). 모든
참가자에게 HF 계정 + 토큰 + 라이선스 승인을 면제하기 위해, 우리는 한 번
캐시하고 오프라인으로 실행합니다:

- **관리자(한 번):** 관리자 HF 토큰(라이선스 수락됨)이 있는 GPU 앱에서 M5 + M6를
  실행한 다음, `aws s3 sync /mnt/sagemaker-nvme/hf/hub s3://<shared>/hf-cache/hub/`.
  (단순한 `hf download` 대신) 모듈을 실행하면 cosmos가 필요로 하는 모든 리비전 +
  사이드 파일(Wan2.1 VAE, Reason1.1, Guardrail1, …)이 트리에 있음을 보장합니다.
- **참가자 설정:** `setup_cosmos_env.sh`가 `hf-cache/hub/`를 `$HF_HOME/hub`로
  다시 `aws s3 sync`하고, 생성된 `cosmos_env.sh` / `cosmos_predict_env.sh`는
  **그 캐시가 있을 때만** **`HF_HUB_OFFLINE=1`**(+ `TRANSFORMERS_OFFLINE=1`)을
  export합니다. 그러면 cosmos가 토큰 없이, 네트워크 없이 캐시에서 로드합니다.
- **검증됨(2026-07-09):** `HF_TOKEN=""`과 `HF_HUB_OFFLINE=1`로, M6 video2world가
  36/36 단계를 완료함 — `uvx hf download`가 오프라인 모드를 준수하고 로컬
  캐시에 적중함. 동일한 메커니즘이 M5를 커버함.
- **폴백:** `hf-cache/hub/`가 S3에 없으면, 설정은 온라인 모드를 켜둔 채로
  두고 호출자가 제공한 `HF_TOKEN`으로 여전히 다운로드합니다(수락된 라이선스
  필요). 노트북은 토큰이 없을 때 더 이상 하드 실패하지 않습니다 — 오프라인
  캐시를 가정하고 둘 다 사용할 수 없는 경우에만 실제 다운로드에서 오류를
  발생시킵니다.

## 인스턴스 / 비용 참고

- **아무 GPU 인스턴스에서나 되지 않습니다** — 두 모델 모두 한 GPU에 올리려면 ~65 GB가
  필요합니다. 24 GB 카드에서는 **GPU 2장 이상**이 있어야 샤딩으로 실행되며, 1장이면
  노트북이 `RuntimeError`로 멈추고 멀티 GPU 인스턴스를 고르라고 안내합니다
  (M5 cell 2 / M6 cell 2). p5.48xlarge(H100×8)와 p 계열에서 검증되었습니다.
  걸림돌은 결코 인스턴스가 아니었습니다 — 환경 연결이었고, 이제 스크립트화됨.
- 환경 + 체크포인트는 NVMe에 있으며 **앱 재시작 시 초기화됩니다**; 설정 셀은
  멱등적이므로 재시작 후 재실행이 의도된 흐름입니다. 오프라인 S3 캐시로, 새
  앱의 첫 실행은 HF에서 다시 다운로드하는 대신 S3에서 체크포인트를 복원합니다
  (빠름, 리전 내).
- 일회성 첫 실행 비용은 `uv sync` + 캐시 복원(~15-25분)입니다.
