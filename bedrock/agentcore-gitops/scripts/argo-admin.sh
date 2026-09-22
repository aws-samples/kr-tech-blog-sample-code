#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
printf 'URL: https://%s\nUsername: admin\n' "$(cat .state/argocd-hostname)"
printf 'Password: '
kubectl --context eks-ack-agentcore -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 --decode
printf '\n'
