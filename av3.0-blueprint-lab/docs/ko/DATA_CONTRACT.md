# AV 3.0 Blueprint Lab — 모듈 간 데이터 계약

12개 파이프라인 모듈(M1–M12)은 **오직 S3를 통해서만** 서로에게 데이터를 전달합니다 —
인메모리나 노트북 간 상태는 없습니다. 이 문서는 각 모듈이 읽고 쓰는
S3 키와 관련된 JSON 형태에 대한 권위 있는 기록으로, 한 노트북의
변경이 다운스트림 리더를 조용히 깨뜨리지 않도록 합니다.

> 2026-07 기준 노트북에 대해 검증됨(run-and-improve 하드닝 이후).
> 모듈의 출력 키를 변경한다면, 이 파일 **그리고** 다운스트림
> 리더를 같은 변경에서 함께 업데이트하세요.

## 1. 범위 & 버킷

| Env var | 기본값 | 담는 내용 |
|---|---|---|
| `USER_BUCKET` | `av30lab-user-workspace-{account_id}-{region}` | `users/{profile}/mN/` 아래의 사용자별 출력 |
| `SHARED_BUCKET` | `av30lab-shared-data-{account_id}-{region}` | nuScenes 소스, Cosmos/Alpamayo HF 캐시, M9 데모 `.pt`, M10 관리자 레퍼런스 번들, `notebook-templates/` |
| `USER_PROFILE` | (SageMaker 프로필 이름에서 JupyterLab LCC가 주입) | 사용자별 프리픽스 `{profile}`. **M4은 미설정 시 하드 페일**; 다른 모든 모듈은 `"default"`로 폴백. |

## 2. 모듈 엣지 그래프 (읽기 → 쓰기)

| 모듈 | 읽기 | 쓰기 | 비고 |
|---|---|---|---|
| **M1** Data Exploration | 공유 nuScenes-mini | `m1/manifest.json`, `m1/selected_scenes.json` | `selected_scenes.json` = 전체 nuScenes 장면 레코드(name + description); `cam_front_scenes`는 **항상** 기록됨 |
| **M2** Cosmos Reason captioning | `m1/manifest.json` + 공유 CAM_FRONT jpgs | `m2/captions.json` | 각 캡션 항목은 `scene` + `inference_time_s`를 가짐(M3은 `scene`으로 조인) |
| **M3** Cosmos Curator | `m1/manifest.json` **및** `m2/captions.json` | `m3/curated_captions.json`, `m3/curation_report.json`, `m3/clips/` | M12 트레이닝 계약은 `curated_captions` 아래의 평탄한 리스트 |
| **M4** OpenSearch search | `m2/captions.json`(**m3 아님**) | `m4/index_metadata.json`, `m4/embeddings.npy` | `"default"` 프로필을 거부하는 유일한 모듈 |
| **M5** Cosmos Transfer | `m1/manifest.json` cam_front + 공유 jpgs | `m5/*.mp4`, `m5/source/nuscenes_cam_front.mp4`, `m5/manifest.json` | `m5/source/` 클립은 M6에 필수적 |
| **M6** Cosmos Predict | **PRIMARY** `m5/source/` 클립; **FALLBACK** `m1/manifest.json` | `m6/*.mp4`, `m6/source/`, `m6/manifest.json` | 입력 엣지 2개 — M5의 클립을 선호, M1로 폴백 |
| **M7** Nerfstudio | 공유 nuScenes CAM_FRONT를 **직접** | `m7/reconstruction_metadata.json`, 렌더 | 합성 사인파 포즈(스모크 테스트); `splatfacto` 셀은 gsplat 빌드(`scripts/setup_gsplat_env.sh`)가 필요 |
| **M8** Cosmos Reason LoRA SFT | `m1/manifest.json` + 공유 nuScenes **어노테이션 테이블** | `m8/lora_adapter/`, `m8/training_log.json`, `m8/dataset.json`, `m8/loss_curve.png`, `m8/eval_samples.json` | 학습 타깃은 nuScenes **사람** 라벨(`scene.description`, `sample_annotation`→`instance`→`category`)이며, 의도적으로 `m2/captions.json`을 **쓰지 않습니다** — Cosmos Reason을 자기 출력으로 학습시키면 손실이 자기참조가 됩니다 |
| **M9** Alpamayo VLA | 공유 `hf-cache/alpamayo-demo/*.pt` | `m9/manifest.json`, 클립별 `_pred.npy`/`_gt.npy`/`_cot.txt`, `metrics.json` | `model` + `modes_run` 키는 M10 프로비넌스 |
| **M10** AlpaSim closed-loop | `m9/manifest.json`(**프로비넌스 전용**) + 사용자 자신의 `m10/aggregate/` **우선**, 없으면 공유 `m10-reference/` | (S3 출력 없음 — 인라인 시각화) | CPU 노트북; 실제 평가는 별도의 GPU EC2에서 실행 |
| **M11** Pipeline automation | `m1/`만(`selected_scenes.json` → `manifest.json` → 합성 폴백) | `m11/pipeline/`(**private stub namespace**), `m11/pipeline_execution.json`, `m11/pipeline_definition.json` | 리프(leaf); 자신의 `captions.json`/`curated_captions.json`를 `m11/`에 **만** 쓰며, 의도적으로 `m2/`/`m3/`에는 쓰지 않음 — 그래서 M3/M4/M12가 의존하는 진짜 것을 덮어쓸 수 없음 |
| **M12** HyperPod training | `m3/curated_captions.json` | `m12/input/…`, 모델 tarball, `m12/training_metadata.json` | M3가 없으면 합성 데이터셋으로 폴백 |

