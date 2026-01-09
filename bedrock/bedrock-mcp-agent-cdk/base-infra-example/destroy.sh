#!/bin/bash
#The default region is Oregon. There are code dependencies on the Oregon region. Changing regions requires code modifications
export AWS_REGION=us-west-2

STACK_NAME=bedrock-agent-mcp-test-vpc

aws cloudformation delete-stack \
    --stack-name $STACK_NAME \
    --region $AWS_REGION