#!/bin/bash
# setup_nemo_curator_env.sh — Install NVIDIA NeMo Curator (VIDEO pipeline) on a
# SageMaker Distribution (SMD) GPU JupyterLab app, so M3 can run REAL data
# curation (split / transcode / motion filter) instead of a pure-Python stub.
#
# WHY THIS SCRIPT EXISTS
# ----------------------
# The AV 3.0 blog's curation stage is NVIDIA "Cosmos Curator" on HyperPod+SLURM
# (Docker/Pixi, ~30-min image build, 200 GB — not runnable in a notebook). Its
# pip-installable sibling, **NeMo Curator** (github.com/NVIDIA-NeMo/Curator),
# runs the SAME pipeline shape (VideoReader -> FixedStride split -> transcode ->
# motion filter -> manifest) and IS installable at workshop scale — IF you:
#   1. PIN to the v1.2.0 tag. `main` moved to a v26.x line with different extras
#      (video_media) and pins (av 17, torch 2.10). A bare `pip install
#      nemo-curator` resolves to a layout whose module paths differ, which is
#      exactly why an earlier attempt in this repo broke with
#      `ModuleNotFoundError: nemo_curator.filters` (that top-level module does
#      not exist in 1.2.0 — filters live under nemo_curator/stages/.../).
#   2. Install into a DEDICATED uv venv on the NVMe, NOT the shared SMD kernel.
#      video_cuda12 caps torch<=2.9.1 and drags in vllm / flash-attn / pycuda /
#      PyNvVideoCodec + a transformers==4.55.2 override — these fight the SMD
#      image's own torch/transformers/CUDA userspace. A separate venv is the
#      natural fit: the M3 notebook shells out to it (like M5 shells out to the
#      cosmos venv), so the kernel itself stays clean.
#   3. Use the libopenh264 (software H.264) encoder — NOT libvpx-vp9. NeMo
#      Curator's motion filter reads motion-vector side data, which ffmpeg
#      exports for H.264/MPEG but NOT for VP9 (a VP9 clip yields motion_score
#      -1 and is dropped as "no_motion_frames"). H.264 also needs a software
#      h264 decoder present, which conda-forge ffmpeg ships. libopenh264 is
#      CPU-only, so no NVENC/GPU encoder is required.
#
# For the split -> transcode -> motion-filter subset, **NO model weights are
# required** (motion filter is model-free — it reads decoded motion vectors).
# So there is nothing to pre-cache to S3, and no HF token is needed. (Only the
# optional Cosmos-Embed1 embedding/dedup stage would need a model — see the
# --with-embeddings note at the bottom; off by default.)
#
# This install is EPHEMERAL: the NVMe and the image layer reset when the
# JupyterLab app restarts. Re-run this script after any restart — it is
# idempotent and skips work already done.
#
# USAGE (from a GPU JupyterLab terminal, or `!bash scripts/setup_nemo_curator_env.sh`):
#     bash scripts/setup_nemo_curator_env.sh
#     # then, to get the env into your current shell:
#     source /mnt/sagemaker-nvme/nemo-curator-work/nemo_curator_env.sh
#     # verify:
#     nemo-curator-python -c "from nemo_curator.pipeline import Pipeline; \
#         from nemo_curator.stages.video.clipping.clip_extraction_stages import \
#         FixedStrideExtractorStage, ClipTranscodingStage; print('imports OK')"
#
# Requirements: a GPU instance (g5/g6/p4d/p5 — for the NVMe scratch + CUDA 12),
# network egress to PyPI + GitHub, ~15 GB free on the NVMe for the venv + wheel
# cache. FFmpeg with the libopenh264 encoder + a software h264 decoder must be present (the
# script checks and tries to install it if missing).
set -uo pipefail

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
NVME="${NEMO_CURATOR_NVME:-/mnt/sagemaker-nvme}"
if [ ! -d "$NVME" ]; then NVME="/tmp"; fi     # fall back to /tmp off-GPU (import-only smoke)
WORK="$NVME/nemo-curator-work"
VENV="$WORK/.venv"
ENV_FILE="$WORK/nemo_curator_env.sh"           # sourced by M3
PY_VERSION="${NEMO_CURATOR_PY:-3.12}"          # v1.2.0 requires-python >=3.10,<3.13 → 3.12 OK
NC_VERSION="${NEMO_CURATOR_VERSION:-1.2.0}"    # PIN. Do NOT let this drift to main/v26.x.
# Use the CPU video extra, NOT video_cuda12. video_cuda12 hard-depends on
# flash-attn (source build) + PyNvVideoCodec/cvcuda/pycuda, and flash-attn's
# build fails on the SMD image (CUDA 12.9 nvcc vs the torch wheel's CUDA) — the
# same reason setup_cosmos_env.sh EXCLUDES flash-attn for Alpamayo. The
# split/transcode/motion-filter subset is model-free and (verified against the
# v1.2.0 source) imports + runs with only video_cpu deps: av, opencv, torchvision,
# einops, easydict. No flash-attn, no source compile, no CUDA-version fight.
NC_EXTRA="${NEMO_CURATOR_EXTRA:-video_cpu}"

