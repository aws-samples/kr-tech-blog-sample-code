/**
 * IAM Stack - Roles and policies for UBI to LTR pipeline.
 *
 * This stack creates IAM roles for:
 * - OpenSearch Ingestion (OSI) pipelines
 * - Lambda functions
 * - Step Functions state machine
 */

import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export interface IamStackProps extends cdk.StackProps {
  /**
   * Environment prefix for resource naming.
   * @default 'dev'
   */
  readonly envPrefix?: string;

  /**
   * OpenSearch domain ARN (optional, can be set later).
   */
  readonly openSearchDomainArn?: string;

  /**
   * S3 bucket ARN for data storage.
   */
  readonly dataBucketArn?: string;
}

export class IamStack extends cdk.Stack {
  /**
   * Role for OSI pipelines to access OpenSearch and S3.
   */
  public readonly osiPipelineRole: iam.Role;

  /**
   * Role for Lambda functions to access OpenSearch, S3, and Bedrock.
   */
  public readonly lambdaExecutionRole: iam.Role;

  /**
   * Role for Step Functions to orchestrate the pipeline.
   */
  public readonly stepFunctionsRole: iam.Role;

  constructor(scope: Construct, id: string, props: IamStackProps = {}) {
    super(scope, id, props);

    const envPrefix = props.envPrefix ?? 'dev';
    const region = cdk.Stack.of(this).region;
    const account = cdk.Stack.of(this).account;

    // ===========================================================================
    // OSI Pipeline Role
    // ===========================================================================
    this.osiPipelineRole = new iam.Role(this, 'OsiPipelineRole', {
      roleName: `${envPrefix}-ubi-osi-pipeline-role`,
      assumedBy: new iam.ServicePrincipal('osis-pipelines.amazonaws.com'),
      description: 'Role for OpenSearch Ingestion pipelines to access OpenSearch and S3',
    });

    // Policy for OSI to write to OpenSearch
    this.osiPipelineRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'OpenSearchAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'es:DescribeDomain',
          'es:ESHttp*',
        ],
        resources: [
          props.openSearchDomainArn ?? `arn:aws:es:${region}:${account}:domain/*`,
        ],
      })
    );

    // Policy for OSI to write to S3 (for DLQ and backups)
    if (props.dataBucketArn) {
      this.osiPipelineRole.addToPolicy(
        new iam.PolicyStatement({
          sid: 'S3Access',
          effect: iam.Effect.ALLOW,
          actions: [
            's3:GetObject',
            's3:PutObject',
            's3:DeleteObject',
            's3:ListBucket',
          ],
          resources: [
            props.dataBucketArn,
            `${props.dataBucketArn}/*`,
          ],
        })
      );
    }

    // ===========================================================================
    // Lambda Execution Role
    // ===========================================================================
    this.lambdaExecutionRole = new iam.Role(this, 'LambdaExecutionRole', {
      roleName: `${envPrefix}-ubi-lambda-execution-role`,
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: 'Role for Lambda functions in the UBI-LTR pipeline',
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaVPCAccessExecutionRole'),
      ],
    });

    // Policy for Lambda to access OpenSearch
    this.lambdaExecutionRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'OpenSearchAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'es:ESHttpGet',
          'es:ESHttpPost',
          'es:ESHttpPut',
          'es:ESHttpDelete',
          'es:ESHttpHead',
        ],
        resources: [
          props.openSearchDomainArn ?? `arn:aws:es:${region}:${account}:domain/*`,
        ],
      })
    );

    // Policy for Lambda to access Bedrock (for LLM judgments)
    this.lambdaExecutionRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'BedrockAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'bedrock:InvokeModel',
          'bedrock:InvokeModelWithResponseStream',
        ],
        resources: [
          // Claude Sonnet 4.5 (on-demand inference profile)
          `arn:aws:bedrock:${region}::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0`,
          `arn:aws:bedrock:${region}:${account}:inference-profile/us.anthropic.claude-sonnet-4-5-20250929-v1:0`,
          // Cross-region inference profiles
          `arn:aws:bedrock:us-*::foundation-model/anthropic.claude-*`,
        ],
      })
    );

    // Policy for Lambda to access S3
    if (props.dataBucketArn) {
      this.lambdaExecutionRole.addToPolicy(
        new iam.PolicyStatement({
          sid: 'S3Access',
          effect: iam.Effect.ALLOW,
          actions: [
            's3:GetObject',
            's3:PutObject',
            's3:DeleteObject',
            's3:ListBucket',
          ],
          resources: [
            props.dataBucketArn,
            `${props.dataBucketArn}/*`,
          ],
        })
      );
    }

    // Policy for Lambda to access Secrets Manager (for OpenSearch credentials)
    this.lambdaExecutionRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'SecretsManagerAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'secretsmanager:GetSecretValue',
        ],
        resources: [
          `arn:aws:secretsmanager:${region}:${account}:secret:${envPrefix}-ubi-*`,
        ],
      })
    );

    // ===========================================================================
    // Step Functions Role
    // ===========================================================================
    this.stepFunctionsRole = new iam.Role(this, 'StepFunctionsRole', {
      roleName: `${envPrefix}-ubi-stepfunctions-role`,
      assumedBy: new iam.ServicePrincipal('states.amazonaws.com'),
      description: 'Role for Step Functions to orchestrate UBI-LTR pipeline',
    });

    // Policy for Step Functions to invoke Lambda
    this.stepFunctionsRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'LambdaInvoke',
        effect: iam.Effect.ALLOW,
        actions: [
          'lambda:InvokeFunction',
        ],
        resources: [
          `arn:aws:lambda:${region}:${account}:function:${envPrefix}-ubi-*`,
        ],
      })
    );

    // Policy for Step Functions logging
    this.stepFunctionsRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'CloudWatchLogs',
        effect: iam.Effect.ALLOW,
        actions: [
          'logs:CreateLogDelivery',
          'logs:GetLogDelivery',
          'logs:UpdateLogDelivery',
          'logs:DeleteLogDelivery',
          'logs:ListLogDeliveries',
          'logs:PutResourcePolicy',
          'logs:DescribeResourcePolicies',
          'logs:DescribeLogGroups',
        ],
        resources: ['*'],
      })
    );

    // Policy for Step Functions to send events
    this.stepFunctionsRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'EventBridge',
        effect: iam.Effect.ALLOW,
        actions: [
          'events:PutTargets',
          'events:PutRule',
          'events:DescribeRule',
        ],
        resources: [
          `arn:aws:events:${region}:${account}:rule/*`,
        ],
      })
    );

    // ===========================================================================
    // Outputs
    // ===========================================================================
    new cdk.CfnOutput(this, 'OsiPipelineRoleArn', {
      value: this.osiPipelineRole.roleArn,
      description: 'ARN of the OSI pipeline role',
      exportName: `${envPrefix}-OsiPipelineRoleArn`,
    });

    new cdk.CfnOutput(this, 'LambdaExecutionRoleArn', {
      value: this.lambdaExecutionRole.roleArn,
      description: 'ARN of the Lambda execution role',
      exportName: `${envPrefix}-LambdaExecutionRoleArn`,
    });

    new cdk.CfnOutput(this, 'StepFunctionsRoleArn', {
      value: this.stepFunctionsRole.roleArn,
      description: 'ARN of the Step Functions role',
      exportName: `${envPrefix}-StepFunctionsRoleArn`,
    });

    // Add tags
    cdk.Tags.of(this).add('Project', 'UBI-LTR');
    cdk.Tags.of(this).add('Environment', envPrefix);
    cdk.Tags.of(this).add('ManagedBy', 'CDK');
  }
}
