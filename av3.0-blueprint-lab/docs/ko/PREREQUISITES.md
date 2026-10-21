# AV 3.0 Blueprint Lab — 사전 요구 사항

## 참가자용: 노트북을 위해 준비할 것 없음 🎉

**모든 노트북 모듈에 대해 Hugging Face 계정, 토큰, 모델 라이선스 승인은 필요하지
않습니다.** 노트북이 사용하는 모든 모델(Cosmos Reason, Cosmos Transfer, Cosmos
Predict, Alpamayo)은 **워크숍 관리자가 S3에 미리 캐시해 두었으며**, 노트북은
이를 **오프라인**으로 로드합니다. 대시보드 링크를 열고 모듈을 실행하기만 하면
됩니다 — [PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md)를 참조하세요.

> 필요한 것은 관리자가 보내주는 **참가자 대시보드 링크**뿐입니다.

### 한 가지 예외 — 선택적 M10 직접 실행에는 본인의 HF 토큰이 필요합니다 🔑
M10의 *노트북*(결과 시각화)은 다른 모든 모듈과 마찬가지로 토큰이 필요하지
않습니다. 하지만 SSM을 통해 GPU 호스트에서 실제 AlpaSim 시뮬레이션을 직접
실행하는 **선택적 고급 경로**(
[M10_PARTICIPANT_SSM_RUNBOOK.md](M10_PARTICIPANT_SSM_RUNBOOK.md) 참조)를 택한다면,
본인의 Hugging Face 토큰이 **필요합니다**. AlpaSim이 런타임에 게이트된
**`nvidia/PhysicalAI-Autonomous-Vehicles-NuRec`** 장면을 다운로드하기 때문입니다(이
데이터셋은 모델과 달리 공유 오프라인 캐시에 *포함되어 있지 않습니다*). M10 직접 실행
전에:

