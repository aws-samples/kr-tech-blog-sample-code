import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';
import { EcomUbiStackProps } from './common';

/**
 * S3 bucket shared by the sample:
 *  - ubi-archive/   raw UBI queries/events archived by the OSI pipeline
 *  - osi-dlq/       OSI dead-letter queue
 *  - pipeline/      ML pipeline artifacts (stats, judgments, ranklib, models, metrics)
 */
export class EcomUbiStorageStack extends cdk.Stack {
  public readonly dataBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props: EcomUbiStackProps) {
    super(scope, id, props);

    this.dataBucket = new s3.Bucket(this, 'DataBucket', {
      bucketName: `${props.envPrefix}-data-${this.account}-${this.region}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      versioned: false,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      lifecycleRules: [
        {
          id: 'expire-ubi-archive',
          prefix: 'ubi-archive/',
          expiration: cdk.Duration.days(90),
        },
        {
          id: 'expire-dlq',
          prefix: 'osi-dlq/',
          expiration: cdk.Duration.days(30),
        },
      ],
    });

    new cdk.CfnOutput(this, 'DataBucketName', {
      value: this.dataBucket.bucketName,
      exportName: `${props.envPrefix}-data-bucket`,
    });
  }
}
