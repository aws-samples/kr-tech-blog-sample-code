"""Lambda handler for listing all workshop users.

GET /users
Scans DynamoDB and returns all users with their status.
"""

import logging
import os
import sys
from datetime import datetime, timezone

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from config import SESSIONS_TABLE_NAME
from errors import api_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Boto3 clients — created at module level for connection reuse
dynamodb = boto3.resource("dynamodb")


@api_handler
def handler(event, context):
    """List all workshop users."""
    table = dynamodb.Table(SESSIONS_TABLE_NAME)

    # Scan all items (acceptable for workshop-scale data)
    items = []
    response = table.scan()
    items.extend(response.get("Items", []))

    # Handle pagination for larger datasets
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))

    logger.info(f"Found {len(items)} users")

    # Enrich with computed status
    now_ts = int(datetime.now(timezone.utc).timestamp())
    users = []
    for item in items:
        expires_at = item.get("expiresAt", 0)
        # Convert Decimal to int for comparison
        if hasattr(expires_at, "__int__"):
            expires_at = int(expires_at)

        is_expired = now_ts > expires_at if expires_at else False

        users.append(
            {
                "userId": item.get("userId"),
                "name": item.get("name"),
                "email": item.get("email"),
                "status": item.get("status", "unknown"),
                "module": item.get("currentModule") or "-",
                "workspaceUrl": item.get("presignedUrl", ""),
                # Durable token for building the participant dashboard link;
                # empty for rows provisioned before this field existed.
                "participantToken": item.get("participantToken", ""),
                "urlExpired": is_expired,
                "expiresAt": item.get("expiresAtIso"),
                "createdAt": item.get("createdAt"),
                "moduleProgress": item.get("moduleProgress", {}),
                # Which region's Studio domain holds this profile. Surfaced because
                # without it every region-resolution failure is invisible in the UI —
                # you would see a normal-looking row for a user whose workspace,
                # storage and cost all live somewhere else. "" for rows provisioned
                # before the attribute existed.
                "region": item.get("region", ""),
                # Why the last teardown stopped, set only with status "delete-failed".
                # delete_user hands its slow tail to an async self-invocation, so there
                # is no HTTP response left to report a failure through — this row IS the
                # report. Omitting it would leave a user stuck in a failed-delete state
                # with nothing on screen to say why, and an incomplete OpenSearch
                # Serverless cleanup billing at its 2-OCU floor.
                "lastDeleteError": item.get("lastDeleteError", ""),
            }
        )

    # Sort by creation time, newest first
    users.sort(key=lambda u: u.get("createdAt", ""), reverse=True)

    return {
        "users": users,
        "total": len(users),
    }
