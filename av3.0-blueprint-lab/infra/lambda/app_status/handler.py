"""Lambda handler for reporting a user's live SageMaker app status.

GET /sessions/{id}/app-status  (Token auth)
Returns the REAL JupyterLab app health so the participant dashboard can show
whether the workspace is starting, running, or failed to launch (e.g.
EC2InsufficientCapacityError on ml.g5.12xlarge) — separate from the static
per-module progress. Read-only: no mutation.
"""

import logging
import os
import sys

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from config import SAGEMAKER_DOMAIN_ID, SESSIONS_TABLE_NAME, is_gpu_instance
from errors import ApiError, api_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Boto3 clients — created at module level for connection reuse
sagemaker = boto3.client("sagemaker")
dynamodb = boto3.resource("dynamodb")

APP_TYPE = "JupyterLab"

# Substring that identifies the AWS capacity-shortage failure, so the UI can
# surface an actionable "try an alternative instance" hint.
_CAPACITY_MARKER = "InsufficientCapacity"


@api_handler
def handler(event, context):
    """Return the live JupyterLab app status for a user."""
    path_params = event.get("pathParameters") or {}
    user_id = path_params.get("id") or path_params.get("userId")

    if not user_id:
        raise ApiError(400, "Missing userId in path")

    # Ownership guard: a valid token reaches this route for ANY {id} (the
    # TokenAuthorizer returns a stage-wide resource). Reject reads of another
    # user's live status/progress.
    authorizer_ctx = (event.get("requestContext") or {}).get("authorizer") or {}
    caller_id = authorizer_ctx.get("userId")
    if caller_id and caller_id != user_id:
        raise ApiError(403, "Token not authorized for this userId")

    # Resolve the space name from DynamoDB (same source create_user wrote).
    table = dynamodb.Table(SESSIONS_TABLE_NAME)
    response = table.get_item(Key={"userId": user_id})
    item = response.get("Item")

    if not item:
        raise ApiError(404, f"User not found: {user_id}")

    space_name = item.get("spaceName", f"{user_id}-space")
    ddb_instance = item.get("instanceType", "ml.t3.medium")

    # A failed instance change recovers by restoring the PREVIOUS type and relaunching
    # (change_instance._restore_previous), so the live app reads InService and looks
    # perfectly healthy — the participant would otherwise just see their requested change
    # silently not happen. change_instance clears this on the next success.
    change_error = item.get("lastInstanceChangeError")

    # The space's ACTUAL EBS volume size, for the dashboard to display.
    #
    # The participant dashboard used to render a per-module literal from
    # web/user/src/data/pipeline-config.ts, which was never the provisioned volume: a
    # participant saw "100 GB" in the panel while Studio showed 5 GB for the same space, and
    # the +50/+200 arithmetic was computed against the fiction. Returning the real number
    # here is what lets the panel show the volume instead of a wish.
    #
    # Best-effort: on any failure return None and let the UI say "unknown" rather than print
    # a guess. This handler's role has sagemaker:DescribeSpace (api.py).
    storage_gb = None
    try:
        space = sagemaker.describe_space(
            DomainId=SAGEMAKER_DOMAIN_ID,
            SpaceName=space_name,
        )
        storage_gb = (
            space.get("SpaceSettings", {})
            .get("SpaceStorageSettings", {})
            .get("EbsStorageSettings", {})
            .get("EbsVolumeSizeInGb")
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"DescribeSpace failed for {space_name}: {exc}")

    # Describe the app. A space with no app (never launched, or previous app
    # failed and was auto-deleted) is a normal state — report "NotFound" rather
    # than erroring, so the UI can prompt the user to open the workspace.
    try:
        resp = sagemaker.describe_app(
            DomainId=SAGEMAKER_DOMAIN_ID,
            SpaceName=space_name,
            AppType=APP_TYPE,
            AppName="default",
        )
    except sagemaker.exceptions.ResourceNotFound:
        return {
            "userId": user_id,
            "name": item.get("name"),
            "status": "NotFound",
            "instanceType": ddb_instance,
            "failureReason": None,
            "isGpu": is_gpu_instance(ddb_instance),
            "capacityError": False,
            "moduleProgress": item.get("moduleProgress", {}),
            "lastInstanceChangeError": change_error,
            # The space (and its volume) outlive the app, so this is known even here.
            "storageGB": storage_gb,
        }

    status = resp.get("Status")  # Pending | InService | Deleting | Deleted | Failed
    failure_reason = resp.get("FailureReason")
    instance_type = resp.get("ResourceSpec", {}).get("InstanceType", ddb_instance)
    capacity_error = bool(failure_reason and _CAPACITY_MARKER in failure_reason)

    return {
        "userId": user_id,
        "name": item.get("name"),
        "status": status,
        "instanceType": instance_type,
        "failureReason": failure_reason,
        "isGpu": is_gpu_instance(instance_type),
        "capacityError": capacity_error,
        "moduleProgress": item.get("moduleProgress", {}),
        "lastInstanceChangeError": change_error,
        "storageGB": storage_gb,
    }
