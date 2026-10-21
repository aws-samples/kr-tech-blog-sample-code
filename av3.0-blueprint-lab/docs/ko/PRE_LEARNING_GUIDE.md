# AV 3.0 Blueprint Lab — 참가자 사전 학습 가이드

**워크숍 전에 읽어 보세요.** 이 문서는 실습 모듈이 이해될 수 있도록 랩 이면의
*개념*을 설명합니다. 단계별 클릭 실행 안내서가 **아닙니다** — 그것은
당일 사용하는 [PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md)입니다.

- ⏱️ **핵심 읽기(꼭 하세요): 약 45–60분.** 1–4절 + 처음 시작할 모듈.
- 📚 **선택적 심화 학습: 원하는 만큼.** 6절에 논문, 저장소, 문서 링크가 있습니다.
- 준비를 위해 무언가를 설치하거나 AWS/Hugging Face 계정을 보유할 **필요는
  없습니다** — 핵심 읽기는 개념적인 내용입니다. (관리자가 모든 것을 미리 캐시합니다.)

---

## 1. 큰 그림 — "AV 3.0 / Physical AI"란 무엇인가?

자율주행 개발은 세 가지 큰 시대를 거쳐 왔습니다:

- **AV 1.0** — 수작업 규칙 + 고전적 로보틱스. 롱테일 상황에 취약함.
- **AV 2.0** — 대규모 레이블링된 데이터셋 기반의 딥러닝. 더 나아졌지만 데이터에
  대한 요구가 크고 여전히 모듈식(별도의 인지 → 예측 → 계획 스택).
- **AV 3.0** — **엔드투엔드, 파운데이션 모델 기반**. 대규모 멀티모달
  모델(비전-언어, 월드 모델, 비전-언어-**액션** 정책)을 방대한 양의 실제 *및
  합성* 주행 데이터로 학습하고, 도로에 나가기 전에 시뮬레이션에서 평가합니다.
  "**Physical AI**"는 물리 세계에서 인지하고 행동하는 AI(로봇, AV)를 아우르는
  NVIDIA의 포괄 용어입니다.

**이 랩이 다루는 핵심 문제: 데이터.** 최신 AV 모델은 막대하고 *다양하며*
*잘 레이블링된* 주행 데이터를 필요로 합니다 — 실제 도로에서 안전하게 수집할 수
없는 드물고/위험한 상황(갑자기 뛰어나오는 아이, 화이트아웃, 역주행 차량)을
포함해서요. AV 3.0의 해답은 다음과 같은 **데이터 파이프라인**입니다:
1. 실제 센서 데이터에서 시작하여,
2. AI로 **캡셔닝하고 큐레이션**하며(검색 가능하고 고품질이 되도록),
3. 생성형 "월드 모델"로 더 많은 데이터 — 새로운 날씨, 새로운 시나리오 — 를
   **합성**하고,
4. 주행 **정책**을 학습시키고,
5. 차량에 적용하기 전에 **폐루프 시뮬레이션에서 평가**합니다.

이 랩은 바로 그 파이프라인을 AWS에서 NVIDIA의 오픈 모델을 사용하여 처음부터 끝까지
직접 실습해 보는 과정입니다. **여러분은 실제 파이프라인을 실행하게 됩니다**(장난감이
아닌) — 작은 데이터셋에서요.

