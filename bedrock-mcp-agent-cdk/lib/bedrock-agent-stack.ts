import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { Construct } from 'constructs';
import { NodejsFunction } from "aws-cdk-lib/aws-lambda-nodejs";

interface McpServerConfig {
  command: string;
  args: string[];
  bundling?: any
}

interface BedrockAgentStackProps extends cdk.StackProps {
  mcpConfig: any,
  openApiSchema: any,
  vpcId: string,
  subnetIds: string[]
}

export class BedrockAgentStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: BedrockAgentStackProps) {
    super(scope, id, props);

    const accountId = cdk.Stack.of(this).account;
    const region = cdk.Stack.of(this).region;
    const novaInferenceProfileArn = `arn:aws:bedrock:${region}:${accountId}:inference-profile/us.amazon.nova-pro-v1:0`;
    const novaModelArn = "arn:aws:bedrock:*::foundation-model/amazon.nova-pro-v1:0";

    const vpc = ec2.Vpc.fromLookup(this, 'VPC', {
      vpcId: props.vpcId
    });
 
    const lambdaSg = new ec2.SecurityGroup(this, 'LambdaSecurityGroup', {
      vpc,
      description: 'Security group for Lambda function',
      allowAllOutbound: true
    });

    const subnets = props.subnetIds.map(subnetId => 
      ec2.Subnet.fromSubnetId(this, subnetId, subnetId)
    )

    // Create a Lambda function for each MCP server
    let lambdaFunctions = [];
    let actionGroups = [];
    for (const [mcpServerName, mcpServerConfig] of Object.entries(props.mcpConfig.mcpServers) as [string, McpServerConfig][]) {
      let bundling = {
        externalModules: ['@aws-sdk/*'],
          docker: false,
          forceDockerBundling: false
      };
      
      if (mcpServerConfig.bundling) {
        bundling = {
          ...mcpServerConfig.bundling,
          externalModules: [
            ...(mcpServerConfig.bundling.externalModules || []),
            '@aws-sdk/*'
          ],
          docker: false,
          forceDockerBundling: false
        };
      }

      const lambdaFunction = new NodejsFunction(this, `McpHandler-${mcpServerName}`, {
        runtime: cdk.aws_lambda.Runtime.NODEJS_22_X,
        handler: 'index.handler',
        entry: path.join(__dirname, '../lambda/mcp_action_group_handler/index.mjs'),
        timeout: cdk.Duration.seconds(180),
        memorySize: 512,
        environment: {
          MCP_SERVER_NAME: mcpServerName,
          MCP_SERVER_CONFIG: Buffer.from(JSON.stringify(mcpServerConfig)).toString('base64')
        },
        vpc,
        vpcSubnets: {
          subnets: subnets
        },
        securityGroups: [lambdaSg],
        bundling: bundling
      });
      lambdaFunctions.push(lambdaFunction);


      actionGroups.push({
        // '-' is not allowed for action group name
        ActionGroupName: `${mcpServerName.replace(/-/g, '_')}`,
        ActionGroupExecutor: {
          Lambda: lambdaFunction.functionArn
        },
        ApiSchema: {
          Payload: JSON.stringify(props.openApiSchema[mcpServerName], null, 2)
        }
      })
    }

    const statements = [
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream', 'bedrock:GetInferenceProfile', 'bedrock:GetFoundationModel'],
        resources: [novaInferenceProfileArn, novaModelArn]
      }),
      // new iam.PolicyStatement({
      //   effect: iam.Effect.ALLOW,
      //   actions: ['s3:GetObject', 's3:GetObjectVersion', 's3:GetObjectVersionAttributes', 's3:GetObjectAttributes'],
      //   resources: ['*']
      // }),
      // new iam.PolicyStatement({
      //   effect: iam.Effect.ALLOW,
      //   actions: ['bedrock:Retrieve', 'bedrock:RetrieveAndGenerate'],
      //   resources: ['*']
      // }),
      // new iam.PolicyStatement({
      //   effect: iam.Effect.ALLOW,
      //   actions: ['bedrock:AssociateThirdPartyKnowledgeBase'],
      //   resources: ['*']
      // }),
      // new iam.PolicyStatement({
      //   effect: iam.Effect.ALLOW,
      //   actions: ['bedrock:GetPrompt'],
      //   resources: ['*']
      // }),
      // new iam.PolicyStatement({
      //   effect: iam.Effect.ALLOW,
      //   actions: ['bedrock:GetAgentAlias', 'bedrock:InvokeAgent'],
      //   resources: ['*']
      // }),
      // new iam.PolicyStatement({
      //   effect: iam.Effect.ALLOW,
      //   actions: ['bedrock:ApplyGuardrail'],
      //   resources: ['*']
      // }),
    ]

    // Create IAM role for Bedrock Agent
    const bedrockAgentRole = new iam.Role(this, 'BedrockAgentRole', {
      assumedBy: new iam.ServicePrincipal('bedrock.amazonaws.com'),
      description: 'Role for Bedrock Agent',
      inlinePolicies: {
        'BedrockAgentInlinePolicy': new iam.PolicyDocument({
          statements: statements,
        }),
      },
    });

    const bedrockAgent = new cdk.CfnResource(this, 'BedrockAgent', {
      type: 'AWS::Bedrock::Agent',
      properties: {
        AgentName: 'BedrockMcpDemoAgent',
        AgentResourceRoleArn: bedrockAgentRole.roleArn,
        FoundationModel: novaInferenceProfileArn,
        AutoPrepare: true,
        Description: 'An agent that provides MCP capability',
        IdleSessionTTLInSeconds: 1800,
        Instruction: `You are an intelligent and resourceful assistant with access to extensive knowledge and various actions. Your role is to:

1. Provide comprehensive solutions by:
   - Utilizing all available knowledge in your training
   - Leveraging all accessible actions and tools
   - Combining multiple approaches when beneficial

2. Communicate effectively by:
   - Responding in the user's preferred language
   - Structuring answers clearly and logically
   - Using appropriate formatting for better readability

3. Ensure optimal assistance by:
   - Understanding the context and intent of queries
   - Considering multiple perspectives and solutions
   - Providing practical and actionable recommendations
   - Explaining complex concepts in an accessible way

4. Maintain high quality by:
   - Verifying information accuracy
   - Acknowledging limitations when present
   - Asking clarifying questions when needed
   - Providing sources or references when applicable

5. Adapt communication style to:
   - Match user's technical level
   - Respect cultural considerations
   - Maintain professional yet friendly tone

When responding, first analyze the query thoroughly, then utilize all relevant knowledge and available actions to provide the most helpful and comprehensive solution possible.

Language preference: Respond in the same language as the user's query, defaulting to English if unclear.`,
        ActionGroups: actionGroups
      }
    });

    for(const lambdaFunction of lambdaFunctions) {
      lambdaFunction.addPermission('BedrockInvokePermission', {
        principal: new iam.ServicePrincipal('bedrock.amazonaws.com'),
        action: 'lambda:InvokeFunction',
        sourceAccount: accountId,
        sourceArn: `arn:aws:bedrock:${region}:${accountId}:agent/${bedrockAgent.getAtt('AgentId')}`,
      });
    }

    // Output the Agent ID and Alias ID
    new cdk.CfnOutput(this, 'BedrockAgentId', {
      value: bedrockAgent.ref,
      description: 'The ID of the Bedrock Agent'
    });
  }
}
