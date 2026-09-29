#!/usr/bin/env bash
set -euo pipefail
set +x
cd "$(dirname "$0")/.."
export AWS_PROFILE="${AWS_PROFILE:-default}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_PAGER=""
unset AWS_BEARER_TOKEN_BEDROCK
exec uv run --project agent python scripts/watch-gateway-curl.py "$@"
