#!/bin/bash

# 설정 변수
S3_BUCKET_NAME="my-bedrock-logs-bucket"  # 원하는 버킷 이름으로 변경
REGION="us-east-1"  # 원하는 리전으로 변경
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
KEY_PREFIX="bedrock-logs"

echo "=== Amazon Bedrock용 S3 버킷 설정 시작 ==="
echo "Bucket: $S3_BUCKET_NAME"
echo "Region: $REGION"
echo "Account ID: $ACCOUNT_ID"
echo ""

# 1. S3 버킷 생성
echo "[1/4] S3 버킷 생성 중..."
if [ "$REGION" == "us-east-1" ]; then
    aws s3api create-bucket \
        --bucket $S3_BUCKET_NAME \
        --region $REGION 2>/dev/null
else
    aws s3api create-bucket \
        --bucket $S3_BUCKET_NAME \
        --region $REGION \
        --create-bucket-configuration LocationConstraint=$REGION 2>/dev/null
fi

if [ $? -eq 0 ]; then
    echo "✓ S3 버킷 생성 완료"
else
    echo "⚠ S3 버킷이 이미 존재하거나 생성 실패"
fi

# 2. 퍼블릭 액세스 차단 설정
echo "[2/4] 퍼블릭 액세스 차단 설정 중..."
aws s3api put-public-access-block \
    --bucket $S3_BUCKET_NAME \
    --public-access-block-configuration \
        "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

if [ $? -eq 0 ]; then
    echo "✓ 퍼블릭 액세스 차단 완료"
fi

# 3. Bucket ACL 비활성화 (Object Ownership 설정)
echo "[3/4] Bucket ACL 비활성화 중..."
aws s3api put-bucket-ownership-controls \
    --bucket $S3_BUCKET_NAME \
    --ownership-controls Rules=[{ObjectOwnership=BucketOwnerEnforced}]

if [ $? -eq 0 ]; then
    echo "✓ Bucket ACL 비활성화 완료"
fi

# 4. Bucket Policy 생성 및 적용
echo "[4/4] Bucket Policy 적용 중..."
cat > s3-bucket-policy.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AmazonBedrockLogsWrite",
            "Effect": "Allow",
            "Principal": {
                "Service": "bedrock.amazonaws.com"
            },
            "Action": "s3:PutObject",
            "Resource": "arn:aws:s3:::$S3_BUCKET_NAME/$KEY_PREFIX/AWSLogs/$ACCOUNT_ID/BedrockModelInvocationLogs/*",
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

aws s3api put-bucket-policy \
    --bucket $S3_BUCKET_NAME \
    --policy file://s3-bucket-policy.json

if [ $? -eq 0 ]; then
    echo "✓ Bucket Policy 적용 완료"
else
    echo "✗ Bucket Policy 적용 실패"
fi

echo ""
echo "=== S3 버킷 설정 완료 ==="
echo "Bucket Name: $S3_BUCKET_NAME"
echo "Key Prefix: $KEY_PREFIX"
echo ""
echo "Bedrock 로깅 설정에서 다음 정보를 사용하세요:"
echo "  - bucketName: $S3_BUCKET_NAME"
echo "  - keyPrefix: $KEY_PREFIX"
echo ""

# 임시 파일 정리
rm -f s3-bucket-policy.json
echo "✓ 임시 파일 정리 완료"
