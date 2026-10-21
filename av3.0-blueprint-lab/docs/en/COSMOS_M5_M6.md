# Cosmos Transfer / Predict (M5, M6) — real inference on the SMD image

**Status:** M5 (Cosmos Transfer 2.5, edge → weather) and M6 (Cosmos Predict 2.5,
video2world) are both **verified end-to-end** on the SageMaker Distribution (SMD)
GPU image — M5 on the repo example + a real nuScenes CAM_FRONT clip, M6 via a
full JupyterLab "Restart & Run All". Both now run **without a participant HF
token** via an offline S3 checkpoint cache (see "Offline checkpoint cache" below).

## The core problem these modules had

The shipped notebooks imported a **hallucinated `cosmos1` package**
(`from cosmos1.models.diffusion.inference... import load_model_by_config`,
`WorldGenerationPipeline`, `cosmos1.utils.video_utils`) that **does not exist**.
There is no `pip install cosmos-transfer2`. The real workflow is:

1. Clone the official repo `github.com/nvidia-cosmos/cosmos-transfer2.5`.
2. `uv sync --extra=cu128 --python 3.10` (torch 2.7 + cu128, transformer-engine,
   megatron — all **prebuilt** wheels, no source compile).
3. Run `examples/inference.py -i <spec.json> -o <outdir> control:edge`.

