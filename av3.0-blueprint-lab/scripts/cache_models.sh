#!/bin/bash
# cache_models.sh — Pre-cache NVIDIA models to S3 for AV 3.0 Blueprint Lab
# Downloads models from Hugging Face Hub to a local temp directory,
# then syncs to the shared S3 bucket for SageMaker access.
set -uo pipefail

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
# Region must be explicit — NO literal default. This used to be "us-west-2", and the
# destination bucket is resolved from the CloudFormation stack in $REGION (below), so
# running this with AWS_REGION unset after deploying a SECOND region re-synced ~157 GB
# of models into the ALREADY-POPULATED first region's bucket, printing
# "Region: us-west-2" the whole time — which reads as success.
#
# deploy.sh baited that trap by printing "HF_TOKEN=xxx ./scripts/cache_models.sh" with
# no region: deploy.sh exports AWS_REGION in its OWN process, which does not survive
# into the operator's next shell. It now prints the region explicitly.
REGION="${AWS_REGION:-}"
if [ -z "$REGION" ]; then
    echo "ERROR: set AWS_REGION (e.g. AWS_REGION=ap-northeast-2 $0)." >&2
    echo "       Refusing to guess: guessing seeds the wrong region, silently." >&2
    exit 2
fi
STACK_NAME="Av30BlueprintLabStack"
TEMP_DIR="${TMPDIR:-/tmp}/av30-model-cache"

# Model registry: name | HF repo | S3 prefix | gated flag
#
# SCOPE WARNING — read before treating a clean run here as "the region is seeded".
# This script seeds model-cache/ and NOTHING ELSE. In the four-line seeding block in
# docs/en/ADDING_A_REGION.md §4 it replaces exactly ONE line; the other three
# (hf-cache/, m10-reference/, and the datasets/ stage) still have to be done. Running
# only this script is how ap-northeast-2 came up with M5/M6/M9/M10 broken on
# 2026-09-26. Verify with scripts/check_seeding.sh, never by this script's exit code.
#
# NOTE: Alpamayo-1.5-10B (M9) is intentionally NOT here. M9 loads its weights
# from the HuggingFace OFFLINE cache tree (hf-cache/hub/), not this flat
# model-cache, because at runtime it also pulls a hidden Cosmos-Reason2-8B VLM
# backbone that a flat weights-only copy would miss. That tree is NOT produced by
# any script in this repo — see docs/en/ADMIN_GUIDE.md §6.3 for how it comes into
# being, and docs/en/ALPAMAYO_M9.md for M9's side of it. A flat
# model-cache/alpamayo-1.5/ copy would just be unused dead weight.
declare -a MODELS=(
    "Cosmos Reason 1 (7B)|nvidia/Cosmos-Reason1-7B|cosmos-reason1|false"
    "Cosmos Transfer 2.5 (2B)|nvidia/Cosmos-Transfer2.5-2B|cosmos-transfer2.5|true"
    "Cosmos Predict 2.5 (2B)|nvidia/Cosmos-Predict2.5-2B|cosmos-predict2.5|true"
)

# --------------------------------------------------------------------------
# Pre-flight checks
# --------------------------------------------------------------------------
echo "=== AV 3.0 Blueprint Lab — Model Pre-caching ==="
echo ""

# Check HF_TOKEN
if [ -z "${HF_TOKEN:-}" ]; then
    echo "ERROR: HF_TOKEN environment variable is not set."
    echo ""
    echo "To obtain a token:"
    echo "  1. Go to https://huggingface.co/settings/tokens"
    echo "  2. Create a token with 'read' access"
    echo "  3. For gated models (Alpamayo), accept the license at the model page first"
    echo "  4. Export the token: export HF_TOKEN=hf_..."
    echo ""
    exit 1
fi

# Check required CLI tools
for cmd in hf aws jq; do
    if ! command -v "$cmd" &> /dev/null; then
        echo "ERROR: '$cmd' is not installed or not in PATH."
        if [ "$cmd" = "hf" ]; then
            echo "  Install: pip install huggingface_hub"
        fi
        exit 1
    fi
