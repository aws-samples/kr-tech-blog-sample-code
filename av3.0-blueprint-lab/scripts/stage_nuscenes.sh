#!/bin/bash
# stage_nuscenes.sh — Upload the nuScenes v1.0-mini dataset to the shared S3
# bucket for AV 3.0 Blueprint Lab (consumed by M1, M2, M7).
#
# nuScenes-mini is available two ways:
#
#   EASIEST — pull from the public AWS Open Data mirror (no login, no license
#   gate at download time; usage still governed by nuScenes terms of use). This
#   is the default when neither NUSCENES_TGZ nor NUSCENES_DIR is set:
#            ./scripts/stage_nuscenes.sh
#   Source: s3://motional-nuscenes/public/v1.0/v1.0-mini.tgz (ap-northeast-1,
#   --no-sign-request). Override with NUSCENES_S3_SOURCE=s3://.../file.tgz.
#
#   MANUAL — if you already have the archive (e.g. downloaded from
#   https://www.nuscenes.org/nuscenes after signup), point the script at it:
#            NUSCENES_TGZ=/path/to/v1.0-mini.tgz ./scripts/stage_nuscenes.sh
#            NUSCENES_DIR=/path/to/extracted     ./scripts/stage_nuscenes.sh
#
# The dataset is uploaded to:
#   s3://<SHARED_BUCKET>/datasets/nuscenes-mini/
# with the standard layout the notebooks expect:
#   datasets/nuscenes-mini/v1.0-mini/*.json   (metadata tables)
#   datasets/nuscenes-mini/samples/CAM_FRONT/*.jpg  (+ other sensors)
#
# Bucket resolution (same convention as cache_models.sh):
#   MODEL_BUCKET env var  >  first CLI arg  >  CloudFormation stack output
set -uo pipefail

# Region must be explicit — NO literal default. See cache_models.sh for the full
# rationale: the destination bucket comes from the CloudFormation stack in $REGION, so a
# default silently re-seeds the FIRST region after a second region is deployed.
# (NUSCENES_S3_REGION below is unrelated — it is the public source bucket's region.)
REGION="${AWS_REGION:-}"
if [ -z "$REGION" ]; then
    echo "ERROR: set AWS_REGION (e.g. AWS_REGION=ap-northeast-2 $0)." >&2
    echo "       Refusing to guess: guessing seeds the wrong region, silently." >&2
    exit 2
fi
STACK_NAME="Av30BlueprintLabStack"
DEST_PREFIX="datasets/nuscenes-mini/"

echo "=== AV 3.0 Blueprint Lab — nuScenes-mini Staging ==="
echo ""

# --------------------------------------------------------------------------
# Pre-flight
# --------------------------------------------------------------------------
for cmd in aws jq tar; do
    if ! command -v "$cmd" &> /dev/null; then
        echo "ERROR: '$cmd' is not installed or not in PATH."
        exit 1
    fi
done

# Public AWS Open Data mirror (used when no local source is provided).
NUSCENES_S3_SOURCE="${NUSCENES_S3_SOURCE:-s3://motional-nuscenes/public/v1.0/v1.0-mini.tgz}"
NUSCENES_S3_REGION="${NUSCENES_S3_REGION:-ap-northeast-1}"

# --------------------------------------------------------------------------
# Resolve S3 bucket (MODEL_BUCKET > arg > CFN output)
# --------------------------------------------------------------------------
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
        echo "  Deploy first, or pass the bucket name:"
        echo "  MODEL_BUCKET=my-bucket ./scripts/stage_nuscenes.sh"
        exit 1
    }
    BUCKET=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="SharedDataBucketArn") | .OutputValue' | sed 's|arn:aws:s3:::||')
    if [ -z "$BUCKET" ] || [ "$BUCKET" = "null" ]; then
        echo "ERROR: Could not find SharedDataBucketArn in stack outputs."
        exit 1
    fi
    echo "Resolved bucket from stack: $BUCKET"
fi

echo "Region:      $REGION"
echo "Bucket:      $BUCKET"
echo "Destination: s3://$BUCKET/$DEST_PREFIX"
echo ""

