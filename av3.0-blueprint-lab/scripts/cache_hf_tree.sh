#!/usr/bin/env bash
# cache_hf_tree.sh — BUILD the HuggingFace offline cache tree and upload it to S3.
#
# WHY THIS EXISTS
# ---------------
# s3://<shared>/hf-cache/hub/ is the offline HF cache that M5, M6 and M9 read so that
# participants need no HuggingFace account. Until now NOTHING in this repository produced
# it. Every hf-cache reference in scripts/ read FROM S3; the only recipe was a manual
# ritual (run M5, M6 and M9 once each on a GPU app with an admin token, then sync the
# cache up from that app's terminal). That ritual is retired: it needed the execution
# role every participant shares to write hf-cache/, which let any participant replace
# what every other participant's kernel loads. This script, or a bucket-to-bucket copy,
# run from a workstation with admin credentials, is now the only way in
# (docs/en/ADMIN_GUIDE.md §6.3). cache_models.sh looks like the seeding script but
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
# .no_exist MARKERS. A seeded tree also holds a few 0-byte models--*/.no_exist/<sha>/<file>
# files. HuggingFace writes one when an ONLINE load finds that a file does not exist
# upstream; a download never creates them, so this script cannot fetch them. It creates
# the ones the manifest records as `no_exist` rows instead. check_seeding.sh's object
# counts include them: without them Alpamayo-1.5-10B and Cosmos-Reason2-8B came up 15/16
# and 17/22 (measured in 2c9d6d2). Whether M9 actually needs them offline is untested, so
# they stay required. Record them with --record-markers (below), from a tree that has them
# or from the markers an online M9 run wrote (docs/en/ADMIN_GUIDE.md §6.3).
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
#   AWS_REGION=us-west-2 ./scripts/cache_hf_tree.sh --markers-only  # upload only the markers
#   aws s3 ls s3://<...>/ --recursive | ./scripts/cache_hf_tree.sh --record-markers
#   aws s3 ls s3://<shared>/hf-cache/hub/ --recursive | ./scripts/cache_hf_tree.sh --regenerate
#
#   --record-markers  add the markers in an S3 listing on stdin to the manifest's
#                     `no_exist` rows (file rows are untouched): a seeded hf-cache/hub/, or
#                     the staged markers of an online M9 run. Reads key NAMES only, never
#                     object contents; refuses a non-empty marker or one that would hide a
#                     file the manifest downloads, and skips revisions it does not pin.
#   --regenerate      rewrite the WHOLE manifest (files and markers) from a seeded tree.
#   --markers-only    create the recorded markers and upload just those (no token, no
#                     download): for a tree that is already seeded but lacks them.
#
# Env:
#   AWS_REGION   (required, except for --record-markers and --regenerate) the region whose
#                shared bucket to seed. Never defaulted — a defaulted region is how a
#                second-region seed once overwrote the first.
#   HF_TOKEN     (required unless --dry-run) admin token with the licences accepted.
#   SHARED_BUCKET  override the derived bucket name.
#   HF_SCRATCH   where to build the cache (default $TMPDIR/av30-hf-tree). Needs ~65 GiB.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="$SCRIPT_DIR/hf_cache_manifest.tsv"
DRY_RUN=0
REGENERATE=0
RECORD_MARKERS=0
MARKERS_ONLY=0

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)        DRY_RUN=1; shift ;;
        --regenerate)     REGENERATE=1; shift ;;
        --record-markers) RECORD_MARKERS=1; shift ;;
        --markers-only)   MARKERS_ONLY=1; shift ;;
        -h|--help)    sed -n '2,/^set -/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

