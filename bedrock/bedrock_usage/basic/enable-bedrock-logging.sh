#!/bin/bash

# 설정 변수
REGION="us-east-1"  # 원하는 리전으로 변경
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ROLE_NAME="BedrockLoggingRole"
LOG_GROUP_NAME="/aws/bedrock/modelinvocations"
S3_BUCKET_NAME=""  # S3 사용 시 버킷 이름 입력 (선택사항)
S3_KEY_PREFIX="bedrock-logs"  # S3 키 프리픽스 (선택사항)

ROLE_ARN="arn:aws:iam::$ACCOUNT_ID:role/$ROLE_NAME"

echo "=== Amazon Bedrock 모델 호출 로깅 활성화 ==="
echo "Region: $REGION"
echo "Role ARN: $ROLE_ARN"
echo "Log Group: $LOG_GROUP_NAME"
echo ""

# CloudWatch만 사용하는 경우
if [ -z "$S3_BUCKET_NAME" ]; then
    echo "CloudWatch Logs만 사용하여 로깅 설정 중..."
    aws bedrock put-model-invocation-logging-configuration \
        --region $REGION \
        --logging-config '{
            "cloudWatchConfig": {
                "logGroupName": "'"$LOG_GROUP_NAME"'",
                "roleArn": "'"$ROLE_ARN"'"
            },
            "textDataDeliveryEnabled": true,
            "imageDataDeliveryEnabled": true,
            "embeddingDataDeliveryEnabled": true
        }'
else
    # CloudWatch + S3 (대용량 데이터) 사용하는 경우
    echo "CloudWatch Logs + S3 (대용량 데이터)로 로깅 설정 중..."
    aws bedrock put-model-invocation-logging-configuration \
        --region $REGION \
        --logging-config '{
            "cloudWatchConfig": {
                "logGroupName": "'"$LOG_GROUP_NAME"'",
                "roleArn": "'"$ROLE_ARN"'",
                "largeDataDeliveryS3Config": {
                    "bucketName": "'"$S3_BUCKET_NAME"'",
                    "keyPrefix": "'"$S3_KEY_PREFIX"'"
                }
            },
            "textDataDeliveryEnabled": true,
            "imageDataDeliveryEnabled": true,
            "embeddingDataDeliveryEnabled": true
        }'
fi

if [ $? -eq 0 ]; then
    echo ""
    echo "✓ Bedrock 로깅 활성화 완료!"
    echo ""
    echo "로깅 상태 확인:"
    echo "aws bedrock get-model-invocation-logging-configuration --region $REGION"
    echo ""
    echo "CloudWatch Logs 확인:"
    echo "aws logs tail $LOG_GROUP_NAME --region $REGION --follow"
else
    echo ""
    echo "✗ 로깅 활성화 실패"
    echo "다음을 확인하세요:"
    echo "  1. IAM Role이 존재하는지: aws iam get-role --role-name $ROLE_NAME"
    echo "  2. Log Group이 존재하는지: aws logs describe-log-groups --log-group-name-prefix $LOG_GROUP_NAME --region $REGION"
    if [ ! -z "$S3_BUCKET_NAME" ]; then
        echo "  3. S3 버킷이 존재하는지: aws s3 ls s3://$S3_BUCKET_NAME"
    fi
fi
