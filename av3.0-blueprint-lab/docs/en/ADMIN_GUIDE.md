# AV 3.0 Blueprint Lab — Admin Guide

Everything the workshop admin does **before, during, and after** the event, in the
order you'll do it. Participants only need their dashboard link (see
[PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md)); everything else is on you.

> **Golden rule:** all the heavy, gated, GPU, and credential work is the admin's.
> If you finish the pre-event checklist below, a participant can run M0–M12 from a
> browser with **no AWS account, no Hugging Face token, and no license clicks**
> (the one exception is the optional M10 self-run — see §7).

---

## 0. What you are operating

- **One CDK stack** (`Av30PlatformStack`) → VPC, KMS-encrypted S3 (shared + per-user
  workspace), DynamoDB, Cognito, WAF, API Gateway + Lambda, 2 CloudFront dashboards
  (admin + user), and a SageMaker Studio domain whose participants all share ONE
  execution role, `av30lab-sagemaker-execution-role` (not one role per user). Isolation
  between participants comes from IAM policy conditions comparing a space's owner against
  `${sagemaker:UserProfileName}` — see the residual-risk note in
  `infra/av30_constructs/sagemaker.py`.
- **Two S3 buckets** (names are derived from **your** account + region — the
  examples in this guide use account `<aws-account-id>` / `us-west-2`, the reference
  deployment; substitute your own — see §1.5):
  - `av30lab-shared-data-<account>-<region>` — models, datasets, notebook templates, M10 reference.
  - `av30lab-user-workspace-<account>-<region>` — one `users/<id>/` prefix per participant.

> **Note on the IDs in this guide.** Everywhere you see `<aws-account-id>` or
> `us-west-2` (bucket names, ARNs, quota "current" values, CLI examples), those
> are from the reference deployment. They are **not** hard-coded in the stack —
> the account is taken from your credentials and the region from `$AWS_REGION`
> at deploy time (§5). Pick yours in §1.5, then read the examples with your own
> values substituted.
- **13 notebooks M0–M12**. Most are participant-self-service; a few need one-time
  admin pre-work (models, datasets, the M10 reference run). See the matrix in §4.

---

## 1. Pre-event timeline

| When | Task | Why the lead time |
|---|---|---|
| **Day −7** | Request GPU + job quota increases (§2) | Approvals take 24–48 h, sometimes longer |
| **Day −7** | Accept all gated HF licenses on your admin account (§3) | Instant, but easy to forget one |
| **Day −3** | `cdk bootstrap` + `deploy.sh` (§5) | ~25 min; leaves time to fix issues |
| **Day −3** | Stage nuScenes + pre-cache models + HF offline cache (§6) | 30–90 min of background transfers |
| **Day −2** | Run the M10 AlpaSim reference eval on EC2 (§6.4), if using M10 | ~$30, tens of min–2 h on a GPU box |
| **Day −1** | Upload notebook templates, smoke-test one user end-to-end (§8) | Catches provisioning/quota gaps |
| **Day 0** | Provision participants, hand out dashboard links (§9), monitor (§10) | — |
| **Day +0** | Delete users, **revoke HF token, rotate NGC key** (§12) | Security hygiene |

---

## 1.5. Choosing your AWS account and Region (do this first)

The platform is **account- and region-agnostic** — nothing in the stack pins the
reference account (`<aws-account-id>`) or region (`us-west-2`). Everything derives at
deploy time: the **account** from your AWS credentials, and the **region** from the
`AWS_REGION` you export in §5. Decide both before you request quotas (§2), because
GPU quotas and gated-model availability are per-account **and** per-region.

**Choosing the account**
- Use an account **you are an admin of** (or have IAM rights to create roles,
  Cognito pools, CloudFront, VPCs, and SageMaker domains). `deploy.sh` runs
  `cdk bootstrap`, which needs elevated permissions once per account+region.
- Prefer a **dedicated / sandbox** account: the stack creates a Studio domain,
  buckets, and a WAF, and teardown (`scripts/teardown.sh`) is cleanest when it
  isn't sharing the account with unrelated production resources.
- Whatever account your credentials point at when you run `deploy.sh` is where it
  lands. Confirm before deploying:
  ```bash
  aws sts get-caller-identity --query Account --output text
  ```
  This account id is what fills the `<account>` in every bucket name and ARN.

**Choosing the Region** — this matters more than the account, because it gates GPU
capacity and model access:
- **GPU availability varies by region.** The GPU families this lab uses (`g5`,
  `g6`, and optionally `p4d`) are **not** in every region, and quota approvals
  are per-region. Pick a region with strong GPU capacity — `us-west-2` (Oregon)
  and `us-east-1` (N. Virginia) are the safest.
- **Latency:** closer to the participants is nicer for the interactive Studio UI,
  but capacity should win the tie — a region where you can't get GPUs is useless.
- **Data residency / org policy:** if your organisation restricts regions, choose a
  compliant one that still has the GPU families above.
- **Model + dataset staging is region-local.** The HF/model caches and nuScenes are
  staged into the shared bucket **in your chosen region** (§6); if you later move
  regions you must re-stage (see the "Region portability" note in `README.md`).

**Verify a candidate region has the capacity you need** before committing (empty
output for a family means it isn't offered there):
```bash
export AWS_REGION="us-west-2"     # your candidate
# GPU instance types offered for SageMaker Studio apps in this region:
aws service-quotas list-service-quotas --service-code sagemaker --region "$AWS_REGION" \
  --query "Quotas[?contains(QuotaName,'Studio JupyterLab Apps running on ml.g6') || contains(QuotaName,'Studio JupyterLab Apps running on ml.g5')].{Name:QuotaName,Current:Value,Code:QuotaCode}" \
  --output table
```

Once account + region are settled, export `AWS_REGION` (§5 uses it throughout),
request the quotas in §2 **in that region**, and stage caches (§6) **in that
region**. Changing either later means re-bootstrapping, re-quota-ing, and
re-staging — so lock it in now.

---

## 2. Service quotas (request Day −7)

Two families of quota matter. The README's quota table covers the first; the
**job quotas** below are easy to miss and block M12/M11 for a full room.

### 2a. Studio JupyterLab App quotas (interactive notebooks)
Search "**Studio JupyterLab Apps running on**" in the Service Quotas console. The table
below is exactly the set the **user dashboard's Instance Options** offers (recommended +
alternatives), and the API enforces it: `cdk synth` reads the list from
`web/user/src/data/pipeline-config.ts` and keeps the types this region sells, and
`change_instance` refuses any other type with a 400 before touching the running app, even
when the API is called directly. To change the list, edit that file and redeploy the stack.
Quota **codes are region-independent** (verified identical across us-west-2 /
ap-northeast-2 / eu-west-1); the **values are not**, and neither is which types have a
quota at all.

> **The cap covers the dashboard's API, not Studio's own controls.** The participant
> execution role can still start an app from inside Studio, and there a type outside the
> list is stopped only by its quota. Do not request quota for a type you do not mean to
> offer (see the p4d row).

