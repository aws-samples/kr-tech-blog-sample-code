#!/usr/bin/env bash
# check_seeding.sh — assert that a region's shared-data bucket is actually seeded.
#
# WHY THIS EXISTS
# ---------------
# Measured in ap-northeast-2 on 2026-09-26: the region was brought up by running
# scripts/cache_models.sh, which seeds ONLY model-cache/. The HuggingFace offline cache
# tree at hf-cache/hub/ was therefore never created — and nothing anywhere noticed.
# deploy.sh ran 15 guards, every one of them green; the Day-1 smoke test exercised M1 and
# M2, the only two modules whose prefixes happen to be seeded by that script; and
# setup_cosmos_env.sh printed a one-line warning 20 minutes before the failure and then
# exited 0. The first thing to detect the gap was a participant, four modules in, holding
# a $8.72/hr GPU, reading a torchrun ChildFailedError that named CUDA out-of-memory for a
# HuggingFace 401.
#
# So: this runs AFTER seeding and BEFORE anyone is provisioned.
#
# PRESENCE IS NOT ENOUGH — the central design point.
# HuggingFace offline mode performs NO integrity checking whatsoever: a 0-byte file at the
# right path is reported as a successful download. And a half-finished `aws s3 sync` is
# worse than an empty prefix: setup_cosmos_env.sh will restore it, its own shape check may
# be satisfied by whichever repos did arrive, and every still-missing checkpoint then stops
# being a download and becomes an opaque "Local entry not found ... offline mode is
# enabled" — twenty minutes in, on a GPU. So this script asserts TREE SHAPE with EXPECTED
# OBJECT COUNTS per repo (a presence test passes a sync killed after three objects),
# asserts a specific named object is non-zero, and — when given --source-region — compares
# CRC64 checksums, not sizes. `aws s3 sync` itself compares size+mtime, so it cannot tell
# you whether the bytes match; that is the blind spot this closes.
#
# Usage:
#   ./scripts/check_seeding.sh --region ap-northeast-2
#   ./scripts/check_seeding.sh --region ap-northeast-2 --source-region us-west-2
#
# Exit: 0 = every REQUIRED prefix present and well-shaped. 1 = something required is
# missing or malformed (message says which modules break). 2 = usage/credential problem.
set -uo pipefail

REGION=""
SOURCE_REGION=""
BUCKET=""
PROFILE_ARG=()

# needval: `shift 2` with only one argument left FAILS and shifts NOTHING, so the loop
# re-reads the same flag forever — an admin typo (`--region` with no value) hung the
# script at 100% CPU instead of the documented exit 2.
needval() {
    [ "$1" -ge 2 ] || { echo "ERROR: $2 requires a value." >&2; exit 2; }
}
while [ $# -gt 0 ]; do
    case "$1" in
        --region)        needval $# --region;        REGION="$2";  shift 2 ;;
        --source-region) needval $# --source-region; SOURCE_REGION="$2"; shift 2 ;;
        --bucket)        needval $# --bucket;        BUCKET="$2";  shift 2 ;;
        --profile)       needval $# --profile;       PROFILE_ARG=(--profile "$2"); shift 2 ;;
        -h|--help)
            # Track the header block rather than a line number, which drifted out of date
            # the first time this file was edited and truncated the exit-code contract.
            sed -n '2,/^set -/p' "$0" | sed '$d; s/^# \{0,1\}//'
            exit 0 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

if [ -z "$REGION" ]; then
    echo "ERROR: --region is required." >&2
    echo "       It is not defaulted on purpose: the whole failure this script exists to" >&2
    echo "       catch came from a seeding command that silently assumed us-west-2." >&2
    exit 2
fi

ACCT="$(aws sts get-caller-identity "${PROFILE_ARG[@]+"${PROFILE_ARG[@]}"}" \
        --query Account --output text 2>/dev/null)"
if [ -z "$ACCT" ] || [ "$ACCT" = "None" ]; then
    echo "ERROR: could not resolve the AWS account (credentials?)." >&2
    exit 2
fi
[ -n "$BUCKET" ] || BUCKET="av30lab-shared-data-${ACCT}-${REGION}"

