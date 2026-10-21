#!/usr/bin/env bash
# cache_hf_tree.sh — BUILD the HuggingFace offline cache tree and upload it to S3.
#
# WHY THIS EXISTS
# ---------------
# s3://<shared>/hf-cache/hub/ is the offline HF cache that M5, M6 and M9 read so that
# participants need no HuggingFace account. Until now NOTHING in this repository produced
# it. Every hf-cache reference in scripts/ read FROM S3; the only recipe was a manual
# ritual (docs/en/ADMIN_GUIDE.md §6.3: run M5, M6 and M9 once each on a GPU app with an
# admin token, then sync the cache up). cache_models.sh looks like the seeding script but
# writes a different prefix in a different layout and cannot produce this tree.
#
# The consequence, measured on 2026-09-26: an operator followed the README quick start
# verbatim, ran cache_models.sh, got a clean exit — and shipped ap-northeast-2 with M5, M6,
# M9 and M10 unable to run. deploy.sh reported success and all 15 of its guards were green.
# An artifact that cannot be rebuilt from the repo is an artifact that gets skipped.
#
# This script closes that hole. It needs NO GPU and runs NO notebook: it downloads exactly
# the repos, revisions and files recorded in scripts/hf_cache_manifest.tsv into a scratch
# HF_HOME, then syncs that cache tree to S3.
#
# WHAT IT STILL REQUIRES: an HF_TOKEN whose account has accepted the gated licences. That
# is not a limitation of this script — those bytes are gated at the source and no amount of
# tooling removes the licence click. See docs/en/PREREQUISITES.md for the list.
#
# WHEN TO USE WHICH PATH
#   * You already run the lab in another region -> DON'T use this. Copy bucket-to-bucket
#     (README step 6b); it is faster, needs no token, and is byte-exact.
#   * This is your FIRST region -> use this. There is nothing to copy from.
#
# Usage:
#   AWS_REGION=us-west-2 HF_TOKEN=hf_... ./scripts/cache_hf_tree.sh
#   AWS_REGION=us-west-2 HF_TOKEN=hf_... ./scripts/cache_hf_tree.sh --dry-run
#   ./scripts/cache_hf_tree.sh --regenerate       # rewrite the manifest from a seeded tree
#
# Env:
#   AWS_REGION   (required) the region whose shared bucket to seed. Never defaulted — a
#                defaulted region is how a second-region seed once overwrote the first.
#   HF_TOKEN     (required unless --dry-run) admin token with the licences accepted.
#   SHARED_BUCKET  override the derived bucket name.
#   HF_SCRATCH   where to build the cache (default $TMPDIR/av30-hf-tree). Needs ~65 GiB.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="$SCRIPT_DIR/hf_cache_manifest.tsv"
DRY_RUN=0
REGENERATE=0

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)    DRY_RUN=1; shift ;;
        --regenerate) REGENERATE=1; shift ;;
        -h|--help)    sed -n '2,/^set -/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

REGION="${AWS_REGION:-}"
if [ -z "$REGION" ]; then
    echo "ERROR: AWS_REGION is required and is deliberately not defaulted." >&2
    echo "       A defaulted region is how seeding a second region once rewrote the" >&2
    echo "       first region's bucket." >&2
    exit 2
fi

ACCT="$(aws sts get-caller-identity --query Account --output text 2>/dev/null)"
if [ -z "$ACCT" ] || [ "$ACCT" = "None" ]; then
    echo "ERROR: could not resolve the AWS account (credentials?)." >&2
    exit 2
fi
BUCKET="${SHARED_BUCKET:-av30lab-shared-data-${ACCT}-${REGION}}"
DEST="s3://${BUCKET}/hf-cache/hub/"

# --------------------------------------------------------------------------
# --regenerate: rewrite the manifest from a tree that is already known good.
# --------------------------------------------------------------------------
# The manifest must be GENERATED, never hand-maintained. Hand-typing it would have missed
# that nvidia/Cosmos-Predict2.5-2B is pinned at TWO revisions, and would have omitted the
# Qwen / google-siglip transitive dependencies that no NVIDIA document lists.
if [ "$REGENERATE" -eq 1 ]; then
    echo "Reading an S3 --recursive listing of a SEEDED hf-cache/hub/ on stdin..."
    # The generator goes to a temp FILE, not `python3 - <<EOF`. With `python3 -`, the
    # interpreter reads the PROGRAM from stdin, so the heredoc consumes the very listing
    # the program is supposed to parse and it always reports "no snapshot files found".
    _gen="$(mktemp "${TMPDIR:-/tmp}/av30-hfgen.XXXXXX.py")"
    trap 'rm -f "$_gen"' EXIT
    cat > "$_gen" <<'PYGEN'
