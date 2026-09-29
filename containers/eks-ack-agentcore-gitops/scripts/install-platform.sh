#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
ack_image_values="${ACK_IMAGE_VALUES:-config/ack-image-values.yaml}"
if [[ -z "${ACK_IMAGE_VALUES:-}" && -f .state/ack-image-values.json ]]; then ack_image_values=.state/ack-image-values.json; fi
uv run --project agent python scripts/ack-assets.py verify --values "$ack_image_values"
source scripts/environment.sh
output() { jq -r ".EksAckAgentCore.$1" .state/outputs.json; }
version() { jq -r ".$1" config/versions.json; }
kube() { kubectl --context "$KUBE_CONTEXT" "$@"; }
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION" --alias "$KUBE_CONTEXT" --profile "$AWS_PROFILE" >/dev/null
helm upgrade --install aws-load-balancer-controller aws-load-balancer-controller \
  --repo https://aws.github.io/eks-charts --version "$(version loadBalancerControllerChart)" \
  --kube-context "$KUBE_CONTEXT" --namespace kube-system \
  --set clusterName="$CLUSTER_NAME" --set region="$AWS_REGION" --set vpcId="$(output VpcId)" \
  --set serviceAccount.name=aws-load-balancer-controller --wait --timeout 10m
helm upgrade --install argocd argo-cd --repo https://argoproj.github.io/argo-helm \
  --version "$(version argoCdChart)" --kube-context "$KUBE_CONTEXT" --namespace argocd --create-namespace \
  --values config/argocd-values.yaml --wait --timeout 10m
aws ecr-public get-login-password --region us-east-1 | helm registry login --username AWS --password-stdin public.ecr.aws
test -f .state/ack-crds/bedrockagentcorecontrol.services.k8s.aws_gateways.yaml
kube apply --server-side --field-manager=ack-http-schema --force-conflicts -f .state/ack-crds/
helm upgrade --install ack-agentcore oci://public.ecr.aws/aws-controllers-k8s/bedrockagentcorecontrol-chart \
  --version "$(version ackAgentCoreChart)" --kube-context "$KUBE_CONTEXT" --namespace agentcore --create-namespace --skip-crds \
  --values config/ack-values.yaml --values "$ack_image_values" --set aws.region="$AWS_REGION" --wait --timeout 10m
helm upgrade --install argo-rollouts argo-rollouts --repo https://argoproj.github.io/argo-helm \
  --version "$(version argoRolloutsChart)" --kube-context "$KUBE_CONTEXT" --namespace argo-rollouts --create-namespace \
  --set dashboard.enabled=false --wait --timeout 10m
if [[ ! -f .state/certificate-arn ]]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj '/CN=argocd.demo.internal' \
    -keyout .state/argocd.key -out .state/argocd.crt >/dev/null 2>&1
  chmod 600 .state/argocd.key
  aws acm import-certificate --certificate fileb://.state/argocd.crt --private-key fileb://.state/argocd.key \
    --tags Key=Project,Value=eks-ack-agentcore --query CertificateArn --output text > .state/certificate-arn
fi
uv run --project agent python scripts/render-ingress.py \
  --certificate-arn "$(cat .state/certificate-arn)" --admin-cidr "$(output AdminCidr)" | kube apply -f -
for attempt in $(seq 1 60); do
  hostname="$(kube get ingress argocd-admin -n argocd -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')"
  if [[ -n "$hostname" ]]; then break; fi
  sleep 10
done
test -n "$hostname"
printf '%s\n' "$hostname" > .state/argocd-hostname
openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj '/CN=argocd.demo.internal' \
  -addext "subjectAltName=DNS:$hostname" -keyout .state/argocd.key -out .state/argocd.crt >/dev/null 2>&1
chmod 600 .state/argocd.key
aws acm import-certificate --certificate-arn "$(cat .state/certificate-arn)" \
  --certificate fileb://.state/argocd.crt --private-key fileb://.state/argocd.key >/dev/null
printf 'Argo CD: https://%s\n' "$hostname"
