# HyperPod (M12) — real distributed training demo, CPU by design

**Status:** M12 runs a **real, distributed PyTorch DDP training job** (SageMaker
Training Job, `instance_count=2`) on **M3's curated captions**, and visualizes the
**measured** per-epoch loss and throughput from the job's own artifacts. Nothing is
simulated. It is **not** a HyperPod cluster — that is separate infrastructure a
notebook cannot provision (see below). M12 demonstrates the *distributed-training
pattern* HyperPod scales, on affordable CPU instances.

## What M12 was, and what it is now

The shipped M12 was **not a hallucinated-API failure** like M5/M6/M9/M10 — every
import and AWS call was real (`sagemaker.pytorch.PyTorch`, `torch.distributed`,
`describe_training_job`). Its problems were different:

| Shipped M12 | Fixed M12 |
|---|---|
| Title said "HyperPod" but used a plain SageMaker Training Job | Honestly framed: distributed *pattern*, HyperPod = concept (stated up front) |
| Declared M3 input but never read it (`estimator.fit()` had no `inputs=`) | `fit(inputs={"training": …})` mounts M3's `curated_captions.json`; the script engineers features from real captions |
| Metrics were `np.random` simulations | Loss/throughput parsed from the job's real `training_log.json` (rank-0 wrote it) |
| `backend="nccl"` hard-coded (needs GPU) | Auto-selects `gloo` (CPU) / `nccl` (GPU) so it runs on CPU **and** GPU |
| Requested `ml.g5.xlarge` × 2 (GPU quota = 1 → would fail) | `ml.m5.xlarge` × 2 (CPU training quota available) |
| Cost was hard-coded constants | Real demo cost from `BillableTimeInSeconds`; HyperPod cost clearly labeled "conceptual" |

## Why CPU (and why that's the right call)

The demo model is a small MLP (`QualityPredictor`, 8 engineered features). The
teaching point is **genuine multi-node `torch.distributed` all-reduce**, not GPU
throughput — a tiny model can't show GPU's advantage. So:

- **`ml.m5.xlarge` × 2, `gloo` backend** — real 2-rank DDP: `init_process_group`,
  `DistributedSampler` sharding, `DDP` gradient all-reduce, rank-0 checkpoint. All
  of it happens for real, for pennies.
- CPU training quota is available out of the box; the demo needs no GPU.

## The CPU-vs-GPU trade-off (for a future GPU run)

The **same training script** runs GPU/`nccl` unchanged — it detects
`torch.cuda.is_available()` and picks the backend + device. To run M12 on GPU:

1. **Raise the GPU training quota.** As of the 2026-07 pretest, in the reference lab account (`us-west-2`; your region may differ — check your own quotas):
   - `ml.g5.xlarge for training job usage` = **1** (quota code `L-B6D80D9C`,
     Adjustable) → request ≥2 for a 2-node job. Approval takes ~days.
   - `ml.m5.xlarge for training job usage` = **30** (why CPU works today).
2. In the notebook set `INSTANCE_TYPE = "ml.g5.xlarge"` (cell-4). No other change —
   the script switches to `nccl` and `cuda` automatically.

| | CPU (`ml.m5.xlarge` × 2) | GPU (`ml.g5.xlarge` × 2) |
|---|---|---|
| Backend | `gloo` | `nccl` (production collective) |
| Quota (reference deploy example: us-west-2, 2026-07) | 30 — available now | 1 — needs raise (~days) |
| Cost | ~$0.23/hr × 2 | ~$1.41/hr × 2 |
| DDP all-reduce verified | ✅ (gloo) | ✅ (nccl) |
| Demo model benefits from GPU | No (tiny MLP) | No (tiny MLP) |

**Bottom line:** both prove "2 nodes really trained distributed." GPU only adds the
real `nccl` path; the small model shows no speed benefit either way. CPU is the
pragmatic choice for the workshop; GPU is a documented, one-line switch if the quota
is raised.

## Why real HyperPod is out of scope for a notebook

SageMaker HyperPod is a **persistent cluster**, created with `aws sagemaker
create-cluster` (Slurm or EKS orchestration), plus VPC/subnets/security groups, FSx
for Lustre shared storage, and EFA networking. Cluster creation alone takes ~20 min
and the cluster then bills continuously — this is long-running, large-scale training
infrastructure, not a notebook cell. (Conceptually the same reason M10's AlpaSim runs
on a GPU EC2 host outside the notebook.) Additionally, `ml.p4d.24xlarge for cluster
usage` and `... for training job usage` are both **0** in this lab account, so a real
HyperPod p4d cluster can't be created here regardless. M12 therefore teaches the
pattern HyperPod scales and explains HyperPod's added value (auto node replacement,
FSx, Slurm/EKS scheduling, EFA/NCCL) rather than provisioning one.

