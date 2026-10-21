# AlpaSim (M10) — real closed-loop evaluation, hosted on EC2

**Status:** M10 evaluates the Alpamayo 1.5 policy in **closed-loop** with the real
**AlpaSim** simulator ([NVlabs/alpasim](https://github.com/NVlabs/alpasim),
Apache-2.0). Unlike M5/M6/M9, AlpaSim **cannot run inside a SageMaker Studio
notebook** — it is a Docker-Compose fleet of gRPC microservices needing a ≥40 GB
GPU. So the real simulation runs on a **GPU EC2 host**, and the M10 notebook (CPU)
downloads and visualizes the genuine results it produced.

**Two modes (the notebook auto-detects, preferring your own run):**
1. **Participant self-run** — each participant runs AlpaSim on a GPU host the
   admin pre-provisions for them, reached over **SSM**, writing to their own
   `s3://<user-workspace>/users/<id>/m10/`. Real "I drove it myself" experience,
   but **~$10.5/hr/host**, ≤16 concurrent (G-vCPU quota), first build tens of
   minutes to ~2–3 h. Participant guide: `M10_PARTICIPANT_SSM_RUNBOOK.md`; admin
   provisioning + IAM: `M10_MANUAL_TEST_RUNBOOK.md` Part C.
2. **Admin reference run** — the admin runs AlpaSim once and uploads to
   `s3://<shared>/m10-reference/`; every participant inspects that same genuine
   evaluation at **$0 per-user GPU cost**. This is the notebook's fallback when a
   participant has no run of their own.

Both write the identical artifact layout; the same `scripts/alpasim_ec2_setup.sh`
serves both (output path chosen by `PARTICIPANT_ID`/`M10_OUTPUT_PREFIX`/
`OUTPUT_BUCKET` env — unset ⇒ legacy admin `m10-reference/`).

## The core problem this module had

The shipped notebook imported a **hallucinated `alpasim` package**
(`import alpasim`, `alpasim.env.NuRecEnvironment`,
`alpasim.policy.PolicyWrapper.from_alpamayo`,
`alpasim.metrics.{CollisionMetric,RouteCompletionMetric,ComfortMetric,MetricAggregator}`)
and a fabricated gym-style `env.reset()/env.step()` loop with invented metrics
(`route_completion`, `comfort_score`). None of that exists — same class of bug as
M5/M6's fake `cosmos1` and M9's fake `alpamayo`. There is no `pip install
alpasim`. The real interface is the **`alpasim_wizard` Hydra CLI** driving Docker
Compose, and the real metrics are `collision_at_fault`, `collision_rear`,
`dist_to_gt_trajectory`, `offroad`.

## Why M10 can't run in the notebook (and M5/M6/M9 could)

M5/M6/M9 were rebuilt as in-process `uv` venvs precisely because a SageMaker
Studio JupyterLab app is a **managed container with no Docker daemon**. AlpaSim's
execution model is fundamentally different:

- It is a set of **microservices** — `renderer` (NuRec/NRE), `driver` (the
  Alpamayo policy), `physics`, `runtime`, `controller` — each a **container**,
  wired over gRPC and brought up by **Docker Compose** (`run_method:
  DOCKER_COMPOSE`). `deploy=local` still means *local containers*, not
  container-free execution. There is no pure-Python mode.
- The **Alpamayo 1.5 driver needs ~40 GB VRAM** (≥60 GB with CFG-nav), and the
  NuRec renderer is co-resident with its own VRAM.

A notebook cell cannot `docker compose up`, so M10 runs elsewhere.

## The architecture we use: admin-run reference eval

1. **Admin, once, on a GPU EC2 host** (`scripts/alpasim_ec2_setup.sh`): restore
   the shared HF cache (Alpamayo-1.5-10B + Cosmos-Reason2-8B, already staged by
   M9), clone AlpaSim, `source setup_local_env.sh`, `docker login nvcr.io`, run
   the wizard, and upload the genuine outputs to `s3://<shared>/m10-reference/`.
2. **Participant, in the M10 notebook (CPU `ml.t3.medium`)**: `aws s3 sync` the
   reference results and visualize the real `metrics_results.txt` table, the
   per-rollout `metrics.parquet` (bar of `collision_at_fault`/`collision_rear`/
   `offroad`, histogram of `dist_to_gt_trajectory`), AlpaSim's own
   `metrics_results.png`, and the real eval video.

This is a **genuine** closed-loop evaluation of the exact model M9 runs — not
simulated numbers. It is honestly framed everywhere as an admin reference run,
not a per-user simulation.

## The honest M9 → M10 link

AlpaSim does **not** consume M9's predicted-trajectory `.npy`. It loads the
**same `nvidia/Alpamayo-1.5-10B` checkpoint** (from the shared hf-cache) as its
`driver=alpamayo1_5` plugin and drives it closed-loop. So:

- **M9** = the Alpamayo model predicting a trajectory **open-loop** (minADE).
- **M10** = the **same model** driving **closed-loop** in AlpaSim (safety metrics).

The shared artifact is the checkpoint, not the trajectory file. The notebook
reads M9's `manifest.json` only to display this provenance.

## Instance & GPU placement (from the repo's topology configs)

AlpaSim's `topology` config pins services to GPUs (`src/wizard/configs/topology/`):

| topology | driver | renderer | physics | Fits on |
|---|---|---|---|---|
| `1gpu` | GPU 0 | GPU 0 | GPU 0 | one **≥80 GB** card (A100 80GB / H100) — driver ~40 GB + co-resident renderer |
| `2gpu` | GPU 0 (×3 replica) | GPU 1 | GPU 0+1 | **two ≥40 GB** cards → **L40S 48 GB ×2 = g6e.12xlarge** |

24 GB cards (A10G/L4) do **not** fit the 40 GB driver under either topology —
and AlpaSim runs the driver as a container we don't control, so M9's
`balanced-expert` multi-24 GB-card trick does not apply here.

> ### ⚠️ M10 needs **≥2 GPUs** — and the instance name's number is NOT the GPU count
> `topology=2gpu` (the default) places the renderer on **GPU 1**, so the host must
> expose **at least 2 GPUs**. In the g6e family, a **bigger vCPU size does NOT mean
> more GPUs** — only three sizes have multiple GPUs. Picking `g6e.16xlarge` because
> it "looks bigger than 12xlarge" gives you **1 GPU** and the run dies at launch with
> `Service renderer requested GPUs [1] but only 0 .. 0 are available`.
>
> | g6e size | GPUs | vCPU | OK for M10 (2gpu)? |
> |---|---|---|---|
> | g6e.xlarge / 2xlarge / 4xlarge / 8xlarge | **1** | 4–32 | ❌ single GPU |
> | **g6e.12xlarge** | **4** | 48 | ✅ **recommended** |
> | g6e.16xlarge | **1** | 64 | ❌ single GPU (bigger box, still 1 GPU!) |
> | g6e.24xlarge | **4** | 96 | ✅ (overkill for M10) |
> | g6e.48xlarge | **8** | 192 | ✅ (overkill) |
>
> Rule of thumb: **multi-GPU g6e = 12xlarge (4), 24xlarge (4), 48xlarge (8)**. Every
> other size — including 16xlarge — is a **single-GPU** box. Confirm before you run:
> `nvidia-smi --query-gpu=index,name,memory.total --format=csv` must list **≥2** rows.

- **Recommended (cost-optimal): `g6e.12xlarge` (4× L40S 48 GB) + `topology=2gpu`**,
  ~$10.5/hr on-demand (reference deploy example region: us-west-2; pricing varies by region).
- **Safe fallback:** `p4de.24xlarge` / `p5.48xlarge` (80 GB cards) + `topology=1gpu`
  (a single ≥80 GB card is enough for 1gpu; 2gpu still needs two cards).
- CFG-nav stays **off** (default) so the driver fits ~40 GB.

## Gated dependencies

- **HF:** `nvidia/Alpamayo-1.5-10B` + `nvidia/Cosmos-Reason2-8B` (loaded offline
  from the shared hf-cache) and the **`nvidia/PhysicalAI-Autonomous-Vehicles-NuRec`**
  dataset. ⚠️ **NuRec is downloaded at runtime and is NOT in the shared offline
  cache** (unlike the models) — so `HF_TOKEN` is a **hard requirement** of
  `alpasim_ec2_setup.sh` (preflight fails `HF_TOKEN not set` otherwise), and the
  token's account must have accepted the NuRec license (else `GatedRepoError`).
  In **admin reference** mode the admin supplies their token; in **participant
  self-run** mode **each participant supplies their own token** — this is the one
  place the "participants need no HF token" rule does not hold (see
  `PREREQUISITES.md` and `M10_PARTICIPANT_SSM_RUNBOOK.md`).
- **NGC:** the renderer image `nvcr.io/nvidia/nre/nre-ga:26.04` is pulled from NGC.
  You need an NGC API key (`https://org.ngc.nvidia.com/setup/api-key`) and access
  to that image. This is the **M10 hard gate** — `alpasim_ec2_setup.sh` verifies it
  with `docker manifest inspect` before the long build.

## Admin one-time sequence

Launch a Docker-capable GPU host (AWS **Deep Learning Base GPU AMI** — ships
Docker + NVIDIA Container Toolkit + driver ≥570) in a **public subnet with
internet egress** (the lab VPC is isolated; use the default VPC), then:

```bash
export HF_TOKEN=hf_xxx            # Alpamayo + Cosmos-Reason2 + NuRec accepted
export NGC_API_KEY=nvapi-xxx      # NGC access to nre-ga
# SHARED_BUCKET is deliberately NOT exported: the script derives
# av30lab-shared-data-<acct>-<region> from STS + IMDS and exits 1 if it cannot.
bash scripts/alpasim_ec2_setup.sh
# verify the m10-reference/ upload, then TERMINATE the instance.
```

The script: preflight (nvidia-smi / docker / NVIDIA runtime / uv / cargo) →
restore `hf-cache/hub` into `$HF_HOME` → clone AlpaSim (pinned) → NGC login +
`docker manifest inspect` gate → `source setup_local_env.sh` →
`uv run alpasim_wizard deploy=local topology=2gpu driver=alpamayo1_5
scenes.scene_ids="['clipgt-01d503d4-449b-46fc-8d78-9085e70d3554']"
wizard.log_dir=$PWD/out eval.video.video_layouts=[REASONING_OVERLAY]` → verify
`aggregate/metrics_results.txt`, `rollouts/**/metrics.parquet`, an eval `.mp4` →
upload to `s3://<shared>/m10-reference/` (`aggregate/`, `rollouts/`, `eval/eval.mp4`,
`run.json`).

The reference bundle is written under `hf-cache/`-sibling prefix `m10-reference/`
on the **shared** bucket: admin creds on the EC2 host write it; participants read
all of the shared bucket. (Cost: ~$30 one-time on g6e.12xlarge; $0 per
participant.)

## Real output artifacts (what the notebook visualizes)

- `aggregate/metrics_results.txt` — formatted driving-score table (mean/std/quantiles).
- `aggregate/metrics_results.png` — AlpaSim's visual summary.
- `rollouts/{scene}/{batch}/metrics.parquet` — per-rollout metrics
  (`collision_at_fault`, `collision_rear`, `dist_to_gt_trajectory`, `offroad`, …).
- `eval/eval.mp4` — the closed-loop rollout with the Chain-of-Causation overlay.
- `run.json` — provenance (driver, scene, topology, renderer image, instance).

## Verified run (2026-07-12, reference deploy example account <aws-account-id>)

Real AlpaSim closed-loop evaluation of `nvidia/Alpamayo-1.5-10B` on **g6e.12xlarge**
(4× L40S 46 GB), alpasim **v0.96.0** *(that tag has since been removed upstream; the pin is now v2026.5, which is UNVERIFIED — see the note below)*, renderer `nvcr.io/nvidia/nre/nre-ga:26.04`,
scene `clipgt-01d503d4-449b-46fc-8d78-9085e70d3554`, topology `m7_4gpu` (driver
alone on GPU 0). Driver loaded Alpamayo from the S3 hf-cache **offline** (no token,
no download). Genuine driving scores:

| Metric | Value |
|---|---|
| collision_any / collision_at_fault / collision_rear | 0.00 (no collisions) |
| offroad / offroad_or_collision | 0.00 |
| dist_to_gt_trajectory (max) | 4.37 m |
| dist_traveled_m (vs GT 73.77 m) | 78.12 m |
| progress_rel / progress | 0.92 / 1.00 (route essentially completed) |
| min_distance_to_obstacle_m | 1.12 m |
| duration_frac_20s | 0.78 |

Outputs uploaded to `s3://<shared>/m10-reference/` (aggregate/, rollouts/, eval/eval.mp4
with the reasoning overlay, run.json). One-time cost ≈ $30 (a few hours of
g6e.12xlarge including the cached-miss first build).

### Gotchas found wiring the run (fixed in scripts/alpasim_ec2_setup.sh)
- **`$HOME` unbound** under `set -u` in an SSM shell → export `HOME=/root` early.
- **`Mount point does not exist: data/drivers`** → the wizard bind-mounts
  `data/{drivers,nre-artifacts/ego-hoods,trafficsim-models}`; `mkdir -p` them first.
- **Driver 401 gated repo** → the base `driver` service has no `environments`, so
  it tried to reach HF online; add a `deploy/local_m7.yaml` that sets
  `driver.environments` = `HF_TOKEN, HF_HOME, HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1`.
  (Same offline-cache lesson as M9.)
- **CUDA OOM** → the stock `topology=2gpu` puts **three** driver replicas on GPU 0;
  three 40 GB Alpamayo copies can't fit an L40S. Use a custom `topology=m7_4gpu`
  that gives the driver GPU 0 alone (renderer GPU 1, physics GPU 2, trafficsim GPU 3),
  one replica, one rollout.

## License

Alpamayo-1.5-10B weights are **non-commercial** (research/evaluation only).
AlpaSim code is Apache-2.0. NuRec scenes are under the NVIDIA AV NuRec Dataset
License. The M10 notebook surfaces this notice.

---

### The pinned alpasim tag (read before a workshop)

`scripts/alpasim_ec2_setup.sh` pins `ALPASIM_TAG` (default `v2026.5`). The measured run
recorded above used `alpasim-base-v0.96.0`, which **no longer exists** —
`git ls-remote --tags https://github.com/NVlabs/alpasim` returns only `v2026.4` and
`v2026.5`. The script used to fall through to the default branch on a tag miss, so a run
could silently use a moving `main`; it now **fails loudly** and prints the available tags.

What is verified about `v2026.5`: every upstream path this script touches exists there
(`deploy/local.yaml`, `driver/alpamayo1_5.yaml`, `topology/` with 6 entries,
`data/scenes/sim_scenes.csv`), and the pinned `SCENE_ID` appears exactly once in its
916-scene `sim_scenes.csv`. `main` lists that scene twice.

What is **NOT** verified: no M10 run has been performed against `v2026.5`. Run one on the
admin EC2 host before the event. If it fails, try `ALPASIM_TAG=v2026.4` (910 scenes, also
carries the pinned scene) — do not fall back to the default branch.
