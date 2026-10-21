"""AV 3.0 Blueprint Lab - Network Construct.

Private-only, NAT-free VPC. Only the S3 *gateway* endpoint is created by default;
the interface endpoints are opt-in via `vpc_interface_endpoints=True`.

WHY THE INTERFACE ENDPOINTS DEFAULT TO OFF
------------------------------------------
An interface endpoint only earns its cost if something *inside this VPC* calls the
service through it. Verified in this repo, nothing does:

  * The Lambdas are NOT in the VPC — `vpc` appears zero times in
    av30_constructs/api.py, so all 14 functions run in the AWS-managed Lambda
    network and cannot reach an endpoint in this VPC at all.
  * The SageMaker Domain is the VPC's ONLY consumer (av30_stack.py passes
    `vpc=network.vpc` to SageMakerConstruct and nowhere else), and it is created
    with `app_network_access_type="PublicInternetOnly"`. In that mode Studio
    traffic egresses through a SageMaker-MANAGED VPC; ours carries only
    EFS/home-directory traffic. So notebook calls to SageMaker/ECR/CloudWatch/STS
    never traverse these endpoints either.

Each interface endpoint bills $0.01 per AZ-hour, so 6 services x 2 AZs = 12 ENIs
= ~$87.60/month, per region, for no consumer. The S3 gateway endpoint is free and
IS used (bucket access from the notebooks), so it is always created.

WHEN TO TURN THEM BACK ON
-------------------------
Pass `vpc_interface_endpoints=True` if the domain is switched to
`app_network_access_type="VpcOnly"`. In that mode Studio egresses ONLY through
this VPC, and without at least the sagemaker.api and sagemaker.runtime endpoints
the JupyterLab app will not start. The same applies if the Lambdas are ever
attached to the VPC.
"""

from constructs import Construct

import aws_cdk as cdk
from aws_cdk import (
    aws_ec2 as ec2,
)