**GPU workhorse: `ml.g5.12xlarge` (4× A10G, 96 GB).** It is what the dashboard now
recommends for M2, M3 and the four heavy modules (M5, M6, M8, M9), for reasons that are
all measured: it has the *identical* geometry to `ml.g6.24xlarge` (`describe-instance-types`
reports 4 GPUs × 22,888 MiB for both, so every per-GPU module gate takes the same branch),
it is cheaper in both regions ($7.09 vs $8.34 in us-west-2; $8.72 vs $10.26 in
ap-northeast-2), it has a higher quota (5 vs 2 in us-west-2, 5 vs **0** in ap-northeast-2),
and the lab's captured passes are reachable from it. Be precise about what is
measured. `examples/notebooks-with-outputs.tar.gz` now holds a full M0–M12 run on
**4x NVIDIA A10G** — i.e. g5.12xlarge itself — with M9 at minADE 0.3779, `Status: PASS`.
So this exact instance is directly measured; it no longer rests on the geometry argument.
(The previous bundle recorded the same pipeline on **4x NVIDIA L4** with M9 at minADE
0.3805, and `docs/en/ALPAMAYO_M9.md:181-187` separately records M9 on **8x A10G**
/ g5.48xlarge. Those remain real measurements, they are simply no longer what the
published bundle contains.) One caveat carried by that run: M7's novel-view render
finished with `rc=1` and produced **0 frames** — training completed, the render did not.
The reason to prefer g5.12xlarge is quota and price.
`ml.p4d.24xlarge` is the dashboard's only native-resolution / full-720p path; read its row
below before requesting quota for it.

> **The `us-west-2` column below is not your region.** Quota is a per-(account × region)
> fact: the entire `ml.g6.*` family is sold in ap-northeast-2 with a quota of **0**, and
> `ml.g7e.*`/`ml.p5.*` are not sold there at all. Run
> `./scripts/check_quotas.py --region <target>` for the real numbers — it prints the exact
> `request-service-quota-increase` command for each shortfall. (A quota-0 type is now
> rejected by the dashboard up front rather than accepted and then failing to start.)

| Instance | Quota code | us-west-2 (2026-09) | Min for a 10-person room | Role in the dashboard |
|---|---|---|---|---|
| ml.t3.medium | L-71FAF417 | 2500 | ≥20 | **Recommended** for all CPU notebooks (M0, M1, M10, M4, M12, M11) |
| ml.t3.large | L-2733D4D5 | 30 | ≥0 | CPU alternative |
| ml.t3.xlarge | L-61F9C762 | 30 | ≥0 | CPU alternative (M1) |
| ml.m5.large | L-3BDCD216 | 11 | ≥0 | CPU alternative |
| ml.m5.xlarge | L-77B8159A | 11 | ≥0 | CPU alternative (M4) |
| ml.g5.xlarge | L-988CE6C5 | 5 | ≥5 | **Recommended** for M7 (Nerfstudio) |
| ml.g5.2xlarge | L-F73C7DB9 | 5 | ≥0 | M7 alternative |
| ml.g5.4xlarge | L-81940D85 | 5 | ≥0 | M7 alternative |
| **ml.g5.12xlarge** | **L-8D2ED7BF** | **5** | **≥5** | **Recommended workhorse — M2, M3, M5, M6, M8, M9 (4× A10G, 96 GB)** |
| ml.g5.24xlarge | L-F087CCFC | 2 | ≥1 | M2/M3/M5–M9 alternative |
| ml.g5.48xlarge | L-83AB5D73 | 2 | ≥1 | M2/M3/M5–M9 alternative / OOM fallback |
| ml.g6.xlarge | L-AABA5942 | 5 | ≥0 | M7 alternative (L4) — **0 in ap-northeast-2** |
| ml.g6.2xlarge | L-92D1521D | 5 | ≥0 | M7 alternative (L4) — **0 in ap-northeast-2** |
| ml.g6.4xlarge | L-692B8304 | 5 | ≥0 | M7 alternative (L4) — **0 in ap-northeast-2** |
| ml.g6.12xlarge | L-962247BA | 2 | ≥0 | M2/M3 capacity fallback (4× L4, 96 GB) — **0 in ap-northeast-2** |
| ml.g6.24xlarge | L-8ACE1754 | 2 | ≥0 | M2/M3 alternative (4× L4, 96 GB) — same geometry as g5.12xlarge but dearer; **0 in ap-northeast-2** |
| ml.p4d.24xlarge | L-AD63F1D2 | 2 | 0 unless intended | M2, M3, M5, M6, M8, M9 alternative — the only native-res path (8× A100, ~$25.25/hr in us-west-2). **Defaults to 0; leave it there unless you mean to offer it** — at 0 the dashboard refuses it before touching the running app |

> **Not offered: `ml.g7e.*`, `ml.p5.*`, `ml.g6.48xlarge`** and every other type missing
> from the table. `change_instance` rejects them with a 400, so the dashboard needs no quota
> for them. g7e would be the cheapest native-resolution path (one 96 GB card at ~$4.20/hr),
> but it is not sold for Studio in ap-northeast-2 and no module has been run on it in this
> lab, so it is not on the list. Their quotas still matter for the Studio path above.

Sizing the room: request the **recommended** instance for each module at ≥ the
number of concurrent participants, and at least the minimum shown for the one or
two fallbacks you intend to steer people to (capacity errors surface an
alternative in the dashboard). You do **not** need quota for every alternative —
only the ones you'll actually direct the room to use. If you standardise the GPU
modules on **g5.12xlarge** (recommended — and the only heavy-module recommendation that
is non-zero in both us-west-2 and ap-northeast-2), request that one to ≥ your headcount
and leave p4d at its default of 0 unless you mean to offer it.