import collections, re, sys
rows = []
for line in sys.stdin:
    p = line.split(None, 3)
    if len(p) < 4:
        continue
    m = re.match(r'.*hf-cache/hub/models--([^/]+)/snapshots/([0-9a-f]{40})/(.+)$', p[3].strip())
    if not m:
        continue
    parts = m.group(1).split('--')
    rows.append((f"{parts[0]}/{'--'.join(parts[1:])}", m.group(2), m.group(3)))
if not rows:
    sys.exit("No snapshot files found on stdin — was that a seeded hf-cache/hub/ listing?")
by = collections.defaultdict(list)
for repo, sha, f in rows:
    by[(repo, sha)].append(f)
with open(sys.argv[1], 'w') as fh:
    fh.write("# hf_cache_manifest.tsv — GENERATED by cache_hf_tree.sh --regenerate.\n")
    fh.write("# Format: <repo>\\t<revision>\\t<file>\n")
    fh.write(f"# {len(rows)} files, {len(by)} (repo, revision) pairs.\n\n")
    for (repo, sha), files in sorted(by.items()):
        for f in sorted(files):
            fh.write(f"{repo}\t{sha}\t{f}\n")
print(f"Wrote {sys.argv[1]}: {len(rows)} files, {len(by)} (repo, revision) pairs.")
PYGEN
    python3 "$_gen" "$MANIFEST"
    exit $?
fi

[ -r "$MANIFEST" ] || { echo "ERROR: manifest not found: $MANIFEST" >&2; exit 2; }

if [ "$DRY_RUN" -eq 0 ] && [ -z "${HF_TOKEN:-}" ]; then
    echo "ERROR: HF_TOKEN is required." >&2
    echo "       The Cosmos/Alpamayo checkpoints are GATED at the source. Create a read" >&2
    echo "       token and accept the licences on every repo listed in" >&2
    echo "       docs/en/PREREQUISITES.md, then re-run. --dry-run needs no token." >&2
    exit 2
fi

SCRATCH="${HF_SCRATCH:-${TMPDIR:-/tmp}/av30-hf-tree}"
export HF_HOME="$SCRATCH"
export HF_HUB_DISABLE_XET=1   # the chunked backend errors with "Unable to parse string as hex hash value"
unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE  # we are deliberately ONLINE here

PAIRS="$(awk -F'\t' '!/^#/ && NF==3 {print $1"\t"$2}' "$MANIFEST" | sort -u | grep -c . || echo 0)"
FILES="$(awk -F'\t' '!/^#/ && NF==3' "$MANIFEST" | grep -c . || echo 0)"

echo "=== Build the HF offline cache tree ==="
echo "Manifest : $MANIFEST ($FILES files across $PAIRS repo+revision pairs)"
echo "Scratch  : $SCRATCH  (needs ~65 GiB free)"
echo "Dest     : $DEST"
echo "Region   : $REGION"
[ "$DRY_RUN" -eq 1 ] && echo "MODE     : DRY RUN — nothing is downloaded or uploaded"
echo ""

# Disk pre-check. `hf download` on a full volume does not fail fast, it stalls at ~0%.
if [ "$DRY_RUN" -eq 0 ]; then
    mkdir -p "$SCRATCH"
    AVAIL_GIB="$(df -Pk "$SCRATCH" | awk 'NR==2 {printf "%d", $4/1048576}')"
    if [ "${AVAIL_GIB:-0}" -lt 65 ]; then
        echo "ERROR: only ${AVAIL_GIB} GiB free at $SCRATCH; need ~65 GiB." >&2
        echo "       Set HF_SCRATCH to a bigger volume (an instance NVMe, not /tmp)." >&2
        exit 2
    fi
    command -v hf >/dev/null 2>&1 || { echo "ERROR: the 'hf' CLI is not on PATH (pip install -U huggingface_hub)." >&2; exit 2; }
    # Fail fast and LOUDLY on a bad token, rather than 12 repos of "Access denied".
    if ! HF_TOKEN="$HF_TOKEN" hf auth whoami >/dev/null 2>&1; then
        echo "ERROR: 'hf auth whoami' failed — HF_TOKEN is invalid or expired." >&2
        exit 2
    fi
    echo "Token OK: $(HF_TOKEN="$HF_TOKEN" hf auth whoami 2>/dev/null | head -1)"
    echo ""
