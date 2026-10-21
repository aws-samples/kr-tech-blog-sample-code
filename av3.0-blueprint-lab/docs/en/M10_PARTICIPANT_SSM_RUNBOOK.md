# M10 Participant Run Guide — run the real AlpaSim on your own GPU host (SSM)

> ## ⚠️ Read this first — cost and time
> - This run happens on a **GPU server (g6e.12xlarge) that the admin launched for you**.
>   That server is billed at **roughly $10.5 per hour**.
> - **The first build takes a long time** — tens of minutes up to 2-3 hours (code compilation + container image
>   download + NuRec scene download). It does not finish in 5 minutes like a notebook.
> - **You cannot turn off the server.** When you're done, **be sure to notify the admin of "completion"** so the admin
>   terminates the server. If you don't tell them, charges keep piling up.
> - This is the **optional advanced path** for M10. If you just want to see the results, visualize the admin's shared reference
>   result in the notebook (without this document, CPU, $0) — [ALPASIM_M10.md](ALPASIM_M10.md).

M10 has two layers. **(1) The real AlpaSim run** happens on the GPU server (this document), and **(2) result visualization**
happens in a SageMaker CPU notebook. AlpaSim is a fleet of gRPC microservices brought up with Docker-Compose, and
the driver uses a ≥40GB GPU, so it cannot run in a SageMaker Studio notebook, which has no Docker daemon.
That's why the run happens on a separate GPU EC2 host, and the notebook downloads and views that result.

---

## Prerequisites
What you get from the admin:
1. **AWS access key** (Access Key ID + Secret) — your dedicated IAM user.
2. **Your GPU instance ID** (`i-0abc...` format).

