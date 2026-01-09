#!/bin/bash
. ../conf/vpc-info

STACK_NAME=bedrock-agent-mcp-test-notebook

aws cloudformation create-stack \
    --stack-name $STACK_NAME \
    --template-body file://generated-sagemaker-notebook-template.yaml \
    --capabilities CAPABILITY_IAM \
    --region $AWS_REGION

echo -e "Waiting for stack operation to complete..."
if aws cloudformation wait stack-create-complete --stack-name $STACK_NAME --region $AWS_REGION 2>/dev/null || \
   aws cloudformation wait stack-update-complete --stack-name $STACK_NAME --region $AWS_REGION 2>/dev/null; then
    echo -e "Stack operation completed successfully"
else
    echo -e "Stack operation failed"
    exit 1
fi

# 노트북 인스턴스 이름
NOTEBOOK_NAME=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $AWS_REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`NotebookInstanceId`].OutputValue' \
    --output text | awk -F/ '{print $NF}')

# 노트북 인스턴스 상태 확인 및 대기
echo -e "Waiting for notebook instance to be ready..."
while true; do
    STATUS=$(aws sagemaker describe-notebook-instance \
        --notebook-instance-name $NOTEBOOK_NAME \
        --region $AWS_REGION \
        --query 'NotebookInstanceStatus' \
        --output text)
    
    if [ "$STATUS" = "InService" ]; then
        break
    elif [ "$STATUS" = "Failed" ]; then
        echo -e "Notebook instance creation failed$"
        exit 1
    fi
    
    echo -e "Current status: $STATUS. Waiting..."
    sleep 30
done

# 노트북 URL 출력
NOTEBOOK_URL="https://${AWS_REGION}.console.aws.amazon.com/sagemaker/home?region=${AWS_REGION}#/notebook-instances/openNotebook/${NOTEBOOK_NAME}?view=classic"
echo -e "Deployment completed successfully."
echo -e "Notebook URL: ${NOTEBOOK_URL}"
