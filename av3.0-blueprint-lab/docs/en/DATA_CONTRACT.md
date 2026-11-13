# AV 3.0 Blueprint Lab — Cross-Module Data Contract

The 12 pipeline modules (M1–M12) pass data to each other **only through S3** — no
in-memory or cross-notebook state. This document is the authoritative record of
which S3 keys each module reads and writes, and the JSON shapes involved, so a
change in one notebook doesn't silently break a downstream reader.

> Verified against the notebooks as of 2026-07 (post run-and-improve hardening).
> If you change a module's output keys, update this file **and** the downstream
> reader in the same change.

## 1. Scope & buckets

| Env var | Default | Holds |
|---|---|---|
| `USER_BUCKET` | `av30lab-user-workspace-{account_id}-{region}` | per-user outputs under `users/{profile}/mN/` |
| `SHARED_BUCKET` | `av30lab-shared-data-{account_id}-{region}` | nuScenes source, Cosmos/Alpamayo HF caches, M9 demo `.pt`, M10 admin reference bundle, `notebook-templates/` |
| `USER_PROFILE` | (injected by the JupyterLab LCC from the SageMaker profile name) | the per-user prefix `{profile}`. **M4 hard-fails if unset**; all other modules fall back to `"default"`. |

## 2. Module edge graph (reads → writes)

| Module | Reads | Writes | Notes |
|---|---|---|---|
| **M1** Data Exploration | shared nuScenes-mini | `m1/manifest.json`, `m1/selected_scenes.json` | `selected_scenes.json` = full nuScenes scene records (name + description); `cam_front_scenes` is **always** written |
| **M2** Cosmos Reason captioning | `m1/manifest.json` + shared CAM_FRONT jpgs | `m2/captions.json` | each caption item carries `scene` + `inference_time_s` (M3 joins on `scene`) |
| **M3** Cosmos Curator | `m1/manifest.json` **and** `m2/captions.json` | `m3/curated_captions.json`, `m3/curation_report.json`, `m3/clips/` | the M12 training contract is the flat list under `curated_captions` |
| **M4** OpenSearch search | `m2/captions.json` (**NOT m3**) | `m4/index_metadata.json`, `m4/embeddings.npy` | the only module that refuses a `"default"` profile |
| **M5** Cosmos Transfer | `m1/manifest.json` cam_front + shared jpgs | `m5/*.mp4`, `m5/source/nuscenes_cam_front.mp4`, `m5/manifest.json` | `m5/source/` clip is load-bearing for M6 |
| **M6** Cosmos Predict | **PRIMARY** `m5/source/` clip; **FALLBACK** `m1/manifest.json` | `m6/*.mp4`, `m6/source/`, `m6/manifest.json` | two input edges — prefer M5's clip, fall back to M1 |
| **M7** Nerfstudio | shared nuScenes CAM_FRONT **directly** | `m7/reconstruction_metadata.json`, renders | synthetic sin-wave poses (smoke test); the `splatfacto` cell needs the gsplat build (`scripts/setup_gsplat_env.sh`) |
| **M8** Cosmos Reason LoRA SFT | `m1/manifest.json` + shared nuScenes **annotation tables** | `m8/lora_adapter/`, `m8/training_log.json`, `m8/dataset.json`, `m8/loss_curve.png`, `m8/eval_samples.json` | targets are nuScenes HUMAN labels (`scene.description`, `sample_annotation`→`instance`→`category`), deliberately **NOT** `m2/captions.json` — training Cosmos Reason on its own output would make the loss self-referential |
| **M9** Alpamayo VLA | shared `hf-cache/alpamayo-demo/*.pt` | `m9/manifest.json`, per-clip `_pred.npy`/`_gt.npy`/`_cot.txt`, `metrics.json` | `model` + `modes_run` keys are M10 provenance |
| **M10** AlpaSim closed-loop | `m9/manifest.json` (**provenance only**) + user's own `m10/aggregate/` **preferred**, else shared `m10-reference/` | (no S3 output — inline viz) | CPU notebook; the real eval runs on a separate GPU EC2 |
| **M11** Pipeline automation | `m1/` only (`selected_scenes.json` → `manifest.json` → synthetic fallback) | `m11/pipeline/` (**private stub namespace**), `m11/pipeline_execution.json`, `m11/pipeline_definition.json` | leaf; writes its own `captions.json`/`curated_captions.json` into `m11/` **only**, deliberately NOT `m2/`/`m3/`, so it can't clobber the real ones M3/M4/M12 depend on |
| **M12** HyperPod training | `m3/curated_captions.json` | `m12/input/…`, model tarball, `m12/training_metadata.json` | falls back to a synthetic dataset if M3 absent |

## 3. Key schemas (authoritative key lists)

- **`m1/manifest.json`**: `scenes`, `num_samples`, `num_cam_front_frames`,
  `cam_front_files` (nuScenes-root-relative paths), `cam_front_scenes`,
  `source_bucket`, `source_prefix`
- **`m1/selected_scenes.json`**: list of `{name, description, ...}` (read by M11)
- **`m2/captions.json`**: `module`, `model`, `generated_at`, `num_captions`,
  `total_inference_time_s`, `avg_inference_time_s`, `prompt_template`,
  `captions[{frame_idx, scene, filename, caption, inference_time_s, timestamp}]`
- **`m3/curated_captions.json`**: `module`, `generated_at`, `curator`,
  `source_modules[]`, `curation_stats{...}`,
  `curated_captions[ <M2 item> + curation_verdict ]`
- **`m9/manifest.json`**: `module`, `profile`, `timestamp`, `model`, `license`,
  `modes_run`, `clips`, `results` (read by M10 for provenance)

## 4. Canonical progress module-id map

The dashboard progress feature (B2) keys `moduleProgress` on these ids. The
source of truth is `scripts/av30_progress.py` and it must match
`web/user/src/data/pipeline-config.ts` exactly.

| Notebook | `mark_complete()` id |
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

Each notebook's final cell calls `mark_complete("<id>")`, which POSTs
`{moduleId, status:"completed"}` to `{AV30_API_URL}/sessions/{profile}/progress`
with the `X-Api-Key` header. It is best-effort and non-fatal — a failed ping
never fails the module. The backend (`update_progress`) also still accepts the
short back-compat ids `m0`–`m12`.

## 5. Nuances worth calling out

- **M6's primary input is M5's clip**, not M1 — M6 only falls back to M1 when the
  M5 source clip is missing.
- **M10 prefers the participant's own AlpaSim run** (`users/{profile}/m10/aggregate/`)
  and falls back to the shared admin reference (`m10-reference/`).
- **M4 reads M2, not M3** — it is a parallel search branch off the raw captions,
  not a consumer of the curated set.
- **M11 writes a divergent stub schema into a private `m11/pipeline/` namespace**
  to avoid clobbering `m2/`/`m3/` (which M3/M4/M12 depend on).
- **M1's `cam_front_scenes` is always written**; the `?`/`.get()` guards in some
  downstream cells are only for older manifests.
