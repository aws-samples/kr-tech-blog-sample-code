"""AV 3.0 Blueprint Lab — participant progress ping (shared helper).

Each pipeline notebook's FINAL cell calls mark_complete("<canonical-module-id>")
to flip that module's node on the participant dashboard. Best-effort and
NON-FATAL: a failed ping must NEVER fail the module (the notebook already did the
real work by the time this runs). Skips silently when run outside a provisioned
workspace (e.g. locally), where the env vars below are absent.

Env vars are injected by the JupyterLab notebook-sync lifecycle config at app
launch, sourced from the participant's own users/<id>/.av30-progress.env:
  AV30_API_URL         e.g. https://<api>.execute-api.us-west-2.amazonaws.com/prod
  AV30_PROGRESS_TOKEN  the participant's X-Api-Key token
  USER_PROFILE         the participant userId (== the {id} path segment)

Canonical module ids (must match web/user/src/data/pipeline-config.ts):
(numbered in the blog's 8-stage order, which is NOT the order they were written)
  M1  -> m01-data-exploration   (stage 1-2  explore)
  M2  -> m02-cosmos-reason      (stage 3    captioning)
  M3  -> m03-cosmos-curator     (stage 3    curation)
  M4  -> m04-opensearch         (stage 4    search + indexing)
  M5  -> m05-cosmos-transfer    (stage 5    weather augmentation)
  M6  -> m06-cosmos-predict     (stage 5    scenario generation)
  M7  -> m07-nerfstudio         (stage 6    neural reconstruction)
  M8  -> m08-cosmos-sft         (stage 7    LoRA SFT training)
  M9  -> m09-alpamayo-vla       (stage 7    VLA inference)
  M10 -> m10-alpasim            (stage 8    closed-loop eval)
  M11 -> m11-orchestration      (ext        SageMaker Pipelines)
  M12 -> m12-hyperpod           (ext        distributed-training scale-up)
"""
import os


def mark_complete(module_id, timeout=5.0):
    """POST {moduleId, status:"completed"} for this participant. Returns True on
    success, False otherwise (never raises). Re-running a notebook re-POSTs the
    same value — idempotent, harmless."""
    api = os.environ.get("AV30_API_URL", "").strip().rstrip("/")
    token = os.environ.get("AV30_PROGRESS_TOKEN", "").strip()
    profile = os.environ.get("USER_PROFILE", "").strip()
    if not (api and token and profile):
        print(f"[progress] skipped — not in a provisioned workspace; "
              f"'{module_id}' not marked on the dashboard.")
        return False
    try:
        import requests
        resp = requests.post(
            f"{api}/sessions/{profile}/progress",
            json={"moduleId": module_id, "status": "completed"},
            headers={"X-Api-Key": token},
            timeout=timeout,
        )
        if resp.status_code < 300:
            print(f"[progress] '{module_id}' marked complete on your dashboard.")
            return True
        print(f"[progress] dashboard update skipped (HTTP {resp.status_code}) — "
              f"the module still completed successfully.")
        return False
    except Exception as e:  # noqa: BLE001 — best-effort; never fail the module
        print(f"[progress] dashboard update skipped ({type(e).__name__}) — "
              f"the module still completed successfully.")
        return False
