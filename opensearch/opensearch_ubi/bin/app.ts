#!/usr/bin/env node
/**
 * CDK App Entry Point - UBI to LTR Pipeline Infrastructure.
 *
 * This app deploys the complete infrastructure for:
 * 1. OpenSearch Service domain with UBI plugin support
 * 2. OSI (OpenSearch Ingestion) pipeline configurations
 * 3. S3 buckets for data storage
 * 4. Lambda functions for judgment generation
 * 5. Step Functions for pipeline orchestration
 *
 * Usage:
 *   npm run build
 *   cdk deploy --all
 *
 * Environment variables:
 *   CDK_DEFAULT_ACCOUNT - AWS account ID
 *   CDK_DEFAULT_REGION  - AWS region (default: us-east-1)
 *   ENV_PREFIX          - Environment prefix (default: dev)
 */

import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { IamStack } from '../lib/iam-stack';
import { StorageStack } from '../lib/storage-stack';
import { OpenSearchStack } from '../lib/opensearch-stack';
import { OsiStack } from '../lib/osi-stack';
import { ProcessingStack } from '../lib/processing-stack';
import { SetupStack } from '../lib/setup-stack';
import { WebappStack } from '../lib/webapp-stack';

const app = new cdk.App();

// ===========================================================================
// Configuration
// ===========================================================================
const envPrefix = app.node.tryGetContext('envPrefix') ?? process.env.ENV_PREFIX ?? 'dev';
const region = app.node.tryGetContext('region') ?? process.env.CDK_DEFAULT_REGION ?? 'us-east-1';
const account = process.env.CDK_DEFAULT_ACCOUNT ?? process.env.AWS_ACCOUNT_ID;

// OpenSearch configuration
const openSearchConfig = {
  version: app.node.tryGetContext('opensearchVersion') ?? '3.3',
  instanceType: app.node.tryGetContext('instanceType') ?? 't3.small.search',
  instanceCount: parseInt(app.node.tryGetContext('instanceCount') ?? '1'),
  ebsVolumeSize: parseInt(app.node.tryGetContext('ebsVolumeSize') ?? '20'),
  dedicatedMasterEnabled: app.node.tryGetContext('dedicatedMaster') === 'true',
  multiAzEnabled: app.node.tryGetContext('multiAz') === 'true',
};

// Processing configuration
const processingConfig = {
  bedrockModelId: app.node.tryGetContext('bedrockModelId') ?? 'us.anthropic.claude-sonnet-4-5-20250929-v1:0',
  enableSchedule: app.node.tryGetContext('enableSchedule') === 'true',
  scheduleExpression: app.node.tryGetContext('scheduleExpression') ?? 'rate(1 day)',
};

const env: cdk.Environment = {
  account,
  region,
};

console.log(`
===========================================================================
UBI to LTR Pipeline Infrastructure
===========================================================================
Environment:  ${envPrefix}
Region:       ${region}
Account:      ${account ?? 'Not specified (will use default)'}

OpenSearch Configuration:
  - Version:        ${openSearchConfig.version}
  - Instance Type:  ${openSearchConfig.instanceType}
  - Instance Count: ${openSearchConfig.instanceCount}
  - EBS Volume:     ${openSearchConfig.ebsVolumeSize} GB

Processing Configuration:
  - Bedrock Model:  ${processingConfig.bedrockModelId}
  - Scheduled:      ${processingConfig.enableSchedule}
===========================================================================
`);

// ===========================================================================
// Stack Deployment
// ===========================================================================

// 1. Storage Stack (S3 buckets)
const storageStack = new StorageStack(app, `UbiLtr-StorageStack-${envPrefix}`, {
  stackName: `${envPrefix}-ubi-ltr-storage`,
  description: 'S3 buckets for UBI-LTR pipeline data storage',
  env,
  envPrefix,
  iaTransitionDays: 30,
  retentionDays: 365,
  enableVersioning: true,
});

// 2. IAM Stack (roles and policies)
const iamStack = new IamStack(app, `UbiLtr-IamStack-${envPrefix}`, {
  stackName: `${envPrefix}-ubi-ltr-iam`,
  description: 'IAM roles and policies for UBI-LTR pipeline',
  env,
  envPrefix,
  dataBucketArn: storageStack.dataBucket.bucketArn,
});

// Add dependency
iamStack.addDependency(storageStack);

