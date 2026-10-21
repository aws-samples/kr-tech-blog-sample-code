"""AV 3.0 Blueprint Lab - Storage Construct.

KMS key with rotation, two S3 buckets (shared-data, user-workspace).

BUCKET NAMING — THE REGION SUFFIX IS MANDATORY, NOT COSMETIC
------------------------------------------------------------
Names are `av30lab-{shared-data|user-workspace}-{account}-{region}`.

S3 bucket names are GLOBALLY unique, so the previous account-only names
(`av30lab-shared-data-{account}`) made a second region in the same account
impossible: the 2nd stack failed at CREATE with BucketAlreadyOwnedByYou. The
region suffix is what unblocks deploying this stack to more than one region.

Each region needs its OWN buckets regardless of cost, because the VPC reaches S3
through a *gateway* endpoint and "a gateway endpoint is available only in the
Region where you created it" — a bucket in another region is unreachable from
these isolated subnets, not merely slower.

Longest name is 50 chars (`av30lab-user-workspace-<12-digit acct>-ap-northeast-2`),
within S3's 63-char limit. Anything that builds these names by hand — scripts/
deploy.sh, scripts/teardown.sh, the notebook env fallbacks, and the docs — must
use the same pattern.
"""

from constructs import Construct

import aws_cdk as cdk
from aws_cdk import (
    Aws,
    Duration,
    RemovalPolicy,
    aws_kms as kms,
    aws_s3 as s3,
)


class StorageConstruct(Construct):
    """KMS encryption key and S3 buckets for platform data.

    Attributes:
        kms_key: Symmetric KMS key with automatic rotation.
        shared_data_bucket: Versioned bucket for shared datasets (RETAIN on delete).
        user_workspace_bucket: Ephemeral bucket with lifecycle (DESTROY on delete).
    """

    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)

        # KMS key used by both buckets
        self._kms_key = kms.Key(
            self,
            "Key",
            alias="av30lab-key",
            description="AV 3.0 Blueprint Lab encryption key",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Shared data bucket — versioned, retained on stack deletion
        self._shared_data_bucket = s3.Bucket(
            self,
            "SharedDataBucket",
            bucket_name=f"av30lab-shared-data-{Aws.ACCOUNT_ID}-{Aws.REGION}",
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self._kms_key,
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
        )

        # User workspace bucket — ephemeral, lifecycle to Glacier after 30 days
        self._user_workspace_bucket = s3.Bucket(
            self,
            "UserWorkspaceBucket",
            bucket_name=f"av30lab-user-workspace-{Aws.ACCOUNT_ID}-{Aws.REGION}",
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self._kms_key,
            versioned=False,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="TransitionToGlacier",
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.GLACIER,
                            transition_after=Duration.days(30),
                        ),
                    ],
                ),
            ],
        )

    @property
    def kms_key(self) -> kms.Key:
        """Symmetric KMS key with automatic rotation."""
        return self._kms_key

    @property
    def shared_data_bucket(self) -> s3.Bucket:
        """Versioned bucket for shared datasets."""
        return self._shared_data_bucket

    @property
    def user_workspace_bucket(self) -> s3.Bucket:
        """Ephemeral bucket for user workspace files."""
        return self._user_workspace_bucket