### 2b. SageMaker **job** quotas (M12 and M11 — the ones people forget)
M12 submits a real **training job** and M11 runs real **processing jobs** on
separate managed instances (not the notebook's instance). These have their own
quotas:

| Quota | Code | Verified value (reference deploy example: us-west-2) | Needed by |
|---|---|---|---|
| ml.m5.xlarge for **training** job usage | L-CCE2AFA6 | 30 | M12 (needs ≥2 — it's a 2-node job) |
| ml.m5.xlarge for **processing** job usage | L-0307F515 | 16 | M11 (needs ≥1 — sequential 3-step DAG) |

Both are comfortably above the workshop's needs today, but **verify** — if either
is 0 in your account, M12/M11 fail at job submission even though the notebook opens.
Note `ml.g5.*` **processing** job quota is 0 here; that's fine because M11 runs on
CPU by design.

```bash
# Check everything at once:
aws service-quotas list-service-quotas --service-code sagemaker --region "$AWS_REGION" \
  --query "Quotas[?contains(QuotaName,'Studio JupyterLab Apps') || contains(QuotaName,'for training job') || contains(QuotaName,'for processing job')].{Name:QuotaName,Value:Value,Code:QuotaCode}" \
  --output table

# Request an increase (the two types the dashboard actually recommends, to 10 for a full room):
aws service-quotas request-service-quota-increase \
  --service-code sagemaker --quota-code L-8D2ED7BF --desired-value 10 --region "$AWS_REGION"   # ml.g5.12xlarge
aws service-quotas request-service-quota-increase \
  --service-code sagemaker --quota-code L-988CE6C5 --desired-value 10 --region "$AWS_REGION"   # ml.g5.xlarge
```

> The quota **codes** above are the same in every region; run these against
> **your** `$AWS_REGION` (§5) so you're requesting capacity where you'll actually
> deploy. GPU availability varies by region — see §1.5 for choosing one.

---

## 3. Gated Hugging Face + NGC licenses (accept Day −7)

On **your admin HF account**, click "Agree and access repository" on each. This is
the only place licenses are accepted — participants never see this.

| Repo | Needed by | License |
|---|---|---|
| nvidia/Cosmos-Reason1-7B | M2 | NVIDIA Open Model (not gated, but log in) |
| nvidia/Cosmos-Guardrail1 | M5, M6 | NVIDIA Open Model |
| nvidia/Cosmos-Transfer2.5-2B | M5 | NVIDIA Open Model |
| nvidia/Cosmos-Predict2.5-2B | M6 | NVIDIA Open Model |
| nvidia/Alpamayo-1.5-10B | M9, M10 | **Non-commercial** (research/eval only) |
| nvidia/Cosmos-Reason2-8B | M9, M10 (hidden Alpamayo backbone) | NVIDIA Open Model |
| nvidia/PhysicalAI-Autonomous-Vehicles | M9 (demo clip) | NVIDIA AV Dataset (12-month expiry) |
| nvidia/PhysicalAI-Autonomous-Vehicles-NuRec | M10 (AlpaSim scenes) | NVIDIA AV NuRec Dataset |

**M10 also needs NGC** (separate from HF): the NuRec renderer image
`nvcr.io/nvidia/nre/nre-ga:26.04`. Get a key at
`https://org.ngc.nvidia.com/setup/api-key`. (In testing this image was
anonymously pullable, but have a key ready in case that changes.)

> Set `export HF_TOKEN=hf_...` once you've accepted everything; you'll use it in §6.

---

## 4. Per-module admin pre-work matrix

This is the heart of the guide — **which modules need admin work vs. run themselves.**

| Module | Compute (what participant sees) | Admin pre-work required | Doc |
|---|---|---|---|
| M0 Overview | CPU t3.medium | none | — |
| M1 Data Exploration | CPU t3.medium | Stage nuScenes-mini (§6.1) | — |
| M2 Cosmos Reason | GPU g5.12xlarge (or g6.24xlarge) | Pre-cache model to `model-cache/` (§6.2) | — |
| M3 Cosmos Curator | GPU g5.12xlarge (or g6.24xlarge) | (uses M2 output; no extra cache) | — |
| M4 OpenSearch | CPU t3.medium | (uses M2 output; no extra cache) | — |
| M5 Cosmos Transfer | GPU g5.12xlarge (or p4d.24xlarge for 720p) | HF **offline cache** to `hf-cache/hub/` (§6.3) | [COSMOS_M5_M6.md](COSMOS_M5_M6.md) |
| M6 Cosmos Predict | GPU g5.12xlarge (or p4d.24xlarge for native) | HF offline cache (§6.3) | [COSMOS_M5_M6.md](COSMOS_M5_M6.md) |
| M7 Nerfstudio | GPU g5.xlarge (or g6.xlarge) | gsplat CUDA build runs per-session via `scripts/setup_gsplat_env.sh` (§11) | See §11 below |
| M8 Cosmos Reason SFT | GPU g5.12xlarge (or g6.24xlarge) | (reuses M2's `model-cache/cosmos-reason1/`; no extra cache) | — |
| M9 Alpamayo VLA | GPU g5.12xlarge (or p4d.24xlarge) | HF offline cache **+ demo clip** (§6.3) | [ALPAMAYO_M9.md](ALPAMAYO_M9.md) |
| M10 AlpaSim | CPU t3.medium (visualizer) | **Run reference eval on EC2 once** (§6.4) | [ALPASIM_M10.md](ALPASIM_M10.md) |
| M11 Pipeline | CPU t3.medium (runs real SageMaker Pipeline) | none (job quota §2b) | [PIPELINE_M11.md](PIPELINE_M11.md) |
| M12 HyperPod | CPU t3.medium (submits real DDP job) | none (job quota §2b) | [HYPERPOD_M12.md](HYPERPOD_M12.md) |

**Bottom line:** the required one-time admin caches are **nuScenes (M1) + model-cache
(M2) + hf-cache (M5/M6/M9) + M9 demo clip**, plus the **M10 reference run** if you're
running M10. M12 and M11 need **no cache** — just the job quotas in §2b.

---

### 4b. One-minute check that unlocks a real IAM tightening (free)

`CreateApp` / `DeleteApp` are currently granted on `resources=["*"]` for the shared
execution role. That means a participant with a terminal can create or delete an app on
**someone else's** space via the CLI (the dashboard offers no such path). Narrowing it to
an owner condition on `${sagemaker:UserProfileName}` is the fix — but only if that policy
variable actually resolves at request time, and **you cannot find that out by simulation**:

* `iam:SimulateCustomPolicy` does **not** substitute `${sagemaker:*}` variables. It returns
  `implicitDeny` for every case containing one, and `allowed` with literals — so it says
  nothing either way.
* Assuming the role from outside Studio does not help either: with no app context the
  variable is empty, and an unresolved variable in a `Resource` matches nothing, so the
  request fails closed. Also uninformative.

The only reliable test is the live one, and it costs nothing:

1. Open a participant's Studio space **as that participant** (or from the admin console
   acting on their profile) and click **Run space**, then **Open JupyterLab**.
2. **No `AccessDenied`** ⇒ the variables resolve at request time ⇒ it is safe to change
   `CreateApp`/`DeleteApp` in `infra/av30_constructs/sagemaker.py` from `resources=["*"]`
   to the same owner condition already used by `SageMakerOwnPrivateSpaceUpdate`.
3. An `AccessDenied` ⇒ do **not** narrow it. Unresolved policy variables fail closed, so
   tightening without this evidence locks every participant out of their own workspace.

Record the outcome here when you run it, so the next admin does not have to re-derive it.

---

## 5. Deploy the platform (Day −3)

> **Region is explicit, and a redeploy is guarded.** Pass `--region` — there is no default
> anywhere in the deploy path. On an UPDATE of an existing stack, `deploy.sh` now reads the
> live state and **refuses** rather than doing something destructive silently: it stops if
> the deploy would change the stack's `Owner` tag (which replaces the Studio domain, losing
> every participant workspace and orphaning the EFS), and it stops on any wrong combination
> of `HOSTED_UI_DOMAIN_EXISTS` (either declaring a Cognito domain that already exists
> unmanaged, or deleting one the stack does own). Each refusal prints the exact command to
> re-run. A brand-new region needs none of these flags.
> To stand up an ADDITIONAL region, see [../en/ADDING_A_REGION.md](ADDING_A_REGION.md).


```bash
# Required env
export ADMIN_EMAIL="you@example.com"       # becomes the Cognito admin + SNS alert target
export REGION="us-west-2"                  # YOUR chosen region (§1.5) — passed explicitly below
export AWS_REGION="$REGION"                # the seeding scripts in §6 read this
export HF_TOKEN="hf_..."                    # for the caching steps in §6
# Optional: restrict the admin API to your IP/CIDR (participant routes stay open)
export ADMIN_IP_ALLOWLIST="203.0.113.0/24" # default 0.0.0.0/0 = no WAF

# One-time CDK bootstrap (per account+region)
cd infra && source .venv/bin/activate && pip install -r requirements.txt
npx cdk bootstrap aws://$(aws sts get-caller-identity --query Account --output text)/$REGION
cd ..

# Generate this region's instance rate table (REQUIRED — the Lambdas raise at import
# without it rather than quoting another region's prices)
./scripts/refresh_instance_rates.py --region "$REGION" --merge

# Deploy stack + build/upload both dashboards (~25 min). Region is explicit.
./scripts/deploy.sh --region "$REGION"
```

`deploy.sh` passes `ADMIN_EMAIL`, `ADMIN_IP_ALLOWLIST` and the resolved region to CDK via
`--context` (**not** env vars). If you skip `deploy.sh` and run `cdk deploy` by hand you must
pass `--context admin_email=...` — omitting it does not fail, it silently replaces your alert
email with `placeholder@example.com` and **deletes the real subscription**, including a
confirmed one. It prints the **Admin Dashboard URL** and **API endpoint** at the end, plus a
GPU-quota pre-flight and a warning if the account has no account-wide budget.

**What `ADMIN_IP_ALLOWLIST` restricts.** It attaches a WAF WebACL to the API Gateway stage
that blocks the **admin API** for any IP outside the list. The participant routes
(`/presigned-url/{userId}`, `/sessions/{id}/instance-type|storage|progress|app-status`,
`/modules/{id}/instance-options`) are allowed from any IP, because the participant dashboard
runs in each participant's browser and the notebooks report progress from SageMaker-managed
egress. Those routes still require the participant's token. Neither CloudFront distribution
has a WAF, so from an IP outside the list the admin dashboard and the Cognito sign-in page
still load, but every data call fails with **"Failed to fetch"**. In the browser's Network
tab the `OPTIONS` preflight shows **403**: every admin call sends `Authorization` and a JSON
`Content-Type`, so the browser always preflights. The fix is to add your own IP. **Do not add
participant or SageMaker IP ranges**: they need nothing, and listing them only opens the
admin API's network path to those addresses. Export the same value on every later deploy;
running `deploy.sh` without it falls back to `0.0.0.0/0` and removes the WAF.

**Create the admin login** (username must be the email — Cognito uses email as the
sign-in alias):
```bash
aws cognito-idp admin-create-user \
  --user-pool-id <POOL_ID_FROM_DEPLOY_OUTPUT> \
  --username "$ADMIN_EMAIL" \
  --user-attributes Name=email,Value=$ADMIN_EMAIL Name=email_verified,Value=true \
  --temporary-password 'TempPass1!' --region $AWS_REGION
```
Log in to the admin dashboard; you'll be forced to set a new password.

---

## 6. One-time data + model staging (Day −3 to −2)

All of these write to the **shared** bucket. Steps 6.3/6.4 must run on a machine
that can reach the gated repos with your token.

### 6.1 nuScenes-mini (M1/M2/M7)
```bash
./scripts/stage_nuscenes.sh    # pulls the public AWS Open Data mirror → datasets/nuscenes-mini/
```

### 6.2 Simple model cache (M2/M3)
```bash
pip install huggingface_hub && hf auth login --token "$HF_TOKEN"
./scripts/cache_models.sh      # → s3://<shared>/model-cache/ (Cosmos-Reason1-7B, Transfer2.5, Predict2.5)
```

### 6.3 HF offline cache (M5/M6/M9) — the "no participant token" trick

> **`cache_models.sh` does NOT build `hf-cache/hub/`** — use `scripts/cache_hf_tree.sh`.
> Until 2026-09-26 nothing in this repo produced the tree at all: every `hf-cache`
> reference in `scripts/` read *from* S3 and never wrote to it, so the only recipe was a
> manual ritual on a GPU app (now retired — see the warning below). `cache_models.sh` is
> not a substitute: it writes a different prefix (`model-cache/`) in a different layout
> (flat `hf download --local-dir`, not `models--org--name/snapshots/<sha>/…`).
>
> Consequences, both of which have bitten:
> * **For a new region, copy it — do not rebuild it.** `aws s3 sync` bucket-to-bucket from a
>   seeded region (see [ADDING_A_REGION.md](ADDING_A_REGION.md) §4). ap-northeast-2 was
>   seeded with `cache_models.sh` instead on 2026-09-26 and shipped with M5/M6/M9/M10 dead.
> * **Verify, never infer.** `./scripts/check_seeding.sh --region <r>` asserts the five
>   `models--nvidia--*` directories the runtime globs test plus the specific pinned
>   `tokenizer.pth` blob. A green `cache_models.sh` run proves nothing about this prefix.

M5/M6/M9 load gated checkpoints through HF's **own cache layout** at runtime
(M9 also pulls a hidden Cosmos-Reason2-8B backbone). `setup_cosmos_env.sh` restores
`hf-cache/hub/` into `HF_HOME` and sets `HF_HUB_OFFLINE=1`, so participants run offline
with no token. Seed it **from your admin workstation, with admin credentials**:
```bash
# Region #2 onward: copy byte-exact from a region that already works (README step 6b).
aws s3 sync s3://av30lab-shared-data-<account>-<seeded-region>/hf-cache/ \
            s3://<shared>/hf-cache/ --source-region <seeded-region> --region "$AWS_REGION"
# First region: build the tree from the pinned manifest (no GPU, ~65 GiB scratch).
AWS_REGION="$AWS_REGION" HF_TOKEN=hf_... ./scripts/cache_hf_tree.sh
./scripts/check_seeding.sh --region "$AWS_REGION"
```

**`.no_exist` markers (M9).** `check_seeding.sh` also counts a few 0-byte
`models--*/.no_exist/<revision>/<file>` files under `Alpamayo-1.5-10B` and
`Cosmos-Reason2-8B`. HuggingFace writes one when an *online* load finds that a file does
not exist upstream. A download never creates them, so `cache_hf_tree.sh` creates only the
ones `scripts/hf_cache_manifest.tsv` records as `no_exist` rows. A bucket-to-bucket copy
brings them along. If the manifest records none, a tree built by `cache_hf_tree.sh` alone
shows 15/16 and 17/22 objects for those two repos, and the check fails. Whether M9
actually fails offline without them has not been tested, so the check keeps counting
them. Record them once, then upload only the markers (no token, no download):
```bash
# From a tree that has them, e.g. a region seeded by the old GPU-app procedure (read-only):
aws s3 ls s3://av30lab-shared-data-<account>-<seeded-region>/hf-cache/hub/ --recursive \
  --region <seeded-region> | ./scripts/cache_hf_tree.sh --record-markers
AWS_REGION="$AWS_REGION" ./scripts/cache_hf_tree.sh --markers-only
```
With no such tree, an online M9 run on your GPU app writes them: see steps 1 and 3 of
the clip procedure below. `--record-markers` reads key names only, never object contents.
It refuses a marker that is not empty or that would hide a file the manifest downloads,
and it skips revisions the manifest does not pin. Keep the updated manifest (commit it
in your copy of the repo), so the next first region gets the markers from
`cache_hf_tree.sh` directly.

> **Never write `hf-cache/` from a Studio terminal, and never paste admin AWS keys into
> one.** Earlier versions of this guide synced the cache up from a GPU JupyterLab app,
> which needed the SageMaker execution role to write `hf-cache/*`. That role is shared by
> every participant, and every participant's kernel loads this prefix: M9 opens
> `hf-cache/alpamayo-demo/*.pt` with `torch.load(weights_only=False)`, which unpickles the
> file and so runs any code in it. One participant could therefore run code as every
> other participant. The write grant is gone, so from a Studio app `aws s3 cp`/`sync` to
> `hf-cache/` now fails with `AccessDenied`, by design. Working around that with admin
> keys in the terminal is worse: the app's home directory is synced from
> `users/<profile>/` in S3 at every start, so a `.bashrc` planted there would capture them.

> **Upgrading a stack deployed before this change.** Until now every participant could
> write `hf-cache/*`, so do not trust that prefix until you have audited it. Do the audit
> before you rely on it, and before you use the region as the source of a copy: a copy
> carries any replaced object into the new region, and `check_seeding.sh --source-region`
> cannot notice, because it only compares the two regions with each other. The shared
> bucket is versioned, so a read-only listing shows every write. Use read-only
> credentials:
> ```bash
> # Noncurrent versions and delete markers: each one is a write after the first upload.
> aws s3api list-object-versions --bucket <shared> --prefix hf-cache/ --region <r> \
>   --query 'Versions[?IsLatest==`false`].[LastModified,Key]' --output text
> aws s3api list-object-versions --bucket <shared> --prefix hf-cache/ --region <r> \
>   --query 'DeleteMarkers[].[LastModified,Key]' --output text      # "None" = no deletes
> # Current versions, newest first: anything after your original seed needs a look.
> aws s3api list-object-versions --bucket <shared> --prefix hf-cache/ --region <r> \
>   --query 'Versions[?IsLatest].[LastModified,Key]' --output text | sort -r | head -20
> ```
> Investigate every hit. The pickle-format files matter most, because loading one runs
> code: `alpamayo-demo/*.pt`, and in the hub tree Cosmos-Transfer2.5 and
> Cosmos-Predict2.5's `*_ema_bf16.pt`, Predict2.5's `tokenizer.pth`, and Guardrail1's
> `safety_filter.pt` and `Resnet50_Final.pth`. Whatever the audit shows, produce and
> publish `alpamayo-demo/*.pt` again by the procedure below instead of inheriting it.
> Deleting object versions is destructive: get separate approval before you do it.

**M9 also needs a demo clip.** Its dataset can't be read offline, and the clip has to be
produced inside the `a1_5` venv on a GPU. So the GPU app *produces* the clip and your
workstation *publishes* it. Do this before you provision participants (§9). If you
copied `hf-cache/` from a seeded region, the clip came with it (`check_seeding.sh`
confirms it), so skip steps 1-3 unless you are publishing it again. Do that once if the
source region was deployed before this change (see the upgrade note above).

**Before you start, make sure no participant can write to your workspace.** Produce the
clip only before any participant profile exists, or once the user-workspace bucket is
isolated per user. Until then the execution role every participant shares can write every
`users/<profile>/` prefix, and your app copies `users/<your-profile>/` into its home
directory at every start. A planted `.bashrc`, IPython startup file or replaced
`scripts/alpamayo_save_clip.py` would then control both the `.pt` and the sha256 printed
for it, and would see the `HF_TOKEN` you export. The hash only proves that the file did
not change after it left the app. On a stack that already ran a cohort, delete the
participants' profiles first and use a fresh user profile of your own: files planted
under your old prefix stay there, and a new space under the same profile still copies
that prefix.

1. On a GPU JupyterLab app of your own profile, with an `HF_TOKEN` whose account has
   accepted the licenses (§3):
   ```bash
   export HF_TOKEN=hf_...
   bash scripts/setup_cosmos_env.sh alpamayo     # build the a1_5 venv
   source /mnt/sagemaker-nvme/cosmos-work/alpamayo_env.sh
   unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE     # this save must be online
   python scripts/alpamayo_save_clip.py --clip 030c760c-ae38-49aa-9ad8-f5650a545d26 \
     --t0-us 5100000 --out /mnt/sagemaker-nvme/m6_work/clips
   ```
   The script ends by printing `sha256  <hash>  030c760c-….pt`. **Copy that hash by hand
   into your own notes.** Do not save it as a file in S3 next to the clip, where it could
   be replaced together with the clip.

   *Only if you need the `.no_exist` markers (see above):* in the same terminal, run one
   inference online, then stage the markers it wrote. They are empty files, and only
   their names are used.
   ```bash
   python scripts/alpamayo_infer.py \
     --clips /mnt/sagemaker-nvme/m6_work/clips/030c760c-ae38-49aa-9ad8-f5650a545d26.pt \
     --out /mnt/sagemaker-nvme/m6_work/out
   aws s3 sync /mnt/sagemaker-nvme/hf/hub "s3://$USER_BUCKET/users/$USER_PROFILE/staging/hub-markers/" \
     --exclude '*' --include '*/.no_exist/*' --exclude '*/snapshots/*'
   ```
2. Move the `.pt` off the app, either way:
   * `cp /mnt/sagemaker-nvme/m6_work/clips/030c760c-*.pt ~/`, then right-click it in the
     JupyterLab file browser and choose **Download**; or
   * `aws s3 cp /mnt/sagemaker-nvme/m6_work/clips/030c760c-*.pt "s3://$USER_BUCKET/users/$USER_PROFILE/staging/"`
     (your own workspace prefix: the role can write there, but not to `hf-cache/`).
3. On your admin workstation, with admin credentials:
   ```bash
   CLIP=030c760c-ae38-49aa-9ad8-f5650a545d26.pt
   USERB=av30lab-user-workspace-<account>-$AWS_REGION
   aws s3 cp "s3://$USERB/users/<your-profile>/staging/$CLIP" . --region "$AWS_REGION"   # skip if downloaded
   shasum -a 256 "$CLIP"       # MUST equal the hash from step 1 (Linux: sha256sum "$CLIP")
   aws s3 cp "$CLIP" "s3://<shared>/hf-cache/alpamayo-demo/" --region "$AWS_REGION"
   aws s3 rm "s3://$USERB/users/<your-profile>/staging/$CLIP" --region "$AWS_REGION"
   # Only if you staged .no_exist markers in step 1:
   aws s3 ls "s3://$USERB/users/<your-profile>/staging/hub-markers/" --recursive \
     --region "$AWS_REGION" | ./scripts/cache_hf_tree.sh --record-markers
   AWS_REGION="$AWS_REGION" ./scripts/cache_hf_tree.sh --markers-only
   aws s3 rm "s3://$USERB/users/<your-profile>/staging/hub-markers/" --recursive --region "$AWS_REGION"
   ./scripts/check_seeding.sh --region "$AWS_REGION"
   ```
   If the hash does not match, the file changed after it left the app. Do not upload it;
   produce it again.

Full sequence: [COSMOS_M5_M6.md](COSMOS_M5_M6.md), [ALPAMAYO_M9.md](ALPAMAYO_M9.md).

### 6.4 M10 AlpaSim reference eval (only if running M10)
AlpaSim is a Docker-Compose microservice system needing a ≥40 GB GPU — it
**cannot run in a Studio notebook**. Run it once on a Docker-capable GPU EC2 host:
```bash
# On a Deep Learning Base GPU AMI box (g6e.12xlarge, public subnet):
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export HF_TOKEN=hf_... NGC_API_KEY=nvapi-...
# Do NOT export SHARED_BUCKET: the script derives av30lab-shared-data-<acct>-<region>
# itself and exits 1 if it cannot. An exported value overrides that and, if it is
# missing the region suffix, silently targets a bucket that does not exist.
bash scripts/alpasim_ec2_setup.sh    # → uploads s3://<shared>/m10-reference/
# then TERMINATE the instance.
```
The M10 notebook (CPU) downloads and visualizes these results for every participant.
~$30 one-time; participant cost $0. Full details + the optional participant
self-run path: [ALPASIM_M10.md](ALPASIM_M10.md), [M10_MANUAL_TEST_RUNBOOK.md](M10_MANUAL_TEST_RUNBOOK.md).

### 6.5 Upload notebook templates + scripts (do this LAST, after any notebook edits)
```bash
# <shared> = av30lab-shared-data-<account>-<region>. $AWS_REGION is the value exported in §5 (or: export AWS_REGION=...)
aws s3 sync notebooks/ s3://<shared>/notebook-templates/ --region "$AWS_REGION" \
    --exclude "*__pycache__*" --exclude "*.pyc"
aws s3 sync scripts/   s3://<shared>/notebook-templates/scripts/ --region "$AWS_REGION" \
    --exclude "*__pycache__*" --exclude "*.pyc"
```

> **Re-syncing into a bucket that already holds the pre-renumbering notebooks?**
> `aws s3 sync` does not delete, so the old names (`M4_Cosmos_Transfer_…`,
> `M8_OpenSearch_…`, `M9_HyperPod_…`, `M10_Nerfstudio_…`) would sit alongside the new
> ones and participants would see both. Do **not** add `--delete` — that would also
> wipe the `notebook-templates/scripts/` folder, which this sync does not repopulate.
> Remove the stale objects explicitly instead:
> ```bash
> for f in M4_Cosmos_Transfer_Augmentation M5_Cosmos_Predict_Synthesis \
>          M6_Alpamayo_VLA_Inference M7_AlpaSim_ClosedLoop \
>          M8_OpenSearch_Semantic_Search M9_HyperPod_Distributed_Training \
>          M10_Nerfstudio_3D_Reconstruction; do
>   aws s3 rm "s3://av30lab-shared-data-$ACCOUNT-$AWS_REGION/notebook-templates/$f.ipynb" \
>     --region "$AWS_REGION"
> done
> ```
> A fresh deployment after `teardown.sh` needs none of this.
These are copied into each user's workspace at provisioning time (and the notebooks
fall back to downloading scripts from this path). **Re-run this whenever you change
a notebook or script** — otherwise participants get the old version. Participants
already provisioned can re-sync from a JupyterLab terminal:
`aws s3 cp s3://<shared>/notebook-templates/<NB>.ipynb ~/`.

