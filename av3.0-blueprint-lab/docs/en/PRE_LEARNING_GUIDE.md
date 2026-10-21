# AV 3.0 Blueprint Lab — Participant Pre-Learning Guide

**Read this before the workshop.** It teaches the *concepts* behind the lab so the
hands-on modules make sense. It is **not** the click-by-click runbook — that's
[PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md), which you'll use on the day.

- ⏱️ **Core reading (do this): ~45–60 min.** Sections 1–4 + the module you'll start with.
- 📚 **Optional deeper dive: as much as you like.** Section 6 links papers, repos, and docs.
- You do **not** need to install anything or have an AWS/Hugging Face account to
  prepare — the core reading is conceptual. (The admin pre-caches everything.)

---

## 1. The big picture — what is "AV 3.0 / Physical AI"?

Autonomous-vehicle development has moved through three broad eras:

- **AV 1.0** — hand-written rules + classical robotics. Brittle in the long tail.
- **AV 2.0** — deep learning on large labeled datasets. Better, but data-hungry and
  still modular (separate perception → prediction → planning stacks).
- **AV 3.0** — **end-to-end, foundation-model-driven**. Large multimodal models
  (vision-language, world models, vision-language-**action** policies) trained on
  huge amounts of real *and synthetic* driving data, evaluated in simulation before
  the road. "**Physical AI**" is NVIDIA's umbrella term for AI that perceives and
  acts in the physical world (robots, AVs).

