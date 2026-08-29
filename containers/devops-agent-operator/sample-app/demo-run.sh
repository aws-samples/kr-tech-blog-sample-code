#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ============================================================
# Configuration — 아래 값을 자신의 환경에 맞게 수정하세요
# ============================================================
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-<YOUR_AWS_ACCOUNT_ID>}"
AWS_REGION="${AWS_REGION:-<YOUR_AWS_REGION>}"
ECR_REPO="sample-app"
S3_BUCKET="${CODEBUILD_SOURCE_BUCKET:-<YOUR_CODEBUILD_SOURCE_BUCKET>}"
CODEBUILD_PROJECT="${CODEBUILD_PROJECT:-<YOUR_CODEBUILD_PROJECT>}"
S3_INCIDENTS_BUCKET="${S3_INCIDENTS_BUCKET:-<YOUR_INCIDENTS_BUCKET>}"
GITHUB_REPO="${GITHUB_REPO:-<YOUR_GITHUB_ORG>/<YOUR_REPO>}"
# ============================================================

usage() {
  echo "Usage: ./demo-run.sh [stable|buggy|status|cleanup]"
  echo ""
  echo "  stable  - Deploy stable version (normal operation)"
  echo "  buggy   - Introduce bug, build, and deploy (triggers incident)"
  echo "  status  - Check current pod and operator status"
  echo "  cleanup - Remove sample-app deployment"
  exit 1
}

wait_for_build() {
  local build_id=$1
  echo "    Waiting for build to complete..."
  while true; do
    STATUS=$(aws codebuild batch-get-builds --ids "$build_id" --region $AWS_REGION \
      --query "builds[0].buildStatus" --output text 2>/dev/null)
    if [ "$STATUS" = "SUCCEEDED" ]; then
      echo "    ✓ Build succeeded"
      return 0
    elif [ "$STATUS" = "FAILED" ] || [ "$STATUS" = "FAULT" ] || [ "$STATUS" = "STOPPED" ]; then
      echo "    ✗ Build failed: $STATUS"
      return 1
    fi
    sleep 10
    printf "."
  done
}

get_latest_image() {
  aws ecr describe-images --repository-name $ECR_REPO --region $AWS_REGION \
    --query "sort_by(imageDetails, &imagePushedAt)[-1].imageTags[0]" --output text
}

build_and_push() {
  echo "[2/4] Uploading source to S3..."
  rm -f /tmp/source.zip
  cd "$REPO_ROOT"
  zip -r /tmp/source.zip sample-app/ -x "sample-app/versions/*" -x "sample-app/DEMO.md" -x "sample-app/README.md" > /dev/null
  aws s3 cp /tmp/source.zip "s3://$S3_BUCKET/source.zip" --region $AWS_REGION > /dev/null

  echo "[3/4] Starting CodeBuild..."
  BUILD_ID=$(aws codebuild start-build --project-name $CODEBUILD_PROJECT --region $AWS_REGION \
    --query "build.id" --output text)
  echo "    Build ID: $BUILD_ID"
  wait_for_build "$BUILD_ID"
}

deploy() {
  local image_tag=$1
  local commit_sha=$2
  local full_image="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:${image_tag}"

  echo "[4/4] Deploying image: $full_image"
  cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sample-app
  namespace: default
  labels:
    app: sample-app
spec:
  replicas: 1
  selector:
    matchLabels:
      app: sample-app
  template:
    metadata:
      labels:
        app: sample-app
      annotations:
        app.kubernetes.io/source-repository: "https://github.com/${GITHUB_REPO}"
        app.kubernetes.io/source-commit: "${commit_sha}"
        github.com/repository: "${GITHUB_REPO}"
        github.com/commit: "${commit_sha}"
    spec:
      containers:
        - name: app
          image: ${full_image}
          resources:
            requests:
              cpu: 10m
              memory: 32Mi
            limits:
              cpu: 100m
              memory: 64Mi
EOF
  echo "    ✓ Deployment applied"
}

case "${1:-}" in
  stable)
    echo "=== Deploying STABLE version ==="
    echo ""
    echo "[1/4] Switching to stable code..."
    cp "$SCRIPT_DIR/versions/stable.py" "$SCRIPT_DIR/app.py"
    cd "$REPO_ROOT"
    git add sample-app/app.py
    git commit -m "revert: restore stable config with defaults" --allow-empty > /dev/null 2>&1 || true
    git push origin main > /dev/null 2>&1 || true
    COMMIT_SHA=$(git rev-parse HEAD)
    echo "    Commit: ${COMMIT_SHA:0:7}"

    build_and_push
    IMAGE_TAG=$(get_latest_image)
    deploy "$IMAGE_TAG" "$COMMIT_SHA"

    echo ""
    echo "=== Waiting for pod to be ready... ==="
    sleep 10
    kubectl get pods -l app=sample-app
    ;;

  buggy)
    echo "=== Deploying BUGGY version ==="
    echo ""
    echo "[1/4] Introducing bug..."
    cp "$SCRIPT_DIR/versions/buggy.py" "$SCRIPT_DIR/app.py"
    cd "$REPO_ROOT"
    git add sample-app/app.py
    git commit -m "refactor: require explicit APP_CONFIG, add database_url validation

- Remove default config fallback (strict mode)
- Add required field validation: app_name, port, database_url
- App now exits with error if config is missing or incomplete" > /dev/null 2>&1
    git push origin main > /dev/null 2>&1
    COMMIT_SHA=$(git rev-parse HEAD)
    echo "    Commit: ${COMMIT_SHA:0:7}"
    echo "    Change: removed default config, added database_url requirement"

    build_and_push
    IMAGE_TAG=$(get_latest_image)
    deploy "$IMAGE_TAG" "$COMMIT_SHA"

    echo ""
    echo "=== Pod will crash shortly — watch operator logs: ==="
    echo "kubectl logs -f deployment/devops-agent-operator -n devops-agent-operator-system"
    ;;

  status)
    echo "=== Current Status ==="
    echo ""
    echo "--- Pods ---"
    kubectl get pods -l app=sample-app -n default
    echo ""
    echo "--- Operator (last 5 lines) ---"
    kubectl logs deployment/devops-agent-operator -n devops-agent-operator-system --tail=5 2>/dev/null | grep -v "^$"
    echo ""
    echo "--- Latest S3 incidents ---"
    aws s3 ls "s3://${S3_INCIDENTS_BUCKET}/incidents/" --region $AWS_REGION 2>/dev/null | tail -5
    ;;

  cleanup)
    echo "=== Cleanup ==="
    kubectl delete deployment sample-app -n default --ignore-not-found
    echo "✓ Done"
    ;;

  *)
    usage
    ;;
esac