fi

# --------------------------------------------------------------------------
# Download, one (repo, revision) pair at a time, only the manifest's files.
# --------------------------------------------------------------------------
# Per-pair, not per-repo, because a repo can be pinned at more than one revision — and
# file-scoped, because these repos are far larger upstream than what the lab needs
# (Cosmos-Predict2.5-2B contributes exactly two files across its two revisions).
FAIL=0
DONE=0
while IFS=$'\t' read -r repo sha; do
    [ -n "$repo" ] || continue
    # Read into an array WITHOUT mapfile: that is a bash 4+ builtin, and macOS still ships
    # bash 3.2 as /bin/bash, where it silently is not found and every download is skipped.
    # An admin may well run this from a laptop, so 3.2 has to work.
    wanted=()
    while IFS= read -r _f; do
        [ -n "$_f" ] && wanted+=("$_f")
    done < <(awk -F'\t' -v r="$repo" -v s="$sha" '!/^#/ && $1==r && $2==s {print $3}' "$MANIFEST")
    DONE=$((DONE + 1))
    if [ "${#wanted[@]}" -eq 0 ]; then
        echo "[$DONE/$PAIRS] $repo @ ${sha:0:12} — NO FILES in manifest, skipping (malformed?)"
        FAIL=$((FAIL + 1))
        continue
    fi
    printf '[%d/%d] %s @ %s — %d file(s)\n' "$DONE" "$PAIRS" "$repo" "${sha:0:12}" "${#wanted[@]}"
    if [ "$DRY_RUN" -eq 1 ]; then
        printf '        hf download %s --revision %s %s%s\n' "$repo" "${sha:0:12}" "${wanted[0]}" \
            "$([ "${#wanted[@]}" -gt 1 ] && printf ' ... (+%d more)' "$(( ${#wanted[@]} - 1 ))")"
        continue
    fi
    if ! HF_TOKEN="$HF_TOKEN" hf download "$repo" --revision "$sha" "${wanted[@]}" \
         >/dev/null 2>/tmp/hf_dl_err.$$; then
        echo "        FAILED: $(head -2 /tmp/hf_dl_err.$$ | tr '\n' ' ')"
        # "requires approval" / "Access denied" means an unaccepted licence, which is the
        # one failure the operator must act on themselves. Name it explicitly.
        if grep -qiE 'requires approval|access denied' /tmp/hf_dl_err.$$; then
            echo "        ^ that is an UNACCEPTED LICENCE. Visit https://huggingface.co/$repo"
            echo "          and click 'Agree and access repository', then re-run."
        fi
        FAIL=$((FAIL + 1))
    fi
    rm -f /tmp/hf_dl_err.$$
done < <(awk -F'\t' '!/^#/ && NF==3 {print $1"\t"$2}' "$MANIFEST" | sort -u)

if [ "$DRY_RUN" -eq 1 ]; then
    echo ""
    echo "Dry run complete. Re-run without --dry-run to download and upload."
    exit 0
fi

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "=== $FAIL of $PAIRS pair(s) failed — NOT uploading ==="
    echo "Uploading a partial tree is worse than uploading nothing: one repo directory is"
    echo "enough for setup_cosmos_env.sh to consider the cache present, and every missing"
    echo "checkpoint then fails as an opaque 'Local entry not found ... offline mode is"
    echo "enabled' on a participant's GPU instead of as a download."
    exit 1
fi

echo ""
echo "=== Uploading $SCRATCH/hub -> $DEST ==="
if ! aws s3 sync "$SCRATCH/hub" "$DEST" --region "$REGION" --only-show-errors; then
    echo "ERROR: upload failed. Re-run — aws s3 sync resumes." >&2
    exit 1
fi

echo ""
echo "=== Verifying ==="
if [ -x "$SCRIPT_DIR/check_seeding.sh" ]; then
    "$SCRIPT_DIR/check_seeding.sh" --region "$REGION"
    exit $?
fi
echo "(scripts/check_seeding.sh not executable — run it manually to verify)"
