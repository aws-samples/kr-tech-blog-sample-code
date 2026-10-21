#!/bin/bash
# setup_cosmos_env.sh — Install the NVIDIA Cosmos stacks (Transfer 2.5 for M5,
# Predict 2.5 for M6) on a SageMaker Distribution (SMD) GPU JupyterLab app, so
# the notebooks can run REAL inference.
#
# WHY THIS SCRIPT EXISTS
# ----------------------
# The Cosmos notebooks cannot just `pip install cosmos-*` — the real workflow is
# to clone each official repo (github.com/nvidia-cosmos/cosmos-transfer2.5 and
# cosmos-predict2.5), `uv sync` its pinned deps (torch 2.7 + cu128, Python 3.10,
# transformer-engine, megatron), then invoke `examples/inference.py`. Both repos
# share the SAME install shape (cosmos-oss[cu128_torch27]); only the top-level
# package differs (cosmos_transfer2 vs cosmos_predict2), so they need SEPARATE
# uv venvs. On the SMD GPU image the install works, but four environment gaps
# must be patched for the (all pip-wheel) CUDA stack to load:
#
#   1. opencv-python (GUI build) needs libGL/libgthread the SMD image lacks
#      -> keep only opencv-python-headless.
#   2. transformer-engine's _load_nvrtc() crashes on `ldconfig -p | grep nvrtc`
#      (pip CUDA libs aren't in the linker cache) -> we set CUDA_HOME to the pip
#      nvidia/ tree so TE's own recursive glob finds libnvrtc BEFORE ldconfig.
#   3. TE then dlopen()s versioned SONAMEs (libcublas.so.12 ...) -> put every
#      pip nvidia */lib on LD_LIBRARY_PATH.
#   4. TE also dlopen()s the UNVERSIONED name (libcudart.so) which pip wheels
#      don't ship -> create libX.so -> libX.so.NN symlinks.
#
# HuggingFace: the Cosmos checkpoints are gated. You must (a) export HF_TOKEN
# for an account that has accepted the licenses on the NVIDIA Cosmos repos, and
# (b) disable hf-xet (its chunked backend errors with "Unable to parse string
# as hex hash value") via HF_HUB_DISABLE_XET=1.
#
# This whole install is EPHEMERAL: an app restart resets the image layer and
# /tmp. It lives on the 28 TB local NVMe (/mnt/sagemaker-nvme) which also
# survives only for the life of the running app. Re-run this script after any
# app restart. It is idempotent — re-running skips work already done.
#
# USAGE (from a GPU JupyterLab terminal, or `!bash scripts/setup_cosmos_env.sh`):
#     export HF_TOKEN=hf_xxx            # account must have accepted Cosmos licenses
#     bash scripts/setup_cosmos_env.sh          # both Cosmos repos (default)
#     bash scripts/setup_cosmos_env.sh transfer # only Transfer 2.5 (M5)
#     bash scripts/setup_cosmos_env.sh predict  # only Predict 2.5 (M6)
#     bash scripts/setup_cosmos_env.sh alpamayo # only Alpamayo 1.5 (M9)
#     # then, to get an env into your current shell:
#     source /mnt/sagemaker-nvme/cosmos-work/cosmos_env.sh          # Transfer (M5)
#     source /mnt/sagemaker-nvme/cosmos-work/cosmos_predict_env.sh  # Predict (M6)
#     source /mnt/sagemaker-nvme/cosmos-work/alpamayo_env.sh        # Alpamayo (M9)
#
# M5 sources cosmos_env.sh; M6 sources cosmos_predict_env.sh; M9 sources
# alpamayo_env.sh. They point at SEPARATE venvs, so keep them distinct.
#
# ALPAMAYO (M9) is a DIFFERENT stack from Cosmos: package alpamayo1_5, Python
# 3.12 (not 3.10), torch 2.8, NO transformer-engine, and flash-attn EXCLUDED
# (its source build fails on the SMD image; the model is loaded with
# attn_implementation="sdpa"). So it skips the conda-3.10 / TE .so-symlink /
# ldconfig steps and gets its own prepare_alpamayo() below. `both` means the
# two Cosmos repos only — alpamayo must be requested explicitly.
#
# Requirements: a GPU instance (p4d/p5/g5/g6...), sudo (for ldconfig, present on
# SMD), ~80 GB free on the NVMe per repo venv + model cache, and network egress
# to GitHub + HuggingFace.
set -uo pipefail

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
NVME="${COSMOS_NVME:-/mnt/sagemaker-nvme}"
WORK="$NVME/cosmos-work"
# One 0600 sidecar shared by all three env files, so a caller-supplied HF_TOKEN is
# never written into a world-readable sourced script. See write_hf_token_sidecar.
HF_TOKEN_FILE="$WORK/.hf_token"
CONDA_ENV="${COSMOS_CONDA_ENV:-cosmos-t25}"
PY_VERSION="3.10"

