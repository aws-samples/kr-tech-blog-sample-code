"""AV 3.0 Blueprint Lab - Auth Construct.

Cognito User Pool (admin-only), User Pool Client, WAF WebACL with IP allowlist.
"""

from constructs import Construct

import aws_cdk as cdk
from aws_cdk import (
    aws_cognito as cognito,
    aws_wafv2 as wafv2,
)


class AuthConstruct(Construct):
    """Authentication and WAF protection for admin dashboard.

    Attributes:
        user_pool: Cognito User Pool with strict password policy (admin-only).
        user_pool_client: App client for admin dashboard SPA.
        web_acl_arn: ARN of the WAF WebACL (REGIONAL scope — it attaches to API Gateway,
            not CloudFront) with IP allowlist, or None when the allowlist is 0.0.0.0/0.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        dashboard_url: str,
        hosted_ui_prefix: str = "av30lab-admin",
    ) -> None:
        """
        Args:
            dashboard_url: Origin of the admin SPA (the admin CloudFront URL). Becomes
                the client's callback/logout URL. REQUIRED: without it Cognito rejects
                every /oauth2/authorize request, and it is the single reason a fresh
                account could not sign in — the live pool had these URLs set BY HAND
                and the CDK never knew about them.
            hosted_ui_prefix: Cognito hosted-UI domain prefix. Unique across all AWS
                accounts WITHIN A REGION — not globally. The region is part of the
                hostname (<prefix>.auth.<region>.amazoncognito.com), so there is no
                shared name to contend for and ONE account can hold the SAME prefix in
                several regions simultaneously. Verified: "av30lab-admin" is ACTIVE in
                both us-west-2 and ap-northeast-2 of account <aws-account-id>, fronting
                different pools. So a second region needs NO rename.
                The SPA builds ${cognitoDomain}/oauth2/authorize from it.

                Probing a target region, read `describe-user-pool-domain` like this:
                  HTTP 200 + populated DomainDescription -> already ours
                  HTTP 200 + EMPTY DomainDescription     -> free
                  ResourceNotFoundException              -> taken by ANOTHER account
                Only the third case requires a different prefix.
        """
        super().__init__(scope, construct_id)

        # Cognito User Pool — admin-only with strict password policy
        self._user_pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name="av30lab-admin-pool",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True,
                require_lowercase=True,
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # User Pool Client for admin dashboard SPA (no secret for public client)
        self._user_pool_client = cognito.UserPoolClient(
            self,
            "UserPoolClient",
            user_pool=self._user_pool,
            user_pool_client_name="av30lab-admin-dashboard",
            generate_secret=False,
            auth_flows=cognito.AuthFlow(
                user_srp=True,
                user_password=False,
            ),
            o_auth=cognito.OAuthSettings(
                # Authorization code + PKCE, NOT implicit. The client has no secret,
                # so PKCE is the correct SPA flow; implicit returns the access token in
                # the URL fragment (browser history, extensions, Referer) and is removed
                # in OAuth 2.1. The live pool had drifted to implicit-only because the
                # SPA was written against it; the SPA now does the code exchange.
                flows=cognito.OAuthFlows(
                    authorization_code_grant=True,
                    implicit_code_grant=False,
                ),
                # PROFILE is required: CognitoProvider requests "openid email profile",
                # and Cognito rejects the authorize call outright if a requested scope
                # is not allowed on the client. It was allowed live but missing here.
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE,
                ],
                callback_urls=[dashboard_url],
                logout_urls=[dashboard_url],
            ),
            prevent_user_existence_errors=True,
        )

        # Hosted UI domain. Absent from the CDK entirely until now — it existed only as
        # a hand-created resource, so `cdk deploy` into a fresh account produced a pool
        # with no sign-in endpoint and the SPA redirected to a host that does not
        # resolve. That was the single reason a new account could not sign in.
        #
        # `-c hosted_ui_domain_exists=true` skips declaring it, for the one deployment
        # that already has an UNMANAGED domain with this prefix. Adopting that one is
        # not possible without deleting it first: a CloudFormation IMPORT change set may
        # contain no other create/update/delete, and CFN reports ~60 unchanged resources
        # in this stack as "modified" during import validation (verified — plain
        # `cdk diff --method=template` reports 0 changes for the same template), so a
        # clean import change set cannot be produced.
        #
        # DO NOT set this flag for a new region. It is the most dangerous lever in this
        # file: skipping the domain declaration yields a user pool with NO sign-in
        # endpoint, and deploy.sh then aborts on the missing CognitoHostedUiUrl output.
        # It exists ONLY to accommodate the single pre-existing unmanaged domain in
        # us-west-2. A second region does not need it — the prefix is per-region (see
        # hosted_ui_prefix above), so CFN can simply create its own domain there, which
        # is exactly what happened in ap-northeast-2.
        self._hosted_ui_prefix = hosted_ui_prefix
        self._user_pool_domain = None
        if not self.node.try_get_context("hosted_ui_domain_exists"):
            self._user_pool_domain = self._user_pool.add_domain(
                "HostedUiDomain",
                cognito_domain=cognito.CognitoDomainOptions(
                    domain_prefix=hosted_ui_prefix,
                ),
            )

        # WAF IP allowlist from context parameter (comma-separated CIDRs)
        # Scope is REGIONAL — attached to API Gateway (not CloudFront).
        # If "0.0.0.0/0" (allow all) → skip WAF entirely (WAF IP Set rejects /0 notation)
        admin_ip_allowlist = self.node.try_get_context("admin_ip_allowlist") or "0.0.0.0/0"
        self._waf_enabled = admin_ip_allowlist.strip() != "0.0.0.0/0"

        if self._waf_enabled:
            ip_addresses = [cidr.strip() for cidr in admin_ip_allowlist.split(",")]

            self._ip_set = wafv2.CfnIPSet(
                self,
                "AdminIpSet",
                name="av30lab-admin-ip-allowlist",
                scope="REGIONAL",
                ip_address_version="IPV4",
                addresses=ip_addresses,
            )

            self._web_acl = wafv2.CfnWebACL(
                self,
                "WebAcl",
                name="av30lab-admin-waf",
                scope="REGIONAL",
                default_action=wafv2.CfnWebACL.DefaultActionProperty(block={}),
                visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                    cloud_watch_metrics_enabled=True,
                    metric_name="av30lab-admin-waf",
                    sampled_requests_enabled=True,
                ),
                rules=[
                    wafv2.CfnWebACL.RuleProperty(
                        name="AllowAdminIPs",
                        priority=0,
                        action=wafv2.CfnWebACL.RuleActionProperty(allow={}),
                        visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                            cloud_watch_metrics_enabled=True,
                            metric_name="av30lab-allow-admin-ips",
                            sampled_requests_enabled=True,
                        ),
                        statement=wafv2.CfnWebACL.StatementProperty(
                            ip_set_reference_statement=wafv2.CfnWebACL.IPSetReferenceStatementProperty(
                                arn=self._ip_set.attr_arn,
                            ),
                        ),
                    ),
                ],
            )

    @property
    def user_pool(self) -> cognito.UserPool:
        """Cognito User Pool for admin authentication."""
        return self._user_pool

    @property
    def user_pool_client(self) -> cognito.UserPoolClient:
        """App client for admin dashboard SPA."""
        return self._user_pool_client

    @property
    def hosted_ui_url(self) -> str:
        """Hosted-UI base URL, e.g. https://av30lab-admin.auth.us-west-2.amazoncognito.com.

        Exported so deploy.sh writes it into config.json as `cognitoDomain` instead of
        assuming the prefix exists — that assumption is what let the domain stay
        undeclared while the SPA kept building /oauth2/authorize against it.
        """
        if self._user_pool_domain is not None:
            return self._user_pool_domain.base_url()
        # hosted_ui_domain_exists=true: the domain is real but unmanaged, so derive the
        # URL from the prefix. Same string CDK would emit; deploy.sh still fails loudly
        # if this output is missing entirely.
        return (
            f"https://{self._hosted_ui_prefix}.auth."
            f"{cdk.Stack.of(self).region}.amazoncognito.com"
        )

    @property
    def waf_enabled(self) -> bool:
        """Whether WAF IP allowlist is active."""
        return self._waf_enabled

    @property
    def web_acl_arn(self) -> str | None:
        """ARN of the WAF WebACL (REGIONAL scope), or None if WAF disabled."""
        return self._web_acl.attr_arn if self._waf_enabled else None
