import * as cdk from 'aws-cdk-lib';
import * as apigw from 'aws-cdk-lib/aws-apigateway';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as fs from 'fs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as path from 'path';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import { Construct } from 'constructs';
import { EcomUbiStackProps, importSharedRole, lambdaLogsStatement } from './common';

export interface WebappStackProps extends EcomUbiStackProps {
  readonly osiIngestUrl: string;
  readonly osiPipelineArn: string;
}

/**
 * VoltMall storefront:
 *   CloudFront ── default ──> S3 (React SPA)
 *              └─ /api/*  ──> API Gateway ──> Lambda (FastAPI)
 *
 * The backend searches ecom_products directly on the domain and forwards UBI
 * queries/events to the OSI pipeline with SigV4 (service: osis).
 */
export class EcomUbiWebappStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: WebappStackProps) {
    super(scope, id, props);

    const role = importSharedRole(this, props.sharedRoleArn);
    const policy = new iam.Policy(this, 'BackendPolicy', {
      statements: [
        lambdaLogsStatement(),
        new iam.PolicyStatement({
          actions: ['osis:Ingest'],
          resources: [props.osiPipelineArn],
        }),
        new iam.PolicyStatement({
          actions: ['ssm:GetParameter'],
          resources: [`arn:aws:ssm:${this.region}:${this.account}:parameter/${props.envPrefix}/*`],
        }),
      ],
    });
    policy.attachToRole(role);

    const backendDir = path.join(__dirname, '..', '.build', 'backend');
    if (!fs.existsSync(path.join(backendDir, 'main.py'))) {
      throw new Error(`missing ${backendDir} — run scripts/build.sh first`);
    }

    const backend = new lambda.Function(this, 'BackendFn', {
      functionName: `${props.envPrefix}-webapp-backend`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'main.handler',
      code: lambda.Code.fromAsset(backendDir),
      role,
      memorySize: 1024,
      timeout: cdk.Duration.seconds(29),
      environment: {
        OPENSEARCH_ENDPOINT: props.opensearchEndpoint,
        OSI_INGEST_URL: props.osiIngestUrl,
        PRODUCTS_INDEX: props.productsIndex,
        LTR_STORE: props.ltrStore,
        LTR_FEATURESET: props.ltrFeatureset,
        LTR_MODEL_PARAM: `/${props.envPrefix}/ltr/model-name`,
        APPLICATION: 'voltmall',
      },
    });
    backend.node.addDependency(policy);

    const api = new apigw.LambdaRestApi(this, 'Api', {
      restApiName: `${props.envPrefix}-api`,
      handler: backend,
      proxy: true,
      deployOptions: { stageName: 'prod', throttlingRateLimit: 100, throttlingBurstLimit: 200 },
      defaultCorsPreflightOptions: {
        allowOrigins: apigw.Cors.ALL_ORIGINS,
        allowMethods: apigw.Cors.ALL_METHODS,
        allowHeaders: ['*'],
      },
    });

    const siteBucket = new s3.Bucket(this, 'SiteBucket', {
      bucketName: `${props.envPrefix}-site-${this.account}-${this.region}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    const distribution = new cloudfront.Distribution(this, 'Distribution', {
      comment: `${props.envPrefix} VoltMall storefront`,
      defaultRootObject: 'index.html',
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(siteBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
      },
      additionalBehaviors: {
        'api/*': {
          origin: new origins.RestApiOrigin(api),
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
        },
      },
      errorResponses: [
        { httpStatus: 403, responseHttpStatus: 200, responsePagePath: '/index.html', ttl: cdk.Duration.seconds(10) },
        { httpStatus: 404, responseHttpStatus: 200, responsePagePath: '/index.html', ttl: cdk.Duration.seconds(10) },
      ],
    });

    const distDir = path.join(__dirname, '..', 'webapp-frontend', 'dist');
    if (!fs.existsSync(path.join(distDir, 'index.html'))) {
      throw new Error(`missing ${distDir} — run scripts/build.sh first`);
    }

    new s3deploy.BucketDeployment(this, 'DeploySite', {
      sources: [s3deploy.Source.asset(distDir)],
      destinationBucket: siteBucket,
      distribution,
      distributionPaths: ['/*'],
      memoryLimit: 512,
    });

    new cdk.CfnOutput(this, 'StoreUrl', { value: `https://${distribution.distributionDomainName}` });
    new cdk.CfnOutput(this, 'ApiUrl', { value: api.url });
  }
}