# --------------------------------------------------------------------------
# Obtain a local directory containing the dataset
# --------------------------------------------------------------------------
CLEANUP_DIR=""
CLEANUP_TGZ=""
if [ -n "${NUSCENES_DIR:-}" ]; then
    SRC_DIR="$NUSCENES_DIR"
    echo "Using pre-extracted directory: $SRC_DIR"
else
    # If no local archive was given, pull it from the public mirror.
    if [ -z "${NUSCENES_TGZ:-}" ]; then
        NUSCENES_TGZ="$(mktemp "${TMPDIR:-/tmp}/v1.0-mini.XXXXXX.tgz")"
        CLEANUP_TGZ="$NUSCENES_TGZ"
        echo "Downloading $NUSCENES_S3_SOURCE (~4 GB) from public mirror..."
        aws s3 cp --no-sign-request "$NUSCENES_S3_SOURCE" "$NUSCENES_TGZ" \
            --region "$NUSCENES_S3_REGION" --only-show-errors || {
            echo "ERROR: download from public mirror failed."
            rm -f "$CLEANUP_TGZ"
            exit 1
        }
    fi
    if [ ! -f "$NUSCENES_TGZ" ]; then
        echo "ERROR: archive not found: $NUSCENES_TGZ"
        exit 1
    fi
    SRC_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nuscenes-mini.XXXXXX")"
    CLEANUP_DIR="$SRC_DIR"
    echo "Extracting $NUSCENES_TGZ -> $SRC_DIR ..."
    tar -xzf "$NUSCENES_TGZ" -C "$SRC_DIR" || {
        echo "ERROR: extraction failed."
        rm -rf "$CLEANUP_DIR"; rm -f "$CLEANUP_TGZ"
        exit 1
    }
    [ -n "$CLEANUP_TGZ" ] && rm -f "$CLEANUP_TGZ"
fi

# --------------------------------------------------------------------------
# Verify the expected layout (some archives nest under an extra dir)
# --------------------------------------------------------------------------
if [ ! -f "$SRC_DIR/v1.0-mini/scene.json" ]; then
    # look one level down for a wrapper directory
    CAND=$(find "$SRC_DIR" -maxdepth 2 -type f -name scene.json -path '*/v1.0-mini/*' 2>/dev/null | head -1)
    if [ -n "$CAND" ]; then
        SRC_DIR="$(dirname "$(dirname "$CAND")")"
        echo "Detected dataset root at: $SRC_DIR"
    fi
fi

if [ ! -f "$SRC_DIR/v1.0-mini/scene.json" ]; then
    echo "ERROR: v1.0-mini/scene.json not found under $SRC_DIR."
    echo "  This does not look like the nuScenes-mini archive."
    [ -n "$CLEANUP_DIR" ] && rm -rf "$CLEANUP_DIR"
    exit 1
fi
if [ ! -d "$SRC_DIR/samples/CAM_FRONT" ]; then
    echo "WARNING: samples/CAM_FRONT not found — M1 image display / M7 will fail,"
    echo "         but metadata-only M1 exploration will still work."
fi
echo "Layout verified: v1.0-mini/ metadata present."
echo ""

# --------------------------------------------------------------------------
# Upload
# --------------------------------------------------------------------------
echo "Uploading to s3://$BUCKET/$DEST_PREFIX (this may take a few minutes)..."
aws s3 sync "$SRC_DIR/" "s3://$BUCKET/$DEST_PREFIX" \
    --region "$REGION" --only-show-errors || {
    echo "ERROR: upload failed."
    [ -n "$CLEANUP_DIR" ] && rm -rf "$CLEANUP_DIR"
    exit 1
}

# --------------------------------------------------------------------------
# Post-check + cleanup
# --------------------------------------------------------------------------
echo ""
echo "Verifying upload..."
JSON_COUNT=$(aws s3 ls "s3://$BUCKET/${DEST_PREFIX}v1.0-mini/" --region "$REGION" 2>/dev/null | grep -c '\.json' || true)
echo "  metadata JSON files in v1.0-mini/: $JSON_COUNT"

[ -n "$CLEANUP_DIR" ] && rm -rf "$CLEANUP_DIR"

echo ""
echo "=== Done. nuScenes-mini staged at s3://$BUCKET/$DEST_PREFIX ==="
echo "M1 / M2 / M7 can now read the dataset."
