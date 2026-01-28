#!/bin/bash

# 설정 변수
ROLE_NAME="BedrockLoggingRole"
REGION="us-east-1"  # 원하는 리전으로 변경
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
LOG_GROUP_NAME="/aws/bedrock/modelinvocations"

# 사용법 출력
usage() {
    echo "사용법: $0 [OPTIONS]"
    echo ""
    echo "옵션:"
    echo "  --type <TYPE>         로깅 타입: cloudwatch-only | s3-only | both (기본값: cloudwatch-only)"
    echo "  --bucket <NAME>       S3 버킷 이름 (s3-only 또는 both 선택 시 필수)"
    echo "  -h, --help            도움말 표시"
    echo ""
    echo "예제:"
    echo "  $0 --type cloudwatch-only"
    echo "  $0 --type s3-only --bucket my-bedrock-logs"
    echo "  $0 --type both --bucket my-bedrock-logs"
    exit 1
}

# 기본값 설정
LOGGING_TYPE="cloudwatch-only"
S3_BUCKET_NAME=""

# 인자 파싱
while [[ $# -gt 0 ]]; do
    case $1 in
        --type)
            LOGGING_TYPE="$2"
            shift 2
            ;;
        --bucket)
            S3_BUCKET_NAME="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "알 수 없는 옵션: $1"
            usage
            ;;
    esac
done

# 로깅 타입 검증
if [[ "$LOGGING_TYPE" != "cloudwatch-only" && "$LOGGING_TYPE" != "s3-only" && "$LOGGING_TYPE" != "both" ]]; then
    echo "오류: 유효하지 않은 로깅 타입입니다: $LOGGING_TYPE"
    usage
fi

# S3 버킷 이름 검증
if [[ "$LOGGING_TYPE" == "s3-only" || "$LOGGING_TYPE" == "both" ]]; then
    if [ -z "$S3_BUCKET_NAME" ]; then
        echo "오류: --type $LOGGING_TYPE 사용 시 --bucket 옵션이 필수입니다."
        usage
    fi
fi

echo ""
echo "=== Amazon Bedrock 로깅 역할 생성 시작 ==="
echo "Account ID: $ACCOUNT_ID"
echo "Region: $REGION"
echo "Logging Type: $LOGGING_TYPE"
echo "S3 Bucket: $S3_BUCKET_NAME"
echo ""

# 1. Trust Policy 생성
echo "[1/5] Trust Policy 생성 중..."
cat > bedrock-trust-policy.json <<EOF
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
                    "aws:SourceAccount": "$ACCOUNT_ID"
                },
                "ArnLike": {
                    "aws:SourceArn": "arn:aws:bedrock:$REGION:$ACCOUNT_ID:*"
                }
            }
        }
    ]
}
EOF
echo "✓ Trust Policy 생성 완료"

# 2. IAM Role 생성
echo "[2/5] IAM Role 생성 중..."
aws iam create-role \
    --role-name $ROLE_NAME \
    --assume-role-policy-document file://bedrock-trust-policy.json \
    --description "Role for Amazon Bedrock model invocation logging"

if [ $? -eq 0 ]; then
    echo "✓ IAM Role 생성 완료"
else
    echo "⚠ IAM Role이 이미 존재하거나 생성 실패"
fi

# 3. CloudWatch Logs Permission Policy 생성 (cloudwatch-only 또는 both인 경우)
if [[ "$LOGGING_TYPE" == "cloudwatch-only" || "$LOGGING_TYPE" == "both" ]]; then
    echo "[3/5] CloudWatch Logs Permission Policy 생성 중..."
    cat > bedrock-cloudwatch-policy.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": "arn:aws:logs:$REGION:$ACCOUNT_ID:log-group:$LOG_GROUP_NAME:*"
        }
    ]
}
EOF
    echo "✓ CloudWatch Logs Policy 생성 완료"

    # 4. Permission Policy를 Role에 연결
    echo "[4/5] Permission Policy를 Role에 연결 중..."
    aws iam put-role-policy \
        --role-name $ROLE_NAME \
        --policy-name BedrockCloudWatchLogsPolicy \
        --policy-document file://bedrock-cloudwatch-policy.json

    if [ $? -eq 0 ]; then
        echo "✓ CloudWatch Logs Policy 연결 완료"
    else
        echo "✗ Policy 연결 실패"
    fi
else
    echo "[3/5] CloudWatch Logs 설정 건너뛰기 (S3-only 모드)"
    echo "[4/5] CloudWatch Logs 설정 건너뛰기 (S3-only 모드)"
