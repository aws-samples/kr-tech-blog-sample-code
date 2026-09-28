#!/usr/bin/env node
/**
 * VoltMall — UBI/LTR end-to-end sample attached to an existing OpenSearch domain.
 *
 * Stacks:
 *  - EcomUbiStorageStack : S3 bucket for UBI archive / DLQ / ML artifacts
 *  - EcomUbiOsiStack     : OpenSearch Ingestion pipeline (HTTP -> ubi_queries_ecom / ubi_events_ecom)
 *  - EcomUbiSetupStack   : index mappings + product catalog seeding + LTR store (custom resource)
 *  - EcomUbiWebappStack  : FastAPI Lambda + API Gateway + CloudFront + React storefront
 *  - EcomUbiMlStack      : Step Functions ML pipeline (extract -> judge -> features -> train -> evaluate)
 *
 * The existing domain uses fine-grained access control. A caller-supplied IAM
 * role that is already mapped to the required FGAC backend roles is reused by
 * OSI sinks and the sample Lambdas. See scripts/00-prepare-iam.sh.
 */
import * as cdk from 'aws-cdk-lib';
import { EcomUbiStorageStack } from '../lib/storage-stack';
import { EcomUbiOsiStack } from '../lib/osi-stack';
import { EcomUbiSetupStack } from '../lib/setup-stack';
import { EcomUbiWebappStack } from '../lib/webapp-stack';
import { EcomUbiMlStack } from '../lib/ml-pipeline-stack';

const app = new cdk.App();

function requiredContext(name: string): string {
  const value = app.node.tryGetContext(name) as string | undefined;
  if (!value) {
    throw new Error(`Missing CDK context '${name}'. Pass -c ${name}=<value>.`);
  }
  return value;
}

const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION ?? 'us-east-1',
};

const ctx = {
  envPrefix: app.node.tryGetContext('envPrefix') as string,
  opensearchEndpoint: requiredContext('opensearchEndpoint'),
  opensearchDomainArn: requiredContext('opensearchDomainArn'),
  sharedRoleArn: requiredContext('sharedOpenSearchRoleArn'),
  judgeModelId: requiredContext('judgeModelId'),
  productsIndex: app.node.tryGetContext('productsIndex') as string,
  ubiQueriesIndex: app.node.tryGetContext('ubiQueriesIndex') as string,
  ubiEventsIndex: app.node.tryGetContext('ubiEventsIndex') as string,
  judgmentsIndex: app.node.tryGetContext('judgmentsIndex') as string,
  metricsIndex: app.node.tryGetContext('metricsIndex') as string,
  ltrStore: app.node.tryGetContext('ltrStore') as string,
  ltrFeatureset: app.node.tryGetContext('ltrFeatureset') as string,
};

const storage = new EcomUbiStorageStack(app, 'EcomUbiStorageStack', { env, ...ctx });

const osi = new EcomUbiOsiStack(app, 'EcomUbiOsiStack', {
  env,
  ...ctx,
  dataBucket: storage.dataBucket,
});

new EcomUbiSetupStack(app, 'EcomUbiSetupStack', { env, ...ctx });

new EcomUbiWebappStack(app, 'EcomUbiWebappStack', {
  env,
  ...ctx,
  osiIngestUrl: osi.ingestUrl,
  osiPipelineArn: osi.pipelineArn,
});

new EcomUbiMlStack(app, 'EcomUbiMlStack', {
  env,
  ...ctx,
  dataBucket: storage.dataBucket,
});

app.synth();
