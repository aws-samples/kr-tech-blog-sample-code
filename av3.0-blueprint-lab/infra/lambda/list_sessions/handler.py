"""Lambda handler for listing active sessions with estimated costs.

GET /sessions
Scans DynamoDB for all users, calculates running costs for active sessions,
and returns sessions sorted by status (active first) then cost descending.
"""

import logging
import os
import sys
from datetime import datetime, timezone

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from config import INSTANCE_RATES, SESSIONS_TABLE_NAME, gpu_model
from errors import api_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Boto3 clients — created at module level for connection reuse
dynamodb = boto3.resource("dynamodb")


def _start_time(item: dict) -> datetime | None:
    """Parse the session start, or None if it is missing/unparseable."""
    raw = item.get("createdAt")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def calculate_estimated_cost(item: dict, now: datetime, *, since_midnight: bool) -> float:
    """Estimated spend for one session, from INSTANCE_RATES x elapsed hours.

    `since_midnight=True` clamps the window to 00:00 UTC today. That is what the
    admin column labelled "Cost Today" needs: billing from createdAt would report a
    participant provisioned four days ago as having spent four days of money today,
    and the page also SUMS these into a "today's cost" tile. Pass False for the
    run-to-date figure.

    Note this bills from when the user was PROVISIONED, not from when their current
    app started, and it does not subtract time the app spent stopped — so it is an
    upper bound, which is the safe direction for a cost guardrail.
    """
    start_time = _start_time(item)
    if start_time is None:
        return 0.0

    if since_midnight:
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_time = max(start_time, midnight)

    elapsed_hours = (now - start_time).total_seconds() / 3600
    if elapsed_hours <= 0:
        return 0.0
    rate = INSTANCE_RATES.get(item.get("instanceType", "ml.t3.medium"), 0.0)
    return round(elapsed_hours * rate, 4)


@api_handler
def handler(event, context):
    """List all sessions with estimated costs."""
    table = dynamodb.Table(SESSIONS_TABLE_NAME)

    # Scan all items (acceptable for workshop-scale data)
    items = []
    response = table.scan()
    items.extend(response.get("Items", []))

    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))

    logger.info(f"Found {len(items)} total users")

    now = datetime.now(timezone.utc)
    sessions = []

    for item in items:
        # `status` is the AUTH field (token_authorizer requires "active"); appStatus is
        # compute state, written by terminate_session. Terminating used to set
        # status="offline", which revoked the participant's token permanently — so the two
        # are now separate and the DISPLAY status is derived from both. Legacy rows with
        # status="offline" still render as offline.
        auth_status = item.get("status", "offline")
        app_state = item.get("appStatus")
        if auth_status != "active":
            status = auth_status
        elif app_state == "stopped":
            status = "offline"
        else:
            status = auth_status
        instance_type = item.get("instanceType", "ml.t3.medium")
        user_id = item.get("userId")

        cost_today = 0.0
        cost_total = 0.0
        if status != "offline":
            cost_today = calculate_estimated_cost(item, now, since_midnight=True)
            cost_total = calculate_estimated_cost(item, now, since_midnight=False)

        # FIELD NAMES ARE A CONTRACT with web/admin/src/pages/SessionsPage.tsx. They
        # previously did NOT match, and every mismatch failed silently in a different
        # way: the page reads s.costToday and called .toFixed(2) on it, so an
        # undefined threw inside the cell renderer and blanked the whole table; it
        # reads s.sessionId and passed it to terminateSession(), so the request went
        # to /sessions/undefined; and it counts GPU boxes with `gpuType !== null`,
        # which an absent field satisfies for EVERY row. Keep these keys in step with
        # the Session interface in web/admin/src/api/client.ts.
        sessions.append(
            {
                # The terminate/instance-type/storage routes all key on the userId,
                # so that is what the page must hand back. Same value, two names:
                # sessionId is what the table trackBy + action buttons use.
                "sessionId": user_id,
                "userId": user_id,
                "userName": item.get("name"),
                "status": status,
                "instanceType": instance_type,
                # null (not "" or "none") for CPU — the page's GPU count is
                # `gpuType !== null`, so any truthy placeholder over-counts.
                "gpuType": gpu_model(instance_type),
                "startedAt": item.get("createdAt"),
                "costToday": cost_today,
                # Run-to-date, for context; the page currently shows only costToday.
                "estimatedCostTotal": cost_total,
                "currentModule": item.get("currentModule"),
                # See list_users: region must be visible or a mis-regioned session
                # looks identical to a healthy one.
                "region": item.get("region", ""),
                # No default. A row without storageGB was provisioned before create_user
                # started recording it, and its real volume is whatever the domain default
                # was at the time — not something this handler can know. Defaulting to a
                # number would assert a size that is wrong for exactly those rows.
                # (Nothing in web/admin/src renders this yet; it is here for the API.)
                "storageGB": item.get("storageGB"),
            }
        )

    # Sort: active first, then by cost descending
    status_priority = {"active": 0, "provisioning": 1, "stopping": 2, "offline": 3}
    sessions.sort(
        key=lambda s: (
            status_priority.get(s["status"], 9),
            -s["costToday"],
        )
    )

    return {
        "sessions": sessions,
        "total": len(sessions),
        "activeCount": sum(1 for s in sessions if s["status"] != "offline"),
    }
