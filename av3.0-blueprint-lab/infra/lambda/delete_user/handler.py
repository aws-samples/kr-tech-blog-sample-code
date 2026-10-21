"""Lambda handler for permanently deleting a workshop user.

DELETE /users/{id}
Tears down everything create_user provisioned, in dependency order:
  1. JupyterLab app  (must be gone before the space can be deleted)
  2. Space           (must be gone before the user profile can be deleted)
  3. User profile
  4. OpenSearch Serverless collection + policies created by M4 (if any)
  5. S3 workspace files under users/{userId}/
  6. DynamoDB session row

This is a HARD delete and cannot be undone. Every SageMaker step is idempotent
(ResourceNotFound is swallowed) so a retry after a partial failure resumes cleanly.

Split into a fast synchronous request path and an asynchronous continuation, for
the same reason change_instance is:

* Sync path (`_http_handler`): look the user up, issue delete_app (instant,
  async server-side), mark the row `deleting`, self-invoke with
  InvocationType='Event' and return immediately.

* Async path (`_delete_async`): the three sequential SageMaker waits (app 240s +
  space 180s + profile 180s) plus AOSS/S3/DynamoDB. Needs the function's full
  timeout, which is why api.py gives it 15 minutes.

MEASURED (ap-northeast-2, 2026-09-26) — why this had to change: the teardown ran
entirely on the request path and took 32.5s for a user whose GPU app was running,
while API Gateway's REST integration is capped at 29s. The browser got a 504 with
no CORS headers 4s before the Lambda succeeded, so a COMPLETE, CORRECT delete was
reported to the admin as a failure. They then clicked Delete again three times and
got "404 User not found" each time — the row was already gone. An earlier delete of
a user with no running app finished in 22.5s and looked fine, so the bug only
appeared once a real workshop instance was up: the more expensive the resource, the
more likely the delete looks broken.

`status = "deleting"` is load-bearing beyond display: token_authorizer requires
`status == "active"`, so writing it revokes the participant's dashboard token the
moment teardown starts.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from config import (
    SAGEMAKER_DOMAIN_ID,
    SESSIONS_TABLE_NAME,
    USER_BUCKET_NAME,
    aoss_collection_name,
    safe_delete_app,
)
from errors import ApiError, api_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Boto3 clients — created at module level for connection reuse
sagemaker = boto3.client("sagemaker")
s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
aoss = boto3.client("opensearchserverless")
lambda_client = boto3.client("lambda")  # for the async self-invoke

# App type for user compute (JupyterLab spaces, matching create_user).
APP_TYPE = "JupyterLab"

# How long a row may sit in `deleting` before a repeat Delete is allowed to dispatch
# a fresh teardown. Must exceed the async path's worst case (app 240s + space 180s +
# profile 180s = 600s) so a healthy in-flight delete is never duplicated, and stay
# under the function's 15-min timeout so a genuinely dead invocation is recoverable
# from the UI instead of needing a console visit.
STALE_DELETE_SECONDS = 720


def cleanup_aoss(user_id: str) -> dict:
    """Best-effort teardown of the OpenSearch Serverless resources M4 creates.

    Deletes the collection (by id, after lookup) then its three policies
    (encryption `-enc`, network `-net`, data-access `-access`). Fully idempotent:
    a user who never ran M4 has none of these, and every "not found" is ignored.

    Best-effort — never raises, so an AOSS hiccup can't block the SageMaker/S3/DDB
    teardown. But it now RECORDS incompleteness in the response (`complete` +
    `reasons`) instead of silently swallowing it, so a caller/sweeper can tell a
    collection may still be billing. The collection name is derived with the
    SHARED sanitizer (aoss_collection_name) so it byte-matches whatever M4 named
    it — the old raw `user_id[:8]` diverged for uppercase/leading-digit/hyphen
    ids and left orphans.

    NOTE (async): delete_collection returns immediately; the collection enters
    DELETING and its 3 policies cannot be dropped until it is fully gone (they
    raise ConflictException here). That is EXPECTED on a fresh delete — the
    teardown.sh global AOSS sweep is the backstop that reaps the policies later.
    So `collectionDeleted: True` means "deletion queued", not "confirmed gone".
    """
    name = aoss_collection_name(user_id)
    result = {
        "collection": name,
        "collectionFound": False,
        "collectionDeleted": False,
        "policiesDeleted": [],
        "complete": True,
        "reasons": [],
    }

    def _why(exc: Exception) -> str:
        """Identify a failure usefully.

        type(exc).__name__ is almost always the string "ClientError" for a botocore
        failure, which tells an operator nothing: an AccessDeniedException (needs a
        policy fix, the collection will bill forever) and a ConflictException (expected
        while the collection is DELETING, self-heals) both reported identically. Prefer
        the AWS error CODE.
        """
        code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        return code or type(exc).__name__

    def _absent(exc: Exception) -> bool:
        """True when the resource simply does not exist.

        "Not found" is the SUCCESS case for a teardown: there is nothing left to bill.
        Most participants never reach M4, so no collection and no policies were ever
        created and all three deletes raise ResourceNotFoundException. Counting that as
        `complete: False` fired the admin UI's orphan warning on EVERY deletion — and a
        warning that always fires is one nobody reads, which defeats the point of
        surfacing genuine orphans at all. Found by smoke-testing a user who never ran M4.
        """
        return _why(exc) in ("ResourceNotFoundException", "NotFoundException", "404")

    # 1) Delete the collection (needs the id from batch_get_collection).
    try:
        resp = aoss.batch_get_collection(names=[name])
        details = resp.get("collectionDetails", [])
        if details:
            result["collectionFound"] = True
            coll_id = details[0]["id"]
            aoss.delete_collection(id=coll_id)  # async: enters DELETING
            result["collectionDeleted"] = True  # QUEUED, not confirmed gone
            logger.info(f"Queued delete of aoss collection {name} (id={coll_id})")
        else:
            logger.info(f"No aoss collection {name} (user never ran M4)")
    except Exception as e:  # noqa: BLE001 — best-effort, but now RECORDED
        if _absent(e):
            logger.info(f"No aoss collection {name} (user never ran M4)")
        else:
            result["complete"] = False
            result["reasons"].append(f"collection:{_why(e)}")
            logger.warning(f"aoss collection cleanup for {name}: {e}")

    # 2) Delete the security + access policies. Names/types match M4.
    for pname, ptype, api in (
        (f"{name}-enc", "encryption", aoss.delete_security_policy),
        (f"{name}-net", "network", aoss.delete_security_policy),
        (f"{name}-access", "data", aoss.delete_access_policy),
    ):
        try:
            api(name=pname, type=ptype)
            result["policiesDeleted"].append(pname)
            logger.info(f"Deleted aoss {ptype} policy {pname}")
        except Exception as e:  # noqa: BLE001 — best-effort
            # ResourceNotFoundException means the policy was never created (the
            # common case — the user never ran M4), so there is nothing to bill and
            # nothing to report. ConflictException is EXPECTED while the collection
            # is still DELETING (it still references the policy) and IS reported, so
            # the admin knows the teardown.sh sweep still has work to do.
            if _absent(e):
                logger.info(f"No aoss {ptype} policy {pname} (nothing to clean up)")
            else:
                result["complete"] = False
                result["reasons"].append(f"{pname}:{_why(e)}")
                logger.warning(f"aoss policy cleanup for {pname}: {e}")

    return result


def wait_for_app_deleted(space_name: str, max_wait: int = 240) -> None:
    """Poll DescribeApp until the app is gone (Deleted/Failed or ResourceNotFound)."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            resp = sagemaker.describe_app(
                DomainId=SAGEMAKER_DOMAIN_ID,
                SpaceName=space_name,
                AppType=APP_TYPE,
                AppName="default",
            )
            if resp.get("Status") in ("Deleted", "Failed"):
                return
        except sagemaker.exceptions.ResourceNotFound:
            return
        time.sleep(5)
    raise ApiError(504, "Timed out waiting for the app to shut down")


