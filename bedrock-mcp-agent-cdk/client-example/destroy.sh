#!/bin/bash
. ../conf/vpc-info

STACK_NAME=bedrock-agent-mcp-test-notebook

aws cloudformation delete-stack \
    --stack-name $STACK_NAME \
    --region $AWS_REGION