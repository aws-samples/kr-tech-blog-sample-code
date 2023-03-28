import {
    Stack,
    StackProps,
    RemovalPolicy,
    aws_s3_deployment,
    aws_lambda as lambda,
    aws_iot as iot,
    aws_iam as iam,
    aws_s3 as s3
} from "aws-cdk-lib";
import {
    AwsCustomResource,
    AwsCustomResourcePolicy,
    PhysicalResourceId,
} from "aws-cdk-lib/custom-resources";
import { Construct } from "constructs";
import testDevicePolicyJson from "./device/device-policy.json";
import testProvisioningTemplateJson from "./device/provisioning-template.json";
import * as path from "path";
import { Config } from "../config/config";
import testDeviceClaimCertificatePolicyJson from "./device/device-cc-policy.json";

export class AwsIotCoreProvisioningInfraStack extends Stack {
    constructor(scope: Construct, id: string, props?: StackProps) {
        super(scope, id, props);

        // Modify testDevicePolicyJson according to Configs and create device policy for device policy
        testDevicePolicyJson.Statement[1].Resource = [
            `arn:aws:iot:${Config.aws.region}:${Config.aws.account}:topic/$aws/rules/*`,
            `arn:aws:iot:${Config.aws.region}:${Config.aws.account}:topic/` + '${iot:ClientId}'
        ]
        testDevicePolicyJson.Statement[2].Resource = [
            `arn:aws:iot:${Config.aws.region}:${Config.aws.account}:topicfilter/` + '${iot:ClientId}'
        ]

        let testDevicePolicy = new iot.CfnPolicy(
            this, Config.app.service + "-" + Config.app.environment + "device-policy",
            {
                policyDocument: testDevicePolicyJson,
                policyName: Config.app.service + "-" + Config.app.environment + "-device-policy",
            }
        );


        // Create role for pre-provisioning lambda for verification of devices
        let rolePreProvisioningLambda = new iam.Role(
            this, Config.app.service + "-" + Config.app.environment + "-pre-provisioning-lambda-role",
            {
                assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
                description: "AWS IAM role for pre-provisioning lambda",
                roleName: Config.app.service + "-" + Config.app.environment + "-pre-provisioning-lambda-role",
            }
        );


        // Crate lambda for pre-provisioning hook and add permission for invoke
        let lambdaPreProvisioningHook = new lambda.Function(
            this,
            Config.app.service + "-" + Config.app.environment +
            "-pre-provisioning-hook-lambda",
            {
                code: lambda.Code.fromAsset(path.join(__dirname, "device")),
                handler: "lambda_function.lambda_handler",
                runtime: lambda.Runtime.PYTHON_3_9,
                role: rolePreProvisioningLambda,
                description: "Lambda for pre-provisioning hook",
                functionName: Config.app.service + "-" + Config.app.environment + "-pre-provisioning-hook-lambda",
            }
        );

        lambdaPreProvisioningHook.addPermission("InvokePermission", {
            principal: new iam.ServicePrincipal("iot.amazonaws.com"),
            action: "lambda:InvokeFunction",
        });


        // Crate role for provisioning templates and add AWSIoTThingsRegistration policy
        let roleProvisioning = new iam.Role(
            this, Config.app.service + "-" + Config.app.environment + "-provisioning-template-role",
            {
                assumedBy: new iam.ServicePrincipal("iot.amazonaws.com"),
                description: "AWS IAM role for provisioning services",
                roleName: Config.app.service + "-" + Config.app.environment + "-provisioning-template-role",
            }
        );

        roleProvisioning.addManagedPolicy(
            iam.ManagedPolicy.fromAwsManagedPolicyName(
                "service-role/AWSIoTThingsRegistration"
            )
        );

        // Create provisioning template
        testProvisioningTemplateJson.Resources.policy.Properties.PolicyName = testDevicePolicy.policyName!

        let testProvisioningTemplate = new iot.CfnProvisioningTemplate(
            this, Config.app.service + "-" + Config.app.environment + "-provision-template",
            {
                provisioningRoleArn: roleProvisioning.roleArn,
                templateBody: JSON.stringify(testProvisioningTemplateJson),
                enabled: true,
                preProvisioningHook: {
                    "payloadVersion": "2020-04-01",
                    "targetArn": lambdaPreProvisioningHook.functionArn
                },
                description: "AWS IoT Provisioning Template",
                templateName: Config.app.service + "-" + Config.app.environment + "-provision-template",
            }
        );

        // Modify testDeviceClaimCertificatePolicyJson and create vehicle gateway policy for Claim Certificate
        let templateTopicCreate = `arn:aws:iot:${Config.aws.region}:${Config.aws.account}:topic/$aws/certificates/create/*`
        let templateTopicProvisioning = `arn:aws:iot:${Config.aws.region}:${Config.aws.account}:topic/$aws/provisioning-templates/${testProvisioningTemplate.templateName}/provision/*`
        testDeviceClaimCertificatePolicyJson.Statement[1].Resource = [templateTopicCreate, templateTopicProvisioning]

        let templateTopicFilterCreate = `arn:aws:iot:${Config.aws.region}:${Config.aws.account}:topicfilter/$aws/certificates/create/*`
        let templateTopicFilterProvisioning = `arn:aws:iot:${Config.aws.region}:${Config.aws.account}:topicfilter/$aws/provisioning-templates/${testProvisioningTemplate.templateName}/provision/*`
        testDeviceClaimCertificatePolicyJson.Statement[2].Resource = [templateTopicFilterCreate, templateTopicFilterProvisioning]

        let testDeviceClaimCertificatePolicy = new iot.CfnPolicy(
            this, Config.app.service + "-" + Config.app.environment + "-claim-certificate-policy",
            {
                policyDocument: testDeviceClaimCertificatePolicyJson,
                policyName: Config.app.service + "-" + Config.app.environment + "-claim-certificate-policy",
            }
        );

        // Create claim certificate by using AwsCustomResource
        let createKeysAndCertificateForClaimCertificate = new AwsCustomResource(
            this, Config.app.service + "-" + Config.app.environment + "-create-keys-and-certificate-for-claim-certificate",
            {
                onUpdate: {
                    service: "Iot",
                    action: "createKeysAndCertificate",
                    parameters: {setAsActive: true},
                    physicalResourceId: PhysicalResourceId.fromResponse("certificateId"),
                    outputPaths: ["certificateArn", "certificatePem", "keyPair.PublicKey", "keyPair.PrivateKey"],
                },
                policy: AwsCustomResourcePolicy.fromSdkCalls({resources: AwsCustomResourcePolicy.ANY_RESOURCE}),
            }
        );


        // Attach policy to claim certificate
        let PolicyPrincipalAttachmentForClaimCertificate =
            new iot.CfnPolicyPrincipalAttachment(
                this, Config.app.service + "-" + Config.app.environment + "policy-principal-attachment", {
                    policyName: testDeviceClaimCertificatePolicy.policyName!,
                    principal: createKeysAndCertificateForClaimCertificate.getResponseField("certificateArn"),
                }
            );

        let cdkTestS3Bucket = new s3.Bucket(this, 'cdkTestS3Bucket', {
                blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
                versioned: true,
                removalPolicy: RemovalPolicy.DESTROY,
                autoDeleteObjects: true,
                bucketName: `${Config.s3BucketName}`
            }
        );


        // Save the vehicle-gateway certificates and keys to S3
        let keyDeploymentForDeviceClaimCertificate = new aws_s3_deployment.BucketDeployment(
            this, Config.app.service + "-" + Config.app.environment + "put-key-to-s3",
            {
                destinationBucket: cdkTestS3Bucket,
                sources: [
                    aws_s3_deployment.Source.data(
                        "claim-certificate/claim.pem",
                        createKeysAndCertificateForClaimCertificate.getResponseField(
                            "certificatePem"
                        )
                    ),
                    aws_s3_deployment.Source.data(
                        "claim-certificate/claim.public.key",
                        createKeysAndCertificateForClaimCertificate.getResponseField(
                            "keyPair.PublicKey"
                        )
                    ),
                    aws_s3_deployment.Source.data(
                        "claim-certificate/claim.private.key",
                        createKeysAndCertificateForClaimCertificate.getResponseField(
                            "keyPair.PrivateKey"
                        )
                    ),
                ],
            }
        );
    }
}
