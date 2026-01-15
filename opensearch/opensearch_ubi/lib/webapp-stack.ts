/**
 * Webapp Stack - API Gateway, Lambda backend, and S3/CloudFront frontend.
 *
 * This stack creates:
 * - Lambda function for FastAPI backend (with Mangum adapter)
 * - API Gateway HTTP API for backend access
 * - IAM role with SSM and Secrets Manager permissions
 * - S3 bucket for static frontend hosting
 * - CloudFront distribution for CDN
 */

import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigateway from 'aws-cdk-lib/aws-apigatewayv2';
import * as apigatewayIntegrations from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as path from 'path';
import { Construct } from 'constructs';

export interface WebappStackProps extends cdk.StackProps {
  /**
   * Environment prefix for resource naming.
   * @default 'dev'
   */
  readonly envPrefix?: string;

  /**
   * ARN of the master user secret in Secrets Manager.
   */
  readonly masterUserSecretArn: string;

  /**
   * Deploy frontend to S3/CloudFront.
   * Requires: cd webapp/frontend && npm run build (before cdk deploy)
   * @default true
   */
  readonly deployFrontend?: boolean;
}

export class WebappStack extends cdk.Stack {
  /**
   * The API Gateway HTTP API.
   */
  public readonly api: apigateway.HttpApi;

  /**
   * The Lambda function for the backend.
   */
  public readonly backendFunction: lambda.Function;

  /**
   * The API endpoint URL.
   */
  public readonly apiEndpoint: string;

  /**
   * The S3 bucket for frontend hosting.
   */
  public readonly frontendBucket: s3.Bucket;

  /**
   * The CloudFront distribution.
   */
  public readonly distribution: cloudfront.Distribution;

  /**
   * The CloudFront URL.
   */
  public readonly websiteUrl: string;