TRANSFER_REPO_DIR="$WORK/cosmos-transfer2.5"
TRANSFER_REPO_URL="https://github.com/nvidia-cosmos/cosmos-transfer2.5.git"
TRANSFER_ENV_FILE="$WORK/cosmos_env.sh"          # sourced by M5
PREDICT_REPO_DIR="$WORK/cosmos-predict2.5"
PREDICT_REPO_URL="https://github.com/nvidia-cosmos/cosmos-predict2.5.git"
PREDICT_ENV_FILE="$WORK/cosmos_predict_env.sh"   # sourced by M6

# Alpamayo 1.5 (M9) — separate stack: Python 3.12 venv, no TE, no flash-attn.
ALPAMAYO_REPO_DIR="$WORK/alpamayo1.5"
ALPAMAYO_REPO_URL="https://github.com/NVlabs/alpamayo1.5.git"
ALPAMAYO_ENV_FILE="$WORK/alpamayo_env.sh"        # sourced by M9
ALPAMAYO_VENV="$ALPAMAYO_REPO_DIR/a1_5"          # Python 3.12 uv venv (verified name)
ALPAMAYO_PY_VERSION="3.12"

# Which stacks to prepare: transfer | predict | both (default) | alpamayo
WHICH="${1:-both}"

echo "=== AV 3.0 Blueprint Lab — Cosmos environment setup ($WHICH) ==="
echo "NVMe work dir : $WORK"
echo "conda env     : $CONDA_ENV (python $PY_VERSION)"
echo ""

# --------------------------------------------------------------------------
# Pre-flight
# --------------------------------------------------------------------------
if [ ! -d "$NVME" ]; then
    echo "ERROR: $NVME not found. This script needs the local NVMe scratch disk"
    echo "       that exists on p4d/p5/g5/g6 SageMaker instances. Are you on a"
    echo "       GPU instance?"
    exit 1
fi

if ! command -v conda &>/dev/null; then
    echo "ERROR: conda not found on PATH (expected on the SMD image)."
    exit 1
fi

# NOTE: there is deliberately no "HF_TOKEN not set — that's probably fine" note
# here any more. It used to print at this point, BEFORE the S3 cache probe, so it
# asserted something nothing had checked yet and read as reassurance in exactly the
# case that cannot work (no cache AND no token). The single verdict is printed after
# the probe instead, where it is a fact rather than a hope.

mkdir -p "$WORK"

# --------------------------------------------------------------------------
# conda env (python 3.10 — Cosmos pins 3.10; SMD base is 3.12) + uv + git-lfs
# --------------------------------------------------------------------------
if conda env list | grep -qE "^\s*${CONDA_ENV}\s"; then
    echo "[conda] env '$CONDA_ENV' already exists — skipping create"
else
    echo "[conda] Creating env '$CONDA_ENV' (python $PY_VERSION)..."
    conda create -n "$CONDA_ENV" "python=$PY_VERSION" -y 2>&1 | tail -3
fi
# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$CONDA_ENV"

# git-lfs lets `git lfs pull` fetch a repo's example assets. Not strictly needed
# (we build our own inference specs), and repo clone works without it because we
# disable the LFS filter below — but install it if easy.
if ! command -v git-lfs &>/dev/null; then
    echo "[conda] Installing git-lfs into '$CONDA_ENV'..."
    conda install -y -c conda-forge git-lfs 2>&1 | tail -2
fi
if ! command -v uv &>/dev/null; then
    pip install -q uv 2>&1 | tail -2
fi
export UV_CACHE_DIR="$NVME/uv-cache"   # keep the huge wheel cache off the 5GB home EBS

# --------------------------------------------------------------------------
# Restore the admin's pre-cached HuggingFace checkpoints into HF_HOME.
# --------------------------------------------------------------------------
# M5/M6's inference.py downloads gated Cosmos checkpoints from HF at runtime.
# Rather than make every participant get an HF token + accept licenses, the admin
# pre-caches the HF cache TREE to S3 (s3://<shared>/hf-cache/hub/) once. Here we
# sync it back into $HF_HOME/hub so cosmos loads it offline (HF_HUB_OFFLINE=1,
# set in the env file when this cache is present). Idempotent: re-sync only
# copies changed objects. If the S3 cache is absent, we skip and fall back to
# token-based online download (a caller-provided HF_TOKEN still works).
HF_HOME_DIR="$NVME/hf"
HF_CACHE_S3="${HF_CACHE_S3:-}"
if [ -z "$HF_CACHE_S3" ]; then
    # Derive the shared bucket from the caller's env, else best-effort default.
    _shared="${SHARED_BUCKET:-}"
    if [ -z "$_shared" ]; then
        # Per-region bucket name (infra/av30_constructs/storage.py) — the region is
        # part of the name, so an un-suffixed guess resolves to nothing.
        _acct="$(aws sts get-caller-identity --query Account --output text 2>/dev/null || true)"
        _reg="${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region 2>/dev/null || true)}}"
        [ -n "$_acct" ] && [ -n "$_reg" ] && _shared="av30lab-shared-data-${_acct}-${_reg}"
    fi
    [ -n "$_shared" ] && HF_CACHE_S3="s3://${_shared}/hf-cache/hub/"
