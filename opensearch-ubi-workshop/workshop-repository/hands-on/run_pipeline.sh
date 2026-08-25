#!/usr/bin/env bash
# Start the LTR ML pipeline (Step Functions) and wait for completion.
# Usage: scripts/run_pipeline.sh ['{"top_n_queries": 60, "max_queries": 40}']
set -euo pipefail

REGION=${AWS_REGION:-ap-northeast-2}
SM_ARN=$(aws stepfunctions list-state-machines --region "$REGION" \
  --query "stateMachines[?name=='ubi-workshop-ltr-pipeline'].stateMachineArn" --output text)
[[ -z "$SM_ARN" ]] && { echo "state machine not found — deploy first"; exit 1; }

NAME="run-$(date +%Y%m%d-%H%M%S)"
INPUT=${1:-'{}'}
EXEC_ARN=$(aws stepfunctions start-execution --region "$REGION" \
  --state-machine-arn "$SM_ARN" --name "$NAME" --input "$INPUT" \
  --query executionArn --output text)
echo "started: $EXEC_ARN"

while true; do
  STATUS=$(aws stepfunctions describe-execution --region "$REGION" \
    --execution-arn "$EXEC_ARN" --query status --output text)
  printf '%s %s\n' "$(date +%T)" "$STATUS"
  [[ "$STATUS" != "RUNNING" ]] && break
  sleep 15
done

echo "== output =="
aws stepfunctions describe-execution --region "$REGION" --execution-arn "$EXEC_ARN" \
  --query output --output text | python3 -m json.tool || true
[[ "$STATUS" == "SUCCEEDED" ]]
