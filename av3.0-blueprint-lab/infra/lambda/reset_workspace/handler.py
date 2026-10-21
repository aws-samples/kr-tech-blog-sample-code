"""Lambda handler for resetting a user's workspace.

POST /users/{id}/reset
Deletes the user's S3 workspace files, re-copies notebook templates,
and resets module progress in DynamoDB.
"""

import logging
import os
import sys

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from config import (
    NOTEBOOK_TEMPLATES_PREFIX,
    SESSIONS_TABLE_NAME,
    SHARED_BUCKET_NAME,
    USER_BUCKET_NAME,
    write_progress_env,
)
from errors import ApiError, api_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Boto3 clients — created at module level for connection reuse
s3 = boto3.client("s3")
# Read-only: used at the end to report whether the reset is visible yet.
sagemaker = boto3.client("sagemaker")
dynamodb = boto3.resource("dynamodb")


def delete_user_workspace(user_id: str) -> int:
    """Delete all S3 objects under the user's workspace prefix.

    Returns the number of objects deleted.
    """
    prefix = f"users/{user_id}/"
    deleted_count = 0

    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=USER_BUCKET_NAME, Prefix=prefix)

    for page in pages:
        objects = page.get("Contents", [])
        if not objects:
            continue

        delete_keys = [{"Key": obj["Key"]} for obj in objects]
        s3.delete_objects(
            Bucket=USER_BUCKET_NAME, Delete={"Objects": delete_keys, "Quiet": True}
        )
        deleted_count += len(delete_keys)

    return deleted_count


def copy_notebook_templates(user_id: str) -> int:
    """Copy notebook templates from shared bucket to user workspace.

    Returns the number of files copied.
    """
    copied_count = 0
    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(
        Bucket=SHARED_BUCKET_NAME, Prefix=NOTEBOOK_TEMPLATES_PREFIX
    )

    for page in pages:
        for obj in page.get("Contents", []):
            source_key = obj["Key"]
            relative_path = source_key[len(NOTEBOOK_TEMPLATES_PREFIX) :]
            if not relative_path:
                continue

            dest_key = f"users/{user_id}/{relative_path}"
            copy_source = {"Bucket": SHARED_BUCKET_NAME, "Key": source_key}

            s3.copy_object(
                CopySource=copy_source,
                Bucket=USER_BUCKET_NAME,
                Key=dest_key,
            )
            copied_count += 1

    return copied_count


@api_handler
def handler(event, context):
    """Reset a user's workspace to initial state."""
    # Extract userId from path parameters
    path_params = event.get("pathParameters") or {}
    user_id = path_params.get("id") or path_params.get("userId")

    if not user_id:
        raise ApiError(400, "userId path parameter is required")

    logger.info(f"Resetting workspace for user: {user_id}")

    # Validate user exists in DynamoDB
    table = dynamodb.Table(SESSIONS_TABLE_NAME)
    response = table.get_item(Key={"userId": user_id})

    if "Item" not in response:
        raise ApiError(404, f"User not found: {user_id}")

    # Delete existing workspace files
    deleted_count = delete_user_workspace(user_id)
    logger.info(f"Deleted {deleted_count} objects from workspace: {user_id}")

    # Re-copy notebook templates
    copied_count = copy_notebook_templates(user_id)
    logger.info(f"Copied {copied_count} template files for user: {user_id}")

    # Rewrite the progress credentials. delete_user_workspace above cleared the WHOLE
    # users/<id>/ prefix, which includes .av30-progress.env — and re-copying templates does
    # not restore it, because it lives under notebook-templates/ for nobody. Without this
    # the reset participant's notebooks all still SUCCEED while every mark-complete cell
    # silently no-ops, so their dashboard stays grey for the rest of the workshop and both
    # sides debug the wrong thing.
    #
    # This is the same omission config.py's write_progress_env docstring records happening
    # once already in bulk_provision, where bulk-provisioned participants had no progress
    # tracking at all. Re-staging notebooks is exactly what Reset is for, so it has to
    # restore everything provisioning wrote.
    item = response["Item"]
    token = item.get("participantToken", "")
    if token and write_progress_env(
        s3, USER_BUCKET_NAME, user_id, token, os.environ.get("API_URL", "")
    ):
        logger.info(f"Rewrote progress env for {user_id}")
    else:
        logger.warning(
            f"No progress env rewritten for {user_id} "
            f"(token present={bool(token)}); their dashboard will not update"
        )

    # Reset module progress in DynamoDB
    table.update_item(
        Key={"userId": user_id},
        UpdateExpression="SET moduleProgress = :empty, lastResetAt = :now",
        ExpressionAttributeValues={
            ":empty": {},
            ":now": __import__("datetime")
            .datetime.now(__import__("datetime").timezone.utc)
            .isoformat(),
        },
    )
    logger.info(f"Reset module progress for user: {user_id}")

    # Is there a RUNNING app? This determines whether the reset is visible yet.
    #
    # Everything above happened in S3. The participant's JupyterLab home is populated by the
    # notebook-sync lifecycle config, which runs ONLY at app start — so a participant whose
    # app is already up still sees the files they had before this call, and their kernels are
    # still alive (nothing here stops them). Reporting "Workspace reset successfully" without
    # saying that led an admin to Reset a participant, see no change, and reasonably conclude
    # the reset had failed.
    app_running = False
    try:
        resp = sagemaker.describe_app(
            DomainId=SAGEMAKER_DOMAIN_ID,
            SpaceName=item.get("spaceName", f"{user_id}-space"),
            AppType="JupyterLab",
            AppName="default",
        )
        app_running = resp.get("Status") in ("Pending", "InService")
    except Exception as exc:  # noqa: BLE001 — includes ResourceNotFound (no app: normal)
        logger.info(f"No live app for {user_id}: {exc}")

    return {
        "userId": user_id,
        "message": "Workspace reset successfully",
        "filesDeleted": deleted_count,
        "filesCopied": copied_count,
        "appRunning": app_running,
        "note": (
            "The participant's workspace is still running, so it has the OLD files and its "
            "kernels are still holding any GPU memory. The new files arrive only when the "
            "app restarts (the notebook-sync lifecycle config runs at app start): have them "
            "use Stop space then Run space in SageMaker Studio, or terminate the session "
            "from the Sessions tab and let them press Start Workspace."
            if app_running else
            "No app is running, so the participant will get the fresh files the next time "
            "they start their workspace."
        ),
    }
