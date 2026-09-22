#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/environment.sh
runtime_id="${1:?Supply Runtime ID}"
expected_version="${2:?Supply the expected numeric runtime version}"
endpoint="${3:-live}"
for attempt in $(seq 1 90); do
  aws bedrock-agentcore-control get-agent-runtime-endpoint --agent-runtime-id "$runtime_id" \
    --endpoint-name "$endpoint" > .state/endpoint.json
  if jq -e --arg expected "$expected_version" '.status == "READY" and .liveVersion == $expected' .state/endpoint.json >/dev/null; then
    jq '{name,status,liveVersion}' .state/endpoint.json
    exit 0
  fi
  sleep 10
done
cat .state/endpoint.json
exit 1
