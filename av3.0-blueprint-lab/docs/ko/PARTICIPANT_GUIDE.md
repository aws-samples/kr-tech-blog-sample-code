# AV 3.0 Blueprint Lab — 참가자 가이드

환영합니다! 이 가이드는 AV 3.0 파이프라인 노트북(M0–M12)을 처음부터 끝까지
실행하는 과정을 안내합니다. AWS 계정이나 콘솔 접근 권한은 **필요하지 않습니다** —
워크숍 관리자가 개인 대시보드 링크를 제공하며, 모든 작업은 브라우저에서
이루어집니다.

> 📚 **AV 3.0 / Cosmos & Alpamayo 모델이 처음이신가요?** **워크숍 전에**
> [PRE_LEARNING_GUIDE.md](PRE_LEARNING_GUIDE.md)를 읽어 보세요(약 45–60분)
> — 모듈을 이해할 수 있도록 개념을 설명합니다. 이 가이드는 당일 사용하는
> 단계별 클릭 실행 안내서입니다.

이 파이프라인은 [NVIDIA + AWS Physical AI 블로그](https://aws.amazon.com/blogs/industries/building-an-end-to-end-physical-ai-data-pipeline-for-autonomous-vehicle-3-0-on-aws-with-nvidia/)를 따릅니다:
데이터 탐색 → 캡셔닝(Cosmos Reason) → 큐레이션 → 증강 →
VLA 추론 → 폐루프 시뮬레이션.

---

## 0. 사전 준비 사항 — 준비할 것 없음

**Hugging Face 계정, 토큰, 모델 라이선스 승인은 필요하지 않습니다.**
모든 모델(Cosmos Reason / Transfer / Predict, Alpamayo)은 **관리자가 S3에
미리 캐시해 두었으며**, 노트북은 이를 오프라인으로 로드합니다. 아래의 대시보드
링크를 열고 모듈을 실행하기만 하면 됩니다.

필요한 것은 관리자가 보내주는 **참가자 대시보드 링크**뿐입니다. (관리자용
세부 사항: [PREREQUISITES.md](PREREQUISITES.md).)

> M9/M10은 Alpamayo-1.5-10B를 사용하며, 이는 **비상업용**(연구/평가 전용)입니다 —
> 직접 다운로드하지는 않지만, M9/M10을 실행하는 것은 해당 라이선스에 동의하는 것입니다.

---

## 1. 대시보드 열기

관리자가 다음과 같은 형태의 **참가자 대시보드 링크**를 제공합니다:

```
https://<user-dashboard>.cloudfront.net/?userId=<your-id>&token=<your-token>
```

- 아무 브라우저에서나 여세요. 이 링크는 **만료되지 않습니다** — 북마크해 두고
  워크숍 중 언제든 다시 사용하세요.
- 페이지에 **"Demo Mode"** 배너가 표시되면, 링크에 `userId`/`token`이
  누락된 것입니다 — 뒤로 돌아가 관리자가 보낸 전체 링크를 여세요.
- **Pipeline Map**이 표시됩니다: M1–M12 노드 12개가 상태별로 색상 구분되어 있습니다.

> 여기서 실행하는 워크스페이스 링크는 몇 분 후 만료되지만, 그것을 직접 복사할
> 일은 없습니다 — **Open Workspace**를 클릭할 때마다(3단계) 대시보드가 새 링크를
> 생성합니다. 대시보드 링크만 계속 사용하세요.

---

## 2. 모듈에 맞는 인스턴스 선택

모듈마다 필요한 컴퓨팅이 다릅니다. **CPU 모듈**(M0, M1, M4, M10, M11, M12)은
작은 기본 인스턴스에서 실행되며 변경할 필요가 없습니다. **GPU 모듈**(M2, M3, M5–M9)은
GPU 인스턴스가 필요하며, 대시보드에서 직접 선택합니다.
(M12의 노트북은 **CPU**입니다 — 별도의 `ml.m5.xlarge` 인스턴스에서 실행되는 실제
2노드 분산 학습 작업을 제출한 뒤, 측정된 지표를 시각화합니다.
[HYPERPOD_M12.md](HYPERPOD_M12.md)를 참조하세요.)
(M10의 SageMaker 노트북은 **CPU**입니다 — 실제 AlpaSim 결과를 다운로드하여
시각화합니다. 실제 폐루프 시뮬레이션은 별도의 **GPU EC2 호스트**에서 실행됩니다:
관리자의 공유 레퍼런스 실행을 사용하거나, 선택적 고급 경로로 SSM을 통해
직접 실행할 수 있습니다(**시간당 약 $10.5**, 수십 분에서 약 2–3시간 소요; 이
호스트는 직접 종료할 수 없으며 관리자가 종료합니다). 직접 실행하는 경우에는 추가로
**본인의 Hugging Face 토큰**이 필요합니다(게이트된 NuRec 장면용 —
[PREREQUISITES.md](PREREQUISITES.md) 참조); 노트북만 사용하는 경로에는 토큰이
필요하지 않습니다. [ALPASIM_M10.md](ALPASIM_M10.md)를, 직접 실행의 경우
[M10_PARTICIPANT_SSM_RUNBOOK.md](M10_PARTICIPANT_SSM_RUNBOOK.md)를 참조하세요.)

워크스페이스는 작은 CPU 인스턴스(`ml.t3.medium`)에서 시작됩니다.
<strong>M2(Cosmos Reason Captioning)</strong>와 같은 GPU 모듈을 실행하기 전에 인스턴스를
전환하세요:

1. Pipeline Map에서 **M2 — Cosmos Reason Captioning** 노드를 클릭합니다.
2. 사이드 패널에서 **Instance Options**를 클릭합니다.
3. 권장 인스턴스(**`ml.g5.12xlarge`**)가 이미 선택되어 있습니다.
   **Apply & Restart**를 클릭합니다.
4. 워크스페이스가 다시 시작됩니다(몇 분 소요). 올바른 **GPU 소프트웨어 이미지가
   자동으로 선택됩니다** — 직접 선택하지 않습니다.

이것이 전체 흐름입니다: **인스턴스를 선택하고 Apply를 클릭하세요.** 플랫폼이
GPU 이미지와 노트북 동기화를 대신 처리합니다.

### 모듈별 권장 인스턴스

| 모듈 | 권장 인스턴스 | 유형 |
|--------|---------------------|------|
| M0 파이프라인 개요 | `ml.t3.medium` | CPU |
| M1 데이터 탐색 | `ml.t3.medium` | CPU |
| **M2 Cosmos Reason 캡셔닝** | **`ml.g5.12xlarge`** | GPU (4× A10G, 96 GB) |
| M3 Cosmos Curator | `ml.g5.12xlarge` | GPU |
| M4 OpenSearch 시맨틱 검색 | `ml.t3.medium` | CPU |
| M5 Cosmos Transfer (날씨 증강) | **`ml.g5.12xlarge`** | GPU (4× A10G, GPU당 24 GB) — 480p로 실행; 아래 티어 표 참조 |
| M6 Cosmos Predict (시나리오 생성) | **`ml.g5.12xlarge`** | GPU (4× A10G) — 480×832로 실행; 아래 티어 표 참조 |
| M7 Nerfstudio 3D 재구성 | `ml.g5.xlarge` | GPU (1× A10G) — ⚠️ **제한적으로 동작**: GPU 확인 + 데이터 준비 셀은 실행되지만, 최종 3D 학습 셀(splatfacto)은 현재 이미지에서 실행되지 않습니다. M7은 선택/데모 모듈로 취급하세요(아래 참고 사항 참조). |
| M8 Cosmos Reason LoRA SFT | **`ml.g5.12xlarge`** | GPU (4× A10G) — 네이티브 1600×900으로 학습. VRAM은 같은 22,888 MiB 지오메트리인 **4× L4에서 실측**: 최악 GPU 피크 11.28 GiB, 여유 10.76 GiB. GPU 2장 이상(또는 40 GB 이상 1장) 필요. **4× A10G**(`ml.g5.12xlarge`)에서 end-to-end 실행 완료: 40스텝 × 4 accum, 7.8분, loss 18.06 → 7.83, 최악 GPU 피크 7.05 GiB, 어댑터 154.1 MiB. 출력은 `examples/notebooks-with-outputs.tar.gz` 에 있습니다. |
| M9 Alpamayo VLA 추론 | **`ml.g5.12xlarge`** | GPU (4× A10G) — 샤딩 "balanced-expert" 경로; 통과한 실행(minADE 0.3779)은 A10G에서 나왔습니다 |
| M10 AlpaSim 폐루프 평가 | `ml.t3.medium` | CPU (실제 AlpaSim 결과를 시각화; 실제 시뮬레이션은 GPU EC2 호스트에서 실행 — 관리자 레퍼런스 또는 SSM을 통한 본인 실행) |
| M11 파이프라인 자동화 | `ml.t3.medium` | CPU |
| M12 HyperPod 분산 학습 | `ml.t3.medium` | CPU (`ml.m5.xlarge`×2에서 실제 2노드 DDP 학습 작업 제출; HyperPod 자체는 개념적 — HYPERPOD_M12.md 참조) |

워크스페이스는 **200 GB** EBS 볼륨으로 생성되며, 이는 모든 모듈을 커버합니다.
**Instance Options** 패널은 볼륨의 *실제* 크기와 그 모듈의 *권장* 용량을 함께 보여줍니다 —
서로 다른 숫자이고 패널이 그렇게 구분해 표시합니다. 노트북이 실제로 디스크가 부족하면 거기서
**+50 GB / +200 GB**를 추가할 수 있습니다. 볼륨은 늘릴 수는 있지만 **줄일 수는 없습니다**.

### 출력 품질 vs 비용 — GPU당 VRAM 티어 (M5 / M6 / M9)

**권장 인스턴스로 모든 모듈이 완주합니다.** 랩을 끝내기 위해 더 큰 박스가 필요하지
않습니다. 더 큰 박스가 주는 것은 *출력 품질*이며, 이는 **GPU당 VRAM**에 달려
있습니다 — 총 VRAM도, 인스턴스 크기 숫자도 아닙니다:

| 인스턴스 | GPU당 | M5 / M6 출력 | M9 경로 | ~$/hr |
|---|---|---|---|---|
| **`ml.g5.12xlarge`** (기본값) | ~22.5 GB | 480p, 가드레일 **OFF** | 샤딩 `balanced-expert` | **7.09** |
| `ml.g6.24xlarge` | ~22.5 GB | 기본값과 동일 | 샤딩 | 8.34 — 같은 티어, +18% 비용 |
| `ml.g7e.2xlarge` (RTX PRO 6000 1장) | **96 GB** | **720p / 네이티브, 가드레일 ON** | **단일 GPU** | **4.20** — 아래 주의사항 참조 |
| `ml.g5.24xlarge` | ~22.5 GB | 기본값과 동일 | 샤딩 | 10.18 — **이득 없음, +44% 비용** |
| `ml.g5.48xlarge` / `ml.g6.48xlarge` | ~22.5 GB | 기본값과 동일 | 샤딩 | 20.36 / 16.69 — GPU 수만 늘고 티어는 동일 |
| `ml.p4d.24xlarge` | 40 GB | 720p / 네이티브, 가드레일 ON | 단일 GPU | 25.25 |
| `ml.p5.48xlarge` | 80 GB | 720p / 네이티브, 가드레일 ON | 단일 GPU | 63.30 |

알아둘 점 세 가지:

- **g5·g6 패밀리에서는 사이즈를 올리면 GPU 개수만 늘고, GPU당 VRAM은 그대로입니다.**
  A10G도 L4도 전부 24 GB입니다. 따라서 g5/g6로는 38–40 GB 티어에 도달할 수 없습니다.
  가능한 패밀리는 g7e(카드당 96 GB), p4d(A100 40 GB), p5(H100 80 GB)입니다.
- **24 GB 카드는 검증된 경로이며, 성능이 떨어지는 임시 대안이 아닙니다.** M9은 24 GB
  카드에서 처음부터 끝까지 실행해 **minADE 0.3779 m, `Status: PASS`** 를 기록했습니다 —
  H100 레퍼런스 실행과 0.003 m 차이입니다([ALPAMAYO_M9.md](ALPAMAYO_M9.md) "Verified runs" 참조).
- **`ml.g7e.2xlarge`는 "좋을수록 비싸다"는 통념을 깹니다.** RTX PRO 6000 Blackwell
  한 장이 96 GB이므로 **단일** GPU로 최상위 티어를 만족하며, 가격은 기본값의 약
  **절반**입니다. 단, 실제 주의사항 두 가지: 이 랩에는 **g7e 검증 실행 기록이
  없으며**, 이 인스턴스는 **별도의 Studio-JupyterLab 쿼터**가 필요합니다(기본
  미지급). 선택 전에 워크숍 관리자에게 문의하세요. 권장·검증된 선택은 여전히
  기본값입니다.

가드레일 모델을 켠 최대 해상도 출력이 필요하면 `ml.g7e.2xlarge`(가장 저렴)를 먼저,
없으면 `ml.p4d.24xlarge`를 고르세요 — 어느 쪽이든 끝나면 즉시 정지하세요.

---

## 3. 워크스페이스를 열고 노트북 실행하기

1. 대시보드 오른쪽 상단의 버튼을 봅니다.
   - **Open Workspace** → 클릭하면 새 JupyterLab 탭이 열립니다(별도 로그인 없음).
   - **Start Workspace** → 워크스페이스가 멈춘 상태입니다(첫 로그인 때, 그리고 유휴
     종료 후에 이렇게 보입니다). 클릭하면 Instance Options가 열리니 인스턴스를 확인하고
     **Apply & Restart**를 누릅니다. 버튼이 **Open Workspace**로 바뀌면 그것을 클릭합니다.
   - **Workspace starting… / Shutting down…** → 전환 중이므로 기다립니다.
2. JupyterLab 파일 브라우저에서 해당 모듈의 노트북을 엽니다(예:
   `M2_Cosmos_Reason_Captioning.ipynb`).
3. 셀을 위에서 아래로 실행합니다(Shift+Enter 또는 Run ▸ Run All Cells).

> **인스턴스를 변경한 후(2단계)에는 항상 Open Workspace를 다시 클릭**하여 새
> 링크를 받으세요 — 이전 탭은 이전 인스턴스를 가리킵니다.

> ℹ️ **인스턴스 변경은 작업 내용을 지우지 않습니다.** 각 모듈은 결과를 S3에
> 저장하고 다음 모듈이 거기서 읽어오며, 워크스페이스 홈 디렉터리는 재시작 후에도
> 유지됩니다. 이전 커널의 메모리 내 변수만 지워집니다 — 새 노트북의 셀을 다시
> 실행하기만 하면 됩니다. 아래
> [인스턴스 변경 시 무엇이 유지되나요?](#what-survives-an-instance-change)를 참조하세요.

---

## 4. GPU 확인 (M2 및 기타 GPU 모듈)

각 GPU 노트북은 **사전 점검용 GPU 확인** 셀로 시작합니다. GPU 인스턴스가
올바르게 프로비저닝된 경우 다음과 같은 내용이 표시됩니다:

```
CUDA available: True
GPU: NVIDIA A10G  ×4   (96 GB total)
```

대신 다음과 같이 표시되면:

```
ERROR: No GPU detected!
```

…워크스페이스가 아직 **CPU 인스턴스**에 있는 것입니다. 다음과 같이 해결하세요:
- 대시보드로 돌아가 → **M2 노드 → Instance Options → `ml.g5.12xlarge` 선택 →
  Apply & Restart**, 재시작을 기다린 후 **Open Workspace**를 다시 클릭하고
  셀을 다시 실행합니다.

M2가 성공하면 Cosmos Reason 모델을 다운로드하고(미리 캐시되어 있어 빠름), 샘플
클립에 캡션을 달고, `captions.json`을 워크스페이스에 기록합니다 — 이는 M3에
입력됩니다.

---

<a id="what-survives-an-instance-change"></a>
## 인스턴스 변경 시 무엇이 유지되나요?

매우 흔한 걱정입니다: *"CPU 인스턴스에서 M1을 끝냈습니다. M2를 위해 GPU
인스턴스로 전환하고 워크스페이스가 재시작되면 M1 결과를 잃게 되나요?"*

**아니요 — 작업 내용은 안전합니다.** 인스턴스를 변경하고 워크스페이스가 재시작될 때
정확히 어떤 일이 일어나는지는 다음과 같습니다:

| 항목 | 재시작 후 유지되나요? | 이유 |
|------|:---:|-----|
| **S3의 모듈 결과** (M1의 `m1/` 출력, M2의 `captions.json` 등) | ✅ **유지됨** | 각 노트북은 결과를 S3 워크스페이스에 업로드하고, 다음 모듈이 S3에서 이를 다운로드합니다. 이것이 데이터가 M1 → M2 → M3 …로 흐르는 방식입니다.|
| **홈 디렉터리** (`/home/sagemaker-user`: 노트북, 저장한 파일, 다운로드) | ✅ **유지됨** | 인스턴스 변경은 컴퓨팅 + 소프트웨어 이미지만 교체합니다. 스토리지 볼륨(EBS)은 재시작 동안 계속 연결된 상태로 유지됩니다. |
| **노트북 파일 자체** (M0–M12) | ✅ **유지됨** | 시작할 때마다 자동으로 다시 동기화됩니다. |
| **이전 커널의 메모리 내 상태** (Python 변수, 로드된 모델, `df = ...`) | ❌ **지워짐** | 커널은 새 인스턴스에서 새로운 프로세스로 시작됩니다. 이는 *모든* Jupyter 재시작에서 정상적인 동작입니다. |

### 실제로 이것이 의미하는 바

- **이 설계는 노트북의 메모리나 로컬 디스크가 아니라 S3를 통해 모듈 간에 데이터를
  의도적으로 전달합니다.** 따라서 모듈 사이에 인스턴스를 전환하는 것은 정상적이고
  예상된 워크플로의 일부이며 — 데이터 손실 위험이 아닙니다.
- **전환하기 전에**, 방금 끝낸 모듈이 실제로 **마지막 "S3 업로드" 셀**을
  실행했는지 확인하세요. *Run ▸ Run All Cells*(권장)를 사용했다면 이미
  실행되었습니다. M1이 출력을 기록했는지는 S3 워크스페이스에
  `m1/`이 나타나는지 확인하여 알 수 있습니다(M1의 마지막 셀이 S3 경로를 출력합니다).
- **전환한 후에는**, 다음 노트북을 열고 셀을 위에서부터 실행하세요. 각
  GPU 모듈의 초반 셀은 필요한 입력을 S3에서 **다시 다운로드**합니다(예: M2는
  M1의 `m1/` 출력과 캐시에서 Cosmos Reason 모델을 가져옵니다). 따라서 M1의
  메모리가 없는 새 커널이어도 전혀 문제가 없습니다.
- **자유롭게 오갈 수 있습니다.** GPU → CPU로 전환하거나(예: M4을 위해
  `ml.t3.medium`으로 복귀) 이후 다시 CPU → GPU로 전환해도 S3나 홈 디렉터리의
  내용은 아무것도 잃지 않습니다.

### 다시 해야 하는 한 가지

**저장하지 않은 메모리 내 결과**가 있었다면 — 예를 들어 셀에서 무언가를 계산했지만
파일이나 S3에 기록하지 않은 경우 — 그 값은 이전 커널의 메모리에만 존재했기 때문에
재시작 후 사라집니다. 셀을 다시 실행하여 재계산하세요. 파일에 기록되었거나 S3에
업로드된 것은 아무것도 영향받지 않습니다.

> **경험칙:** *파일 또는 S3 = 안전. 변수에만 존재 = 셀 다시 실행.*

---

## 5. GPU 인스턴스를 사용할 수 없는 경우 (용량 오류)

가끔 AWS의 해당 리전에서 `ml.g5.12xlarge` 용량이 일시적으로 부족할 수 있습니다.
실행 시 다음과 같이 표시될 수 있습니다:

```
EC2InsufficientCapacityError: Instance type 'ml.g5.12xlarge' is temporarily unavailable ...
```

해결 방법: **Instance Options**를 다시 열고 대체 인스턴스인 <strong>`ml.g6.12xlarge`</strong>를
선택하세요(4× NVIDIA L4, GPU당 24 GB / 합계 96 GB — `ml.g5.12xlarge`의 A10G와 GPU당 VRAM이
같습니다). `ml.g5.12xlarge`가 기본값인 모든 모듈(M2, M3, M5, M6, M8, M9 — 4× L4에서 모두
통과를 측정)의 요구 사항을 충족합니다. 이것마저 용량이 없으면 목록 아래쪽의 더 큰 4× / 8×
24 GB 타입도 같은 방식으로 동작합니다. Apply & Restart한 후 계속 진행하세요.

패널의 대체 목록에는 이미 각 모듈에 적합한 대체 인스턴스가 제공되므로, 바로 다음
항목을 선택하기만 하면 됩니다.

---

## 6. 비용 및 올바른 사용 태도

GPU 인스턴스는 시간 단위로 과금되며 **무료가 아닙니다**(`ml.g5.12xlarge` ≈
시간당 $7.09; `ml.g6.24xlarge` ≈ 시간당 $8.34; `ml.p4d.24xlarge` ≈ 시간당 $25.25). 다음 사항을 지켜주세요:

- GPU 모듈에서 CPU 모듈(M4, M11)로 이동할 때는 (Instance Options를 통해)
  **`ml.t3.medium`으로 다시 전환**하세요 — GPU 인스턴스를 유휴 상태로 두지 마세요.
- 워크스페이스는 **90분(`-c idle_timeout_minutes=<60..180>`로 변경 가능) 동안 활동이 없으면 자동으로 종료**되지만, 여기에
  의존하지 마세요 — 자리를 비울 때는 작업을 마치거나 일시 중지하세요. 다시 켜려면 아무
  모듈 노드 → **Instance Options** → **Apply & Restart**. 파일은 스페이스 볼륨에 있으므로
  종료되어도 그대로 남습니다.
- 워크숍 관리자는 활성 세션을 볼 수 있으며 문제가 생기면 도와줄 것입니다.

---

## 7. 모듈 흐름 한눈에 보기

```
M1 (explore, CPU)
   └─▶ M2 (caption, GPU) ─▶ M3 (curate, GPU) ─┬─▶ M5 (weather aug, GPU)
                                              ├─▶ M6 (scenario gen, GPU)
                                              ├─▶ M9 (VLA, GPU) ─▶ M10 (sim eval, CPU*)
                                              └─▶ M12 (distributed train, CPU† → m5.xlarge×2 job)
   M2 ─▶ M4 (search, CPU)
   nuScenes ─▶ M7 (3D recon, GPU‡)     M1 ─▶ M11 (orchestration, CPU)
```

\* M10의 실제 AlpaSim 폐루프 시뮬레이션은 GPU EC2 호스트에서 실행됩니다(관리자, 1회);
참가자 노트북은 CPU이며 그 실제 결과를 시각화합니다.

‡ M7은 **제한적으로 동작하는/선택적** 모듈입니다: GPU 확인 및 데이터 준비 셀은
실행되지만, 최종 splatfacto(3D Gaussian Splatting) 학습 셀은 현재 SageMaker
이미지에서 실행되지 않습니다 — 커스텀 CUDA 툴킷 이미지가 필요합니다. 마지막 셀이
실패해도 놀라지 마세요; 모듈의 나머지 부분은 여전히 3D 재구성 단계를 보여줍니다.

† M12의 노트북은 CPU이며 별도의 `ml.m5.xlarge` 인스턴스(gloo)에서 실행되는 실제
2노드 `torch.distributed` DDP 학습 작업을 제출한 뒤, 측정된 지표를 시각화합니다.
전체 SageMaker HyperPod은 별도의 인프라입니다 —
[HYPERPOD_M12.md](HYPERPOD_M12.md)를 참조하세요.

**M0**(개요, GPU 불필요)부터 시작한 다음, 다른 경로로 분기하기 전에 핵심 경로인
**M1 → M2 → M3**를 따르세요. 전체 아키텍처와 블로그 단계 → 모듈 매핑은
**M0_Pipeline_Overview.ipynb**를 참조하세요.

---

## 빠른 문제 해결

| 증상 | 해결 방법 |
|---|---|
| "Demo Mode" 배너 | 관리자가 보낸 전체 대시보드 링크(`?userId=&token=`)를 엽니다. |
| GPU 노트북에서 "No GPU detected" | CPU에 있는 것입니다 — Instance Options → GPU 인스턴스 → Apply & Restart → Open Workspace 다시 클릭. |
| `EC2InsufficientCapacityError` | Instance Options에서 `ml.g6.12xlarge`(또는 다음) 대체 인스턴스를 선택합니다. |
| 워크스페이스 링크 만료 / 빈 화면 | 대시보드에서 **Open Workspace**를 다시 클릭하여 새 링크를 받습니다. |
| 오른쪽 상단 버튼이 **Start Workspace** 일 때 | 워크스페이스가 멈춘 상태입니다 — 첫 로그인과 90분 유휴 종료 후에는 정상입니다. 클릭 → 인스턴스 확인 → **Apply & Restart** → **Open Workspace**가 나타나면 클릭. 파일은 스페이스 볼륨에 있어 종료되어도 남습니다. |
| JupyterLab이 아니라 SageMaker Studio 화면에 도착했을 때 | 대시보드로 돌아가 그쪽 버튼을 쓰세요. 어떤 인스턴스를 썼는지 비용 보고에 기록하는 경로라서 그것이 지원되는 방법입니다. Studio의 **Run space** / **Open JupyterLab**도 자기 워크스페이스에는 동작해야 하지만, 권한 오류가 나면 대시보드를 쓰세요. |
| 노트북에서 디스크 부족 | Instance Options → +50 GB / +200 GB → Apply. |
| M5 / M6 가 "GPU MEMORY IS ALREADY IN USE BY ANOTHER PROCESS" 로 멈춤 | **M2**나 **M8**을 실행한 뒤라면 정상입니다. 두 노트북은 7B 모델을 모든 GPU에 걸쳐 올리고 커널이 끝날 때까지 붙잡으며, M5/M6은 카드당 거의 전부가 필요합니다. 이제 중단 메시지가 메모리를 쥔 PID를 나열합니다. 해당 노트북을 열어 마지막 **Release the GPUs** 셀을 실행한 뒤 여기서 Run All Cells 하면 됩니다 — 커널 종료는 필요 없습니다. |
| 인스턴스 변경 후 노트북 파일 누락 | 재시작이 완료될 때까지 기다린 후 Open Workspace를 다시 클릭합니다(시작 시 노트북이 다시 동기화됨). |
| "인스턴스를 변경한 후 결과를 잃었나요?" | 아니요 — 결과는 S3에 있고 홈 디렉터리는 유지됩니다; 이전 커널의 메모리만 지워집니다. [인스턴스 변경 시 무엇이 유지되나요?](#what-survives-an-instance-change)를 참조하세요. 새 노트북을 위에서부터 다시 실행하세요. |