## 3. 키 스키마 (권위 있는 키 목록)

- **`m1/manifest.json`**: `scenes`, `num_samples`, `num_cam_front_frames`,
  `cam_front_files`(nuScenes 루트 상대 경로), `cam_front_scenes`,
  `source_bucket`, `source_prefix`
- **`m1/selected_scenes.json`**: `{name, description, ...}`의 리스트(M11이 읽음)
- **`m2/captions.json`**: `module`, `model`, `generated_at`, `num_captions`,
  `total_inference_time_s`, `avg_inference_time_s`, `prompt_template`,
  `captions[{frame_idx, scene, filename, caption, inference_time_s, timestamp}]`
- **`m3/curated_captions.json`**: `module`, `generated_at`, `curator`,
  `source_modules[]`, `curation_stats{...}`,
  `curated_captions[ <M2 item> + curation_verdict ]`
- **`m9/manifest.json`**: `module`, `profile`, `timestamp`, `model`, `license`,
  `modes_run`, `clips`, `results`(M10이 프로비넌스용으로 읽음)

## 4. 정규(canonical) 진행 모듈 id 맵

대시보드 진행 기능(B2)은 이 id들로 `moduleProgress`를 키잉합니다. 진실
공급원은 `scripts/av30_progress.py`이며 이는
`web/user/src/data/pipeline-config.ts`와 정확히 일치해야 합니다.

| 노트북 | `mark_complete()` id |
|---|---|
| M1_Data_Exploration | `m01-data-exploration` |
| M2_Cosmos_Reason_Captioning | `m02-cosmos-reason` |
| M3_Cosmos_Curator | `m03-cosmos-curator` |
| M4_OpenSearch_Semantic_Search | `m04-opensearch` |
| M5_Cosmos_Transfer_Augmentation | `m05-cosmos-transfer` |
| M6_Cosmos_Predict_Synthesis | `m06-cosmos-predict` |
| M7_Nerfstudio_3D_Reconstruction | `m07-nerfstudio` |
| M8_Cosmos_Reason_SFT | `m08-cosmos-sft` |
| M9_Alpamayo_VLA_Inference | `m09-alpamayo-vla` |
| M10_AlpaSim_ClosedLoop | `m10-alpasim` |
| M11_Pipeline_Automation | `m11-orchestration` |
| M12_HyperPod_Distributed_Training | `m12-hyperpod` |

각 노트북의 마지막 셀은 `mark_complete("<id>")`를 호출하며, 이는
`{moduleId, status:"completed"}`를 `X-Api-Key` 헤더와 함께
`{AV30_API_URL}/sessions/{profile}/progress`로 POST합니다. 이는 베스트 에포트이고
비치명적입니다 — 핑 실패가 모듈을 실패시키는 일은 없습니다. 백엔드(`update_progress`)는
짧은 하위 호환 id `m0`–`m12`도 여전히 받습니다.

## 5. 짚고 넘어갈 만한 뉘앙스

- **M6의 기본 입력은 M5의 클립**이지 M1이 아닙니다 — M6는 M5 소스 클립이
  없을 때만 M1로 폴백합니다.
- **M10은 참가자 자신의 AlpaSim 실행**(`users/{profile}/m10/aggregate/`)을 선호하고
  공유 관리자 레퍼런스(`m10-reference/`)로 폴백합니다.
- **M4은 M2를 읽지, M3를 읽지 않습니다** — 이는 원본 캡션에서 갈라진 병렬 검색 분기이지,
  큐레이션된 집합의 소비자가 아닙니다.
- **M11은 분기된 스텁 스키마를 private `m11/pipeline/` 네임스페이스에 씁니다** —
  `m2/`/`m3/`(M3/M4/M12가 의존)를 덮어쓰지 않기 위해서입니다.
- **M1의 `cam_front_scenes`는 항상 기록됩니다**; 일부 다운스트림 셀의
  `?`/`.get()` 가드는 오래된 매니페스트만을 위한 것입니다.
