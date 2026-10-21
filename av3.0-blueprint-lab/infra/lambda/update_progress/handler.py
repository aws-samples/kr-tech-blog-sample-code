"""Lambda handler for updating module progress.

POST /sessions/{id}/progress
Updates a user's progress on a specific module in DynamoDB.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from config import MODULE_CONFIG, SESSIONS_TABLE_NAME
from errors import ApiError, api_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Boto3 clients — created at module level for connection reuse
dynamodb = boto3.resource("dynamodb")

# Valid module IDs (m0 through m12) — short back-compat ids
VALID_MODULE_IDS = {f"m{i}" for i in range(13)}

# Also accept the MODULE_CONFIG keys (module-1 through module-5)
VALID_MODULE_IDS.update(MODULE_CONFIG.keys())

# Canonical LONG ids emitted by the frontend + the notebook mark-complete cells
# (web/user/src/data/pipeline-config.ts). Kept alongside the m0..m12 short ids so
# older callers keep working.
#
# The numbers follow the blog's 8-stage order (see docs/*/PRE_LEARNING_GUIDE.md),
# which is NOT the order these modules were originally written in — that is why the
# slugs look "out of sequence" here. Listed in stage order:
VALID_MODULE_IDS.update({
    "m01-data-exploration",     # stage 1-2
    "m02-cosmos-reason",        # stage 3   captioning
    "m03-cosmos-curator",       # stage 3   curation
    "m04-opensearch",           # stage 4   search + indexing
    "m05-cosmos-transfer",      # stage 5   augmentation
    "m06-cosmos-predict",       # stage 5   scenario generation
    "m07-nerfstudio",           # stage 6   neural reconstruction
    "m08-cosmos-sft",           # stage 7   model training (LoRA SFT)
    "m09-alpamayo-vla",         # stage 7   VLA inference
    "m10-alpasim",              # stage 8   closed-loop eval
    "m11-orchestration",        # ext       SageMaker Pipelines
    "m12-hyperpod",             # ext       distributed-training scale-up
})

# Valid progress statuses
VALID_STATUSES = {"in_progress", "completed"}


@api_handler
def handler(event, context):
    """Update module progress for a user."""
    # Extract userId from path
    path_params = event.get("pathParameters") or {}
    user_id = path_params.get("id")

    if not user_id:
        raise ApiError(400, "Missing userId in path")

    # Ownership guard: the TokenAuthorizer returns a stage-wide wildcard resource,
    # so ANY valid token reaches this route for ANY {id}. Reject a write to a path
    # whose userId != the token owner (context.userId set by token_authorizer).
    authorizer_ctx = (event.get("requestContext") or {}).get("authorizer") or {}
    caller_id = authorizer_ctx.get("userId")
    if caller_id and caller_id != user_id:
        raise ApiError(403, "Token not authorized for this userId")

    # Parse request body
    body = event.get("body")
    if not body:
        raise ApiError(400, "Request body is required")

    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            raise ApiError(400, "Invalid JSON in request body")

    module_id = body.get("moduleId", "").strip()
    # Fold the frontend's hyphenated enum ("in-progress") to the stored form
    # ("in_progress"). Only the status is folded — module ids contain significant
    # hyphens (m01-data-exploration) and must not be touched.
    status = body.get("status", "").strip().replace("-", "_")

    if not module_id:
        raise ApiError(400, "Field 'moduleId' is required")
    if not status:
        raise ApiError(400, "Field 'status' is required")

    # Validate moduleId
    if module_id not in VALID_MODULE_IDS:
        raise ApiError(
            400,
            f"Invalid moduleId: {module_id}",
            details=f"Valid IDs: {sorted(VALID_MODULE_IDS)}",
        )

    # Validate status
    if status not in VALID_STATUSES:
        raise ApiError(
            400,
            f"Invalid status: {status}",
            details=f"Valid statuses: {sorted(VALID_STATUSES)}",
        )

    # Verify user exists
    table = dynamodb.Table(SESSIONS_TABLE_NAME)
    response = table.get_item(Key={"userId": user_id})
    item = response.get("Item")

    if not item:
        raise ApiError(404, f"User not found: {user_id}")

    logger.info(f"Updating progress for {user_id}: {module_id} = {status}")

    now_iso = datetime.now(timezone.utc).isoformat()

    # Build update expression
    update_expr = "SET moduleProgress.#mid = :status, lastProgressUpdate = :now"
    expr_names = {"#mid": module_id}
    expr_values = {
        ":status": status,
        ":now": now_iso,
    }

    # If in_progress, also update currentModule
    if status == "in_progress":
        update_expr += ", currentModule = :module_id"
        expr_values[":module_id"] = module_id

    table.update_item(
        Key={"userId": user_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )
    logger.info(f"Updated module progress in DynamoDB for user: {user_id}")

    return {
        "updated": True,
        "userId": user_id,
        "moduleId": module_id,
        "status": status,
    }