> **Editing notebooks:** the repo's `notebooks/*.ipynb` are the single source of truth —
> edit them directly and re-sync via §6.5; the cross-module S3 contract they rely on is
> in [DATA_CONTRACT.md](DATA_CONTRACT.md).

---

## 7. Optional: M10 participant self-run (advanced)

By default every participant shares your one M10 reference eval (§6.4) and needs no
token. If you instead want **each participant to run AlpaSim themselves** on their
own admin-provisioned GPU host over SSM:
- You pre-provision a GPU EC2 host per participant and grant least-privilege SSM
  access (exact-ARN or ABAC). **Participants cannot terminate hosts — you do**
  (cost-runaway guard).
- Each participant needs **their own HF token** (the NuRec dataset is gated and not
  in the shared cache).
- Cost ~$10.5/hr/host, ≤16 concurrent by the G-vCPU quota.

Full runbooks: [M10_MANUAL_TEST_RUNBOOK.md](M10_MANUAL_TEST_RUNBOOK.md) Part C (admin
provisioning + IAM) and [M10_PARTICIPANT_SSM_RUNBOOK.md](M10_PARTICIPANT_SSM_RUNBOOK.md)
(participant steps). This is opt-in; skip it for a standard workshop.

---

## 8. Smoke test (Day −1) — prove one user works end-to-end