1. Hugging Face 계정과 토큰을 만드세요(`https://huggingface.co/settings/tokens`).
2. 그 계정으로
   [`nvidia/PhysicalAI-Autonomous-Vehicles-NuRec`](https://huggingface.co/datasets/nvidia/PhysicalAI-Autonomous-Vehicles-NuRec)의
   라이선스에 동의하세요("Agree and access repository").
3. SSM 세션 안에서 `export HF_TOKEN=hf_…`할 수 있도록 토큰을 준비해 두세요.

M10 노트북만 실행한다면(기본값) 이 단계를 건너뛰세요 — 토큰이 필요하지 않습니다.

### 라이선스 참고 (M9 / M10)
M9/M10이 사용하는 Alpamayo-1.5-10B 가중치는 **비상업용** 라이선스(연구/평가 전용)
하에 있습니다. 직접 다운로드하지는 않지만, M9/M10을 실행함으로써 해당 라이선스에
동의하게 됩니다.

---

## 워크숍 관리자용: 모델 미리 캐시하기 (이벤트 전에 한 번 수행)

노트북은 참가자가 Hugging Face에 인증하도록 요구하지 않습니다. 대신 관리자가
모든 것을 한 번(HF 토큰 + 동의한 라이선스로) 다운로드하여 S3에 스테이징합니다.
두 개의 별도 캐시:

### A. 단순 모델 캐시 — M2 (`model-cache/`)
`scripts/cache_models.sh`는 각 저장소를 `hf download --local-dir`로 다운로드하고
`s3://<shared>/model-cache/<name>/`에 `aws s3 sync`합니다. **M2** 노트북은
거기서 `aws s3 sync`합니다 — 순수한 파일 트리입니다. (M3는 순수 Python 큐레이션
단계이며 모델을 로드하지 않습니다; M2의 `captions.json` 출력을 소비합니다.)

```bash
export HF_TOKEN=hf_...            # admin token, licenses accepted (see list below)
./scripts/cache_models.sh          # resolves the shared bucket from the stack
```

### B. HF 오프라인 캐시 — M5, M6, M9 (`hf-cache/hub/`)
M5/M6/M9은 런타임에 Hugging Face 자체 캐시 레이아웃을 통해 게이트된 체크포인트를
로드합니다(M5/M6는 Cosmos 저장소의 `examples/inference.py`를 통해; M9은
`Alpamayo1_5.from_pretrained`을 통해, 이는 숨겨진 `Cosmos-Reason2-8B` VLM 백본도
가져옵니다). 이를 **참가자 토큰 없이** 작동시키기 위해, 관리자는 **HF 캐시 트리**를
`s3://<shared>/hf-cache/hub/`에 스테이징하며; `setup_cosmos_env.sh`가 이를
`HF_HOME`으로 복원하고 `HF_HUB_OFFLINE=1`을 설정합니다.

이 캐시를 채우는 가장 확실한 방법(각 모델이 필요로 하는 모든 리비전 + 사이드
파일이 존재함을 보장)은 **관리자 HF 토큰으로 GPU 인스턴스에서 M5, M6, M9을 각각
한 번씩 실행**한 다음, 결과 캐시를 sync하는 것입니다:

```bash
# On a GPU JupyterLab app, after M5 + M6 + M9 have each run once successfully:
aws s3 sync /mnt/sagemaker-nvme/hf/hub \
  s3://<shared-bucket>/hf-cache/hub/ --only-show-errors
```

그 후에는 참가자에게 토큰이 필요하지 않습니다: `setup_cosmos_env.sh`가 S3 캐시를
발견하여 복원하고 오프라인으로 실행합니다.

> **M9에는 데모 클립도 필요합니다.** M9의 `PhysicalAI-Autonomous-Vehicles`
> 데이터셋은 오프라인으로 읽을 수 없으므로, 관리자가 데모 클립을 한 번 미리
> 저장하여(`scripts/alpamayo_save_clip.py`)
> `s3://<shared>/hf-cache/alpamayo-demo/`에 업로드합니다(`hf-cache/` 아래에 두어
> exec 역할의 쓰기 범위로 GPU 앱 터미널에서 업로드되도록). 전체 일회성 절차는
> [ALPAMAYO_M9.md](ALPAMAYO_M9.md)를 참조하세요.

### C. AlpaSim 폐루프 레퍼런스 평가 — M10 (`m10-reference/`)
M10은 실제 AlpaSim 시뮬레이터로 Alpamayo 정책을 **폐루프** 평가합니다. 이
시뮬레이터는 Docker-Compose 마이크로서비스 시스템으로, **Studio 노트북에서
실행할 수 없으며**(Docker 데몬 없음) ≥40 GB GPU가 필요합니다. 따라서 관리자가
이를 **GPU EC2 호스트에서 한 번**(`scripts/alpasim_ec2_setup.sh`) 실행하고 실제
결과를 `s3://<shared>/m10-reference/`에 업로드하며; M10 노트북(CPU)이 이를
다운로드하여 시각화합니다. 관리자 HF 토큰(NuRec 데이터셋) **및 NGC API
키**(게이트된 NuRec 렌더러 이미지)가 필요합니다. 일회성 비용 약 $30; 참가자 비용
$0. 전체 절차, 인스턴스 선택, GPU 배치 세부 사항은
[ALPASIM_M10.md](ALPASIM_M10.md)를 참조하세요.

### 관리자: 한 번 동의해야 할 라이선스 (관리자의 HF 계정에서)
각 항목에서 <strong>"Agree and access repository"</strong>에 동의한 다음 `HF_TOKEN`을
설정하세요:

| 저장소 | 사용처 | 라이선스 |
|---|---|---|
| [nvidia/Cosmos-Reason1-7B](https://huggingface.co/nvidia/Cosmos-Reason1-7B) | M2, M5, M6 | NVIDIA Open Model |
| [nvidia/Cosmos-Guardrail1](https://huggingface.co/nvidia/Cosmos-Guardrail1) | M5, M6 | NVIDIA Open Model |
| [nvidia/Cosmos-Transfer2.5-2B](https://huggingface.co/nvidia/Cosmos-Transfer2.5-2B) | M5 | NVIDIA Open Model |
| [nvidia/Cosmos-Predict2.5-2B](https://huggingface.co/nvidia/Cosmos-Predict2.5-2B) | M6 | NVIDIA Open Model |
| [nvidia/Alpamayo-1.5-10B](https://huggingface.co/nvidia/Alpamayo-1.5-10B) | M9, M10 | **비상업용** |
| [nvidia/Cosmos-Reason2-8B](https://huggingface.co/nvidia/Cosmos-Reason2-8B) | M9, M10 (Alpamayo VLM 백본) | NVIDIA Open Model |
| [nvidia/PhysicalAI-Autonomous-Vehicles](https://huggingface.co/datasets/nvidia/PhysicalAI-Autonomous-Vehicles) | M9 (데모 클립, 데이터셋) | NVIDIA |
| [nvidia/PhysicalAI-Autonomous-Vehicles-NuRec](https://huggingface.co/datasets/nvidia/PhysicalAI-Autonomous-Vehicles-NuRec) | M10 (AlpaSim 평가 장면) | NVIDIA AV NuRec Dataset License |

**M10에는 NGC도 필요합니다**(HuggingFace가 아님): AlpaSim NuRec 렌더러 이미지
`nvcr.io/nvidia/nre/nre-ga:26.04`는 NVIDIA NGC에서 가져옵니다.
`https://org.ngc.nvidia.com/setup/api-key`에서 API 키를 받고 해당 이미지에 대한
접근 권한을 확보하세요. 이는 관리자 전용입니다(M10은 EC2 호스트에서 실행,
[ALPASIM_M10.md](ALPASIM_M10.md) 참조).

> **보안:** 관리자 토큰은 비밀입니다 — 커밋하지 말고, 캐싱이 완료된 후에는
> 폐기하세요(참가자가 접근하는 것은 S3의 캐시뿐입니다).

### 대체 방안 (S3 HF 캐시가 스테이징되지 않은 경우)
`hf-cache/hub/`가 S3에 없으면, M5/M6는 **온라인** 다운로드로 대체되며 그러면
참가자는 `HF_TOKEN`(노트북 첫 셀에 붙여넣기)과 동의한 라이선스가 *실제로*
필요합니다. M9은 추가로 데모 `.pt`가 스테이징되어 있어야 합니다(그 데이터셋은
오프라인으로 전혀 읽을 수 없음). 캐시 + 데모 클립을 스테이징하면(§B) 이 모든
것을 피할 수 있습니다 — 권장 사항입니다.
