# M10 Manual Test Runbook (Part A: admin GPU run → Part B: participant notebook)

M10 has two layers. **Part A** = admin runs the real AlpaSim on a GPU EC2 instance to produce
`m10-reference/` (heavy, one-time). **Part B** = participants visualize that result in a CPU notebook (light and
repeatable). "Both, in order" means using A to freshly produce the reference result → then B to view it in the notebook.

> In the reference deployment this has already run successfully, and genuine results were uploaded to
> `s3://av30lab-shared-data-<aws-account-id>-<region>/m10-reference/`.
> If such a reference result already exists, **running Part B alone is a complete
> verification**. Part A is only needed when you want to "reproduce from scratch" (~$30, 2-3 hours).

---

## 0. Refresh credentials (common to both, do this first)

The local session token has expired. Re-log in as the **admin of the AWS account that deployed this lab**, then wrap every aws
call in the **6-env-unset wrapper** (to prevent credentials from another account leaking in and getting mixed up).

> **⚠️ Do not skip this step.** The `UN()` below is a shell **function** — every `UN aws …`
> command that follows depends on it. If you paste the A2/A3/C* blocks without defining it,
> you get `command not found: UN` (e.g. `AMI=` ends up empty) and everything afterward fails.
> A shell function is valid **only within the current terminal session**, so **every time you open a new terminal
> (or whenever your credentials expire) you must re-run this block**.

> **Do not hardcode the account/region.** Below, `ACCOUNT` is derived automatically via `sts` and
> the bucket names are derived from it — since every later command in this document uses these variables,
> it works **as-is on any other AWS account/region too**. (The `<aws-account-id>` /
> `<region>` in the document body are just example placeholders.)

```bash
# After logging in the usual way (Isengard/SSO, etc.):
UN() { env -u AWS_PROFILE -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY \
             -u AWS_SESSION_TOKEN -u AWS_SHARED_CREDENTIALS_FILE -u AWS_CONFIG_FILE "$@"; }
UN aws sts get-caller-identity --query '[Account,Arn]' --output text
# → <your account id>  arn:aws:...:assumed-role/...

# The account/region this lab is deployed to → the variables every later block uses (defined once here instead of hardcoding)
export REGION=<region>                                    # your deployed region (e.g. us-west-2)
export ACCOUNT=$(UN aws sts get-caller-identity --query Account --output text)
export SHARED_BUCKET=av30lab-shared-data-${ACCOUNT}-${REGION}       # model/data/notebook templates + m10-reference
export USER_BUCKET=av30lab-user-workspace-${ACCOUNT}-${REGION}      # per-participant users/<id>/ (used in Part C)
echo "ACCOUNT=$ACCOUNT REGION=$REGION"
echo "SHARED_BUCKET=$SHARED_BUCKET"
```

---

# Part A — admin: re-run the real AlpaSim on a GPU EC2 instance (~$30, optional)

