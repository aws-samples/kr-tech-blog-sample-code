# AV 3.0 Blueprint Lab — Participant Guide

Welcome! This guide walks you through running the AV 3.0 pipeline notebooks
(M0–M12) end to end. You do **not** need an AWS account or console access — the
workshop admin gives you a personal dashboard link, and everything happens from
your browser.

> 📚 **New to AV 3.0 / the Cosmos & Alpamayo models?** Read
> [PRE_LEARNING_GUIDE.md](PRE_LEARNING_GUIDE.md) **before the workshop** (~45–60 min)
> — it explains the concepts so the modules make sense. This guide is the
> click-by-click runbook for the day.

The pipeline follows the [NVIDIA + AWS Physical AI blog](https://aws.amazon.com/blogs/industries/building-an-end-to-end-physical-ai-data-pipeline-for-autonomous-vehicle-3-0-on-aws-with-nvidia/):
data exploration → captioning (Cosmos Reason) → curation → augmentation →
VLA inference → closed-loop simulation.

---

## 0. Prerequisites — nothing to prepare

**You don't need a Hugging Face account, token, or any model-license approval.**
All models (Cosmos Reason / Transfer / Predict, Alpamayo) are **pre-cached to S3
by the admin**, and the notebooks load them offline. Just open your dashboard
link (below) and run the modules.

The only thing you need is the **participant dashboard link** your admin sends
you. (Details for admins: [PREREQUISITES.md](PREREQUISITES.md).)

> M9/M10 use Alpamayo-1.5-10B, which is **non-commercial** (research/eval only) —
> you don't download it, but running M9/M10 acknowledges that license.

---

## 1. Open your dashboard

Your admin gives you a **participant dashboard link** that looks like:

```
https://<user-dashboard>.cloudfront.net/?userId=<your-id>&token=<your-token>
```

- Open it in any browser. This link **does not expire** — bookmark it and reuse
  it any time during the workshop.
- If the page shows a **"Demo Mode"** banner, the link is missing your
  `userId`/`token` — go back and open the full link the admin sent you.
- You'll see the **Pipeline Map**: nodes M1–M12 (12 of them), color-coded by status.

> The workspace links you launch from here do expire after a few minutes, but you
> never copy those by hand — the dashboard mints a fresh one each time you click
> **Open Workspace** (Step 3). Just keep using your dashboard link.

---

## 2. Pick the right instance for your module

Different modules need different compute. **CPU modules** (M0, M1, M4, M10, M11, M12)
run on the small default instance and need no change. **GPU modules** (M2, M3, M5–M9)
need a GPU instance — and you select it yourself from the dashboard.
(M12's notebook is **CPU** — it submits a real 2-node distributed training job that
runs on separate `ml.m5.xlarge` instances, then visualizes the measured metrics.
See [HYPERPOD_M12.md](HYPERPOD_M12.md).)
(M10's SageMaker notebook is **CPU** — it downloads and visualizes genuine AlpaSim
results. The real closed-loop simulation runs on a separate **GPU EC2 host**:
either the admin's shared reference run, or — as an optional advanced path — your
own run over SSM (**~$10.5/hr**, tens of minutes to ~2–3 h; you cannot terminate
that host, the admin does). The self-run additionally requires **your own Hugging
Face token** (for the gated NuRec scene — see [PREREQUISITES.md](PREREQUISITES.md));
the notebook-only path needs no token. See [ALPASIM_M10.md](ALPASIM_M10.md) and, for
the self-run, [M10_PARTICIPANT_SSM_RUNBOOK.md](M10_PARTICIPANT_SSM_RUNBOOK.md).)

Your workspace starts on a small CPU instance (`ml.t3.medium`). Before running a
GPU module such as **M2 (Cosmos Reason Captioning)**, switch it:

1. On the Pipeline Map, click the **M2 — Cosmos Reason Captioning** node.
2. In the side panel, click **Instance Options**.
3. The recommended instance (**`ml.g5.12xlarge`**) is already selected. Click
   **Apply & Restart**.
4. Your workspace restarts (a few minutes). The correct **GPU software image is
   selected automatically** — you don't choose it.

That's the whole flow: **pick the instance, click Apply.** The platform handles
the GPU image and the notebook-sync for you.

### Recommended instance per module

| Module | Recommended instance | Type |
|--------|---------------------|------|
| M0 Pipeline Overview | `ml.t3.medium` | CPU |
| M1 Data Exploration | `ml.t3.medium` | CPU |
| **M2 Cosmos Reason Captioning** | **`ml.g5.12xlarge`** | GPU (4× A10G, 96 GB) |
| M3 Cosmos Curator | `ml.g5.12xlarge` | GPU |
| M4 OpenSearch Semantic Search | `ml.t3.medium` | CPU |
| M5 Cosmos Transfer (Weather Aug) | **`ml.g5.12xlarge`** | GPU (4× A10G, 24 GB/GPU) — runs at 480p; see tier table below |
| M6 Cosmos Predict (Scenario Gen) | **`ml.g5.12xlarge`** | GPU (4× A10G) — runs at 480×832; see tier table below |
| M7 Nerfstudio 3D Reconstruction | `ml.g5.xlarge` | GPU (1× A10G) — ⚠️ **known-limited**: the GPU check + data-prep cells run, but the final 3D-training cell (splatfacto) does not run on the current image. Treat M7 as an optional/demo module (see note below). |
| M8 Cosmos Reason LoRA SFT | **`ml.g5.12xlarge`** | GPU (4× A10G) — trains at native 1600×900. VRAM measured on 4× L4, the same 22,888 MiB geometry: 11.28 GiB worst-GPU peak, 10.76 GiB spare. Needs ≥2 GPUs (or one card ≥40 GB). **Run end to end on 4× A10G** (`ml.g5.12xlarge`): 40 steps × 4 accum in 7.8 min, loss 18.06 → 7.83, worst-GPU peak 7.05 GiB, 154.1 MiB adapter. Outputs are in `examples/notebooks-with-outputs.tar.gz`. |
| M9 Alpamayo VLA Inference | **`ml.g5.12xlarge`** | GPU (4× A10G) — sharded "balanced-expert" path; the passing run (minADE 0.3779) was on A10G |
| M10 AlpaSim Closed-Loop Eval | `ml.t3.medium` | CPU (visualizes genuine AlpaSim results; real sim runs on a GPU EC2 host — admin reference, or your own via SSM) |
| M11 Pipeline Automation | `ml.t3.medium` | CPU |
| M12 HyperPod Distributed Training | `ml.t3.medium` | CPU (submits a real 2-node DDP training job on `ml.m5.xlarge`×2; HyperPod itself is conceptual — see HYPERPOD_M12.md) |

Your workspace is created with a **200 GB** EBS volume, which covers every module. The
**Instance Options** panel shows the size your volume actually is, plus the capacity that
module recommends — they are two different numbers and the panel labels them as such. If a
notebook does run out of disk you can add **+50 GB / +200 GB** there; note that a volume can
be grown but **never shrunk**.

### Output quality vs cost — the per-GPU VRAM tiers (M5 / M6 / M9)

**The recommended instance completes every module.** You do not need a bigger box to
finish the lab. What a bigger box buys is *output quality*, and it depends on **VRAM
per GPU** — not total VRAM, and not the instance size number:

| Instance | per-GPU | M5 / M6 output | M9 path | ~$/hr |
|---|---|---|---|---|
| **`ml.g5.12xlarge`** (default) | ~22.5 GB | 480p, guardrails **OFF** | sharded `balanced-expert` | **7.09** |
| `ml.g6.24xlarge` | ~22.5 GB | identical to the default | sharded | 8.34 — same tier, +18% cost |
| `ml.g7e.2xlarge` (1× RTX PRO 6000) | **96 GB** | **720p / native, guardrails ON** | **single-GPU** | **4.20** — see caveat below |
| `ml.g5.24xlarge` | ~22.5 GB | identical to the default | sharded | 10.18 — **no benefit, +44% cost** |
| `ml.g5.48xlarge` / `ml.g6.48xlarge` | ~22.5 GB | identical to the default | sharded | 20.36 / 16.69 — more GPUs, same tier |
| `ml.p4d.24xlarge` | 40 GB | 720p / native, guardrails ON | single-GPU | 25.25 |
| `ml.p5.48xlarge` | 80 GB | 720p / native, guardrails ON | single-GPU | 63.30 |

Three things worth knowing:

- **Within the g5 and g6 families, a bigger size adds GPUs — never VRAM per GPU.**
  Every A10G and every L4 is 24 GB. So no g5/g6 size can reach the 38–40 GB tier.
  The families that can are g7e (96 GB/card), p4d (A100 40 GB) and p5 (H100 80 GB).
- **24 GB cards are a verified path, not a degraded fallback.** M9 on 24 GB cards was
  run end-to-end with **minADE 0.3779 m, `Status: PASS`** — 0.003 m from the H100
  reference run (see [ALPAMAYO_M9.md](ALPAMAYO_M9.md) "Verified runs").
- **`ml.g7e.2xlarge` breaks the usual "better costs more" rule.** One RTX PRO 6000
  Blackwell card holds 96 GB, so it clears the top tier on a *single* GPU at roughly
  **half the default's price**. Two caveats, both real: this lab has **no verified run
  on g7e**, and the instance needs **its own Studio-JupyterLab quota** (not granted by
  default) — ask your workshop admin before selecting it. The default remains the
  recommended, tested choice.

If you want full-resolution output with the guardrail models enabled, try
`ml.g7e.2xlarge` first (cheapest) and `ml.p4d.24xlarge` otherwise — and stop it
promptly either way.

---

## 3. Open the workspace and run the notebook

1. Look at the button top-right of the dashboard.
   - **Open Workspace** → click it. A fresh JupyterLab tab opens, no extra login.
   - **Start Workspace** → your workspace is stopped (this is what you see on your
     very first login, and after the idle shutdown). Click it: Instance Options opens,
     check the instance, then **Apply & Restart**. Wait until the button becomes
     **Open Workspace**, then click that.
   - **Workspace starting… / Shutting down…** → it is mid-transition; wait.
2. In the JupyterLab file browser, open the module's notebook (e.g.
   `M2_Cosmos_Reason_Captioning.ipynb`).
