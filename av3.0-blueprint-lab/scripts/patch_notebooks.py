#!/usr/bin/env python3
"""Patch AV3.0 tutorial notebooks to reference the ACTUAL deployed AWS resources.

The notebooks ship with hardcoded bucket names (three different, all wrong),
inconsistent profile env-var names, and model-cache / nuScenes prefixes that do
not match what is staged in S3. This script rewrites, in place, only the config
cell (and a couple of body lines) of each notebook — preserving cell outputs and
metadata so the diff stays minimal.

Config resolution after patching (single canonical scheme):
    USER_PROFILE  <- os.environ["USER_PROFILE"]  (injected by the JupyterLab LCC)
    SHARED_BUCKET <- os.environ["SHARED_BUCKET"]  (fallback av30lab-shared-data-<acct>)
    USER_BUCKET   <- os.environ["USER_BUCKET"]    (fallback av30lab-user-workspace-<acct>)

Run from the repo root:  python3 scripts/patch_notebooks.py
Idempotent: safe to re-run (string replacements are no-ops once applied).
"""

import json
import sys
from pathlib import Path

NB_DIR = Path(__file__).resolve().parent.parent / "notebooks"

# ---- Canonical env-driven definitions (with account-derived fallbacks) ----
SHARED_LINE = (
    'SHARED_BUCKET = os.environ.get("SHARED_BUCKET", '
    'f"av30lab-shared-data-{ACCOUNT_ID}")'
)
USER_LINE = (
    'USER_BUCKET = os.environ.get("USER_BUCKET", '
    'f"av30lab-user-workspace-{ACCOUNT_ID}")'
)

