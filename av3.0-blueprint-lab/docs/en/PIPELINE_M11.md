# SageMaker Pipelines (M11) — real orchestration demo, CPU by design

**Status:** M11 **defines and runs a real SageMaker Pipeline** — `upsert()` +
`start()` of a 3-step dependency DAG (Caption → Curate → Augment), polled to
completion, with the run recorded to S3. It is not a definition-only demo. The
step scripts are pure Python over M1's scene metadata, so the steps run on **CPU**
(`ml.m5.xlarge`); the teaching point is the **orchestration pattern**, not compute.

## What M11 was, and what it is now

Like M12, M11 was **not a hallucinated-API failure** — every import and class
(`Pipeline`, `ProcessingStep`, `PipelineSession`, `ScriptProcessor`) is real
SageMaker Python SDK **v2**. Its problems were the same family M12 hit, plus a few
of its own:

| Shipped M11 | Fixed M11 |
|---|---|
| `from sagemaker import Session` (v2 top-level) → fails on the SDK-v3 kernel | cell-1 pins v2 (`>=2.257.2,<3`) + auto kernel restart (from M12) |
| Step1 globbed `INPUT_DIR/*.jpg`, but M1 writes only JSON to `m1/` → 0 captions | Step1 reads M1's `selected_scenes.json` (real scene names + descriptions) → grounded captions |
| 3 steps requested `ml.g5.12xlarge`/`g5.xlarge` (GPU) — processing quota is 0 here | CPU `ml.m5.xlarge` (processing quota available); scripts are pure Python so GPU adds nothing |
| GPU `pytorch-training` image | CPU sklearn container via `image_uris.retrieve("sklearn", …)` — **no `image_scope`** (sklearn has no `processing` scope; passing it raises `ValueError: Unsupported image scope`) |
| exec role lacked `CreatePipeline`/`StartPipelineExecution`/`CreateProcessingJob` | added `SageMakerPipelines` (pipeline/av30-*) + `SageMakerProcessingJobs` (processing-job/*) to the CDK exec role |
| SDK uploads (step code, pipeline def) default to `sagemaker-<region>-<account>` root — outside the role's `users/*` write scope → AccessDenied | `Session`/`PipelineSession(default_bucket=USER_BUCKET, default_bucket_prefix=users/<profile>/m11)` |
| cost cells hard-coded GPU rates | real per-step durations from `execution.list_steps()` + CPU rate; GPU shown as conceptual production |

## Why CPU (and why that's the right call)

The three step scripts do **no model inference** — Step1 builds captions from
M1's scene `description` strings, Step2 is a keyword-score filter + md5 dedup,
Step3 is template string augmentation. None of it uses a GPU. So running the steps
on GPU would be pure waste (and the g5 *processing* quota is 0 in this account
anyway). The **value M11 teaches is orchestration** — a reproducible dependency
DAG, per-step instances that start/stop automatically, and full lineage — and that
is byte-for-byte identical whether a step runs on CPU or GPU. In production the
captioning step would swap to a GPU image running a real VLM (e.g. Cosmos Reason);
only the per-step compute changes, not the pipeline.

## The M1 → M11 data link (real)

Step1 mounts `s3://<user-workspace>/users/<profile>/m1/` and reads
`selected_scenes.json` — the actual nuScenes scenes M1 selected, each with a
`name` (e.g. `scene-0061`) and a human `description` (e.g. "Parked truck,
construction, intersection, turn left, following..."). The captions are grounded
in those real descriptions, so the pipeline consumes genuine upstream output
rather than inventing a count. (M1 does not copy image files into `m1/`; it records
scene metadata and points at the shared nuScenes dataset — so metadata is the
right thing to consume.)

## IAM added for M11 (CDK, least-privilege)

In `infra/av30_constructs/sagemaker.py`, added to the SageMaker execution role:
- `SageMakerPipelines` — `CreatePipeline`/`UpdatePipeline`/`StartPipelineExecution`/
  `Describe*`/`ListPipelineExecutionSteps`/…, scoped to `pipeline/av30-*`.
- `SageMakerProcessingJobs` — `CreateProcessingJob`/`DescribeProcessingJob`/
  `StopProcessingJob`/`AddTags` on `processing-job/*` (SDK auto-names processing
  jobs, so the resource can't be prefix-scoped).
- `iam:PassRole` — reused the self-only, `PassedToService=sagemaker.amazonaws.com`
  statement added for M12; the ProcessingSteps pass this role to their containers.

## Bugs surfaced (mirrors M12 + Pipeline-specific)

Same v2/v3 SDK chain as M12 (#1 v3 kernel, #2 in-memory mix / kernel restart), plus:
- **Pipeline/Processing IAM** — M12 only added training-job perms; M11 needs the
  Pipeline + Processing set above (deployed & verified on the live exec role
  `av30lab-sagemaker-execution-role`).
- **Upload scope** — `default_bucket_prefix` so all SDK uploads land under
  `users/<profile>/m11/` (the only path the exec role can write). Verified present
  on both `Session` and `PipelineSession` in the pinned SDK 2.257.3.
- **GPU quota 0** — steps moved to CPU (same reason M12 uses CPU).
- **Empty input** — consume M1's `selected_scenes.json`, not absent `*.jpg`.
- **`image_scope="processing"` blocker (found in pre-run audit)** — cell-3 built the
  step image with `image_uris.retrieve(framework="sklearn", …, image_scope="processing")`,
  which raises `ValueError: Unsupported image scope: processing` (sklearn's registry
  has only `inference`/`training`/`inference_graviton`). It failed on the first line
  of cell-3 on *every* run — before any pipeline was defined, so no billing, but a
  hard dead-stop. Fix: omit `image_scope`; the returned
  `…/sagemaker-scikit-learn:1.2-1-cpu-py3` is the correct CPU image (this is how
  `SKLearnProcessor` resolves it internally). Caught by installing the pinned SDK in
  an isolated venv and reproducing the exact call, so no billed step ever hit it.
- **Output-namespace collision with real M2/M3 modules (found in pre-run audit)** —
  the steps originally wrote to `users/<profile>/m2/captions.json` and
  `…/m3/curated_captions.json` — the *exact keys and filenames* the real M2/M3
  modules produce, but with an incompatible demo schema (no per-caption `filename`,
  no top-level `model`). Running M11 would silently overwrite a participant's genuine
  M2/M3 output, and a later re-run of **M4** (`m2_output["model"]`, `cap["filename"]`)
  or **M3** (`captions[0]["filename"]`) would then crash with `KeyError`. Verified
  against the M2/M3/M4 notebook source. Fix: route all three step outputs into an
  **M11-private namespace** `users/<profile>/m11/pipeline/stepN_*/` (Step 1 still
  reads real `m1/` read-only). The DAG/dependencies/lineage are unchanged; M11 is now
  self-contained and cannot pollute other modules' data. (Confirmed by re-running the
  full 3-step DAG locally on real M1 data: 3→3→3→9, and nothing written to m2/m3/m4.)

## Verified run

**Managed run verified (2026-07-14, Studio Run-All, participant profile `ky-5-34x1bx`).**
A real SageMaker Pipeline was upserted and executed end-to-end on CPU:

```
execution: av30-data-pipeline-ky-5-34x1bx/execution/3p1jfdpcp0ga  → Succeeded
  AV-Captioning       Succeeded  154s   (read real m1/selected_scenes.json)
  Data-Curation       Succeeded  153s
  Data-Augmentation   Succeeded  303s
  step compute total: 610s → ~$0.039 @ ml.m5.xlarge; wall time 634s
```

Confirmed against live S3 after the run:
- **Real M1 → M11 link:** the 9 final captions are grounded in M1's actual nuScenes
  scene descriptions (truck / construction / cyclist / crosswalk), 9/9 — not synthetic.
- **Outputs isolated:** step outputs landed only under
  `users/ky-5-34x1bx/m11/pipeline/step{1,2,3}_*/`; run record at
  `m11/pipeline_execution.json` (status Succeeded, 3/3 steps) +
  `m11/pipeline_definition.json`. SDK code uploads stayed inside `users/…/m11/`
  (no AccessDenied — `default_bucket_prefix` working).
- **No collision:** the real `m2/captions.json` (22649 B) and
  `m3/curated_captions.json` (24767 B) were left **untouched** — the private-namespace
  fix (bug #4) verified in the real environment.

Both pre-run-audit blockers (`image_scope="processing"` ValueError; m2/m3 output
collision) were fixed *before* this run, so it succeeded on the first managed
execution with no billed step wasted on a preventable failure.
