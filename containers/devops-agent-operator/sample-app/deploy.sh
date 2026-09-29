#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Configuration
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-<YOUR_AWS_ACCOUNT_ID>}"
AWS_REGION="${AWS_REGION:-<YOUR_AWS_REGION>}"
ECR_REPO="sample-app"
IMAGE_TAG=$(git -C "$REPO_ROOT" rev-parse --short HEAD)
COMMIT_SHA=$(git -C "$REPO_ROOT" rev-parse HEAD)
FULL_IMAGE="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:${IMAGE_TAG}"

echo "=== Sample App Build & Deploy ==="
echo "Image: $FULL_IMAGE"
echo "Commit: $COMMIT_SHA"
echo ""

# 1. Create ECR repo if not exists
echo "[1/4] Ensuring ECR repository..."
aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$AWS_REGION" 2>/dev/null || \
  aws ecr create-repository --repository-name "$ECR_REPO" --region "$AWS_REGION" --output text

# 2. Build and push
echo "[2/4] Building and pushing Docker image..."
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
docker build -t "$FULL_IMAGE" "$SCRIPT_DIR"
docker push "$FULL_IMAGE"

# 3. Render k8s manifest
echo "[3/4] Rendering Kubernetes manifest..."
sed -e "s|__COMMIT_SHA__|${COMMIT_SHA}|g" \
    -e "s|__IMAGE__|${FULL_IMAGE}|g" \
    "$SCRIPT_DIR/k8s-deployment.yaml.tpl" > "$SCRIPT_DIR/k8s-deployment.yaml"

# 4. Deploy
echo "[4/4] Deploying to cluster..."
kubectl apply -f "$SCRIPT_DIR/k8s-deployment.yaml"
kubectl rollout status deployment/sample-app --timeout=60s

echo ""
echo "=== Deploy complete ==="
echo "Commit: $COMMIT_SHA"
echo "Image: $FULL_IMAGE"
kubectl get pods -l app=sample-app