## Output artifacts

- `users/<profile>/m12/training_metadata.json` — job summary, data source
  (`real_m3` | `synthetic`), measured per-epoch metrics, HyperPod notes.
- `users/<profile>/m12/<job-name>/output/model.tar.gz` — checkpoint +
  `training_log.json` (the real metrics the notebook plots).
- `users/<profile>/m12/input/curated_captions.json` — the M3 data staged as the
  training channel (only when M3 has run).

## Verified run

**Local dry-run (2026-07-13, $0)** — the exact embedded `train_distributed.py`,
run as a real 2-process gloo DDP job (`torchrun --nproc_per_node=2`) on M3's real
`curated_captions.json` (`ky-5-34x1bx`, 12 captions):

```
Backend: gloo | world_size: 2 | nodes: 2
Dataset: REAL M3 captions | samples: 12 | feature_dim: 8
Epoch 1/5 | Loss: 0.134977 ...
Epoch 5/5 | Loss: 0.000053 | Throughput: 7 samples/s
Checkpoint + training_log.json saved
```

This confirms the parts that matter: genuine 2-rank `torch.distributed` init +
all-reduce (gloo), real M3 caption ingestion (`dataset: real_m3`), a real per-epoch
`training_log.json` whose keys match the notebook's cell-6 parser, and a loadable
checkpoint (`model_state_dict` + `optimizer_state_dict` + `final_loss`). Loss falls
0.135 → 5.3e-5 — measured, not simulated.

**Managed run verified (2026-07-14, Studio Run-All, participant profile ky-5-34x1bx):**
`estimator.fit()` on **`ml.m5.xlarge`×2** completed — `Training job completed`,
320 billable seconds, **`Data source: real_m3`** (trained on M3's curated captions
via the `training` channel), model artifact at
`users/ky-5-34x1bx/m12/.../output/model.tar.gz`, demo cost ~$0.02. Full M3→M12→
metrics pipeline confirmed end-to-end in the real Studio environment.

### Six real bugs the participant Run-All surfaced (none reproducible locally)
The Studio kernel + managed training job exposed a chain of issues a local dry-run
could never hit:
1. **SDK v3 kernel** — SageMaker Distribution ships Python SDK v3 (modular
   `sagemaker.core`/`sagemaker.train`, no top-level `Session` or
   `sagemaker.pytorch.PyTorch`). Fix: cell-1 pins v2 (`sagemaker>=2.257.2,<3`).
2. **v2/v3 in-memory mix** — pip swaps files but the kernel keeps v3 imported
   (`cannot import name ModelMetrics`). Fix: cell-1 auto-restarts the kernel after
   installing v2 (re-run cell-1 once after the restart).
3. **`torch_distributed` is GPU/Trainium-only** in the SDK — rejected on CPU
   (`ValueError: ... only for GPU and Trainium`). Fix: use `distribution={"mpi":
   {"processes_per_host": 1}}`.
4. **exec role write scope is `users/*`** — the estimator's default code upload to
   the bucket root `<job>/source/...` is denied. Fix: `code_location=
   s3://<bucket>/users/<profile>/m12/code`.
5. **`iam:PassRole` + `sagemaker:CreateTrainingJob` missing** — the exec role was
   built for Studio app management, not training-job submission. Fix: added a
   scoped `SageMakerTrainingJobs` (av30-m12-* ARN) + self-only `PassRole`
   (`iam:PassedToService=sagemaker.amazonaws.com`) statement in
   `infra/av30_constructs/sagemaker.py` and deployed.
6. **MPI rank order ≠ SM_HOSTS order → rendezvous hang.** The first CPU attempt
   derived rank/master from `SM_HOSTS` (sorted), but MPI's rank-0 host was
   `algo-2` while `SM_HOSTS[0]` was `algo-1`, so `dist.init_process_group` hung
   forever at "Waiting for orted process". Fix: read rank/world_size from
   **mpi4py** (`MPI.COMM_WORLD`) and broadcast rank-0's own hostname as
   `MASTER_ADDR`.

**GPU note still applies:** on `ml.g5.xlarge` you'd switch the distribution back to
`torch_distributed` (torchrun) and the script auto-selects nccl; the mpi4py
rendezvous above is the CPU path.
