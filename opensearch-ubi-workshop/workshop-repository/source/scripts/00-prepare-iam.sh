#!/usr/bin/env bash
# One-time IAM preparation for the advanced existing-domain CDK path.
# SHARED_OPENSEARCH_ROLE_NAME must identify a role already mapped to the
# required FGAC backend roles on the target domain.
set -euo pipefail

: "${SHARED_OPENSEARCH_ROLE_NAME:?Set the FGAC-mapped role name used by OSI and Lambda}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo "== ${SHARED_OPENSEARCH_ROLE_NAME} trust policy (osis + lambda) =="
CURRENT_POLICY=$(mktemp)
UPDATED_POLICY=$(mktemp)
trap 'rm -f "$CURRENT_POLICY" "$UPDATED_POLICY"' EXIT
aws iam get-role --role-name "$SHARED_OPENSEARCH_ROLE_NAME" \
  --query 'Role.AssumeRolePolicyDocument' --output json > "$CURRENT_POLICY"
python3 - "$CURRENT_POLICY" "$UPDATED_POLICY" <<'PY'
import json
import sys

source, destination = sys.argv[1:]
with open(source, encoding="utf-8") as file:
    policy = json.load(file)

statements = policy.setdefault("Statement", [])
if not isinstance(statements, list):
    statements = [statements]
    policy["Statement"] = statements

if not any(statement.get("Sid") == "AllowWorkshopLambdaAssumeRole" for statement in statements):
    statements.append({
        "Sid": "AllowWorkshopLambdaAssumeRole",
        "Effect": "Allow",
        "Principal": {"Service": "lambda.amazonaws.com"},
        "Action": "sts:AssumeRole",
    })

with open(destination, "w", encoding="utf-8") as file:
    json.dump(policy, file)
PY
aws iam update-assume-role-policy --role-name "$SHARED_OPENSEARCH_ROLE_NAME" \
  --policy-document "file://${UPDATED_POLICY}"

if [[ -n "${BEDROCK_CONNECTOR_ROLE_NAME:-}" ]]; then
  echo "== ${BEDROCK_CONNECTOR_ROLE_NAME} (optional ml-commons connector role) =="
  if ! aws iam get-role --role-name "$BEDROCK_CONNECTOR_ROLE_NAME" >/dev/null 2>&1; then
    aws iam create-role --role-name "$BEDROCK_CONNECTOR_ROLE_NAME" \
      --description "Connector role for OpenSearch ml-commons to invoke Bedrock models" \
      --assume-role-policy-document '{
        "Version": "2012-10-17",
        "Statement": [
          {"Effect": "Allow", "Principal": {"Service": "es.amazonaws.com"}, "Action": "sts:AssumeRole"},
          {"Effect": "Allow", "Principal": {"Service": "es.aws.internal"}, "Action": "sts:AssumeRole"}
        ]
      }' >/dev/null
  fi
  aws iam put-role-policy --role-name "$BEDROCK_CONNECTOR_ROLE_NAME" --policy-name BedrockInvokePolicy \
    --policy-document "{
      \"Version\": \"2012-10-17\",
      \"Statement\": [{
        \"Effect\": \"Allow\",
        \"Action\": [\"bedrock:InvokeModel\"],
        \"Resource\": [
          \"arn:aws:bedrock:*::foundation-model/*\",
          \"arn:aws:bedrock:*:${ACCOUNT_ID}:inference-profile/*\"
        ]
      }]
    }"
fi

echo "IAM preparation done."
