import {
    Stack,
    StackProps,
    aws_iot as iot,
    aws_iam as iam,
    aws_secretsmanager as secretsmanager,
    aws_kms as kms,
} from "aws-cdk-lib";
import { Construct } from "constructs";
import rulePolicyJson from "./rule/rule-policy.json";
import { Config } from "../config/config";
import ruleKeysJson from "./rule/rule-keys.json";
import keyPolicyJson from "./rule/key-policy.json";

export class AwsIotCoreRuleInfraStack extends Stack {
    constructor(scope: Construct, id: string, props?: StackProps) {
        super(scope, id, props);
        // For rules in IoT Core, please refer to this https://ap-northeast-2.console.aws.amazon.com/iot/home?region=ap-northeast-2#/rulehub
        // For role/policy for rules, please refer to https://docs.aws.amazon.com/iot/latest/developerguide/iot-create-role.html

        //  Create role for Rule engine
        let roleRuleEngine = new iam.Role(
            this, Config.app.service + "-" + Config.app.environment + "-rule-engine-role", {
                assumedBy: new iam.ServicePrincipal("iot.amazonaws.com"),
                description: "AWS I AM role for IoT rule engine",
                roleName: Config.app.service + "-" + Config.app.environment + "-rule-engine-role",
            }
        );

        // Create policy for rule engine
        let iotCoreRolePolicy = iam.PolicyDocument.fromJson(rulePolicyJson);

        let ruleEnginePolicy = new iam.Policy(
            this,
            Config.app.service +
            "-" +
            Config.app.environment +
            "-iot-core-role-policy",
            {
                document: iotCoreRolePolicy,
                policyName: "iotCoreRolePolicy",
            }
        );

        ruleEnginePolicy.attachToRole(roleRuleEngine)

        //Create Topic Rule Destination for Kafka, replace security group, subnet, and VPC values with your own
        let cfnTopicRuleDestination = new iot.CfnTopicRuleDestination(
            this,
            "MyCfnTopicRuleDestination",
            /* all optional props */ {
                vpcProperties: {
                    roleArn: roleRuleEngine.roleArn,
                    securityGroups: ["<VPC Security Group>"],
                    subnetIds: [
                        "<VPC subnet ID>",
                        "<VPC subnet ID>",
                    ],
                    vpcId: "<VPC ID>",
                },
            }
        );

        //CDK Unable to infer the rule destination requires IAM policies. Manually adding dependency
        cfnTopicRuleDestination.node.addDependency(ruleEnginePolicy)


        //Create KMS key for secret encryption
        keyPolicyJson.Statement[0].Principal.AWS = "arn:aws:iam::" + Config.aws.account + ":root"

        const key = new kms.CfnKey(this, "Key", {
            enabled: true,
            enableKeyRotation: false,
            keyPolicy: keyPolicyJson,
            keySpec: "SYMMETRIC_DEFAULT",
            keyUsage: "ENCRYPT_DECRYPT",
        });

        new kms.CfnAlias(this, "KeyAlias", {
            aliasName:
                "alias/" +
                Config.app.application +
                "-" +
                Config.app.environment +
                "-msk",
            targetKeyId: key.ref,
        });

        //Create AWS Secrets Manager Password for MSK connection 
        const iotSecret = new secretsmanager.CfnSecret(this, "IoTSecret", {
            name:
                "AmazonMSK_" +
                Config.app.application +
                "-" +
                Config.app.environment,
            kmsKeyId: key.ref,
            generateSecretString: {
                passwordLength: 20,
                excludeCharacters: "]/'",
                generateStringKey: "password",
                secretStringTemplate: JSON.stringify({username: "test-kafka"}),
            },
        });

        // Get rules from ruleKeysJson
        let testRuleKeys = ruleKeysJson.testRules;

        // Create Rules in IoT Core to send to S3 and MSK
        testRuleKeys.forEach((key) => {
            new iot.CfnTopicRule(
                this, Config.app.service + "-" + Config.app.environment + `-topic-rule-${key}`,
                {
                    topicRulePayload: {
                        actions: [
                            {
                                kafka: {
                                    clientProperties: {
                                        acks: "1",
                                        //Replace placeholder Kafka bootstrap Servers with your own
                                        "bootstrap.servers": Config.msk.bootstrapServers,
                                        "security.protocol": Config.msk.securityProtocol,
                                        "sasl.mechanism": Config.msk.saslMechanism,
                                        "sasl.scram.username":
                                            "${get_secret('AmazonMSK_iot','SecretString','username'," +
                                            `'${roleRuleEngine.roleArn}')}`,
                                        "sasl.scram.password":
                                            "${get_secret('AmazonMSK_iot','SecretString','password'," +
                                            `'${roleRuleEngine.roleArn}')}`,
                                    },
                                    destinationArn: cfnTopicRuleDestination.attrArn,
                                    topic: `test-msk-topic.${key}`
                                },
                            },
                        ],
                        sql: `SELECT * FROM 'test-rule/${key}'`,
                    },
                    // iot does not allow rule '-' (dash).
                    ruleName: `test_rule_${key}`,
                }
            );
        });
    }
}