# Per-notebook list of exact (old, new) substring replacements applied to the
# joined source of whichever code cell contains the old string.
REPLACEMENTS = {
    "M1_Data_Exploration.ipynb": [],  # neutered — repo .ipynb is the source of truth (see chore/hygiene)
    "M2_Cosmos_Reason_Captioning.ipynb": [],  # neutered — repo .ipynb is the source of truth (see chore/hygiene)
    "M3_Cosmos_Curator.ipynb": [],  # neutered — M3 rewritten in-repo (real NeMo Curator); old patterns gone
    "M4_OpenSearch_Semantic_Search.ipynb": [
        ('USER_BUCKET = f"av30-blueprint-lab-{ACCOUNT_ID}"', USER_LINE),
        # BUG: `from sentence_transformers import SentenceTransformer` pulls in
        # `transformers`, which auto-probes the TensorFlow backend and imports
        # activations_tf -> fails on the SMD GPU image because it ships Keras 3
        # (transformers needs the tf-keras / Keras-2 shim):
        #   ValueError: Your currently installed version of Keras is Keras 3 ...
        # We only need the PyTorch path, so disable the TF/Flax backends BEFORE
        # transformers is imported. Set the env vars at the very top of the cell.
        (
            '"""Install dependencies — sentence-transformers for embedding, opensearch-py for client"""\n'
            'import subprocess\n'
            'import sys\n',

            '"""Install dependencies — sentence-transformers for embedding, opensearch-py for client"""\n'
            'import os\n'
            '# transformers must NOT load the TensorFlow backend (SMD GPU image has\n'
            '# Keras 3, which the transformers TF path rejects). Force the torch-only\n'
            '# path before any transformers import.\n'
            'os.environ["USE_TF"] = "0"\n'
            'os.environ["USE_FLAX"] = "0"\n'
            'os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"\n'
            'import subprocess\n'
            'import sys\n'
        ),
        # SECURITY: drop the "dashboard" network rule so we do NOT expose the
        # public OpenSearch Dashboards web UI. The notebook only uses the
        # collection API (index + search via opensearch-py), so a collection-only
        # rule is sufficient. Data stays protected regardless of AllowFromPublic
        # because every data-plane call still requires the execution role's IAM
        # aoss:APIAccessAll + the data-access policy that names only that role.
        (
            '    network_policy = json.dumps([{\n'
            '        "Rules": [{\n'
            '            "ResourceType": "collection",\n'
            '            "Resource": [f"collection/{collection_name}"]\n'
            '        }, {\n'
            '            "ResourceType": "dashboard",\n'
            '            "Resource": [f"collection/{collection_name}"]\n'
            '        }],\n'
            '        "AllowFromPublic": True\n'
            '    }])',

            '    # Collection-only network rule (no public "dashboard"/web-UI rule).\n'
            '    # Data access is still gated by IAM (aoss:APIAccessAll) + the data-\n'
            '    # access policy naming this execution role, so the endpoint being\n'
            '    # public does not permit unauthenticated reads/writes.\n'
            '    network_policy = json.dumps([{\n'
            '        "Rules": [{\n'
            '            "ResourceType": "collection",\n'
            '            "Resource": [f"collection/{collection_name}"]\n'
            '        }],\n'
            '        "AllowFromPublic": True\n'
            '    }])'
        ),
        # BUG: OpenSearch Serverless (aoss) VECTORSEARCH only supports the FAISS
        # k-NN engine, NOT nmslib. An nmslib index either fails to create or
        # silently rejects writes. Switch the engine to faiss.
        (
            '"engine": "nmslib"',
            '"engine": "faiss"',
        ),
        # BUG: aoss does NOT support the index-management _refresh API — calling
        # os_client.indices.refresh() returns 404. aoss makes documents
        # searchable automatically (near-real-time); there is no manual refresh.
        # Replace with a short sleep so the subsequent search sees the docs.
        (
            '# Force refresh to make documents searchable immediately\n'
            'os_client.indices.refresh(index=INDEX_NAME)',

            '# NOTE: OpenSearch Serverless does NOT support the _refresh API\n'
            '# (indices.refresh -> 404). aoss indexes documents automatically in\n'
            '# near-real-time; wait briefly so the search cell sees them.\n'
            'time.sleep(10)',
        ),
        # BUG: aoss also does not support indices.exists (404). Guard the
        # delete-if-exists block so a fresh collection (no index yet) does not
        # 404 before create. create_index is the only call we actually need.
        (
            '# Create index (delete if exists)\n'
            'if os_client.indices.exists(index=INDEX_NAME):\n'
            '    os_client.indices.delete(index=INDEX_NAME)\n'
            '    print(f"Deleted existing index: {INDEX_NAME}")\n'
            '\n'
            'os_client.indices.create(index=INDEX_NAME, body=index_body)',

            '# Create the index. aoss does not support indices.exists (404), so we\n'
            '# just try to create it and treat "already exists" as fine (aoss is\n'
            '# fresh per collection, so this normally creates it outright).\n'
            'try:\n'
            '    os_client.indices.create(index=INDEX_NAME, body=index_body)\n'
            'except Exception as _e:\n'
            '    if "resource_already_exists" in str(_e) or "already exists" in str(_e):\n'
            '        print(f"Index already exists: {INDEX_NAME}")\n'
            '    else:\n'
            '        raise',
        ),
    ],
    # M12 is NOT string-patched. It was rewritten in-repo (via NotebookEdit) to a
    # real 2-node torch.distributed DDP job: cell-1 already uses the
    # av30lab-user-workspace-{ACCOUNT_ID} convention, cell-5 fits on M3's curated
    # captions (real input), and cell-6 plots the job's measured training_log.json
    # (no np.random simulation). It trains on CPU (ml.m5.xlarge x2, gloo); the same
    # script runs GPU/nccl if that quota is raised. The old bucket string this
    # patch targeted no longer exists, so there is nothing for the string-patcher.
    # See docs/en/HYPERPOD_M12.md.
    "M12_HyperPod_Distributed_Training.ipynb": [],
    # M11 is NOT string-patched. Like M12, it was rewritten in-repo (via
    # NotebookEdit) into a real SageMaker Pipeline that upserts + starts a 3-step
    # DAG on CPU (ml.m5.xlarge). cell-1 already uses the
    # av30lab-user-workspace-{ACCOUNT_ID} / av30lab-shared-data-{ACCOUNT_ID}
    # convention and a PipelineSession(default_bucket_prefix=users/{PROFILE}/m11)
    # so SDK uploads stay inside the exec role's write scope. Step 1 consumes M1's
    # real selected_scenes.json. The old av30-blueprint-lab-* bucket strings this
    # patch targeted no longer exist, so there is nothing for the string-patcher.
    # See docs/en/PIPELINE_M11.md.
    "M11_Pipeline_Automation.ipynb": [],
    "M7_Nerfstudio_3D_Reconstruction.ipynb": [
        ('USER_BUCKET = f"av30-blueprint-lab-{ACCOUNT_ID}"', USER_LINE),
        ('SHARED_BUCKET = "av30-blueprint-lab-shared"', SHARED_LINE),
        ('INPUT_PREFIX = "nuscenes-mini/"',
         'INPUT_PREFIX = "datasets/nuscenes-mini/"'),
        # NOTE: the fpsample-prebuilt-wheel fix and the __version__/metadata fix
        # for cell 3 are applied directly in the notebook (they don't fit the
        # simple substring-replace model cleanly — the fpsample `new` contained
        # the original nerfstudio-install `old`, which broke idempotency). The
        # cell-5 training fixes below remain here as they are stable substrings.
        # (Historical: `pip install nerfstudio` alone fails building fpsample
        # 1.0.2 from source — pybind11 multiple_interpreters — so cell 3 pre-
        # installs fpsample==0.1.0 with --only-binary.)
        # BUG: `nerfstudio.__version__` does not exist on the installed package,
        # so the version print raises AttributeError even though the install
        # succeeded (ns-train works). Read the version from package metadata,
        # which is the reliable source and never raises AttributeError.
        (
            '# Import nerfstudio modules\n'
            'import nerfstudio\n'
            'print(f"Nerfstudio version: {nerfstudio.__version__}")',

            '# Confirm nerfstudio is importable and report its version from\n'
            '# package metadata (the module does not expose __version__).\n'
            'import importlib.metadata\n'
            'import nerfstudio  # noqa: F401 — import proves it loads\n'
            'try:\n'
            '    _ns_ver = importlib.metadata.version("nerfstudio")\n'
            'except Exception:\n'
            '    _ns_ver = "unknown"\n'
            'print(f"Nerfstudio version: {_ns_ver}")'
        ),
        # BUG: "wandb_disabled" is NOT a valid --vis value. ns-train only accepts
        # viewer/wandb/tensorboard/comet (and viewer+* combos), so it exits
        # immediately on arg-parse — no training runs, no config.yml is written.
        # Use "tensorboard": headless, writes only local files, no server/wandb.
        (
            '"--vis", "wandb_disabled",  # Disable viewer/wandb in notebook',
            '"--vis", "tensorboard",  # Headless: local files only, no viewer/wandb',
        ),
        # BUG: the training subprocess result is never checked, so a failed
        # ns-train still prints "Training complete!" (silent false success — the
        # actual symptom that hid the invalid --vis). Fail loudly instead.
        (
            'process.wait()\n'
            'train_time = time.time() - start_train\n'
            '\n'
            'print(f"\\nTraining complete!")',

            'process.wait()\n'
            'train_time = time.time() - start_train\n'
            '\n'
            'if process.returncode != 0:\n'
            '    raise RuntimeError(\n'
            '        f"ns-train failed (exit {process.returncode}). See streamed "\n'
            '        f"output above for the cause."\n'
            '    )\n'
            '\n'
            'print(f"\\nTraining complete!")'
        ),
        # BUG: splatfacto invokes torch.compile, whose Triton/inductor backend
        # JIT-compiles a CUDA helper at runtime and links -lcuda. On the SMD GPU
        # image libcuda.so is not on the linker path, so that gcc build fails:
        #   InductorError: CalledProcessError ... gcc ... cuda_utils.c ... -lcuda
        # gsplat's own rasterization kernels are prebuilt and work fine, so we
        # disable torch.compile (eager mode) for the training subprocess by
        # passing env explicitly to Popen — no shell/global change needed.
        (
            '# Run training process\n'
            'process = subprocess.Popen(\n'
            '    train_cmd,\n'
            '    stdout=subprocess.PIPE,\n'
            '    stderr=subprocess.STDOUT,\n'
            '    text=True\n'
            ')',

            '# Run training process. Disable torch.compile for this subprocess:\n'
            '# the Triton/inductor backend fails to link libcuda.so on this image,\n'
            '# and splatfacto runs fine in eager mode (gsplat kernels are prebuilt).\n'
            '_train_env = {\n'
            '    **os.environ,\n'
            '    "TORCH_COMPILE_DISABLE": "1",\n'
            '    "TORCHDYNAMO_DISABLE": "1",\n'
            '}\n'
            'process = subprocess.Popen(\n'
            '    train_cmd,\n'
            '    stdout=subprocess.PIPE,\n'
            '    stderr=subprocess.STDOUT,\n'
            '    text=True,\n'
            '    env=_train_env\n'
            ')'
        ),
    ],
    # M5/M6/M9/M10 use a different scheme: BLUEPRINT_* env vars and a single S3_BUCKET
    # used for BOTH model reads and user I/O. Split it: SHARED_BUCKET for the
    # model cache, S3_BUCKET repointed to the user-workspace bucket for m*/ I/O
    # (body cells build f"s3://{S3_BUCKET}{INPUT_PREFIX}", so keeping the name
    # S3_BUCKET but pointing it at the user bucket needs no body edits). These
    # cells lack ACCOUNT_ID/boto3, so we inject them.
    # M5 is NOT patched here. Its shipped cells used a hallucinated `cosmos1`
    # API that does not exist; the notebook was rewritten directly (via
    # NotebookEdit) to the REAL cosmos-transfer2.5 workflow — clone the official
    # repo via scripts/setup_cosmos_env.sh, assemble M1's nuScenes CAM_FRONT
    # frames into an mp4, and call examples/inference.py with edge control. The
    # rewritten cells already carry the correct config + `total_memory`, so
    # there is nothing left for the string-patcher to fix. See
    # docs/en/COSMOS_M5_M6.md and scripts/setup_cosmos_env.sh.
    "M5_Cosmos_Transfer_Augmentation.ipynb": [],
    # M6 is NOT patched here. Its shipped cells used a hallucinated `cosmos1`
    # API; the notebook was rewritten directly (via NotebookEdit) to the REAL
    # cosmos-predict2.5 Video2World workflow — setup_cosmos_env.sh (predict) +
    # reuse M5's nuScenes clip + examples/inference.py --inference-type=video2world.
    # The rewritten cells carry the correct config + `total_memory`, so there is
    # nothing left for the string-patcher. See docs/en/COSMOS_M5_M6.md.
    "M6_Cosmos_Predict_Synthesis.ipynb": [],
    # M9 is NOT patched here. Its shipped cells imported a hallucinated `alpamayo`
    # package (alpamayo.model.AlpamayoForConditionalGeneration,
    # alpamayo.inference.AlpamayoInferencePipeline, alpamayo.utils.*) that does
    # NOT exist. The notebook was rewritten directly (via NotebookEdit) to the
    # REAL NVlabs/alpamayo1.5 workflow — setup via scripts/setup_cosmos_env.sh
    # alpamayo (Python 3.12 venv, no flash-attn / sdpa), torch.load a pre-saved
    # demo clip, and run scripts/alpamayo_infer.py
    # (sample_trajectories_from_data_with_vlm_rollout → Chain-of-Causation
    # reasoning + trajectory + minADE). The rewritten cells carry the correct
    # config + per-device `total_memory` check, so there is nothing left for the
    # string-patcher. See docs/en/ALPAMAYO_M9.md.
    "M9_Alpamayo_VLA_Inference.ipynb": [],
    # M10 is NOT patched here. Its shipped cells imported a hallucinated `alpasim`
    # package (import alpasim, alpasim.env.NuRecEnvironment,
    # alpasim.policy.PolicyWrapper.from_alpamayo, alpasim.metrics.*) and a
    # fabricated gym-style env.reset()/env.step() loop with invented metrics
    # (route_completion / comfort_score). AlpaSim is real (NVlabs/alpasim) but is
    # a Docker-Compose gRPC microservice system that a SageMaker Studio notebook
    # (no Docker daemon) cannot host, and its driver needs a >=40 GB GPU. So M10
    # was rewritten directly (via NotebookEdit) to a CPU download-and-visualize
    # notebook. The real AlpaSim closed-loop eval runs on a GPU EC2 host
    # (scripts/alpasim_ec2_setup.sh) and uploads genuine results; the notebook
    # auto-detects the source (real metrics: collision_at_fault / collision_rear /
    # dist_to_gt_trajectory / offroad):
    #   - participant self-run  -> s3://<user-workspace>/users/<id>/m10/ (preferred)
    #   - admin reference run   -> s3://<shared>/m10-reference/          (fallback)
    # Because the notebook is rewritten in-repo and shipped as-is via `aws s3 sync
    # notebooks/`, there is nothing for the string-patcher. See docs/en/ALPASIM_M10.md
    # and docs/en/M10_PARTICIPANT_SSM_RUNBOOK.md.
    "M10_AlpaSim_ClosedLoop.ipynb": [],
    # M8 is NOT patched here. It was authored in-repo against the real nuScenes
    # tables and the S3 model cache, so its shipped cells already carry the right
    # buckets/prefixes and there is nothing for the string-patcher to fix.
    "M8_Cosmos_Reason_SFT.ipynb": [],
}


