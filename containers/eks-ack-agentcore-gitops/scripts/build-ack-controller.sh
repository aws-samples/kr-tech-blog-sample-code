#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/environment.sh
source_revision="$(jq -er '.ackControllerSourceRevision' config/versions.json)"
controller_version="$(jq -er '.ackControllerPatch' config/versions.json)"
sdk_version="$(jq -er '.ackControlSdk' config/versions.json)"
directory="$(mktemp -d .state/ack-build.XXXXXX)"
curl -fsSL "https://api.github.com/repos/aws-controllers-k8s/bedrockagentcorecontrol-controller/tarball/$source_revision" | tar -xz --strip-components=1 -C "$directory"
test "$(uv run --project agent python -c 'import sys,yaml; print(yaml.safe_load(open(sys.argv[1]))["version"])' "$directory/helm/Chart.yaml")" = "$(jq -r '.ackAgentCoreChart' config/versions.json)"
patch -d "$directory" -p1 < patches/ack-controller/endpoint-version.patch
uv run --project agent python patches/ack-controller/extend_gateway.py "$directory"
aws ecr-public get-login-password --region us-east-1 | docker login --username AWS --password-stdin public.ecr.aws
repository="$(aws ecr describe-repositories --repository-names eks-ack-agentcore --query 'repositories[0].repositoryUri' --output text)"
aws ecr get-login-password | docker login --username AWS --password-stdin "${repository%%/*}"
tag="ack-$controller_version-$(date -u +%Y%m%d%H%M%S)"
docker buildx build --platform linux/arm64 --provenance=false --sbom=false \
  --build-arg GOPROXY="${GOPROXY:-https://proxy.golang.org,direct}" \
  --build-arg ACK_CONTROL_SDK_VERSION="$sdk_version" \
  --build-arg ACK_CONTROLLER_VERSION="$controller_version" \
  --file patches/ack-controller/Dockerfile --tag "$repository:$tag" --push "$directory"
digest="$(aws ecr describe-images --repository-name eks-ack-agentcore --image-ids imageTag="$tag" --query 'imageDetails[0].imageDigest' --output text)"
printf '%s@%s\n' "$repository" "$digest" > .state/ack-image-uri
mkdir -p .state/ack-crds
for resource in agentruntimes agentruntimeendpoints gateways gatewaytargets; do
  cp "$directory/helm/crds/bedrockagentcorecontrol.services.k8s.aws_$resource.yaml" .state/ack-crds/
done
cp "$directory"/helm/crds/services.k8s.aws_*.yaml .state/ack-crds/
uv run --project agent python scripts/ack-assets.py create \
  --repository "$repository" --tag "$tag@$digest" --values .state/ack-image-values.json
printf 'Patched ACK image: %s@%s\n' "$repository" "$digest"
