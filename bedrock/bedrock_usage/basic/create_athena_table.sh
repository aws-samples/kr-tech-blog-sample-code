#!/bin/bash

# Athena 테이블 생성 및 쿼리 스크립트

set -e

echo "=========================================="
echo "Athena Table Creation for Bedrock Logs"
echo "=========================================="
echo ""

# 변수 설정
REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
BUCKET_NAME="bedrock-invocation-logs-${ACCOUNT_ID}"
DATABASE_NAME="bedrock_logs_db"
TABLE_NAME="model_invocation_logs"
ATHENA_OUTPUT_BUCKET="athena-query-results-${ACCOUNT_ID}"

echo "📋 Configuration:"
echo "  Database: $DATABASE_NAME"
echo "  Table: $TABLE_NAME"
echo "  S3 Bucket: s3://$BUCKET_NAME/bedrock-logs/"
echo "  Athena Output: s3://$ATHENA_OUTPUT_BUCKET/"
echo ""

# 1. Athena 결과 저장용 S3 버킷 생성
echo "1️⃣  Creating Athena output bucket..."
aws s3api create-bucket \
    --bucket "$ATHENA_OUTPUT_BUCKET" \
    --region "$REGION" \
    --create-bucket-configuration LocationConstraint="$REGION" 2>/dev/null || echo "  ℹ️  Bucket already exists"

echo "  ✅ Athena output bucket ready"
echo ""

# 2. Athena 데이터베이스 생성
echo "2️⃣  Creating Athena database..."

CREATE_DATABASE_QUERY="CREATE DATABASE IF NOT EXISTS $DATABASE_NAME"

QUERY_ID=$(aws athena start-query-execution \
    --query-string "$CREATE_DATABASE_QUERY" \
    --result-configuration "OutputLocation=s3://$ATHENA_OUTPUT_BUCKET/" \
    --region "$REGION" \
    --query 'QueryExecutionId' \
    --output text)

echo "  Query ID: $QUERY_ID"
sleep 3

# 쿼리 상태 확인
STATUS=$(aws athena get-query-execution \
    --query-execution-id "$QUERY_ID" \
    --region "$REGION" \
    --query 'QueryExecution.Status.State' \
    --output text)

echo "  Status: $STATUS"
echo "  ✅ Database created: $DATABASE_NAME"
echo ""

# 3. Athena 테이블 생성
echo "3️⃣  Creating Athena table for Bedrock logs..."

CREATE_TABLE_QUERY=$(cat <<EOF
CREATE EXTERNAL TABLE IF NOT EXISTS ${DATABASE_NAME}.${TABLE_NAME} (
  timestamp string,
  accountId string,
  identity struct<arn:string>,
  region string,
  requestId string,
  operation string,
  modelId string,
  input struct<
    inputContentType:string,
    inputTokenCount:int
  >,
  output struct<
    outputContentType:string,
    outputTokenCount:int
  >,
  requestMetadata struct<
    application_name:string,
    application_id:string,
    environment:string,
    team:string,
    cost_center:string,
    tenant_id:string,
    user_id:string,
    timestamp:string
  >,
  schemaType string,
  schemaVersion string
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
LOCATION 's3://${BUCKET_NAME}/bedrock-logs/'
EOF
)

QUERY_ID=$(aws athena start-query-execution \
    --query-string "$CREATE_TABLE_QUERY" \
    --query-execution-context Database="$DATABASE_NAME" \
    --result-configuration "OutputLocation=s3://$ATHENA_OUTPUT_BUCKET/" \
    --region "$REGION" \
    --query 'QueryExecutionId' \
    --output text)

echo "  Query ID: $QUERY_ID"
sleep 3

STATUS=$(aws athena get-query-execution \
    --query-execution-id "$QUERY_ID" \
    --region "$REGION" \
    --query 'QueryExecution.Status.State' \
    --output text)

echo "  Status: $STATUS"
echo "  ✅ Table created: ${DATABASE_NAME}.${TABLE_NAME}"
echo ""

# 4. 테이블 확인 쿼리
echo "4️⃣  Verifying table..."

VERIFY_QUERY="SHOW TABLES IN $DATABASE_NAME"

QUERY_ID=$(aws athena start-query-execution \
    --query-string "$VERIFY_QUERY" \
    --query-execution-context Database="$DATABASE_NAME" \
    --result-configuration "OutputLocation=s3://$ATHENA_OUTPUT_BUCKET/" \
    --region "$REGION" \
    --query 'QueryExecutionId' \
    --output text)

sleep 3

aws athena get-query-results \
    --query-execution-id "$QUERY_ID" \
    --region "$REGION"

echo ""
echo "=========================================="
echo "✅ Athena Setup Complete!"
echo "=========================================="
echo ""
echo "📊 Sample Queries:"
echo ""
echo "1. Count all logs:"
echo "   SELECT COUNT(*) FROM ${DATABASE_NAME}.${TABLE_NAME};"
echo ""
echo "2. Application-wise token usage:"
echo "   SELECT"
echo "     requestmetadata.application_name,"
echo "     SUM(input.inputtokencount) as total_input,"
echo "     SUM(output.outputtokencount) as total_output,"
echo "     COUNT(*) as requests"
echo "   FROM ${DATABASE_NAME}.${TABLE_NAME}"
echo "   GROUP BY requestmetadata.application_name"
echo "   ORDER BY total_input + total_output DESC;"
echo ""
echo "3. Tenant-wise usage:"
echo "   SELECT"
echo "     requestmetadata.tenant_id,"
echo "     SUM(input.inputtokencount + output.outputtokencount) as total_tokens"
echo "   FROM ${DATABASE_NAME}.${TABLE_NAME}"
echo "   WHERE requestmetadata.tenant_id IS NOT NULL"
echo "   GROUP BY requestmetadata.tenant_id;"
echo ""
echo "🔗 Run queries in Athena Console:"
echo "   https://console.aws.amazon.com/athena/home?region=$REGION#query"
echo ""
