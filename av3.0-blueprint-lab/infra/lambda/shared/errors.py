"""Shared error handling for AV 3.0 Blueprint Lab Lambda functions."""

import json
import logging
import traceback
from decimal import Decimal
from functools import wraps

from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that converts DynamoDB Decimal values to int/float.

    The DynamoDB resource layer returns all Number attributes as Decimal,
    which the default json encoder cannot serialize.
    """

    def default(self, obj):
        if isinstance(obj, Decimal):
            # Preserve integers as int, others as float
            return int(obj) if obj % 1 == 0 else float(obj)
        return super().default(obj)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,X-Api-Key,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
    "Content-Type": "application/json",
}


class ApiError(Exception):
    """Custom API error with HTTP status code."""

    def __init__(self, status_code: int, message: str, details: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.details = details


def api_handler(func):
    """Decorator that wraps Lambda handlers with error handling and CORS headers.

    Catches ApiError, ClientError, and generic exceptions, returning
    appropriate JSON error responses with CORS headers.
    """

    @wraps(func)
    def wrapper(event, context):
        # Handle OPTIONS preflight
        if event.get("httpMethod") == "OPTIONS":
            return {
                "statusCode": 200,
                "headers": CORS_HEADERS,
                "body": "",
            }

        try:
            result = func(event, context)

            # If handler returns a dict without statusCode, wrap it
            if isinstance(result, dict) and "statusCode" not in result:
                return {
                    "statusCode": 200,
                    "headers": CORS_HEADERS,
                    "body": json.dumps(result, cls=DecimalEncoder),
                }

            # If handler returns a full response, ensure CORS headers
            if isinstance(result, dict) and "statusCode" in result:
                result.setdefault("headers", {})
                result["headers"].update(CORS_HEADERS)
                return result

            return result

        except ApiError as e:
            logger.warning(f"API error: {e.status_code} - {e.message}")
            body = {"error": e.message}
            if e.details:
                body["details"] = e.details
            return {
                "statusCode": e.status_code,
                "headers": CORS_HEADERS,
                "body": json.dumps(body),
            }

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            error_message = e.response["Error"]["Message"]
            logger.error(f"AWS ClientError: {error_code} - {error_message}")
            return {
                "statusCode": 502,
                "headers": CORS_HEADERS,
                "body": json.dumps(
                    {
                        "error": "AWS service error",
                        "details": f"{error_code}: {error_message}",
                    }
                ),
            }

        except Exception as e:
            logger.error(f"Unhandled exception: {str(e)}")
            logger.error(traceback.format_exc())
            return {
                "statusCode": 500,
                "headers": CORS_HEADERS,
                "body": json.dumps({"error": "Internal server error"}),
            }

    return wrapper


def require_own_user(event: dict, user_id: str) -> None:
    """Reject a participant token used against a DIFFERENT participant's userId.

    The TokenAuthorizer deliberately returns a STAGE-WIDE resource
    (`.../prod/*`) so API Gateway can cache one policy across methods. The
    consequence is that ANY valid participant token authorizes EVERY token route
    for EVERY {userId} — authorization at the gateway proves only "this is a
    participant", never "this is THAT participant". The per-route ownership check
    is therefore the only thing standing between participants.

    Three routes shipped without it while two had it inline:
        POST  /presigned-url/{userId}      -> a working Studio URL into someone
                                             else's workspace
        PATCH /sessions/{id}/instance-type -> deletes their running app and
                                             rebuilds it on a chosen instance
        PATCH /sessions/{id}/storage       -> resizes their EBS volume
    All three are token-auth ONLY (no admin path goes through them), so this can
    be applied unconditionally.

    FAILS CLOSED, unlike the original inline guard (`if caller_id and caller_id
    != user_id`), which passed when the context was missing. On a token-auth
    route the authorizer always sets context.userId on its Allow policy, so an
    absent value means the request did not come through the authorizer — which is
    exactly when denying is right.
    """
    ctx = (event.get("requestContext") or {}).get("authorizer") or {}
    caller_id = ctx.get("userId")
    if not caller_id:
        raise ApiError(
            403,
            "Request did not carry an authorized participant identity",
            details="Expected requestContext.authorizer.userId from the TokenAuthorizer.",
        )
    if caller_id != user_id:
        raise ApiError(403, "Token not authorized for this userId")
