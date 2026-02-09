#!/bin/bash

# CloudWatch Logs 확인 스크립트
echo "=========================================="
echo "Checking Bedrock Invocation Logs"
echo "=========================================="
echo ""

echo "1️⃣  Checking log streams..."
aws logs describe-log-streams \
  --log-group-name "/aws/bedrock/modelinvocations" \
  --order-by LastEventTime \
  --descending \
  --max-items 1 \
  --region us-east-1

echo ""
echo "2️⃣  Running CloudWatch Logs Insights query..."

QUERY_ID=$(aws logs start-query \
  --log-group-name "/aws/bedrock/modelinvocations" \
  --start-time $(date -u -v-1H +%s) \
  --end-time $(date -u +%s) \
  --query-string 'fields @timestamp, requestMetadata.application_name as App, requestMetadata.tenant_id as Tenant, input.inputTokenCount as Input, output.outputTokenCount as Output | sort @timestamp desc | limit 20' \
  --region us-east-1 \
  --query 'queryId' \
  --output text)

echo "Query ID: $QUERY_ID"
echo "Waiting 5 seconds for query to complete..."
sleep 5

echo ""
echo "3️⃣  Query Results:"
aws logs get-query-results \
  --query-id "$QUERY_ID" \
  --region us-east-1

echo ""
echo "=========================================="
echo "✅ Log check complete"
echo "=========================================="
echo ""
echo "📊 Next: View detailed analytics in CloudWatch Logs Insights"
echo "URL: https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#logsV2:logs-insights"
