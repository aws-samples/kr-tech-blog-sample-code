"""Lambda handler for bulk user provisioning.

POST /users/bulk
Parses a base64-encoded CSV of users and provisions them in parallel
using ThreadPoolExecutor (max 20 concurrent).
"""

import base64
import csv
import io
import json
import logging
import os
import random
import re
import string
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from config import (
    AWS_REGION,
    NOTEBOOK_TEMPLATES_PREFIX,
    PRESIGNED_URL_EXPIRY,
    SAGEMAKER_DOMAIN_ID,
    SESSIONS_TABLE_NAME,
    SHARED_BUCKET_NAME,
    USER_BUCKET_NAME,
    jupyterlab_resource_spec,
    rollback_partial_provision,
    wait_for_user_profile_in_service,
    write_progress_env,
)
from errors import ApiError, api_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Boto3 clients — created at module level for connection reuse
sagemaker = boto3.client("sagemaker")
s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

MAX_CONCURRENT_PROVISIONS = 20


def slugify(text: str) -> str:
    """Convert text to URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text


def generate_user_id(name: str) -> str:
    """Generate a unique user ID from the name with 6 random characters."""
    slug = slugify(name)[:20]
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{slug}-{suffix}"


def copy_notebook_templates(user_id: str) -> int:
    """Copy notebook templates into the user's workspace. Returns the count copied.

    RAISES when nothing was copied. An empty/absent notebook-templates/ prefix used to
    be indistinguishable from success: the paginator yields a page with no "Contents"
    key, the loop body never runs, and this returned None to a caller that ignored it.
    The participant then received an EMPTY workspace and provisioning still answered
    HTTP 200. That is the expected state of a NEW REGION's shared-data bucket before it
    is seeded, so silently succeeding there would hand a whole cohort empty workspaces.
    """
    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(
        Bucket=SHARED_BUCKET_NAME, Prefix=NOTEBOOK_TEMPLATES_PREFIX
    )

    copied = 0
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
            copied += 1

    if copied == 0:
        raise ApiError(
            500,
            "Notebook templates are not staged in this region",
            details=(
                f"s3://{SHARED_BUCKET_NAME}/{NOTEBOOK_TEMPLATES_PREFIX} is empty, so "
                f"this participant would get an empty workspace. Publish the templates "
                f"first (README deploy Step 8 / ADMIN_GUIDE §6.5): "
                f"aws s3 sync notebooks/ s3://{SHARED_BUCKET_NAME}/"
                f"{NOTEBOOK_TEMPLATES_PREFIX} and the same for scripts/ into "
                f"{NOTEBOOK_TEMPLATES_PREFIX}scripts/"
            ),
        )
    return copied


def provision_single_user(user_data: dict) -> dict:
    """Provision a single user. Returns result dict with success/failure info.

    `user_data["region"]` was validated by the parser and always equals AWS_REGION —
    this deployment owns one region. It is recorded on the DynamoDB row as a note of
    which deployment owns it, not as a routing instruction.
    """
    name = user_data.get("name", "").strip()
    email = user_data.get("email", "").strip()
    region = (user_data.get("region") or AWS_REGION).strip()

    if not name:
        return {"name": name, "email": email, "success": False, "error": "Name is required"}

    user_id = generate_user_id(name)
    participant_token = str(uuid.uuid4())

    try:
        # Create SageMaker user profile
        sagemaker.create_user_profile(
            DomainId=SAGEMAKER_DOMAIN_ID,
            UserProfileName=user_id,
            Tags=[
                {"Key": "SageMakerUserProfile", "Value": user_id},
                {"Key": "Workshop", "Value": "av3-blueprint-lab"},
                {"Key": "ParticipantName", "Value": name},
            ],
        )

        # CreateUserProfile is asynchronous and CreateSpace rejects a profile that
        # has not settled. Without this every bulk row failed with "Unable to create
        # Space ... because UserProfile ... is not in InService" — create_user always
        # waited here, bulk_provision never did.
        wait_for_user_profile_in_service(sagemaker, SAGEMAKER_DOMAIN_ID, user_id)

        # Create SageMaker space
        space_name = f"{user_id}-space"
        sagemaker.create_space(
            DomainId=SAGEMAKER_DOMAIN_ID,
            SpaceName=space_name,
            OwnershipSettings={"OwnerUserProfileName": user_id},
            SpaceSettings={
                "AppType": "JupyterLab",
                "JupyterLabAppSettings": {
                    # CPU image on the initial t3.medium; instance + image are
                    # switched together later via change_instance.
                    "DefaultResourceSpec": jupyterlab_resource_spec("ml.t3.medium"),
                },
            },
            SpaceSharingSettings={"SharingType": "Private"},
            Tags=[
                {"Key": "Workshop", "Value": "av3-blueprint-lab"},
                {"Key": "UserId", "Value": user_id},
            ],
        )

        # Copy notebook templates
        copy_notebook_templates(user_id)

        # Progress tracking. create_user wrote this and bulk_provision did not, so
        # bulk-provisioned participants had 27 workspace objects instead of 28 and no
        # progress reporting at all — their dashboard never lit up.
        write_progress_env(
            s3, USER_BUCKET_NAME, user_id, participant_token,
            os.environ.get("API_URL", ""),
        )

        # Generate presigned URL
        presigned_url_response = sagemaker.create_presigned_domain_url(
            DomainId=SAGEMAKER_DOMAIN_ID,
            UserProfileName=user_id,
            SessionExpirationDurationInSeconds=PRESIGNED_URL_EXPIRY,
        )
        presigned_url = presigned_url_response["AuthorizedUrl"]

        # Calculate expiry
        now = datetime.now(timezone.utc)
        expires_at = int(now.timestamp()) + PRESIGNED_URL_EXPIRY
        expires_at_iso = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()

        # Save to DynamoDB
        table = dynamodb.Table(SESSIONS_TABLE_NAME)
        item = {
            "userId": user_id,
            "participantToken": participant_token,
            "name": name,
            "email": email,
            "spaceName": space_name,
            "presignedUrl": presigned_url,
            "expiresAt": expires_at,
            "expiresAtIso": expires_at_iso,
            "createdAt": now.isoformat(),
            "status": "active",
            "moduleProgress": {},
            # See create_user: this is the only record of which region's domain holds
            # the profile, so every later handler resolves its clients from it.
            "region": region,
        }
        table.put_item(Item=item)

        return {
            "name": name,
            "email": email,
            "userId": user_id,
            "participantToken": participant_token,
            "workspaceUrl": presigned_url,
            "presignedUrl": presigned_url,
            "expiresAt": expires_at_iso,
            "success": True,
        }

    except Exception as e:
        logger.error(f"Failed to provision user {name}: {str(e)}")
        # Compensate: remove whatever this row already created. Without this a
        # partial failure (quota, throttling, a not-yet-InService profile) leaves an
        # orphaned UserProfile that the admin CANNOT clean up from the dashboard —
        # delete_user keys on the DynamoDB row, which is written last, so it answers
        # 404 and the profile (plus its EFS home directory) lingers invisibly.
        # Best-effort and never raises: the row's real error must survive.
        cleanup_note = rollback_partial_provision(
            sagemaker, SAGEMAKER_DOMAIN_ID, user_id
        )
        return {
            "name": name,
            "email": email,
            "userId": user_id,
            "success": False,
            "error": str(e) + cleanup_note,
        }


def parse_user_rows(rows: list, default_region: str = "") -> list[dict]:
    """Normalise a JSON `users` array into the same shape parse_csv_body produces.

    Shares parse_csv_body's region contract: a region other than this deployment's
    fails the WHOLE batch up front rather than seating half a room in the wrong place —
    the choice is immutable per participant, so a partial batch would have to be
    deleted and re-provisioned one by one.
    """
    default_region = default_region or AWS_REGION
    users = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        row_region = str(row.get("region") or default_region).strip()
        if row_region != AWS_REGION:
            raise ApiError(
                400,
                f"Row '{name}' asks for {row_region!r}; this deployment serves "
                f"{AWS_REGION}",
                details=(
                    "One region per deployment. Remove the region column, or deploy the "
                    "stack in that region and upload there "
                    "(docs/en/ADDING_A_REGION.md)."
                ),
            )
        users.append(
            {
                "name": name,
                "email": str(row.get("email") or "").strip(),
                "region": row_region,
            }
        )
    return users


def parse_csv_body(body: str, is_base64: bool, default_region: str = "") -> list[dict]:
    """Parse CSV content from request body.

    Expects columns: name, email (header row required). An optional `region` column
    overrides `default_region` per row.
    """
    default_region = default_region or AWS_REGION
    if is_base64:
        try:
            csv_content = base64.b64decode(body).decode("utf-8")
        except Exception:
            raise ApiError(400, "Invalid base64-encoded CSV data")
    else:
        csv_content = body

    reader = csv.DictReader(io.StringIO(csv_content))

    # Validate headers
    if not reader.fieldnames:
        raise ApiError(400, "CSV must have a header row")

    # Normalize field names to lowercase
    normalized_fields = [f.lower().strip() for f in reader.fieldnames]
    if "name" not in normalized_fields:
        raise ApiError(400, "CSV must contain a 'name' column")

    users = []
    for row in reader:
        # Normalize keys
        normalized_row = {k.lower().strip(): v for k, v in row.items()}
        name = normalized_row.get("name", "").strip()
        if name:
            # Optional per-row region column. Validated here so a typo fails the whole
            # upload up front, rather than provisioning half a room into the wrong
            # region — the choice is immutable per participant.
            row_region = (normalized_row.get("region") or default_region).strip()
            if row_region != AWS_REGION:
                raise ApiError(
                    400,
                    f"Row '{name}' asks for {row_region!r}; this deployment serves "
                    f"{AWS_REGION}",
                    details=(
                        "One region per deployment. Remove the region column, or deploy "
                        "the stack in that region and upload there "
                        "(docs/en/ADDING_A_REGION.md)."
                    ),
                )
            users.append(
                {
                    "name": name,
                    "email": normalized_row.get("email", "").strip(),
                    "region": row_region,
                }
            )

    return users


@api_handler
def handler(event, context):
    """Bulk provision workshop users from CSV."""
    body = event.get("body")
    if not body:
        raise ApiError(400, "Request body is required (CSV data)")

    is_base64 = event.get("isBase64Encoded", False)

    # Batch-wide region default. Initialised HERE, not inside the branch below: a raw
    # CSV body never enters that branch, so assigning it only there would leave this
    # name unbound and raise NameError on the parse call. Empty means "let
    # parse_csv_body fall back to AWS_REGION".
    batch_region = ""

    users = None

    # Two accepted body shapes:
    #   {"users": [{name, email, module?, region?}, ...], "region": "<optional>"}
    #   {"csv": "<base64 CSV>", "region": "<optional>"}   (or a raw CSV body)
    #
    # The "users" form is what the admin UI has always sent (BulkUploadModal parses
    # the CSV in the browser, then posts rows via apiClient.bulkProvision), but only
    # the "csv" form was handled. The raw JSON string then fell through to the CSV
    # parser, whose header row became ['{"users": [{"name": "Alice"', ' "email": ...']
    # — no "name" column — so bulk provisioning returned 400 every single time. It is
    # the documented way to seat a room, so it was never usable from the dashboard.
    if not is_base64:
        try:
            json_body = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            json_body = None
        if isinstance(json_body, dict):
            batch_region = (json_body.get("region") or "").strip()
            if isinstance(json_body.get("users"), list):
                users = parse_user_rows(json_body["users"], default_region=batch_region)
            elif "csv" in json_body:
                body = json_body["csv"]
                is_base64 = True

    # Fall back to CSV (base64-wrapped or raw) when no "users" array was supplied.
    if users is None:
        users = parse_csv_body(body, is_base64, default_region=batch_region)

    if not users:
        raise ApiError(400, "No valid users found in CSV")

    if len(users) > 100:
        raise ApiError(400, f"Maximum 100 users per batch, got {len(users)}")

    logger.info(f"Bulk provisioning {len(users)} users")

    # Provision users in parallel
    results = []
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_PROVISIONS) as executor:
        future_to_user = {
            executor.submit(provision_single_user, user): user for user in users
        }
        for future in as_completed(future_to_user):
            result = future.result()
            results.append(result)

    # Summarize results
    successful = [r for r in results if r.get("success")]
    failed = [r for r in results if not r.get("success")]

    logger.info(
        f"Bulk provision complete: {len(successful)} succeeded, {len(failed)} failed"
    )

    # Shape is a CONTRACT with BulkProvisionResult in web/admin/src/api/client.ts:
    # succeeded[] / failed[] are ARRAYS of objects. This used to return
    # {successful: int, failed: int}, so BulkUploadModal's
    # `res.succeeded.length` threw (succeeded was undefined) and `res.failed.length`
    # was undefined-on-an-int — a second, independent break behind the 400 above.
    # `failed` keeping the same NAME but changing TYPE (int -> array) is exactly the
    # kind of mismatch TypeScript cannot catch across HTTP, so keep both sides in step.
    return {
        "succeeded": [
            {
                "email": r.get("email", ""),
                "name": r.get("name", ""),
                "workspaceUrl": r.get("workspaceUrl", ""),
            }
            for r in successful
        ],
        "failed": [
            {
                "email": r.get("email", ""),
                "name": r.get("name", ""),
                "error": r.get("error", "unknown error"),
            }
            for r in failed
        ],
        "total": len(users),
        # Full per-user detail (userId, participantToken, presigned URL, expiry) for
        # anything that needs more than the summary the modal renders.
        "results": results,
    }
