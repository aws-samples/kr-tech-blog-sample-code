import { CfnOutput, RemovalPolicy, Stack, StackProps, Tags } from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as eks from 'aws-cdk-lib/aws-eks';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import versions from '../config/versions.json';
import albPolicy from './policies/load-balancer-controller.json';

export interface PlatformStackProps extends StackProps {
  readonly adminArn: string;
  readonly adminCidr: string;
}

export class PlatformStack extends Stack {
  constructor(scope: Construct, id: string, props: PlatformStackProps) {
    super(scope, id, props);
    const adminCidrs = props.adminCidr.split(',');
    if (adminCidrs.some(cidr => !/^\d{1,3}(\.\d{1,3}){3}\/32$/.test(cidr)
      || cidr.split('/')[0].split('.').some(octet => Number(octet) > 255))) {
      throw new Error('The demo requires explicit administrator IPv4 /32 CIDRs.');
    }
    const prefix = 'eks-ack-agentcore';
    Tags.of(this).add('Project', prefix);
    Tags.of(this).add('Purpose', 'aws-tech-blog-kr');
    const vpc = new ec2.Vpc(this, 'Vpc', {
      maxAzs: 2,
      natGateways: 1,
      ipAddresses: ec2.IpAddresses.cidr('10.83.0.0/16'),
      subnetConfiguration: [
        { name: 'public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
        { name: 'private', subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS, cidrMask: 24 },
      ],
    });
    vpc.publicSubnets.forEach(subnet => Tags.of(subnet).add('kubernetes.io/role/elb', '1'));
    vpc.privateSubnets.forEach(subnet => Tags.of(subnet).add('kubernetes.io/role/internal-elb', '1'));
    const flowLogs = new logs.LogGroup(this, 'VpcFlowLogs', {
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    vpc.addFlowLog('FlowLogs', { destination: ec2.FlowLogDestination.toCloudWatchLogs(flowLogs) });
    vpc.addGatewayEndpoint('S3Endpoint', { service: ec2.GatewayVpcEndpointAwsService.S3 });
    const clusterRole = new iam.Role(this, 'ClusterRole', {
      assumedBy: new iam.ServicePrincipal('eks.amazonaws.com'),
      managedPolicies: [iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonEKSClusterPolicy')],
    });
    const cluster = new eks.CfnCluster(this, 'Cluster', {
      name: prefix,
      version: versions.kubernetes,
      roleArn: clusterRole.roleArn,
      accessConfig: { authenticationMode: 'API', bootstrapClusterCreatorAdminPermissions: false },
      resourcesVpcConfig: {
        subnetIds: vpc.privateSubnets.map(subnet => subnet.subnetId),
        endpointPrivateAccess: true,
        endpointPublicAccess: true,
        publicAccessCidrs: adminCidrs,
      },
      logging: { clusterLogging: { enabledTypes: ['api', 'audit', 'authenticator', 'controllerManager', 'scheduler'].map(type => ({ type })) } },
      upgradePolicy: { supportType: 'STANDARD' },
    });
    new eks.CfnAccessEntry(this, 'AdminAccess', {
      clusterName: cluster.ref,
      principalArn: props.adminArn,
      type: 'STANDARD',
      accessPolicies: [{ policyArn: `arn:${this.partition}:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy`, accessScope: { type: 'cluster' } }],
    });
    const nodeRole = new iam.Role(this, 'NodeRole', {
      assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
      managedPolicies: ['AmazonEKSWorkerNodePolicy', 'AmazonEC2ContainerRegistryPullOnly'].map(name => iam.ManagedPolicy.fromAwsManagedPolicyName(name)),
    });
    const launchTemplate = new ec2.CfnLaunchTemplate(this, 'NodeLaunchTemplate', {
      launchTemplateData: {
        metadataOptions: { httpEndpoint: 'enabled', httpTokens: 'required', httpPutResponseHopLimit: 1 },
        blockDeviceMappings: [{ deviceName: '/dev/xvda', ebs: { encrypted: true, volumeSize: 40, volumeType: 'gp3', deleteOnTermination: true } }],
      },
    });
    const nodegroup = new eks.CfnNodegroup(this, 'Nodes', {
      clusterName: cluster.ref,
      nodeRole: nodeRole.roleArn,
      subnets: vpc.privateSubnets.map(subnet => subnet.subnetId),
      amiType: 'AL2023_ARM_64_STANDARD',
      instanceTypes: ['m7g.large'],
      capacityType: 'ON_DEMAND',
      scalingConfig: { minSize: 2, desiredSize: 2, maxSize: 3 },
      launchTemplate: { id: launchTemplate.ref, version: launchTemplate.attrLatestVersionNumber },
      updateConfig: { maxUnavailable: 1 },
    });
    const podRole = (name: string) => new iam.Role(this, name, {
      assumedBy: new iam.ServicePrincipal('pods.eks.amazonaws.com', { conditions: { StringEquals: { 'aws:SourceAccount': this.account } } }),
    });
    const addPodTrust = (role: iam.Role) => role.assumeRolePolicy?.addStatements(new iam.PolicyStatement({
      principals: [new iam.ServicePrincipal('pods.eks.amazonaws.com')],
      actions: ['sts:TagSession'],
      conditions: { StringEquals: { 'aws:SourceAccount': this.account } },
    }));
    const cniRole = podRole('CniRole');
    addPodTrust(cniRole);
    cniRole.addManagedPolicy(iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonEKS_CNI_Policy'));
    const identityAddon = new eks.CfnAddon(this, 'PodIdentityAddon', {
      clusterName: cluster.ref, addonName: 'eks-pod-identity-agent', addonVersion: versions.addons['eks-pod-identity-agent'], resolveConflicts: 'OVERWRITE',
    });
    identityAddon.addResourceDependency(nodegroup);
    for (const [name, version] of Object.entries(versions.addons)) {
      if (name === 'eks-pod-identity-agent') continue;
      const addon = new eks.CfnAddon(this, `Addon-${name}`, {
        clusterName: cluster.ref, addonName: name, addonVersion: version, resolveConflicts: 'OVERWRITE',
        ...(name === 'vpc-cni' ? { podIdentityAssociations: [{ roleArn: cniRole.roleArn, serviceAccount: 'aws-node' }] } : {}),
      });
      addon.addResourceDependency(identityAddon);
    }
    if (process.env.CNI_BOOTSTRAP !== 'false') {
      nodeRole.addManagedPolicy(iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonEKS_CNI_Policy'));
    }
    const repository = new ecr.Repository(this, 'AgentRepository', {
      repositoryName: prefix,
      imageScanOnPush: true,
      imageTagMutability: ecr.TagMutability.IMMUTABLE,
      encryption: ecr.RepositoryEncryption.AES_256,
      lifecycleRules: [{ tagStatus: ecr.TagStatus.UNTAGGED, maxImageCount: 20 }],
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const runtimeArn = `arn:${this.partition}:bedrock-agentcore:${this.region}:${this.account}:runtime/eks_ack_*`;
    const executionRole = new iam.Role(this, 'AgentExecutionRole', {
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com', { conditions: {
        StringEquals: { 'aws:SourceAccount': this.account },
        ArnLike: { 'aws:SourceArn': runtimeArn },
      } }),
    });
    repository.grantPull(executionRole);
    executionRole.addToPolicy(new iam.PolicyStatement({ actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'], resources: [
      `arn:${this.partition}:bedrock:${this.region}:${this.account}:inference-profile/${versions.modelId}`,
      `arn:${this.partition}:bedrock:*::foundation-model/${versions.foundationModelId}`,
    ] }));
    executionRole.addToPolicy(new iam.PolicyStatement({ actions: ['logs:CreateLogGroup', 'logs:DescribeLogStreams', 'logs:CreateLogStream', 'logs:PutLogEvents'], resources: [`arn:${this.partition}:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/runtimes/eks_ack_*`] }));
    executionRole.addToPolicy(new iam.PolicyStatement({ actions: ['logs:DescribeLogGroups'], resources: ['*'] }));
    executionRole.addToPolicy(new iam.PolicyStatement({ actions: ['bedrock-agentcore:GetWorkloadAccessToken'], resources: [
      `arn:${this.partition}:bedrock-agentcore:${this.region}:${this.account}:workload-identity-directory/default`,
      `arn:${this.partition}:bedrock-agentcore:${this.region}:${this.account}:workload-identity-directory/default/workload-identity/*`,
    ] }));
    const ackRole = podRole('AckRole');
    addPodTrust(ackRole);
    ackRole.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock-agentcore:CreateAgentRuntime'],
      resources: ['*'],
      conditions: { StringEquals: { 'aws:RequestTag/Project': prefix, 'aws:RequestedRegion': this.region } },
    }));
    ackRole.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock-agentcore:CreateAgentRuntimeEndpoint'],
      resources: [`arn:${this.partition}:bedrock-agentcore:${this.region}:${this.account}:runtime/*`],
      conditions: { StringEquals: { 'aws:RequestedRegion': this.region } },
    }));
    ackRole.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock-agentcore:TagResource'],
      resources: [`arn:${this.partition}:bedrock-agentcore:${this.region}:${this.account}:runtime/*`],
      conditions: { StringEquals: { 'aws:RequestTag/Project': prefix, 'aws:RequestedRegion': this.region } },
    }));
    ackRole.addToPolicy(new iam.PolicyStatement({ actions: [
      'bedrock-agentcore:GetAgentRuntime', 'bedrock-agentcore:UpdateAgentRuntime', 'bedrock-agentcore:DeleteAgentRuntime',
      'bedrock-agentcore:GetAgentRuntimeEndpoint', 'bedrock-agentcore:UpdateAgentRuntimeEndpoint', 'bedrock-agentcore:DeleteAgentRuntimeEndpoint',
      'bedrock-agentcore:ListAgentRuntimeVersions', 'bedrock-agentcore:ListAgentRuntimeEndpoints',
      'bedrock-agentcore:TagResource', 'bedrock-agentcore:UntagResource', 'bedrock-agentcore:ListTagsForResource',
    ], resources: [runtimeArn] }));
    ackRole.addToPolicy(new iam.PolicyStatement({ actions: ['bedrock-agentcore:CreateWorkloadIdentity', 'bedrock-agentcore:GetWorkloadIdentity', 'bedrock-agentcore:DeleteWorkloadIdentity', 'bedrock-agentcore:TagResource'], resources: [
      `arn:${this.partition}:bedrock-agentcore:${this.region}:${this.account}:workload-identity-directory/default`,
      `arn:${this.partition}:bedrock-agentcore:${this.region}:${this.account}:workload-identity-directory/default/workload-identity/*`,
    ] }));
    ackRole.addToPolicy(new iam.PolicyStatement({ actions: ['iam:PassRole'], resources: [executionRole.roleArn], conditions: { StringEquals: { 'iam:PassedToService': 'bedrock-agentcore.amazonaws.com' } } }));
    const gatewayArn = `arn:${this.partition}:bedrock-agentcore:${this.region}:${this.account}:gateway/eks-ack-devops-*`;
    const gatewayRole = new iam.Role(this, 'GatewayExecutionRole', {
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com', { conditions: {
        StringEquals: { 'aws:SourceAccount': this.account }, ArnLike: { 'aws:SourceArn': gatewayArn },
      } }),
    });
    gatewayRole.addToPolicy(new iam.PolicyStatement({ actions: ['bedrock-agentcore:InvokeAgentRuntime'], resources: [runtimeArn] }));
    ackRole.addToPolicy(new iam.PolicyStatement({ actions: ['bedrock-agentcore:CreateGateway'], resources: ['*'], conditions: {
      StringEquals: { 'aws:RequestedRegion': this.region, 'aws:RequestTag/Project': prefix },
    } }));
    ackRole.addToPolicy(new iam.PolicyStatement({ actions: ['bedrock-agentcore:TagResource'], resources: [`arn:${this.partition}:bedrock-agentcore:${this.region}:${this.account}:gateway/*`], conditions: {
      StringEquals: { 'aws:RequestTag/Project': prefix },
    } }));
    ackRole.addToPolicy(new iam.PolicyStatement({ actions: [
      'bedrock-agentcore:GetGateway', 'bedrock-agentcore:UpdateGateway', 'bedrock-agentcore:DeleteGateway',
      'bedrock-agentcore:CreateGatewayTarget', 'bedrock-agentcore:GetGatewayTarget', 'bedrock-agentcore:UpdateGatewayTarget', 'bedrock-agentcore:DeleteGatewayTarget', 'bedrock-agentcore:ListGatewayTargets',
      'bedrock-agentcore:TagResource', 'bedrock-agentcore:UntagResource', 'bedrock-agentcore:ListTagsForResource',
    ], resources: [gatewayArn] }));
    ackRole.addToPolicy(new iam.PolicyStatement({ actions: ['iam:PassRole'], resources: [gatewayRole.roleArn], conditions: { StringEquals: { 'iam:PassedToService': 'bedrock-agentcore.amazonaws.com' } } }));
    const checkerRole = podRole('GatewayCheckerRole');
    addPodTrust(checkerRole);
    checkerRole.addToPolicy(new iam.PolicyStatement({ actions: ['bedrock-agentcore:InvokeGateway', 'bedrock-agentcore:GetGateway'], resources: [gatewayArn] }));
    checkerRole.addToPolicy(new iam.PolicyStatement({ actions: ['bedrock-agentcore:GetAgentRuntime', 'bedrock-agentcore:GetAgentRuntimeEndpoint'], resources: [runtimeArn] }));
    checkerRole.addToPolicy(new iam.PolicyStatement({ actions: ['bedrock-agentcore:ListGateways'], resources: ['*'], conditions: { StringEquals: { 'aws:RequestedRegion': this.region } } }));
    const albRole = podRole('LoadBalancerRole');
    addPodTrust(albRole);
    new iam.Policy(this, 'LoadBalancerPolicy', { roles: [albRole], document: iam.PolicyDocument.fromJson(albPolicy) });
    for (const [name, namespace, serviceAccount, role] of [
      ['AckIdentity', 'agentcore', 'ack-agentcore', ackRole],
      ['AlbIdentity', 'kube-system', 'aws-load-balancer-controller', albRole],
      ['CheckerIdentity', 'agentcore', 'gateway-check', checkerRole],
    ] as const) {
      const association = new eks.CfnPodIdentityAssociation(this, name, { clusterName: cluster.ref, namespace, serviceAccount, roleArn: role.roleArn });
      association.addResourceDependency(identityAddon);
    }
    new CfnOutput(this, 'ClusterName', { value: cluster.ref });
    new CfnOutput(this, 'VpcId', { value: vpc.vpcId });
    new CfnOutput(this, 'RepositoryUri', { value: repository.repositoryUri });
    new CfnOutput(this, 'ExecutionRoleArn', { value: executionRole.roleArn });
    new CfnOutput(this, 'GatewayExecutionRoleArn', { value: gatewayRole.roleArn });
    new CfnOutput(this, 'AdminCidr', { value: props.adminCidr });
    new CfnOutput(this, 'Region', { value: this.region });
  }
}
