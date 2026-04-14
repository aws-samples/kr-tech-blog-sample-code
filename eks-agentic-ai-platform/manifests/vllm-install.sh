#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(dirname "$0")"

# Add vLLM production stack Helm repository
helm repo add vllm https://vllm-project.github.io/production-stack
helm repo update

# Install vLLM in ai-inference namespace
helm install vllm vllm/vllm-stack \
  --namespace ai-inference \
  --create-namespace \
  --values "${SCRIPT_DIR}/vllm-values.yaml"

echo "vLLM installed in namespace ai-inference"