def patch_notebook(path: Path, repls: list) -> int:
    nb = json.loads(path.read_text())
    applied = 0
    for old, new in repls:
        if old == new:
            continue
        # Idempotency guard: if the replacement is already applied somewhere,
        # skip it. Required because some `new` strings legitimately CONTAIN
        # `old` (e.g. the fpsample fix prepends an install before the original
        # `pip install nerfstudio` block); without this guard a re-run would
        # match `old` inside the already-patched `new` and accumulate copies.
        if any(
            new in "".join(c["source"])
            for c in nb["cells"] if c.get("cell_type") == "code"
        ):
            continue
        hit = False
        for cell in nb["cells"]:
            if cell.get("cell_type") != "code":
                continue
            src = "".join(cell["source"])
            if old in src:
                src = src.replace(old, new)
                # Re-split into line-preserving list (nbformat convention:
                # each element ends with \n except possibly the last).
                lines = src.splitlines(keepends=True)
                cell["source"] = lines
                applied += 1
                hit = True
                break
        if not hit:
            # Not fatal on re-run (already patched), but warn if the target
            # string is genuinely absent and the new one isn't there either.
            already = any(
                new in "".join(c["source"])
                for c in nb["cells"] if c.get("cell_type") == "code"
            )
            if not already:
                # Hard-fail: the target string is genuinely gone AND the patched
                # form isn't present either -> the notebook has drifted and we
                # would silently ship it unpatched. Refuse loudly (this is a
                # manual dev tool; a real drift must be looked at, not warned).
                raise SystemExit(
                    f"ERROR: pattern not found in {path.name}: {old[:60]!r} "
                    f"(notebook drifted; refusing to ship unpatched)"
                )
    if applied:
        path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n")
    return applied


def main() -> int:
    total = 0
    for name, repls in REPLACEMENTS.items():
        path = NB_DIR / name
        if not path.exists():
            print(f"  MISSING: {name}")
            continue
        n = patch_notebook(path, repls)
        print(f"  {name}: {n} replacement(s) applied")
        total += n
    print(f"\nTotal replacements applied: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
