/**
 * OpenSearch Stack - OpenSearch Service domain and OSI pipelines.
 *
 * This stack creates:
 * - OpenSearch Service domain with UBI plugin support
 * - OSI pipelines for UBI data collection
 * - VPC configuration (optional)
 * - Security groups and access policies
 */

import * as cdk from 'aws-cdk-lib';
import * as opensearch from 'aws-cdk-lib/aws-opensearchservice';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Construct } from 'constructs';

export interface OpenSearchStackProps extends cdk.StackProps {
  /**
   * Environment prefix for resource naming.
   * @default 'dev'
   */
  readonly envPrefix?: string;

  /**
   * OpenSearch version.
   * @default '3.3'
   */
  readonly openSearchVersion?: string;

  /**
   * Instance type for data nodes.
   * @default 't3.medium.search'
   */
  readonly instanceType?: string;

  /**
   * Number of data nodes.
   * @default 3
   */
  readonly instanceCount?: number;

  /**
   * EBS volume size in GB.
   * @default 20
   */
  readonly ebsVolumeSize?: number;

  /**
   * Master user name for fine-grained access control.
   * @default 'admin'
   */
  readonly masterUserName?: string;

  /**
   * Enable dedicated master nodes.
   * @default false (for demo)
   */
  readonly dedicatedMasterEnabled?: boolean;

  /**
   * Enable multi-AZ deployment.
   * @default false (for demo)
   */
  readonly multiAzEnabled?: boolean;

  /**
   * Enable encryption at rest.
   * @default true
   */
  readonly encryptionAtRest?: boolean;

  /**
   * Existing VPC for deployment (optional).
   */
  readonly vpc?: ec2.IVpc;

  /**
   * OSI pipeline role ARN.
   */
  readonly osiPipelineRoleArn?: string;

  /**
   * S3 bucket ARN for DLQ.
   */
  readonly dlqBucketArn?: string;
}

export class OpenSearchStack extends cdk.Stack {
  /**
   * The OpenSearch domain.
   */
  public readonly domain: opensearch.Domain;

  /**
   * The master user secret.
   */
  public readonly masterUserSecret: secretsmanager.Secret;

  /**
   * The domain endpoint.
   */
  public readonly domainEndpoint: string;

