"""Lambda handler for expanding session storage.

PATCH /sessions/{id}/storage
Increases the EBS volume attached to the user's SageMaker space.
Only allows additions of 50 GB or 200 GB increments.

Same fast-sync / async-continuation split as change_instance (see that handler's
docstring): the EBS resize requires delete-app -> wait -> update_space -> wait ->
create_app, which exceeds API Gateway's 29s cap. The sync path validates, issues
the delete, self-invokes, and returns fast; the async path runs the slow tail
and persists storageGB only after the app is recreated.
"""

import json
import logging
import os
import sys

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from config import (
    SAGEMAKER_DOMAIN_ID,
    SESSIONS_TABLE_NAME,
    create_app_when_ready,
    jupyterlab_resource_spec,
    safe_delete_app,
    wait_for_app_deleted,
    wait_for_space_in_service,
    DEFAULT_SPACE_STORAGE_GB,
)

from errors import ApiError, api_handler, require_own_user

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Boto3 clients — created at module level for connection reuse
sagemaker = boto3.client("sagemaker")
dynamodb = boto3.resource("dynamodb")
lambda_client = boto3.client("lambda")  # for the async self-invoke

# Allowed storage expansion increments (GB)
ALLOWED_INCREMENTS = {50, 200}

# Maximum allowed total storage (GB)
MAX_STORAGE_GB = 500

# App type for user compute (JupyterLab spaces, matching create_user)
APP_TYPE = "JupyterLab"


def handler(event, context):
    """Dispatch: async continuation vs. synchronous HTTP request."""
    if isinstance(event, dict) and event.get("_async_apply"):
        return _apply_async(event)
    return _http_handler(event, context)


@api_handler
def _http_handler(event, context):
    """Sync request path: validate, issue delete, self-invoke, return fast."""
    # Extract userId from path
    path_params = event.get("pathParameters") or {}
    user_id = path_params.get("id")

    if not user_id:
        raise ApiError(400, "Missing userId in path")

    # The TokenAuthorizer grants a stage-wide resource, so a valid token reaches this
    # route for ANY userId. Without this, a participant could act on someone else's
    # workspace by editing the path. See require_own_user for the full reasoning.
    require_own_user(event, user_id)

    # Parse request body
    body = event.get("body")
    if not body:
        raise ApiError(400, "Request body is required")

    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            raise ApiError(400, "Invalid JSON in request body")

    add_gb = body.get("addGB")
    if add_gb is None:
        raise ApiError(400, "Field 'addGB' is required")

    # Convert Decimal or string to int
    try:
        add_gb = int(add_gb)
    except (ValueError, TypeError):
        raise ApiError(400, "Field 'addGB' must be a number")

    if add_gb not in ALLOWED_INCREMENTS:
        raise ApiError(
            400,
            f"Invalid addGB value: {add_gb}",
            details=f"Allowed values: {sorted(ALLOWED_INCREMENTS)}",
        )

    # Retrieve current session
    table = dynamodb.Table(SESSIONS_TABLE_NAME)
    response = table.get_item(Key={"userId": user_id})
    item = response.get("Item")

    if not item:
        raise ApiError(404, f"User not found: {user_id}")

    space_name = item.get("spaceName", f"{user_id}-space")
    # Preserve the user's current instance type when recreating the app, so a
    # storage expansion does not silently revert a GPU box (and its GPU image
    # + notebook-sync LCC) back to the CPU default.
    instance_type = item.get("instanceType", "ml.t3.medium")

    # Verify the space exists, and take the CURRENT volume size from it.
    space_info = sagemaker.describe_space(
        DomainId=SAGEMAKER_DOMAIN_ID,
        SpaceName=space_name,
    )
    logger.info(f"Current space status: {space_info.get('Status')}")

    # Size from the LIVE volume, not from DynamoDB.
    #
    # DynamoDB is a record of what this Lambda last did, and it is no longer the only thing
    # that can change the volume: participants now hold a scoped sagemaker:UpdateSpace on
    # their own private space (SageMakerOwnPrivateSpaceUpdate in
    # infra/av30_constructs/sagemaker.py), which is the same API used below. A participant
    # who resizes from a notebook leaves storageGB stale, and adding to a stale base either
    # overshoots MAX_STORAGE_GB silently or, worse, SHRINKS the volume — which AWS rejects,
    # failing the whole resize. describe_space is authoritative; DDB and the provisioning
    # default are only fallbacks for a space that predates this field.
    current_storage = int(
        space_info.get("SpaceSettings", {})
        .get("SpaceStorageSettings", {})
        .get("EbsStorageSettings", {})
        .get("EbsVolumeSizeInGb")
        or item.get("storageGB")
        or DEFAULT_SPACE_STORAGE_GB
    )

    # Validate new total does not exceed maximum
    new_size_gb = current_storage + add_gb
    if new_size_gb > MAX_STORAGE_GB:
        raise ApiError(
            400,
            f"Storage expansion would exceed maximum of {MAX_STORAGE_GB} GB",
            details=f"Current: {current_storage} GB, requested addition: {add_gb} GB",
        )

    logger.info(
        f"Expanding storage for {user_id}: {current_storage} GB -> {new_size_gb} GB"
    )

    # Issue the delete SYNCHRONOUSLY (EBS resize requires the app stopped first;
    # also flips the old app to Deleting before we return, so the frontend
    # poller can't latch onto the pre-resize app).
    deleting = safe_delete_app(sagemaker, SAGEMAKER_DOMAIN_ID, space_name, APP_TYPE)
    if deleting:
        logger.info(f"Issued delete before storage resize for space: {space_name}")
    else:
        logger.warning(f"No live app for space: {space_name}, proceeding")

    # Hand off the slow tail (wait -> resize -> wait -> recreate -> DDB) async.
    lambda_client.invoke(
        FunctionName=context.invoked_function_arn,
        InvocationType="Event",
        Payload=json.dumps(
            {
                "_async_apply": True,
                "userId": user_id,
                "spaceName": space_name,
                "newSizeGB": new_size_gb,
                "instanceType": instance_type,
            }
        ).encode("utf-8"),
    )
    logger.info(f"Dispatched async storage resize for {user_id} -> {new_size_gb} GB")

    return {
        "updated": True,
        "async": True,
        "previousSizeGB": current_storage,
        "newSizeGB": new_size_gb,
    }


