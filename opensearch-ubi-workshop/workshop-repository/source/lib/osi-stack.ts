import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as osis from 'aws-cdk-lib/aws-osis';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Construct } from 'constructs';
import { EcomUbiStackProps, importSharedRole } from './common';

export interface OsiStackProps extends EcomUbiStackProps {
  readonly dataBucket: s3.IBucket;
}

/**
 * OpenSearch Ingestion (OSI) pipeline for VoltMall UBI data.
 *
 * HTTP source (/ecom-ubi) -> route by /type:
 *   type == "query" -> ubi_queries_ecom (document_id = query_id)
 *   type == "event" -> ubi_events_ecom
 * Both routes are also archived to S3 as ndjson, failures go to an S3 DLQ.
 *
 * Sink auth reuses OSIUBIPipelineRole which is already FGAC-mapped
 * (all_access) on the ltr-vector domain.
 */
export class EcomUbiOsiStack extends cdk.Stack {
  public readonly ingestUrl: string;
  public readonly pipelineArn: string;

  constructor(scope: Construct, id: string, props: OsiStackProps) {
    super(scope, id, props);

    const pipelineName = `${props.envPrefix}-pipeline`; // ecom-ubi-pipeline
    const role = importSharedRole(this, props.sharedRoleArn);

    // the OSI sink role needs write access to our archive/DLQ bucket
    const bucketPolicy = new iam.Policy(this, 'OsiBucketAccess', {
      statements: [
        new iam.PolicyStatement({
          actions: ['s3:PutObject', 's3:AbortMultipartUpload'],
          resources: [`${props.dataBucket.bucketArn}/*`],
        }),
        new iam.PolicyStatement({
          actions: ['s3:ListBucket', 's3:GetBucketLocation'],
          resources: [props.dataBucket.bucketArn],
        }),
      ],
    });
    bucketPolicy.attachToRole(role);

    const logGroup = new logs.LogGroup(this, 'OsiLogGroup', {
      logGroupName: `/aws/vendedlogs/OpenSearchIngestion/${pipelineName}`,
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const region = this.region;
    const body = `
version: "2"
ecom-ubi-pipeline:
  source:
    http:
      path: "/ecom-ubi"
  processor:
    - date:
        from_time_received: true
        destination: "@timestamp"
  route:
    - queries: '/type == "query"'
    - events: '/type == "event"'
  sink:
    - opensearch:
        hosts:
          - "https://${props.opensearchEndpoint}"
        index: "${props.ubiQueriesIndex}"
        document_id: "\${query_id}"
        routes:
          - queries
        aws:
          sts_role_arn: "${props.sharedRoleArn}"
          region: "${region}"
        dlq:
          s3:
            bucket: "${props.dataBucket.bucketName}"
            key_path_prefix: "osi-dlq/queries/"
            region: "${region}"
            sts_role_arn: "${props.sharedRoleArn}"
    - opensearch:
        hosts:
          - "https://${props.opensearchEndpoint}"
        index: "${props.ubiEventsIndex}"
        routes:
          - events
        aws:
          sts_role_arn: "${props.sharedRoleArn}"
          region: "${region}"
        dlq:
          s3:
            bucket: "${props.dataBucket.bucketName}"
            key_path_prefix: "osi-dlq/events/"
            region: "${region}"
            sts_role_arn: "${props.sharedRoleArn}"
    - s3:
        aws:
          sts_role_arn: "${props.sharedRoleArn}"
          region: "${region}"
        bucket: "${props.dataBucket.bucketName}"
        object_key:
          path_prefix: "ubi-archive/queries/%{yyyy}/%{MM}/%{dd}/"
        threshold:
          event_collect_timeout: "60s"
          maximum_size: "10mb"
        codec:
          ndjson:
        routes:
          - queries
    - s3:
        aws:
          sts_role_arn: "${props.sharedRoleArn}"
          region: "${region}"
        bucket: "${props.dataBucket.bucketName}"
        object_key:
          path_prefix: "ubi-archive/events/%{yyyy}/%{MM}/%{dd}/"
        threshold:
          event_collect_timeout: "60s"
          maximum_size: "10mb"
        codec:
          ndjson:
        routes:
          - events
`;

    const pipeline = new osis.CfnPipeline(this, 'UbiPipeline', {
      pipelineName,
      minUnits: 1,
      maxUnits: 1,
      pipelineConfigurationBody: body,
      logPublishingOptions: {
        isLoggingEnabled: true,
        cloudWatchLogDestination: { logGroup: logGroup.logGroupName },
      },
      tags: [
        { key: 'Project', value: 'ecom-ubi-ltr' },
        { key: 'ManagedBy', value: 'CDK' },
      ],
    });
    pipeline.node.addDependency(bucketPolicy);

    // e.g. ecom-ubi-pipeline-xxxx.us-east-1.osis.amazonaws.com
    const endpoint = cdk.Fn.select(0, pipeline.attrIngestEndpointUrls);
    this.ingestUrl = `https://${endpoint}/ecom-ubi`;
    this.pipelineArn = pipeline.attrPipelineArn;

    new ssm.StringParameter(this, 'IngestUrlParam', {
      parameterName: `/${props.envPrefix}/osi/ingest-url`,
      stringValue: this.ingestUrl,
    });

    new cdk.CfnOutput(this, 'UbiIngestUrl', { value: this.ingestUrl });
    new cdk.CfnOutput(this, 'UbiPipelineArn', { value: this.pipelineArn });
  }
}
