#!/usr/bin/env bash
# Destructive cleanup for the advanced existing-domain CDK path.
set -euo pipefail

: "${OPENSEARCH_ENDPOINT:?Set the target OpenSearch endpoint host}"
: "${CONFIRM_DELETE:?Set CONFIRM_DELETE=DELETE_ECOM_UBI to continue}"
if [[ "$CONFIRM_DELETE" != "DELETE_ECOM_UBI" ]]; then
  echo "Refusing cleanup: CONFIRM_DELETE must equal DELETE_ECOM_UBI" >&2
  exit 2
fi

export AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-northeast-2}}"

echo "Deleting ecom_* and ubi_*_ecom sample indexes, ecom LTR models, and ecom_features"
python3 - <<'PY'
import os
import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth

host = os.environ["OPENSEARCH_ENDPOINT"].replace("https://", "").rstrip("/")
region = os.environ["AWS_REGION"]
auth = AWSV4SignerAuth(boto3.Session().get_credentials(), region, "es")
client = OpenSearch(
    hosts=[{"host": host, "port": 443}],
    http_auth=auth,
    use_ssl=True,
    verify_certs=True,
    connection_class=RequestsHttpConnection,
    timeout=30,
)

for index in [
    "ecom_products",
    "ubi_queries_ecom",
    "ubi_events_ecom",
    "ecom_judgments",
    "ecom_ltr_metrics",
]:
    try:
        client.indices.delete(index=index)
        print("deleted index", index)
    except Exception as error:
        print("skip", index, str(error)[:100])

try:
    response = client.transport.perform_request("GET", "/_ltr/ecom/_model?size=100")
    for hit in response.get("hits", {}).get("hits", []):
        name = hit.get("_source", {}).get("name", "")
        if name.startswith("ecom-ltr-xgb"):
            client.transport.perform_request("DELETE", f"/_ltr/ecom/_model/{name}")
            print("deleted model", name)
except Exception as error:
    print("model cleanup:", str(error)[:120])

try:
    client.transport.perform_request("DELETE", "/_ltr/ecom/_featureset/ecom_features")
    print("deleted featureset ecom_features")
except Exception as error:
    print("featureset cleanup:", str(error)[:100])
PY

if [[ -n "${SHARED_OPENSEARCH_ROLE_NAME:-}" && "${REVERT_SHARED_ROLE_TRUST:-false}" == "true" ]]; then
  echo "Removing the workshop Lambda trust statement from ${SHARED_OPENSEARCH_ROLE_NAME}"
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

statements = policy.get("Statement", [])
if not isinstance(statements, list):
    statements = [statements]
policy["Statement"] = [
    statement for statement in statements
    if statement.get("Sid") != "AllowWorkshopLambdaAssumeRole"
]

with open(destination, "w", encoding="utf-8") as file:
    json.dump(policy, file)
PY
  aws iam update-assume-role-policy --role-name "$SHARED_OPENSEARCH_ROLE_NAME" \
    --policy-document "file://${UPDATED_POLICY}"
fi

echo "cleanup done"