**여기서 시작하세요:** 이 랩 전체가 구현하는 단 하나의 블로그 글 —
[Building an end-to-end Physical AI data pipeline for AV 3.0 on AWS with NVIDIA](https://aws.amazon.com/blogs/industries/building-an-end-to-end-physical-ai-data-pipeline-for-autonomous-vehicle-3-0-on-aws-with-nvidia/).
지금 한 번 읽어 보세요; 아래의 모든 내용은 이 글에 대한 지도입니다.

---

<a id="the-8-stage-pipeline"></a>
## 2. 8단계 파이프라인 (그리고 모듈이 어떻게 매핑되는가)

블로그는 **8단계** 파이프라인을 정의합니다. 이 랩은 각 단계를 하나 이상의
노트북 모듈(M1–M12)로 구현하며, **번호는 블로그의 단계 순서를 따릅니다**. 여기에
이를 확장하는 몇 가지 **보충** 모듈(M6, M11, M12)이
추가됩니다. 데이터는 **S3**를 통해 모듈 → 모듈로 흐릅니다(각 모듈은 이전 모듈의
출력 폴더를 읽고 자신의 출력을 기록합니다).

```
 real data          AI labeling            synthetic data          policy + eval
 ─────────          ───────────            ──────────────          ────────────
 nuScenes ─▶ M1 ─▶ M2 caption ─▶ M3 curate ─┬─▶ M5 weather aug   (Stage 5)
 (Stage 1-2 explore) (Stage 3)   (Stage 3)   ├─▶ M6 scenario gen (Stage 5)
                        │                     ├─▶ M9 VLA inference ─▶ M10 closed-loop
                        │                     │      (Stage 7)            eval (Stage 8)
                        │                     └─▶ M12 distributed training (ext)
                        └─▶ M4 semantic search (Stage 4)
 nuScenes annotations ─▶ M8 LoRA SFT (Stage 7)  ← human labels, NOT M2's captions
 nuScenes CAM ────────▶ M7 3D reconstruction (Stage 6)    M1 ─▶ M11 orchestration (ext)
```

| 단계 (블로그) | 모듈 | 한 줄 개념 |
|---|---|---|
| 1–2 데이터 수집 및 탐색 | **M1** | 원본 주행 데이터셋(nuScenes-mini)을 로드하고 살펴봅니다. |
| 3 캡셔닝 | **M2** | 비전-언어 모델이 각 클립에 대한 텍스트 설명을 작성합니다. |
| 3 큐레이션 | **M3** | 클립을 분할·트랜스코딩한 뒤 모션이 적은 클립(예: 신호에 정차)을 버립니다. M2 캡션은 자기 씬의 클립이 살아남은 것만 함께 넘어갑니다. *중복 제거도, 캡션 품질 점수도 하지 않습니다 — 아래 대체 표 참조.* |
| 4 검색 | **M4** | 클립을 임베딩으로 변환하여 *의미 기반으로* 검색할 수 있게 합니다("빗속의 좌회전 찾기"). |
| 5 증강 | **M5** | "월드 모델"이 다시 주행하지 않고 실제 클립을 새로운 **날씨/조명**으로 리스타일합니다. |
| 5 (확장) 시나리오 생성 | **M6** | 월드 모델이 프롬프트/시드로부터 **새로운 합성 주행 영상을 생성**합니다. |
| 6 뉴럴 재구성 | **M7** | 카메라 이미지로부터 3D 장면을 재구성합니다(NeRF / Gaussian Splatting). *(제한적으로 동작 — §5 참조.)* |
| 7 모델 학습 | **M8** | 주행 VLM을 nuScenes **사람 라벨**로 LoRA 파인튜닝합니다(M2의 캡션으로 학습하지 않습니다 — 그러면 순환이 됩니다). |
| 7 VLA 추론 | **M9** | 비전-언어-**액션** 모델이 주행 궤적 + 그 추론 과정을 예측합니다. |
| 8 폐루프 평가 | **M10** | 그 정책을 **시뮬레이터**에 넣고 점수를 매깁니다(충돌, 도로 이탈 등). |
| — 오케스트레이션 (확장) | **M11** | M1→M2→M3→M5를 하나의 자동화되고 반복 가능한 **SageMaker Pipeline**으로 연결합니다. |
| — 학습 확장 (확장) | **M12** | 분산 멀티노드 학습(HyperPod)의 *패턴*. |

> **기억해 둘 멘탈 모델:** *실제 데이터 → 레이블링 → 검색 & 정제 →
> 합성 생성으로 증대 → 정책 학습 → 시뮬레이션에서 검증.*

### 이 랩이 블로그를 대체한 지점

파이프라인은 엔드투엔드로 실제입니다 — 실제 NVIDIA 가중치, 실제 nuScenes 데이터, 실제
AWS 서비스. 다만 **워크숍 규모**로 돌아가며, 몇몇 단계는 블로그가 지정한 것 대신 대체물을
씁니다. 모듈 중간에 직접 발견하게 두지 않고 여기 모아 둡니다.

| 단계 | 블로그 | 이 랩 | 이유 |
|---|---|---|---|
| **1–2** 수집 + 품질 게이트 | 물리 매체를 **AWS Data Transfer Terminal**로 S3에 반입; **AWS Batch**가 채널/동기/손상 검증; ROS bag·MCAP·ASAM MDF4 컨테이너에서 센서 데이터 추출 | **M1**은 이미 추출된 nuScenes-mini 트리를 S3에서 읽어 탐색 | 물리 매체도, 추출할 컨테이너 파일도 없습니다 — nuScenes-mini는 jpg + json으로 배포됩니다. 여기서 수집이나 품질 게이트는 **수행되지 않습니다**. |
| **3** 큐레이션 | **NVIDIA Cosmos Curator**를 **SageMaker HyperPod + SLURM**에서: 분할 → 트랜스코딩 → **캡셔닝** → **임베딩** 4개 하위 단계를 하나의 통합 파이프라인으로 | **M3**은 **NeMo Curator**(이름이 비슷하지만 별개의 NVIDIA 프로젝트)로 분할 + 트랜스코딩 + 모션 필터만 수행하고 캡셔닝·임베딩은 끔. 캡셔닝은 **M2**, 임베딩은 **M4** | Cosmos Curator는 영구 GPU 클러스터 위의 Docker + SLURM이라 Studio 노트북에서 실행할 수 없습니다. 분할(fixed stride)과 트랜스코딩(H.264)은 블로그와 일치하고, 나머지 두 하위 단계는 별도 모듈로 옮겼습니다. |
| **3** 캡셔닝 | Curator 하위 단계로서의 **Cosmos Reason**(블로그는 `cosmos-reason2`를 링크) | **M2**가 **Cosmos-Reason1-7B**를 단독 실행 | Reason 1은 게이트가 없어 참가자가 라이선스 클릭도, Hugging Face 토큰도 필요 없습니다. |
| **3** 임베딩 | **Cosmos Embed** — 클립당 *비디오-텍스트 결합* 벡터 | **M4**는 캡션 **텍스트만** `all-MiniLM-L6-v2`(384차원)로 임베딩 | 텍스트 임베딩은 CPU에서 수 초면 끝납니다. 대가는 분명합니다: 검색이 영상이 *보여주는* 것이 아니라 캡션이 *말하는* 것에 매칭됩니다. |
| **4** 검색 | Path A **OpenSearch Service** + NVIDIA cuVS, 텍스트+벡터 **하이브리드** 질의 · Path B **Cosmos Dataset Search**를 **EKS**에서 | **M4**는 Path A를 택하되 OpenSearch **Serverless**에서 벡터 전용 k-NN | Serverless는 하루짜리 워크숍에 클러스터 사이징·패치가 필요 없습니다. Path B(EKS, 전용 UI, 데이터셋 조립 워크플로)는 범위 밖입니다. |
| **5** 증강 | **EC2 + Amazon DCV**. Cosmos Transfer가 *"약 65 GB의 GPU 메모리를 필요로 한다"*고 하여 블로그는 **G7e**(RTX PRO 6000 Blackwell, 96 GB)를 지목 | **M5**는 Studio 노트북에서 실행. 기본값 `ml.g5.12xlarge`는 **카드당 24 GB**라 샤딩하고 480p + 가드레일 OFF로 내려갑니다 | 24 GB 카드가 워크숍에서 쿼터를 안정적으로 확보할 수 있는 선입니다. **블로그가 지목한 바로 그 하드웨어**인 `ml.g7e.2xlarge`(96 GB 1장)는 쿼터가 있으면 선택할 수 있고, 기본값보다 *저렴*합니다. |
| **6** 재구성 | **NuRec** | **M7** Nerfstudio / gsplat | M7 헤더에 이미 명시. 최종 학습 셀은 제한적으로 동작합니다. |
| **7** 학습 | **Alpamayo** | **M8**이 nuScenes 사람 라벨로 Cosmos Reason을 LoRA SFT; **M9**는 NVIDIA 공개 체크포인트로 Alpamayo *추론* | Alpamayo에는 LoRA 경로가 없고, 전체 파인튜닝은 가중치+그래디언트+옵티마이저 상태로 약 123 GiB가 필요합니다. M8 헤더에 자세히 설명돼 있습니다. |
| **8** SiL 테스트 | **AlpaSim** | **M10**은 별도 GPU EC2 호스트에서 실행된 진짜 AlpaSim 결과를 시각화 | AlpaSim은 Docker Compose + gRPC라 Studio 노트북이 호스팅할 수 없습니다. |
| *전 구간* | HyperPod, AWS Batch, EKS, EC2 + DCV | 단일 SageMaker Studio 인스턴스 | 참가자·모듈당 인스턴스 하나가 워크숍이 프로비저닝·과금·정리할 수 있는 규모입니다. |

**대체가 *아닌* 것:** 모델 가중치는 NVIDIA의 실제 가중치이고, 데이터는 실제 nuScenes이며,
보이는 모든 출력은 실제로 계산된 것입니다. 결과가 *없는* 것이 아니라 *품질이 낮아진*
경우(M5/M6 해상도, M7 학습 셀)는 해당 모듈 헤더에 명시돼 있습니다.

---

## 3. 시작하기 전에 이해해야 할 핵심 개념

이것들을 완벽하게 마스터할 필요는 없습니다 — 노트북에서 사용될 때 그 용어를
알아보기만 하면 됩니다.

### 3.1 파운데이션 모델 & NVIDIA Cosmos 제품군
**파운데이션 모델**은 광범위한 데이터로 사전 학습되어 다양한 작업에 적응시킬 수
있는 대규모 모델입니다. 이 랩은 NVIDIA의 **Cosmos** *월드 파운데이션 모델* 제품군과
**Alpamayo** 주행 정책을 사용합니다:

| 모델 (사용 위치) | 유형 | 여기서의 역할 |
|---|---|---|
| **Cosmos Reason 1** (M2) | 비전-언어 모델(VLM) | 비디오 클립에 대해 "추론"하고 캡션을 답니다. |
| **Cosmos Transfer 2.5** (M5) | 월드 모델(video→video) | 실제 클립을 새로운 날씨/조건으로 리스타일합니다. |
| **Cosmos Predict 2.5** (M6) | 월드 모델(생성) | 새로운 합성 주행 영상을 생성합니다. |
| **Alpamayo 1.5** (M9, M10) | 비전-언어-**액션**(VLA) | ego 궤적 + 추론 과정을 예측합니다; "운전자"입니다. |
| **Cosmos Reason 2** (숨겨짐, M9/M10) | VLM 백본 | Alpamayo의 내부 비전 백본. |

- **VLM vs. VLA:** VLM은 *텍스트/이해*를 출력하고, **VLA**는 추가로 *액션*(여기서는
  미래 궤적)을 출력합니다. VLA가 AV 3.0의 "엔드투엔드 운전자"입니다.
- **월드 모델:** 장면의 *미래 프레임*을 예측/생성하는 생성형 모델 — 합성
  데이터(M5/M6)의 근간이 되는 엔진입니다.
- **라이선스 참고:** Alpamayo(M9/M10)는 **비상업용**(연구/평가 전용)입니다.
  직접 다운로드하지는 않지만, M9/M10을 실행하는 것은 해당 라이선스에 동의하는
  것입니다.

### 3.2 데이터셋 — nuScenes
[**nuScenes**](https://www.nuscenes.org/)는 널리 사용되는 오픈 AV 데이터셋(Motional)입니다:
멀티 카메라 + LiDAR + 레이더 주행 장면과 풍부한 어노테이션을 포함합니다. 이 랩은
모든 것이 저렴하게 실행되도록 **nuScenes-mini**(작은 하위 집합)를 사용합니다.
**scene**은 약 20초 길이의 클립이며; **CAM_FRONT**는 M5/M7이 사용하는 전방 카메라
스트림입니다.

### 3.3 합성 데이터 & 왜 중요한가
실제 데이터는 롱테일을 안전하게 다룰 수 없습니다. **증강**(M5: 같은 장면, 새로운
날씨)과 **시나리오 생성**(M6: 완전히 새로운 합성 클립)은 다시 주행하지 않고도
다양성을 배가시킵니다. 이것이 AV 3.0 데이터 전략의 핵심입니다.

### 3.4 임베딩 & 시맨틱 검색 (M4)
**임베딩**은 클립/캡션을 벡터로 변환하여 *유사한 의미 → 가까운 벡터*가 되도록
합니다. 이를 벡터 인덱스(여기서는 **Amazon OpenSearch Serverless**)에 저장하면
파일명 대신 의미로 검색할 수 있습니다("밤, 보행자, 횡단보도") — **k-NN**이 가장
가까운 벡터를 찾습니다.

### 3.5 폐루프 vs. 개루프 평가 (M9 → M10)
- **개루프(M9):** 기록된 데이터를 정책에 입력하고, 정책이 예측한 궤적을 실제로
  일어난 일과 비교합니다(지표: minADE — 평균 궤적 오차).
- **폐루프(M10):** 정책을 *시뮬레이터*에 넣어, 정책 자신의 행동이 다음에 보게 될
  것을 바꾸도록 합니다 — 더 현실적인 테스트입니다. 지표: 충돌, 도로 이탈, 정답
  경로와의 거리. 여기서 사용하는 시뮬레이터는 **AlpaSim**입니다.

### 3.6 분산 학습 (M12) & 오케스트레이션 (M11) — "프로덕션" 개념
- **분산 학습(M12):** 실제 모델은 하나의 GPU에 담기에는 너무 크므로, 학습을 여러
  노드로 나누어 그래디언트를 동기화합니다(**DDP** / `torch.distributed`).
  **SageMaker HyperPod**은 이를 대규모로 수행하기 위한 AWS의 관리형
  클러스터입니다. *(랩에서는 M12가 작은 CPU 인스턴스에서 멀티노드 패턴을 시연합니다
  — §5 참조.)*
- **오케스트레이션(M11):** 노트북을 수동으로 실행하는 대신, 단계를 **SageMaker
  Pipeline** — 각 단계가 자체 컴퓨팅을 시작/중지하고 계보(lineage)가 추적되는
  반복 가능하고 매개변수화된 DAG(방향성 비순환 그래프) — 으로 정의합니다.

### 3.7 여러분이 다루게 될 AWS 플랫폼
- **Amazon SageMaker Studio / JupyterLab** — 브라우저 안의 노트북 환경.
- **인스턴스 & GPU** — 가벼운 작업에는 CPU(`ml.t3.medium`); 모델에는
  GPU(`ml.g5.*`, `ml.p4d.*`). 대시보드에서 인스턴스를 선택하면 플랫폼이 맞는 GPU
  소프트웨어 이미지를 로드합니다. **GPU 시간은 실제 비용이 듭니다** — GPU 모듈
  사이에는 CPU로 다시 전환하세요.
- **S3** — 모든 모듈이 입력을 읽고 출력을 기록하는 곳(이것이 모듈 간에 데이터가
  흐르는 방식이며, 인스턴스 변경 후에도 결과가 유지되는 이유입니다).

---

## 4. 실제로 할 줄 알아야 하는 것 (역량 점검)

다음에 익숙하다면 이 랩은 접근하기 쉽습니다:
- **기본 Python & Jupyter** — 셀을 위에서 아래로 실행하고, 출력/오류를 읽기.
  (코드를 많이 작성하는 것이 아니라 *실행*합니다.)
- **노트북 읽기** — 코드 셀 사이의 마크다운 설명을 따라가기.
- **아주 기본적인 ML 어휘** — 모델, 추론, 학습, 데이터셋, GPU.

필요하지 **않은** 것: 딥러닝 수학, CUDA, AWS 관리, 또는 사전 AV 경험. AWS 관련
사항(인스턴스 선택, 워크스페이스 열기)은 모두 운영 안내서인
[PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md)에 있습니다.

**Jupyter가 처음이신가요?** 10분짜리
[JupyterLab 인터페이스 투어](https://jupyterlab.readthedocs.io/en/stable/user/interface.html)를
훑어보세요 — "셀 실행 = Shift+Enter"와 "Run ▸ Run All Cells"를 아는 정도면
충분합니다.

---

## 5. 당일 당황하지 않도록 알아둘 두 가지

- **M10과 M12 노트북은 CPU입니다** GPU 규모의 아이디어를 다루더라도 말이죠. M10은
  관리자가 GPU 호스트에서 실행한 폐루프 시뮬레이션을 *시각화*하고; M12는 별도의
  관리형 인스턴스에서 실행되는 실제 2노드 학습 작업을 *제출*합니다. 이는
  의도된 것입니다 — 노트북이 오케스트레이션하고; 무거운 컴퓨팅은 다른 곳에서
  일어납니다.
- **M7(3D 재구성)은 제한적으로 동작합니다.** GPU 확인 및 데이터 준비 셀은
  실행되어 해당 단계를 보여주지만, 최종 3D 학습 셀은 현재 워크숍 이미지에서
  실행되지 **않습니다**(CUDA 빌드 툴링의 공백). M7은 선택/데모 모듈로 취급하세요;
  마지막 셀에서 오류가 나도 당황하지 마세요.

당일 권장 경로: **M0(개요) → M1 → M2 → M3**, 그다음 관심 있는 곳으로 분기하세요(M5/M6
합성 데이터, M9/M10 정책 + 시뮬레이션, M4 검색, M12/M11 프로덕션 패턴).

---

## 6. 선택적 심화 학습 (관심사별)

더 깊이 이해하고 싶은 내용에 해당하는 항목을 고르세요. 워크숍에 이 중 어느 것도
필수는 아닙니다.

### 파이프라인 & 플랫폼
- 📄 **AWS + NVIDIA AV 3.0 블로그** (이 랩 전체의 출처) —
  [aws.amazon.com/blogs/industries/…av-3-0…](https://aws.amazon.com/blogs/industries/building-an-end-to-end-physical-ai-data-pipeline-for-autonomous-vehicle-3-0-on-aws-with-nvidia/)
- 📘 **Amazon SageMaker Studio** 문서 —
  [docs.aws.amazon.com/sagemaker/latest/dg/studio.html](https://docs.aws.amazon.com/sagemaker/latest/dg/studio.html)
- 📘 **SageMaker Pipelines** (M11) —
  [docs.aws.amazon.com/sagemaker/latest/dg/pipelines.html](https://docs.aws.amazon.com/sagemaker/latest/dg/pipelines.html)
- 📘 **SageMaker HyperPod** (M12) —
  [docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod.html](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod.html)

### 모델 (NVIDIA Cosmos & Alpamayo)
- 🧩 **NVIDIA Cosmos** — 모델의 본거지, 현재는 **Cosmos 3**:
  [github.com/NVIDIA/Cosmos](https://github.com/NVIDIA/Cosmos)
- 🧩 **Cosmos Cookbook** — 이 랩이 참고하는 포스트 트레이닝 레시피(**별도** 리포지토리이며,
  Cosmos 3 출시 이후 유지보수 전용):
  [github.com/nvidia-cosmos/cosmos-cookbook](https://github.com/nvidia-cosmos/cosmos-cookbook)
  · 문서 사이트: [nvidia-cosmos.github.io/cosmos-cookbook](https://nvidia-cosmos.github.io/cosmos-cookbook/)
- 🧩 **Cosmos Reason 1** (캡셔닝, M2) —
  [huggingface.co/nvidia/Cosmos-Reason1-7B](https://huggingface.co/nvidia/Cosmos-Reason1-7B)
- 🧩 **Cosmos Transfer 2.5** (날씨 증강, M5) —
  [huggingface.co/nvidia/Cosmos-Transfer2.5-2B](https://huggingface.co/nvidia/Cosmos-Transfer2.5-2B)
- 🧩 **Cosmos Predict 2.5** (시나리오 생성, M6) —
  [huggingface.co/nvidia/Cosmos-Predict2.5-2B](https://huggingface.co/nvidia/Cosmos-Predict2.5-2B)
- 🧩 **Alpamayo 1.5** (VLA 정책, M9/M10) —
  [huggingface.co/nvidia/Alpamayo-1.5-10B](https://huggingface.co/nvidia/Alpamayo-1.5-10B)
  (비상업용)

### 데이터, 시뮬레이션, 재구성
- 🚗 **nuScenes** 데이터셋 — [nuscenes.org](https://www.nuscenes.org/)
- 🕹️ **AlpaSim** 시뮬레이터 (M10) — [github.com/NVlabs/alpasim](https://github.com/NVlabs/alpasim)
- 🧊 **Nerfstudio** (M7, 3D 재구성) — [docs.nerf.studio](https://docs.nerf.studio/)
- 🔎 **Amazon OpenSearch Serverless** 벡터 검색 (M4) —
  [docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless.html)

### 용어가 처음이었다면, 개념 설명
- **파운데이션 / 월드 모델**, **VLM**, **VLA** — 위의 Cosmos 및 Alpamayo 모델
  카드를 참조하세요(각각 그 작업을 설명합니다).
- **분산 데이터 병렬 학습(DDP)** — PyTorch
  [Distributed Overview](https://docs.pytorch.org/tutorials/beginner/dist_overview.html).
- **벡터 임베딩 & k-NN 검색** — 위의 OpenSearch 벡터 검색 가이드.

### 가장 깊은 심화: 이 저장소의 모듈 문서
어려운 각 모듈에는 정확히 어떻게 실행되고 왜 그런지 설명하는 엔지니어링 문서가
있습니다:
[COSMOS_M5_M6.md](COSMOS_M5_M6.md) · [ALPAMAYO_M9.md](ALPAMAYO_M9.md) ·
[ALPASIM_M10.md](ALPASIM_M10.md) · [HYPERPOD_M12.md](HYPERPOD_M12.md) ·
[PIPELINE_M11.md](PIPELINE_M11.md). 이 문서들은 모듈을 실행해 보고 내부 동작이
궁금할 때 *그 후에* 읽으세요.

---

## 7. "준비됐나요?" 체크리스트

1–3절을 바탕으로 다음 질문에 답할 수 있다면 워크숍 준비가 된 것입니다:

- [ ] 한 문장으로, AV 3.0 데이터 파이프라인은 *무엇을 위한* 것인가요?
- [ ] 다섯 단계를 말해 보세요: 실제 데이터 → ? → ? → ? → ?
- [ ] **VLM**(M2)과 **VLA**(M9)의 차이는 무엇인가요?
- [ ] 이 랩은 왜 실제 클립만 사용하지 않고 **합성 데이터를 생성**(M5/M6)하나요?
- [ ] **개루프**(M9)와 **폐루프**(M10) 평가의 차이는 무엇인가요?
- [ ] 모듈은 왜 메모리가 아닌 **S3**를 통해 데이터를 전달하나요?
- [ ] 어떤 모듈이 **제한적으로 동작**하며, 무엇을 예상해야 하나요? *(M7 — 학습 셀이 실행되지 않음.)*

질문이 모호하게 느껴진다면 §3에서 해당 개념을(또는 §1의 블로그를) 다시
훑어보세요. 그것이 필요한 준비의 전부입니다 — 당일
[PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md)에서 뵙겠습니다.
