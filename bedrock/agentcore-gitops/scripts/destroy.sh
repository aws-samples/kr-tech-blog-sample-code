#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "${CONFIRM_DESTROY:-}" != eks-ack-agentcore ]]; then
  printf 'Set CONFIRM_DESTROY=eks-ack-agentcore to delete this demo. ECR images are retained.\n' >&2
  exit 1
fi
source scripts/environment.sh
kube() { kubectl --context "$KUBE_CONTEXT" "$@"; }
archive_directory="$(mktemp -d .state/destroyed.XXXXXX)"
chmod 700 "$archive_directory"
aws cloudformation describe-stacks --stack-name EksAckAgentCore > "$archive_directory/stack.json"
jq -e '.Stacks[0].Tags | any(.Key == "Project" and .Value == "eks-ack-agentcore")' "$archive_directory/stack.json" >/dev/null
aws eks describe-cluster --name "$CLUSTER_NAME" > "$archive_directory/cluster.json"
jq -e '.cluster.tags.Project == "eks-ack-agentcore" and .cluster.tags["aws:cloudformation:stack-name"] == "EksAckAgentCore"' "$archive_directory/cluster.json" >/dev/null
for resource in analysisruns gatewaytargets gateways agentruntimeendpoints agentruntimes; do
  kube get "$resource" -n agentcore -o json > "$archive_directory/$resource.json"
  jq -e 'all(.items[]; (.metadata.annotations["argocd.argoproj.io/tracking-id"] // "") | startswith("devops-agent:"))' "$archive_directory/$resource.json" >/dev/null || {
    printf 'Refusing deletion: %s includes resources not owned by devops-agent.\n' "$resource" >&2
    exit 1
  }
done
kube delete application devops-agent -n argocd --ignore-not-found
for resource in analysisruns gatewaytargets gateways agentruntimeendpoints agentruntimes; do
  if [[ "$resource" == agentruntimes ]]; then
    while IFS=$'\t' read -r runtime_id endpoint_name; do
      for attempt in $(seq 1 60); do
        aws bedrock-agentcore-control list-agent-runtime-endpoints --agent-runtime-id "$runtime_id" > "$archive_directory/endpoints-$runtime_id.json"
        if jq -e --arg name "$endpoint_name" 'all(.runtimeEndpoints[]; .name != $name)' "$archive_directory/endpoints-$runtime_id.json" >/dev/null; then break; fi
        if [[ "$attempt" == 60 ]]; then
          printf 'Endpoint %s is still deleting; leaving the controller running.\n' "$endpoint_name" >&2
          exit 1
        fi
        sleep 10
      done
    done < <(jq -r '.items[] | [.spec.agentRuntimeID,.spec.name] | @tsv' "$archive_directory/agentruntimeendpoints.json")
  fi
  while IFS= read -r name; do
    kube delete "$resource" "$name" -n agentcore --ignore-not-found --wait=true --timeout=10m
  done < <(jq -r '.items[].metadata.name' "$archive_directory/$resource.json")
done
kube delete ingress argocd-admin -n argocd --ignore-not-found --wait=true --timeout=10m
helm uninstall ack-agentcore --kube-context "$KUBE_CONTEXT" -n agentcore --wait
helm uninstall argocd --kube-context "$KUBE_CONTEXT" -n argocd --wait
helm uninstall argo-rollouts --kube-context "$KUBE_CONTEXT" -n argo-rollouts --wait
helm uninstall aws-load-balancer-controller --kube-context "$KUBE_CONTEXT" -n kube-system --wait
if [[ -f .state/certificate-arn ]]; then
  aws acm delete-certificate --certificate-arn "$(cat .state/certificate-arn)"
fi
CNI_BOOTSTRAP=false npx cdk destroy --force
kubectl config delete-context "$KUBE_CONTEXT"
for filename in outputs.json cni-migrated certificate-arn argocd-hostname argocd.key argocd.crt application.json; do
  if [[ -f ".state/$filename" ]]; then mv ".state/$filename" "$archive_directory/"; fi
done
printf 'Foundation deleted. Verify residual logs, workload identities, ECR images, and GitHub deploy key before declaring cleanup complete.\n'
printf 'Deleted-environment state archived at %s. ECR and the read-only Git deploy key are retained for reuse.\n' "$archive_directory"