# --------------------------------------------------------------------------
# --regenerate / --record-markers: rewrite the manifest from an S3 listing.
# --------------------------------------------------------------------------
# Both run BEFORE any AWS call: they only parse stdin and write the manifest, so they need
# no region and no credentials (the listing itself comes from a read-only `aws s3 ls`).
#
# The manifest must be GENERATED, never hand-maintained. Hand-typing it would have missed
# that nvidia/Cosmos-Predict2.5-2B is pinned at TWO revisions, and would have omitted the
# Qwen / google-siglip transitive dependencies that no NVIDIA document lists.
if [ "$REGENERATE" -eq 1 ] || [ "$RECORD_MARKERS" -eq 1 ]; then
    if [ "$REGENERATE" -eq 1 ] && [ "$RECORD_MARKERS" -eq 1 ]; then
        echo "ERROR: use --regenerate or --record-markers, not both." >&2
        exit 2
    fi
    if [ -t 0 ]; then
        echo "ERROR: pipe an 'aws s3 ls s3://<bucket>/<prefix> --recursive' listing into this." >&2
        exit 2
    fi
    MODE=regenerate
    [ "$RECORD_MARKERS" -eq 1 ] && MODE=record
    echo "Reading an S3 --recursive listing on stdin (--$([ "$MODE" = record ] && echo record-markers || echo regenerate))..."
    # The generator goes to a temp FILE, not `python3 - <<EOF`. With `python3 -`, the
    # interpreter reads the PROGRAM from stdin, so the heredoc consumes the very listing
    # the program is supposed to parse and it always reports "no snapshot files found".
    _gen="$(mktemp "${TMPDIR:-/tmp}/av30-hfgen.XXXXXX.py")"
    trap 'rm -f "$_gen"' EXIT
    cat > "$_gen" <<'PYGEN'
import os, re, sys

mode, manifest = sys.argv[1], sys.argv[2]
SNAP = re.compile(r'.*hf-cache/hub/models--([^/]+)/snapshots/([0-9a-f]{40})/(.+)$')
HEX40 = re.compile(r'[0-9a-f]{40}\Z')
BLOCK = ("# --- .no_exist markers (0-byte models--*/.no_exist/<revision>/<file>). Written by "
         "--record-markers / --regenerate; re-run those rather than editing by hand.")


def repo_of(d):
    parts = d.split('--')
    return f"{parts[0]}/{'--'.join(parts[1:])}"


def marker_of(key):
    """(repo, sha, file) for a TOP-LEVEL marker key, None for any other key.

    The FIRST models-- segment must be the repo directory: Cosmos-Guardrail1 ships a small
    HF cache of its own inside snapshots/, and the markers in it are ordinary snapshot
    files of that repo (the google/siglip revision they name is pinned here as well).
    """
    segs = key.split('/')
    i = next((n for n, s in enumerate(segs) if s.startswith('models--')), None)
    if i is None or len(segs) < i + 2 or segs[i + 1] != '.no_exist':
        return None
    sha = segs[i + 2] if len(segs) > i + 2 else ''
    rest = segs[i + 3:]
    if not HEX40.match(sha) or not rest or any(p in ('', '.', '..') for p in rest):
        raise ValueError("not models--<org>--<name>/.no_exist/<40-hex revision>/<file>")
    return repo_of(segs[i][len('models--'):]), sha, '/'.join(rest)


files, markers, bad = set(), set(), []
for line in sys.stdin:
    p = line.split(None, 3)
    if len(p) < 4 or not p[2].isdigit():
        continue
    size, key = int(p[2]), p[3].strip()
    m = SNAP.match(key)
    if m:
        files.add((repo_of(m.group(1)), m.group(2), m.group(3)))
        continue
    try:
        mk = marker_of(key)
    except ValueError as e:
        bad.append(f"{key}: {e}")
        continue
    if mk is not None and size != 0:
        bad.append(f"{key}: {size} bytes, but a marker is always empty")
    elif mk is not None:
        markers.add(mk)
if bad:
    sys.exit("Refusing to touch the manifest. These .no_exist keys are malformed:\n  "
             + "\n  ".join(bad))

if mode == 'regenerate':
    if not files:
        sys.exit("No snapshot files found on stdin — was that a seeded hf-cache/hub/ listing?")
    file_rows, old = files, set()
else:
    if not markers:
        sys.exit("No .no_exist markers found on stdin; the manifest is unchanged.")
    keep, file_rows, old = [], set(), set()
    with open(manifest) as fh:
        for ln in fh.read().splitlines():
            cols = ln.split('\t')
            if len(cols) == 4 and cols[0] == 'no_exist':
                old.add(tuple(cols[1:]))      # merged below, so nothing recorded is lost
                continue
            if ln.startswith(BLOCK[:22]):
                continue                      # the previous block header; rewritten below
            if len(cols) == 3 and not ln.startswith('#'):
                file_rows.add(tuple(cols))
            keep.append(ln)
    while keep and not keep[-1].strip():
        keep.pop()

