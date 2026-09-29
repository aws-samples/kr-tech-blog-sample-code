import { App } from 'aws-cdk-lib';
import { PlatformStack } from './platform-stack';

const app = new App();
const account = process.env.CDK_DEFAULT_ACCOUNT;
const region = process.env.AWS_REGION ?? process.env.CDK_DEFAULT_REGION ?? 'us-east-1';
const adminArn = process.env.ADMIN_PRINCIPAL_ARN;
const adminCidr = process.env.ADMIN_CIDR;
if (!account || !adminArn || !adminCidr) {
  throw new Error('Set CDK_DEFAULT_ACCOUNT, ADMIN_PRINCIPAL_ARN, and ADMIN_CIDR before synthesis.');
}
new PlatformStack(app, 'EksAckAgentCore', {
  env: { account, region },
  adminArn,
  adminCidr,
});
