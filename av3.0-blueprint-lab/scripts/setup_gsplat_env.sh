#!/bin/bash
# setup_gsplat_env.sh — build gsplat's CUDA extension so M7 (Nerfstudio
# `ns-train splatfacto`, 3D Gaussian Splatting) actually trains on a SageMaker
# Distribution (SMD) GPU app.
#
# WHY THIS SCRIPT EXISTS
# ----------------------
# nerfstudio hard-pins `gsplat==1.4.0`, whose PyPI wheel is pure-Python
# (py3-none-any, no compiled .so). gsplat's `_backend.py` therefore calls
# torch.utils.cpp_extension.load() on EVERY import and compiles its CUDA kernels
# from source. The SMD GPU image ships the CUDA *runtime* + nvcc but its conda
# CUDA dev packages are INCOMPLETE and laid out in the "targets split" scheme, so
# a naive compile hits a chain of failures (verified on SMD 4.2.x, py3.12,
# torch 2.8.0+cu129, g6/L4 sm_89):
#   1. `cuda_runtime.h: No such file` — dev headers absent -> install
#      cuda-cudart-dev + cuda-crt (they land in targets/x86_64-linux/include).
#   2. `.../targets/x86_64-linux/nvvm/bin/cicc: not found` — conda puts nvvm at
#      /opt/conda/nvvm; nvcc looks under $CUDA_HOME/targets/.../nvvm -> symlink.
#   3. `fatbinary_section.h: No such file` — an internal nvcc header conda omits
#      but the TensorFlow wheel bundles a version-matched (CUDA 12.9) copy.
#   4. Under `ns-train` the compile STILL failed on `cuda_runtime.h` even after
#      the above, because torch cpp_extension HARD-CODES the CUDA include as
#      `-isystem $CUDA_HOME/include` (and `-L $CUDA_HOME/lib64`) and NEVER reads
#      CPATH; and ns-train is a fresh subprocess that re-JITs under a single-arch
#      (sm_89) build key, so any per-shell CPATH we exported never reached it.
#
# THE DURABLE FIX (this script): instead of exporting CPATH (which does not
# survive into ns-train's subprocess), we SYMLINK the real targets-split headers
# into `/opt/conda/include`, libs into `/opt/conda/lib` + `/opt/conda/lib64`, and
# the TF `fatbinary_section.h` gap-filler into the same include dir. Then the
# paths torch hard-codes are physically correct with ZERO environment variables,
# so gsplat builds identically whether imported from a terminal OR re-JITed inside
# ns-train's subprocess.
#
# EPHEMERAL: /opt/conda is an image layer — a JupyterLab app stop/restart RESETS
# the conda dev-header install AND these symlinks (verified: a session reset wiped
# targets/x86_64-linux/include while nvcc + the gsplat py-package survived). So
# this is a per-SESSION bootstrap, not a one-time install. Re-run it at the start
# of every session before M7's training cell. It is idempotent (skips work
# already done); ~3-5 min on a cold session, seconds when already built.
#
# USAGE (from a GPU JupyterLab terminal, or `!bash scripts/setup_gsplat_env.sh`):
#     bash scripts/setup_gsplat_env.sh
#
# Requirements: a 24GB single-GPU instance (g5.xlarge A10G sm_86, or g6 L4
# sm_89), the CUDA 12.9 SMD image, network egress to conda + PyPI.
set -uo pipefail

CONDA_ROOT="${CONDA_ROOT:-/opt/conda}"
PY="$CONDA_ROOT/bin/python"
# Build for A10G (sm_86, g5) AND L4 (sm_89, g6). Note: ns-train auto-detects the
# live GPU's single arch and may re-JIT under that key — the symlink fix below is
# what makes THAT recompile succeed too, regardless of arch.
ARCH="${GSPLAT_ARCH:-8.6;8.9}"
JOBS="${MAX_JOBS:-8}"

echo "=== AV 3.0 Blueprint Lab — gsplat CUDA environment setup ==="
echo "conda root : $CONDA_ROOT"
echo "arch list  : $ARCH   jobs: $JOBS"

# --------------------------------------------------------------------------
# 1) Missing CUDA dev headers (cuda_runtime.h etc.) — reset on every app restart,
#    so (re)install unconditionally when absent.
# --------------------------------------------------------------------------
TGT="$CONDA_ROOT/targets/x86_64-linux"
if [ ! -f "$TGT/include/cuda_runtime.h" ]; then
    echo "[cuda] installing missing dev headers (cuda-cudart-dev, cuda-crt) ..."
    conda install -y -c nvidia -c conda-forge cuda-cudart-dev=12.9 cuda-crt=12.9 2>&1 | tail -4
fi
# Re-discover the real header dir (in case the layout differs).
CUDA_RT="$(find "$CONDA_ROOT/targets" -path '*/include/cuda_runtime.h' 2>/dev/null | head -1)"
if [ -z "$CUDA_RT" ]; then
    echo "ERROR: cuda_runtime.h still missing after install — cannot build gsplat."
    echo "       Fall back to the M7 demo path (see docs/en/TODO_M7_nerfstudio.md)."
    exit 1
fi
TGT="$(dirname "$(dirname "$CUDA_RT")")"   # .../targets/x86_64-linux
echo "[cuda] header tree: $TGT"

# --------------------------------------------------------------------------
# 2) nvvm/cicc discovery — symlink conda's nvvm into the targets tree nvcc probes
# --------------------------------------------------------------------------
if [ ! -e "$TGT/nvvm" ] && [ -d "$CONDA_ROOT/nvvm" ]; then
    ln -s "$CONDA_ROOT/nvvm" "$TGT/nvvm" 2>/dev/null || true
    echo "[nvvm] linked $TGT/nvvm -> $CONDA_ROOT/nvvm"
