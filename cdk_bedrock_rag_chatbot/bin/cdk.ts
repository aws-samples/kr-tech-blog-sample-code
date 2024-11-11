#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { Ec2Stack } from '../lib/ec2stack';

const STACK_PREFIX = "RAGChatbot";
const DEFAULT_REGION = "us-west-2";
const envSetting = {
  env: {
    account: process.env.CDK_DEPLOY_ACCOUNT || process.env.CDK_DEFAULT_ACCOUNT,
    region: DEFAULT_REGION,
  },
};

const app = new cdk.App();

new Ec2Stack(app, `${STACK_PREFIX}-Ec2Stack`, envSetting);

app.synth();