fi
# The PARENT prefix, for the remediation message only. The restore reads hub/, but a
# seeding sync must copy hf-cache/ -> hf-cache/ so that hf-cache/alpamayo-demo/ and the
# refs/ files come along. Printing $HF_CACHE_S3 as the destination while the source was
# hf-cache/ produced hf-cache/hub/hub/ — a nested tree that satisfies the object-count
# parity check (all 481 objects arrive) and then fails the shape check, i.e. it costs a
# full ~115 GiB / ~40 min cross-region cycle and lands back at the same STOP screen.
HF_CACHE_PARENT="${HF_CACHE_S3%hub/}"
# Which repos THIS run needs in the restored tree. Keyed off $WHICH rather than one
# hardcoded glob: `alpamayo` is a different stack, and a check for
# models--nvidia--Cosmos-* would be satisfied by Cosmos-Reason2-8B while the actual
# Alpamayo weights were missing. `transfer` needs Predict2.5-2B too — M5's own
# traceback shows Transfer pulling the Wan2.1 VAE out of nvidia/Cosmos-Predict2.5-2B.
# HF_LICENSE_HINT must stay in step with HF_NEED: the STOP screen tells a participant
# which licenses to accept, and naming the Cosmos three to an M9 participant sends them
# to accept the wrong repos and fail again on the next run.
case "$WHICH" in
    alpamayo) HF_NEED="models--nvidia--Alpamayo-1.5-10B models--nvidia--Cosmos-Reason2-8B"
              HF_LICENSE_HINT="huggingface.co/nvidia/Alpamayo-1.5-10B and /Cosmos-Reason2-8B," ;;
    predict)  HF_NEED="models--nvidia--Cosmos-Predict2.5-2B models--nvidia--Cosmos-Guardrail1"
              HF_LICENSE_HINT="huggingface.co/nvidia/Cosmos-Predict2.5-2B and /Cosmos-Guardrail1," ;;
    *)        HF_NEED="models--nvidia--Cosmos-Transfer2.5-2B models--nvidia--Cosmos-Predict2.5-2B models--nvidia--Cosmos-Guardrail1"
              HF_LICENSE_HINT="huggingface.co/nvidia/Cosmos-Transfer2.5-2B, /Cosmos-Predict2.5-2B and /Cosmos-Guardrail1," ;;
esac

