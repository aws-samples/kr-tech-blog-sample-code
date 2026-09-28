#!/usr/bin/env bash
# Advanced existing-domain deployment: IAM prep -> build -> cdk deploy --all.
set -euo pipefail
cd "$(dirname "$0")"

: "${OPENSEARCH_ENDPOINT:?Set the target domain endpoint host}"
: "${OPENSEARCH_DOMAIN_ARN:?Set the target domain ARN}"
: "${SHARED_OPENSEARCH_ROLE_ARN:?Set the FGAC-mapped shared role ARN}"
: "${JUDGE_MODEL_ID:?Set the deployed ml-commons judge model ID}"

export SHARED_OPENSEARCH_ROLE_NAME="${SHARED_OPENSEARCH_ROLE_ARN##*/}"

bash scripts/00-prepare-iam.sh
bash scripts/build.sh

echo "== cdk deps =="
npm install --no-fund --no-audit --silent

echo "== cdk deploy =="
npx cdk deploy --all --require-approval never --outputs-file outputs.json \
  -c opensearchEndpoint="$OPENSEARCH_ENDPOINT" \
  -c opensearchDomainArn="$OPENSEARCH_DOMAIN_ARN" \
  -c sharedOpenSearchRoleArn="$SHARED_OPENSEARCH_ROLE_ARN" \
  -c judgeModelId="$JUDGE_MODEL_ID" \
  "$@"

echo
echo "== outputs =="
cat outputs.json
