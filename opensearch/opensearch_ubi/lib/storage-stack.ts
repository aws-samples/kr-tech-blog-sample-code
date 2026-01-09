/**
 * Storage Stack - S3 buckets for UBI to LTR pipeline.
 *
 * This stack creates:
 * - Data bucket for UBI events, judgments, and LTR training data
 * - Backup bucket for OSI dead-letter queue
 */

import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export interface StorageStackProps extends cdk.StackProps {
  /**
   * Environment prefix for resource naming.
   * @default 'dev'
   */
  readonly envPrefix?: string;

  /**
   * Number of days to retain data before transitioning to IA.
   * @default 30
   */
  readonly iaTransitionDays?: number;

  /**
   * Number of days to retain data before deletion.
   * @default 365
   */
  readonly retentionDays?: number;

  /**
   * Enable versioning for the data bucket.
   * @default true
   */
  readonly enableVersioning?: boolean;
}

export class StorageStack extends cdk.Stack {
  /**
   * Main data bucket for UBI events, judgments, and training data.
   */
  public readonly dataBucket: s3.Bucket;

  /**
   * Dead-letter queue bucket for failed OSI events.
   */
  public readonly dlqBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props: StorageStackProps = {}) {
    super(scope, id, props);

    const envPrefix = props.envPrefix ?? 'dev';
    const iaTransitionDays = props.iaTransitionDays ?? 30;
    const retentionDays = props.retentionDays ?? 365;
    const enableVersioning = props.enableVersioning ?? true;

    // ===========================================================================
    // Main Data Bucket
    // ===========================================================================
    this.dataBucket = new s3.Bucket(this, 'DataBucket', {
      bucketName: `${envPrefix}-ubi-ltr-data-${cdk.Stack.of(this).account}-${cdk.Stack.of(this).region}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      versioned: enableVersioning,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      lifecycleRules: [
        {
          id: 'TransitionToIA',
          enabled: true,
          transitions: [
            {
              storageClass: s3.StorageClass.INFREQUENT_ACCESS,
              transitionAfter: cdk.Duration.days(iaTransitionDays),
            },
            {
              storageClass: s3.StorageClass.GLACIER,
              transitionAfter: cdk.Duration.days(90),
            },
          ],
          expiration: cdk.Duration.days(retentionDays),
          noncurrentVersionExpiration: cdk.Duration.days(30),
        },
        {
          id: 'CleanupIncompleteUploads',
          enabled: true,
          abortIncompleteMultipartUploadAfter: cdk.Duration.days(7),
        },
      ],
      cors: [
        {
          allowedMethods: [s3.HttpMethods.GET, s3.HttpMethods.PUT, s3.HttpMethods.POST],
          allowedOrigins: ['*'],
          allowedHeaders: ['*'],
          maxAge: 3000,
        },
      ],
    });

    // Add bucket policy for secure access
    this.dataBucket.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: 'EnforceSSLOnly',
        effect: iam.Effect.DENY,
        principals: [new iam.AnyPrincipal()],
        actions: ['s3:*'],
        resources: [
          this.dataBucket.bucketArn,
          `${this.dataBucket.bucketArn}/*`,
        ],
        conditions: {
          Bool: {
            'aws:SecureTransport': 'false',
          },
        },
      })
    );

    // ===========================================================================
    // Dead-Letter Queue Bucket
    // ===========================================================================
    this.dlqBucket = new s3.Bucket(this, 'DlqBucket', {
      bucketName: `${envPrefix}-ubi-ltr-dlq-${cdk.Stack.of(this).account}-${cdk.Stack.of(this).region}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      versioned: false,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      lifecycleRules: [
        {
          id: 'ExpireOldDLQItems',
          enabled: true,
          expiration: cdk.Duration.days(14),
        },
      ],
    });

    // ===========================================================================
    // Folder Structure (using S3 object metadata pattern)
    // ===========================================================================
    // The following prefixes are expected:
    // - ubi-queries/           # Raw UBI query data exports
    // - ubi-events/            # Raw UBI event data exports
    // - judgments/             # LLM-generated judgment data
    //   - raw/                 # Raw judgment output
    //   - processed/           # Processed for LTR training
    // - ltr-training/          # LTR training datasets
    //   - features/            # Feature vectors
    //   - models/              # Trained model files
    // - exports/               # Exported data for external use
    // - backups/               # Backup files

    // ===========================================================================
    // Outputs
    // ===========================================================================
    new cdk.CfnOutput(this, 'DataBucketName', {
      value: this.dataBucket.bucketName,
      description: 'Name of the main data bucket',
      exportName: `${envPrefix}-DataBucketName`,
    });

    new cdk.CfnOutput(this, 'DataBucketArn', {
      value: this.dataBucket.bucketArn,
      description: 'ARN of the main data bucket',
      exportName: `${envPrefix}-DataBucketArn`,
    });

    new cdk.CfnOutput(this, 'DlqBucketName', {
      value: this.dlqBucket.bucketName,
      description: 'Name of the DLQ bucket',
      exportName: `${envPrefix}-DlqBucketName`,
    });

    new cdk.CfnOutput(this, 'DlqBucketArn', {
      value: this.dlqBucket.bucketArn,
      description: 'ARN of the DLQ bucket',
      exportName: `${envPrefix}-DlqBucketArn`,
    });

    // Add tags
    cdk.Tags.of(this).add('Project', 'UBI-LTR');
    cdk.Tags.of(this).add('Environment', envPrefix);
    cdk.Tags.of(this).add('ManagedBy', 'CDK');
  }

  /**
   * Grant read access to the data bucket.
   */
  public grantDataRead(grantee: iam.IGrantable): iam.Grant {
    return this.dataBucket.grantRead(grantee);
  }

  /**
   * Grant write access to the data bucket.
   */
  public grantDataWrite(grantee: iam.IGrantable): iam.Grant {
    return this.dataBucket.grantWrite(grantee);
  }

  /**
   * Grant read/write access to the data bucket.
   */
  public grantDataReadWrite(grantee: iam.IGrantable): iam.Grant {
    return this.dataBucket.grantReadWrite(grantee);
  }

  /**
   * Grant write access to the DLQ bucket.
   */
  public grantDlqWrite(grantee: iam.IGrantable): iam.Grant {
    return this.dlqBucket.grantWrite(grantee);
  }
}
