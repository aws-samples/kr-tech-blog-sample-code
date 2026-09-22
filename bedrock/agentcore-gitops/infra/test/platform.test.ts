import { App } from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { test } from 'node:test';
import { throws } from 'node:assert/strict';
import { PlatformStack } from '../platform-stack';

test('foundation limits access and keeps agents off worker nodes', () => {
  const stack = new PlatformStack(new App(), 'Test', {
    env: { account: '123456789012', region: 'us-east-1' },
    adminArn: 'arn:aws:iam::123456789012:role/Admin', adminCidr: '192.0.2.1/32',
  });
  const template = Template.fromStack(stack);
  template.hasResourceProperties('AWS::EKS::Cluster', {
    Version: '1.36',
    ResourcesVpcConfig: { PublicAccessCidrs: ['192.0.2.1/32'], EndpointPrivateAccess: true },
    AccessConfig: { AuthenticationMode: 'API', BootstrapClusterCreatorAdminPermissions: false },
  });
  template.hasResourceProperties('AWS::ECR::Repository', { ImageTagMutability: 'IMMUTABLE', ImageScanningConfiguration: { ScanOnPush: true } });
  template.resourceCountIs('AWS::EKS::PodIdentityAssociation', 3);
  template.resourceCountIs('AWS::BedrockAgentCore::Runtime', 0);
  template.resourceCountIs('AWS::BedrockAgentCore::Gateway', 0);
  template.hasResourceProperties('AWS::IAM::Policy', {
    PolicyDocument: { Statement: Match.arrayWith([Match.objectLike({
      Action: 'bedrock-agentcore:CreateAgentRuntime', Resource: '*',
      Condition: { StringEquals: { 'aws:RequestTag/Project': 'eks-ack-agentcore', 'aws:RequestedRegion': 'us-east-1' } },
    })]) },
  });
});

test('invalid or broad administrator CIDRs are rejected', () => {
  for (const adminCidr of ['0.0.0.0/0', '192.0.2.1/24', '999.1.1.1/32']) {
    throws(() => new PlatformStack(new App(), 'Invalid', {
      env: { account: '123456789012', region: 'us-east-1' },
      adminArn: 'arn:aws:iam::123456789012:role/Admin', adminCidr,
    }), /explicit administrator IPv4/);
  }
});

test('image lifecycle preserves tagged release and controller images', () => {
  const stack = new PlatformStack(new App(), 'ImageRetention', {
    env: { account: '123456789012', region: 'us-east-1' },
    adminArn: 'arn:aws:iam::123456789012:role/Admin', adminCidr: '192.0.2.1/32',
  });
  const template = Template.fromStack(stack).toJSON();
  const repository = Object.values(template.Resources).find((resource: any) => resource.Type === 'AWS::ECR::Repository') as any;
  const policy = JSON.parse(repository.Properties.LifecyclePolicy.LifecyclePolicyText);
  if (policy.rules.some((rule: any) => rule.selection.tagStatus !== 'untagged')) {
    throw new Error('Lifecycle rules must not expire tagged release images');
  }
});
