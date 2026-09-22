#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
expected="${1:-$(git rev-parse HEAD)}"
kubectl --context eks-ack-agentcore -n argocd annotate application devops-agent argocd.argoproj.io/refresh=hard --overwrite >/dev/null
for attempt in $(seq 1 90); do
  kubectl --context eks-ack-agentcore -n argocd get application devops-agent -o json > .state/application.json
  if jq -e --arg revision "$expected" '.status.sync.revision == $revision and .status.sync.status == "Synced" and .status.health.status == "Healthy" and .status.operationState.phase == "Succeeded" and .status.operationState.syncResult.revision == $revision' .state/application.json >/dev/null; then
    jq '{revision:.status.sync.revision,sync:.status.sync.status,health:.status.health.status}' .state/application.json
    exit 0
  fi
  if jq -e --arg revision "$expected" '.status.operationState.syncResult.revision == $revision and (.status.operationState.phase == "Failed" or .status.operationState.phase == "Error")' .state/application.json >/dev/null; then
    jq '.status.operationState | {phase,message,resources:.syncResult.resources}' .state/application.json
    exit 1
  fi
  if jq -e '.status.health.status == "Degraded"' .state/application.json >/dev/null; then
    kubectl --context eks-ack-agentcore -n agentcore get agentruntimes,agentruntimeendpoints -o yaml
    exit 1
  fi
  sleep 10
done
jq '.status' .state/application.json
exit 1
