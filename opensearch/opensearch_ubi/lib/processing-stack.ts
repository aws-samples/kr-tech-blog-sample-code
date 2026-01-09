/**
 * Processing Stack - Lambda functions and Step Functions for UBI to LTR pipeline.
 *
 * This stack creates:
 * - Lambda functions for data extraction, judgment generation, and LTR training
 * - Step Functions state machine for orchestration
 * - EventBridge rules for scheduled execution
 */

import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as stepfunctions from 'aws-cdk-lib/aws-stepfunctions';
import * as tasks from 'aws-cdk-lib/aws-stepfunctions-tasks';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as path from 'path';
import { Construct } from 'constructs';

export interface ProcessingStackProps extends cdk.StackProps {
  /**
   * Environment prefix for resource naming.
   * @default 'dev'
   */
  readonly envPrefix?: string;

  /**
   * OpenSearch domain endpoint.
   */
  readonly openSearchEndpoint: string;

  /**
   * ARN of the master user secret.
   */
  readonly masterUserSecretArn: string;

  /**
   * Data bucket.
   */
  readonly dataBucket: s3.IBucket;

  /**
   * Lambda execution role ARN.
   * Pass ARN instead of role object to avoid circular dependencies.
   */
  readonly lambdaExecutionRoleArn: string;

  /**
   * Step Functions role ARN.
   * Pass ARN instead of role object to avoid circular dependencies.
   */
  readonly stepFunctionsRoleArn: string;

  /**
   * Bedrock model ID for LLM judgments.
   * @default 'us.anthropic.claude-sonnet-4-5-20250929-v1:0'
   */
  readonly bedrockModelId?: string;

  /**
   * Enable scheduled execution.
   * @default false
   */
  readonly enableSchedule?: boolean;

  /**
   * Schedule expression for pipeline execution.
   * @default 'rate(1 day)'
   */
  readonly scheduleExpression?: string;
}

export class ProcessingStack extends cdk.Stack {
  /**
   * Lambda function for extracting UBI data.
   */
  public readonly extractUbiDataFunction: lambda.Function;

  /**
   * Lambda function for generating LLM judgments.
   */
  public readonly generateJudgmentsFunction: lambda.Function;

  /**
   * Lambda function for preparing LTR training data.
   */
  public readonly prepareLtrDataFunction: lambda.Function;

  /**
   * Lambda function for training LTR model.
   */
  public readonly trainLtrModelFunction: lambda.Function;

  /**
   * Step Functions state machine for the pipeline.
   */
  public readonly stateMachine: stepfunctions.StateMachine;

  constructor(scope: Construct, id: string, props: ProcessingStackProps) {
    super(scope, id, props);

    const envPrefix = props.envPrefix ?? 'dev';
    const bedrockModelId = props.bedrockModelId ?? 'us.anthropic.claude-sonnet-4-5-20250929-v1:0';
    const enableSchedule = props.enableSchedule ?? false;
    const scheduleExpression = props.scheduleExpression ?? 'rate(1 day)';

    const region = cdk.Stack.of(this).region;

    // Import roles by ARN to avoid circular dependencies
    // Using mutable: false prevents CDK from trying to modify the role
    const lambdaExecutionRole = iam.Role.fromRoleArn(
      this,
      'ImportedLambdaRole',
      props.lambdaExecutionRoleArn,
      { mutable: false }
    );

    const stepFunctionsRole = iam.Role.fromRoleArn(
      this,
      'ImportedStepFunctionsRole',
      props.stepFunctionsRoleArn,
      { mutable: false }
    );

    // Common Lambda environment variables
    const commonEnv = {
      OPENSEARCH_ENDPOINT: props.openSearchEndpoint,
      MASTER_USER_SECRET_ARN: props.masterUserSecretArn,
      DATA_BUCKET: props.dataBucket.bucketName,
      AWS_REGION_NAME: region,
      BEDROCK_MODEL_ID: bedrockModelId,
      LOG_LEVEL: 'INFO',
    };

    // Lambda layer for common dependencies
    const dependenciesLayer = new lambda.LayerVersion(this, 'DependenciesLayer', {
      layerVersionName: `${envPrefix}-ubi-dependencies`,
      description: 'Common dependencies for UBI-LTR Lambda functions',
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_12],
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda/layers/dependencies')),
    });