done

# Resolve S3 bucket name
if [ -n "${MODEL_BUCKET:-}" ]; then
    BUCKET="$MODEL_BUCKET"
    echo "Using bucket from MODEL_BUCKET env var: $BUCKET"
elif [ -n "${1:-}" ]; then
    BUCKET="$1"
    echo "Using bucket from argument: $BUCKET"
else
    echo "Resolving bucket from CloudFormation stack '$STACK_NAME'..."
    OUTPUTS=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --query 'Stacks[0].Outputs' \
        --region "$REGION" 2>/dev/null) || {
        echo "ERROR: Could not read CloudFormation stack '$STACK_NAME' in $REGION."
        echo "  Either deploy the stack first, or pass the bucket name:"
        echo "  MODEL_BUCKET=my-bucket ./scripts/cache_models.sh"
        echo "  ./scripts/cache_models.sh my-bucket-name"
        exit 1
    }
    BUCKET=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="SharedDataBucketArn") | .OutputValue' | sed 's|arn:aws:s3:::||')
    if [ -z "$BUCKET" ] || [ "$BUCKET" = "null" ]; then
        echo "ERROR: Could not find SharedDataBucketArn in stack outputs."
        exit 1
    fi
    echo "Resolved bucket from stack: $BUCKET"
fi

echo "Region:    $REGION"
echo "Bucket:    $BUCKET"
echo "Temp dir:  $TEMP_DIR"
echo ""

# Authenticate with Hugging Face.
#
# Export only — do NOT run `hf auth login --token "$HF_TOKEN"`. Two reasons, both real:
#   1. A token on the command line is visible to every user on the machine via `ps`.
#      Measured: `ps -Ao command` printed the full admin token for 2 hours while a
#      download ran.
#   2. `login` also WRITES the token to ~/.cache/huggingface/token, where it outlives this
#      script — the opposite of what "revoke the token after the workshop" wants.
#
# The export is sufficient: huggingface_hub's get_token() resolves
# _get_token_from_environment() BEFORE the token file (verified in huggingface_hub 1.22.0,
# utils/_auth.py), so every `hf` call in this script picks it up.
export HF_TOKEN="$HF_TOKEN"

# Fail fast on a bad token instead of discovering it 15 minutes into the first download.
# whoami takes the token from the environment, so nothing lands in argv.
if ! HF_WHOAMI=$(hf auth whoami 2>&1); then
    echo "ERROR: HF_TOKEN was rejected by Hugging Face." >&2
    echo "       $HF_WHOAMI" >&2
    echo "       Create a 'read' token at https://huggingface.co/settings/tokens" >&2
    exit 1
fi
echo "Hugging Face: authenticated as ${HF_WHOAMI%%$'\n'*}"

# --------------------------------------------------------------------------
# Download and sync models
# --------------------------------------------------------------------------
mkdir -p "$TEMP_DIR"

SUCCESS_COUNT=0
FAIL_COUNT=0
declare -a FAILED_MODELS=()
declare -a SUCCESS_MODELS=()