  constructor(scope: Construct, id: string, props: WebappStackProps) {
    super(scope, id, props);

    const envPrefix = props.envPrefix ?? 'dev';
    const region = cdk.Stack.of(this).region;
    const account = cdk.Stack.of(this).account;
    const deployFrontend = props.deployFrontend ?? true;

    // ===========================================================================
    // IAM Role for Lambda Backend
    // ===========================================================================
    const backendRole = new iam.Role(this, 'BackendRole', {
      roleName: `${envPrefix}-ubi-webapp-backend-role`,
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: 'Execution role for UBI webapp backend Lambda',
    });

    // CloudWatch Logs permissions
    backendRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          'logs:CreateLogGroup',
          'logs:CreateLogStream',
          'logs:PutLogEvents',
        ],
        resources: [`arn:aws:logs:${region}:${account}:*`],
      })
    );

    // SSM Parameter Store read permissions
    backendRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ['ssm:GetParameter', 'ssm:GetParameters'],
        resources: [`arn:aws:ssm:${region}:${account}:parameter/${envPrefix}/ubi-ltr/*`],
      })
    );

    // Secrets Manager read permission for OpenSearch credentials
    backendRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ['secretsmanager:GetSecretValue'],
        resources: [props.masterUserSecretArn],
      })
    );

    // OpenSearch access (HTTP endpoint)
    backendRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ['es:ESHttp*'],
        resources: [`arn:aws:es:${region}:${account}:domain/${envPrefix}-ubi-ltr/*`],
      })
    );

    // OSI pipeline ingestion permission (for UBI data)
    backendRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ['osis:Ingest'],
        resources: [`arn:aws:osis:${region}:${account}:pipeline/${envPrefix}-ubi-*`],
      })
    );

    // ===========================================================================
    // Lambda Function for Backend API
    // ===========================================================================
    // Note: Dependencies are pre-bundled at lambda/webapp-backend
    // Run this to update: cd webapp/backend && pip install --platform manylinux2014_x86_64 --only-binary=:all: -r requirements.txt -t ../../cdk/lambda/webapp-backend && cp main.py ../../cdk/lambda/webapp-backend/
    const backendLogGroup = new logs.LogGroup(this, 'BackendLogGroup', {
      logGroupName: `/aws/lambda/${envPrefix}-ubi-webapp-backend`,
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    this.backendFunction = new lambda.Function(this, 'BackendFunction', {
      functionName: `${envPrefix}-ubi-webapp-backend`,
      description: 'FastAPI backend for UBI webapp with SSM/Secrets Manager integration',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'main.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda/webapp-backend')),
      role: backendRole,
      timeout: cdk.Duration.seconds(30),
      memorySize: 512,
      environment: {
        ENV_PREFIX: envPrefix,
        AWS_REGION_NAME: region,
      },
      logGroup: backendLogGroup,
    });

    // ===========================================================================
    // API Gateway HTTP API
    // ===========================================================================
    this.api = new apigateway.HttpApi(this, 'HttpApi', {
      apiName: `${envPrefix}-ubi-webapp-api`,
      description: 'HTTP API for UBI webapp backend',
      corsPreflight: {
        allowHeaders: ['Content-Type', 'Authorization', 'X-Requested-With'],
        allowMethods: [
          apigateway.CorsHttpMethod.GET,
          apigateway.CorsHttpMethod.POST,
          apigateway.CorsHttpMethod.PUT,
          apigateway.CorsHttpMethod.DELETE,
          apigateway.CorsHttpMethod.OPTIONS,
        ],
        allowOrigins: ['*'],
        maxAge: cdk.Duration.hours(1),
      },
    });

    // Lambda integration
    const lambdaIntegration = new apigatewayIntegrations.HttpLambdaIntegration(
      'LambdaIntegration',
      this.backendFunction
    );

    // Add routes - catch-all to handle all FastAPI routes
    this.api.addRoutes({
      path: '/{proxy+}',
      methods: [apigateway.HttpMethod.ANY],
      integration: lambdaIntegration,
    });

    // Root path for health check
    this.api.addRoutes({
      path: '/health',
      methods: [apigateway.HttpMethod.GET],
      integration: lambdaIntegration,
    });

    this.apiEndpoint = this.api.apiEndpoint;

    // ===========================================================================
    // S3 Bucket for Frontend Hosting
    // ===========================================================================
    this.frontendBucket = new s3.Bucket(this, 'FrontendBucket', {
      bucketName: `${envPrefix}-ubi-webapp-frontend-${account}-${region}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    // ===========================================================================
    // CloudFront Distribution
    // ===========================================================================
    this.distribution = new cloudfront.Distribution(this, 'Distribution', {
      comment: `${envPrefix} UBI Webapp Frontend`,
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(this.frontendBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
      },
      defaultRootObject: 'index.html',
      errorResponses: [
        {
          httpStatus: 403,
          responseHttpStatus: 200,
          responsePagePath: '/index.html',
          ttl: cdk.Duration.minutes(5),
        },
        {
          httpStatus: 404,
          responseHttpStatus: 200,
          responsePagePath: '/index.html',
          ttl: cdk.Duration.minutes(5),
        },
      ],
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
    });

    this.websiteUrl = `https://${this.distribution.distributionDomainName}`;

    // ===========================================================================
    // Deploy Frontend (if enabled)
    // ===========================================================================
    if (deployFrontend) {
      // Deploy static frontend assets
      // Frontend is now located in cdk/webapp-frontend folder
      new s3deploy.BucketDeployment(this, 'DeployFrontend', {
        sources: [s3deploy.Source.asset(path.join(__dirname, '../webapp-frontend/dist'))],
        destinationBucket: this.frontendBucket,
        distribution: this.distribution,
        distributionPaths: ['/*'],
        // Don't delete config.json deployed by the next deployment
        prune: false,
      });
    }

    // Always deploy runtime config with API URL
    // This allows the frontend to dynamically get the API endpoint
    new s3deploy.BucketDeployment(this, 'DeployConfig', {
      sources: [
        s3deploy.Source.jsonData('config.json', {
          apiUrl: this.apiEndpoint,
        }),
      ],
      destinationBucket: this.frontendBucket,
      distribution: this.distribution,
      distributionPaths: ['/config.json'],
      // Only deploy config.json, don't affect other files
      prune: false,
    });

    // ===========================================================================
    // Outputs
    // ===========================================================================
    new cdk.CfnOutput(this, 'BackendFunctionArn', {
      value: this.backendFunction.functionArn,
      description: 'ARN of the backend Lambda function',
      exportName: `${envPrefix}-WebappBackendFunctionArn`,
    });

    new cdk.CfnOutput(this, 'ApiEndpoint', {
      value: this.apiEndpoint,
      description: 'API Gateway endpoint URL',
      exportName: `${envPrefix}-WebappApiEndpoint`,
    });

    new cdk.CfnOutput(this, 'HealthCheckUrl', {
      value: `${this.apiEndpoint}/health`,
      description: 'Health check URL for testing',
    });

    new cdk.CfnOutput(this, 'SearchApiUrl', {
      value: `${this.apiEndpoint}/api/search`,
      description: 'Search API endpoint',
    });

    new cdk.CfnOutput(this, 'FrontendBucketName', {
      value: this.frontendBucket.bucketName,
      description: 'S3 bucket for frontend hosting',
      exportName: `${envPrefix}-WebappFrontendBucket`,
    });

    new cdk.CfnOutput(this, 'CloudFrontDistributionId', {
      value: this.distribution.distributionId,
      description: 'CloudFront distribution ID',
      exportName: `${envPrefix}-WebappDistributionId`,
    });

    new cdk.CfnOutput(this, 'WebsiteUrl', {
      value: this.websiteUrl,
      description: 'CloudFront website URL',
      exportName: `${envPrefix}-WebappUrl`,
    });

    new cdk.CfnOutput(this, 'FrontendDeploymentInstructions', {
      value: `
To deploy the frontend:
1. cd cdk/webapp-frontend && npm install && npm run build
2. cd .. && npx cdk deploy UbiLtr-WebappStack-${envPrefix}

Note: API URL is automatically provided via /config.json at runtime.
No need to set VITE_API_URL environment variable.

Or manually sync:
aws s3 sync cdk/webapp-frontend/dist/ s3://${this.frontendBucket.bucketName}/ --delete
aws cloudfront create-invalidation --distribution-id ${this.distribution.distributionId} --paths "/*"
`.trim(),
      description: 'Instructions for deploying the frontend',
    });

    // Add tags
    cdk.Tags.of(this).add('Project', 'UBI-LTR');
    cdk.Tags.of(this).add('Environment', envPrefix);
    cdk.Tags.of(this).add('ManagedBy', 'CDK');
  }
}