3. Run the cells top to bottom (Shift+Enter, or Run ▸ Run All Cells).

> **After changing instances (Step 2), always click Open Workspace again** to get
> a fresh link — the old tab points at the previous instance.

> ℹ️ **Changing instances does NOT erase your work.** Each module saves its
> results to S3 and the next module reads them from there, and your workspace home
> directory persists across the restart. Only the previous kernel's in-memory
> variables are cleared — just re-run the new notebook's cells. See
> [What survives an instance change?](#what-survives-an-instance-change) below.

---

## 4. Verify the GPU (M2 and other GPU modules)

Each GPU notebook starts with a **pre-flight GPU check** cell. On a correctly
provisioned GPU instance you'll see something like:

```
CUDA available: True
GPU: NVIDIA A10G  ×4   (96 GB total)
```

If instead you see:

```
ERROR: No GPU detected!
```

…your workspace is still on a **CPU instance**. Fix it:
- Go back to the dashboard → **M2 node → Instance Options → select
  `ml.g5.12xlarge` → Apply & Restart**, wait for the restart, then **Open
  Workspace** again and re-run the cell.

When M2 succeeds, it downloads the Cosmos Reason model (pre-cached, fast),
captions the sample clips, and writes `captions.json` to your workspace — this
feeds M3.

---

<a id="what-survives-an-instance-change"></a>
## What survives an instance change?

A very common worry: *"I finished M1 on the CPU instance. If I switch to a GPU
instance for M2 and my workspace restarts, do I lose my M1 results?"*

**No — your work is safe.** Here is exactly what happens when you change instances
and the workspace restarts:

| What | Survives the restart? | Why |
|------|:---:|-----|
| **Module results in S3** (M1's `m1/` output, M2's `captions.json`, etc.) | ✅ **Kept** | Each notebook uploads its results to your S3 workspace, and the next module downloads them from S3. This is how data flows M1 → M2 → M3 …|
| **Your home directory** (`/home/sagemaker-user`: notebooks, files you saved, downloads) | ✅ **Kept** | The instance change swaps only the compute + software image. Your storage volume (EBS) stays attached across the restart. |
| **The notebook files themselves** (M0–M12) | ✅ **Kept** | Re-synced automatically on every start. |
| **In-memory state of the previous kernel** (Python variables, loaded models, `df = ...`) | ❌ **Cleared** | The kernel is a fresh process on the new instance. This is normal for *any* Jupyter restart. |

### What this means in practice

- **The design deliberately passes data between modules through S3, not through
  the notebook's memory or local disk.** So switching instances between modules is
  a normal, expected part of the workflow — not a data-loss risk.
- **Before switching**, just make sure the module you finished actually ran its
  **final "upload to S3" cell**. If you used *Run ▸ Run All Cells* (recommended),
  it already did. You can confirm M1 wrote its output by checking that
  `m1/` appears in your S3 workspace (M1's last cells print the S3 path).
- **After switching**, open the next notebook and run its cells from the top. Each
  GPU module's early cells **re-download** the inputs it needs from S3 (e.g. M2
  pulls M1's `m1/` output and the Cosmos Reason model from the cache), so a fresh
  kernel with no memory from M1 is completely fine.
- **You can switch back and forth freely.** Going GPU → CPU (e.g. back to
  `ml.t3.medium` for M4) and later CPU → GPU again does not lose anything in S3 or
  your home directory.

### The one thing to redo

If you had **unsaved in-memory results** — e.g. you computed something in a cell
but never wrote it to a file or S3 — that value is gone after the restart, because
it lived only in the old kernel's memory. Re-run the cell to recompute it. Nothing
that was written to a file or uploaded to S3 is affected.

> **Rule of thumb:** *File or S3 = safe. Only-in-a-variable = re-run the cell.*

---

## 5. If a GPU instance is unavailable (capacity error)

Occasionally AWS is temporarily out of `ml.g5.12xlarge` capacity in the region.
You may see, when launching:

```
EC2InsufficientCapacityError: Instance type 'ml.g5.12xlarge' is temporarily unavailable ...
```

Fix: open **Instance Options** again and pick the **`ml.g6.12xlarge`**
alternative (4× NVIDIA L40S, 192 GB — a newer generation with more availability).
It comfortably meets M2 and M3's requirements (the only two `ml.g5.12xlarge`
modules). Apply & Restart, then continue.

The panel's alternative list already offers the right fallbacks for each module,
so just choose the next one down.

---

## 6. Cost & good citizenship

GPU instances are billed by the hour and are **not free** (`ml.g5.12xlarge` ≈
$7.09/hr; `ml.g6.24xlarge` ≈ $8.34/hr; `ml.p4d.24xlarge` ≈ $25.25/hr). Please:

- **Switch back to `ml.t3.medium`** (via Instance Options) when you move from a
  GPU module to a CPU module (M4, M11) — don't leave a GPU box idle.
- Your workspace **auto-shuts down after 90 minutes (`-c idle_timeout_minutes=<60..180>` to change) of inactivity**, but don't rely
  on it — finish or pause when you step away. To get it back: any module node →
  **Instance Options** → **Apply & Restart**. Your files are on the space's volume and
  survive the shutdown.
- The workshop admin can see active sessions and will help if something is stuck.

---

## 7. Module flow at a glance

```
M1 (explore, CPU)
   └─▶ M2 (caption, GPU) ─▶ M3 (curate, GPU) ─┬─▶ M5 (weather aug, GPU)
                                              ├─▶ M6 (scenario gen, GPU)
                                              ├─▶ M9 (VLA, GPU) ─▶ M10 (sim eval, CPU*)
                                              └─▶ M12 (distributed train, CPU† → m5.xlarge×2 job)
   M2 ─▶ M4 (search, CPU)
   nuScenes ─▶ M7 (3D recon, GPU‡)     M1 ─▶ M11 (orchestration, CPU)
```

\* M10's real AlpaSim closed-loop simulation runs on a GPU EC2 host (admin, once);
the participant notebook is CPU and visualizes those genuine results.

‡ M7 is a **known-limited/optional** module: its GPU check and data-prep cells
run, but the final splatfacto (3D Gaussian Splatting) training cell does not run
on the current SageMaker image — it needs a custom CUDA-toolkit image. Don't be
surprised if that last cell fails; the rest of the module still illustrates the
3D-reconstruction stage.

† M12's notebook is CPU and submits a real 2-node `torch.distributed` DDP training
job that runs on separate `ml.m5.xlarge` instances (gloo), then visualizes the
measured metrics. Full SageMaker HyperPod is separate infrastructure — see
[HYPERPOD_M12.md](HYPERPOD_M12.md).

Start with **M0** (overview, no GPU), then follow the core path
**M1 → M2 → M3** before branching out. See **M0_Pipeline_Overview.ipynb** for the
full architecture and the blog stage → module mapping.

---

## Quick troubleshooting

| Symptom | Fix |
|---|---|
| "Demo Mode" banner | Open the full dashboard link (`?userId=&token=`) from the admin. |
| "No GPU detected" in a GPU notebook | You're on CPU — Instance Options → GPU instance → Apply & Restart → Open Workspace again. |
| `EC2InsufficientCapacityError` | Pick the `ml.g6.12xlarge` (or next) alternative in Instance Options. |
| Workspace link expired / blank | Click **Open Workspace** again from the dashboard for a fresh link. |
| Top-right button says **Start Workspace** | Your workspace is stopped — normal on first login and after the 90-minute idle shutdown. Click it, check the instance, **Apply & Restart**, then **Open Workspace** when it appears. Your files are on the space's volume and survive the shutdown. |
| You ended up on the SageMaker Studio page instead of JupyterLab | Go back to your dashboard and use the button there; it is the supported path because it records which instance you used for cost reporting. Studio's own **Run space** / **Open JupyterLab** should work on your own workspace, but if either returns an authorization error, use the dashboard. |
| Out of disk in a notebook | Instance Options → +50 GB / +200 GB → Apply. |
| M5 / M6 stop with "GPU MEMORY IS ALREADY IN USE BY ANOTHER PROCESS" | Expected after running **M2** or **M8**: both load a 7B model across every GPU and hold it until their kernel exits, and M5/M6 need nearly a whole card each. The halt message now lists the PIDs holding the memory. Open the notebook that owns it and run its last **Release the GPUs** cell, then Run All Cells here — no kernel shutdown needed. |
| Notebook files missing after instance change | Wait for the restart to finish, then Open Workspace again (notebooks re-sync on start). |
| "Did I lose my results after changing instances?" | No — results are in S3 and your home directory persists; only the old kernel's memory is cleared. See [What survives an instance change?](#what-survives-an-instance-change). Re-run the new notebook from the top. |