## A1. Prerequisites
- **HF token**: a token that has all licenses approved for Alpamayo-1.5-10B + Cosmos-Reason2-8B + the PhysicalAI NuRec dataset
  (approve them in advance with the admin's own HF account).
- **NGC API key**: actually, the renderer image `nvcr.io/nvidia/nre/nre-ga:26.04` **can be pulled publicly**
  (confirmed at gate 0), so no key is needed. If the script has no key it falls back to an anonymous pull.

## A2. Launch the GPU host (manual — there is no launch script)

> **⚠️ The instance must have GPUs ≥2. The number in the name ≠ the number of GPUs.** The default topology (`2gpu`)
> puts the renderer on **GPU 1**, so a **minimum of 2 GPUs** is required. In the g6e family, **a larger
> vCPU size does not mean more GPUs** — multi-GPU is only **12xlarge(4), 24xlarge(4), 48xlarge(8)**,
> and everything else (**including 16xlarge**) has **1 GPU**. If you pick
> `g6e.16xlarge` reasoning "16 > 12 so it must be bigger", it has 1 GPU and dies right before running with
> `Service renderer requested GPUs [1] but only 0 .. 0 are available`.
>
> | g6e size | GPUs | vCPU | M10(2gpu) |
> |---|---|---|---|
> | xlarge / 2xlarge / 4xlarge / 8xlarge | **1** | 4–32 | ❌ |
> | **g6e.12xlarge** | **4** | 48 | ✅ **recommended** |
> | g6e.16xlarge | **1** | 64 | ❌ (bigger, but only 1 GPU!) |
> | g6e.24xlarge | **4** | 96 | ✅ (overkill) |
> | g6e.48xlarge | **8** | 192 | ✅ (overkill) |
>
> After launch, always confirm: `nvidia-smi --query-gpu=index,name --format=csv` shows **2 or more lines**.
> (A single 80 GB card like p4de/p5 can do 1 GPU with `topology=1gpu`.)

At gate 2 this step was manual. Do the following in order:

```bash
# ⟸ You must first have defined the §0 UN() wrapper + the ACCOUNT/REGION/SHARED_BUCKET variables
#    (otherwise 'command not found: UN' or an empty bucket name).
# (a) Look up the latest Deep Learning Base GPU AMI ID (bundles Docker+NVIDIA toolkit+driver)
AMI=$(UN aws ssm get-parameter --region $REGION \
  --name /aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-22.04/latest/ami-id \
  --query Parameter.Value --output text)
echo "AMI=$AMI"

# (b) A public subnet of the default VPC (the lab VPC is isolated with no egress → use the default VPC)
# Assumption: this account/region must have a default VPC + a public subnet (map-public-ip-on-launch=true).
#   - If the default VPC has been deleted (org accounts, etc.) or there is no public subnet, VPC/SUBNET becomes
#     'None'/empty and the run-instances below fails with an obscure error. In that case:
#       * Specify directly: SUBNET=subnet-xxxx (a public subnet that egresses via an IGW), and use that VPC's SG too
#       * Or create a default VPC with `aws ec2 create-default-vpc --region $REGION`.
#   - Subnets[0] is the first subnet (= an arbitrary AZ). If that AZ has no g6e.12xlarge capacity, launch can
#     fail with InsufficientInstanceCapacity → retry with SUBNET set to a subnet id in a different AZ.
VPC=$(UN aws ec2 describe-vpcs --region $REGION --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].VpcId' --output text)
SUBNET=$(UN aws ec2 describe-subnets --region $REGION \
  --filters Name=vpc-id,Values=$VPC Name=map-public-ip-on-launch,Values=true \
  --query 'Subnets[0].SubnetId' --output text)
echo "VPC=$VPC SUBNET=$SUBNET"
# If VPC/SUBNET is None/empty, stop here and act per the comment above (specify directly or create-default-vpc); proceeding empty will make run-instances fail.
[ -n "$VPC" ] && [ "$VPC" != "None" ] && [ -n "$SUBNET" ] && [ "$SUBNET" != "None" ] \
  || { echo "ERROR: could not find a default VPC/public subnet — see comment (b) above (specify directly or create-default-vpc)"; }

# (c) Security group (only egress needed; no inbound since we connect over SSM)
SG=$(UN aws ec2 create-security-group --region $REGION \
  --group-name av30-alpasim-m7 --description "M10 AlpaSim egress" \
  --vpc-id $VPC --query GroupId --output text)
# (no inbound rules added — we connect via SSM Session Manager)

# (d) IAM instance-profile (not present in the lab account → create it on the spot). hf-cache read + m10-reference write + KMS + SSM.
UN aws iam create-role --role-name av30-alpasim-m7-$REGION \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
UN aws iam attach-role-policy --role-name av30-alpasim-m7-$REGION \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
# Build the policy JSON with a heredoc so $SHARED_BUCKET expands (single-quotes would not expand it).
UN aws iam put-role-policy --role-name av30-alpasim-m7-$REGION --policy-name s3-hfcache-m7ref \
  --policy-document "$(cat <<JSON
{"Version":"2012-10-17","Statement":[
  {"Effect":"Allow","Action":["s3:GetObject","s3:ListBucket"],"Resource":["arn:aws:s3:::${SHARED_BUCKET}","arn:aws:s3:::${SHARED_BUCKET}/*"]},
  {"Effect":"Allow","Action":["s3:PutObject"],"Resource":"arn:aws:s3:::${SHARED_BUCKET}/m10-reference/*"},
  {"Effect":"Allow","Action":["kms:Decrypt","kms:GenerateDataKey"],"Resource":"*"}]}
JSON
)"
UN aws iam create-instance-profile --instance-profile-name av30-alpasim-m7-$REGION
UN aws iam add-role-to-instance-profile --instance-profile-name av30-alpasim-m7-$REGION --role-name av30-alpasim-m7-$REGION

> **Why the `-$REGION` suffix on the IAM names.** IAM role and instance-profile names are
> **account-global**, unlike the security group above (which is per-VPC, so it keeps the bare
> name). Without the suffix a second region's M10 run fails `EntityAlreadyExists`, and — far
> worse — the teardown block below deletes them unconditionally "to prevent name collisions
> on the next run", so tearing down M10 in EITHER region would destroy the role the OTHER
> region's running GPU host is using. Suffixing at create AND teardown keeps the two
> deployments independent, which is the model this lab uses (one region per deployment; see
> `docs/en/ADDING_A_REGION.md`).
sleep 15   # wait for IAM propagation

# (e) launch: g6e.12xlarge (4× L40S 48GB), gp3 300GB, public IP
IID=$(UN aws ec2 run-instances --region $REGION \
  --image-id $AMI --instance-type g6e.12xlarge \
  --subnet-id $SUBNET --security-group-ids $SG --associate-public-ip-address \
  --iam-instance-profile Name=av30-alpasim-m7-$REGION \
  --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=300,VolumeType=gp3}' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=av30-alpasim-m7}]' \
  --query 'Instances[0].InstanceId' --output text)
echo "INSTANCE=$IID"
UN aws ec2 wait instance-status-ok --region $REGION --instance-ids $IID   # ~2-3 min
```

## A3. Run on the host (connect via SSM Session Manager)
```bash
# ⟸ You must first have defined the §0 UN() wrapper + the REGION variable (otherwise 'command not found: UN').
UN aws ssm start-session --region $REGION --target $IID
# --- inside the session (root) --- (from here you are on the GPU host. The local §0 variables aren't here, so redefine them)
sudo su -
export HF_TOKEN=hf_xxx                 # the approved token from A1
export NGC_API_KEY=nvapi-xxx           # optional (omit if none — anonymous pull)
# Derive the account from the instance role → derive the bucket name (instead of hardcoding). The host has the aws CLI bundled.
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export SHARED_BUCKET=av30lab-shared-data-${ACCOUNT}-${REGION}
# Fetch the script (use the S3 staged copy):
aws s3 cp s3://$SHARED_BUCKET/notebook-templates/scripts/alpasim_ec2_setup.sh /root/
# ── run (DETACHED by default — see the warning below) ─────────────────────────────────────
# Detach from the session with setsid and run in the background. Even if the SSM session drops (re-login/timeout)
# it won't die, and since the log is redirected there's no buffer loss. After reconnecting, re-attach with tail -f.
setsid bash /root/alpasim_ec2_setup.sh > /var/log/alpasim_m7.log 2>&1 &
echo "started PID $!"
tail -f /var/log/alpasim_m7.log   # even if you exit with Ctrl-C, the background run keeps going
```

> **⚠️ Do not run it with `... | tee` (foreground) — on a long run, if the session drops the whole thing dies.**
> `bash setup.sh 2>&1 | tee log` is a pipeline that is **attached to the SSM session**, so if a Claude Code
> re-login, a network drop, or an SSM idle timeout occurs, SIGHUP **terminates the entire pipeline (including the
> script)**, and the logs still in the tee buffer aren't flushed, so the **log file can end up 0 bytes**
> (a pitfall we actually hit). This script takes tens of minutes from running the wizard through starting the docker containers,
> so **always use the `setsid` approach above**. (Use tee only when watching very briefly in the foreground.)
>
> **When resuming after an interruption** (resume after cleaning up leftover processes/containers — clone/build/cache remain
> so it's fast):
> ```bash
> docker ps -aq | xargs -r docker rm -f    # clean up interrupted containers
> setsid bash /root/alpasim_ec2_setup.sh > /var/log/alpasim_m7.log 2>&1 &
> tail -f /var/log/alpasim_m7.log
> ```
What the script does: preflight (nvidia-smi/docker/uv/cargo) → restore hf-cache → alpasim clone
(tag v2026.5 — alpasim-base-v0.96.0 no longer exists upstream; see below) → NGC login (optional) + verify image access → `source setup_local_env.sh`
→ create mount directories → write `deploy/local_m7.yaml` (driver HF-offline) + `topology/m7_4gpu.yaml`
(driver alone on GPU0) → run `uv run alpasim_wizard ...` → verify results → upload to `s3://.../m10-reference/`.
**The first build takes a long time (protos compilation + image pull + NuRec scene download).**
On a re-run, the clone/build/hf-cache/NuRec scenes remain, so it starts from the wizard step and is much faster.

### Judging success/failure from the log
When `tail -f` stops updating, it's one of two things — **success (finished) or failure (interrupted)** — decide by
looking at the **end** of the log (`tail -n 40 /var/log/alpasim_m7.log`).

- **✅ Success**: the script's completion markers are at the end of the log.
  ```
  runtime-0-1 exited with code 0            # the eval container exited normally with 0
  [verify] core outputs present.
  [upload] -> s3://.../m10-reference/ ...
  === DONE — genuine AlpaSim results uploaded to s3://.../m10-reference/ ===
  ```
  On success, `tail -f` stopping is **normal** (the script finished so the background process exited —
  it did not die). Final confirmation is the S3 check in A4 (today's date).
  > Note: right after completion, seeing the `renderer/physics/controller` containers logged as `exited with code 143` (SIGTERM)/
  > `137` (SIGKILL) is **normal** — after the main container (runtime) finishes with 0, docker
  > compose brings the remaining services down. If `runtime-0-1 exited with code 0` + `=== DONE ===`
  > are present, it's a success.

- **❌ Failure/interruption**: there is **no** `=== DONE ===` at the end of the log and instead one of the following means failure.
  - Ends with `ERROR: ...` (preflight failure, missing required output, etc. — the script exited).
  - `Error executing job` / `RuntimeError: ...` (wizard run failure, e.g. insufficient GPUs).
  - The log **cuts off abruptly in the middle** + no process either → interrupted by a session drop, etc.
    (check process survival with `ps aux | grep -E "[a]lpasim|[w]izard"`; docker with `docker ps`).
  → Fix the cause, then resume with the "resume after interruption" recipe above.

To quickly check only whether it succeeded:
```bash
grep -q "=== DONE" /var/log/alpasim_m7.log && echo "M10 success (S3 upload complete)" \
  || echo "M10 incomplete — check the end of the log (tail -n 40) for ERROR/RuntimeError/the interruption point"
```

## A4. Confirm success → **terminate immediately** (stop billing)
```bash
# ⟸ You must first have defined the §0 UN() wrapper + the SHARED_BUCKET/REGION variables.
# From the local (credentialed) side:
UN aws s3 ls s3://$SHARED_BUCKET/m10-reference/ --recursive --region $REGION
# Success if you see aggregate/results-summary.json + metrics_results.{txt,png,parquet} + rollouts/**/metrics.parquet
# + eval/eval.mp4 + run.json.

# !!! Always clean up (otherwise ~$10.5/hr keeps being billed) !!!
UN aws ec2 terminate-instances --region $REGION --instance-ids $IID
UN aws ec2 wait instance-terminated --region $REGION --instance-ids $IID
# Clean up IAM/SG too (to prevent name collisions on the next run):
UN aws iam remove-role-from-instance-profile --instance-profile-name av30-alpasim-m7-$REGION --role-name av30-alpasim-m7-$REGION
UN aws iam delete-instance-profile --instance-profile-name av30-alpasim-m7-$REGION
UN aws iam delete-role-policy --role-name av30-alpasim-m7-$REGION --policy-name s3-hfcache-m7ref
UN aws iam detach-role-policy --role-name av30-alpasim-m7-$REGION --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
UN aws iam delete-role --role-name av30-alpasim-m7-$REGION
UN aws ec2 delete-security-group --region $REGION --group-id $SG
```

**⚠️ The biggest risk = forgetting to terminate.** Terminate as soon as you've confirmed. (You can also set
`shutdown -h +180` on the host as a backup guard.)

---

# Part C — admin: per-participant self-run provisioning (when participants run AlpaSim themselves)

Part A is the admin producing **one shared reference result** (`m10-reference/`). Part C below is the
pre-wiring the admin does when you want **each participant to run AlpaSim on their own GPU host** (participant run guide =
[M10_PARTICIPANT_SSM_RUNBOOK.md](M10_PARTICIPANT_SSM_RUNBOOK.md)).

> **Cost/limit warning**: g6e.12xlarge = **48 vCPU/instance**, ~**$10.5/hr/instance**. G-vCPU quota 768 →
> **max 16 concurrent (=16 people)**. Always check the quota before launch:
> `UN aws service-quotas get-service-quota --region $REGION --service-code ec2 --quota-code L-DB2E81BA`

## C1. Extend the instance-profile policy (participants write to user-workspace)
Part A's `av30-alpasim-m7` instance role only writes to `m10-reference/`. Participant self-runs need to write to
`users/<id>/m10/`, so extend the policy (a prefix restriction lets multiple participants share it):
```bash
# ⟸ You must first have defined the §0 UN() wrapper + the SHARED_BUCKET/USER_BUCKET variables.
UN aws iam put-role-policy --role-name av30-alpasim-m7-$REGION --policy-name s3-participant-m7 \
  --policy-document "$(cat <<JSON
{"Version":"2012-10-17","Statement":[
  {"Effect":"Allow","Action":["s3:GetObject","s3:ListBucket"],"Resource":["arn:aws:s3:::${SHARED_BUCKET}","arn:aws:s3:::${SHARED_BUCKET}/*"]},
  {"Effect":"Allow","Action":["s3:PutObject"],"Resource":"arn:aws:s3:::${USER_BUCKET}/users/*/m10/*"},
  {"Effect":"Allow","Action":["kms:Decrypt","kms:GenerateDataKey"],"Resource":"*"}]}
JSON
)"
```

## C2. Launch a per-participant GPU instance (reuse Part A2 + a Participant tag)
Add a participant tag to Part A2's (e) `run-instances` (reusing the shared SG/instance-profile):
```bash
# ⟸ You must first have defined the §0 UN() wrapper + refreshed credentials (otherwise 'command not found: UN').
PID=m10-test01     # participant id
IID=$(UN aws ec2 run-instances --region $REGION \
  --image-id $AMI --instance-type g6e.12xlarge \
  --subnet-id $SUBNET --security-group-ids $SG --associate-public-ip-address \
  --iam-instance-profile Name=av30-alpasim-m7-$REGION \
  --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=300,VolumeType=gp3}' \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=av30-alpasim-$PID},{Key=Participant,Value=$PID}]" \
  --query 'Instances[0].InstanceId' --output text)
echo "$PID -> $IID"     # hand this mapping to the participant
UN aws ec2 wait instance-status-ok --region $REGION --instance-ids $IID
```

## C3. Participant SSM credentials — two approaches

### Option 1 — per-participant IAM user + exact-ARN (pre-testing / small scale, recommended)
Create one IAM user per participant and **bake that instance ID directly into the policy** so they can only connect to their own instance.
`ssm:TerminateSession` is **only for ending their own session** — they cannot terminate the instance (prevents cost accidents).
```bash
# ⟸ You must first have defined the §0 UN() wrapper + refreshed credentials (otherwise 'command not found: UN').
UN aws iam create-user --user-name $PID
# With the heredoc, $REGION/$ACCOUNT/$IID expand, but the IAM policy variable ${aws:...} is preserved with \$.
UN aws iam put-user-policy --user-name $PID --policy-name m10-ssm --policy-document "$(cat <<JSON
{
  "Version":"2012-10-17","Statement":[
   {"Sid":"StartOwnInstance","Effect":"Allow","Action":["ssm:StartSession"],
    "Resource":["arn:aws:ec2:${REGION}:${ACCOUNT}:instance/${IID}",
                "arn:aws:ssm:${REGION}:${ACCOUNT}:document/SSM-SessionManagerRunShell"]},
   {"Sid":"Describe","Effect":"Allow","Action":["ssm:DescribeSessions","ssm:GetConnectionStatus","ssm:DescribeInstanceProperties","ec2:DescribeInstances"],"Resource":"*"},
   {"Sid":"TerminateOwnSessionOnly","Effect":"Allow","Action":["ssm:TerminateSession","ssm:ResumeSession"],"Resource":["arn:aws:ssm:*:*:session/\${aws:userid}-*"]},
   {"Sid":"OpenChannel","Effect":"Allow","Action":["ssmmessages:OpenDataChannel","ssmmessages:CreateControlChannel","ssmmessages:CreateDataChannel","ssmmessages:OpenControlChannel"],"Resource":"*"}]}
JSON
)"
UN aws iam create-access-key --user-name $PID   # → deliver to the participant out-of-band
```

### Option 2 — ABAC tag matching (real workshop / N people)
Create just one policy and isolate by **tag match** (no instance ID baked in). The user's principal tag
`Participant=<id>` must equal the instance's `Tag Participant=<id>` to connect. C2 already attached the instance tag,
so only the user side is left:
```bash
# ⟸ You must first have defined the §0 UN() wrapper + refreshed credentials (otherwise 'command not found: UN').
UN aws iam create-user --user-name $PID --tags Key=Participant,Value=$PID
# With the heredoc, $REGION/$ACCOUNT expand, but the IAM policy variable ${aws:...} is preserved with \$.
UN aws iam put-user-policy --user-name $PID --policy-name m10-ssm-abac --policy-document "$(cat <<JSON
{
  "Version":"2012-10-17","Statement":[
   {"Sid":"StartTaggedInstance","Effect":"Allow","Action":["ssm:StartSession"],
    "Resource":"arn:aws:ec2:${REGION}:${ACCOUNT}:instance/*",
    "Condition":{"StringEquals":{"ssm:resourceTag/Participant":"\${aws:PrincipalTag/Participant}"}}},
   {"Sid":"StartDoc","Effect":"Allow","Action":["ssm:StartSession"],"Resource":"arn:aws:ssm:${REGION}:${ACCOUNT}:document/SSM-SessionManagerRunShell"},
   {"Sid":"Describe","Effect":"Allow","Action":["ssm:DescribeSessions","ssm:GetConnectionStatus","ssm:DescribeInstanceProperties","ec2:DescribeInstances"],"Resource":"*"},
   {"Sid":"TerminateOwnSessionOnly","Effect":"Allow","Action":["ssm:TerminateSession","ssm:ResumeSession"],"Resource":["arn:aws:ssm:*:*:session/\${aws:userid}-*"]},
   {"Sid":"OpenChannel","Effect":"Allow","Action":["ssmmessages:OpenDataChannel","ssmmessages:CreateControlChannel","ssmmessages:CreateDataChannel","ssmmessages:OpenControlChannel"],"Resource":"*"}]}
JSON
)"
UN aws iam create-access-key --user-name $PID
```
> (Alternative option 3 — no long-lived access key) An `sts get-federation-token` that wraps the policy above as a session policy
> (≤36h) for temporary credentials. Minimal leak risk but a more complex issuance procedure — for security-strict environments.

## C4. Negative test (wiring verification, required)
With the issued participant key (not the admin key), verify that the isolation actually holds:
```bash
# From a shell where the participant key is exported:
REGION=us-west-2   # (the participant shell has no §0 variables, so define it here; use the deployed region)
aws ssm start-session --target $IID --region $REGION          # ✓ should succeed
aws ssm start-session --target <another-instance> --region $REGION # ✗ should be AccessDenied
aws ec2 terminate-instances --instance-ids $IID --region $REGION # ✗ should be denied (participants cannot terminate)
```

## C5. Participant run → completion notice → admin cleanup
- The participant follows [M10_PARTICIPANT_SSM_RUNBOOK.md](M10_PARTICIPANT_SSM_RUNBOOK.md) to run,
  uploads the result to `users/<id>/m10/`, then **notifies of completion**.
- As soon as the admin is notified, clean up (can be queried in bulk by tag):
```bash
# ⟸ You must first have defined the §0 UN() wrapper + refreshed credentials (otherwise 'command not found: UN').
# Terminate a specific participant
UN aws ec2 terminate-instances --region $REGION --instance-ids $IID
# Bulk-query the remaining participant instances
UN aws ec2 describe-instances --region $REGION \
  --filters "Name=tag:Participant,Values=*" "Name=instance-state-name,Values=running,pending" \
  --query 'Reservations[].Instances[].[InstanceId,Tags[?Key==`Participant`]|[0].Value]' --output text
# Clean up the IAM user (delete keys first)
UN aws iam list-access-keys --user-name $PID --query 'AccessKeyMetadata[].AccessKeyId' --output text \
  | tr '\t' '\n' | while read k; do UN aws iam delete-access-key --user-name $PID --access-key-id "$k"; done
UN aws iam delete-user-policy --user-name $PID --policy-name m10-ssm 2>/dev/null || \
  UN aws iam delete-user-policy --user-name $PID --policy-name m10-ssm-abac 2>/dev/null
UN aws iam delete-user --user-name $PID
```

**⚠️ The biggest risk = forgetting to terminate a participant instance.** Participants can't turn it off, so the admin owns it. Part A4's
shared SG/instance-profile should be cleaned up last, after all participant instances have been terminated.

---

# Part B — participant: visualize M10 in a Studio CPU notebook (~$0, 5 min)

This is what participants actually experience, and it fills the "real Studio environment" gap from gate 3.

## B1. Open the participant dashboard
1. From the admin dashboard, get the test user's **participant dashboard link**
   (`https://<user-dashboard>.cloudfront.net/?userId=<id>&token=<token>`).
   If there isn't one, admin dashboard → Users → Provision to create a new user, and the link appears.
2. Open that link in a browser → the Pipeline Map is shown.

## B2. Confirm the instance = CPU (M10 needs no GPU)
- The M10 notebook runs on **`ml.t3.medium` (CPU)**. The workspace default is t3.medium, so
  **no instance change is needed**. (If you bumped to GPU in M9, it's cost-wise preferable to revert to t3.medium via
  Instance Options before M10 — it does run on GPU too, but that's wasteful.)

## B3. Open the workspace and run the notebook
1. Top-right of the dashboard, **Open Workspace** → the JupyterLab tab.
2. In the file browser, open **`M10_AlpaSim_ClosedLoop.ipynb`**.
3. **Run ▸ Run All Cells** (or Shift+Enter top→bottom).

## B4. Pass criteria (each cell should produce this)
| Cell | Expected output |
|---|---|
| cell-2 config | prints Profile/Reference eval/M9 provenance paths |
| cell-3 provenance | if the M9 manifest exists, shows open-loop minADE; if not, "stand alone" (both are normal) |
| cell-4 download | `aws s3 sync m10-reference/` → the artifact list (aggregate/, rollouts/, eval/, run.json) |
| cell-5 parse | AlpaSim aggregate table verbatim + 11 driving scores (collision 0.00, dist_to_gt 4.37m, progress 0.92) + "Per-rollout time-series: N rows" |
| cell-6 viz | metrics_results.png inline + safety-rate bars + dist_to_gt_trajectory time-series |
| cell-7 video | eval.mp4 (~0.5MB, H.264 1280px) plays inline |
| cell-8 cost | honest CPU framing + reference run metadata (g6e.12xlarge/m7_4gpu) |
| cell-9 validation | 4 checks OK → **PASS** + headline "no at-fault collisions, no off-road, route progress 0.92" + PIPELINE COMPLETE |

## B5. Common failures → causes
| Symptom | Cause/fix |
|---|---|
| cell-4 `M10 reference eval not found in S3` | m10-reference/ not uploaded → do Part A first (or check for an existing bundle) |
| cell-4 download failed / AccessDenied | the execution role lacks read on the shared bucket → already present (normal). If missing, check IAM |
| cell-7 video blank or not shown | **a codec, not a missing file.** AlpaSim's renderer writes MPEG-4 Part 2 (`mpeg4`), which Chrome/Firefox/Edge cannot decode — the browser fails silently, which is not a Python exception, so no try/except catches it. Confirm with `ffprobe -show_entries stream=codec_name eval/eval.mp4`. Fixed at the source: `alpasim_ec2_setup.sh` transcodes to H.264 before upload (and says so if the host has no working ffmpeg); cell-7 now prints the codec instead of a dead player. Non-essential — PASS on metrics alone |
| STS/import error | the CPU kernel includes pandas/matplotlib by default — if not, `%pip install pandas matplotlib` in the first cell |

---

## Note: local pre-validation already done
At gate 3 we ran the **actual source** of notebook cells 4-9 against the live S3 bundle in a local venv (pandas 2.3.3)
→ confirmed all PASS. Part B is the step that re-confirms that in the real Studio environment (the data paths are
the same source and are already validated; what remains is only kernel/network/UI-rendering differences).
