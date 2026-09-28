#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/environment.sh
if aws eks describe-cluster --name "$CLUSTER_NAME" > .state/cluster-before-deploy.json 2>.state/cluster-before-deploy.error; then
  test "$(jq -r '.cluster.tags.Project' .state/cluster-before-deploy.json)" = eks-ack-agentcore
elif [[ "$(cat .state/cluster-before-deploy.error)" == *ResourceNotFoundException* ]]; then
  export CNI_BOOTSTRAP=true
else
  cat .state/cluster-before-deploy.error >&2
  exit 1
fi
npm ci
npm run check
npm test
npx cdk synth --strict --quiet
npx cdk diff --no-change-set
npx cdk deploy --import-existing-resources --require-approval never --outputs-file .state/outputs.json
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION" --alias "$KUBE_CONTEXT" --profile "$AWS_PROFILE"
kubectl --context "$KUBE_CONTEXT" wait nodes --all --for=condition=Ready --timeout=10m
kubectl --context "$KUBE_CONTEXT" rollout status daemonset/eks-pod-identity-agent -n kube-system --timeout=5m
export CNI_BOOTSTRAP=false
if [[ -f .state/admin-cidrs ]]; then export ADMIN_CIDR="$(cat .state/admin-cidrs)"; fi
npx cdk diff --no-change-set
npx cdk deploy --require-approval never --outputs-file .state/outputs.json
touch .state/cni-migrated