echo "=== AV 3.0 Blueprint Lab — NeMo Curator environment setup ==="
echo "NVMe work dir : $WORK"
echo "venv          : $VENV (python $PY_VERSION)"
echo "nemo-curator  : $NC_VERSION  extra=[$NC_EXTRA]"
echo ""

# --------------------------------------------------------------------------
# Pre-flight
# --------------------------------------------------------------------------
if [ "$NVME" = "/tmp" ]; then
    echo "WARNING: /mnt/sagemaker-nvme not found — using /tmp. This is fine for an"
    echo "         import-only smoke test off a GPU box, but real curation wants the"
    echo "         NVMe scratch on a g5/g6/p4d/p5 instance."
    echo ""
fi

mkdir -p "$WORK"

# uv — fast installer. Install to the NVMe if absent (keeps the 5 GB home EBS clear).
export UV_CACHE_DIR="$NVME/uv-cache"
export UV_INSTALL_DIR="$WORK/uv-bin"
if ! command -v uv &>/dev/null; then
    if [ -x "$UV_INSTALL_DIR/uv" ]; then
        export PATH="$UV_INSTALL_DIR:$PATH"
    else
        echo "[uv] installing uv to $UV_INSTALL_DIR ..."
        curl -LsSf https://astral.sh/uv/install.sh | \
            env UV_INSTALL_DIR="$UV_INSTALL_DIR" INSTALLER_NO_MODIFY_PATH=1 sh 2>&1 | tail -3
        export PATH="$UV_INSTALL_DIR:$PATH"
    fi
fi
command -v uv &>/dev/null || { echo "ERROR: uv not on PATH after install."; exit 1; }

# --------------------------------------------------------------------------
# FFmpeg pre-flight — the libopenh264 encoder + a software h264 decoder are both
# required. (Transcode uses H.264 so the motion filter can read motion-vector
# side data; ClipWriter also runs ffprobe in a CPU Ray actor and fail-fasts
# without a software h264 decoder.)
# --------------------------------------------------------------------------
# ffmpeg_works: 0 unless ffmpeg actually RUNS and has the libopenh264 encoder.
# We must RUN it (not just `command -v`) — the SMD image ships a BROKEN 2016
# conda ffmpeg that exists on PATH but exits 127 ("error while loading shared
# libraries: libx264.so.138"); `-encoders 2>/dev/null` on it returns empty,
# which silently looks like "no encoder". We require libopenh264 (H.264): the
# transcode stage uses it because NeMo Curator's motion filter reads
# motion-vector side data, which ffmpeg exports for H.264 but NOT for VP9.
ffmpeg_works() {
    command -v ffmpeg &>/dev/null || return 1
    ffmpeg -hide_banner -version &>/dev/null || return 1   # exits 127 if libs missing
    ffmpeg -hide_banner -encoders 2>/dev/null | grep -q 'libopenh264' || return 1
    ffmpeg -hide_banner -decoders 2>/dev/null | grep -qE '(^| )h264( |$)|libopenh264' || return 1
    return 0
}

if ffmpeg_works; then
    echo "[ffmpeg] OK: $(command -v ffmpeg) ($(ffmpeg -hide_banner -version 2>/dev/null | head -1))"
else
    echo "[ffmpeg] no working ffmpeg with libopenh264 (the SMD image's stock ffmpeg is"
    echo "         broken) — force-reinstalling a modern conda-forge build..."
    if command -v conda &>/dev/null; then
        # --force-reinstall + a version floor is REQUIRED: a bare `conda install
        # ffmpeg` sees the broken 2016 package as "already installed" and skips.
        # ffmpeg 8.x from conda-forge ships libvpx-vp9 + libopenh264, no sudo.
        conda install -y -c conda-forge --force-reinstall 'ffmpeg>=6' 2>&1 | tail -5 || true
    fi
    hash -r 2>/dev/null || true   # refresh PATH cache so the reinstalled ffmpeg is seen
    if ffmpeg_works; then
        echo "[ffmpeg] OK after reinstall: $(command -v ffmpeg) ($(ffmpeg -hide_banner -version 2>/dev/null | head -1))"
    else
        echo "WARNING: still no working ffmpeg with libopenh264. The transcode stage will"
        echo "         fail. Try, in a fresh terminal: conda install -y -c conda-forge"
        echo "         --force-reinstall 'ffmpeg>=6'  then re-run this script."
    fi
fi