# HF_CACHE_OK=1 ONLY when the restore completed and the restored tree holds what this
# run needs. Absent prefix, AccessDenied, failed sync and partial tree all leave it 0
# and all funnel into the single gate below — previously each printed its own warning
# and then continued identically.
HF_CACHE_OK=0
HF_CACHE_WHY=""
if [ -n "$HF_CACHE_S3" ]; then
    # Capture the probe's stderr instead of discarding it with `2>&1`. "prefix does
    # not exist" (the ap-northeast-2 case), "AccessDenied" (an IAM problem) and
    # "Unable to locate credentials" previously all arrived here as the same silent
    # exit 1, so the message printed afterwards was a guess. An absent prefix exits
    # non-zero with NO stderr at all, which is itself the distinguishing signal.
    HF_PROBE_ERR="$(aws s3 ls "$HF_CACHE_S3" 2>&1 >/dev/null)"
    if [ $? -eq 0 ]; then
        echo "[hf-cache] Restoring pre-cached HF checkpoints from $HF_CACHE_S3 ..."
        mkdir -p "$HF_HOME_DIR/hub"
        if aws s3 sync "$HF_CACHE_S3" "$HF_HOME_DIR/hub/" --only-show-errors; then
            # Object-count parity catches an INTERRUPTED restore, which is the single
            # most dangerous state in this script. A PARTIAL tree is strictly worse
            # than an empty one: the env file's `ls models--nvidia--Cosmos-*` glob
            # needs only ONE directory to exist to flip HF_HUB_OFFLINE=1, after which
            # every still-missing checkpoint stops being a download and becomes an
            # opaque "Local entry not found ... offline mode is enabled" 20 minutes
            # later. HF offline mode performs no integrity checking at all, so nothing
            # downstream would ever notice. >= not = : a superset is fine (another
            # stack's repos may already be cached locally), a subset is not.
            # -type f OR -type l: HuggingFace's cache stores each snapshot entry as a
            # SYMLINK into blobs/, so counting regular files only undercounts a perfectly
            # good tree by every snapshot entry and would reject it. (Dangling links would
            # also count, which is fine — the shape check below still demands one real
            # -size +0c file per needed repo, and a symlink to a real blob satisfies it.)
            _s3_out="$(aws s3 ls "$HF_CACHE_S3" --recursive 2>&1)"
            _s3_rc=$?
            _loc_n="$(find "$HF_HOME_DIR/hub" \( -type f -o -type l \) 2>/dev/null | wc -l | tr -d ' ')"
            _s3_n="$(printf '%s\n' "$_s3_out" | awk '$4 !~ /\/$/ {n++} END {print n+0}')"
            if [ "$_s3_rc" -ne 0 ]; then
                # This probe only COUNTS. Treating "could not count" as "incomplete" is a
                # fail-closed on an informational call — and it is reachable at workshop
                # scale, since a 503 SlowDown on LIST is exactly what N participants
                # syncing the same prefix concurrently earn. Skip parity and let the shape
                # check (which is what actually protects against a partial tree) decide.
                echo "[hf-cache] Could not verify object count ($(printf '%s' "$_s3_out" | head -1))"
                echo "           — relying on the tree-shape check instead."
                _s3_n=0
                _loc_n=0
            fi
            if [ "$_s3_rc" -ne 0 ] || { [ "${_s3_n:-0}" -gt 0 ] && [ "${_loc_n:-0}" -ge "${_s3_n:-0}" ]; }; then
                # Shape, not mere presence: each needed repo must have at least one
                # NON-EMPTY file under it. (This is the cheap on-instance check. The
                # rigorous source-vs-destination checksum assertion belongs to
                # scripts/check_seeding.sh, which runs once per region at seed time —
                # do not mistake one for the other.)
                # Assign from a command substitution and test the STRING. Do not write
                # this as `if ! find ... | head -1 | grep -q .`: `set -o pipefail` is
                # active (:61), and grep -q / head -1 exit as soon as they have their
                # answer, so find takes SIGPIPE and the pipeline's status becomes 141
                # precisely WHEN A FILE WAS FOUND — inverting the check and reporting
                # every present repo as missing.
                # find -L (FOLLOW symlinks) is required, not cosmetic. HuggingFace's own
                # cache stores every snapshot entry as a symlink into blobs/, so whenever
                # HF_HOME was populated by an actual download rather than by the S3
                # restore — which is exactly what the admin's seeding ritual produces, and
                # what a token-bearing run produces — a plain `-type f` matches nothing and
                # a perfectly good tree is rejected. -L gives the semantics we actually
                # want on all four cases: a real non-empty file matches; a symlink to a
                # real non-empty blob matches; a DANGLING symlink does not (it is -type l
                # even under -L); and a 0-byte file or a link to one still fails -size +0c,
                # so HF's "a 0-byte file counts as downloaded" hazard stays caught.
                _missing=""
                for _repo in $HF_NEED; do
                    _found="$(find -L "$HF_HOME_DIR/hub/$_repo" -type f -size +0c 2>/dev/null | head -1)"
                    if [ -z "$_found" ]; then
                        _missing="$_missing $_repo"
                    fi
                done
                if [ -z "$_missing" ]; then
                    HF_CACHE_OK=1
                else
                    HF_CACHE_WHY="restored tree is missing:$_missing"
                fi
            else
                HF_CACHE_WHY="restore incomplete (${_loc_n:-0} local files vs ${_s3_n:-0} S3 objects)"
            fi
        else
            HF_CACHE_WHY="aws s3 sync from $HF_CACHE_S3 failed"
        fi
    elif [ -n "$HF_PROBE_ERR" ]; then
        HF_CACHE_WHY="cannot read $HF_CACHE_S3 — $(echo "$HF_PROBE_ERR" | head -1)"
    else
        HF_CACHE_WHY="no HF cache at $HF_CACHE_S3 (prefix does not exist in this region)"
    fi
else
    HF_CACHE_WHY="could not resolve the shared bucket, so \$HF_CACHE_S3 is unset"
fi

