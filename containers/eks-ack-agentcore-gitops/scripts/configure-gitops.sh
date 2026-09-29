#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
repository="$(uv run --project agent python scripts/validate-gitops.py)"
source scripts/environment.sh
kube() { kubectl --context "$KUBE_CONTEXT" "$@"; }
if [[ ! -f .state/argocd-deploy-key ]]; then
  ssh-keygen -t ed25519 -N '' -C eks-ack-agentcore-argocd-readonly -f .state/argocd-deploy-key >/dev/null
  gh api "repos/$repository/keys" -f title=eks-ack-agentcore-argocd-readonly \
    -f key="$(cat .state/argocd-deploy-key.pub)" -F read_only=true --jq .id > .state/deploy-key-id
fi
chmod 600 .state/argocd-deploy-key
gh api "repos/$repository/keys" > .state/repository-keys.json
public_key="$(cut -d ' ' -f 1,2 .state/argocd-deploy-key.pub)"
jq -e --arg key "$public_key" 'any(.[]; .read_only == true and .key == $key)' .state/repository-keys.json >/dev/null || {
  printf 'The saved deploy key does not belong to the selected repository. Use a fresh project-local .state directory.\n' >&2
  exit 1
}
kube create secret generic agentcore-repository --namespace argocd \
  --from-literal=type=git --from-literal=url="ssh://git@github.com/$repository.git" \
  --from-file=sshPrivateKey=.state/argocd-deploy-key --dry-run=client -o yaml | kube apply -f -
kube label secret agentcore-repository -n argocd argocd.argoproj.io/secret-type=repository --overwrite
kube apply -f gitops/project.yaml
if [[ -n "${GITOPS_VALUES_FILE:-}" ]]; then
  printf 'Using explicit local Helm values for validation; this is not a Git-only release.\n' >&2
  uv run --project agent python scripts/render-application.py --values "$GITOPS_VALUES_FILE" | kube apply -f -
else
  kube apply -f gitops/application.yaml
fi