1. Admin Dashboard → **Add User** → test name + email → **Provision**.
2. Copy the **Participant Dashboard Link** from the success dialog (the durable
   `#userId=&token=` link — **not** the 5-minute "Direct workspace URL").
3. Open that link in a fresh browser → the Pipeline Map with 12 module nodes renders (M1-M12; M0 is the overview notebook and has no node),
   and the `#userId=…&token=…` part disappears from the address bar.
4. Click **M2** → **Instance Options** → recommended `ml.g5.12xlarge` preselected →
   **Apply & Restart** → **Open Workspace** → JupyterLab opens.
4b. **Settle whether the scoped IAM conditions resolve (free, ~1 min).** While that app is
   running, open Studio *itself* as the test user — the Studio console, not the deep link —
   go to the space page and click **Run space**, then **Open JupyterLab**. Record whether
   either returns `AccessDenied` on `sagemaker:UpdateSpace` /
   `sagemaker:CreatePresignedDomainUrl`.
   - **No AccessDenied** → the `${sagemaker:DomainId}` / `${sagemaker:UserProfileName}`
     policy variables resolve live, so `CreateApp`/`DeleteApp` can be narrowed from
     `resources=["*"]` to the same owner condition. See the note on the
     `SageMakerStudioAppLifecycle` statement in `infra/av30_constructs/sagemaker.py`.
   - **AccessDenied** → they do not resolve in this account. Leave `CreateApp` broad, and
     keep telling participants to use the dashboard's button.