// 3. OpenSearch Stack (domain + OSI configs)
const openSearchStack = new OpenSearchStack(app, `UbiLtr-OpenSearchStack-${envPrefix}`, {
  stackName: `${envPrefix}-ubi-ltr-opensearch`,
  description: 'OpenSearch Service domain with UBI support',
  env,
  envPrefix,
  openSearchVersion: openSearchConfig.version,
  instanceType: openSearchConfig.instanceType,
  instanceCount: openSearchConfig.instanceCount,
  ebsVolumeSize: openSearchConfig.ebsVolumeSize,
  dedicatedMasterEnabled: openSearchConfig.dedicatedMasterEnabled,
  multiAzEnabled: openSearchConfig.multiAzEnabled,
  osiPipelineRoleArn: iamStack.osiPipelineRole.roleArn,
  dlqBucketArn: storageStack.dlqBucket.bucketArn,
});

// Add dependencies
openSearchStack.addDependency(iamStack);
openSearchStack.addDependency(storageStack);

// 3.5 OSI Stack (OpenSearch Ingestion pipelines for UBI)
const osiStack = new OsiStack(app, `UbiLtr-OsiStack-${envPrefix}`, {
  stackName: `${envPrefix}-ubi-ltr-osi`,
  description: 'OSI pipelines for UBI queries and events ingestion',
  env,
  envPrefix,
  openSearchEndpoint: openSearchStack.domainEndpoint,
  osiPipelineRoleArn: iamStack.osiPipelineRole.roleArn,
  dlqBucketName: storageStack.dlqBucket.bucketName,
});

// Add dependencies - OSI needs OpenSearch domain endpoint and IAM role
osiStack.addDependency(openSearchStack);
osiStack.addDependency(iamStack);
osiStack.addDependency(storageStack);

// 4. Processing Stack (Lambda + Step Functions)
// Pass role ARNs instead of role objects to avoid circular dependencies
const processingStack = new ProcessingStack(app, `UbiLtr-ProcessingStack-${envPrefix}`, {
  stackName: `${envPrefix}-ubi-ltr-processing`,
  description: 'Lambda functions and Step Functions for UBI-LTR pipeline',
  env,
  envPrefix,
  openSearchEndpoint: openSearchStack.domainEndpoint,
  masterUserSecretArn: openSearchStack.masterUserSecret.secretArn,
  dataBucket: storageStack.dataBucket,
  lambdaExecutionRoleArn: iamStack.lambdaExecutionRole.roleArn,
  stepFunctionsRoleArn: iamStack.stepFunctionsRole.roleArn,
  bedrockModelId: processingConfig.bedrockModelId,
  enableSchedule: processingConfig.enableSchedule,
  scheduleExpression: processingConfig.scheduleExpression,
});

// Add dependencies
processingStack.addDependency(openSearchStack);
processingStack.addDependency(iamStack);
processingStack.addDependency(storageStack);

// 5. Setup Stack (OpenSearch initialization)
// This stack creates indices, role mappings, and sample data
const setupStack = new SetupStack(app, `UbiLtr-SetupStack-${envPrefix}`, {
  stackName: `${envPrefix}-ubi-ltr-setup`,
  description: 'OpenSearch initialization with indices, role mappings, and sample data',
  env,
  envPrefix,
  openSearchEndpoint: openSearchStack.domainEndpoint,
  masterUserSecretArn: openSearchStack.masterUserSecret.secretArn,
  lambdaExecutionRoleArn: iamStack.lambdaExecutionRole.roleArn,
  osiPipelineRoleArn: iamStack.osiPipelineRole.roleArn,
});

// Add dependencies - setup must run after OpenSearch and IAM are ready
setupStack.addDependency(openSearchStack);
setupStack.addDependency(iamStack);

// 6. Webapp Stack (Lambda API + Frontend)
// Frontend deployment is enabled by default - requires: cd webapp/frontend && npm run build
const deployFrontend = app.node.tryGetContext('deployFrontend') !== 'false';
const webappStack = new WebappStack(app, `UbiLtr-WebappStack-${envPrefix}`, {
  stackName: `${envPrefix}-ubi-ltr-webapp`,
  description: 'API Gateway, Lambda backend, and S3/CloudFront frontend for UBI webapp',
  env,
  envPrefix,
  masterUserSecretArn: openSearchStack.masterUserSecret.secretArn,
  deployFrontend,
});

// Add dependencies - webapp needs OpenSearch to be ready (for SSM parameters)
webappStack.addDependency(openSearchStack);

// ===========================================================================
// App Synthesis
// ===========================================================================
app.synth();
