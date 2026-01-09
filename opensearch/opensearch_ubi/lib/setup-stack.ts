/**
 * Setup Stack - Custom Resource for OpenSearch initialization.
 *
 * This stack creates:
 * - Lambda function for OpenSearch setup
 * - Custom Resource that triggers setup on deployment
 *
 * Setup includes:
 * - IAM role mapping to OpenSearch all_access
 * - Creation of UBI indices (ubi_queries, ubi_events)
 * - Creation of products index with k-NN support
 * - Creation of llm_judgments index
 * - Sample product data insertion
 */

import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as cr from 'aws-cdk-lib/custom-resources';
import * as path from 'path';
import { Construct } from 'constructs';

export interface SetupStackProps extends cdk.StackProps {
  /**
   * Environment prefix for resource naming.
   * @default 'dev'
   */
  readonly envPrefix?: string;

  /**
   * OpenSearch domain endpoint (without https://).
   */
  readonly openSearchEndpoint: string;

  /**
   * ARN of the master user secret.
   */
  readonly masterUserSecretArn: string;

  /**
   * ARN of the Lambda execution role to map to OpenSearch.
   */
  readonly lambdaExecutionRoleArn: string;

  /**
   * ARN of the OSI pipeline role to map to OpenSearch.
   */
  readonly osiPipelineRoleArn?: string;

  /**
   * Lambda layer for dependencies.
   */
  readonly dependenciesLayerArn?: string;
}

export class SetupStack extends cdk.Stack {
  /**
   * The setup Lambda function.
   */
  public readonly setupFunction: lambda.Function;

  constructor(scope: Construct, id: string, props: SetupStackProps) {
    super(scope, id, props);

    const envPrefix = props.envPrefix ?? 'dev';
    const region = cdk.Stack.of(this).region;

    // ===========================================================================
    // Setup Lambda Role
    // ===========================================================================
    const setupRole = new iam.Role(this, 'SetupRole', {
      roleName: `${envPrefix}-ubi-opensearch-setup-role`,
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
      ],
    });

    // Add permissions to access OpenSearch
    setupRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: ['es:*'],
      resources: ['*'],
    }));

    // Add permissions to read secret
    setupRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'secretsmanager:GetSecretValue',
        'secretsmanager:DescribeSecret',
      ],
      resources: [props.masterUserSecretArn],
    }));

    // ===========================================================================
    // Lambda Layer for Dependencies
    // ===========================================================================
    const dependenciesLayer = new lambda.LayerVersion(this, 'SetupDependenciesLayer', {
      layerVersionName: `${envPrefix}-ubi-setup-dependencies`,
      description: 'Dependencies for OpenSearch setup Lambda',
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_12],
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda/layers/dependencies')),
    });

    // ===========================================================================
    // Setup Lambda Function
    // ===========================================================================
    this.setupFunction = new lambda.Function(this, 'SetupFunction', {
      functionName: `${envPrefix}-ubi-opensearch-setup`,
      description: 'Initialize OpenSearch with indices, role mappings, and sample data',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'setup_opensearch.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda/functions/setup_opensearch')),
      role: setupRole,
      timeout: cdk.Duration.minutes(5),
      memorySize: 512,
      environment: {
        LOG_LEVEL: 'INFO',
      },
      layers: [dependenciesLayer],
      logGroup: new logs.LogGroup(this, 'SetupLogGroup', {
        logGroupName: `/aws/lambda/${envPrefix}-ubi-opensearch-setup`,
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    });

    // ===========================================================================
    // Custom Resource Provider
    // ===========================================================================
    const provider = new cr.Provider(this, 'SetupProvider', {
      onEventHandler: this.setupFunction,
      logGroup: new logs.LogGroup(this, 'ProviderLogGroup', {
        logGroupName: `/aws/lambda/${envPrefix}-ubi-setup-provider`,
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    });

    // ===========================================================================
    // Custom Resource
    // ===========================================================================
    const setupResource = new cdk.CustomResource(this, 'OpenSearchSetup', {
      serviceToken: provider.serviceToken,
      properties: {
        OpenSearchEndpoint: props.openSearchEndpoint,
        MasterUserSecretArn: props.masterUserSecretArn,
        LambdaRoleArn: props.lambdaExecutionRoleArn,
        OsiPipelineRoleArn: props.osiPipelineRoleArn,
        Region: region,
        // Add timestamp to force update on each deployment
        Timestamp: new Date().toISOString(),
      },
    });

    // ===========================================================================
    // Outputs
    // ===========================================================================
    new cdk.CfnOutput(this, 'SetupFunctionArn', {
      value: this.setupFunction.functionArn,
      description: 'ARN of the setup Lambda function',
      exportName: `${envPrefix}-SetupFunctionArn`,
    });

    new cdk.CfnOutput(this, 'SetupResult', {
      value: setupResource.getAttString('Message'),
      description: 'Result of OpenSearch setup',
    });

    // Add tags
    cdk.Tags.of(this).add('Project', 'UBI-LTR');
    cdk.Tags.of(this).add('Environment', envPrefix);
    cdk.Tags.of(this).add('ManagedBy', 'CDK');
  }
}
