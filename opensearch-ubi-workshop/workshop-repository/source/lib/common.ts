import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export interface EcomUbiContext {
  readonly envPrefix: string;
  readonly opensearchEndpoint: string;
  readonly opensearchDomainArn: string;
  readonly sharedRoleArn: string;
  readonly judgeModelId: string;
  readonly productsIndex: string;
  readonly ubiQueriesIndex: string;
  readonly ubiEventsIndex: string;
  readonly judgmentsIndex: string;
  readonly metricsIndex: string;
  readonly ltrStore: string;
  readonly ltrFeatureset: string;
}

export interface EcomUbiStackProps extends cdk.StackProps, EcomUbiContext {}

/**
 * Import the shared, FGAC-mapped OpenSearch role (OSIUBIPipelineRole).
 * mutable=true lets each stack attach the extra inline policies it needs
 * (CloudWatch logs, S3 data bucket, osis:Ingest, ...). The role itself is
 * NOT managed by CDK and survives `cdk destroy`.
 */
export function importSharedRole(scope: Construct, arn: string): iam.IRole {
  return iam.Role.fromRoleArn(scope, 'SharedOpenSearchRole', arn, {
    mutable: true,
  });
}

export function lambdaLogsStatement(): iam.PolicyStatement {
  return new iam.PolicyStatement({
    actions: ['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents'],
    resources: ['arn:aws:logs:*:*:*'],
  });
}
