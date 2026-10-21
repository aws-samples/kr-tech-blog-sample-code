# Adding a Region

How to stand up a **second, independent copy** of the lab in another AWS region, in the
same account, without disturbing the region you already run.

This is *not* a multi-region deployment. Each region is a self-contained lab: its own
Studio domain, buckets, API, Cognito pool, dashboards and budget. Nothing is shared
except the AWS account itself — and that is exactly where the sharp edges are, because a
handful of AWS namespaces are **account-global** rather than regional.

Everything below was measured in account `<aws-account-id>` while deploying
`ap-northeast-2` alongside a live `us-west-2`. Figures marked *(list price)* are from
AWS published pricing, not from an API call in that session.

---

## 0. Is the target region actually empty?

Do this first. "Empty region" was already false in this account — `ap-northeast-2` hosts
an unrelated `FAST-stack`.

```bash
export R=ap-northeast-2
# Resolve YOUR account rather than pasting one: §3 exports this as
# EXPECTED_ACCOUNT_ID, and scripts/deploy.sh refuses to deploy on a mismatch
# ("ERROR: account mismatch"), so a hardcoded id blocks everyone but its owner.
export ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

aws cloudformation describe-stacks --region $R --stack-name Av30BlueprintLabStack
aws s3api list-buckets --query "Buckets[?ends_with(Name,'$R')].Name"
aws sagemaker list-domains --region $R
aws sagemaker list-apps --region $R --query 'Apps[?Status==`InService`]'   # billing NOW
aws efs describe-file-systems --region $R --query 'FileSystems[].Name'     # orphan source
aws apigateway get-account --region $R --query cloudwatchRoleArn           # see §3
aws iam get-role --role-name av30-alpasim-m7                              # account-global
```

Why each matters:

- **S3 bucket names are global.** A leftover `av30lab-*-$ACCOUNT-$R` bucket from an
  abandoned attempt makes `cdk deploy` fail at bucket creation.
- **Studio creates an EFS filesystem per domain per region**, and it survives stack
  deletion on some paths. This account has orphaned filesystems from exactly that.
- **`ml.*` apps already `InService` are billing right now** — check before you assume
  the region is idle.
