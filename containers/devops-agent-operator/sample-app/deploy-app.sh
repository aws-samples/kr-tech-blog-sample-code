#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMMIT_SHA=$(git -C "$REPO_ROOT" rev-parse HEAD)

# Configuration
GITHUB_REPO="${GITHUB_REPO:-<YOUR_GITHUB_ORG>/<YOUR_REPO>}"

echo "=== Sample App Deploy ==="
echo "Commit: $COMMIT_SHA"
echo ""

# 1. Create/update ConfigMap with app code
echo "[1/2] Updating app code ConfigMap..."
kubectl delete configmap sample-app-code -n default --ignore-not-found >/dev/null 2>&1
kubectl create configmap sample-app-code \
  --from-file=app.py="$SCRIPT_DIR/app.py" \
  -n default

# 2. Deploy
echo "[2/2] Deploying..."
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
        app.kubernetes.io/source-commit: "${COMMIT_SHA}"
        github.com/repository: "${GITHUB_REPO}"
        github.com/commit: "${COMMIT_SHA}"
    spec:
      containers:
        - name: app
          image: python:3.12-alpine
          command: ["python", "/app/app.py"]
          volumeMounts:
            - name: app-code
              mountPath: /app
          resources:
            requests:
              cpu: 10m
              memory: 32Mi
            limits:
              cpu: 100m
              memory: 64Mi
      volumes:
        - name: app-code
          configMap:
            name: sample-app-code
EOF

kubectl rollout status deployment/sample-app --timeout=120s

echo ""
echo "=== Deploy complete (commit: ${COMMIT_SHA:0:7}) ==="
kubectl get pods -l app=sample-app