5. Run **M1** (CPU) end-to-end, then **M2** (GPU) — confirms the GPU image is
   auto-selected and the model cache resolves.
6. If you're running M12/M11, run one of each once as the test user to confirm the
   job quotas (§2b) and IAM are in place — they submit real managed jobs.
7. **Delete** the test user (Users tab → Delete) — removes app/space/profile + S3.

---

## 9. Provision participants (Day 0)

**Single user:** Admin Dashboard → **Add User** → name + email → **Provision**.
Hand them the **Participant Dashboard Link** (durable, non-expiring). The Users
table has a **Dashboard Link** column with a copy button per user.

**The link is a bearer credential — treat it like a password.** Whoever holds it can
open that participant's workspace and change its instance until you delete the user
(§12), so send each link to its participant directly, not to a shared channel.
- The token rides in the URL fragment (`#userId=…&token=…`), which the browser never
  sends to the server, so it stays out of CloudFront logs and the `Referer` header.
- On load the dashboard moves it into the tab's session storage and removes it from
  the address bar, so it doesn't show up in a screen share or a copied URL. A reload
  keeps the participant signed in; a new tab or a bookmark of the open page does not.
  Tell participants to keep the original link and reopen it.
- Links handed out earlier in the `?userId=&token=` form keep working and are cleaned
  out of the address bar the same way. The token itself never changes (there is no
  rotation): to retire a leaked link and keep the participant, delete the user — which
  also removes their workspace files — and provision them again.

