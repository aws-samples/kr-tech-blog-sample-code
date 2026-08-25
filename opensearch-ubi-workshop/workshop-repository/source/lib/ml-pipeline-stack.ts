import * as cdk from 'aws-cdk-lib';
import * as fs from 'fs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as path from 'path';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as sfn from 'aws-cdk-lib/aws-stepfunctions';
import * as tasks from 'aws-cdk-lib/aws-stepfunctions-tasks';
import { Construct } from 'constructs';
import { EcomUbiStackProps, importSharedRole, lambdaLogsStatement } from './common';

export interface MlStackProps extends EcomUbiStackProps {
  readonly dataBucket: s3.IBucket;
}

/**
 * Kubeflow-style ML pipeline implemented with Step Functions:
 *
 *   ExtractUbiData ──> GenerateJudgments ──> BuildFeatures ──> TrainModel ──> EvaluateModel
 *   (UBI aggregation)  (LLM-as-a-judge)     (LTR featureset    (XGBoost       (baseline vs LTR
 *    + CTR feedback     via ml-commons)      + feature logging)  LambdaMART)    nDCG/recall)
 *
 * Every step reads/writes artifacts under s3://<data-bucket>/pipeline/<run_id>/.
 */
export class EcomUbiMlStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: MlStackProps) {
    super(scope, id, props);

    const role = importSharedRole(this, props.sharedRoleArn);
    const policy = new iam.Policy(this, 'MlLambdaPolicy', {
      statements: [
        lambdaLogsStatement(),
        new iam.PolicyStatement({
          actions: ['s3:GetObject', 's3:PutObject', 's3:ListBucket'],
          resources: [props.dataBucket.bucketArn, `${props.dataBucket.bucketArn}/*`],
        }),
        new iam.PolicyStatement({
          // direct-Bedrock fallback for the judge step
          actions: ['bedrock:InvokeModel'],
          resources: [
            'arn:aws:bedrock:*::foundation-model/*',
            `arn:aws:bedrock:*:${this.account}:inference-profile/*`,
          ],
        }),
        new iam.PolicyStatement({
          actions: ['ssm:GetParameter', 'ssm:PutParameter'],
          resources: [`arn:aws:ssm:${this.region}:${this.account}:parameter/${props.envPrefix}/*`],
        }),
      ],
    });
    policy.attachToRole(role);

    const layer = new lambda.LayerVersion(this, 'DepsLayer', {
      code: lambda.Code.fromAsset(path.join(__dirname, '..', '.build', 'layer')),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_12],
      description: 'opensearch-py + requests-aws4auth',
    });

    const commonEnv: Record<string, string> = {
      OPENSEARCH_ENDPOINT: props.opensearchEndpoint,
      PRODUCTS_INDEX: props.productsIndex,
      UBI_QUERIES_INDEX: props.ubiQueriesIndex,
      UBI_EVENTS_INDEX: props.ubiEventsIndex,
      JUDGMENTS_INDEX: props.judgmentsIndex,
      METRICS_INDEX: props.metricsIndex,
      DATA_BUCKET: props.dataBucket.bucketName,
      JUDGE_MODEL_ID: props.judgeModelId,
      LTR_STORE: props.ltrStore,
      LTR_FEATURESET: props.ltrFeatureset,
      LTR_MODEL_PARAM: `/${props.envPrefix}/ltr/model-name`,
      APPLICATION: 'voltmall',
    };

    const mkFn = (name: string, file: string, timeoutMin: number, memory = 1024): lambda.Function => {
      const dir = path.join(__dirname, '..', '.build', 'functions', file);
      if (!fs.existsSync(path.join(dir, `${file}.py`))) {
        throw new Error(`missing ${dir} — run scripts/build.sh first`);
      }
      const fn = new lambda.Function(this, name, {
        functionName: `${props.envPrefix}-${file.replace(/_/g, '-')}`,
        runtime: lambda.Runtime.PYTHON_3_12,
        handler: `${file}.handler`,
        code: lambda.Code.fromAsset(dir),
        role,
        layers: [layer],
        timeout: cdk.Duration.minutes(timeoutMin),
        memorySize: memory,
        environment: commonEnv,
      });
      fn.node.addDependency(policy);
      return fn;
    };

    const extractFn = mkFn('ExtractFn', 'extract_ubi_data', 5);
    const judgeFn = mkFn('JudgeFn', 'generate_judgments', 15);
    const featuresFn = mkFn('FeaturesFn', 'build_features', 10);
    const evaluateFn = mkFn('EvaluateFn', 'evaluate_model', 10);

    const trainFn = new lambda.DockerImageFunction(this, 'TrainFn', {
      functionName: `${props.envPrefix}-train-ltr-model`,
      code: lambda.DockerImageCode.fromImageAsset(
        path.join(__dirname, '..', 'lambda', 'functions', 'train_ltr_model'),
      ),
      role,
      timeout: cdk.Duration.minutes(15),
      memorySize: 3008,
      environment: commonEnv,
    });
    trainFn.node.addDependency(policy);

    const mkTask = (id: string, fn: lambda.Function): tasks.LambdaInvoke => {
      const t = new tasks.LambdaInvoke(this, id, {
        lambdaFunction: fn,
        payloadResponseOnly: true,
        taskTimeout: sfn.Timeout.duration(cdk.Duration.minutes(16)),
      });
      t.addRetry({
        errors: ['Lambda.ServiceException', 'Lambda.SdkClientException', 'Lambda.TooManyRequestsException'],
        interval: cdk.Duration.seconds(10),
        maxAttempts: 3,
        backoffRate: 2,
      });
      return t;
    };

    const extractTask = new tasks.LambdaInvoke(this, 'ExtractUbiData', {
      lambdaFunction: extractFn,
      payloadResponseOnly: true,
      payload: sfn.TaskInput.fromObject({
        run_id: sfn.JsonPath.stringAt('$$.Execution.Name'),
        options: sfn.JsonPath.entirePayload,
      }),
    });
    extractTask.addRetry({
      errors: ['Lambda.ServiceException', 'Lambda.SdkClientException', 'Lambda.TooManyRequestsException'],
      interval: cdk.Duration.seconds(10),
      maxAttempts: 3,
      backoffRate: 2,
    });

    const judgeTask = mkTask('GenerateJudgments', judgeFn);
    const featuresTask = mkTask('BuildFeatures', featuresFn);
    const trainTask = mkTask('TrainModel', trainFn as unknown as lambda.Function);
    const evaluateTask = mkTask('EvaluateModel', evaluateFn);

    const definition = extractTask
      .next(judgeTask)
      .next(featuresTask)
      .next(trainTask)
      .next(evaluateTask);

    const sm = new sfn.StateMachine(this, 'LtrPipeline', {
      stateMachineName: `${props.envPrefix}-ltr-pipeline`,
      definitionBody: sfn.DefinitionBody.fromChainable(definition),
      timeout: cdk.Duration.hours(2),
    });

    new cdk.CfnOutput(this, 'StateMachineArn', { value: sm.stateMachineArn });
    new cdk.CfnOutput(this, 'DataBucketOut', { value: props.dataBucket.bucketName });
  }
}
