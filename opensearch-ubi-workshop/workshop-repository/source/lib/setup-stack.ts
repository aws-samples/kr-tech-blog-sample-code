import * as cdk from 'aws-cdk-lib';
import * as crypto from 'crypto';
import * as fs from 'fs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as path from 'path';
import { Construct } from 'constructs';
import { EcomUbiStackProps, importSharedRole, lambdaLogsStatement } from './common';

/**
 * Custom-resource stack that prepares the existing ltr-vector domain:
 *  - creates ecom_products / ubi_queries_ecom / ubi_events_ecom /
 *    ecom_judgments / ecom_ltr_metrics indexes with explicit mappings
 *  - bulk-loads the 450-product electronics catalog
 *  - creates the "ecom" LTR feature store
 *
 * Deletion keeps all indexes/data (shared cluster) — cleanup is a documented
 * manual script.
 */
export class EcomUbiSetupStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: EcomUbiStackProps) {
    super(scope, id, props);

    const role = importSharedRole(this, props.sharedRoleArn);
    const policy = new iam.Policy(this, 'SetupLambdaPolicy', {
      statements: [lambdaLogsStatement()],
    });
    policy.attachToRole(role);

    const assetDir = path.join(__dirname, '..', '.build', 'functions', 'setup_opensearch');
    if (!fs.existsSync(path.join(assetDir, 'setup_opensearch.py'))) {
      throw new Error(`missing ${assetDir} — run scripts/build.sh first`);
    }

    const layer = new lambda.LayerVersion(this, 'DepsLayer', {
      code: lambda.Code.fromAsset(path.join(__dirname, '..', '.build', 'layer')),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_12],
      description: 'opensearch-py + requests-aws4auth',
    });

    const fn = new lambda.Function(this, 'SetupFn', {
      functionName: `${props.envPrefix}-setup-opensearch`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'setup_opensearch.handler',
      code: lambda.Code.fromAsset(assetDir),
      role,
      layers: [layer],
      timeout: cdk.Duration.minutes(10),
      memorySize: 1024,
      environment: {
        OPENSEARCH_ENDPOINT: props.opensearchEndpoint,
        PRODUCTS_INDEX: props.productsIndex,
        UBI_QUERIES_INDEX: props.ubiQueriesIndex,
        UBI_EVENTS_INDEX: props.ubiEventsIndex,
        JUDGMENTS_INDEX: props.judgmentsIndex,
        METRICS_INDEX: props.metricsIndex,
        LTR_STORE: props.ltrStore,
      },
    });
    fn.node.addDependency(policy);

    // hash of the catalog forces the custom resource to re-run when data changes
    const catalog = fs.readFileSync(path.join(assetDir, 'products.json'));
    const dataVersion = crypto.createHash('sha256').update(catalog).digest('hex').slice(0, 16);

    new cdk.CustomResource(this, 'SetupResource', {
      serviceToken: fn.functionArn,
      properties: { DataVersion: dataVersion },
    });

    new cdk.CfnOutput(this, 'ProductsIndexOut', { value: props.productsIndex });
  }
}