    // ===========================================================================
    // Extract UBI Data Lambda
    // ===========================================================================
    this.extractUbiDataFunction = new lambda.Function(this, 'ExtractUbiDataFunction', {
      functionName: `${envPrefix}-ubi-extract-data`,
      description: 'Extract UBI queries and events from OpenSearch',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'extract_ubi_data.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda/functions/extract_ubi_data')),
      role: lambdaExecutionRole,
      timeout: cdk.Duration.minutes(5),
      memorySize: 512,
      environment: {
        ...commonEnv,
        UBI_QUERIES_INDEX: 'ubi_queries',
        UBI_EVENTS_INDEX: 'ubi_events',
      },
      layers: [dependenciesLayer],
      logRetention: logs.RetentionDays.TWO_WEEKS,
    });

    // ===========================================================================
    // Generate Judgments Lambda
    // ===========================================================================
    this.generateJudgmentsFunction = new lambda.Function(this, 'GenerateJudgmentsFunction', {
      functionName: `${envPrefix}-ubi-generate-judgments`,
      description: 'Generate relevance judgments using Claude Sonnet 4.5',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'generate_judgments.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda/functions/generate_judgments')),
      role: lambdaExecutionRole,
      timeout: cdk.Duration.minutes(15),
      memorySize: 1024,
      environment: {
        ...commonEnv,
        PRODUCTS_INDEX: 'products',
        JUDGMENTS_INDEX: 'llm_judgments',
        TOP_K_DOCS: '10',
        RATE_LIMIT_DELAY: '0.5',
      },
      layers: [dependenciesLayer],
      logRetention: logs.RetentionDays.TWO_WEEKS,
    });

    // ===========================================================================
    // Prepare LTR Data Lambda
    // ===========================================================================
    this.prepareLtrDataFunction = new lambda.Function(this, 'PrepareLtrDataFunction', {
      functionName: `${envPrefix}-ubi-prepare-ltr-data`,
      description: 'Prepare training data for LTR model',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'prepare_ltr_data.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda/functions/prepare_ltr_data')),
      role: lambdaExecutionRole,
      timeout: cdk.Duration.minutes(10),
      memorySize: 1024,
      environment: {
        ...commonEnv,
        JUDGMENTS_INDEX: 'llm_judgments',
        FEATURE_STORE_INDEX: 'ltr_features',
      },
      layers: [dependenciesLayer],
      logRetention: logs.RetentionDays.TWO_WEEKS,
    });

    // ===========================================================================
    // Train LTR Model Lambda
    // ===========================================================================
    this.trainLtrModelFunction = new lambda.Function(this, 'TrainLtrModelFunction', {
      functionName: `${envPrefix}-ubi-train-ltr-model`,
      description: 'Train and upload LTR model to OpenSearch',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'train_ltr_model.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda/functions/train_ltr_model')),
      role: lambdaExecutionRole,
      timeout: cdk.Duration.minutes(15),
      memorySize: 2048,
      environment: {
        ...commonEnv,
        LTR_STORE_NAME: 'ubi_ltr_store',
        LTR_FEATURESET_NAME: 'ubi_features',
        LTR_MODEL_NAME: 'ubi_ltr_model',
      },
      layers: [dependenciesLayer],
      logRetention: logs.RetentionDays.TWO_WEEKS,
    });

    // ===========================================================================
    // Step Functions State Machine
    // ===========================================================================

    // Define tasks - use payloadResponseOnly to get Lambda response directly
    const extractUbiTask = new tasks.LambdaInvoke(this, 'ExtractUbiData', {
      lambdaFunction: this.extractUbiDataFunction,
      payloadResponseOnly: true,
      resultPath: '$.extractResult',
      retryOnServiceExceptions: true,
    });

    const generateJudgmentsTask = new tasks.LambdaInvoke(this, 'GenerateJudgments', {
      lambdaFunction: this.generateJudgmentsFunction,
      payloadResponseOnly: true,
      resultPath: '$.judgmentsResult',
      retryOnServiceExceptions: true,
    });

    const prepareLtrTask = new tasks.LambdaInvoke(this, 'PrepareLtrData', {
      lambdaFunction: this.prepareLtrDataFunction,
      payloadResponseOnly: true,
      resultPath: '$.ltrDataResult',
      retryOnServiceExceptions: true,
    });

    const trainLtrTask = new tasks.LambdaInvoke(this, 'TrainLtrModel', {
      lambdaFunction: this.trainLtrModelFunction,
      payloadResponseOnly: true,
      resultPath: '$.trainingResult',
      retryOnServiceExceptions: true,
    });

    // Success and failure states
    const pipelineSuccess = new stepfunctions.Succeed(this, 'PipelineSuccess', {
      comment: 'UBI to LTR pipeline completed successfully',
    });

    const pipelineFailure = new stepfunctions.Fail(this, 'PipelineFailed', {
      error: 'PipelineExecutionFailed',
      cause: 'One or more steps in the pipeline failed',
    });

    // Check if data was extracted
    const checkExtractResult = new stepfunctions.Choice(this, 'CheckExtractResult')
      .when(
        stepfunctions.Condition.numberGreaterThan('$.extractResult.queryCount', 0),
        generateJudgmentsTask
      )
      .otherwise(
        new stepfunctions.Pass(this, 'NoDataToProcess', {
          result: stepfunctions.Result.fromObject({ message: 'No new UBI data to process' }),
        }).next(pipelineSuccess)
      );

    // Check if judgments were generated
    const checkJudgmentsResult = new stepfunctions.Choice(this, 'CheckJudgmentsResult')
      .when(
        stepfunctions.Condition.numberGreaterThan('$.judgmentsResult.judgmentCount', 0),
        prepareLtrTask
      )
      .otherwise(
        new stepfunctions.Pass(this, 'NoJudgmentsGenerated', {
          result: stepfunctions.Result.fromObject({ message: 'No judgments generated' }),
        }).next(pipelineSuccess)
      );

    // Check if LTR data was prepared
    const checkLtrDataResult = new stepfunctions.Choice(this, 'CheckLtrDataResult')
      .when(
        stepfunctions.Condition.booleanEquals('$.ltrDataResult.success', true),
        trainLtrTask
      )
      .otherwise(
        new stepfunctions.Pass(this, 'LtrDataPreparationFailed', {
          result: stepfunctions.Result.fromObject({ message: 'LTR data preparation failed' }),
        }).next(pipelineFailure)
      );

    // Build the state machine definition
    const definition = extractUbiTask
      .addCatch(pipelineFailure, { resultPath: '$.error' })
      .next(checkExtractResult);

    generateJudgmentsTask
      .addCatch(pipelineFailure, { resultPath: '$.error' })
      .next(checkJudgmentsResult);

    prepareLtrTask
      .addCatch(pipelineFailure, { resultPath: '$.error' })
      .next(checkLtrDataResult);

    trainLtrTask
      .addCatch(pipelineFailure, { resultPath: '$.error' })
      .next(pipelineSuccess);

    // Create the state machine
    this.stateMachine = new stepfunctions.StateMachine(this, 'UbiLtrPipeline', {
      stateMachineName: `${envPrefix}-ubi-ltr-pipeline`,
      definition,
      role: stepFunctionsRole,
      timeout: cdk.Duration.hours(2),
      tracingEnabled: true,
      logs: {
        destination: new logs.LogGroup(this, 'StateMachineLogGroup', {
          logGroupName: `/aws/stepfunctions/${envPrefix}-ubi-ltr-pipeline`,
          retention: logs.RetentionDays.TWO_WEEKS,
          removalPolicy: cdk.RemovalPolicy.DESTROY,
        }),
        level: stepfunctions.LogLevel.ALL,
        includeExecutionData: true,
      },
    });

    // ===========================================================================
    // EventBridge Schedule (Optional)
    // ===========================================================================
    if (enableSchedule) {
      new events.Rule(this, 'ScheduledExecution', {
        ruleName: `${envPrefix}-ubi-ltr-schedule`,
        description: 'Scheduled execution of UBI to LTR pipeline',
        schedule: events.Schedule.expression(scheduleExpression),
        targets: [new targets.SfnStateMachine(this.stateMachine)],
        enabled: true,
      });
    }

    // ===========================================================================
    // Outputs
    // ===========================================================================
    new cdk.CfnOutput(this, 'ExtractUbiDataFunctionArn', {
      value: this.extractUbiDataFunction.functionArn,
      description: 'ARN of the Extract UBI Data Lambda function',
      exportName: `${envPrefix}-ExtractUbiDataFunctionArn`,
    });

    new cdk.CfnOutput(this, 'GenerateJudgmentsFunctionArn', {
      value: this.generateJudgmentsFunction.functionArn,
      description: 'ARN of the Generate Judgments Lambda function',
      exportName: `${envPrefix}-GenerateJudgmentsFunctionArn`,
    });

    new cdk.CfnOutput(this, 'PrepareLtrDataFunctionArn', {
      value: this.prepareLtrDataFunction.functionArn,
      description: 'ARN of the Prepare LTR Data Lambda function',
      exportName: `${envPrefix}-PrepareLtrDataFunctionArn`,
    });

    new cdk.CfnOutput(this, 'TrainLtrModelFunctionArn', {
      value: this.trainLtrModelFunction.functionArn,
      description: 'ARN of the Train LTR Model Lambda function',
      exportName: `${envPrefix}-TrainLtrModelFunctionArn`,
    });

    new cdk.CfnOutput(this, 'StateMachineArn', {
      value: this.stateMachine.stateMachineArn,
      description: 'ARN of the Step Functions state machine',
      exportName: `${envPrefix}-StateMachineArn`,
    });

    new cdk.CfnOutput(this, 'StateMachineUrl', {
      value: `https://${region}.console.aws.amazon.com/states/home?region=${region}#/statemachines/view/${this.stateMachine.stateMachineArn}`,
      description: 'URL to view the state machine in AWS Console',
    });

    // Add tags
    cdk.Tags.of(this).add('Project', 'UBI-LTR');
    cdk.Tags.of(this).add('Environment', envPrefix);
    cdk.Tags.of(this).add('ManagedBy', 'CDK');
  }
}