**Bulk (CSV):** Admin Dashboard → bulk upload. The CSV needs a header row with
`name` and `email` columns (case-insensitive). Provisioning runs in parallel;
retry any failures individually.

Each participant gets: a SageMaker user profile + space, a `users/<id>/` S3 prefix
seeded with the notebook templates, and a personal dashboard link.

**Send participants two things:**
- **Before the event** — [PRE_LEARNING_GUIDE.md](PRE_LEARNING_GUIDE.md) (concepts +
  optional deeper-dive reading, ~45–60 min) so they arrive with context.
- **On the day** — their dashboard link + [PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md)
  (the click-by-click runbook).

---

## 10. During the workshop — monitor & control

- **Sessions tab** — live view of who's running what, on which instance, and cost.
- **Capacity errors** (`EC2InsufficientCapacityError`): tell participants to pick any
  alternative Instance Options offers for that module. The panel shows the same list in
  every region, so the API does the filtering: a type this region does not sell, or whose
  quota is 0, is refused with an explanation before the running app is touched. Don't
  name a specific fallback from memory: `ml.g6.12xlarge` was the old advice and is quota 0
  in ap-northeast-2. It's a capacity shortage, not a quota problem.
- **A change that silently didn't happen.** If a participant says their instance change
  did nothing, the app failed to launch on the new type (most often
  `ResourceLimitExceeded` — quota exists but every slot is in use) and was rolled back to
  the previous type so they still have a workspace. The reason is on
  `GET /sessions/{id}/app-status` as `lastInstanceChangeError`. Free a slot (force-terminate
  an idle session) and have them retry.
- **Cost control** — a daily budget alarm emails `ADMIN_EMAIL` via SNS; idle
  JupyterLab apps auto-stop after 90 min (`-c idle_timeout_minutes=<60..180>` to
  change). A running cell or terminal job counts as active, so this never kills work
  in progress. You can **force-terminate** any session from the Sessions tab. Watch for idle GPU boxes —
  the rate is per region, so quote your own: `ml.g5.12xlarge` (the default for five modules)
  is **$8.72/hr** in ap-northeast-2 and $7.09 in us-west-2; `ml.p4d.24xlarge` is **$34.97/hr**
  in ap-northeast-2 and $25.25 in us-west-2. See `infra/lambda/shared/instance_rates.py` for
  your region.
- **Storage cost is per participant and one-way.** Every space is created with a 200 GB gp3
  volume (`DEFAULT_SPACE_STORAGE_GB` in `infra/av30_constructs/__init__.py`). At
  $0.0912/GB-month in ap-northeast-2 that is **~$18.24 per participant per month**, billed
  whether or not the app is running — the idle timer deletes the app, not the volume. AWS does
  not allow SHRINKING a space's volume, and participants can grow it (+50/+200, ceiling 500 GB),
  so this only ever goes up until teardown removes the space.
- **GPU image reminder** — if a participant reports "No GPU detected" on a GPU
  instance, they launched the CPU image; Instance Options → GPU instance → Apply
  re-selects the GPU image.

---

## 11. M7 Nerfstudio — gsplat build (per-session)

**M7's training cell is UNVERIFIED — the repo contradicts itself.** This section used to
assert "M7 now trains". The notebook's own cell 0 says the opposite ("does NOT run on the
current image"), both claims arrived in the same commit, and the captured run retained
output for only 2 of 9 cells — so nobody has seen this pass or fail. One `ml.g5.xlarge`
Run-All (~$0.25, ~15 min) settles it; see `docs/en/TODO_M7_nerfstudio.md`. Until then,
treat M7 as the optional concept + data-prep demo the PARTICIPANT_GUIDE describes.