What you prepare in advance (**required**):
3. **Your Hugging Face token** (`hf_...`). At runtime AlpaSim downloads the gated NuRec scene
   (`nvidia/PhysicalAI-Autonomous-Vehicles-NuRec`), and this dataset is **not** in the admin's
   shared offline cache (unlike the models), so your token is needed. In advance:
   - Create an HF account + token (`https://huggingface.co/settings/tokens`)
   - Accept the license at [`nvidia/PhysicalAI-Autonomous-Vehicles-NuRec`](https://huggingface.co/datasets/nvidia/PhysicalAI-Autonomous-Vehicles-NuRec)
     ("Agree and access repository")
   - (optional) Accepting `nvidia/Alpamayo-1.5-10B`, `nvidia/Cosmos-Reason2-8B` too is safer — though
     these two are placed in hf-cache by the admin, so they usually load offline.

The admin delivers 1 and 2 out-of-band (Slack/email, etc.). 3 is yours, so do not share it with anyone.

---

## 1. Set up credentials + verify
In your local terminal (or CloudShell):
```bash
export AWS_ACCESS_KEY_ID=<received-key>
export AWS_SECRET_ACCESS_KEY=<received-secret>
export REGION=us-west-2   # the reference deployment region; replace with the region the admin deployed to
export AWS_DEFAULT_REGION=$REGION
aws sts get-caller-identity
export ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
# → if your IAM user ARN (arn:aws:iam::<account>:user/m7-<your-id>) appears, it's fine (reference deployment example: <aws-account-id>)
```
> The Session Manager plugin is required (usually already installed). If not:
> https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html

## 2. Connect to the GPU host via SSM
```bash
aws ssm start-session --target <your-instance-id> --region $AWS_DEFAULT_REGION
```
- Once connected, a shell prompt appears. (No SSH key or inbound port needed — SSM handles it)
- You cannot connect with **someone else's instance ID** (`AccessDenied`) — that's normal.

## 3. Run AlpaSim inside the session
> ⚠️ **Each `export` must be on its own line.** If you write it without export like `A=1 B=2`, or the line gets split while pasting,
> the variable isn't passed to the script (the child process), so preflight fails with `HF_TOKEN not set` or
> the result goes to the wrong path. Write `export VAR=value` on each line as below.
```bash
sudo su -
export PARTICIPANT_ID=<your-id>
export M10_OUTPUT_PREFIX=users/<your-id>/m10
export OUTPUT_BUCKET=av30lab-user-workspace-$ACCOUNT-$REGION
export SHARED_BUCKET=av30lab-shared-data-$ACCOUNT-$REGION
export HF_TOKEN=hf_xxx          # required — for downloading the gated NuRec scene (prerequisite 3)

# Verify passthrough (always, before running the script): all 5 must be visible and tok_len must be non-zero
env | grep -E 'PARTICIPANT_ID|M10_OUTPUT_PREFIX|OUTPUT_BUCKET|SHARED_BUCKET'; echo "tok_len=${#HF_TOKEN}"

# Fetch the script and run it detached in the background + watch the log in real time
aws s3 cp s3://$SHARED_BUCKET/notebook-templates/scripts/alpasim_ec2_setup.sh /root/
setsid bash /root/alpasim_ec2_setup.sh > /var/log/m7.log 2>&1 &
tail -f /var/log/m7.log
```
- Early in the log you should see `[s3] participant self-run: id=<your-id> output=s3://…/users/<your-id>/m10/`,
  which means it's going to the per-user path. If you see `admin reference run`, the env above wasn't passed —
  Ctrl-C, re-do the export, and re-run.
- Launched with `setsid ... &`, it keeps running even if the SSM session drops. Exiting `tail -f` with Ctrl-C
  has no effect on the run (you just stop watching the log).
- **It takes a long time.** Even if the log looks stalled, it may be pulling images/downloading scenes.

## 4. Confirm success
The run takes tens of minutes. **When `tail -f` stops updating, it's finished** — decide whether it's success (complete)
or failure (interrupted) by the **end** of the log (`tail -n 40 /var/log/m7.log`).

**✅ Success**: the completion markers are at the end of the log.
```
runtime-0-1 exited with code 0
[verify] core outputs present.
=== DONE — genuine AlpaSim results uploaded to s3://av30lab-user-workspace-.../users/<id>/m10/ ===
>>> Participant <id>: results are in ...
```
- On success, `tail -f` stopping is **normal** (the script finished — it did not die).
- Right after completion, the `renderer/physics/controller` containers being logged as `exited with code 143` (or `137`)
  is also **normal** (the main container finishes with 0, then the rest are cleaned up). If `runtime-0-1 exited
  with code 0` + `=== DONE ===` are present, it's a success.

**❌ Failure/interruption**: there is **no** `=== DONE` and instead the end of the log is `ERROR:` / `RuntimeError` /
`CUDA out of memory` / `HF_TOKEN not set`, or it cut off abruptly in the middle → see the **Troubleshooting** table
below. (Even if the SSM session drops, the setsid run doesn't die, so you can reconnect and re-attach with `tail -f /var/log/m7.log`.)

Quick check:
```bash
grep -q "=== DONE" /var/log/m7.log && echo "success (S3 upload complete)" \
  || echo "incomplete — check tail -n 40 /var/log/m7.log for ERROR/RuntimeError/the point it cut off → Troubleshooting table"
```

Check directly (inside the session or locally):
```bash
# In a new local shell, re-derive ACCOUNT (if inside the §3 session it's already exported)
ACCOUNT=${ACCOUNT:-$(aws sts get-caller-identity --query Account --output text)}
aws s3 ls s3://av30lab-user-workspace-$ACCOUNT-$REGION/users/<your-id>/m10/ --recursive
# OK if you see aggregate/results-summary.json, rollouts/**/metrics.parquet, eval/eval.mp4, run.json
```

## 5. ⚠️ Notify the admin of completion → the admin terminates the server
You don't have permission to turn off the instance (prevents cost accidents). Notify the admin of **"m7-<id> complete"**.
After confirming, the admin terminates it with `terminate-instances` and stops the billing.

## 6. Visualize your result in the SageMaker notebook (CPU)
1. Participant dashboard → **M10 node** (leave the instance as `ml.t3.medium` CPU) → **Open Workspace**
2. Open `M10_AlpaSim_ClosedLoop.ipynb` and **Run All**
3. The notebook auto-detects `users/<your-id>/m10/` and visualizes **your** result
   (cell-2 prints `Result source: your own EC2 run`). If there is none, it falls back to the admin's shared reference.

**Pass criteria**: driving scores (collision_at_fault, etc.) in cell-5, **PASS** + headline in cell-9.

---

## Troubleshooting
| Symptom | Cause / action |
|---|---|
| `aws sts get-caller-identity` fails | key typo/expired → ask the admin to reissue |
| `start-session` → AccessDenied | the instance ID isn't yours → confirm the correct ID with the admin |
| `SessionManagerPlugin not found` | install the plugin via the link above |
| `CUDA out of memory` in the log | notify the admin (topology adjustment needed) |
| `HF_TOKEN not set` / preflight failure in the log | you didn't do step 3's `export HF_TOKEN=hf_…` or the export didn't take → verify with `echo tok_len=${#HF_TOKEN}` and re-run (prerequisite 3) |
| `401` / `GatedRepoError` (NuRec) in the log | the HF token hasn't accepted the NuRec dataset license → "Agree and access" at the prerequisite 3 link, then re-run |
| the log starts with `admin reference run` | env wasn't passed to the script (missing export/split line) → re-export the step 3 env and re-run |
| notebook cell-4 `not found` | steps 3-4 haven't succeeded yet → check the log and re-run |
| everything's done but the server won't turn off | only the admin can terminate → notify the admin |

Admin provisioning/IAM/cleanup procedures: [M10_MANUAL_TEST_RUNBOOK.md](M10_MANUAL_TEST_RUNBOOK.md).
