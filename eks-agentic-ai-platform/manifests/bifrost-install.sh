#!/usr/bin/env bash
set -euo pipefail

# Add Bifrost Helm repository
helm repo add bifrost https://maximhq.github.io/bifrost/helm-charts
helm repo update

# Install Bifrost AI Gateway
helm install bifrost bifrost/bifrost \
  --namespace ai-inference \
  --create-namespace \
  --values "$(dirname "$0")/bifrost-values.yaml"

echo "Bifrost AI Gateway installed in namespace ai-inference"
