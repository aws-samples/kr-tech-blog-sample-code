#!/bin/bash
#The default region is Oregon. There are code dependencies on the Oregon region. Changing regions requires code modifications
export AWS_REGION=us-west-2

STACK_NAME=bedrock-agent-mcp-test-vpc

aws cloudformation create-stack \
    --stack-name $STACK_NAME \
    --template-body file://base-vpc.yaml \
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

VPC_ID=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $AWS_REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`VpcId`].OutputValue' \
    --output text)

PRIVATE_SUBNET1_ID=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $AWS_REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`PrivateSubnet1Id`].OutputValue' \
    --output text)

PRIVATE_SUBNET2_ID=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $AWS_REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`PrivateSubnet2Id`].OutputValue' \
    --output text)

cat << EOF > ../conf/vpc-info
#!/bin/bash
export AWS_REGION=us-west-2
export VPC_ID=${VPC_ID}
export SUBNET_IDS=${PRIVATE_SUBNET1_ID},${PRIVATE_SUBNET2_ID}
EOF

echo ../conf/vpc-info is generated as shown below:
cat ../conf/vpc-info