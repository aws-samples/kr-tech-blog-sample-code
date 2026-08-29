#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Configuration
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-<YOUR_AWS_ACCOUNT_ID>}"
AWS_REGION="${AWS_REGION:-<YOUR_AWS_REGION>}"
ECR_REPO="sample-app"
COMMIT_SHA=$(git -C "$REPO_ROOT" rev-parse HEAD)
IMAGE_TAG=$(git -C "$REPO_ROOT" rev-parse --short HEAD)
FULL_IMAGE="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:${IMAGE_TAG}"

echo "=== Building sample-app in cluster (Kaniko) ==="
echo "Image: $FULL_IMAGE"
echo "Commit: $COMMIT_SHA"
echo ""

# 1. Create ECR repo if not exists
echo "[1/4] Ensuring ECR repository..."
aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$AWS_REGION" 2>/dev/null || \
  aws ecr create-repository --repository-name "$ECR_REPO" --region "$AWS_REGION" --output text >/dev/null

# 2. Create ConfigMap with build context (Dockerfile + source)
echo "[2/4] Creating build context..."
kubectl delete configmap sample-app-build-context --ignore-not-found -n default >/dev/null 2>&1
kubectl create configmap sample-app-build-context \
  --from-file=Dockerfile="$SCRIPT_DIR/Dockerfile" \
  --from-file=app.py="$SCRIPT_DIR/app.py" \
  -n default

# 3. Run Kaniko build pod
echo "[3/4] Running Kaniko build..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: kaniko-build
  namespace: default
spec:
  restartPolicy: Never
  serviceAccountName: default
  initContainers:
    - name: setup-context
      image: busybox
      command: ['sh', '-c', 'cp /build-context/* /workspace/']
      volumeMounts:
        - name: build-context
          mountPath: /build-context
        - name: workspace
          mountPath: /workspace
  containers:
    - name: kaniko
      image: gcr.io/kaniko-project/executor:latest
      args:
        - "--dockerfile=/workspace/Dockerfile"
        - "--context=/workspace"
        - "--destination=${FULL_IMAGE}"
      volumeMounts:
        - name: workspace
          mountPath: /workspace
      env:
        - name: AWS_SDK_LOAD_CONFIG
          value: "true"
        - name: AWS_REGION
          value: "${AWS_REGION}"
  volumes:
    - name: build-context
      configMap:
        name: sample-app-build-context
    - name: workspace
      emptyDir: {}
EOF

# Wait for build
echo "    Waiting for build to complete..."
kubectl wait --for=condition=Ready pod/kaniko-build --timeout=10s 2>/dev/null || true
kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/kaniko-build --timeout=300s 2>/dev/null || {
  echo "    Build logs:"
  kubectl logs kaniko-build -c kaniko 2>/dev/null | tail -10
  STATUS=$(kubectl get pod kaniko-build -o jsonpath='{.status.phase}')
  if [ "$STATUS" != "Succeeded" ]; then
    echo "    ERROR: Build failed (status: $STATUS)"
    kubectl delete pod kaniko-build --ignore-not-found >/dev/null 2>&1
    exit 1
  fi
}
echo "    ✓ Image built: $FULL_IMAGE"
kubectl delete pod kaniko-build --ignore-not-found >/dev/null 2>&1

# 4. Deploy
echo "[4/4] Deploying..."
sed -e "s|__COMMIT_SHA__|${COMMIT_SHA}|g" \
    -e "s|__IMAGE__|${FULL_IMAGE}|g" \
    "$SCRIPT_DIR/k8s-deployment.yaml.tpl" > "$SCRIPT_DIR/k8s-deployment.yaml"
kubectl apply -f "$SCRIPT_DIR/k8s-deployment.yaml"
kubectl rollout status deployment/sample-app --timeout=120s

echo ""
echo "=== Done ==="
echo "Commit: $COMMIT_SHA"
echo "Image: $FULL_IMAGE"
kubectl get pods -l app=sample-app