# --------------------------------------------------------------------------
# The gate: refuse to continue when we already know the run cannot succeed.
# --------------------------------------------------------------------------
# Both halves of the fatal condition are known HERE: no usable offline cache AND no
# token. The script used to print one warning and then spend 15-20 minutes on `uv
# sync` before exiting 0 — so the notebook's only check (`if proc.returncode != 0`)
# passed, the setup cell printed "environment ready", and the participant paid a GPU
# hour to reach a 4-second failure whose cause was never shown. Exit 2 (not 1) so
# "precondition not met" stays distinguishable from "a stack failed to verify".
# A token persisted by an earlier run of THIS script lives in the 0600 sidecar, and both
# generated env files source it — so it is genuinely available to the inference shell.
# Read it here too, or the gate refuses a run that would have worked (e.g. a second
# per-stack invocation from a fresh terminal, which this script's own usage header
# documents). One source of truth for both the gate and the verdict banner.
# shellcheck disable=SC1090
[ -r "$HF_TOKEN_FILE" ] && . "$HF_TOKEN_FILE"
if [ "$HF_CACHE_OK" -eq 0 ] && [ -z "${HF_TOKEN:-}" ]; then
    echo ""
    echo "=== STOP — not starting, because this run cannot succeed ==="
    echo ""
    echo "  Reason : $HF_CACHE_WHY"
    echo "  And    : HF_TOKEN is not set."
    echo ""
    echo "  The Cosmos checkpoints are GATED on HuggingFace. With neither the admin's"
    echo "  pre-cached offline tree nor a token, inference dies seconds after launch"
    echo "  with 'Access denied. This repository requires approval.' — but inside a"
    echo "  torchrun child, where the message is easy to miss entirely."
    echo ""
    echo "  Fix it one of two ways:"
    echo ""
    echo "  A) ADMIN, once per region — seed the offline cache, then re-run this cell."
    echo "     Participants then need no HuggingFace account at all:"
    echo "       aws s3 sync s3://av30lab-shared-data-<acct>-<seeded-region>/hf-cache/ \\"
    echo "                   ${HF_CACHE_PARENT:-s3://av30lab-shared-data-<acct>-<this-region>/hf-cache/} \\"
    echo "                   --source-region <seeded-region> --region <this-region>"
    echo "     Sync hf-cache/ — NOT hf-cache/hub/ — or the tree nests one level too deep."
    echo "     Verify with: ./scripts/check_seeding.sh --region <this-region>"
    echo ""
    echo "  B) PER PARTICIPANT — accept the licenses (auto-approved, instant) on"
    echo "     $HF_LICENSE_HINT"
    echo "     then set HF_TOKEN in the notebook's first cell."
    echo ""
    echo "  Needed for this run ($WHICH): $HF_NEED"
    exit 2
fi

# The env files' offline switch is decided HERE, from the verified verdict, and
# interpolated as literal text at write time. It used to be a runtime `ls
# models--nvidia--Cosmos-*` test inside the generated file, which ANY ONE Cosmos
# directory satisfies -- so a partial tree plus a token produced the worst combination
# in the whole system: the gate correctly announced ONLINE, and the env file then forced
# HF_HUB_OFFLINE=1 anyway, converting every missing checkpoint from a download into an
# opaque "Local entry not found ... offline mode is enabled" 20 minutes later. Deciding
# once also means the literal text now appears in the file ONLY when offline mode is
# really on, so reading the file is no longer self-refuting (the glob remains the
# preferred test because it does not depend on which env file you look at).
if [ "$HF_CACHE_OK" -eq 1 ]; then
    HF_OFFLINE_EXPORTS="export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1"
else
    HF_OFFLINE_EXPORTS="# Offline mode deliberately NOT enabled: no verified offline cache for this run,
# so HuggingFace must be allowed to download using HF_TOKEN."
fi

# One verdict line, printed only now that it is a measured fact.
if [ "$HF_CACHE_OK" -eq 1 ]; then
    echo "[hf-cache] Offline cache verified for '$WHICH' → running OFFLINE, no HF token needed."
else
    echo "[hf-cache] No usable offline cache ($HF_CACHE_WHY)."
    echo "[hf-cache] Proceeding ONLINE with the supplied HF_TOKEN. This needs the gated"
    echo "           licenses accepted on that HuggingFace account, and downloads ~20 GB."
fi

# --------------------------------------------------------------------------
# write_hf_token_sidecar — persist HF_TOKEN out of band, mode 0600.
# --------------------------------------------------------------------------
# The env files are generated with `cat >` under the default umask (0022 on the SMD
# image), so appending `export HF_TOKEN=...` to one published the token to every
# local user. Persistence itself is kept rather than dropped: the env file is
# documented as a standalone entry point (see the header), and it is the only
# durable carrier of the token across a kernel restart or a fresh terminal — a
# Python-only token would silently resurrect the gated-repo failure there.
write_hf_token_sidecar() {
    [ -z "${HF_TOKEN:-}" ] && return 0
    # umask inside a subshell so the file is never even briefly group/world readable;
    # the explicit chmod then also covers a pre-existing file from an earlier run.
    ( umask 077; printf 'export HF_TOKEN="%s"\n' "$HF_TOKEN" > "$HF_TOKEN_FILE" )
    chmod 600 "$HF_TOKEN_FILE" 2>/dev/null || true
    return 0
}