fi

# 5. S3 Permission Policy 생성 (s3-only 또는 both인 경우)
if [[ "$LOGGING_TYPE" == "s3-only" || "$LOGGING_TYPE" == "both" ]]; then
    echo "[5/5] S3 Permission Policy 생성 중..."
    cat > bedrock-s3-policy.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:PutObject"
            ],
            "Resource": "arn:aws:s3:::$S3_BUCKET_NAME/*/AWSLogs/$ACCOUNT_ID/BedrockModelInvocationLogs/*"
        }
    ]
}
EOF

    aws iam put-role-policy \
        --role-name $ROLE_NAME \
        --policy-name BedrockS3LogsPolicy \
        --policy-document file://bedrock-s3-policy.json

    if [ $? -eq 0 ]; then
        echo "✓ S3 Policy 연결 완료"
    else
        echo "✗ S3 Policy 연결 실패"
    fi
else
    echo "[5/5] S3 설정 건너뛰기 (CloudWatch-only 모드)"
fi

# CloudWatch Log Group 생성 (cloudwatch-only 또는 both인 경우)
if [[ "$LOGGING_TYPE" == "cloudwatch-only" || "$LOGGING_TYPE" == "both" ]]; then
    echo ""
    echo "=== CloudWatch Log Group 생성 ==="
    aws logs create-log-group --log-group-name $LOG_GROUP_NAME --region $REGION 2>/dev/null
    if [ $? -eq 0 ]; then
        echo "✓ Log Group 생성 완료: $LOG_GROUP_NAME"
    else
        echo "⚠ Log Group이 이미 존재하거나 생성 불필요"
    fi
fi

# 생성된 Role ARN 출력
echo ""
echo "=== 생성 완료 ==="
ROLE_ARN="arn:aws:iam::$ACCOUNT_ID:role/$ROLE_NAME"
echo "Role ARN: $ROLE_ARN"
echo ""
echo "다음 명령어로 Bedrock 로깅을 활성화할 수 있습니다:"
echo ""

# 로깅 타입에 따라 다른 명령어 출력
case $LOGGING_TYPE in
    cloudwatch-only)
        # CloudWatch Logs만 사용하는 경우
        echo "aws bedrock put-model-invocation-logging-configuration \\"
        echo "    --region $REGION \\"
        echo "    --logging-config '{"
        echo "        \"cloudWatchConfig\": {"
        echo "            \"logGroupName\": \"$LOG_GROUP_NAME\","
        echo "            \"roleArn\": \"$ROLE_ARN\""
        echo "        },"
        echo "        \"textDataDeliveryEnabled\": true,"
        echo "        \"imageDataDeliveryEnabled\": true,"
        echo "        \"embeddingDataDeliveryEnabled\": true"
        echo "    }'"
        ;;
    s3-only)
        # S3만 사용하는 경우
        echo "aws bedrock put-model-invocation-logging-configuration \\"
        echo "    --region $REGION \\"
        echo "    --logging-config '{"
        echo "        \"s3Config\": {"
        echo "            \"bucketName\": \"$S3_BUCKET_NAME\""
        echo "        },"
        echo "        \"textDataDeliveryEnabled\": true,"
        echo "        \"imageDataDeliveryEnabled\": true,"
        echo "        \"embeddingDataDeliveryEnabled\": true"
        echo "    }'"
        ;;
    both)
        # S3와 CloudWatch Logs 둘 다 사용하는 경우
        echo "aws bedrock put-model-invocation-logging-configuration \\"
        echo "    --region $REGION \\"
        echo "    --logging-config '{"
        echo "        \"cloudWatchConfig\": {"
        echo "            \"logGroupName\": \"$LOG_GROUP_NAME\","
        echo "            \"roleArn\": \"$ROLE_ARN\""
        echo "        },"
        echo "        \"s3Config\": {"
        echo "            \"bucketName\": \"$S3_BUCKET_NAME\""
        echo "        },"
        echo "        \"textDataDeliveryEnabled\": true,"
        echo "        \"imageDataDeliveryEnabled\": true,"
        echo "        \"embeddingDataDeliveryEnabled\": true"
        echo "    }'"
        ;;
esac

echo ""
echo "임시 파일 정리 중..."
rm -f bedrock-trust-policy.json bedrock-cloudwatch-policy.json bedrock-s3-policy.json
echo "✓ 완료"