# A marker for a file the manifest downloads would make HF report that file as absent.
hides = sorted(mk for mk in markers | old if mk in file_rows)
if hides:
    sys.exit("Refusing: these markers would hide files the manifest downloads:\n  "
             + "\n  ".join(f"{r}@{s[:12]}/{f}" for r, s, f in hides))
pins = {(r, s) for r, s, _ in file_rows}
new = sorted(mk for mk in markers if mk[:2] in pins)
for r, s, f in sorted(markers - set(new)):
    print(f"  skipped {r}@{s[:12]}/{f}: revision not pinned by the manifest"
          " (did upstream 'main' move past the pin?)")
if mode == 'record' and not new:
    sys.exit("None of the markers is at a pinned revision; the manifest is unchanged.")
# record MERGES with what is already recorded: whether a file exists at a fixed commit
# never changes, so a marker at a pinned revision cannot go stale, and a listing that saw
# only M9's repos must not drop markers recorded from a full tree.
kept = sorted(set(new) | {mk for mk in old if mk[:2] in pins}) if mode == 'record' else new

if mode == 'regenerate':
    pairs = {(r, s) for r, s, _ in file_rows}
    out = ["# hf_cache_manifest.tsv — GENERATED by cache_hf_tree.sh --regenerate.",
           "# Format: <repo>\\t<revision>\\t<file>, and no_exist\\t<repo>\\t<revision>\\t<file>",
           "# for a 0-byte .no_exist marker (see cache_hf_tree.sh).",
           f"# {len(file_rows)} files, {len(pairs)} (repo, revision) pairs, {len(kept)} markers.",
           ""]
    out += [f"{r}\t{s}\t{f}" for r, s, f in sorted(file_rows)]
else:
    out = keep
if kept:
    out += ["", BLOCK] + [f"no_exist\t{r}\t{s}\t{f}" for r, s, f in kept]
tmp = manifest + ".tmp"
with open(tmp, "w") as fh:
    fh.write("\n".join(out) + "\n")
os.replace(tmp, manifest)
added = len(set(kept) - old) if mode == 'record' else len(kept)
print(f"Wrote {manifest}: {len(file_rows)} files, {len(kept)} .no_exist markers ({added} new).")
PYGEN
    python3 "$_gen" "$MODE" "$MANIFEST"
    exit $?
fi

[ -r "$MANIFEST" ] || { echo "ERROR: manifest not found: $MANIFEST" >&2; exit 2; }

