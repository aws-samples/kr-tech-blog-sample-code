#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/deploy-foundation.sh
bash scripts/build-ack-controller.sh
bash scripts/install-platform.sh
bash scripts/build-agent.sh
printf 'Update gitops/environments/dev.yaml with .state/image-uri and .state/outputs.json, commit/push, then run scripts/configure-gitops.sh.\n'
