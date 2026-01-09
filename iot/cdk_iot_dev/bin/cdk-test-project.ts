#!/usr/bin/env node

import { App } from "aws-cdk-lib";
import { AwsIotCoreProvisioningInfraStack } from "../lib/aws-iot-core-provisioning-infra-stack";
import { AwsIotCoreRuleInfraStack } from "../lib/aws-iot-core-rule-infra-stack";
import { Config } from "../config/config";

const app = new App();

new AwsIotCoreProvisioningInfraStack(app, "AwsIotCoreProvisioningInfraStack", {
    env: {
        account: Config.aws.account,
        region: Config.aws.region,
    },
});

new AwsIotCoreRuleInfraStack(app, "AwsIotCoreRuleInfraStack", {
    env: {
        account: Config.aws.account,
        region: Config.aws.region,
    },
});
