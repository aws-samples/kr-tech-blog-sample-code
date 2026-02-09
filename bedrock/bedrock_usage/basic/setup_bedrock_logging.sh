#!/bin/bash

# Bedrock Model Invocation Logging 설정 스크립트
# 이 스크립트는 Bedrock 로깅을 CloudWatch Logs로 자동 설정합니다.

set -e

echo "=========================================="
echo "Bedrock Model Invocation Logging Setup"
echo "=========================================="
echo ""

# 변수 설정
REGION="${AWS_REGION:-us-east-1}"
LOG_GROUP_NAME="/aws/bedrock/modelinvocations"
ROLE_NAME="BedrockModelInvocationLoggingRole"
POLICY_NAME="BedrockLoggingPolicy"

echo "📋 Configuration:"
echo "  Region: $REGION"
echo "  Log Group: $LOG_GROUP_NAME"
echo "  IAM Role: $ROLE_NAME"
echo ""

# 1. CloudWatch Logs 그룹 생성
echo "1️⃣  Creating CloudWatch Logs group..."
aws logs create-log-group \
    --log-group-name "$LOG_GROUP_NAME" \
    --region "$REGION" 2>/dev/null || echo "  ℹ️  Log group already exists"

echo "  ✅ Log group ready: $LOG_GROUP_NAME"
echo ""

# 2. IAM Role 생성 (이미 있으면 스킵)
echo "2️⃣  Creating IAM Role for Bedrock Logging..."

# Trust Policy
TRUST_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "bedrock.amazonaws.com"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "aws:SourceAccount": "$(aws sts get-caller-identity --query Account --output text)"
        }
      }
    }
  ]
}
EOF
)

aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY" \
    --description "Role for Bedrock to write invocation logs to CloudWatch" \
    2>/dev/null || echo "  ℹ️  Role already exists"

echo "  ✅ IAM Role ready: $ROLE_NAME"
echo ""

# 3. IAM Policy 생성 및 연결
echo "3️⃣  Creating and attaching IAM Policy..."

# Policy Document
POLICY_DOCUMENT=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:$REGION:$(aws sts get-caller-identity --query Account --output text):log-group:$LOG_GROUP_NAME:*"
    }
  ]
}
EOF
)

# Policy 생성
POLICY_ARN=$(aws iam create-policy \
    --policy-name "$POLICY_NAME" \
    --policy-document "$POLICY_DOCUMENT" \
    --query 'Policy.Arn' \
    --output text 2>/dev/null) || \
POLICY_ARN="arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):policy/$POLICY_NAME"

echo "  ℹ️  Policy ARN: $POLICY_ARN"

# Policy를 Role에 연결
aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn "$POLICY_ARN" 2>/dev/null || echo "  ℹ️  Policy already attached"

echo "  ✅ Policy attached to role"
echo ""

# 4. Bedrock Logging 구성
echo "4️⃣  Configuring Bedrock Model Invocation Logging..."

ROLE_ARN="arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):role/$ROLE_NAME"

# Logging Configuration (CloudWatch only, no S3)
LOGGING_CONFIG=$(cat <<EOF
{
  "cloudWatchConfig": {
    "logGroupName": "$LOG_GROUP_NAME",
    "roleArn": "$ROLE_ARN"
  },
  "textDataDeliveryEnabled": true,
  "imageDataDeliveryEnabled": false,
  "embeddingDataDeliveryEnabled": false
}
EOF
)

aws bedrock put-model-invocation-logging-configuration \
    --region "$REGION" \
    --logging-config "$LOGGING_CONFIG"

echo "  ✅ Bedrock logging configured"
echo ""

# 5. 설정 확인
echo "5️⃣  Verifying configuration..."
aws bedrock get-model-invocation-logging-configuration \
    --region "$REGION" \
    --output json

echo ""
echo "=========================================="
echo "✅ Setup Complete!"
echo "=========================================="
echo ""
echo "📝 Next Steps:"
echo "  1. Run the sample application:"
echo "     python bedrock_app_with_metadata.py"
echo ""
echo "  2. Wait 2-3 minutes for logs to appear"
echo ""
echo "  3. View logs in CloudWatch:"
echo "     https://console.aws.amazon.com/cloudwatch/home?region=$REGION#logsV2:log-groups/log-group/$(echo $LOG_GROUP_NAME | sed 's/\//%252F/g')"
echo ""
echo "  4. Use CloudWatch Logs Insights to query:"
echo "     See cloudwatch_insights_queries.md for example queries"
echo ""
