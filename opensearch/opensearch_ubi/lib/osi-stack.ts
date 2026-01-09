/**
 * OSI Stack - OpenSearch Ingestion pipeline for UBI data.
 *
 * This stack creates:
 * - Single OSI pipeline for both UBI queries and events with routing
 * - SSM parameter for pipeline endpoint
 */

import * as cdk from 'aws-cdk-lib';
import * as osis from 'aws-cdk-lib/aws-osis';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Construct } from 'constructs';

export interface OsiStackProps extends cdk.StackProps {
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
   * ARN of the OSI pipeline role.
   */
  readonly osiPipelineRoleArn: string;

  /**
   * S3 bucket name for DLQ.
   */
  readonly dlqBucketName: string;
}

export class OsiStack extends cdk.Stack {
  /**
   * The unified UBI pipeline.
   */
  public readonly ubiPipeline: osis.CfnPipeline;

  /**
   * Pipeline ingestion endpoint.
   */
  public readonly pipelineEndpoint: string;

  constructor(scope: Construct, id: string, props: OsiStackProps) {
    super(scope, id, props);

    const envPrefix = props.envPrefix ?? 'dev';
    const region = cdk.Stack.of(this).region;

    // ===========================================================================
    // CloudWatch Log Group for OSI Pipeline
    // ===========================================================================
    const logGroup = new logs.LogGroup(this, 'OsiLogGroup', {
      logGroupName: `/aws/vendedlogs/OpenSearchIngestion/${envPrefix}-ubi-pipeline`,
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ===========================================================================
    // Unified UBI Pipeline with Routing
    // Single pipeline handles both events and queries, routing by type field
    // ===========================================================================
    const ubiPipelineConfig = `
version: "2"
ubi-pipeline:
  source:
    http:
      path: "/ubi"
  processor:
    - date:
        from_time_received: true
        destination: "@timestamp"
  route:
    - ubi-events: '/type == "event"'
    - ubi-queries: '/type == "query"'
  sink:
    - opensearch:
        hosts:
          - "https://${props.openSearchEndpoint}"
        index: "ubi_events"
        aws:
          sts_role_arn: "${props.osiPipelineRoleArn}"
          region: "${region}"
        routes:
          - ubi-events
        dlq:
          s3:
            bucket: "${props.dlqBucketName}"
            key_path_prefix: "ubi-events-dlq/"
            region: "${region}"
            sts_role_arn: "${props.osiPipelineRoleArn}"
    - opensearch:
        hosts:
          - "https://${props.openSearchEndpoint}"
        index: "ubi_queries"
        document_id: "\${query_id}"
        aws:
          sts_role_arn: "${props.osiPipelineRoleArn}"
          region: "${region}"
        routes:
          - ubi-queries
        dlq:
          s3:
            bucket: "${props.dlqBucketName}"
            key_path_prefix: "ubi-queries-dlq/"
            region: "${region}"
            sts_role_arn: "${props.osiPipelineRoleArn}"
`;

    this.ubiPipeline = new osis.CfnPipeline(this, 'UbiPipeline', {
      pipelineName: `${envPrefix}-ubi-pipeline`,
      minUnits: 1,
      maxUnits: 2,
      pipelineConfigurationBody: ubiPipelineConfig,
      logPublishingOptions: {
        isLoggingEnabled: true,
        cloudWatchLogDestination: {
          logGroup: logGroup.logGroupName,
        },
      },
      tags: [
        { key: 'Project', value: 'UBI-LTR' },
        { key: 'Environment', value: envPrefix },
        { key: 'Purpose', value: 'UBI-Pipeline' },
      ],
    });

    // Pipeline endpoint is constructed from pipeline name
    this.pipelineEndpoint = cdk.Fn.select(0, this.ubiPipeline.attrIngestEndpointUrls);

    // ===========================================================================
    // SSM Parameter for Pipeline Endpoint
    // ===========================================================================
    new ssm.StringParameter(this, 'UbiPipelineEndpoint', {
      parameterName: `/${envPrefix}/ubi-ltr/osi/pipeline-endpoint`,
      stringValue: this.pipelineEndpoint,
      description: 'OSI pipeline endpoint for UBI data',
    });

    // ===========================================================================
    // Outputs
    // ===========================================================================
    new cdk.CfnOutput(this, 'UbiPipelineArn', {
      value: this.ubiPipeline.attrPipelineArn,
      description: 'ARN of the UBI pipeline',
      exportName: `${envPrefix}-UbiPipelineArn`,
    });

    new cdk.CfnOutput(this, 'UbiIngestEndpoint', {
      value: `https://${this.pipelineEndpoint}/ubi`,
      description: 'Ingestion endpoint URL for UBI data',
      exportName: `${envPrefix}-UbiIngestEndpoint`,
    });

    // Add tags
    cdk.Tags.of(this).add('Project', 'UBI-LTR');
    cdk.Tags.of(this).add('Environment', envPrefix);
    cdk.Tags.of(this).add('ManagedBy', 'CDK');
  }
}