def _apply_async(event):
    """Slow continuation: wait for delete, resize the EBS volume, recreate app.

    Not @api_handler-decorated (no HTTP caller). On failure it raises, failing
    the async invocation; the app is left Failed for GET /app-status to surface.
    """
    user_id = event["userId"]
    space_name = event["spaceName"]
    new_size_gb = int(event["newSizeGB"])
    instance_type = event.get("instanceType", "ml.t3.medium")

    logger.info(f"[async] Resizing storage for {user_id} -> {new_size_gb} GB")

    # The delete was already issued on the request path; wait for it to finish.
    wait_for_app_deleted(sagemaker, SAGEMAKER_DOMAIN_ID, space_name, APP_TYPE)

    # Update space with new storage size.
    sagemaker.update_space(
        DomainId=SAGEMAKER_DOMAIN_ID,
        SpaceName=space_name,
        SpaceSettings={
            "SpaceStorageSettings": {
                "EbsStorageSettings": {
                    "EbsVolumeSizeInGb": new_size_gb,
                }
            }
        },
    )
    logger.info(f"[async] Updated space {space_name} storage to {new_size_gb} GB")

    # Wait for the space to return to InService after the resize before
    # recreating the app (otherwise create_app 502s on first try).
    wait_for_space_in_service(sagemaker, SAGEMAKER_DOMAIN_ID, space_name)

    # Recreate the app — preserve the instance type, matching CPU/GPU image, and
    # notebook-sync LCC. create_app_when_ready retries while the just-resized EBS
    # volume finishes returning to Available.
    create_app_when_ready(
        sagemaker,
        SAGEMAKER_DOMAIN_ID,
        space_name,
        jupyterlab_resource_spec(instance_type),
        APP_TYPE,
    )
    logger.info(f"[async] Recreated {APP_TYPE} app for space: {space_name}")

    # Persist only after the recreate succeeds.
    table = dynamodb.Table(SESSIONS_TABLE_NAME)
    table.update_item(
        Key={"userId": user_id},
        # Same reasoning as change_instance: this recreated the app, so an appStatus
        # of "stopped" left over from an admin Terminate would make list_sessions
        # report the now-running box as offline and cost it at $0.00.
        UpdateExpression="SET storageGB = :size REMOVE appStatus, terminatedAt",
        ExpressionAttributeValues={":size": new_size_gb},
    )
    logger.info(f"[async] Storage resize complete for {user_id}: {new_size_gb} GB")
    return {"applied": True, "userId": user_id, "newSizeGB": new_size_gb}