# A self-comparison passes every check while validating nothing — the CRC and the object
# count are both compared against themselves.
if [ -n "$SOURCE_REGION" ] && [ "$SOURCE_REGION" = "$REGION" ]; then
    echo "ERROR: --source-region must differ from --region (comparing a region with" >&2
    echo "       itself is a tautology: every check would pass by construction)." >&2
    exit 2
fi

echo "=== Seeding check ==="
echo "Account : $ACCT"
echo "Region  : $REGION"
echo "Bucket  : s3://$BUCKET"
[ -n "$SOURCE_REGION" ] && echo "Compare : against av30lab-shared-data-${ACCT}-${SOURCE_REGION}"
echo ""

FAILED=0
WARNED=0

# key_count <prefix> -> integer
#
# Uses list-objects-v2 --query KeyCount. Do NOT rewrite this as
# `--query 'length(Contents)'`: on an ABSENT prefix Contents is null and the CLI exits
# 255 with "In function length(), invalid type for value: None", which under `|| true`
# is indistinguishable from "empty" and under `set -e` kills the script. KeyCount is
# always a number.
key_count() {
    aws s3api list-objects-v2 --bucket "$BUCKET" --prefix "$1" --max-keys 1 \
        --region "$REGION" "${PROFILE_ARG[@]+"${PROFILE_ARG[@]}"}" \
        --query KeyCount --output text 2>/dev/null || echo 0
}

# obj_count <prefix> -> total objects under the prefix (not capped at a page).
# Separate from key_count on purpose: key_count passes --max-keys 1 and answers only
# "is there anything here", while the tree-shape assertion needs a real total.
obj_count() {
    aws s3 ls "s3://$BUCKET/$1" --recursive --region "$REGION" \
        "${PROFILE_ARG[@]+"${PROFILE_ARG[@]}"}" 2>/dev/null \
        | awk '$4 !~ /\/$/ {n++} END {print n+0}'
}

# object_ok <key> -> 0 when the object exists AND has a non-zero size.
# Size matters: HF treats a 0-byte file as a completed download.
object_ok() {
    local size
    size="$(aws s3api head-object --bucket "$BUCKET" --key "$1" --region "$REGION" \
            "${PROFILE_ARG[@]+"${PROFILE_ARG[@]}"}" --query ContentLength --output text 2>/dev/null)"
    [ -n "$size" ] && [ "$size" != "None" ] && [ "$size" -gt 0 ] 2>/dev/null
}

# require <prefix> <modules-that-break>
require() {
    local prefix="$1" modules="$2" n
    n="$(key_count "$prefix")"
    if [ "${n:-0}" -ge 1 ]; then
        printf "  [ OK   ] %-46s\n" "$prefix"
    else
        printf "  [ FAIL ] %-46s EMPTY/ABSENT -> breaks %s\n" "$prefix" "$modules"
        FAILED=$((FAILED + 1))
    fi
}

# optional <prefix> <modules> — absence is reported but never fails the run.
# Classified this way deliberately: a gate that fires on something which cannot break a
# module is a gate people learn to skip, which is how hf-cache/ slipped through in the
# first place.
optional() {
    local prefix="$1" modules="$2" n
    n="$(key_count "$prefix")"
    if [ "${n:-0}" -ge 1 ]; then
        printf "  [ OK   ] %-46s\n" "$prefix"
    else
        printf "  [ warn ] %-46s absent -> %s\n" "$prefix" "$modules"
        WARNED=$((WARNED + 1))
    fi
}

echo "--- Required prefixes ---"
require "datasets/nuscenes-mini/"        "M1 (and everything downstream of it)"
require "notebook-templates/"            "new participant provisioning"
require "model-cache/cosmos-reason1/"    "M2, M8"
require "hf-cache/hub/"                  "M5, M6, M9"

