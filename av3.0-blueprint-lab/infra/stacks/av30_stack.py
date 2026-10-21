"""AV 3.0 Blueprint Lab - Main CDK Stack.

Orchestrates all constructs: Network, Storage, Database, SageMaker, Auth,
Monitoring, API, and Dashboards (admin + user).
"""

from constructs import Construct

import aws_cdk as cdk
from aws_cdk import aws_wafv2 as wafv2

from av30_constructs.network import NetworkConstruct
from av30_constructs.storage import StorageConstruct
from av30_constructs.database import DatabaseConstruct
from av30_constructs.sagemaker import SageMakerConstruct, first_party_image_arn
from av30_constructs.auth import AuthConstruct
from av30_constructs.monitoring import MonitoringConstruct
from av30_constructs.api import ApiConstruct
from av30_constructs.dashboards import DashboardConstruct


def _require_generated_rate_table(region: str) -> None:
    """Fail at SYNTH if this region has no generated Studio-JupyterLab rate table.

    Without this the failure mode is the worst possible shape: `cdk deploy` SUCCEEDS, and
    then every Lambda dies at import, because infra/lambda/shared/config.py resolves the
    table at module scope —

        INSTANCE_RATES = _rates_for_region(AWS_REGION)   # raises UnpricedRegionError

    — and 14 of the 15 handlers import that module, including `token_authorizer` and
    `create_user`. So the whole API 500s and nobody can even sign in, for a reason that is
    invisible in the CloudFormation output.

    Only the regions in the generated file are usable. Generate one with:

        ./scripts/refresh_instance_rates.py --region <region> --merge

    This mirrors smd_images.UnsupportedRegionError, which already guards the image ARNs at
    synth for the same reason: a silent wrong value is worse than a loud refusal. Region is
    resolved from `-c region=...` / CDK_DEFAULT_REGION before synth, so it is a real string
    here, not a token — an unresolved token simply misses the table and is reported.
    """
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "lambda" / "shared" / "instance_rates.py"
    spec = importlib.util.spec_from_file_location("av30_instance_rates_guard", path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    generated = mod.RATES_BY_REGION

    if region not in generated:
        raise ValueError(
            f"No generated Studio-JupyterLab rate table for region {region!r}.\n"
            f"Deploying anyway would succeed and then 500 the entire API: "
            f"infra/lambda/shared/config.py resolves INSTANCE_RATES at import, and 14 of "
            f"15 Lambda handlers import it (including token_authorizer and create_user).\n"
            f"Generate it FIRST — see docs/en/ADDING_A_REGION.md §2.5:\n"
            f"    ./scripts/refresh_instance_rates.py --region {region} --merge\n"
            f"Generated today: {', '.join(sorted(generated))}"
        )


class Av30BlueprintLabStack(cdk.Stack):
    """Core infrastructure stack for AV 3.0 Blueprint Lab."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Refuse at synth rather than deploying a stack whose Lambdas cannot import.
        _require_generated_rate_table(self.region)

        # Apply project-level tags.
        #
        # `Owner` is settable per deployment (`-c owner_tag=...`) because SageMaker
        # treats Tags as REPLACEMENT-REQUIRING, and several of its resources carry a
        # fixed custom name. Changing this one cosmetic value therefore forces
        # CloudFormation to replace the Studio domain and the idle-shutdown lifecycle
        # config — and since their names do not change, CFN refuses outright:
        #
        #   CloudFormation cannot update a stack when a custom-named resource requires
        #   replacing. Rename av30lab-idle-shutdown-3h and update the stack again.
        #
        # That is exactly what happened updating a stack deployed before this repo was
        # sanitised for public release (it had Owner=<a person>). A fresh deployment
        # never sees it; an existing one can now keep its tag and get a small, safe
        # update instead of a domain rebuild that also orphans the domain's EFS.
        cdk.Tags.of(self).add("Project", "av30-blueprint-lab")
        cdk.Tags.of(self).add(
            "Owner", self.node.try_get_context("owner_tag") or "av30-blueprint-lab"
        )

        # Network layer: NAT-free VPC with the free S3 gateway endpoint.
        # The 6 paid interface endpoints (~$87.60/month per region) are OFF by
        # default because nothing in this VPC consumes them: the Lambdas are not
        # VPC-attached and the domain is PublicInternetOnly. Turn them on with
        #   npx cdk deploy -c vpc_interface_endpoints=true
        # if you switch the domain to VpcOnly. See NetworkConstruct's docstring.
        network = NetworkConstruct(
            self,
            "Network",
            vpc_interface_endpoints=str(
                self.node.try_get_context("vpc_interface_endpoints") or ""
            ).lower()
            in ("1", "true", "yes"),
        )

        # Storage layer: KMS key and S3 buckets
        storage = StorageConstruct(self, "Storage")

        # Database layer: DynamoDB sessions table
        database = DatabaseConstruct(self, "Database")

        # SageMaker layer: Studio Domain with execution role and lifecycle config
        sagemaker_domain = SageMakerConstruct(
            self,
            "SageMaker",
            vpc=network.vpc,
            shared_data_bucket=storage.shared_data_bucket,
            user_workspace_bucket=storage.user_workspace_bucket,
            # jupyter-server-3 is a FIRST-PARTY image, whose owning account is a
            # different series from the SageMaker Distribution accounts AND differs per
            # region (us-west-2 236514542706, us-east-1 081325390199, ...). It was
            # pinned to the us-west-2 account, so every other region got an ARN for an
            # image that does not exist. Resolved from the shared table instead.
            sagemaker_image_arn=self.node.try_get_context("sagemaker_image_arn")
            or first_party_image_arn(self.region, "jupyter-server-3"),
        )

        admin_dashboard = DashboardConstruct(
            self,
            "AdminDashboard",
            bucket_name=f"av30lab-admin-dashboard-{cdk.Aws.ACCOUNT_ID}-{cdk.Aws.REGION}",
        )

        user_dashboard = DashboardConstruct(
            self,
            "UserDashboard",
            bucket_name=f"av30lab-user-dashboard-{cdk.Aws.ACCOUNT_ID}-{cdk.Aws.REGION}",
        )

        # Auth layer: Cognito User Pool + hosted UI + WAF WebACL with IP allowlist.
        # Declared AFTER the dashboards because the user-pool client's callback and
        # logout URLs must be the admin SPA's own origin. The dependency is one-way —
        # DashboardConstruct takes only a bucket name and never references Cognito — so
        # there is no cycle; CloudFormation resolves the CloudFront domain at deploy.
        auth = AuthConstruct(
            self,
            "Auth",
            dashboard_url=admin_dashboard.url,
            # The hosted-UI prefix namespace is PER REGION, not global — verified:
            # av30lab-admin is ACTIVE in us-west-2 and free in ap-northeast-2,
            # eu-west-1 and us-east-1 (the region is part of the hostname,
            # <prefix>.auth.<region>.amazoncognito.com). So a second region can reuse
            # the same prefix and needs no rename. Overridable anyway, for the case
            # where another AWS account has already taken it in the target region.
            hosted_ui_prefix=(
                self.node.try_get_context("hosted_ui_prefix") or "av30lab-admin"
            ),
        )

        # Monitoring layer: SNS notifications + daily budget alarm
        monitoring = MonitoringConstruct(self, "Monitoring")

        # API layer: API Gateway + Lambda functions + authorizers
        api = ApiConstruct(
            self,
            "Api",
            user_pool=auth.user_pool,
            sessions_table=database.sessions_table,
            shared_data_bucket=storage.shared_data_bucket,
            user_workspace_bucket=storage.user_workspace_bucket,
            sagemaker_domain_id=sagemaker_domain.domain_id,
            sagemaker_execution_role=sagemaker_domain.execution_role,
            notebook_lifecycle_config_arn=sagemaker_domain.notebook_lifecycle_config_arn,
        )

        # Attach WAF (REGIONAL) to API Gateway stage for IP allowlist enforcement
        # Only created when admin_ip_allowlist is set to specific IPs (not 0.0.0.0/0)
        if auth.waf_enabled:
            wafv2.CfnWebACLAssociation(
                self,
                "WafApiAssociation",
                resource_arn=f"arn:aws:apigateway:{cdk.Aws.REGION}::/restapis/{api.api.rest_api_id}/stages/{api.api.deployment_stage.stage_name}",
                web_acl_arn=auth.web_acl_arn,
            )

        # Dashboard layer: Admin and User dashboards (WAF is on API Gateway, not CloudFront)
        # Region-suffixed like the data buckets: S3 names are globally unique, so an
        # account-only name collides the moment this stack is deployed to a second
        # region. These are control-plane resources and will move to the control-plane
        # stack, where only one copy exists — the suffix is harmless there and
        # prevents a collision during the transition. scripts/deploy.sh reads both
        # names from the AdminBucketName / UserBucketName stack outputs, so nothing
        # hardcodes them.

        # Stack outputs for cross-stack references and operational visibility
        cdk.CfnOutput(self, "VpcId", value=network.vpc.vpc_id)
        cdk.CfnOutput(self, "KmsKeyArn", value=storage.kms_key.key_arn)
        cdk.CfnOutput(
            self,
            "SharedDataBucketArn",
            value=storage.shared_data_bucket.bucket_arn,
        )
        cdk.CfnOutput(
            self,
            "UserWorkspaceBucketArn",
            value=storage.user_workspace_bucket.bucket_arn,
        )
        cdk.CfnOutput(
            self, "SessionsTableArn", value=database.sessions_table.table_arn
        )
        cdk.CfnOutput(
            self, "SageMakerDomainId", value=sagemaker_domain.domain_id
        )
        cdk.CfnOutput(
            self,
            "SageMakerExecutionRoleArn",
            value=sagemaker_domain.execution_role.role_arn,
        )
        cdk.CfnOutput(
            self,
            "SageMakerLifecycleConfigArn",
            value=sagemaker_domain.lifecycle_config_arn,
        )
        cdk.CfnOutput(
            self,
            "SageMakerNotebookLifecycleConfigArn",
            value=sagemaker_domain.notebook_lifecycle_config_arn,
        )
        cdk.CfnOutput(
            self, "UserPoolId", value=auth.user_pool.user_pool_id
        )
        cdk.CfnOutput(
            self,
            "UserPoolClientId",
            value=auth.user_pool_client.user_pool_client_id,
        )
        if auth.waf_enabled:
            cdk.CfnOutput(self, "WebAclArn", value=auth.web_acl_arn)
        cdk.CfnOutput(
            self, "AdminSnsTopicArn", value=monitoring.sns_topic.topic_arn
        )
        cdk.CfnOutput(self, "ApiUrl", value=api.api_url)
        cdk.CfnOutput(
            self,
            "AdminBucketName",
            value=admin_dashboard.bucket.bucket_name,
        )
        cdk.CfnOutput(
            self,
            "UserBucketName",
            value=user_dashboard.bucket.bucket_name,
        )
        cdk.CfnOutput(
            self,
            "AdminDistributionId",
            value=admin_dashboard.distribution.distribution_id,
        )
        cdk.CfnOutput(
            self,
            "UserDistributionId",
            value=user_dashboard.distribution.distribution_id,
        )
        cdk.CfnOutput(self, "AdminUrl", value=admin_dashboard.url)
        # Hosted-UI base URL. scripts/deploy.sh used to hardcode
        # "https://av30lab-admin.auth.${REGION}.amazoncognito.com" — which is why the
        # domain being absent from the CDK went unnoticed for so long: the generated
        # config.json always looked right, and only the redirect failed at runtime.
        cdk.CfnOutput(self, "CognitoHostedUiUrl", value=auth.hosted_ui_url)
        cdk.CfnOutput(self, "UserUrl", value=user_dashboard.url)
