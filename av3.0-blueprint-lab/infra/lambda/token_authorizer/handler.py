"""Lambda authorizer for API Gateway.

Validates participant tokens via DynamoDB GSI lookup. Returns an IAM Allow
policy for a valid token of an active user; raises "Unauthorized" (401) for a
missing/unknown token or an inactive user. There is deliberately no expiry-based
Deny — the participant token stays valid for the whole workshop (see handler()).
"""

import logging
import os
import sys

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from config import SESSIONS_TABLE_NAME

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Boto3 clients — created at module level for connection reuse
dynamodb = boto3.resource("dynamodb")


def generate_policy(principal_id: str, effect: str, resource: str, context: dict | None = None) -> dict:
    """Generate an IAM policy document for API Gateway authorization."""
    policy = {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": resource,
                }
            ],
        },
    }
    if context:
        policy["context"] = context
    return policy


def handler(event, context):
    """Lambda authorizer handler.

    Reads x-api-key header, queries DynamoDB GSI (token-index),
    checks token validity and expiry, returns IAM allow/deny policy.

    Note: This handler does NOT use the @api_handler decorator because
    Lambda authorizers must return IAM policy documents, not HTTP responses.
    """
    logger.info("Token authorizer invoked")

    # Extract the token from headers
    headers = event.get("headers") or {}
    # API Gateway may pass headers with different casing
    token = (
        headers.get("x-api-key")
        or headers.get("X-Api-Key")
        or headers.get("X-API-KEY")
    )

    # Also check authorizationToken for TOKEN type authorizers
    if not token:
        token = event.get("authorizationToken", "")
        # Strip "Bearer " prefix if present
        if token.startswith("Bearer "):
            token = token[7:]

    method_arn = event.get("methodArn", "*")

    if not token:
        logger.warning("No token provided")
        raise Exception("Unauthorized")  # API Gateway expects this for 401

    try:
        # Query DynamoDB GSI to find user by participant token
        table = dynamodb.Table(SESSIONS_TABLE_NAME)
        response = table.query(
            IndexName="participantToken-index",
            KeyConditionExpression=boto3.dynamodb.conditions.Key(
                "participantToken"
            ).eq(token),
        )

        items = response.get("Items", [])

        if not items:
            logger.warning(f"Token not found in database")
            raise Exception("Unauthorized")

        user_item = items[0]
        user_id = user_item.get("userId", "unknown")

        # Check if user is active
        if user_item.get("status") != "active":
            logger.warning(f"User {user_id} is not active (status={user_item.get('status')})")
            raise Exception("Unauthorized")

        # NOTE: we intentionally do NOT check `expiresAt` here. That field is the
        # presigned-URL session expiry (now + PRESIGNED_URL_EXPIRY, ~8h), which
        # presigned_url refreshes on every "Open Workspace". The participant
        # dashboard token must stay valid for the whole workshop, independent of
        # that URL lifetime — SageMaker already enforces the presigned URL's own
        # expiry on the URL itself. Treating expiresAt as a TOKEN expiry meant a
        # participant who hadn't opened their workspace in 8h got a 403 Deny.
        # A participant token is valid iff it exists in the table and the user is
        # active; revoke access by setting status != "active" (or delete_user).

        # Token is valid — allow access
        logger.info(f"Authorized user: {user_id}")

        # Use wildcard resource to allow caching across methods
        # Replace specific method/path with wildcard
        resource_arn_parts = method_arn.split(":")
        api_gateway_arn = ":".join(resource_arn_parts[:5])
        api_parts = resource_arn_parts[5].split("/")
        wildcard_resource = f"{api_gateway_arn}:{api_parts[0]}/{api_parts[1]}/*"

        return generate_policy(
            principal_id=user_id,
            effect="Allow",
            resource=wildcard_resource,
            context={
                "userId": user_id,
                "name": user_item.get("name", ""),
                "email": user_item.get("email", ""),
            },
        )

    except Exception as e:
        if str(e) == "Unauthorized":
            raise
        logger.error(f"Authorization error: {str(e)}")
        raise Exception("Unauthorized")