echo ""
echo "--- hf-cache tree shape (what the runtime globs actually test) ---"
# These are the exact directory names setup_cosmos_env.sh globs for. A KeyCount>=1 on
# hf-cache/hub/ above says only that SOMETHING is there — an interrupted sync passes it.
# Each entry carries the EXPECTED object count, measured from the seeded us-west-2 tree
# on 2026-09-26. A >=1 presence test is not enough and is not a theoretical concern: an
# `aws s3 sync` killed after three objects leaves every repo directory existing, passes a
# presence test, and then flips HF_HUB_OFFLINE=1 on a tree that is missing almost
# everything. Counting is what makes the DEFAULT invocation (the one deploy.sh uses, with
# no --source-region) able to detect that.
#
# A count below the expectation is a hard FAIL. A count ABOVE it is only a warning: the
# upstream repos legitimately gain files over time, and this must not become a gate that
# fires on a newer, perfectly good cache.
for entry in \
    "models--nvidia--Cosmos-Transfer2.5-2B|2|M5" \
    "models--nvidia--Cosmos-Predict2.5-2B|4|M5, M6" \
    "models--nvidia--Cosmos-Guardrail1|192|M5, M6" \
    "models--nvidia--Alpamayo-1.5-10B|16|M9" \
    "models--nvidia--Cosmos-Reason2-8B|22|M9 (Alpamayo's backbone)"
do
    repo="${entry%%|*}"; rest="${entry#*|}"; want="${rest%%|*}"; mods="${rest##*|}"
    n="$(obj_count "hf-cache/hub/${repo}/")"
    if [ "${n:-0}" -eq 0 ]; then
        printf "  [ FAIL ] %-38s MISSING -> breaks %s\n" "$repo" "$mods"
        FAILED=$((FAILED + 1))
    elif [ "${n:-0}" -lt "$want" ]; then
        printf "  [ FAIL ] %-38s %s/%s objects — INCOMPLETE -> breaks %s\n" \
            "$repo" "$n" "$want" "$mods"
        FAILED=$((FAILED + 1))
    elif [ "${n:-0}" -gt "$want" ]; then
        printf "  [ warn ] %-38s %s objects (expected %s — upstream may have grown)\n" \
            "$repo" "$n" "$want"
        WARNED=$((WARNED + 1))
    else
        printf "  [ OK   ] %-38s %s objects\n" "$repo" "$n"
    fi
done

echo ""
echo "--- Named object assertion ---"
# The exact object M5 died on. cosmos's checkpoint_db.py pins this commit sha, so the
# cache must hold THAT revision — HF HEAD for the repo has already moved past it, and an
# offline lookup of a different sha is a miss. Asserting the specific file also catches
# the case a prefix check cannot: present path, zero bytes.
TOKENIZER="hf-cache/hub/models--nvidia--Cosmos-Predict2.5-2B/snapshots/f176dc95b4a70f53ce01c4b302851595e7322b00/tokenizer.pth"
if object_ok "$TOKENIZER"; then
    echo "  [ OK   ] Cosmos-Predict2.5-2B @f176dc95 tokenizer.pth (non-zero)"
else
    echo "  [ FAIL ] $TOKENIZER"
    echo "           missing or 0 bytes. This is the precise object M5's traceback died"
    echo "           on. HF offline mode does not verify integrity, so a 0-byte file here"
    echo "           fails LATER and more opaquely than an absent one."
    FAILED=$((FAILED + 1))
fi

echo ""
echo "--- M9 demo clip (required) ---"
# alpamayo-demo/ is REQUIRED, not optional: M9 cell 5 does `aws s3 cp` of the demo .pt
# and raises on a non-zero exit, and the upstream dataset needed to regenerate it is
# itself gated — so no participant can work around its absence. It was classified
# optional here, which meant the gate printed PASS and exited 0 on a region where M9
# cannot run, and exit 0 is what an automated caller consumes.
require "hf-cache/alpamayo-demo/" "M9 (cell 5 raises; only an admin can produce the clip)"

echo ""
echo "--- Optional prefixes ---"
# m10-reference/ stays optional: M10 is itself optional in the lab.
optional "m10-reference/"          "M10 raises 'No M10 AlpaSim results found in S3'"

