"""AV 3.0 Blueprint Lab - Database Construct.

DynamoDB sessions table with a GSI on participantToken.

NOTE: This table intentionally has NO TTL. It previously set
time_to_live_attribute="expiresAt", but `expiresAt` is the presigned-URL
expiry (now + 8h) — using it as the TTL attribute made DynamoDB auto-delete
every user's row ~8 hours after provisioning, silently emptying the roster
mid-workshop and orphaning their SageMaker resources. Workshop users must
persist until an admin explicitly removes them (Delete User flow), so TTL is
removed. `expiresAt` remains a plain attribute used only for URL-expiry display.
"""

from constructs import Construct

import aws_cdk as cdk
from aws_cdk import (
    RemovalPolicy,
    aws_dynamodb as dynamodb,
)


class DatabaseConstruct(Construct):
    """DynamoDB table for session tracking.

    Attributes:
        sessions_table: Table with PK=userId, TTL, and participantToken GSI.
            One item per user; all handlers key by userId alone.
    """

    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)

        self._sessions_table = dynamodb.Table(
            self,
            "SessionsTableV2",
            table_name="av30-sessions-v2",
            partition_key=dynamodb.Attribute(
                name="userId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            # No time_to_live_attribute — see module docstring. Users must not
            # auto-expire; deletion is explicit via the Delete User flow.
            point_in_time_recovery=True,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # GSI for looking up sessions by participant token (e.g., join-by-link flow)
        self._sessions_table.add_global_secondary_index(
            index_name="participantToken-index",
            partition_key=dynamodb.Attribute(
                name="participantToken", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

    @property
    def sessions_table(self) -> dynamodb.Table:
        """DynamoDB sessions table."""
        return self._sessions_table
