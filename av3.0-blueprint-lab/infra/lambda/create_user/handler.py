"""Lambda handler for creating a new workshop user.

POST /users
Creates a SageMaker user profile, space, copies notebook templates,
generates a presigned URL, and saves the session to DynamoDB.
"""

import json
import logging
import os
import random
import re
import string
import sys
import time
import uuid
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
    DEFAULT_SPACE_STORAGE_GB,
)
from errors import ApiError, api_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Boto3 clients — created at module level for connection reuse
sagemaker = boto3.client("sagemaker")
s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")


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
            # Strip the templates prefix, keep the relative path
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
            logger.info(f"Copied {source_key} -> {dest_key}")
            copied += 1

    if copied == 0:
        raise ApiError(
            500,
            "Notebook templates are not staged in this region",
            details=(
                f"s3://{SHARED_BUCKET_NAME}/{NOTEBOOK_TEMPLATES_PREFIX} is empty, so "
                f"this participant would get an empty workspace. Publish the templates "
                f"first (README deploy Step 8 / ADMIN_GUIDE §6.5)."
            ),
        )
    return copied


@api_handler
def handler(event, context):
    """Create a new workshop user."""
    # Parse and validate request body
    body = event.get("body")
    if not body:
        raise ApiError(400, "Request body is required")

    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            raise ApiError(400, "Invalid JSON in request body")

    name = body.get("name", "").strip()
    email = body.get("email", "").strip()

    if not name:
        raise ApiError(400, "Field 'name' is required")

    # This deployment owns exactly ONE region, so the participant's region is
    # AWS_REGION — there is nothing to choose. A `region` field is still ACCEPTED so an
    # older client does not break, but a MISMATCH is rejected rather than ignored: the
    # caller asked to place a participant somewhere this deployment cannot reach, and
    # silently placing them here instead would be wrong in a way nobody would notice
    # until the participant opened a workspace with the wrong region's data.
    #
    # The choice is IMMUTABLE either way: a UserProfile belongs to exactly one Domain and
    # a Domain is regional, so there is no "move this participant", only delete and
    # re-provision. To seat participants in another region, deploy the stack there
    # (docs/en/ADDING_A_REGION.md) and provision from THAT deployment's dashboard.
    requested_region = (body.get("region") or AWS_REGION).strip()
    if requested_region != AWS_REGION:
        raise ApiError(
            400,
            f"This deployment serves {AWS_REGION}, not {requested_region!r}",
            details=(
                f"One region per deployment. Deploy the stack in {requested_region} and "
                f"provision from that deployment instead (docs/en/ADDING_A_REGION.md)."
            ),
        )
    region = AWS_REGION

    # Generate identifiers
    user_id = generate_user_id(name)
    participant_token = str(uuid.uuid4())

    logger.info(f"Creating user: {user_id} (name={name})")

    # Every step below creates real resources, and any of them can fail: quota,
    # throttling, a profile that never settles — and, by design, an unseeded
    # region, where copy_notebook_templates RAISES rather than handing out an
    # empty workspace. Without compensation that leaves an orphaned UserProfile
    # the admin cannot remove: delete_user keys on the DynamoDB row written at the
    # very end, so it answers 404, and user_id is random so it cannot even be
    # named. bulk_provision has rolled back since its own partial-failure bug;
    # this path did not, so making the unseeded-region failure loud would have
    # started manufacturing exactly those orphans.
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
        logger.info(f"Created SageMaker user profile: {user_id}")

        # UserProfile creation is asynchronous — wait until it is InService before
        # creating the space (CreateSpace fails otherwise). Shared with bulk_provision,
        # which was missing this wait entirely.
        try:
            wait_for_user_profile_in_service(sagemaker, SAGEMAKER_DOMAIN_ID, user_id)
        except TimeoutError as e:
            raise ApiError(504, str(e))
        except RuntimeError as e:
            raise ApiError(502, str(e))
        logger.info(f"UserProfile {user_id} is InService")

        # Create SageMaker space for the user
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
        logger.info(f"Created SageMaker space: {space_name}")

        # Copy notebook templates to user workspace
        copy_notebook_templates(user_id)

        # B2 progress tracking: write the participant's own progress credentials into
        # their workspace prefix. The notebook-sync LCC already `aws s3 sync`s
        # users/<id>/ to the home dir at app launch, so it lands as
        # ~/.av30-progress.env with NO new IAM grant (the file holds only this
        # participant's own token — same trust boundary as their browser session).
        # The notebook mark-complete cells source AV30_API_URL + AV30_PROGRESS_TOKEN.
        if write_progress_env(
            s3, USER_BUCKET_NAME, user_id, participant_token,
            os.environ.get("API_URL", ""),
        ):
            logger.info(f"Wrote progress env for {user_id}")
        else:
            logger.warning(f"No progress env written for {user_id}")

        # Generate presigned URL (8 hours)
        presigned_url_response = sagemaker.create_presigned_domain_url(
            DomainId=SAGEMAKER_DOMAIN_ID,
            UserProfileName=user_id,
            SessionExpirationDurationInSeconds=PRESIGNED_URL_EXPIRY,
        )
        presigned_url = presigned_url_response["AuthorizedUrl"]

        # Calculate expiry timestamp
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
            # The size create_space just inherited from the domain. Recorded so
            # list_sessions and expand_storage do not have to guess: before this, nothing
            # wrote storageGB and expand_storage fell back to a hardcoded 5, which stopped
            # matching the volume the moment the domain default changed.
            "storageGB": DEFAULT_SPACE_STORAGE_GB,
            # The ONLY record of which region's domain holds this user's profile. Every
            # later handler resolves its SageMaker/S3 clients from this, so the row is
            # read before teardown starts and deleted last.
            "region": region,
        }
    except Exception as e:
        note = rollback_partial_provision(sagemaker, SAGEMAKER_DOMAIN_ID, user_id)
        logger.error(f"Provisioning failed for {user_id}: {e}{note}")
        # Surface the cleanup outcome to the admin: if an orphan survived, the note
        # names it. Re-raise the ORIGINAL error — the failure, not the cleanup, is
        # what needs fixing.
        if isinstance(e, ApiError) and note:
            e.details = f"{e.details or ''}{note}".strip()
        raise
    table.put_item(Item=item)
    logger.info(f"Saved session to DynamoDB: {user_id}")

    return {
        "userId": user_id,
        "workspaceUrl": presigned_url,
        "presignedUrl": presigned_url,
        "participantToken": participant_token,
        "expiresAt": expires_at_iso,
        "name": name,
        "email": email,
        "status": "active",
        "module": "-",
        "spaceName": space_name,
        "region": region,
    }