Unlike M7 (gsplat needs a source CUDA compile the SMD image can't do), **M5 is
all prebuilt** — so once the environment is wired up, it just works, and it is
reproducible via a script.

## `scripts/setup_cosmos_env.sh`

One idempotent script does the whole install on the instance NVMe
(`/mnt/sagemaker-nvme`, 28 TB on p4d/p5) and writes `cosmos_env.sh` that the
notebook sources. It encodes every environment fix we had to discover:

| # | Symptom | Root cause | Fix in script |
|---|---------|-----------|---------------|
| 1 | `ImportError: libGL.so.1` then `libgthread-2.0.so.0` | `opencv-python` (GUI build) needs system GL libs the SMD image lacks | keep only `opencv-python-headless` |
| 2 | `CalledProcessError: ldconfig -p \| grep libnvrtc` | transformer-engine `_load_nvrtc()` runs `ldconfig`; pip CUDA libs aren't in the linker cache, grep exits 1 and crashes before the fallback | set `CUDA_HOME` to the pip `nvidia/` tree so TE's recursive glob finds `libnvrtc` first |
| 3 | `OSError: libcublas.so.12: cannot open shared object file` | TE `dlopen`s versioned SONAMEs; pip CUDA dirs not on loader path | put every `nvidia/*/lib` on `LD_LIBRARY_PATH` |
| 4 | `RuntimeError: Unable to dlopen libcudart.so` | TE `dlopen`s the **unversioned** name; pip wheels ship only `libcudart.so.12` | create `libX.so → libX.so.NN` symlinks |
| 5 | `Access denied. This repository requires approval` | Cosmos checkpoints are HuggingFace-gated | `HF_TOKEN` for an account that accepted the licenses (below) |
| 6 | `RuntimeError: Unable to parse string as hex hash value` | hf-xet chunked download backend bug | `HF_HUB_DISABLE_XET=1` |

`ldconfig` (step 3-adjacent) is also registered via
`/etc/ld.so.conf.d/pip-nvidia-cuda.conf` as belt-and-suspenders, but
`LD_LIBRARY_PATH` in `cosmos_env.sh` is the real guarantee (some SMD app shells
didn't pick up the conf.d file).

### Gated HuggingFace repos (accept licenses once, per HF account)

- https://huggingface.co/nvidia/Cosmos-Guardrail1
- https://huggingface.co/nvidia/Cosmos-Transfer2.5-2B
- https://huggingface.co/nvidia/Cosmos-Reason1-7B  (used as the prompt/guardrail reasoner)
- (M6) https://huggingface.co/nvidia/Cosmos-Predict2.5-2B

Set `export HF_TOKEN=hf_xxx` before running the setup cell. **Do not commit the
token.** If a token is ever exposed, revoke it at
https://huggingface.co/settings/tokens.

## M5 notebook flow (rewritten)

`notebooks/M5_Cosmos_Transfer_Augmentation.ipynb` now:

1. **Config** — profile/buckets, NVMe work dir, weather prompts, `HF_TOKEN`.
2. **GPU check** — any GPU box ≥ 24 GB (`total_memory`, not `total_mem`).
3. **Install** — runs `scripts/setup_cosmos_env.sh` (idempotent; ~15-25 min on
   the first run of a fresh app, near-instant after).
4. **Build input** — reads `m1/manifest.json`, downloads the listed nuScenes
   CAM_FRONT frames from the shared bucket, stitches ≤57 of them into a
   1280×704 @ 10 fps mp4.
5. **Build spec** — one JSON per weather condition; `control_path` **omitted**
   so Cosmos computes the Canny edge control on the fly (`--video-path` only).
6. **Inference** — `examples/inference.py ... control:edge` per spec (35
   diffusion steps; ~3-5 min/clip on p4d/p5).
7. **Upload** — generated + edge-control mp4s + source clip + manifest → `m5/`.
8. **Cost + validate + inline preview.**

Default `CONDITIONS = ["rain"]` to keep a workshop run cheap; extend to
`["rain","fog","night"]` for all variants.

### Verified runs (2026-07-07, reference deploy example account <aws-account-id>)

- Repo example: `robot_edge_spec.json` → `robot_edge.mp4` (3.8 MB, 35/35 steps).
- nuScenes: 57 CAM_FRONT frames → auto-edge → `nuscenes_rain.mp4`
  (`{'edge': None}` in the log confirms on-the-fly edge; 35/35 steps, ~4m38s on
  the running GPU box).

## M6 (Cosmos Predict 2.5) — verified

M6 shipped the same hallucinated API (`WorldGenerationPipeline`). The real path
is the sibling repo **`github.com/nvidia-cosmos/cosmos-predict2.5`** — same
install shape as Transfer (`cosmos-oss[cu128_torch27]`, `uv sync --extra=cu128`,
same CUDA/opencv fixes) but a **separate** top-level package (`cosmos_predict2`)
in its **own `.venv`**. Verified end-to-end on 2026-07-09 (KY-5, p5.48xlarge,
H100×8).

- `scripts/setup_cosmos_env.sh` now takes an arg: `transfer` | `predict` | `both`
  (default). `prepare_repo()` clones + `uv sync`s each repo into its own venv,
  applies the shared fixes, and writes a per-stack env file: **`cosmos_env.sh`**
  (Transfer/M5) and **`cosmos_predict_env.sh`** (Predict/M6). M6 sources the
  latter.
- M6 notebook (`notebooks/M6_Cosmos_Predict_Synthesis.ipynb`) rewritten to the
  real flow: run setup (`predict`) → reuse M5's nuScenes clip (`m5/source/`, else
  rebuild from M1) → build a Video2World spec → `examples/inference.py -i spec
  -o out --inference-type=video2world` → upload to `m6/`.
- **Input spec** (Predict 2.5): `{"inference_type":"video2world", "name":..,
  "prompt":.., "input_path":<mp4>}`. Note `input_path` (NOT Transfer's
  `video_path`). Base 2B needs **no** `--experiment`/`--checkpoint-path`; the
  mode is auto-detected (2+ video frames → video2world). Checkpoints
  (Cosmos-Predict2.5-2B/base/post-trained, Reason1.1-7B, Guardrail1) auto-download
  from HF into `HF_HOME`.
- **Verified run**: nuScenes CAM_FRONT clip → `near_collision` prompt →
  `Generating video with standard mode... 36/36 [~4m07s]` → `nuscenes_near_collision.mp4`.

### Two bugs found while wiring M6 (fixed in setup_cosmos_env.sh)
- **uv venv has no `pip`.** The refactor briefly used `"$venv/bin/python" -m pip`
  for the opencv cleanup → `No module named pip`, so the GUI `opencv-python` was
  left in place and `import cv2` hit `libgthread-2.0.so.0` (same libGL family as
  M5). Fix: use **`VIRTUAL_ENV=$venv uv pip ...`** (uv venvs always have `uv pip`,
  never `pip`).
- **git-lfs not on the bare SMD shell PATH** → `git clone` checkout fails
  (`git-lfs filter-process: git-lfs: not found`). Fix: clone with
  `-c filter.lfs.smudge= -c filter.lfs.process= -c filter.lfs.required=false`
  (code files come down; LFS example assets stay as pointers, which we don't need).

## Offline checkpoint cache — no participant HF token

M5/M6's `examples/inference.py` pulls gated Cosmos checkpoints through Hugging
Face's own cache at runtime (`checkpoint_db` → `uvx hf download`). To spare every
participant an HF account + token + license approvals, we cache once and run
offline:

- **Admin (once):** run M5 + M6 on a GPU app with an admin HF token (licenses
  accepted), then `aws s3 sync /mnt/sagemaker-nvme/hf/hub s3://<shared>/hf-cache/hub/`.
  Running the modules (vs a bare `hf download`) guarantees every revision + side
  file cosmos needs (Wan2.1 VAE, Reason1.1, Guardrail1, …) is in the tree.
- **Participant setup:** `setup_cosmos_env.sh` `aws s3 sync`s `hf-cache/hub/` back
  into `$HF_HOME/hub`, and the generated `cosmos_env.sh` / `cosmos_predict_env.sh`
  export **`HF_HUB_OFFLINE=1`** (+ `TRANSFORMERS_OFFLINE=1`) **only when that
  cache is present**. cosmos then loads from cache with no token, no network.
- **Verified (2026-07-09):** with `HF_TOKEN=""` and `HF_HUB_OFFLINE=1`, M6
  video2world completed 36/36 steps — `uvx hf download` honored offline mode and
  hit the local cache. Same mechanism covers M5.
- **Fallback:** if `hf-cache/hub/` is absent in S3, setup leaves online mode on
  and a caller-supplied `HF_TOKEN` still downloads (accepted licenses required).
  The notebooks no longer hard-fail when the token is missing — they assume the
  offline cache and only error at the actual download if neither is available.

## Instance / cost notes

- **Not any GPU instance** — both models need ~65 GB to load on ONE GPU. On
  24 GB cards the notebook shards with `torchrun` and **requires ≥2 GPUs**, so a
  *small* single-GPU box (e.g. `ml.g6.4xlarge`) hard-fails in the pre-flight cell:
  `RuntimeError: ... cannot be sharded to fit. Pick a multi-GPU instance`. Note the
  guard is `RUN_MODE == "shard" and GPU_COUNT < 2`, so it is about the **card being
  too small**, not about being single-GPU: one card ≥70 GB takes the `single` path
  and passes.
- Cell 2 picks the run strategy from **per-GPU VRAM** (never the sum), so the
  instance you choose changes the *output*, not just the speed:

  | per-GPU | Strategy | M5 output | M6 output | Guardrails | Example (~$/hr) |
  |---|---|---|---|---|---|
  | ≥70 GB | single GPU | 720p | native | ON | `ml.g7e.2xlarge` (**4.20**), `ml.p5.48xlarge` (63.30) |
  | ≥38 GB | N-GPU shard | 720p | native | ON | `ml.p4d.24xlarge` (25.25) |
  | <38 GB | N-GPU shard | 480p, 16/57 frames | 480×832, 45 frames | **OFF** | `ml.g5.12xlarge` (7.09) ← default |

  Because every A10G and L4 is 24 GB, **no g5/g6 size reaches the ≥38 GB tier** —
  a bigger g5/g6 adds GPUs, not per-GPU VRAM. The families that do are g7e
  (RTX PRO 6000 Blackwell, 96 GB/card), p4d (A100 40 GB) and p5 (H100 80 GB).

  **`ml.g7e.2xlarge` is the cheapest top-tier box** — 96 GB on ONE card at
  ~$4.20/hr, i.e. the `≥70 GB` single-GPU path at *half* the 24 GB default's
  price. Two caveats: it needs **its own Studio-JupyterLab quota**, and this lab
  has **no verified g7e run** (the verified runs below are g6.24xlarge and
  p5.48xlarge). Treat it as a promising opt-in, not the tested path.
- The 24 GB path also halts if another process already holds GPU memory (the
  "foreign occupancy" check) — close other notebooks' kernels before running.
- Verified on 24 GB cards — `ml.g6.24xlarge` (480p) — and on p5.48xlarge H100×8
  (720p). The default is now `ml.g5.12xlarge`, which is the SAME tier (4 GPUs ×
  22,888 MiB, identical to g6.24xlarge per `describe-instance-types`), so it takes the
  same <38 GB branch; it is cheaper and, unlike g6, has non-zero quota in
  ap-northeast-2. The original blocker was never the instance — it was the
  environment wiring, now scripted.
- The env + checkpoints live on the NVMe and are **reset on app restart**; the
  setup cell is idempotent, so re-running after a restart is the intended flow.
  With the offline S3 cache, a fresh app's first run restores checkpoints from S3
  (fast, in-region) instead of re-downloading from HF.
- One-time first-run cost is the `uv sync` + cache restore (~15-25 min).