  constructor(scope: Construct, id: string, props: OpenSearchStackProps = {}) {
    super(scope, id, props);

    const envPrefix = props.envPrefix ?? 'dev';
    const openSearchVersion = props.openSearchVersion ?? '3.3';
    const instanceType = props.instanceType ?? 't3.medium.search';
    const instanceCount = props.instanceCount ?? 3;
    const ebsVolumeSize = props.ebsVolumeSize ?? 20;
    const masterUserName = props.masterUserName ?? 'admin';
    const dedicatedMasterEnabled = props.dedicatedMasterEnabled ?? false;
    const multiAzEnabled = props.multiAzEnabled ?? false;
    const encryptionAtRest = props.encryptionAtRest ?? true;

    const region = cdk.Stack.of(this).region;
    const account = cdk.Stack.of(this).account;

    // ===========================================================================
    // Master User Secret
    // ===========================================================================
    this.masterUserSecret = new secretsmanager.Secret(this, 'MasterUserSecret', {
      secretName: `${envPrefix}-ubi-opensearch-master-user`,
      description: 'Master user credentials for OpenSearch domain',
      generateSecretString: {
        secretStringTemplate: JSON.stringify({ username: masterUserName }),
        generateStringKey: 'password',
        excludePunctuation: false,
        includeSpace: false,
        passwordLength: 32,
        requireEachIncludedType: true,
      },
    });

    // ===========================================================================
    // OpenSearch Domain
    // ===========================================================================
    this.domain = new opensearch.Domain(this, 'Domain', {
      domainName: `${envPrefix}-ubi-ltr`,
      version: opensearch.EngineVersion.openSearch(openSearchVersion),

      // Capacity configuration
      capacity: {
        dataNodes: instanceCount,
        dataNodeInstanceType: instanceType,
        masterNodes: dedicatedMasterEnabled ? 3 : undefined,
        masterNodeInstanceType: dedicatedMasterEnabled ? 't3.small.search' : undefined,
        multiAzWithStandbyEnabled: false,
      },

      // EBS configuration
      ebs: {
        volumeSize: ebsVolumeSize,
        volumeType: ec2.EbsDeviceVolumeType.GP3,
        throughput: 125,
        iops: 3000,
      },

      // Zone awareness
      zoneAwareness: multiAzEnabled
        ? {
            availabilityZoneCount: 2,
            enabled: true,
          }
        : {
            enabled: false,
          },

      // Security configuration
      encryptionAtRest: {
        enabled: encryptionAtRest,
      },
      nodeToNodeEncryption: true,
      enforceHttps: true,
      tlsSecurityPolicy: opensearch.TLSSecurityPolicy.TLS_1_2_PFS,

      // Fine-grained access control
      fineGrainedAccessControl: {
        masterUserName: masterUserName,
        masterUserPassword: this.masterUserSecret.secretValueFromJson('password'),
      },

      // Logging
      logging: {
        slowSearchLogEnabled: true,
        appLogEnabled: true,
        slowIndexLogEnabled: true,
      },

      // Access policy (open for demo, restrict in production)
      accessPolicies: [
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          principals: [new iam.AnyPrincipal()],
          actions: ['es:*'],
          resources: [`arn:aws:es:${region}:${account}:domain/${envPrefix}-ubi-ltr/*`],
        }),
      ],

      // Removal policy
      removalPolicy: cdk.RemovalPolicy.DESTROY,

      // Advanced options for plugins
      advancedOptions: {
        'rest.action.multi.allow_explicit_index': 'true',
        'indices.query.bool.max_clause_count': '4096',
      },
    });

    this.domainEndpoint = this.domain.domainEndpoint;

    // ===========================================================================
    // CloudWatch Log Groups for OSI Pipelines
    // ===========================================================================
    const osiLogGroup = new logs.LogGroup(this, 'OsiLogGroup', {
      logGroupName: `/aws/vendedlogs/OpenSearchIngestion/${envPrefix}-ubi`,
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ===========================================================================
    // OSI Pipeline Configuration (YAML)
    // ===========================================================================
    // Note: OSI pipelines must be created via AWS CLI or Console
    // as CDK L2 constructs are not yet available.
    // The following outputs provide the necessary configuration.

    const osiQueriesPipelineConfig = `
version: "2"
ubi-queries-pipeline:
  source:
    http:
      path: "/ubi/queries"
  processor:
    - date:
        from_time_received: true
        destination: "@timestamp"
  sink:
    - opensearch:
        hosts:
          - "https://${this.domain.domainEndpoint}"
        index: "ubi_queries"
        aws:
          sts_role_arn: "${props.osiPipelineRoleArn ?? 'REPLACE_WITH_OSI_ROLE_ARN'}"
          region: "${region}"
        dlq:
          s3:
            bucket: "${props.dlqBucketArn?.split(':').pop() ?? 'REPLACE_WITH_DLQ_BUCKET'}"
            key_path_prefix: "ubi-queries-dlq/"
            region: "${region}"
`;

    const osiEventsPipelineConfig = `
version: "2"
ubi-events-pipeline:
  source:
    http:
      path: "/ubi/events"
  processor:
    - date:
        from_time_received: true
        destination: "@timestamp"
  sink:
    - opensearch:
        hosts:
          - "https://${this.domain.domainEndpoint}"
        index: "ubi_events"
        aws:
          sts_role_arn: "${props.osiPipelineRoleArn ?? 'REPLACE_WITH_OSI_ROLE_ARN'}"
          region: "${region}"
        dlq:
          s3:
            bucket: "${props.dlqBucketArn?.split(':').pop() ?? 'REPLACE_WITH_DLQ_BUCKET'}"
            key_path_prefix: "ubi-events-dlq/"
            region: "${region}"
`;

    // ===========================================================================
    // Index Templates (for reference - apply via OpenSearch API)
    // ===========================================================================
    const ubiQueriesMapping = {
      mappings: {
        properties: {
          query_id: { type: 'keyword' },
          query_response_id: { type: 'keyword' },
          user_query: { type: 'text', fields: { keyword: { type: 'keyword' } } },
          application: { type: 'keyword' },
          timestamp: { type: 'date' },
          user_id: { type: 'keyword' },
          session_id: { type: 'keyword' },
          query_attributes: { type: 'object', enabled: false },
        },
      },
      settings: {
        number_of_shards: 1,
        number_of_replicas: 0,
        'index.knn': true,
      },
    };

    const ubiEventsMapping = {
      mappings: {
        properties: {
          action_name: { type: 'keyword' },
          query_id: { type: 'keyword' },
          timestamp: { type: 'date' },
          client_id: { type: 'keyword' },
          user_id: { type: 'keyword' },
          session_id: { type: 'keyword' },
          object_id: { type: 'keyword' },
          object_id_field: { type: 'keyword' },
          position: { type: 'integer' },
          message: { type: 'text' },
          event_attributes: { type: 'object', enabled: false },
        },
      },
      settings: {
        number_of_shards: 1,
        number_of_replicas: 0,
      },
    };

    const judgmentsMapping = {
      mappings: {
        properties: {
          query: { type: 'text', fields: { keyword: { type: 'keyword' } } },
          doc_id: { type: 'keyword' },
          product_name: { type: 'text' },
          rank: { type: 'integer' },
          rating: { type: 'float' },
          reason: { type: 'text' },
          model: { type: 'keyword' },
          timestamp: { type: 'date' },
        },
      },
      settings: {
        number_of_shards: 1,
        number_of_replicas: 0,
      },
    };

    // ===========================================================================
    // Outputs
    // ===========================================================================
    new cdk.CfnOutput(this, 'DomainEndpoint', {
      value: this.domain.domainEndpoint,
      description: 'OpenSearch domain endpoint',
      exportName: `${envPrefix}-OpenSearchDomainEndpoint`,
    });

    new cdk.CfnOutput(this, 'DomainArn', {
      value: this.domain.domainArn,
      description: 'OpenSearch domain ARN',
      exportName: `${envPrefix}-OpenSearchDomainArn`,
    });

    new cdk.CfnOutput(this, 'MasterUserSecretArn', {
      value: this.masterUserSecret.secretArn,
      description: 'ARN of the master user secret',
      exportName: `${envPrefix}-MasterUserSecretArn`,
    });

    new cdk.CfnOutput(this, 'DashboardUrl', {
      value: `https://${this.domain.domainEndpoint}/_dashboards`,
      description: 'OpenSearch Dashboards URL',
      exportName: `${envPrefix}-DashboardUrl`,
    });

    new cdk.CfnOutput(this, 'OsiQueriesPipelineConfig', {
      value: osiQueriesPipelineConfig.replace(/\n/g, '\\n'),
      description: 'OSI pipeline configuration for UBI queries (deploy manually)',
    });

    new cdk.CfnOutput(this, 'OsiEventsPipelineConfig', {
      value: osiEventsPipelineConfig.replace(/\n/g, '\\n'),
      description: 'OSI pipeline configuration for UBI events (deploy manually)',
    });

    new cdk.CfnOutput(this, 'UbiQueriesMapping', {
      value: JSON.stringify(ubiQueriesMapping),
      description: 'Index mapping for ubi_queries (apply via API)',
    });

    new cdk.CfnOutput(this, 'UbiEventsMapping', {
      value: JSON.stringify(ubiEventsMapping),
      description: 'Index mapping for ubi_events (apply via API)',
    });

    new cdk.CfnOutput(this, 'JudgmentsMapping', {
      value: JSON.stringify(judgmentsMapping),
      description: 'Index mapping for llm_judgments (apply via API)',
    });

    // ===========================================================================
    // SSM Parameters for Webapp Configuration
    // ===========================================================================
    new ssm.StringParameter(this, 'OpenSearchHostParameter', {
      parameterName: `/${envPrefix}/ubi-ltr/opensearch/host`,
      stringValue: this.domain.domainEndpoint,
      description: 'OpenSearch domain endpoint for webapp',
    });

    new ssm.StringParameter(this, 'OpenSearchRegionParameter', {
      parameterName: `/${envPrefix}/ubi-ltr/opensearch/region`,
      stringValue: region,
      description: 'OpenSearch region for webapp',
    });

    new ssm.StringParameter(this, 'ProductIndexParameter', {
      parameterName: `/${envPrefix}/ubi-ltr/opensearch/index-name`,
      stringValue: 'products',
      description: 'Product index name for webapp',
    });

    // Add tags
    cdk.Tags.of(this).add('Project', 'UBI-LTR');
    cdk.Tags.of(this).add('Environment', envPrefix);
    cdk.Tags.of(this).add('ManagedBy', 'CDK');
  }
}