- **`av30-alpasim-m7`** (M10's IAM role + instance profile) is **account-global and
  un-suffixed**. See "Known sharp edges" below before running M10 anywhere.

---

## 1. Bootstrap CDK

```bash
aws cloudformation describe-stacks --region $R --stack-name CDKToolkit >/dev/null 2>&1 \
  || npx cdk bootstrap aws://$ACCOUNT/$R
```

Collision-free: every bootstrap role name carries `-{account}-{region}`.

---

## 2. Quotas (do this ~a week ahead)

**Scope: a quota is `(account × region)`.** The console's "Applied **account-level** quota
value" column and "Adjustability: **Account level**" read like "one value for the whole
account" — they do not mean that. Those labels render a **different field** from the one
that answers the region question, and the API makes the two explicit:

| Field | Question it answers | Value here |
|---|---|---|
| `QuotaAppliedAtLevel` | account **vs resource** — what the console labels | `ACCOUNT` |
| `GlobalQuota` | account-global **vs per-region** | `false` |

`list-service-quotas --quota-applied-at-level` takes the enum `[ALL, ACCOUNT, RESOURCE]`
and its own help says it "filters the response to return applied quota values for the
ACCOUNT, RESOURCE, or ALL levels". So *account-level* is the opposite of *resource-level*
(adjusted for the account rather than per individual resource) **within whichever region
the console is currently showing**. It says nothing about cross-region sharing.

Three independent proofs of the region scope:

- **`GlobalQuota`** is `false` for all **2,258** SageMaker quotas (full paginated count).
  For contrast: IAM 23/23 and Route 53 9/9 are `true`, and S3 is mixed — `General purpose
  buckets` is `true` while its replication quotas are `false`.
- The `QuotaArn` embeds the region, so they are distinct resources:
  `arn:aws:servicequotas:us-west-2:…:sagemaker/L-8ACE1754` vs
  `arn:aws:servicequotas:ap-northeast-2:…:sagemaker/L-8ACE1754`.
- Same account, same code, **different applied values** (2 vs 0), with two entirely
  separate `list-requested-service-quota-change-history` streams — increases are filed and
  approved per region.

So an increase granted in region A does nothing for region B. Quota **codes** are shared;
**values, requests and even which quotas exist** are not — `ml.g6.24xlarge for notebook
instance usage` exists in us-west-2 and does not exist in ap-northeast-2 at all (10 vs 9
search hits for "g6.24xlarge").

### Measured for the instance types this lab actually offers

| Quota (Studio JupyterLab apps) | Code | us-west-2 | ap-northeast-2 | Used by |
|---|---|---|---|---|
| `ml.t3.medium` | `L-71FAF417` | 2500 | 2500 | default workspace |
| `ml.g5.xlarge` | `L-988CE6C5` | 5 | 5 | M7 (Nerfstudio) |
| `ml.g5.12xlarge` | `L-8D2ED7BF` | 5 | 5 | M2, M3 |
| `ml.g5.24xlarge` | `L-F087CCFC` | 2 | 2 | M5, M6, M8, M9 (24 GB tier) |
| `ml.g5.48xlarge` | `L-83AB5D73` | 2 | 2 | M6/M9 sharded |
| `ml.p4d.24xlarge` | `L-AD63F1D2` | 2 | **2** | 40 GB tier — 720p, guardrails ON |
| **`ml.g6.12xlarge`** | `L-962247BA` | 2 | **0** ⚠ | M2/M3 alternative |
| `ml.g6.24xlarge` | `L-8ACE1754` | 2 | **0** | not recommended by the dashboard (same tier as g5.12xlarge, dearer) |
| `ml.p5.48xlarge` | `L-B41FBF28` | 1 | **0** | 80 GB tier |
| `ml.m5.xlarge` *training* | `L-CCE2AFA6` | 30 | 30 | M12 |
| `ml.m5.xlarge` *processing* | `L-0307F515` | 16 | 16 | M11 |

> **Quota is not the only cap — AZ coverage is.** A Studio app can only launch in an
> availability zone the domain holds a subnet in, and the GPU types are NOT sold in every
> AZ. Measured 2026-09-25 in this account with
> `describe-instance-type-offerings --location-type availability-zone-id` (AZ *IDs*, which
> are stable across accounts — the a/b/c *names* are not):
>
> | Region | g5.* sold in | p4d sold in | domain reached (before the `max_azs` fix) |
> |---|---|---|---|
> | ap-northeast-2 | apne2-az1, az3, az4 | apne2-az2, az4 | **1 of 3** for g5; p4d shares **zero** AZs with g5 |
> | us-west-2 | usw2-az1, az2, az3 | all four | 2 of 3 |
>
> `apne2-az2` sells no g5 and no g6 at all. The VPC now builds subnets in every AZ
> (`infra/av30_constructs/network.py`, `max_azs=99`), which fixes this by construction —
> but it only takes effect on a **redeploy**, and `check_quotas.py` does not yet report
> coverage. So a type it calls "OK 5" can still fail at app start with
> `EC2InsufficientCapacityError: … unavailable in supported availability zones [...]`.
> Measured that exact failure on three types in a row while quota was 5 and usage 0.

**The whole `g6` and `g6e` family is 0 in ap-northeast-2** — not just the 24xlarge. `g7e`
is 0 in *both* regions.

**But Seoul is not GPU-blocked.** `g5` is available across the full range and
`p4d.24xlarge` is already approved at 2, so the lab runs there today with **no quota
request at all**. The module-to-instance mapping, read from
`web/user/src/data/pipeline-config.ts` rather than from module numbers:

| Instance | Seoul quota | Modules |
|---|---|---|
| `ml.t3.medium` | 2500 | M1, **M4** (OpenSearch is CPU-only), M10 viz, M11, M12 |
| `ml.g5.xlarge` | 5 | M7 |
| `ml.g5.12xlarge` | 5 | M2, M3 **and** M5, M6, M8, M9 — the dashboard default for all six |
| `ml.g5.24xlarge` | **2** | alternative for the same six (same 22.5 GB tier, ~44% dearer) |
| `ml.p4d.24xlarge` | 2 | the same six, at the 40 GB tier (720p / guardrails ON) |

So the binding number is **5 concurrent participants**, set by `ml.g5.12xlarge` and
`ml.g5.xlarge` — and it is the same 5 in us-west-2, so Seoul is not the weaker choice.
Measured with `check_quotas.py`: both regions pass at 5 and neither passes at 10. To run a
bigger room, raise those two; steering people onto `g5.24xlarge`/`g5.48xlarge`/`p4d.24xlarge`
adds a few more slots on top.

Nothing here recommends a `g6` type, which is why Seoul needs no quota request: the four
heavy modules used to default to `ml.g6.24xlarge` (quota **0** here, and 2 in us-west-2), and
now default to `ml.g5.12xlarge` — identical geometry (4 GPUs × 22,888 MiB), cheaper, and
quota 5 in both regions.

An earlier version of this table put CPU-only M4 on the 24 GB tier and M10 on `g5.xlarge`,
because it used pre-renumbering module numbers.

Rather than reading that table, run the pre-flight — it resolves live quota, cross-checks
the generated rate table, and names the modules each shortfall affects:

```bash
./scripts/check_quotas.py --region $R --participants 10
```

It exits non-zero if any type the participant dashboard recommends cannot run. `deploy.sh`
also runs it automatically, BEFORE `cdk deploy`. Measured for this account at 10 participants:
**neither** region passes as configured — `ml.g6.24xlarge` is wanted by four modules and
allows 2 concurrent in us-west-2 and 0 in ap-northeast-2, and `ml.g5.12xlarge` /
`ml.g5.xlarge` allow 5. Plan the cohort around that, or raise quota:

```bash
# Must be filed IN the target region. The script prints the exact code for each shortfall.
aws service-quotas request-service-quota-increase --region $R \
  --service-code sagemaker --quota-code L-8D2ED7BF --desired-value 10   # ml.g5.12xlarge
aws service-quotas request-service-quota-increase --region $R \
  --service-code sagemaker --quota-code L-988CE6C5 --desired-value 10   # ml.g5.xlarge
```

**Before requesting, check the instance is offered for Studio in that region at all.**
Availability is per-region *and per-usage-type* — "is the family in the region" is the
wrong question and will mislead you:

```bash
aws pricing get-products --region us-east-1 --service-code AmazonSageMaker \
  --filters Type=TERM_MATCH,Field=instanceType,Value=ml.g6.24xlarge \
            Type=TERM_MATCH,Field=regionCode,Value=$R \
            Type=TERM_MATCH,Field=platoinstancetype,Value=Studio-JupyterLab \
  --query 'length(PriceList)'
```

Measured: `ap-northeast-2` returns a real `APN2-Studio:JupyterLab-ml.g6.24xlarge`
product, so its quota of 0 is worth raising. **`eu-west-1` returns zero Studio products
for that type** — a quota request there would be futile; steer to the `g5` path instead.

---

## 2.5. Generate the rate table for this region — BEFORE you deploy

**Do not skip this, and do not do it after §3.** Only five regions ship pre-generated
(`ap-northeast-1`, `ap-northeast-2`, `eu-west-1`, `us-east-1`, `us-west-2`). For any
other region the deploy SUCCEEDS and then the whole API returns 500, because
`infra/lambda/shared/config.py` resolves `INSTANCE_RATES` at **module import**:

```python
INSTANCE_RATES = _rates_for_region(AWS_REGION)   # raises UnpricedRegionError
```

14 of the 15 Lambda handlers import that module — including `token_authorizer` and
`create_user` — so nobody can even sign in. It is not "wrong prices on one endpoint".

```bash
./scripts/refresh_instance_rates.py --region $R --merge   # --merge keeps the other regions
grep -c "\"$R\":" infra/lambda/shared/instance_rates.py  # expect 1
```

It writes **two** files from one fetch: the Lambda asset above and
`scripts/av30_instance_rates.py`, which §4 syncs into every participant workspace so the
notebooks' cost cells quote THIS region. Generating late therefore means re-running §3
**and** §4, not just this command.

Needs `pricing:GetProducts` (the Price List API lives in us-east-1; the script calls it
there and passes `$R` as a filter) and `servicequotas:ListServiceQuotas` for the quota
codes.

---

## 3. Deploy

```bash
export EXPECTED_ACCOUNT_ID=$ACCOUNT
export ADMIN_EMAIL=you@example.com
export ADMIN_IP_ALLOWLIST=1.2.3.4/32          # omit to allow all
./scripts/deploy.sh --region $R
```

`deploy.sh` sets the `admin_email`, `admin_ip_allowlist` and `region` contexts for you,
and pins `--context region=$R` so `infra/app.py` cannot resolve a different region than
the shell guards just checked. Observed runtime **~3 minutes**, 176 resources.

**Leave these unset for a new region:**

| Context / env | Why not |
|---|---|
| `OWNER_TAG` | Only for updating a stack whose `Owner` tag differs from the default. SageMaker treats domain **tags** as replacement-requiring, so a mismatch replaces the Studio domain and orphans its EFS. Needed only when updating a stack created with a different `Owner` tag — `deploy.sh` refuses the mismatch and prints the exact `OWNER_TAG=...` re-run command. |
| `HOSTED_UI_DOMAIN_EXISTS` | The most dangerous lever here. It skips declaring the Cognito hosted-UI domain, producing a pool with **no sign-in endpoint**. It exists solely for the one pre-existing unmanaged domain in us-west-2. |
| `APIGW_ACCOUNT_ROLE` | `AWS::ApiGateway::Account` is an unnamed **per-account-per-region singleton** implemented as an unconditional `PATCH /account`. If the region already has a CloudWatch role (Seoul has one belonging to `FAST-stack`), opting in **hijacks another stack's role**. Only set it if `aws apigateway get-account --region $R --query cloudwatchRoleArn` returns `None`. `deploy.sh` refuses when the existing role isn't ours. |

> **Use `deploy.sh`, not bare `cdk deploy`.** `admin_email` defaults to
> `placeholder@example.com`, so a `cdk deploy` that omits `-c admin_email=...` **replaces
> your alert email with the placeholder and deletes the real subscription** — including a
> *confirmed* one. Observed exactly that while iterating on this region. Recovery costs a
> fresh confirmation click, because the recreated subscription comes back
> `PendingConfirmation`. The placeholder subscription cannot even be cleaned up
> (`Cannot delete a subscription which is pending confirmation. Detaching subscription
> from stack.`) — it lingers until SNS discards it after ~3 days. If you must call `cdk`
> directly, always pass `-c admin_email=` (and, for us-west-2, `-c owner_tag=` and
> `-c hosted_ui_domain_exists=true`).

**You do not need a new Cognito prefix.** The hosted-UI prefix is unique per **region**,
not globally — the region is inside the hostname
(`<prefix>.auth.<region>.amazoncognito.com`). `av30lab-admin` is ACTIVE in *both*
us-west-2 and ap-northeast-2 of this account, fronting different pools. Only override
`-c hosted_ui_prefix=...` if the probe below says another account owns it there:

```bash
aws cognito-idp describe-user-pool-domain --domain av30lab-admin --region $R
```

| Response | Meaning |
|---|---|
| 200, populated `DomainDescription` | already yours |
| 200, **empty** `DomainDescription` | free — use it |
| `ResourceNotFoundException` | taken by **another account** in that region → pick a new prefix |

---

## 4. Seed the shared bucket

**Always pass `AWS_REGION` explicitly.** The seeding scripts now refuse to run without
it, because a default silently re-seeds the *first* region (they resolve the destination
bucket from the CloudFormation stack in `$REGION`).

Notebook templates are **required** — provisioning deliberately fails with
`HTTP 500 "Notebook templates are not staged in this region"` rather than handing
participants an empty workspace:

```bash
SHARED=av30lab-shared-data-$ACCOUNT-$R
aws s3 sync notebooks/ "s3://$SHARED/notebook-templates/"        --region $R \
    --exclude "*__pycache__*" --exclude "*.pyc"
aws s3 sync scripts/   "s3://$SHARED/notebook-templates/scripts/" --region $R \
    --exclude "*__pycache__*" --exclude "*.pyc"
```

### Then the data — BUCKET-TO-BUCKET, not by re-downloading

`cache_models.sh` pulls from Hugging Face (needs `HF_TOKEN` plus accepted licences on every
gated repo) and only then uploads. For a SECOND region that is the wrong direction: the
bytes already exist in the first region's bucket. Copy them across instead — no token, no
licence step, and S3-to-S3 rather than internet-to-you-to-S3:

```bash
SRC=av30lab-shared-data-$ACCOUNT-us-west-2     # the region that is already seeded
DST=av30lab-shared-data-$ACCOUNT-$R

# Largest first, so the long pole starts immediately. Each is resumable — re-run to finish.
aws s3 sync "s3://$SRC/model-cache/"   "s3://$DST/model-cache/"   --source-region us-west-2 --region $R
aws s3 sync "s3://$SRC/hf-cache/"      "s3://$DST/hf-cache/"      --source-region us-west-2 --region $R
aws s3 sync "s3://$SRC/datasets/"      "s3://$DST/datasets/"      --source-region us-west-2 --region $R
aws s3 sync "s3://$SRC/m10-reference/" "s3://$DST/m10-reference/" --source-region us-west-2 --region $R
```

Only use `stage_nuscenes.sh` / `cache_models.sh` when there is no seeded region to copy from:

```bash
AWS_REGION=$R ./scripts/stage_nuscenes.sh                      # public mirror, no token
AWS_REGION=$R HF_TOKEN=hf_... ./scripts/cache_models.sh        # re-downloads ~157 GiB
```

> **These two scripts replace only two of the four lines above.** `cache_models.sh` writes
> `model-cache/` and nothing else; `stage_nuscenes.sh` writes `datasets/`. Neither can
> produce `hf-cache/`. That tree is a HuggingFace *offline cache* layout
> (`models--org--name/snapshots/<sha>/…`), while `cache_models.sh` uses
> `hf download --local-dir`, which is flat. To build it use **`scripts/cache_hf_tree.sh`**
> (from `scripts/hf_cache_manifest.tsv`, admin `HF_TOKEN` required); to seed a second
> region, copying bucket-to-bucket as above is faster and needs no token.
> `m10-reference/` has no producer — copy it.
>
> This is not hypothetical. ap-northeast-2 was seeded on 2026-09-26 by running
> `cache_models.sh` in place of the block above. It completed cleanly, `deploy.sh` reported
> success, the Day-1 smoke test (M1 + M2 — the only modules that prefix covers) passed, and
> the region shipped with **M5, M6, M9 and M10 unable to run**. It was found by a
> participant four modules in, holding a $8.72/hr GPU. Run step 10 below.

Measured from the us-west-2 source bucket:

| Prefix | Size | Objects | Modules that break without it |
|---|---|---|---|
| `notebook-templates/` | 0.55 MiB | 31 | **all** — provisioning hard-fails |
| `datasets/` (nuScenes-mini) | 5.01 GiB | 31,225 | M1, M2, M3, M5, M6, M7, M8, M9 |
| `model-cache/` | 157.45 GiB | 1,707 | M2, M8 |
| `hf-cache/` | 115.00 GiB | 481 | M5, M6, M9 |
| `m10-reference/` | 0.03 GiB | 16 | M10 visualisation |
| **total** | **277.49 GiB** | **33,457** | |

`m8-lora-probe/` (1 object, 3 KiB) is deliberately **not** listed: it is a dated SageMaker
training-job `sourcedir.tar.gz` from a one-off probe, no notebook reads it, and listing an
unreachable prefix invites reading the whole table as advisory — which is the reading that
let `hf-cache/` be skipped.

Verified by reading the notebooks, not assumed: M5 and M6 reach `hf-cache/hub/` indirectly
through `scripts/setup_cosmos_env.sh`, so a grep for the prefix in those two notebooks finds
nothing.

**What actually happens without it** (measured, ap-northeast-2, 2026-09-26 — the earlier
description of this was wrong twice over):

* `setup_cosmos_env.sh` now stops with a `=== STOP ===` block whose first line is
  `Reason : no HF cache at <uri> (prefix does not exist in this region)`. With an
  `HF_TOKEN` present it instead proceeds and logs
  `[hf-cache] No usable offline cache (…)`. Neither of these is the
  `WARNING: restore failed…` string that earlier revisions of this document told you to
  grep for — that was always a *different* branch (`aws s3 sync` failed, rather than the
  prefix being absent), so an operator searching for it found nothing.
* Before the fix this was **not** a "per-participant token hunt" — it was silent. The script
  exited 0, the notebook printed "environment ready", and 15-20 minutes later M5 died after
  four seconds inside `torchrun` with a `ChildFailedError` whose only visible advice named
  CUDA out-of-memory. The HuggingFace 401 was in the captured stderr but outside the 25-line
  window the notebook printed.
* The script now **refuses to start** (exit 2) when there is neither a usable cache nor an
  `HF_TOKEN`, and names both remedies. So today an unseeded region fails in seconds, before
  any GPU time is spent — but it still fails. Seed the prefix.

Cost: roughly **$5.73 one-time** (transfer + requests) and **$6.94/month** storage in
ap-northeast-2 *(transfer/request unit prices are list price; the $0.025/GB-mo Seoul
storage rate is API-verified)*.

`stage_nuscenes.sh` pulls from the public `s3://motional-nuscenes` in `ap-northeast-1` with
`--no-sign-request`; that is correct and region-independent.

> `aws s3 ls` reports **current objects only**. If the new buckets have versioning, the
> real billed footprint is larger — this account has already seen 298 GB reported
> against 441.7 GB actually billed.

---

## 5. Verification checklist

1. `aws cloudformation describe-stacks --region $R --stack-name Av30BlueprintLabStack`
   → `CREATE_COMPLETE`.
2. **The budget measures the region, not $0.00.** This is the one check that has already
   caught a silent regression:
   ```bash
   aws budgets describe-budget --account-id $ACCOUNT \
     --budget-name av30lab-daily-budget-$R \
     --query 'Budget.[CostFilters,CalculatedSpend.ActualSpend.Amount]'
   ```
   `CostFilters` must be `{"Region": ["<region-code>"]}`. A **display name** there
   (`"Asia Pacific (Seoul)"`) is not rejected — it matches nothing, so the budget reads
   `0.0` for ever and never alarms. Cross-check against Cost Explorer:
   ```bash
   aws ce get-cost-and-usage --time-period Start=$YDAY,End=$TODAY --granularity DAILY \
     --metrics UnblendedCost \
     --filter "{\"Dimensions\":{\"Key\":\"REGION\",\"Values\":[\"$R\"]}}"
   ```
   Budget `0.0` while CE is `> 0` ⇒ broken filter.
3. **The budget alert can actually be delivered.** A new region means a new SNS topic and
   therefore a **new unconfirmed email subscription**. CloudFormation reports
   `CREATE_COMPLETE` for the *request*, never retries, and SNS discards unconfirmed
   subscriptions after ~3 days. `deploy.sh` warns — do not ignore it.
   ```bash
   aws sns list-subscriptions-by-topic --region $R --topic-arn <topic> \
     --query 'Subscriptions[?Protocol==`email`].[Endpoint,SubscriptionArn]'
   ```
   A `SubscriptionArn` of `PendingConfirmation` means the alarm has nowhere to go.
4. SPA config is region-local:
   `aws s3 cp s3://av30lab-admin-dashboard-$ACCOUNT-$R/config.json -` must mention only
   `$R`.
5. `aws cognito-idp describe-user-pool-domain --domain av30lab-admin --region $R` →
   `ACTIVE`, pool id prefixed `$R`.
6. **Instance rates were generated BEFORE the deploy** (§2.5) and survived it:
   ```bash
   grep -c '"'"$R"'":' infra/lambda/shared/instance_rates.py   # expect 1
   ./scripts/check_quotas.py --region $R --participants <cohort>
   ```
7. Create a Cognito admin, sign in through the hosted UI, provision **one** participant,
   and confirm the workspace is **not empty** (measured: **32** objects — 31 staged
   templates + `.av30-progress.env`).
8. `aws apigateway get-account --region $R --query cloudwatchRoleArn` unchanged from its
   value in §0.
9. **The region you already had is untouched:** its stack still `UPDATE_COMPLETE`, its
   budget still present, its `apigateway get-account` unchanged.
10. **The data is actually there — run this before provisioning anyone:**

    ```bash
    ./scripts/check_seeding.sh --region $R --source-region us-west-2
    ```

    It must exit 0. Items 1-9 all pass on a region where M5, M6, M9 and M10 cannot run —
    that is exactly what happened in ap-northeast-2 on 2026-09-26 — because none of them
    inspects a byte of the 277.49 GiB §4 just told you to copy. The check asserts *tree
    shape*, not mere presence: it looks for the five `models--nvidia--*` directories the
    runtime globs actually test, asserts the specific `tokenizer.pth` blob at the commit
    sha Cosmos pins, and with `--source-region` compares CRC64 checksums and object counts.
    Presence alone is not sufficient — HuggingFace offline mode does **no** integrity
    checking, so a 0-byte file reads as a successful download, and a half-finished
    `aws s3 sync` is *worse* than an empty prefix: one directory is enough to flip
    `HF_HUB_OFFLINE=1`, after which every still-missing checkpoint becomes an opaque
    `Local entry not found` instead of a download.

### A cheap honest smoke test (well under $1)

Deploy (§3), seed **`notebook-templates/` only** (0.55 MiB ≈ $0.00), provision one
participant, start **one `ml.t3.medium`** app (quota is already 2500), run the checklist,
delete the app, then `./scripts/teardown.sh --region $R`.

That proves: all 176 resources create alongside the existing region; the Cognito prefix
genuinely coexists; the budget name and filter; `ApiGateway::Account` left alone; the
SageMaker image account mapping resolves to a real image (the app actually starts);
sign-in end-to-end; the empty-bucket guard; and that region 1 is undisturbed.

It does **not** prove: GPU capacity or quota (a `t3.medium` says nothing about
`ml.g6.24xlarge`, which is quota 0 in Seoul); that the 272 GiB you skipped is present, so
M2/M3/M5/M6/M9 will fail at model load; concurrency (one user is not ten); or that a
budget alert is actually delivered.

---

## Known sharp edges

**`INSTANCE_RATES` is a us-west-2 price snapshot — and doubles as the instance
allowlist.** `infra/lambda/shared/config.py` is not keyed by region, and
`change_instance` derives `VALID_INSTANCE_TYPES` from its keys while `instance_options`
builds the participant dropdown from them. Two consequences:

| Studio-JupyterLab | us-west-2 | ap-northeast-2 | reported |
|---|---|---|---|
| `ml.t3.medium` | $0.0500 | $0.0620 | −24% |
| `ml.g5.12xlarge` | $7.0900 | $8.7180 | −23% |
| `ml.g6.24xlarge` | $8.3440 | $10.2600 | −23% |

1. Every cost shown to participants and admins reads ~23% **low** in Seoul — the wrong
   direction for a lab whose documented failure mode is unnoticed spend.
2. The dropdown is unfiltered by region, so a region can be offered an instance it does
   not have for Studio (e.g. `ml.g6.24xlarge` in `eu-west-1`), failing per-participant
   at app start.

The uniform ~23% Seoul delta is coincidence, not a rule — do not "fix" this with a
multiplier; key the table by region.

**`av30-alpasim-m7` (M10) is account-global and un-suffixed.** IAM role and
instance-profile names are account-global, so a second region's M10 run fails
`EntityAlreadyExists`. Worse, the M10 runbook's teardown deletes both *unconditionally*
"to prevent name collisions on the next run" — so tearing down M10 in **either** region
destroys the role the other region's running GPU host is using. Suffix both names with
the region at create *and* teardown before running M10 in more than one region. The live
role's inline policies also name buckets with no region segment at all, so they no longer
match the current bucket names.

**Keep `REGION_CONFIG` / `TARGET_REGIONS` unset.** `infra/lambda/shared/config.py`
defines a dormant cross-region control plane, and `create_user` / `bulk_provision`
already accept a `region` field in the request body. Neither env var is set by the CDK,
so today everything collapses to the single deploy region — which is the independent-copy
model this document describes. Setting them would silently convert two independent labs
into one control plane managing both.

**CloudFront distributions are an account-global quota.** Each region adds 2 (plus 2
Cognito-managed ones that don't count). The default limit is 200, so there is no
practical risk, but the check is
`aws service-quotas get-service-quota --service-code cloudfront --quota-code L-24B04930`.

---

## Teardown

```bash
./scripts/teardown.sh --region $R      # or AWS_REGION=$R ./scripts/teardown.sh
```

The region is explicit and confirmation requires typing `<account>/<region>` — the script
used to default to `us-west-2`, which meant running it to reclaim region B could delete
region A instead (the old prompt only asked for the account id, which is identical for
every region). Afterwards verify the known orphan sources, none of which
CloudFormation tracks:

```bash
aws efs describe-file-systems --region $R          # Studio's per-domain filesystem
aws ec2 describe-security-groups --region $R \
  --filters "Name=group-name,Values=security-group-for-*-nfs-*"
aws s3api list-buckets --query "Buckets[?ends_with(Name,'$R')].Name"
aws budgets describe-budgets --account-id $ACCOUNT --query "Budgets[].BudgetName"
```

Deletion order for a Studio domain is apps → spaces → **user profiles** (created at
runtime, so the stack does not own them) → stack. After that, the retained EFS **mount
targets** pin the subnets and SageMaker's auto-created NFS security groups
(`security-group-for-{inbound,outbound}-nfs-<domainId>`, which reference each other on
tcp/988) pin the VPC. Revoke the cross-references before deleting the groups.
