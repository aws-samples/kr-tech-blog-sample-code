# SageMaker Pipelines (M11) — 실제 오케스트레이션 데모, 설계상 CPU

**상태:** M11은 **실제 SageMaker Pipeline을 정의하고 실행합니다** — 3단계 종속성
DAG(Caption → Curate → Augment)의 `upsert()` + `start()`를 완료까지 폴링하고,
실행을 S3에 기록합니다. 정의 전용 데모가 아닙니다. 단계 스크립트는 M1의 장면
메타데이터에 대한 순수 Python이므로, 단계들은 **CPU**(`ml.m5.xlarge`)에서
실행됩니다; 교육 요점은 컴퓨팅이 아니라 **오케스트레이션 패턴**입니다.

## M11이 무엇이었고, 이제 무엇인가

M12처럼, M11은 **환각된 API 실패가 아니었습니다** — 모든 임포트와 클래스
(`Pipeline`, `ProcessingStep`, `PipelineSession`, `ScriptProcessor`)가 실제
SageMaker Python SDK **v2**입니다. 그것의 문제는 M12가 겪은 것과 같은 계열에,
몇 가지 자체 문제가 더해졌습니다:

| 배포된 M11 | 수정된 M11 |
|---|---|
| `from sagemaker import Session`(v2 최상위) → SDK-v3 커널에서 실패 | cell-1이 v2를 고정함(`>=2.257.2,<3`) + 자동 커널 재시작(M12에서) |
| Step1이 `INPUT_DIR/*.jpg`를 glob했지만, M1은 `m1/`에 JSON만 씀 → 캡션 0개 | Step1이 M1의 `selected_scenes.json`(실제 장면 이름 + 설명)을 읽음 → 근거 있는 캡션 |
| 3개 단계가 `ml.g5.12xlarge`/`g5.xlarge`(GPU)를 요청함 — 여기서 처리 할당량은 0 | CPU `ml.m5.xlarge`(처리 할당량 이용 가능); 스크립트가 순수 Python이라 GPU가 아무것도 추가하지 않음 |
| GPU `pytorch-training` 이미지 | `image_uris.retrieve("sklearn", …)`를 통한 CPU sklearn 컨테이너 — **`image_scope` 없음**(sklearn에는 `processing` 스코프가 없음; 전달하면 `ValueError: Unsupported image scope` 발생) |
| 실행 역할에 `CreatePipeline`/`StartPipelineExecution`/`CreateProcessingJob`이 없었음 | CDK 실행 역할에 `SageMakerPipelines`(pipeline/av30-*) + `SageMakerProcessingJobs`(processing-job/*)를 추가함 |
| SDK 업로드(단계 코드, 파이프라인 정의)가 기본적으로 `sagemaker-<region>-<account>` 루트로 감 — 역할의 `users/*` 쓰기 범위 밖 → AccessDenied | `Session`/`PipelineSession(default_bucket=USER_BUCKET, default_bucket_prefix=users/<profile>/m11)` |
| 비용 셀이 GPU 요율을 하드코딩함 | `execution.list_steps()`에서 실제 단계별 소요 시간 + CPU 요율; GPU는 개념적 프로덕션으로 표시됨 |

## 왜 CPU인가(그리고 왜 그것이 올바른 선택인가)

세 개의 단계 스크립트는 **모델 추론을 하지 않습니다** — Step1은 M1의 장면
`description` 문자열에서 캡션을 빌드하고, Step2는 키워드 점수 필터 + md5 중복
제거이며, Step3은 템플릿 문자열 증강입니다. 그중 어느 것도 GPU를 사용하지
않습니다. 따라서 단계들을 GPU에서 실행하는 것은 순전히 낭비일 것입니다(그리고
이 계정에서 g5 *처리* 할당량은 어차피 0입니다). **M11이 가르치는 가치는
오케스트레이션**입니다 — 재현 가능한 종속성 DAG, 자동으로 시작/정지하는
단계별 인스턴스, 그리고 완전한 계보(lineage) — 그리고 그것은 단계가 CPU에서
실행되든 GPU에서 실행되든 바이트 단위로 동일합니다. 프로덕션에서는 캡셔닝
단계가 실제 VLM(예: Cosmos Reason)을 실행하는 GPU 이미지로 교체될 것입니다;
단계별 컴퓨팅만 바뀌고, 파이프라인은 바뀌지 않습니다.

## M1 → M11 데이터 연결(실제)

Step1은 `s3://<user-workspace>/users/<profile>/m1/`을 마운트하고
`selected_scenes.json`을 읽습니다 — M1이 선택한 실제 nuScenes 장면들로, 각각
`name`(예: `scene-0061`)과 사람이 읽을 수 있는 `description`(예: "Parked truck,
construction, intersection, turn left, following...")을 가집니다. 캡션은 그
실제 설명에 근거하므로, 파이프라인은 개수를 지어내는 대신 진짜 상류 출력을
소비합니다. (M1은 이미지 파일을 `m1/`으로 복사하지 않습니다; 장면 메타데이터를
기록하고 공유 nuScenes 데이터셋을 가리킵니다 — 따라서 메타데이터가 소비할
올바른 대상입니다.)

## M11을 위해 추가된 IAM(CDK, 최소 권한)

`infra/av30_constructs/sagemaker.py`에서, SageMaker 실행 역할에 추가됨:
- `SageMakerPipelines` — `CreatePipeline`/`UpdatePipeline`/`StartPipelineExecution`/
  `Describe*`/`ListPipelineExecutionSteps`/…, `pipeline/av30-*`로 범위 지정됨.
- `SageMakerProcessingJobs` — `processing-job/*`에서
  `CreateProcessingJob`/`DescribeProcessingJob`/`StopProcessingJob`/`AddTags`(SDK가
  처리 작업 이름을 자동 생성하므로, 리소스를 프리픽스로 범위 지정할 수 없음).
- `iam:PassRole` — M12를 위해 추가된 자신 전용,
  `PassedToService=sagemaker.amazonaws.com` 구문을 재사용함; ProcessingStep들이
  이 역할을 그들의 컨테이너에 전달함.

## 드러난 버그들(M12 미러링 + 파이프라인 특유)

M12와 동일한 v2/v3 SDK 체인(#1 v3 커널, #2 인메모리 혼합 / 커널 재시작), 더하기:
- **Pipeline/Processing IAM** — M12는 학습 작업 권한만 추가했음; M11은 위의
  Pipeline + Processing 세트가 필요함(라이브 실행 역할
  `av30lab-sagemaker-execution-role`에서 배포 & 검증됨).
- **업로드 범위** — 모든 SDK 업로드가 `users/<profile>/m11/` 아래에 오도록
  `default_bucket_prefix`(실행 역할이 쓸 수 있는 유일한 경로). 고정된 SDK
  2.257.3에서 `Session`과 `PipelineSession` 둘 다에 존재함을 확인함.
- **GPU 할당량 0** — 단계들을 CPU로 옮김(M12가 CPU를 사용하는 것과 같은 이유).
- **빈 입력** — 없는 `*.jpg`가 아니라 M1의 `selected_scenes.json`을 소비함.
- **`image_scope="processing"` 걸림돌(사전 실행 감사에서 발견됨)** — cell-3이
  `image_uris.retrieve(framework="sklearn", …, image_scope="processing")`으로
  단계 이미지를 빌드했는데, 이는 `ValueError: Unsupported image scope: processing`을
  발생시킴(sklearn의 레지스트리에는 `inference`/`training`/`inference_graviton`만
  있음). 그것은 *모든* 실행에서 cell-3의 첫 줄에서 실패했음 — 어떤 파이프라인이
  정의되기도 전이라 과금은 없지만, 하드 데드스톱. 수정: `image_scope`를 생략함;
  반환된 `…/sagemaker-scikit-learn:1.2-1-cpu-py3`이 올바른 CPU 이미지임(이것이
  `SKLearnProcessor`가 내부적으로 해석하는 방식). 고정된 SDK를 격리된 venv에
  설치하고 정확한 호출을 재현하여 잡았으므로, 어떤 과금된 단계도 이에 부딪히지
  않았음.
- **실제 M2/M3 모듈과의 출력 네임스페이스 충돌(사전 실행 감사에서 발견됨)** —
  단계들이 원래 `users/<profile>/m2/captions.json`과
  `…/m3/curated_captions.json`에 썼음 — 실제 M2/M3 모듈이 생성하는 *정확한 키와
  파일명*이지만, 호환되지 않는 데모 스키마(캡션별 `filename` 없음, 최상위
  `model` 없음)로. M11을 실행하면 참가자의 진짜 M2/M3 출력을 조용히 덮어쓰고,
  나중에 **M4**(`m2_output["model"]`, `cap["filename"]`) 또는
  **M3**(`captions[0]["filename"]`)를 재실행하면 `KeyError`로 크래시했을 것.
  M2/M3/M4 노트북 소스에 대해 검증함. 수정: 세 단계 출력을 모두 **M11 전용
  네임스페이스** `users/<profile>/m11/pipeline/stepN_*/`로 라우팅함(Step 1은
  여전히 실제 `m1/`을 읽기 전용으로 읽음). DAG/종속성/계보는 변경되지 않음;
  M11은 이제 자체 완결적이며 다른 모듈의 데이터를 오염시킬 수 없음. (실제 M1
  데이터에 대해 전체 3단계 DAG를 로컬에서 재실행하여 확인함: 3→3→3→9, 그리고
  m2/m3/m4에 아무것도 쓰이지 않음.)

## 검증된 실행

**관리형 실행 검증됨(2026-07-14, Studio Run-All, 참가자 프로필 `ky-5-34x1bx`).**
실제 SageMaker Pipeline이 CPU에서 upsert되고 엔드투엔드로 실행됨:

```
execution: av30-data-pipeline-ky-5-34x1bx/execution/3p1jfdpcp0ga  → Succeeded
  AV-Captioning       Succeeded  154s   (read real m1/selected_scenes.json)
  Data-Curation       Succeeded  153s
  Data-Augmentation   Succeeded  303s
  step compute total: 610s → ~$0.039 @ ml.m5.xlarge; wall time 634s
```

실행 후 라이브 S3에 대해 확인됨:
- **실제 M1 → M11 연결:** 9개의 최종 캡션이 M1의 실제 nuScenes 장면 설명(truck /
  construction / cyclist / crosswalk)에 근거함, 9/9 — 합성이 아님.
- **출력 격리됨:** 단계 출력이 `users/ky-5-34x1bx/m11/pipeline/step{1,2,3}_*/`
  아래에만 안착함; 실행 기록은 `m11/pipeline_execution.json`(상태 Succeeded, 3/3
  단계) + `m11/pipeline_definition.json`에. SDK 코드 업로드는 `users/…/m11/` 내부에
  머물렀음(AccessDenied 없음 — `default_bucket_prefix` 작동).
- **충돌 없음:** 실제 `m2/captions.json`(22649 B)과
  `m3/curated_captions.json`(24767 B)은 **손대지 않은 채로** 남음 — 실제
  환경에서 검증된 전용 네임스페이스 수정(버그 #4).

두 사전 실행 감사 걸림돌(`image_scope="processing"` ValueError; m2/m3 출력
충돌)은 이 실행 *전에* 수정되었으므로, 예방 가능한 실패에 낭비된 과금 단계
없이 첫 관리형 실행에서 성공했습니다.
