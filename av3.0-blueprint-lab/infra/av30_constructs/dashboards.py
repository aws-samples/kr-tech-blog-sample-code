"""AV 3.0 Blueprint Lab - Dashboard Construct.

S3-hosted SPA served via CloudFront with optional WAF protection.
Reusable: instantiated for admin (with WAF) and user (without WAF) dashboards.
"""

from constructs import Construct

import aws_cdk as cdk
from aws_cdk import (
    RemovalPolicy,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_s3 as s3,
)


class DashboardConstruct(Construct):
    """S3 + CloudFront SPA hosting with optional WAF WebACL.

    Attributes:
        bucket: The S3 bucket holding static assets.
        distribution: The CloudFront distribution.
        url: The CloudFront domain URL (https).
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        bucket_name: str,
        web_acl_arn: str | None = None,
    ) -> None:
        super().__init__(scope, construct_id)

        # S3 bucket for SPA static assets
        self._bucket = s3.Bucket(
            self,
            "Bucket",
            bucket_name=bucket_name,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # Origin Access Identity for CloudFront → S3
        oai = cloudfront.OriginAccessIdentity(
            self,
            "OAI",
            comment=f"OAI for {bucket_name}",
        )
        self._bucket.grant_read(oai)

        # CloudFront distribution
        error_responses = [
            cloudfront.ErrorResponse(
                http_status=403,
                response_http_status=200,
                response_page_path="/index.html",
                ttl=cdk.Duration.seconds(0),
            ),
            cloudfront.ErrorResponse(
                http_status=404,
                response_http_status=200,
                response_page_path="/index.html",
                ttl=cdk.Duration.seconds(0),
            ),
        ]

        distribution_props: dict = {
            "default_behavior": cloudfront.BehaviorOptions(
                origin=origins.S3Origin(
                    self._bucket,
                    origin_access_identity=oai,
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
            ),
            "default_root_object": "index.html",
            "error_responses": error_responses,
            "minimum_protocol_version": cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
            "http_version": cloudfront.HttpVersion.HTTP2_AND_3,
        }

        if web_acl_arn:
            distribution_props["web_acl_id"] = web_acl_arn

        self._distribution = cloudfront.Distribution(
            self,
            "Distribution",
            **distribution_props,
        )

    @property
    def bucket(self) -> s3.Bucket:
        """S3 bucket holding static SPA assets."""
        return self._bucket

    @property
    def distribution(self) -> cloudfront.Distribution:
        """CloudFront distribution serving the SPA."""
        return self._distribution

    @property
    def url(self) -> str:
        """HTTPS URL of the CloudFront distribution."""
        return f"https://{self._distribution.distribution_domain_name}"