fi

# --------------------------------------------------------------------------
# 3) DURABLE header/lib discovery — mirror the targets-split tree into the
#    standard $CUDA_HOME paths torch cpp_extension HARD-CODES. This (not CPATH)
#    is what makes ns-train's subprocess recompile succeed with no env vars.
#    Per-file `ln -s` (never a blanket `ln -sf`) so a same-named real conda
#    header/lib is never clobbered.
# --------------------------------------------------------------------------
echo "[link] mirroring CUDA headers -> $CONDA_ROOT/include and libs -> $CONDA_ROOT/lib[64]"
for f in "$TGT"/include/*; do ln -s "$f" "$CONDA_ROOT/include/" 2>/dev/null; done
for f in "$TGT"/lib/*;     do ln -s "$f" "$CONDA_ROOT/lib/"     2>/dev/null; done
# gsplat/torch link with `-L $CUDA_HOME/lib64 -lcudart`, so libcudart MUST be
# resolvable in lib64 — not just lib. The old `[ -e lib64 ] || ln -s tree`
# guard SILENTLY skipped when lib64 already existed as an (empty) directory,
# leaving `-lcudart` unresolvable -> `/usr/bin/ld: cannot find -lcudart`.
# Test for the actual library, not the directory: if libcudart is missing from
# lib64, mirror every target lib into it per-file (works whether lib64 is a
# real dir or absent).
if ! ls "$CONDA_ROOT"/lib64/libcudart.so* >/dev/null 2>&1; then
    mkdir -p "$CONDA_ROOT/lib64"
    for f in "$TGT"/lib/*; do ln -s "$f" "$CONDA_ROOT/lib64/" 2>/dev/null; done
    echo "[link] mirrored CUDA libs into $CONDA_ROOT/lib64 (was missing libcudart)"
fi
# Fail fast if libcudart still isn't linkable from lib64 — otherwise the build
# fails opaquely 3 min later at the linker.
ls "$CONDA_ROOT"/lib64/libcudart.so >/dev/null 2>&1 || \
    ls "$CONDA_ROOT"/lib64/libcudart.so.* >/dev/null 2>&1 || {
        echo "ERROR: libcudart.so not linkable in $CONDA_ROOT/lib64 — gsplat link (-lcudart) will fail."; exit 1; }

# TF-bundled nvcc headers (version-matched CUDA 12.9) fill internal headers conda
# omits (e.g. fatbinary_section.h). Real conda headers linked above win.
TFINC="$(find "$CONDA_ROOT"/lib/python*/site-packages/tensorflow/include/external/cuda_nvcc/include -name fatbinary_section.h 2>/dev/null | head -1 | xargs -r dirname)"
if [ -n "$TFINC" ]; then
    echo "[link] TF gap-filler headers: $TFINC"
    for h in "$TFINC"/*.h; do ln -s "$h" "$CONDA_ROOT/include/" 2>/dev/null; done
fi
[ -f "$CONDA_ROOT/include/cuda_runtime.h" ] || { echo "ERROR: cuda_runtime.h not linked into $CONDA_ROOT/include"; exit 1; }

# --------------------------------------------------------------------------
# 4) Fast path: if gsplat's compiled backend already imports (in a CLEAN env,
#    the way ns-train calls it), we're done.
# --------------------------------------------------------------------------
if env -u CPATH -u LIBRARY_PATH -u LD_LIBRARY_PATH \
       "$PY" -c "from gsplat.cuda._backend import _C" 2>/dev/null; then
    echo "[gsplat] CUDA backend already builds/imports in a clean env — done."
    echo "=== Done (cached). ==="
    exit 0
fi

# --------------------------------------------------------------------------
# 5) Build gsplat 1.4.0 from source. CUDA_HOME=/opt/conda so nvcc self-locates
#    nvvm/cicc/ptxas; headers/libs are now discoverable via the standard-path
#    symlinks (no CPATH needed). Clear any stale JIT cache first.
# --------------------------------------------------------------------------
export CUDA_HOME="$CONDA_ROOT"
export PATH="$CONDA_ROOT/bin:$PATH"
export TORCH_CUDA_ARCH_LIST="$ARCH"
export MAX_JOBS="$JOBS"
rm -rf ~/.cache/torch_extensions/*/gsplat_cuda 2>/dev/null || true

echo "[gsplat] source-building gsplat==1.4.0 (this can take ~3-5 min) ..."
"$PY" -m pip install --no-build-isolation --no-cache-dir gsplat==1.4.0 2>&1 | tail -6

# --------------------------------------------------------------------------
# 6) Prove it in a CLEAN env (no CPATH/LIBRARY_PATH) — this is how ns-train's
#    subprocess will import it. If this passes, ns-train's recompile will too.
# --------------------------------------------------------------------------
if env -u CPATH -u C_INCLUDE_PATH -u CPLUS_INCLUDE_PATH -u LIBRARY_PATH -u LD_LIBRARY_PATH \
       "$PY" -c "from gsplat.cuda._backend import _C; print('gsplat CUDA backend OK (clean env)')" 2>&1 | tail -3; then
    echo "=== Done. gsplat CUDA extension builds in a clean env — M7 ns-train can now run. ==="
    exit 0
else
    echo "ERROR: gsplat built but its CUDA backend failed to import in a clean env."
    echo "       Re-run this script, or fall back to the M7 demo path"
    echo "       (see docs/en/TODO_M7_nerfstudio.md)."
    exit 1
fi