def wait_for_space_deleted(space_name: str, max_wait: int = 180) -> None:
    """Poll DescribeSpace until the space no longer exists."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            sagemaker.describe_space(
                DomainId=SAGEMAKER_DOMAIN_ID, SpaceName=space_name
            )
        except sagemaker.exceptions.ResourceNotFound:
            return
        time.sleep(5)
    raise ApiError(504, "Timed out waiting for the space to delete")


def wait_for_profile_deleted(user_id: str, max_wait: int = 180) -> None:
    """Poll DescribeUserProfile until the profile no longer exists."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            sagemaker.describe_user_profile(
                DomainId=SAGEMAKER_DOMAIN_ID, UserProfileName=user_id
            )
        except sagemaker.exceptions.ResourceNotFound:
            return
        time.sleep(5)
    raise ApiError(504, "Timed out waiting for the user profile to delete")


def delete_user_workspace(user_id: str) -> int:
    """Delete all S3 objects under the user's workspace prefix.

    Mirrors reset_workspace.delete_user_workspace. Returns objects deleted.
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deleting_age_seconds(started_iso) -> float:
    """Seconds since a teardown was marked in-flight; +inf when unknown.

    Unknown (missing/unparseable timestamp) returns infinity ON PURPOSE: that means
    "treat as stale, allow a retry". The opposite default would make a row whose
    timestamp we cannot read permanently undeletable from the UI.
    """
    if not started_iso:
        return float("inf")
    try:
        started = datetime.fromisoformat(str(started_iso))
    except ValueError:
        return float("inf")
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - started).total_seconds()


def _record_delete_failure(user_id: str, message: str) -> None:
    """Leave the row visible with the reason, so a failed teardown is not silent.

    Never raises: it is called from the async path's except block, and a failure to
    record a failure must not replace it with a different one.
    """
    try:
        dynamodb.Table(SESSIONS_TABLE_NAME).update_item(
            Key={"userId": user_id},
            UpdateExpression="SET #s = :s, lastDeleteError = :e",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "delete-failed", ":e": message[:900]},
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"Could not record delete failure for {user_id}: {e}")


def handler(event, context):
    """Dispatch: async continuation vs. synchronous HTTP request."""
    if isinstance(event, dict) and event.get("_async_delete"):
        return _delete_async(event)
    return _http_handler(event, context)


@api_handler
def _http_handler(event, context):
    """Sync request path: validate, issue the app delete, self-invoke, return fast."""
    path_params = event.get("pathParameters") or {}
    user_id = path_params.get("id") or path_params.get("userId")

    if not user_id:
        raise ApiError(400, "Missing userId in path")

    logger.info(f"Deleting user: {user_id}")

    # Verify the user exists in DynamoDB and grab the space name.
    table = dynamodb.Table(SESSIONS_TABLE_NAME)
    response = table.get_item(Key={"userId": user_id})
    item = response.get("Item")

    if not item:
        raise ApiError(404, f"User not found: {user_id}")

    space_name = item.get("spaceName", f"{user_id}-space")

    # Repeat click while a teardown is already running: report it instead of starting a
    # second one. Two concurrent teardowns race on the same space — the loser calls
    # delete_space on a space already DELETING, which is not a ResourceNotFound and so
    # would surface as a hard failure on a delete that is in fact succeeding.
    if item.get("status") == "deleting":
        age = _deleting_age_seconds(item.get("deleteStartedAt"))
        if age < STALE_DELETE_SECONDS:
            logger.info(f"Delete already in progress for {user_id} ({age:.0f}s ago)")
            return {
                "deleted": False,
                "async": True,
                "alreadyInProgress": True,
                "userId": user_id,
            }
        logger.warning(
            f"Previous delete for {user_id} started {age:.0f}s ago and never "
            "finished; dispatching a fresh teardown"
        )

    # Issue the app delete SYNCHRONOUSLY (instant, async server-side) so the app flips
    # to Deleting before we return. safe_delete_app tolerates "no app" and "app
    # previously failed + auto-deleted" (ValidationException).
    app_was_running = safe_delete_app(
        sagemaker, SAGEMAKER_DOMAIN_ID, space_name, APP_TYPE
    )
    if app_was_running:
        logger.info(f"Issued app delete for space: {space_name}")
    else:
        logger.warning(f"No live app for space: {space_name}, proceeding")

    # Mark the row before handing off. Also revokes the participant's dashboard token
    # (token_authorizer requires status == "active"), which is what we want: their
    # workspace is being torn down. lastDeleteError is cleared so a retry after a
    # failure does not keep showing the old reason.
    table.update_item(
        Key={"userId": user_id},
        UpdateExpression=(
            "SET #s = :s, deleteStartedAt = :t REMOVE lastDeleteError"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "deleting", ":t": _now_iso()},
    )

    lambda_client.invoke(
        FunctionName=context.invoked_function_arn,
        InvocationType="Event",
        Payload=json.dumps(
            {
                "_async_delete": True,
                "userId": user_id,
                "spaceName": space_name,
            }
        ).encode("utf-8"),
    )
    logger.info(f"Dispatched async teardown for {user_id}")

    return {
        "deleted": False,
        "async": True,
        "userId": user_id,
        "appWasRunning": app_was_running,
    }


def _delete_async(event):
    """Slow continuation: wait out the SageMaker deletes, then AOSS, S3 and the row.

    Not @api_handler-decorated: there is no HTTP caller to answer.

    DELIBERATELY DOES NOT RAISE. Lambda retries a failed async invocation twice by
    default, and a retry mid-teardown would call delete_space/delete_user_profile
    against resources already in DELETING — not a ResourceNotFound, so it would fail
    differently on every attempt. A handled failure returns normally (no retry) and is
    recorded on the row as `delete-failed` + lastDeleteError, where the admin can see
    it and press Delete again: every step swallows ResourceNotFound, so the retry
    resumes from wherever the first attempt stopped.
    """
    user_id = event["userId"]
    space_name = event["spaceName"]

    logger.info(f"[async] Tearing down {user_id}")

    try:
        return _teardown(user_id, space_name)
    except Exception as e:  # noqa: BLE001 — see docstring
        logger.error(f"[async] Teardown failed for {user_id}: {e}")
        _record_delete_failure(user_id, f"{type(e).__name__}: {e}")
        return {"deleted": False, "userId": user_id, "error": str(e)}


def _teardown(user_id: str, space_name: str) -> dict:
    """The teardown proper, in dependency order. Called only from _delete_async."""
    table = dynamodb.Table(SESSIONS_TABLE_NAME)

    # 1. The app delete was already issued on the request path; wait for it to finish.
    wait_for_app_deleted(space_name)

    # 2. Delete the space (only possible once the app is gone).
    try:
        sagemaker.delete_space(
            DomainId=SAGEMAKER_DOMAIN_ID, SpaceName=space_name
        )
        logger.info(f"Deleting space: {space_name}")
        wait_for_space_deleted(space_name)
    except sagemaker.exceptions.ResourceNotFound:
        logger.warning(f"No space: {space_name}, proceeding")

    # 3. Delete the user profile (only possible once the space is gone).
    try:
        sagemaker.delete_user_profile(
            DomainId=SAGEMAKER_DOMAIN_ID, UserProfileName=user_id
        )
        logger.info(f"Deleting user profile: {user_id}")
        wait_for_profile_deleted(user_id)
    except sagemaker.exceptions.ResourceNotFound:
        logger.warning(f"No user profile: {user_id}, proceeding")

    # 4. Delete the OpenSearch Serverless collection + policies that M4 may have
    #    created for this user (best-effort, idempotent — no-op if M4 never ran).
    aoss_result = cleanup_aoss(user_id)

    # 5. Delete the user's S3 workspace files.
    files_deleted = delete_user_workspace(user_id)
    logger.info(f"Deleted {files_deleted} S3 objects for user: {user_id}")

    # An orphaned AOSS collection bills at a 2-OCU floor indefinitely, so incomplete
    # cleanup must not vanish with the row. It used to ride back in the HTTP response as
    # a warning flash; on the async path there is no response to carry it, so the ROW is
    # the warning — kept as delete-failed, with Delete re-running the (idempotent) sweep.
    #
    # ConflictException is EXCLUDED because it is the NORMAL outcome: delete_collection is
    # async, and the three policies cannot be dropped until the collection leaves DELETING.
    # Treating it as a failure would leave a ghost row after every delete of a participant
    # who ran M4 — an alarm that always fires is one nobody reads. teardown.sh's global
    # AOSS sweep is the documented backstop for exactly that case.
    blocking = [r for r in aoss_result["reasons"] if "ConflictException" not in r]
    if blocking:
        reason = (
            f"OpenSearch Serverless cleanup incomplete ({', '.join(blocking)}). "
            f'Collection "{aoss_result["collection"]}" may still exist and bill. '
            "Everything else was deleted; press Delete again to retry the sweep."
        )
        logger.error(f"[async] {user_id}: {reason}")
        _record_delete_failure(user_id, reason)
        return {
            "deleted": False,
            "userId": user_id,
            "filesDeleted": files_deleted,
            "aoss": aoss_result,
            "error": reason,
        }
    if aoss_result["reasons"]:
        logger.warning(
            f"[async] {user_id}: AOSS policies still referenced by the DELETING "
            f"collection ({', '.join(aoss_result['reasons'])}); teardown.sh sweeps them"
        )

    # 6. Delete the DynamoDB session row (last, so a mid-teardown retry can
    #    still look the user up and resume).
    table.delete_item(Key={"userId": user_id})
    logger.info(f"Deleted DynamoDB row for user: {user_id}")

    return {
        "deleted": True,
        "userId": user_id,
        "filesDeleted": files_deleted,
        "aoss": aoss_result,
    }