What the setup is *intended* to do, after a per-session gsplat CUDA
build: `gsplat` ships a pure-Python wheel and compiles its CUDA kernels from
source on first use, but the SageMaker Distribution image's conda CUDA dev
packages are incomplete. **`scripts/setup_gsplat_env.sh`** (M7 cell 3 invokes it)
fixes the whole chain: installs the missing dev headers, symlinks `nvvm` so `nvcc`
finds `cicc`, mirrors the CUDA headers/libs into the standard `$CUDA_HOME` paths
(so the build works with zero env vars, even inside `ns-train`'s subprocess), and
source-builds `gsplat==1.4.0`.

- It is **ephemeral** — the SMD app resets `/opt/conda` on restart, so the setup
  cell re-runs each session (~3–5 min cold, seconds when already built).
- The demo uses **synthetic sin-wave camera poses**, so training runs end-to-end
  (a genuine Gaussian-Splatting pipeline) but the reconstruction is a smoke test,
  not a metrically correct scene. Wiring real nuScenes calibration is the next step.
- **M7 caveat:** the gsplat CUDA build runs per-session via
  `scripts/setup_gsplat_env.sh`; treat M7 as an optional/demo module and expect the
  final training cell to be sensitive to the GPU image's CUDA toolchain.

---

## 12. Teardown & post-event security

- **One-shot teardown:** **`scripts/teardown.sh`** reclaims everything with the
  admin AWS creds. Dry-run by default (enumerates, changes nothing); `--yes` to
  act, `--user <id>` to scope to a single user, `--destroy` to also `cdk destroy`.
  Per user it deletes app→space→profile→AOSS→S3→DDB (same order as the delete_user
  Lambda), then runs a **global `av30-semantic-*` AOSS sweep** to catch any
  orphaned OpenSearch Serverless collection (these bill continuously — the sweep is
  the safety net), and terminates `Participant`+`av30-alpasim-*`-tagged GPU EC2
  hosts. It prints a manual HF/NGC key-revocation checklist at the end.
- **Delete a single user interactively:** Admin Dashboard → Users → **Delete**
  (same dependency order in one action).
- **A deleted or disabled participant is not cut off instantly.** Delete, or setting
  the user's `status` in the `av30-sessions-v2` table to anything other than `active`,
  revokes their dashboard token, but API Gateway caches the token authorizer's answer
  for up to **60 seconds**. Inside that window the token still reaches the participant
  routes. Open Workspace, instance changes and storage expansion check `status`
  themselves and are refused at once. To cut the token off immediately, flush the
  stage's authorizer cache right after the delete:

  ```bash
  API_ID=$(aws cloudformation describe-stacks --stack-name Av30BlueprintLabStack --region "$AWS_REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text | cut -d/ -f3 | cut -d. -f1)
  aws apigateway flush-stage-authorizers-cache --rest-api-id "$API_ID" --stage-name prod --region "$AWS_REGION"
  ```

  The flush clears every cached token, which only costs the other participants one
  extra authorizer call on their next request. A Studio browser session that is
  already open does not go through this cache; Delete ends it by removing the app,
  space and user profile.
- **Tear down the stack** (if the platform is temporary): `scripts/teardown.sh
  --yes --destroy`, or `cd infra && npx cdk destroy`. Note the shared-data bucket
  is RETAIN — it and its cached models survive a destroy and must be emptied by hand.
- **Revoke the admin HF token** `hf_...` — the S3 caches are all participants ever
  touch, so the token isn't needed after staging.
- **Rotate the NGC API key** if you used M10.
- The idle stack still costs ~$80/mo (NAT, VPC endpoints, DynamoDB, CloudFront) —
  destroy it if you're done.

---

## 13. Admin troubleshooting quick table

| Symptom | Cause / Fix |
|---|---|
| `ResourceLimitExceeded: ...Studio JupyterLab Apps... is 0` | GPU app quota not raised — §2a. |
| M12 job fails at submission (`AccessDeniedException` on `CreateTrainingJob`) | The exec-role's training-job ARN prefix must match the notebook's `JOB_NAME`. The module renumber moved HyperPod M9→M12 and the notebook now submits `av30-m12-distributed-*`; a deployment predating that fix still grants `av30-m9-*` and every submission is denied. The m5.xlarge **job** quota (§2b) is a separate, rarer cause — check the error first: `AccessDenied` = IAM prefix, `ResourceLimitExceeded` = quota. |
| Participant "No GPU detected" on a GPU instance | CPU image selected — re-Apply via Instance Options. |
| M5/M6/M9 setup cell stops with "this region has no usable offline HuggingFace cache and no HF_TOKEN" (exit 2) | `hf-cache/hub/` not seeded in **this** region (§6.3). Seed it, then `./scripts/check_seeding.sh --region <r>`. This message is the *fixed* behaviour — before 2026-09-26 the same condition was silent: setup printed "environment ready", then M5 died four seconds into `torchrun` with a `ChildFailedError` that named CUDA out-of-memory. If you still see that older shape, the participant is running a stale staged copy of `setup_cosmos_env.sh`. |
| M5/M6/M9 fails with `Local entry not found … offline mode is enabled` | The restored cache is **partial**. An interrupted `aws s3 sync` is the usual cause — **re-run the same sync**, it resumes and re-copies anything missing or size-mismatched. What `sync` cannot detect is a destination object that is the *right size with wrong content*, because it compares size+mtime rather than checksums; if `check_seeding.sh --source-region <seeded>` reports a CRC64 mismatch, delete that one object and re-sync. |
| M7 training cell fails on gsplat | Re-run M7 cell 3 (`scripts/setup_gsplat_env.sh`) — the CUDA build is per-session and resets on app restart. §11. |
| M9 fails to load its clip | demo `.pt` not uploaded to `hf-cache/alpamayo-demo/` (§6.3). |
| `aws s3 cp`/`sync` to `hf-cache/` from a Studio terminal fails with `AccessDenied` | Expected: the execution role every participant shares has no write on the shared bucket, on purpose (§6.3). Seed or publish from your admin workstation; do not paste admin keys into the Studio terminal. |
| M10 notebook shows nothing (cell-4 raises "No M10 AlpaSim results found in S3") | `m10-reference/` reference eval not run (§6.4). |
| M10 shows metrics and plots but the **video** is blank | **Not a missing bundle — do NOT re-run §6.4.** The codec: AlpaSim's renderer writes MPEG-4 Part 2, which Chrome/Firefox/Edge cannot decode. cell-7 prints the codec it found. Fix by replacing that one object with an H.264 version — no GPU host needed: `aws s3 cp s3://$SHARED_BUCKET/m10-reference/eval/eval.mp4 .` then `ffmpeg -i eval.mp4 -vf scale=1280:-2 -c:v libx264 -pix_fmt yuv420p -movflags +faststart -an eval_h264.mp4` and copy it back over `m10-reference/eval/eval.mp4`. `scripts/alpasim_ec2_setup.sh` now transcodes at upload time, so a bundle produced after that change is already H.264. |
| M4's search demo ranks the **same caption several times**, and its index cell prints `403 authorization_exception` on delete | The collection's data-access policy predates the **`aoss:DeleteIndex`** grant, so M4 cannot clear its index — and because AOSS rejects a caller-supplied document `_id`, every `index()` INSERTS. Each re-run therefore adds another full copy (measured: 24 → 48 → 72 → 96 → 120 documents for 24 captions). The participant role cannot fix the policy: `aoss:UpdateAccessPolicy` is deliberately not granted, because on `collection/*` it would let one participant reach another's collection. With admin creds delete BOTH the collection and its data policy — a surviving policy is the old one — then have the participant Run All, and M4 recreates them with the grant: `aws opensearchserverless list-collections --region $REGION --query 'collectionSummaries[?starts_with(name,\`av30-semantic-\`)].[id,name]' --output text`, then `aws opensearchserverless delete-collection --id <id> --region $REGION` and `aws opensearchserverless delete-access-policy --name <name>-access --type data --region $REGION`. |
| SNS budget alert went to placeholder@example.com | Deployed without `--context admin_email` — redeploy via `deploy.sh`. |
| Participant link shows "Demo Mode" | They opened the bare URL, or a new tab or bookmark of an already-open dashboard (the token leaves the address bar on load). Have them reopen the original `#userId=&token=` link, or resend it. |
| Bulk provision partial failure | Retry failed rows individually; check `bulk_provision` CloudWatch logs. |

---

## Related docs
- [PRE_LEARNING_GUIDE.md](PRE_LEARNING_GUIDE.md) — send to participants before the event.
- [PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md) — hand this to participants on the day.
- [PREREQUISITES.md](PREREQUISITES.md) — the token/license detail behind §3/§6.
- Module deep-dives: [COSMOS_M5_M6.md](COSMOS_M5_M6.md), [ALPAMAYO_M9.md](ALPAMAYO_M9.md),
  [ALPASIM_M10.md](ALPASIM_M10.md), [HYPERPOD_M12.md](HYPERPOD_M12.md),
  [PIPELINE_M11.md](PIPELINE_M11.md).
- [ADDING_A_REGION.md](ADDING_A_REGION.md) — stand up an additional, independent
  region (quotas, seeding, the contexts a redeploy needs).
- [README.md](../../README.md) — full deployment + architecture reference.
