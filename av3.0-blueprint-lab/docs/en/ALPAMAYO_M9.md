# Alpamayo 1.5 (M9) — real VLA inference on the SMD image

**Status:** M9 (Alpamayo 1.5, Vision-Language-Action trajectory prediction) is
**verified end-to-end** on the SageMaker Distribution (SMD) GPU image — real
inference on a `PhysicalAI-Autonomous-Vehicles` demo clip producing a
Chain-of-Causation explanation + a predicted ego trajectory (**minADE 0.375 m**
on the verified clip). Like M5/M6 it runs **without a participant HF token**, via
an offline S3 checkpoint cache plus a pre-saved demo clip.

## The core problem this module had

The shipped notebook imported a **hallucinated `alpamayo` package**
(`from alpamayo.model import AlpamayoForConditionalGeneration`,
`alpamayo.inference.AlpamayoInferencePipeline`, `alpamayo.utils.load_frames_from_video`,
`pipeline.predict_trajectory` / `predict_trajectory_multicam` / `visual_qa`) that
**does not exist** — the same class of bug as M5/M6's fake `cosmos1`. There is no
`pip install alpamayo`. The real workflow is the official repo
[`NVlabs/alpamayo1.5`](https://github.com/NVlabs/alpamayo1.5), package
`alpamayo1_5` (underscore).

Unlike M5/M6, Alpamayo is a **different stack**: Python **3.12** (Cosmos pins
3.10), torch 2.8, transformers 4.57.1, `physical-ai-av==0.2.0`, **no
transformer-engine**, and **flash-attn excluded** (its source build fails on the
SMD image). So it gets its own venv and its own setup path.

## The real inference flow (verified)

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

`attn_implementation="sdpa"` is **mandatory**: the repo default is
`flash_attention_2`, which `ImportError`s because flash-attn isn't installed.

## Two decisive offline findings

M9 needs to run token-free like M5/M6, but the two halves behave differently:

1. **Model loads offline — use the hf-cache (same as M5/M6).** With `HF_TOKEN`
   unset and `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`,
   `Alpamayo1_5.from_pretrained(...)` + `helper.get_processor` load from the
   S3-restored HF cache with **no token, no network** — including the *hidden*
   VLM backbone **`nvidia/Cosmos-Reason2-8B`** (Alpamayo's Qwen3-VL base), which
   `from_pretrained` pulls transparently. So the shared `hf-cache/hub/` tree must
   contain **both** `models--nvidia--Alpamayo-1.5-10B` **and**
   `models--nvidia--Cosmos-Reason2-8B`.

   > This is why the flat `model-cache/alpamayo-1.5/` copy (raw weights only) is
   > **not** used at runtime — it lacks the Reason2 backbone. `cache_models.sh`
   > no longer downloads it.

2. **Data CANNOT load offline — pre-save a demo clip instead.**
   `load_physical_aiavdataset` builds a `PhysicalAIAVDatasetInterface`, whose
   `__init__` unconditionally calls `self.api.list_repo_refs()` on the gated
   `PhysicalAI-Autonomous-Vehicles` dataset (`physical_ai_av/utils/hf_interface.py`).
   That ignores `HF_HUB_OFFLINE=1` and errors:
   `OfflineModeIsEnabled: Cannot reach .../datasets/nvidia/PhysicalAI-Autonomous-Vehicles/refs`.
   So the **admin** runs `load_physical_aiavdataset` once online and
   `torch.save`s the resulting `data` dict (~100 MB, mostly the 4-camera image
   frames) to S3. The **participant** notebook only `torch.load`s that `.pt` and
   **never imports `physical_ai_av`** — zero token, zero network.

## `scripts/setup_cosmos_env.sh alpamayo`

The Cosmos setup script gained an `alpamayo` mode (`bash scripts/setup_cosmos_env.sh
alpamayo`). It reuses the shared preamble (bucket resolution + `hf-cache/hub/`
restore into `$HF_HOME`) and adds a dedicated `prepare_alpamayo()`:

- clone `NVlabs/alpamayo1.5` (LFS filter disabled, like the Cosmos repos);
- `uv venv a1_5 --python 3.12` then
  `VIRTUAL_ENV=$venv uv sync --active --no-install-package flash-attn`;
- **skip** the transformer-engine `.so`-symlink / `CUDA_HOME` / `ldconfig` steps
  (Alpamayo has no TE — torch 2.8's bundled CUDA loads fine);
- write `alpamayo_env.sh`, which activates the `a1_5` venv, **clears any
  `CUDA_HOME`/`LD_LIBRARY_PATH`** leaked from a sourced cosmos env, and flips on
  `HF_HUB_OFFLINE=1` when `$HF_HOME/hub/models--nvidia--Alpamayo-*` is present.

`alpamayo` is **not** part of `both` (that's the two Cosmos repos) — request it
explicitly.

## `scripts/alpamayo_infer.py`

A committed script (not a repo CLI — the real flow is bespoke) that the notebook
runs via `bash -lc 'source alpamayo_env.sh && python scripts/alpamayo_infer.py
--clips ... --out ...'`. It loads the model **once**, loops the demo clips, and
writes plain artifacts the notebook kernel can read without torch:
`<clip>_pred.npy`, `<clip>_gt.npy`, `<clip>_cot.txt`, and `metrics.json`
(minADE per clip). It loads each `.pt` with `weights_only=False` (torch 2.8
defaults to `True`, which would reject the `int`/`str` entries in the dict).

`scripts/alpamayo_save_clip.py` is the admin-only companion that produces those
`.pt` files (online, with a token).

## M9 notebook flow (rewritten)

`notebooks/M9_Alpamayo_VLA_Inference.ipynb` (11 cells):

1. **Title** + **License** (non-commercial weights) markdown.
2. **Config** — profile/buckets, NVMe work dir, `DEMO_CLIPS`, `HF_TOKEN` optional.
3. **GPU check** — **per-device** max ≥ 40 GB (the model loads onto a single
   device via `.to("cuda")`, so the sum across GPUs is misleading).
4. **Setup** — runs `setup_cosmos_env.sh alpamayo` (idempotent).
5. **Input** — download the demo `.pt`(s) from `hf-cache/alpamayo-demo/` +
   locate `alpamayo_infer.py`.
6. **Inference** — `bash -lc` into the `a1_5` venv, run `alpamayo_infer.py`.
7. **Visualize** — predicted vs. ground-truth trajectory + print the reasoning.
8. **Upload** — outputs → `users/{profile}/m9/`; the manifest keeps the keys M10
   reads (`model` / `modes_run` / `timestamp` / `results`).
9. **Cost.**
10. **Validate + inline preview + Next module (M10).**

Default `DEMO_CLIPS = ["030c760c-..."]` (one clip) to keep a workshop run cheap;
uncomment the other staged clips to run all.

## Admin one-time setup

On a GPU app with an admin `HF_TOKEN` (licenses accepted for
`Alpamayo-1.5-10B`, its `Cosmos-Reason2-8B` backbone, and
`PhysicalAI-Autonomous-Vehicles`):

```bash
export HF_TOKEN=hf_xxx
bash scripts/setup_cosmos_env.sh alpamayo          # build the a1_5 venv (online)
source /mnt/sagemaker-nvme/cosmos-work/alpamayo_env.sh
unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE          # data prep MUST be online

# For each demo clip: save the data dict, run one inference to fill the HF cache.
python scripts/alpamayo_save_clip.py --clip 030c760c-ae38-49aa-9ad8-f5650a545d26 \
    --t0-us 5100000 --out /mnt/sagemaker-nvme/m6_work/clips
python scripts/alpamayo_infer.py \
    --clips /mnt/sagemaker-nvme/m6_work/clips/030c760c-ae38-49aa-9ad8-f5650a545d26.pt \
    --out /mnt/sagemaker-nvme/m6_work/out

# Publish: add Alpamayo + Reason2 to the shared HF cache, and upload the .pt(s).
aws s3 sync /mnt/sagemaker-nvme/hf/hub s3://<shared>/hf-cache/hub/ --only-show-errors
aws s3 cp /mnt/sagemaker-nvme/m6_work/clips/030c760c-...pt s3://<shared>/hf-cache/alpamayo-demo/
```

Both admin uploads target `hf-cache/*`, which is the one prefix the SageMaker
execution role can **write** on the shared bucket — so the whole sequence runs
straight from the GPU app terminal (no admin workstation, no IAM change).
Participants read all of the shared bucket, so they can pull both the
`hf-cache/hub/` tree and `hf-cache/alpamayo-demo/*.pt`.

> The **notebook + scripts staging** (`aws s3 sync notebooks/ scripts/ →
> notebook-templates/`) is the exception: `notebook-templates/*` is read-only for
> the execution role, so run that one step from the admin workstation (or any
> credentials with write to the shared bucket).

## Verified runs (reference deploy example: account <aws-account-id>)

Clip `030c760c-ae38-49aa-9ad8-f5650a545d26 @ t0_us=5_100_000`; Chain-of-Causation
*"Nudge to the left to clear the construction equipment blocking the right side of
our lane."* (89 chars).

- **p5.48xlarge (H100 80 GB), single-GPU** (2026-07-10): `MODEL+PROCESSOR OFFLINE
  LOAD OK` (5 shards) with `HF_TOKEN` unset + `HF_HUB_OFFLINE=1` (model +
  Cosmos-Reason2-8B backbone from cache). **minADE 0.375 m.**
- **g5.48xlarge (8× A10G 24 GB), `balanced-expert`** (2026-07-12): `pinned 42
  action-stack keys -> cuda:0`, offline (cache-only, no download). **minADE
  0.378 m** — 0.003 m from the H100 run (bf16 op-order across architectures; well
  within tolerance).
- **Full notebook Restart & Run All on g5** (2026-07-12, participant path, no HF
  token): cell-3 auto-selected `balanced-expert`, cell-6 minADE 0.3779 m, cell-10
  `Status: PASS`, outputs written to `users/<profile>/m9/`.

## Multi-GPU (24 GB cards) — the `balanced-expert` device map

p4d/p5 are frequently capacity-constrained. M9 also runs on **24 GB multi-GPU**
boxes (g5.48xlarge = 8× A10G 24 GB, g6.48xlarge = 8× L4 24 GB), but **not** with a
plain `device_map="auto"`:

- **Why `auto` fails.** Alpamayo1_5 defines no `_no_split_modules`, so accelerate
  splits the diffusion action `expert` (a `Qwen3VLTextModel`, ~2.3 B) across GPUs.
  `sample_trajectories_from_data_with_vlm_rollout` then does `device =
  input_ids.device` and `self.diffusion.sample(device=device)`, and inside the
  diffusion loop the expert's KV-cache `torch.cat` mixes tensors from two GPUs →
  `Expected all tensors to be on the same device (cuda:6 vs cuda:1)`.
- **Why a single 24 GB GPU fails.** The full ~21 GB model fills one A10G, then the
  VLM `generate` KV cache growth OOMs.
- **The fix: `--device-map balanced-expert`** (in `scripts/alpamayo_infer.py`).
  It loads once with `auto` to read the *real* `hf_device_map`, then rebuilds an
  explicit map that pins the entire **action stack** (`expert`, `diffusion`,
  `action_space`, `action_in_proj`, `action_out_proj`) onto **cuda:0** while
  leaving the big VLM sharded across the other GPUs, and wraps `expert.forward` to
  migrate the VLM-produced `past_key_values` onto cuda:0 (accelerate does *not*
  auto-move a Cache object's interior tensors). Now `device == cuda:0` for the
  whole diffusion rollout and the cache is self-consistent. cuda:0 holds only the
  action stack (~5 GB) + the migrated cache + diffusion activations (~10 GB total,
  well under 24 GB). Notebook cell-3 selects this automatically when no single GPU
  ≥ 40 GB is present.

## Instance / cost notes

- Verified on **p5.48xlarge (H100 80 GB)** (single-GPU) and **g5.48xlarge (8× A10G
  24 GB)** (`balanced-expert`, see below). The model is ~10.5 B params (~21 GB
  bf16) plus VLM-rollout activations.
  - **Single GPU ≥ 40 GB** (p5, p4d A100, g6e L40S 48 GB): loaded onto one device
    (`.to("cuda")`), the verified path. p4d A100 40 GB should fit but is the
    untested floor; if it OOMs, either use p5 or force `balanced-expert`.
  - **24 GB multi-GPU** (g5, g6): `balanced-expert` shards the VLM and pins the
    action stack to cuda:0. This is the **capacity hedge** — when p4d/p5 are
    unavailable, M9 still runs on whatever multi-GPU box is free.
- The env + checkpoints live on the NVMe and are **reset on app restart**; the
  setup cell is idempotent, and a fresh app restores the checkpoints from S3
  (fast, in-region) instead of re-downloading.

## License

Alpamayo-1.5-10B weights are **non-commercial** (research/evaluation only). M9
and M10 both surface this notice; the inference code is Apache-2.0.
