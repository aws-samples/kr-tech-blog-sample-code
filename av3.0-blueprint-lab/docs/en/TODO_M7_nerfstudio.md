# M7 (Nerfstudio) — the splatfacto training cell

This is the document the notebook and `scripts/setup_gsplat_env.sh` point at when the
3D-training step fails. Read the first section before you spend time debugging: the
repository itself does not agree on whether this cell is expected to work.

---

## 1. The repo states two contradictory things. Neither is measured.

| Where | Claim |
|---|---|
| `notebooks/M7_Nerfstudio_3D_Reconstruction.ipynb` cell 0 | "The **splatfacto training cell (cell 5) does NOT run** on the current SageMaker Distribution GPU image … Real training needs a **custom image with the full CUDA toolkit**." |
| the same notebook, cell 5 | "**`scripts/setup_gsplat_env.sh` … fixes all of it** the durable way … so training runs end-to-end (a genuine Gaussian-Splatting pipeline)." |
| `docs/en/ADMIN_GUIDE.md` | "**M7 now trains** — the `splatfacto` cell works after a one-time gsplat CUDA build." |
| `docs/en/PARTICIPANT_GUIDE.md` | M7 is "known-limited"; "Don't be surprised if that last cell fails." |

Both notebook claims were introduced in the **same commit** (`7260cf8`), so the history
cannot arbitrate between them. The ADMIN_GUIDE's optimistic line is *older* than the
script it credits.

**The execution record now settles half of it.**
`examples/notebooks-with-outputs.tar.gz` holds a full 9-of-9-cell M7 run on **4x A10G**
(`ml.g5.12xlarge`, sm_86): gsplat's CUDA backend built, nerfstudio 1.1.5 installed, and
`splatfacto` trained **5000 iterations in 83.9 s**, its densification log ending at
236,507 Gaussians. So the notebook cell-0 claim that the cell "does NOT run" is false,
and cell 5 plus the ADMIN_GUIDE are right: **training runs** — including on the A10G arch
that section 3 below still calls unverified.

**What the same run shows failing is the step after it.** Cell 7's novel-view render
exited `rc=1` and produced **0 frames** ("No rendered images found — check render
output."), so cell 8 uploaded only `reconstruction_metadata.json` (667 bytes) and no
imagery — while `docs/en/DATA_CONTRACT.md` lists M7's outputs as
"`m7/reconstruction_metadata.json`, renders". Cell 10 then marked the module complete on
the dashboard anyway.

**Status: training VERIFIED on 4x A10G; novel-view render FAILING.** M7 stays optional,
but the open question has moved. It is no longer "does it train" — it is "why does the
render exit 1 and write nothing", and separately "why does a module that produced no
renders report itself complete".

---

## 2. What is left to settle — the render, not the training

The training question is answered (section 1). What a fresh run still has to answer is why
`ns-render` exits 1 with 0 frames. Note that the captured failure came from a **4-GPU**
box; a single-GPU run may behave differently, which is itself worth knowing.

M7's recommended instance is `ml.g5.xlarge` (1× A10G 24 GB, ~$1.41/hr in us-west-2,
~$1.73 in ap-northeast-2), so one Run-All is ~$0.25 and about 15 minutes.

1. Provision one throwaway participant, set the instance to `ml.g5.xlarge`.
2. **Restart & Run All.** Do not skip the install cell — see the ephemerality note below.
3. Capture cell 7's full stderr, not just its summary line, and record whether any frames
   appear under the render output directory.
4. Then correct the notebook's own cell-0 and cell-5 markdown, which still say the
   training cell does not run and that no execution record exists.

Tear the profile down afterwards: `scripts/teardown.sh --user <id>`.

---

## 3. What the failure looks like, and what the script already does about it

`splatfacto` needs **gsplat**, whose PyPI distribution is pure-Python: the CUDA kernels
are JIT-compiled from source on first use. The SageMaker Distribution image ships the CUDA
*runtime* and `nvcc`, but its conda CUDA **dev** packages are incomplete and split across
non-standard paths. A naive build therefore fails on:

- missing headers — `cuda_runtime.h`, `fatbinary_section.h`
- an `nvvm` mismatch, so `nvcc` cannot find `cicc`
- and critically, `ns-train` re-compiles in a **fresh subprocess** that ignores any
  `CPATH` you exported in the shell

`scripts/setup_gsplat_env.sh` addresses all three: it installs the missing dev headers,
symlinks `nvvm` so `nvcc` finds `cicc`, and symlinks the real CUDA headers and libs into
the standard `$CUDA_HOME/include` + `lib64` paths that torch hard-codes — so the build
works with no environment variables, in a terminal or inside `ns-train`'s subprocess. It
also adds version-matched TensorFlow-bundled nvcc headers as a gap-filler.

It builds for both architectures the lab uses: `setup_gsplat_env.sh:54`
`ARCH="${GSPLAT_ARCH:-8.6;8.9}"` covers sm_86 (A10G, `ml.g5.*`) and sm_89 (L4,
`ml.g6.*`). The script's own header records verification on **g6/L4 only**, while notebook
cell 3 claims "g6/L4 + g5/A10G". The captured run in
`examples/notebooks-with-outputs.tar.gz` resolves that in the notebook's favour: it built
and trained on **A10G / sm_86**. The script header is simply behind.

### This is a per-SESSION bootstrap, not an install

`/opt/conda` is an image layer. Stopping and restarting the JupyterLab app wipes the dev
headers and symlinks — the gsplat *Python package* survives, the CUDA *build inputs* do
not. **Re-run the install cell at the start of every session** before the training cell.
It is idempotent: ~3–5 min cold, seconds when already built.

If you hit a build error, this is the first thing to check. An app that idle-shut-down
(90 min default) and was reopened is the common case.

---

## 4. If it does not work: the demo path

M7 is explicitly optional. Cells 1–4 — setup, GPU check, Nerfstudio install, nuScenes
multi-camera data prep — run and demonstrate the reconstruction *pipeline*: loading real
nuScenes camera images, building camera poses and intrinsics, and writing the
`transforms.json` a Gaussian-Splatting trainer consumes. That is a legitimate walkthrough
of blog Stage 6 without the training step.

Present it that way rather than as a failure, and move on to M8/M9.

---

## 5. A separate limitation that survives even if training works

The camera poses written in the data-prep cell are a **synthetic sin-wave trajectory**,
not real nuScenes calibration. So even a clean `splatfacto` run is a **smoke test** of the
pipeline, not a metrically correct reconstruction.

Making it real means wiring nuScenes `calibrated_sensor` + `ego_pose` into
`transforms.json`. The tables are already staged — `scripts/stage_nuscenes.sh` copies the
whole `v1.0-mini/*.json` set — so this is a data-plumbing task, not a missing-data one.

Note also that the blog's canonical Stage 6 uses NVIDIA Omniverse **NuRec** (commercial);
Nerfstudio is the open-source stand-in here, so exact parity with the blog was never the
goal.