# --------------------------------------------------------------------------
# prepare_repo — clone + uv sync + opencv-headless + .so symlinks + env file.
# Args: 1=repo_url 2=repo_dir 3=import_name 4=env_file 5=label
# --------------------------------------------------------------------------
prepare_repo() {
    local repo_url="$1" repo_dir="$2" import_name="$3" env_file="$4" label="$5"
    echo ""
    echo "========================================================================"
    echo "=== Preparing $label"
    echo "========================================================================"

    # Clone. Disable the git-lfs filter so checkout succeeds even when the
    # `git-lfs` binary isn't on PATH (common in a bare SMD shell) — code files
    # come down fine; only LFS-tracked example assets stay as pointers, which we
    # don't need (we generate our own inference specs).
    if [ -d "$repo_dir/.git" ]; then
        echo "[1/6] Repo already cloned at $repo_dir — skipping"
    else
        echo "[1/6] Cloning $repo_url ..."
        git clone --depth 1 \
            -c filter.lfs.smudge= -c filter.lfs.process= -c filter.lfs.required=false \
            "$repo_url" "$repo_dir" 2>&1 | tail -3
    fi
    cd "$repo_dir"

    # uv sync the pinned deps into this repo's OWN .venv.
    if [ -d "$repo_dir/.venv" ] && "$repo_dir/.venv/bin/python" -c "import $import_name" 2>/dev/null; then
        echo "[2/6] .venv already has $import_name — skipping uv sync"
    else
        echo "[2/6] uv sync --extra=cu128 --python $PY_VERSION (can take 10-20 min)..."
        uv sync --extra=cu128 --python "$PY_VERSION" 2>&1 | tail -15
    fi
    local venv="$repo_dir/.venv"
    local site="$venv/lib/python${PY_VERSION}/site-packages"

    # opencv: keep ONLY headless (GUI build needs libGL/libgthread SMD lacks).
    # Use `uv pip` (this repo's uv venv has NO pip module). --no-deps so it can't
    # drag numpy up. Force VIRTUAL_ENV so uv targets THIS venv. uv sync often
    # installs BOTH opencv-python and -headless; removing the GUI build and
    # reinstalling headless leaves a cv2 that needs no system GL libs.
    echo "[3/6] Ensuring opencv-python-headless..."
    if VIRTUAL_ENV="$venv" uv pip list 2>/dev/null | grep -q "^opencv-python "; then
        VIRTUAL_ENV="$venv" uv pip uninstall opencv-python 2>&1 | tail -2
    fi
    if ! "$venv/bin/python" -c "import cv2" 2>/dev/null; then
        VIRTUAL_ENV="$venv" uv pip install --force-reinstall --no-deps \
            opencv-python-headless 2>&1 | tail -2
    fi

    # Unversioned .so symlinks (TE dlopen()s libcudart.so, not libcudart.so.12).
    echo "[4/6] Creating unversioned .so symlinks for pip CUDA libs..."
    local nvroot
    nvroot="$(readlink -f "$site/nvidia")"
    if [ -d "$nvroot" ]; then
        for d in "$nvroot"/*/lib; do
            [ -d "$d" ] || continue
            for so in "$d"/*.so.*; do
                [ -e "$so" ] || continue
                local stem; stem="$(basename "$so")"; stem="${stem%%.so.*}"
                local link="$d/${stem}.so"
                [ -e "$link" ] || ln -s "$so" "$link"
            done
        done
        echo "      done ($(find "$nvroot" -type l -name '*.so' | wc -l) symlinks present)"
    else
        echo "      WARNING: $site/nvidia not found — pip CUDA wheels missing?"
    fi

    # ldconfig: register pip CUDA dirs (belt-and-suspenders; LD_LIBRARY_PATH in
    # the env file is the real guarantee).
    echo "[5/6] Registering pip CUDA lib dirs with ldconfig (needs sudo)..."
    if command -v sudo &>/dev/null && [ -d "$nvroot" ]; then
        if ! grep -q 'ld.so.conf.d' /etc/ld.so.conf 2>/dev/null; then
            echo 'include /etc/ld.so.conf.d/*.conf' | sudo tee -a /etc/ld.so.conf >/dev/null
        fi
        ls -d "$nvroot"/*/lib | sudo tee "/etc/ld.so.conf.d/pip-nvidia-${label}.conf" >/dev/null
        sudo ldconfig 2>/dev/null || true
        echo "      ldconfig updated"
    else
        echo "      sudo unavailable — relying on LD_LIBRARY_PATH"
    fi

    # Write the env file the notebook sources. Activates conda (for git-lfs etc.)
    # then this repo's .venv LAST so its python (with the cosmos package + TE)
    # wins on PATH.
    echo "[6/6] Writing $env_file ..."
    cat > "$env_file" <<EOF
# $(basename "$env_file") — source this to run $label examples/inference.py.
# Generated by setup_cosmos_env.sh. Safe to source repeatedly.
source "\$(conda info --base)/etc/profile.d/conda.sh"
conda activate $CONDA_ENV
source "$venv/bin/activate"

export COSMOS_REPO_DIR="$repo_dir"
# CUDA_HOME -> pip nvidia tree so transformer-engine's recursive glob finds
# libnvrtc before it hits the (broken-on-SMD) ldconfig code path.
export CUDA_HOME="$nvroot"
export LD_LIBRARY_PATH="\$(ls -d "$nvroot"/*/lib 2>/dev/null | paste -sd: -):\${LD_LIBRARY_PATH:-}"
# hf-xet chunked backend is buggy here -> classic HTTPS download.
export HF_HUB_DISABLE_XET=1
export HF_HOME="$NVME/hf"
export UV_CACHE_DIR="$NVME/uv-cache"
# HF_TOKEN, when the caller supplied one, lives in a 0600 sidecar rather than inline
# here: this file is written by \`cat >\` under the default umask, so an inline token
# is world-readable on the instance. Sourced EARLY on purpose — as the file's LAST
# statement, \`[ -r x ] && . x\` would make the whole env file return 1 whenever no
# token exists, and M5 does \`source "\$env_file" && cd ...\`, so every token-less
# (i.e. correctly cached) run would break.
[ -r "$HF_TOKEN_FILE" ] && . "$HF_TOKEN_FILE"
# Offline HF: if the admin's pre-cached checkpoints were restored into HF_HOME
# (see restore step in setup_cosmos_env.sh), force offline so cosmos loads them
# WITHOUT a token or network. If the cache is absent we leave online mode on so
# a caller-provided HF_TOKEN can still download as a fallback.
#
# The line(s) below are interpolated at WRITE time from the verified cache verdict, not
# evaluated at source time. The previous version tested
# \`ls \$HF_HOME/hub/models--nvidia--Cosmos-*\` here, which any ONE Cosmos directory
# satisfies -- so a PARTIAL cache forced offline mode on and turned every missing
# checkpoint into an opaque "Local entry not found" instead of a download.
$HF_OFFLINE_EXPORTS
EOF
    write_hf_token_sidecar

    # Verify import through the env file.
    echo "--- Verifying $import_name import ($label) ---"
    # shellcheck disable=SC1090
    ( source "$env_file" && cd "$repo_dir" && \
      python -c "import $import_name; print('$import_name import OK')" 2>&1 | tail -5 )
}

