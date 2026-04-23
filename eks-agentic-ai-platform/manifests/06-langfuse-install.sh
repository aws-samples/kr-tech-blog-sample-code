#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(dirname "$0")"

# Add Langfuse Helm repository
helm repo add langfuse https://langfuse.github.io/langfuse-k8s
helm repo update

# Install Langfuse in observability namespace
helm install langfuse langfuse/langfuse \
  --namespace observability \
  --create-namespace \
  --values "${SCRIPT_DIR}/06-langfuse-values.yaml"

echo "Langfuse installed in namespace observability"
