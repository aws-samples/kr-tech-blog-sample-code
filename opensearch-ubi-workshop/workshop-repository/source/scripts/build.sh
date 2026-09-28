#!/usr/bin/env bash
# Build all Lambda bundles + the React frontend into .build/ and webapp-frontend/dist.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== [1/5] python deps layer =="
rm -rf .build/layer && mkdir -p .build/layer/python
python3 -m pip install -q -r lambda/layers/requirements.txt -t .build/layer/python --no-cache-dir

echo "== [2/5] webapp backend bundle =="
rm -rf .build/backend && mkdir -p .build/backend
python3 -m pip install -q -r lambda/webapp-backend/requirements.txt -t .build/backend --no-cache-dir
cp lambda/webapp-backend/main.py .build/backend/

echo "== [3/5] pipeline function bundles =="
for fn in setup_opensearch extract_ubi_data generate_judgments build_features evaluate_model; do
  rm -rf ".build/functions/$fn" && mkdir -p ".build/functions/$fn"
  cp "lambda/functions/$fn/$fn.py" ".build/functions/$fn/"
  cp lambda/shared/oscommon.py ".build/functions/$fn/"
done
cp data/products.json .build/functions/setup_opensearch/

echo "== [4/5] docker train-fn context =="
cp lambda/shared/oscommon.py lambda/functions/train_ltr_model/

echo "== [5/5] frontend build =="
(cd webapp-frontend && npm install --no-fund --no-audit --silent && npm run build)

echo "build complete."