# --------------------------------------------------------------------------
# prepare_alpamayo — clone + Python 3.12 uv venv (no flash-attn) + env file.
# Alpamayo 1.5 (M9) has NO transformer-engine, so it skips the TE .so-symlink,
# CUDA_HOME and ldconfig gymnastics entirely — torch 2.8's bundled CUDA loads
# fine. flash-attn is EXCLUDED (source build needs nvcc the SMD image lacks);
# the model is loaded with attn_implementation="sdpa". The hf-cache restore in
# the preamble above already populated $HF_HOME/hub (Alpamayo-1.5-10B + its
# hidden Cosmos-Reason2-8B VLM backbone), so the env file flips on
# HF_HUB_OFFLINE when that cache is present.
# --------------------------------------------------------------------------
prepare_alpamayo() {
    echo ""
    echo "========================================================================"
    echo "=== Preparing Alpamayo 1.5 (VLA, Python $ALPAMAYO_PY_VERSION, no flash-attn)"
    echo "========================================================================"

    # Clone (LFS filter disabled — same rationale as the Cosmos repos).
    if [ -d "$ALPAMAYO_REPO_DIR/.git" ]; then
        echo "[1/4] Repo already cloned at $ALPAMAYO_REPO_DIR — skipping"
    else
        echo "[1/4] Cloning $ALPAMAYO_REPO_URL ..."
        git clone --depth 1 \
            -c filter.lfs.smudge= -c filter.lfs.process= -c filter.lfs.required=false \
            "$ALPAMAYO_REPO_URL" "$ALPAMAYO_REPO_DIR" 2>&1 | tail -3
    fi
    cd "$ALPAMAYO_REPO_DIR"

    # Python 3.12 uv venv named a1_5 (verified). uv sync WITHOUT flash-attn:
    # its source build fails on the SMD image (no nvcc). --active targets the
    # VIRTUAL_ENV we set instead of creating a .venv.
    if [ -d "$ALPAMAYO_VENV" ] && "$ALPAMAYO_VENV/bin/python" -c "import alpamayo1_5" 2>/dev/null; then
        echo "[2/4] a1_5 venv already has alpamayo1_5 — skipping uv sync"
    else
        echo "[2/4] uv venv a1_5 --python $ALPAMAYO_PY_VERSION + uv sync --no-install-package flash-attn (10-20 min)..."
        uv venv "$ALPAMAYO_VENV" --python "$ALPAMAYO_PY_VERSION" 2>&1 | tail -3
        VIRTUAL_ENV="$ALPAMAYO_VENV" uv sync --active --no-install-package flash-attn 2>&1 | tail -15
    fi

    # Write the env file M9 sources. No conda, no TE, no CUDA_HOME/LD_LIBRARY_PATH
    # — and actively clear any leaked from a previously-sourced cosmos env (a
    # stale CUDA_HOME points the loader at the 3.10 pip tree and breaks torch 2.8).
    echo "[3/4] Writing $ALPAMAYO_ENV_FILE ..."
    cat > "$ALPAMAYO_ENV_FILE" <<EOF
# $(basename "$ALPAMAYO_ENV_FILE") — source this to run M9 (alpamayo1_5).
# Generated by setup_cosmos_env.sh. Safe to source repeatedly.
source "$ALPAMAYO_VENV/bin/activate"
export ALPAMAYO_REPO_DIR="$ALPAMAYO_REPO_DIR"
# Alpamayo uses torch's bundled CUDA (no transformer-engine). Clear any CUDA_HOME
# / LD_LIBRARY_PATH leaked from a sourced cosmos env in the same shell.
unset CUDA_HOME LD_LIBRARY_PATH
export HF_HUB_DISABLE_XET=1
export HF_HOME="$NVME/hf"
export UV_CACHE_DIR="$NVME/uv-cache"
# See the Cosmos env file for why the token is a 0600 sidecar sourced early, not
# an inline export appended at the end.
[ -r "$HF_TOKEN_FILE" ] && . "$HF_TOKEN_FILE"
# Interpolated at WRITE time from the verified verdict (see the Cosmos env file). The
# old runtime glob on models--nvidia--Alpamayo-* ignored the Cosmos-Reason2-8B backbone
# entirely, so a tree with Alpamayo but no backbone forced offline mode on and failed
# opaquely at model load.
$HF_OFFLINE_EXPORTS
EOF
    write_hf_token_sidecar

    # Verify import through the env file.
    echo "[4/4] Verifying alpamayo1_5 import ..."
    # shellcheck disable=SC1090
    ( source "$ALPAMAYO_ENV_FILE" && cd "$ALPAMAYO_REPO_DIR" && \
      python -c "import alpamayo1_5; print('alpamayo1_5 import OK')" 2>&1 | tail -5 )
}

