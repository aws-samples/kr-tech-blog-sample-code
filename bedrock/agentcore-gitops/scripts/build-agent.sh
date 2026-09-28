#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/environment.sh
tag="${1:-v1-$(date -u +%Y%m%d%H%M%S)}"
repository="$(aws ecr describe-repositories --repository-names eks-ack-agentcore --query 'repositories[0].repositoryUri' --output text)"
registry="${repository%%/*}"
uv sync --project agent --frozen
uv run --directory agent pytest
uv export --project agent --no-dev --no-emit-project --frozen -o agent/requirements.lock >/dev/null
aws ecr get-login-password | docker login --username AWS --password-stdin "$registry"
docker buildx build --platform linux/arm64 --provenance=false --sbom=false \
  --build-arg BUILD_REVISION="${2:-$tag}" \
  --tag "$repository:$tag" --push agent
digest="$(aws ecr describe-images --repository-name eks-ack-agentcore \
  --image-ids imageTag="$tag" --query 'imageDetails[0].imageDigest' --output text)"
printf '%s@%s\n' "$repository" "$digest" > .state/image-uri
printf 'Image: %s@%s\n' "$repository" "$digest"
