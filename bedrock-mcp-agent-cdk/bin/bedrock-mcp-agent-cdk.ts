#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { BedrockAgentStack } from '../lib/bedrock-agent-stack';
import * as path from 'path';
import * as fs from 'fs';
import { AwsSolutionsChecks } from 'cdk-nag';

class ValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ValidationError';
  }
}

class Application {
  private mcpConfigPath: any;
  private mcpConfig: any;
  private app = new cdk.App();
  private openApiSchemaPath: any;
  private openApiSchema: any;
  private awsRegion: string;
  private vpcId: string | undefined;
  private subnetIdList: string[] | undefined;

  constructor() {
    this.mcpConfigPath = path.join(__dirname, '../conf/mcp.json');
    this.openApiSchemaPath = path.join(__dirname, '../conf/generated_open_api_schema.json');
  }

  async initialize(): Promise<void> {
    // Context에서 VPC ID와 Subnet IDs 가져오기
    this.awsRegion = this.app.node.tryGetContext('region');
    this.vpcId = this.app.node.tryGetContext('vpcId');
    const subnetIds = this.app.node.tryGetContext('subnetIds');
    // this.vpcId = process.env.VPC_ID
    // const subnetIds = process.env.SUBNET_IDS

    // 필수 파라미터 검증
    if (!this.awsRegion) {
      throw new ValidationError('Missing required parameter. Please provide vpcId using: cdk deploy -c region=vpc-xxxx');
    }
    if (!this.vpcId) {
      throw new ValidationError('Missing required parameter. Please provide vpcId using: cdk deploy -c vpcId=vpc-xxxx');
    }
    if (!subnetIds) {
      throw new ValidationError('Missing required parameter. Please provide subnetIds using: cdk deploy -c subnetIds=subnet-xxxx,subnet-yyyy');
    }

    // Subnet IDs 형식 검증
    this.subnetIdList = subnetIds.split(',');
    if (this.subnetIdList) {
      if (this.subnetIdList.length === 0) {
        throw new ValidationError('At least one subnet ID must be provided');
      }

      for (const subnetId of this.subnetIdList) {
        if (!subnetId.match(/^subnet-[a-z0-9]+$/)) {
          throw new ValidationError(`Invalid subnet ID format: ${subnetId}. Must start with "subnet-"`);
        }
      }
    }

    console.log(this.mcpConfigPath);
    try {
      this.mcpConfig = JSON.parse(fs.readFileSync(this.mcpConfigPath, 'utf8'));
      this.openApiSchema = JSON.parse(fs.readFileSync(this.openApiSchemaPath, 'utf8'));
    } catch (error) {
      console.error('Failed to parse JSON file:', error);
      throw new ValidationError('Invalid JSON format in configuration file');
    }
  }

  run(): void {
    new BedrockAgentStack(this.app, 'BedrockAgentStack', {
      // env: { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION },
      env: { account: process.env.CDK_DEFAULT_ACCOUNT, region: this.awsRegion },
      mcpConfig: this.mcpConfig,
      openApiSchema: this.openApiSchema,
      vpcId: this.vpcId as string,
      subnetIds: this.subnetIdList  as string[]
    });

    cdk.Aspects.of(this.app).add(new AwsSolutionsChecks());
  }

  cleanup(): void {
  }
}

async function main() {
  const app = new Application();

  try {
    try {
      await app.initialize();
    } catch (error) {
      if (error instanceof ValidationError) {
        console.error('Error:', error.message);
        process.exit(1);
      } else {
        throw error;
      }
    }
      app.run();
      app.cleanup();
  }
  catch (error) {
    console.error("Application error:", error);
    process.exit(1);
  }
}

if (require.main === module) {
  main().catch(error => {
    console.error("Unhandled error:", error);
    process.exit(1);
  });
}