# --------------------------------------------------------------------------
# Run for the requested stack(s)
# --------------------------------------------------------------------------
FAILED=0
if [ "$WHICH" = "transfer" ] || [ "$WHICH" = "both" ]; then
    prepare_repo "$TRANSFER_REPO_URL" "$TRANSFER_REPO_DIR" \
        "cosmos_transfer2" "$TRANSFER_ENV_FILE" "transfer2.5" \
        || FAILED=1
fi
if [ "$WHICH" = "predict" ] || [ "$WHICH" = "both" ]; then
    prepare_repo "$PREDICT_REPO_URL" "$PREDICT_REPO_DIR" \
        "cosmos_predict2" "$PREDICT_ENV_FILE" "predict2.5" \
        || FAILED=1
fi
# Alpamayo is requested explicitly (NOT part of `both`) — different stack.
if [ "$WHICH" = "alpamayo" ]; then
    prepare_alpamayo || FAILED=1
fi

echo ""
if [ "$FAILED" -eq 0 ]; then
    # Qualify the banner. An unconditional "=== SUCCESS ===" is what let the M5 setup
    # cell print "environment ready" for a run that could not download a single
    # checkpoint: the repos and venvs really were built, so the banner was true about
    # the only thing it measured, and false about the thing that mattered.
    if [ "$HF_CACHE_OK" -eq 1 ]; then
        echo "=== SUCCESS (offline HF cache verified — no token needed) ==="
    else
        echo "=== SUCCESS (repos built; HF downloads will go ONLINE via HF_TOKEN) ==="
    fi
    echo "Env files written under $WORK:"
    [ -f "$TRANSFER_ENV_FILE" ] && echo "  M5 (Transfer): source $TRANSFER_ENV_FILE  ->  examples/inference.py ... control:edge"
    [ -f "$PREDICT_ENV_FILE" ]  && echo "  M6 (Predict):  source $PREDICT_ENV_FILE  ->  examples/inference.py ... --inference-type=video2world"
    [ -f "$ALPAMAYO_ENV_FILE" ] && echo "  M9 (Alpamayo): source $ALPAMAYO_ENV_FILE  ->  python scripts/alpamayo_infer.py --clips ... --out ..."
    # Exit 0 EXPLICITLY. Without this, the script's exit code is that of the last
    # command above — the `[ -f "$ALPAMAYO_ENV_FILE" ]` test — which is FALSE (1)
    # whenever Alpamayo wasn't part of this run (e.g. WHICH=both installs only
    # transfer+predict). That made a fully-successful setup return exit 1, which
    # the M5/M6 notebooks correctly flagged as a failure.
    exit 0
else
    echo "=== One or more stacks failed to verify — see errors above ==="
    exit 1
fi