# The recorded markers, checked against the file rows: tab-separated repo, sha, file.
# Checked here, before any AWS call, so a bad manifest fails a --dry-run too.
MARKERS="$(awk -F'\t' '
    /^#/ || NF == 0 { next }
    NF == 3 { pin[$1 FS $2] = 1; have[$1 FS $2 FS $3] = 1; next }
    NF == 4 && $1 == "no_exist" { n++; r[n] = $2; s[n] = $3; f[n] = $4; next }
    { printf "manifest line %d: neither a file row nor a no_exist row\n", NR > "/dev/stderr"; bad = 1 }
    END {
        for (i = 1; i <= n; i++) {
            k = r[i] FS s[i]; p = "/" f[i] "/"
            if (!(k in pin)) why = "revision is not pinned by any file row"
            else if ((k FS f[i]) in have) why = "would hide a file the manifest downloads"
            else if (f[i] == "" || p ~ /\/\.\.?\// || p ~ /\/\//) why = "bad file path"
            else { print r[i] FS s[i] FS f[i]; continue }
            printf "manifest marker %s@%s/%s: %s\n", r[i], substr(s[i], 1, 12), f[i], why > "/dev/stderr"
            bad = 1
        }
        exit bad
    }' "$MANIFEST")" || { echo "ERROR: fix the manifest rows above (or re-record them)." >&2; exit 2; }
MARKER_N="$(printf '%s' "$MARKERS" | grep -c . || true)"

# make_markers <hub-dir>: create every recorded marker as an empty file under <hub-dir>.
make_markers() {
    local hub="$1" repo sha f
    while IFS=$'\t' read -r repo sha f; do
        [ -n "$repo" ] || continue
        mkdir -p "$(dirname "$hub/models--${repo//\//--}/.no_exist/$sha/$f")" \
            && : > "$hub/models--${repo//\//--}/.no_exist/$sha/$f" || return 1
    done <<< "$MARKERS"
}

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
# --markers-only: upload just the recorded markers into an already-seeded tree.
# --------------------------------------------------------------------------
# No token and no download: a marker is an empty file whose NAME is the whole content.
if [ "$MARKERS_ONLY" -eq 1 ]; then
    if [ "$MARKER_N" -eq 0 ]; then
        echo "ERROR: the manifest records no .no_exist markers yet. Record them first" >&2
        echo "       (--record-markers; docs/en/ADMIN_GUIDE.md §6.3)." >&2
        exit 2
    fi
    echo "=== Upload $MARKER_N recorded .no_exist marker(s) -> $DEST ==="
    if [ "$DRY_RUN" -eq 1 ]; then
        printf '%s\n' "$MARKERS" | awk -F'\t' '{printf "  %s@%s/%s\n", $1, substr($2, 1, 12), $3}'
        echo "Dry run: nothing uploaded."
        exit 0
    fi
    _mk="$(mktemp -d "${TMPDIR:-/tmp}/av30-hf-markers.XXXXXX")"
    trap 'rm -rf "$_mk"' EXIT
    make_markers "$_mk/hub" || { echo "ERROR: could not create the markers under $_mk" >&2; exit 1; }
    if ! aws s3 sync "$_mk/hub" "$DEST" --region "$REGION" --only-show-errors; then
        echo "ERROR: upload failed. Re-run." >&2
        exit 1
    fi
    if [ -x "$SCRIPT_DIR/check_seeding.sh" ]; then
        echo ""
        "$SCRIPT_DIR/check_seeding.sh" --region "$REGION"
        exit $?
    fi
    exit 0
fi

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
echo "Manifest : $MANIFEST ($FILES files across $PAIRS repo+revision pairs, $MARKER_N .no_exist markers)"
echo "Scratch  : $SCRATCH  (needs ~65 GiB free)"
echo "Dest     : $DEST"
echo "Region   : $REGION"
[ "$DRY_RUN" -eq 1 ] && echo "MODE     : DRY RUN — nothing is downloaded or uploaded"
echo ""
if [ "$MARKER_N" -eq 0 ]; then
    echo "WARNING: the manifest records no .no_exist markers. check_seeding.sh counts them,"
    echo "         so it will report Alpamayo-1.5-10B and Cosmos-Reason2-8B a few objects"
    echo "         short and fail. Record them, then run --markers-only:"
    echo "         docs/en/ADMIN_GUIDE.md §6.3."
    echo ""
fi

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
    done < <(awk -F'\t' -v r="$repo" -v s="$sha" '!/^#/ && NF==3 && $1==r && $2==s {print $3}' "$MANIFEST")
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

# `hf download --revision <sha>` writes no refs/main, but loaders that pass no revision
# (Alpamayo1_5.from_pretrained, the Reason2 backbone it pulls) resolve 'main' through that
# file — offline, a missing ref is a cache MISS on a byte-perfect snapshot. Point main at
# the pin for every repo pinned at exactly ONE revision; a multi-revision repo
# (Cosmos-Predict2.5-2B) is only ever looked up by sha, so it gets no main.
while IFS=$'\t' read -r repo sha; do
    d="$SCRATCH/hub/models--${repo//\//--}/refs"
    mkdir -p "$d" && printf '%s' "$sha" > "$d/main"
done < <(awk -F'\t' '!/^#/ && NF==3 {print $1"\t"$2}' "$MANIFEST" | sort -u \
         | awk -F'\t' '{n[$1]++; s[$1]=$2} END {for (r in n) if (n[r]==1) print r"\t"s[r]}')

# The recorded .no_exist markers (see the header): empty files, so creating them is the
# whole job. A download never produces them.
if ! make_markers "$SCRATCH/hub"; then
    echo "ERROR: could not create the .no_exist markers under $SCRATCH/hub." >&2
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
