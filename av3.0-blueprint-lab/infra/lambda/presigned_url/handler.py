"""Lambda handler for generating a new presigned URL for an existing user.

POST /presigned-url/{userId}
Validates the user exists in DynamoDB, generates a fresh presigned URL,
and updates the expiry in DynamoDB.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from config import PRESIGNED_URL_EXPIRY, SAGEMAKER_DOMAIN_ID, SESSIONS_TABLE_NAME
from errors import ApiError, api_handler, require_own_user

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Boto3 clients — created at module level for connection reuse
sagemaker = boto3.client("sagemaker")
dynamodb = boto3.resource("dynamodb")


@api_handler
def handler(event, context):
    """Generate a new presigned URL for an existing user."""
    # Extract userId from path parameters
    path_params = event.get("pathParameters") or {}
    user_id = path_params.get("userId") or path_params.get("id")

    if not user_id:
        raise ApiError(400, "userId path parameter is required")

    # The TokenAuthorizer grants a stage-wide resource, so a valid token reaches this
    # route for ANY userId. Without this, a participant could act on someone else's
    # workspace by editing the path. See require_own_user for the full reasoning.
    require_own_user(event, user_id)

    logger.info(f"Generating presigned URL for user: {user_id}")

    # Validate user exists in DynamoDB
    table = dynamodb.Table(SESSIONS_TABLE_NAME)
    response = table.get_item(Key={"userId": user_id})

    if "Item" not in response:
        raise ApiError(404, f"User not found: {user_id}")

    user_item = response["Item"]

    if user_item.get("status") == "deleted":
        raise ApiError(410, f"User has been deleted: {user_id}")

    # Generate new presigned URL.
    #
    # When the participant's JupyterLab app is already running, land them INSIDE it
    # (LandingUri "app:JupyterLab:" + SpaceName) instead of on the Studio home page.
    # Without this the participant arrives at Studio home and has to find their own space
    # before they can do anything.
    #
    # This started life as a PERMISSION workaround: the participant execution role had
    # neither sagemaker:UpdateSpace (needed by the space page's "Run space") nor
    # sagemaker:CreatePresignedDomainUrl (needed by Studio's "Open JupyterLab"), so both of
    # Studio's own buttons failed with AccessDenied and Studio showed a permanent
    # "Permission issue detected" banner. Both are now granted, scoped to the caller's own
    # private space / own user profile — see SageMakerOwnPrivateSpaceUpdate and
    # SageMakerPresignedUrlOwnProfileOnly in infra/av30_constructs/sagemaker.py.
    #
    # The deep link is kept anyway, for two reasons that survive the grant: it is simply a
    # better path (one click into JupyterLab instead of three through Studio), and the
    # scoped grants depend on ${sagemaker:*} policy variables resolving at request time,
    # which is documented but not yet confirmed in this account. If they do not resolve, the
    # statements match nothing and this deep link is again the only working route.
    #
    # Only when the app is LIVE. A LandingUri pointing at an app that does not exist has
    # nowhere to go, so with no app we keep the old behaviour (Studio home) — and the
    # dashboard's Instance Options panel is what starts the app in that case.
    # LandingUri values are from the CreatePresignedDomainUrl API reference:
    # "app:JupyterLab:relative/path" directs the user into the JupyterLab application.
    url_kwargs = {
        "DomainId": SAGEMAKER_DOMAIN_ID,
        "UserProfileName": user_id,
        "SessionExpirationDurationInSeconds": PRESIGNED_URL_EXPIRY,
    }
    space_name = user_item.get("spaceName") or f"{user_id}-space"
    if _app_is_serving(space_name):
        url_kwargs["SpaceName"] = space_name
        url_kwargs["LandingUri"] = "app:JupyterLab:"
        logger.info(f"App is live; landing {user_id} directly in JupyterLab")
    else:
        logger.info(
            f"No live app for space {space_name}; landing {user_id} on Studio home "
            f"(the dashboard's Instance Options panel starts the app)"
        )

    presigned_url_response = sagemaker.create_presigned_domain_url(**url_kwargs)
    presigned_url = presigned_url_response["AuthorizedUrl"]

    # Calculate new expiry
    now = datetime.now(timezone.utc)
    expires_at = int(now.timestamp()) + PRESIGNED_URL_EXPIRY
    expires_at_iso = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()

    # Update DynamoDB with new presigned URL and expiry
    table.update_item(
        Key={"userId": user_id},
        UpdateExpression="SET presignedUrl = :url, expiresAt = :exp, expiresAtIso = :expIso, updatedAt = :now",
        ExpressionAttributeValues={
            ":url": presigned_url,
            ":exp": expires_at,
            ":expIso": expires_at_iso,
            ":now": now.isoformat(),
        },
    )
    logger.info(f"Updated presigned URL for user: {user_id}, expires: {expires_at_iso}")

    return {
        "userId": user_id,
        "presignedUrl": presigned_url,
        "expiresAt": expires_at_iso,
    }


def _app_is_serving(space_name: str) -> bool:
    """True only when this space's JupyterLab app is InService.

    DELIBERATELY STRICTER than _live_app_state in change_instance/handler.py, which counts
    Pending as live. The two predicates answer different questions:
      * change_instance asks "is a restart a no-op?" — a Pending app is already coming up
        on the requested type, so yes.
      * this asks "should I deep-link the browser into JupyterLab?" — a Pending app has no
        server behind it yet (the instance is still booting and the image still pulling),
        and a deep link would land on a route nothing answers. Studio home is the better
        destination until the app is actually serving.

    Best-effort: any failure returns False, which costs the participant only the nicer
    landing page, never the URL itself.
    """
    try:
        resp = sagemaker.describe_app(
            DomainId=SAGEMAKER_DOMAIN_ID,
            SpaceName=space_name,
            AppType="JupyterLab",
            AppName="default",
        )
    except sagemaker.exceptions.ResourceNotFound:
        # Normal: no app has been created yet, or one was idle-shut-down.
        return False
    except Exception as exc:  # noqa: BLE001
        # A throttle is NOT "no app" — log it as the anomaly it is rather than at INFO,
        # so a cohort-start DescribeApp throttle is visible instead of looking routine.
        logger.warning(f"DescribeApp failed for {space_name}: {exc}")
        return False
    return resp.get("Status") == "InService"
