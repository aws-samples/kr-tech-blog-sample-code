#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export AWS_PROFILE="${AWS_PROFILE:-default}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
unset AWS_BEARER_TOKEN_BEDROCK
configuration="$(uv run --project agent python -c 'import json,yaml; print(json.dumps(yaml.safe_load(open("gitops/environments/dev.yaml"))))')"
exec uv run --project agent python agent/gateway_probe.py \
  --gateway-name "$(jq -r '.gateway.name' <<< "$configuration")" \
  --target "$(jq -r '.gateway.targetName' <<< "$configuration")" \
  --runtime-id "$(jq -r '.endpoint.runtimeId' <<< "$configuration")" \
  --expect-release "$(jq -r '.runtime.release' <<< "$configuration")" \
  --expect-build "$(jq -r '.runtime.buildRevision' <<< "$configuration")" \
  --expect-image "$(jq -r '.runtime.imageUri' <<< "$configuration")" "$@"