# --------------------------------------------------------------------------
# Cross-region comparison (only when asked)
# --------------------------------------------------------------------------
# Compares CHECKSUMS, not sizes. `aws s3 sync` itself compares size+mtime, so it cannot
# tell you whether the bytes match — which is exactly the blind spot that lets a bad copy
# survive a re-sync.
if [ -n "$SOURCE_REGION" ]; then
    SRC_BUCKET="av30lab-shared-data-${ACCT}-${SOURCE_REGION}"
    echo ""
    echo "--- Checksum comparison vs $SOURCE_REGION ---"
    crc() {
        aws s3api head-object --bucket "$1" --key "$2" --region "$3" \
            "${PROFILE_ARG[@]+"${PROFILE_ARG[@]}"}" --checksum-mode ENABLED \
            --query 'ChecksumCRC64NVME' --output text 2>/dev/null
    }
    a="$(crc "$SRC_BUCKET" "$TOKENIZER" "$SOURCE_REGION")"
    b="$(crc "$BUCKET" "$TOKENIZER" "$REGION")"
    if [ -z "$a" ] || [ "$a" = "None" ]; then
        echo "  [ warn ] source has no CRC64 for the tokenizer — cannot compare"
        WARNED=$((WARNED + 1))
    elif [ "$a" = "$b" ]; then
        echo "  [ OK   ] tokenizer.pth CRC64 matches ($a)"
    else
        echo "  [ FAIL ] tokenizer.pth CRC64 differs: source=$a dest=$b"
        FAILED=$((FAILED + 1))
    fi

    # Object-count parity over the whole tree.
    #
    # total() keeps the listing's exit status, because collapsing a FAILED source listing
    # to 0 is not a neutral default: it reported a fully-seeded destination as INCOMPLETE
    # and told the operator to re-sync 115 GiB, which cannot clear the error, so they loop.
    # Degrade to a warning the way the sibling CRC branch above already does.
    TOTAL_RC=0
    total() {
        local out
        out="$(aws s3 ls "s3://$1/hf-cache/" --recursive --region "$2" \
               "${PROFILE_ARG[@]+"${PROFILE_ARG[@]}"}" 2>&1)"
        TOTAL_RC=$?
        [ "$TOTAL_RC" -eq 0 ] || { printf '%s' "$out" | head -1; return 0; }
        printf '%s\n' "$out" | awk '$4 !~ /\/$/ {n++} END {print n+0}'
    }
    sn="$(total "$SRC_BUCKET" "$SOURCE_REGION")"; sn_rc=$TOTAL_RC
    dn="$(total "$BUCKET" "$REGION")"; dn_rc=$TOTAL_RC
    if [ "$sn_rc" -ne 0 ] || [ "$dn_rc" -ne 0 ]; then
        echo "  [ warn ] could not list one of the buckets — parity not checked"
        [ "$sn_rc" -ne 0 ] && echo "           source: $sn"
        [ "$dn_rc" -ne 0 ] && echo "           dest:   $dn"
        WARNED=$((WARNED + 1))
    elif [ "${sn:-0}" -gt 0 ] && [ "${dn:-0}" -ge "${sn:-0}" ]; then
        echo "  [ OK   ] hf-cache object count: $dn here vs $sn in $SOURCE_REGION"
    else
        echo "  [ FAIL ] hf-cache object count: $dn here vs $sn in $SOURCE_REGION — INCOMPLETE"
        echo "           A partial tree is worse than an empty one: it flips"
        echo "           HF_HUB_OFFLINE=1 on and turns downloads into opaque cache misses."
        FAILED=$((FAILED + 1))
    fi
fi

echo ""
if [ "$FAILED" -eq 0 ]; then
    echo "=== PASS — $REGION is seeded ($WARNED optional prefix(es) absent) ==="
    exit 0
fi

echo "=== FAIL — $FAILED required check(s) failed. DO NOT provision participants yet. ==="
echo ""
echo "To seed hf-cache/ from an already-working region (bucket-to-bucket, ~115 GiB):"
echo "  aws s3 sync s3://av30lab-shared-data-${ACCT}-<seeded-region>/hf-cache/ \\"
echo "              s3://${BUCKET}/hf-cache/ \\"
echo "              --source-region <seeded-region> --region ${REGION}"
echo ""
echo "Sync hf-cache/ — NOT hf-cache/hub/ — so the alpamayo-demo clip and the refs/ files"
echo "come along. Use the CLI, not a hand-rolled CopyObject loop: two objects exceed the"
echo "5 GiB single-copy limit and need multipart."
echo ""
echo "No seeded region to copy from? Build the tree instead (admin HF_TOKEN required,"
echo "no GPU, ~30-60 min):"
echo "  AWS_REGION=${REGION} HF_TOKEN=hf_... ./scripts/cache_hf_tree.sh"
echo ""
echo "cache_models.sh does NOT produce this prefix: it writes model-cache/ only, in a flat"
echo "layout rather than the HuggingFace offline cache tree. A clean run of it is not"
echo "evidence that this check will pass."
exit 1
