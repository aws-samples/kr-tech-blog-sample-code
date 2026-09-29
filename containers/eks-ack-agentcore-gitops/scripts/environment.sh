#!/usr/bin/env bash
set -euo pipefail
umask 077
export AWS_PROFILE="${AWS_PROFILE:-default}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_DEFAULT_REGION="$AWS_REGION"
unset AWS_BEARER_TOKEN_BEDROCK
identity="$(aws sts get-caller-identity --output json)"
export CDK_DEFAULT_ACCOUNT="$(jq -er '.Account' <<< "$identity")"
export CDK_DEFAULT_REGION="$AWS_REGION"
export ADMIN_PRINCIPAL_ARN="${ADMIN_PRINCIPAL_ARN:-$(jq -er '.Arn' <<< "$identity")}"
if [[ "$ADMIN_PRINCIPAL_ARN" == arn:*:sts::*:assumed-role/* ]]; then
  printf 'Set ADMIN_PRINCIPAL_ARN to the IAM role ARN, not the STS session ARN.\n' >&2
  exit 1
fi
export ADMIN_CIDR="${ADMIN_CIDR:-$(if [[ -f .state/admin-cidrs ]]; then cat .state/admin-cidrs; else curl -fsS https://checkip.amazonaws.com | tr -d '\n'; printf '/32'; fi)}"
export CLUSTER_NAME=eks-ack-agentcore
export KUBE_CONTEXT=eks-ack-agentcore
mkdir -p .state
chmod 700 .state
if [[ -f .state/cni-migrated ]]; then export CNI_BOOTSTRAP=false; fi