TOTAL=${#MODELS[@]}
CURRENT=0

for entry in "${MODELS[@]}"; do
    IFS='|' read -r NAME REPO PREFIX GATED <<< "$entry"
    CURRENT=$((CURRENT + 1))

    echo "---------------------------------------------------------------"
    echo "[$CURRENT/$TOTAL] $NAME"
    echo "  Repository: $REPO"
    echo "  Destination: s3://$BUCKET/model-cache/$PREFIX/"
    if [ "$GATED" = "true" ]; then
        echo "  NOTE: Gated model — requires license acceptance at https://huggingface.co/$REPO"
    fi
    echo ""

    LOCAL_PATH="$TEMP_DIR/$PREFIX"

    # ALREADY IN S3? Skip. Re-running after a partial failure used to re-download every
    # model that had already succeeded — measured: a second run spent 17 min re-fetching
    # 15 GiB and then 2 HOURS re-fetching 51 GiB that were already uploaded, only to run
    # the local disk out of space again. Compare object COUNT and total BYTES against the
    # weights actually present, so a half-finished prefix is not mistaken for a complete one.
    S3_STATS=$(aws s3 ls "s3://$BUCKET/model-cache/$PREFIX/" --recursive --region "$REGION" \
                 2>/dev/null | awk '{n++; b+=$3} END {printf "%d %d", n+0, b+0}')
    S3_N=$(echo "$S3_STATS" | cut -d' ' -f1)
    S3_B=$(echo "$S3_STATS" | cut -d' ' -f2)
    if [ "${S3_N:-0}" -gt 0 ] && [ "${S3_B:-0}" -gt 1000000000 ]; then
        echo "  SKIP: already in S3 ($S3_N objects, $((S3_B / 1073741824)) GiB)."
        echo "        Delete the prefix first if you need to re-cache it:"
        echo "          aws s3 rm s3://$BUCKET/model-cache/$PREFIX/ --recursive --region $REGION"
        echo ""
        SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
        continue
    fi

    # DISK CHECK before downloading. The HF weights are large (Cosmos-Predict2.5-2B is
    # ~70 GiB) and `hf download` on a full volume does not fail fast — it stalls at ~0%
    # CPU indefinitely, which is indistinguishable from a slow network. Measured: one run
    # sat for 2 hours in that state. Refuse up front instead.
    AVAIL_KB=$(df -Pk "$TEMP_DIR" | awk 'NR==2 {print $4}')
    AVAIL_GB=$((AVAIL_KB / 1048576))
    if [ "$AVAIL_GB" -lt 80 ]; then
        echo "  FAILED: only ${AVAIL_GB} GiB free on $(df -Pk "$TEMP_DIR" | awk 'NR==2 {print $6}')."
        echo "          The largest model in this set needs ~70 GiB of scratch, plus HF keeps"
        echo "          a second copy in .cache/huggingface, so budget ~80 GiB free."
        echo ""
        echo "  If another region of this lab is already seeded, copy bucket-to-bucket"
        echo "  instead — it uses NO local disk and needs no HF token:"
        echo "    aws s3 sync s3://av30lab-shared-data-<account>-<seeded-region>/model-cache/$PREFIX/ \\"
        echo "                s3://$BUCKET/model-cache/$PREFIX/ \\"
        echo "      --source-region <seeded-region> --region $REGION"
        echo ""
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_MODELS+=("$NAME")
        continue
    fi

    mkdir -p "$LOCAL_PATH"

    # Step 1: Download from Hugging Face
    #
    # Token via HF_TOKEN in the environment, NOT --token: a CLI argument is visible to
    # every user on the machine in `ps`. Measured: `ps -Ao command` printed the full
    # admin token for 2 hours while a download was running.
    #
    # Output is NOT piped through `tail` any more. Buffering the progress meant a stalled
    # download printed nothing at all — the operator could not tell "downloading 70 GiB"
    # from "wedged on a full disk". The last lines are kept on failure via the log file.
    echo "  Downloading from Hugging Face..."
    DL_LOG="$TEMP_DIR/.$PREFIX.download.log"
    if ! HF_TOKEN="$HF_TOKEN" hf download "$REPO" --local-dir "$LOCAL_PATH" 2>&1 \
           | tee "$DL_LOG"; then
        echo "  FAILED: Download failed for $NAME"
        if grep -qiE "No space left on device|os error 28" "$DL_LOG" 2>/dev/null; then
            # Do not offer the license/token/network guesses for a disk error — that
            # mis-sent an operator to Hugging Face to re-check licences that were fine.
            echo "    Cause: OUT OF DISK on $(df -Pk "$TEMP_DIR" | awk 'NR==2 {print $6}')"
            echo "           ($(df -Ph "$TEMP_DIR" | awk 'NR==2 {print $4}') free)"
            echo "    Free space, or copy bucket-to-bucket from a seeded region (no local"
            echo "    disk, no token) — see the command above."
        else
            echo "  Possible causes:"
            if [ "$GATED" = "true" ]; then
                echo "    - License not accepted: visit https://huggingface.co/$REPO"
            fi
            echo "    - Invalid or expired HF_TOKEN"
            echo "    - Network connectivity issue"
        fi
        echo ""
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_MODELS+=("$NAME")
        continue
    fi

    # Step 2: Sync to S3
    echo "  Syncing to S3..."
    if ! aws s3 sync "$LOCAL_PATH" "s3://$BUCKET/model-cache/$PREFIX/" \
        --region "$REGION" \
        --only-show-errors; then
        echo "  FAILED: S3 upload failed for $NAME"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_MODELS+=("$NAME")
        continue
    fi

    echo "  OK: $NAME cached successfully."
    echo ""
    SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
    SUCCESS_MODELS+=("$NAME")
done

# --------------------------------------------------------------------------
# Cleanup and summary
# --------------------------------------------------------------------------
echo ""
echo "==============================================================="
echo "=== Model Pre-caching Summary ==="
echo "==============================================================="
echo ""
echo "  Successful: $SUCCESS_COUNT / $TOTAL"
if [ ${#SUCCESS_MODELS[@]} -gt 0 ]; then
    for m in "${SUCCESS_MODELS[@]}"; do
        echo "    [OK] $m"
    done
fi
echo ""
echo "  Failed:     $FAIL_COUNT / $TOTAL"
if [ ${#FAILED_MODELS[@]} -gt 0 ]; then
    for m in "${FAILED_MODELS[@]}"; do
        echo "    [FAIL] $m"
    done
fi
echo ""
echo "  S3 location: s3://$BUCKET/model-cache/"
echo ""
# --------------------------------------------------------------------------
# What this script does NOT seed. Say it out loud.
# --------------------------------------------------------------------------
# Measured 2026-09-26: ap-northeast-2 was brought up by running this script, which
# completed cleanly and reported success — and left a region where M5, M6, M9 and M10
# could not run, because hf-cache/ was never created. This script writes model-cache/
# ONLY, and in a flat `hf download --local-dir` layout that is NOT the HuggingFace
# offline cache tree the Cosmos/Alpamayo runtimes read. A green run here is therefore
# not evidence that the region is usable, and nothing said so until a participant found
# out four modules in.
echo "  !!  NOT SEEDED BY THIS SCRIPT — still required for M5/M6/M9/M10  !!"
echo ""
echo "  This script writes model-cache/ only (flat layout, for M2/M8). The Cosmos and"
echo "  Alpamayo runtimes read a DIFFERENT prefix in a DIFFERENT layout — the HuggingFace"
echo "  offline cache TREE at hf-cache/hub/. Copy it from a region that already has it:"
echo ""
echo "    aws s3 sync s3://av30lab-shared-data-<acct>-<seeded-region>/hf-cache/ \\"
echo "                s3://$BUCKET/hf-cache/ \\"
echo "                --source-region <seeded-region> --region $REGION"
echo ""
echo "    aws s3 sync s3://av30lab-shared-data-<acct>-<seeded-region>/m10-reference/ \\"
echo "                s3://$BUCKET/m10-reference/ \\"
echo "                --source-region <seeded-region> --region $REGION"
echo ""
echo "  Sync hf-cache/ and not hf-cache/hub/, so hf-cache/alpamayo-demo/ (M9's demo clip)"
echo "  and the refs/ files come along."
echo ""
echo "  Then verify — do not assume:"
echo "    ./scripts/check_seeding.sh --region $REGION --source-region <seeded-region>"
echo ""

# Offer cleanup
read -r -p "Remove local temp files ($TEMP_DIR)? [Y/n] " CLEANUP
CLEANUP="${CLEANUP:-Y}"
if [[ "$CLEANUP" =~ ^[Yy] ]]; then
    rm -rf "$TEMP_DIR"
    echo "  Temp files removed."
else
    echo "  Temp files kept at: $TEMP_DIR"
fi

echo ""
if [ $FAIL_COUNT -gt 0 ]; then
    echo "Some models failed. Re-run after fixing the issues above."
    exit 1
fi
echo "All models cached successfully."