class NetworkConstruct(Construct):
    """VPC with isolated private subnets, an S3 gateway endpoint, and optional
    interface endpoints.

    Args:
        vpc_interface_endpoints: Create the 6 paid interface endpoints
            (sagemaker.api, sagemaker.runtime, ecr.api, ecr.dkr, logs, sts).
            Defaults to False — see the module docstring for why, and turn it on
            if the domain moves to VpcOnly or the Lambdas join the VPC.

    Attributes:
        vpc: The VPC resource.
        endpoints_security_group: Security group for the interface endpoints. It
            is created even when the endpoints are not, so callers (and a later
            VpcOnly switch) have a stable handle.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc_interface_endpoints: bool = False,
    ) -> None:
        super().__init__(scope, construct_id)

        # Private-only VPC — no public subnets, no NAT.
        #
        # ALL AZs, not 2. A Studio app can only launch in an AZ the domain has a subnet in,
        # so max_azs directly caps the GPU capacity pool the lab can draw from, and
        # EC2InsufficientCapacityError is the lab's most common real failure. The GPU types
        # are NOT offered in every AZ, and the gap was severe at max_azs=2 (measured
        # 2026-09-25 in account <aws-account-id>, via describe-instance-type-offerings on
        # availability-zone-id, which is stable across accounts unlike the a/b/c names):
        #
        #   ap-northeast-2  g5.12xlarge sold in apne2-az1, az3, az4 — apne2-az2 sells NO
        #                   g5/g6 at all. max_azs=2 picks az1+az2, so the domain reached
        #                   1 of 3 GPU AZs and every heavy module competed in ONE AZ.
        #   us-west-2       g5.12xlarge sold in usw2-az1, az2, az3; max_azs=2 reached 2 of 3.
        #
        # Measured consequence, same day: g5.12xlarge, g5.24xlarge AND g6.24xlarge all
        # returned "temporarily unavailable in supported availability zones [usw2-az2,
        # usw2-az1]" — the only two the domain had — while quota was 5 and usage 0. Three
        # types, one shortage, zero alternatives reachable.
        #
        # Safe to widen on a LIVE domain: AWS::SageMaker::Domain SubnetIds is documented
        # "Update requires: No interruption", so the domain is not replaced and its EFS is
        # not orphaned. Existing subnets keep their CIDRs and logical IDs — CDK allocates
        # per AZ index and appends, so this adds subnets rather than renumbering them.
        # Free here: PRIVATE_ISOLATED, nat_gateways=0. The one cost to know about is
        # vpc_interface_endpoints=True, which places an ENI per subnet — that line roughly
        # doubles going from 2 AZs to 4.
        self._vpc = ec2.Vpc(
            self,
            "Vpc",
            vpc_name="av30lab-vpc",
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/16"),
            max_azs=99,  # CDK clamps to the region's AZ count (4 in both lab regions)
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24,
                ),
            ],
        )

        # Security group for VPC interface endpoints — allows HTTPS from within VPC
        self._endpoints_sg = ec2.SecurityGroup(
            self,
            "EndpointsSg",
            vpc=self._vpc,
            description="Allow HTTPS inbound for VPC interface endpoints",
            allow_all_outbound=False,
        )
        self._endpoints_sg.add_ingress_rule(
            peer=ec2.Peer.ipv4(self._vpc.vpc_cidr_block),
            connection=ec2.Port.tcp(443),
            description="HTTPS from VPC CIDR",
        )

        # Gateway endpoint: S3. ALWAYS created — it is free, and it is required the
        # moment the domain moves to VpcOnly.
        #
        # It is NOT, today, on the notebooks' path, and two earlier claims here were
        # wrong (verified 2026-09-24):
        #
        #   "the notebooks do use it"  — they do not. The domain is
        #   AppNetworkAccessType=PublicInternetOnly in both live regions, so app traffic
        #   egresses through the SageMaker-MANAGED VPC, not this one. The only ENIs in
        #   these subnets are the two EFS mount targets.
        #
        #   "which is why every region needs its own buckets" — true premise, wrong
        #   conclusion. A gateway endpoint does serve only its own region's S3 (the route
        #   tables here carry just 10.0.0.0/16 local plus the local S3 prefix list —
        #   pl-68a54001 in us-west-2, pl-78a54011 in ap-northeast-2, disjoint CIDR sets —
        #   with no IGW and no NAT), but since the notebooks are not in these subnets that
        #   is not what forces per-region buckets. The real reasons are S3's GLOBAL
        #   bucket-name namespace (see storage.py) plus cross-region GET latency and
        #   $0.02/GB transfer-out on ~157 GB of model cache — which the module docstring
        #   above already says.
        self._vpc.add_gateway_endpoint(
            "S3Endpoint",
            service=ec2.GatewayVpcEndpointAwsService.S3,
        )

        # Interface endpoints — opt-in, $0.01 per AZ-hour each. See module docstring.
        if vpc_interface_endpoints:
            interface_services = {
                "SageMakerApi": ec2.InterfaceVpcEndpointAwsService.SAGEMAKER_API,
                "SageMakerRuntime": ec2.InterfaceVpcEndpointAwsService.SAGEMAKER_RUNTIME,
                "EcrApi": ec2.InterfaceVpcEndpointAwsService.ECR,
                "EcrDkr": ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER,
                "CloudWatchLogs": ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
                "Sts": ec2.InterfaceVpcEndpointAwsService.STS,
            }
            for endpoint_id, service in interface_services.items():
                self._vpc.add_interface_endpoint(
                    endpoint_id,
                    service=service,
                    private_dns_enabled=True,
                    security_groups=[self._endpoints_sg],
                )

    @property
    def vpc(self) -> ec2.Vpc:
        """The VPC resource."""
        return self._vpc

    @property
    def endpoints_security_group(self) -> ec2.SecurityGroup:
        """Security group attached to VPC interface endpoints."""
        return self._endpoints_sg