**The core problem this lab is about: data.** A modern AV model needs enormous,
*diverse*, *well-labeled* driving data — including rare/dangerous situations you
can't safely collect on real roads (a child running out, a whiteout, a wrong-way
driver). The AV 3.0 answer is a **data pipeline** that:
1. starts from real sensor data,
2. **captions and curates** it with AI (so it's searchable and high-quality),
3. **synthesizes** more data — new weather, new scenarios — with generative "world
   models,"
4. trains a driving **policy**, and
5. **evaluates it in closed-loop simulation** before anything touches a car.

This lab is a hands-on, end-to-end walk through exactly that pipeline, on AWS, using
NVIDIA's open models. **You will run the real pipeline** (not a toy) on a small
dataset — with real weights and real outputs, at workshop scale. Several stages use a
documented stand-in for the blog's tooling or hardware; they are all listed in
[Where this lab substitutes for the blog](#where-this-lab-substitutes-for-the-blog)
in §2, so you can see the swap before you hit it.

**Start here:** the one blog post this entire lab implements —
[Building an end-to-end Physical AI data pipeline for AV 3.0 on AWS with NVIDIA](https://aws.amazon.com/blogs/industries/building-an-end-to-end-physical-ai-data-pipeline-for-autonomous-vehicle-3-0-on-aws-with-nvidia/).
Read it once now; everything below is a map of it.

---

<a id="the-8-stage-pipeline"></a>
## 2. The 8-stage pipeline (and how the modules map to it)

The blog defines an **8-stage** pipeline. This lab implements each stage as one or
more notebook modules (M1–M12), **numbered in the blog's stage order**, plus a few
**supplementary** modules that extend it (M6, M11, M12). Data flows module →
module through **S3** (each module reads the previous one's output folder and
writes its own).

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

| Stage (blog) | Module | Concept in one line |
|---|---|---|
| 1–2 Data collection & exploration | **M1** | Load and browse the raw driving dataset (nuScenes-mini). |
| 3 Captioning | **M2** | A vision-language model writes a text description of each clip. |
| 3 Curation | **M3** | Split and transcode the clips, then drop the low-motion ones (e.g. stopped at a light). M2's captions ride along, keeping those whose scene survived. *No dedup and no caption quality score — see the substitutions table below.* |
| 4 Search | **M4** | Turn clips into embeddings so you can *semantically* search them ("find left turns in rain"). |
| 5 Augmentation | **M5** | A "world model" restyles real clips into new **weather/lighting** without re-driving. |
| 5 (ext) Scenario generation | **M6** | A world model **generates new synthetic driving video** from a prompt/seed. |
| 6 Neural reconstruction | **M7** | Rebuild a 3D scene from camera images (NeRF / Gaussian Splatting). *(known-limited — see §5.)* |
| 7 Model training | **M8** | LoRA fine-tune a driving VLM on nuScenes **human** labels (not on M2's captions — that would be circular). |
| 7 VLA inference | **M9** | A Vision-Language-**Action** model predicts the driving trajectory + its reasoning. |
| 8 Closed-loop eval | **M10** | Put that policy in a **simulator** and score it (collisions, off-road, etc.). |
| — Orchestration (ext) | **M11** | Wire M1→M2→M3→M5 into one automated, repeatable **SageMaker Pipeline**. |
| — Training scale-up (ext) | **M12** | The *pattern* for distributed multi-node training (HyperPod). |

> **Mental model to hold onto:** *real data → label it → search & clean it →
> multiply it with synthetic generation → train a policy → prove it in sim.*

### Where this lab substitutes for the blog

The pipeline is real end to end — real NVIDIA weights, real nuScenes data, real AWS
services — but it runs at **workshop scale**, and several stages use a stand-in for
what the blog specifies. They are listed here rather than left for you to discover
mid-module.

| Stage | The blog | This lab | Why |
|---|---|---|---|
| **1–2** Ingest + quality gate | Physical media via **AWS Data Transfer Terminal** into S3; **AWS Batch** validates channels / sync / corruption; sensor data extracted from ROS bag, MCAP or ASAM MDF4 containers | **M1** reads an already-extracted nuScenes-mini tree from S3 and browses it | There is no physical media and no container file to extract — nuScenes-mini ships as jpg + json. Nothing here is ingested or quality-gated. |
| **3** Curation | **NVIDIA Cosmos Curator** on **SageMaker HyperPod + SLURM**: one integrated pipeline over four sub-stages — split → transcode → **caption** → **embed** | **M3** runs **NeMo Curator** (a separate NVIDIA project, despite the name) for split + transcode + a motion filter, with captioning and embedding switched off. Captioning is **M2**; embedding is **M4** | Cosmos Curator is Docker + SLURM on a persistent GPU cluster, so it cannot run inside a Studio notebook. Splitting matches the blog (fixed stride) and so does transcoding (H.264); the other two sub-stages move to their own modules. |
| **3** Captioning | **Cosmos Reason** as a Curator sub-stage (the blog links `cosmos-reason2`) | **M2** runs **Cosmos-Reason1-7B** standalone | Reason 1 is ungated, so participants need no licence click and no Hugging Face token. |
| **3** Embedding | **Cosmos Embed** — *joint video-text* vectors per clip | **M4** embeds the caption **text only**, with `all-MiniLM-L6-v2` (384-dim) | Text-only embeddings run on CPU in seconds. The cost is real: search matches what the caption *says*, not what the video *shows*. |
| **4** Search | Path A **OpenSearch Service** + NVIDIA cuVS with **hybrid** text+vector queries · Path B **Cosmos Dataset Search** on **EKS** | **M4** takes Path A — but on OpenSearch **Serverless**, vector-only k-NN | Serverless needs no cluster to size or patch for a one-day workshop. Path B (EKS, its UI and dataset-assembly workflow) is out of scope. |
| **5** Augmentation | **EC2 + Amazon DCV**. Cosmos Transfer *"requires approximately 65 GB of GPU memory"*, so the blog names **G7e** (RTX PRO 6000 Blackwell, 96 GB) | **M5** runs in a Studio notebook; the default `ml.g5.12xlarge` has **24 GB per card**, so it shards and drops to 480p with guardrails off | 24 GB cards are what a workshop can reliably get quota for. `ml.g7e.2xlarge` — the blog's own hardware, one 96 GB card — is selectable if your account has the quota, and costs *less* than the default. |
| **6** Reconstruction | **NuRec** | **M7** Nerfstudio / gsplat | Already disclosed in M7's header; its final training cell is known-limited. |
| **7** Training | **Alpamayo** | **M8** LoRA-SFTs Cosmos Reason on nuScenes human labels; **M9** runs Alpamayo *inference* on NVIDIA's released checkpoint | Alpamayo ships no LoRA path and a full fine-tune needs ~123 GiB of weight + gradient + optimizer state. M8's header spells this out. |
| **8** SiL testing | **AlpaSim** | **M10** visualizes a genuine AlpaSim run executed on a separate GPU EC2 host | AlpaSim is Docker Compose + gRPC; a Studio notebook cannot host it. |
| *everywhere* | HyperPod, AWS Batch, EKS, EC2 + DCV | single SageMaker Studio instances | One instance per participant per module is what a workshop can provision, bill and tear down. |

**What is *not* a substitution:** the model weights are NVIDIA's real ones, the data is
real nuScenes, and every output you see was actually computed. Where a result is
*degraded* rather than absent — M5/M6 resolution, M7's training cell — the module says
so in its own header.

---

## 3. Key concepts to understand before you start

You don't need to master these — just recognize the words when a notebook uses them.

### 3.1 Foundation models & the NVIDIA Cosmos family
A **foundation model** is a large model pre-trained on broad data that you adapt to
many tasks. This lab uses NVIDIA's **Cosmos** family of *world foundation models* and
the **Alpamayo** driving policy:

| Model (used in) | Type | What it does here |
|---|---|---|
| **Cosmos Reason 1** (M2) | Vision-Language Model (VLM) | "Reasons" about a video clip and captions it. |
| **Cosmos Transfer 2.5** (M5) | World model (video→video) | Restyles a real clip into new weather/conditions. |
| **Cosmos Predict 2.5** (M6) | World model (generation) | Generates new synthetic driving video. |
| **Alpamayo 1.5** (M9, M10) | Vision-Language-**Action** (VLA) | Predicts an ego trajectory + chain-of-reasoning; the "driver." |
| **Cosmos Reason 2** (hidden, M9/M10) | VLM backbone | Alpamayo's internal vision backbone. |

- **VLM vs. VLA:** a VLM outputs *text/understanding*; a **VLA** additionally outputs
  an *action* (here: a future trajectory). VLA is the AV 3.0 "end-to-end driver."
- **World model:** a generative model that predicts/produces *future frames* of a
  scene — the engine behind synthetic data (M5/M6).
- **License note:** Alpamayo (M9/M10) is **non-commercial** (research/eval only). You
  don't download it; running M9/M10 acknowledges that license.

### 3.2 The dataset — nuScenes
[**nuScenes**](https://www.nuscenes.org/) is a widely used open AV dataset (Motional):
multi-camera + LiDAR + radar driving scenes with rich annotations. The lab uses
**nuScenes-mini** (a small subset) so everything runs cheaply. A **scene** is a
~20-second clip; **CAM_FRONT** is the front camera stream M5/M7 use.

### 3.3 Synthetic data & why it matters
Real data can't cover the long tail safely. **Augmentation** (M5: same scene, new
weather) and **scenario generation** (M6: brand-new synthetic clips) multiply
diversity without re-driving. This is the heart of AV 3.0's data strategy.

### 3.4 Embeddings & semantic search (M4)
An **embedding** turns a clip/caption into a vector so that *similar meaning →
nearby vectors*. Store them in a vector index (here **Amazon OpenSearch
Serverless**) and you can search by meaning ("night, pedestrians, crosswalk")
instead of filenames — **k-NN** finds the nearest vectors.

### 3.5 Closed-loop vs. open-loop evaluation (M9 → M10)
- **Open-loop (M9):** feed logged data to the policy, compare its predicted
  trajectory to what actually happened (metric: minADE — average trajectory error).
- **Closed-loop (M10):** put the policy *in a simulator* where its own actions change
  what it sees next — the realistic test. Metrics: collisions, off-road, distance to
  the ground-truth path. The simulator here is **AlpaSim**.

### 3.6 Distributed training (M12) & orchestration (M11) — the "production" concepts
- **Distributed training (M12):** real models are too big for one GPU, so training is
  split across many nodes that sync gradients (**DDP** / `torch.distributed`).
  **SageMaker HyperPod** is AWS's managed cluster for this at scale. *(In the lab M12
  demonstrates the multi-node pattern on small CPU instances — see §5.)*
- **Orchestration (M11):** instead of running notebooks by hand, define the steps as
  a **SageMaker Pipeline** — a repeatable, parameterized DAG (directed acyclic graph)
  where each step starts/stops its own compute and the lineage is tracked.

### 3.7 The AWS platform you'll touch
- **Amazon SageMaker Studio / JupyterLab** — your notebook environment in the browser.
- **Instances & GPUs** — CPU (`ml.t3.medium`) for light work; GPU (`ml.g5.*`,
  `ml.p4d.*`) for the models. You pick the instance from the dashboard; the platform
  loads the matching GPU software image. **GPU time costs real money** — switch back
  to CPU between GPU modules.
- **S3** — where every module reads inputs and writes outputs (this is how data flows
  between modules, and why your results survive an instance change).

---

## 4. What you actually need to know how to do (skills check)

The lab is approachable if you're comfortable with:
- **Basic Python & Jupyter** — running cells top-to-bottom, reading output/errors.
  (You will *run* code, not write much.)
- **Reading a notebook** — following markdown explanations between code cells.
- **Very basic ML vocabulary** — model, inference, training, dataset, GPU.

You do **not** need: deep learning math, CUDA, AWS administration, or prior AV
experience. Anything AWS-specific (picking an instance, opening the workspace) is in
the operational [PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md).

**New to Jupyter?** Skim the 10-minute
[JupyterLab interface tour](https://jupyterlab.readthedocs.io/en/stable/user/interface.html) —
just enough to know "Run cell = Shift+Enter" and "Run ▸ Run All Cells".

---

## 5. Two things to know so you're not surprised on the day

- **M10 and M12 notebooks are CPU** even though they're about GPU-scale ideas. M10
  *visualizes* a closed-loop simulation the admin ran on a GPU host; M12 *submits* a
  real 2-node training job that runs on separate managed instances. This is by
  design — the notebook orchestrates; the heavy compute happens elsewhere.
- **M7 (3D reconstruction) is known-limited.** Its GPU check and data-prep cells
  run and illustrate the stage, but the final 3D-training cell does **not** run on
  the current workshop image (a CUDA build-tooling gap). Treat M7 as an
  optional/demo module; don't be alarmed if the last cell errors.

Suggested path on the day: **M0 (overview) → M1 → M2 → M3**, then branch to whatever
interests you (M5/M6 synthetic data, M9/M10 policy + sim, M4 search, M12/M11
production patterns).

---

## 6. Optional deeper dive (by interest)

Pick the rows that match what you want to understand more deeply. None of this is
required for the workshop.

### The pipeline & the platform
- 📄 **AWS + NVIDIA AV 3.0 blog** (the source of this whole lab) —
  [aws.amazon.com/blogs/industries/…av-3-0…](https://aws.amazon.com/blogs/industries/building-an-end-to-end-physical-ai-data-pipeline-for-autonomous-vehicle-3-0-on-aws-with-nvidia/)
- 📘 **Amazon SageMaker Studio** docs —
  [docs.aws.amazon.com/sagemaker/latest/dg/studio.html](https://docs.aws.amazon.com/sagemaker/latest/dg/studio.html)
- 📘 **SageMaker Pipelines** (M11) —
  [docs.aws.amazon.com/sagemaker/latest/dg/pipelines.html](https://docs.aws.amazon.com/sagemaker/latest/dg/pipelines.html)
- 📘 **SageMaker HyperPod** (M12) —
  [docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod.html](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod.html)

### The models (NVIDIA Cosmos & Alpamayo)
- 🧩 **NVIDIA Cosmos** — the models' home, now **Cosmos 3**:
  [github.com/NVIDIA/Cosmos](https://github.com/NVIDIA/Cosmos)
- 🧩 **Cosmos Cookbook** — the post-training recipes this lab draws from (a
  *separate* repo, now maintenance-only since Cosmos 3):
  [github.com/nvidia-cosmos/cosmos-cookbook](https://github.com/nvidia-cosmos/cosmos-cookbook)
  · browsable docs: [nvidia-cosmos.github.io/cosmos-cookbook](https://nvidia-cosmos.github.io/cosmos-cookbook/)
- 🧩 **Cosmos Reason 1** (captioning, M2) —
  [huggingface.co/nvidia/Cosmos-Reason1-7B](https://huggingface.co/nvidia/Cosmos-Reason1-7B)
- 🧩 **Cosmos Transfer 2.5** (weather aug, M5) —
  [huggingface.co/nvidia/Cosmos-Transfer2.5-2B](https://huggingface.co/nvidia/Cosmos-Transfer2.5-2B)
- 🧩 **Cosmos Predict 2.5** (scenario gen, M6) —
  [huggingface.co/nvidia/Cosmos-Predict2.5-2B](https://huggingface.co/nvidia/Cosmos-Predict2.5-2B)
- 🧩 **Alpamayo 1.5** (VLA policy, M9/M10) —
  [huggingface.co/nvidia/Alpamayo-1.5-10B](https://huggingface.co/nvidia/Alpamayo-1.5-10B)
  (non-commercial)

### Data, simulation, reconstruction
- 🚗 **nuScenes** dataset — [nuscenes.org](https://www.nuscenes.org/)
- 🕹️ **AlpaSim** simulator (M10) — [github.com/NVlabs/alpasim](https://github.com/NVlabs/alpasim)
- 🧊 **Nerfstudio** (M7, 3D reconstruction) — [docs.nerf.studio](https://docs.nerf.studio/)
- 🔎 **Amazon OpenSearch Serverless** vector search (M4) —
  [docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless.html)

### Concepts, if the terms were new
- **Foundation / world models**, **VLM**, **VLA** — see the Cosmos and Alpamayo model
  cards above (each explains its task).
- **Distributed data-parallel training (DDP)** — PyTorch
  [Distributed Overview](https://docs.pytorch.org/tutorials/beginner/dist_overview.html).
- **Vector embeddings & k-NN search** — the OpenSearch vector-search guide above.

### The deepest dive: the module docs in this repo
Each hard module has an engineering write-up explaining exactly how it runs and why:
[COSMOS_M5_M6.md](COSMOS_M5_M6.md) · [ALPAMAYO_M9.md](ALPAMAYO_M9.md) ·
[ALPASIM_M10.md](ALPASIM_M10.md) · [HYPERPOD_M12.md](HYPERPOD_M12.md) ·
[PIPELINE_M11.md](PIPELINE_M11.md). Read these *after* you've run a module and want
the internals.

---

## 7. "Am I ready?" checklist

You're ready for the workshop if you can answer these from Sections 1–3:

- [ ] In one sentence, what is the AV 3.0 data pipeline *for*?
- [ ] Name the five phases: real data → ? → ? → ? → ?
- [ ] What's the difference between a **VLM** (M2) and a **VLA** (M9)?
- [ ] Why does the lab **generate synthetic data** (M5/M6) instead of just using real clips?
- [ ] What's the difference between **open-loop** (M9) and **closed-loop** (M10) evaluation?
- [ ] Why do modules pass data through **S3** rather than in memory?
- [ ] Which module is **known-limited**, and what should you expect? *(M7 — training cell doesn't run.)*

If a question is fuzzy, re-skim that concept in §3 (or the blog in §1). That's all
the preparation you need — see you in [PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md) on
the day.