# --------------------------------------------------------------------------
# Create the dedicated uv venv (idempotent) + install nemo-curator[video_cpu]
# --------------------------------------------------------------------------
IMPORT_CHECK='from nemo_curator.pipeline import Pipeline
from nemo_curator.stages.video.clipping.clip_extraction_stages import FixedStrideExtractorStage, ClipTranscodingStage
from nemo_curator.stages.video.io.video_reader import VideoReader
from nemo_curator.stages.video.filtering.motion_filter import MotionFilterStage, MotionVectorDecodeStage
from nemo_curator.stages.video.io.clip_writer import ClipWriterStage'

if [ -d "$VENV" ] && "$VENV/bin/python" -c "$IMPORT_CHECK" 2>/dev/null; then
    echo "[venv] $VENV already has nemo-curator $NC_VERSION with all video stages — skipping install."
else
    # A prior failed/partial install leaves a stale venv (e.g. torch present but
    # nemo-curator missing). Remove it so the retry starts clean.
    if [ -d "$VENV" ]; then
        echo "[venv] removing stale/partial venv at $VENV for a clean retry ..."
        rm -rf "$VENV"
    fi
    echo "[venv] creating uv venv (python $PY_VERSION) at $VENV ..."
    uv venv --python "$PY_VERSION" "$VENV" 2>&1 | tail -3

    # video_cpu is all prebuilt wheels — NO source compilation (no flash-attn,
    # no pycuda), so no torch pre-install, no --no-build-isolation, and no
    # transformers override are needed. The resolver pulls a prebuilt torch
    # wheel; a CPU-only motion-filter run doesn't care which CUDA it was built
    # for (it imports and runs CPU tensor ops fine).
    echo "[venv] installing nemo-curator==$NC_VERSION [$NC_EXTRA] (5-15 min; pinned tag) ..."
    VIRTUAL_ENV="$VENV" uv pip install \
        "nemo-curator[$NC_EXTRA]==$NC_VERSION" 2>&1 | tail -20

    echo "[venv] verifying video-pipeline imports resolve ..."
    if "$VENV/bin/python" -c "$IMPORT_CHECK" 2>&1 | tail -5; then
        echo "[venv] import check PASSED."
    else
        echo "ERROR: nemo-curator installed but the video-pipeline imports do not"
        echo "       resolve. This is the failure mode the v1.2.0 pin is meant to"
        echo "       prevent — check that the resolved version is exactly $NC_VERSION"
        echo "       (VIRTUAL_ENV=$VENV uv pip show nemo-curator)."
        exit 1
    fi
fi

# --------------------------------------------------------------------------
# Locate the shipped video example (the CLI M3 shells out to)
# --------------------------------------------------------------------------
EXAMPLE="$(find "$VENV" -path '*tutorials/video/getting-started/video_split_clip_example.py' 2>/dev/null | head -1)"
if [ -z "$EXAMPLE" ]; then
    # tutorials may not ship inside the wheel; fetch the pinned copy from GitHub.
    EXAMPLE="$WORK/video_split_clip_example.py"
    if [ ! -f "$EXAMPLE" ]; then
        echo "[example] fetching video_split_clip_example.py @ v$NC_VERSION from GitHub ..."
        curl -LsSf -o "$EXAMPLE" \
          "https://raw.githubusercontent.com/NVIDIA-NeMo/Curator/v$NC_VERSION/tutorials/video/getting-started/video_split_clip_example.py" \
          2>&1 | tail -2 || echo "  (fetch failed — M3 can still call the Pipeline API directly)"
    fi
fi
echo "[example] video CLI: ${EXAMPLE:-<none — use the Pipeline API>}"

# --------------------------------------------------------------------------
# Emit the env file M3 sources
# --------------------------------------------------------------------------
cat > "$ENV_FILE" <<EOF
# nemo_curator_env.sh — source this to run NeMo Curator's video pipeline.
# Generated by setup_nemo_curator_env.sh. Safe to source repeatedly.
export NEMO_CURATOR_VENV="$VENV"
export NEMO_CURATOR_WORK="$WORK"
export NEMO_CURATOR_EXAMPLE="${EXAMPLE:-}"
export UV_CACHE_DIR="$NVME/uv-cache"
# Convenience: a python that runs INSIDE the curator venv.
nemo-curator-python() { "$VENV/bin/python" "\$@"; }
export -f nemo-curator-python 2>/dev/null || true
EOF

echo ""
echo "=== Done. NeMo Curator ($NC_VERSION) ready. ==="
echo "Source it:  source $ENV_FILE"
echo "Venv python: $VENV/bin/python"
echo ""
echo "NOTE: this installs the split/transcode/motion-filter subset (model-free)."
echo "      To also demo Cosmos-Embed1 embeddings + semantic dedup, pre-cache"
echo "      nvidia/Cosmos-Embed1-224p (~2.4 GB, ungated, rev 787e0b9) and pass"
echo "      --embedding-algorithm cosmos-embed1-224p (drop --no-generate-embeddings)."
