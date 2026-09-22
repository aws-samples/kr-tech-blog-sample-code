#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../../.."
drawio="${DRAWIO_BIN:-/Applications/draw.io.app/Contents/MacOS/draw.io}"
python3 docs/aws-tech-blog/tools/build_assets.py
temporary_directory="$(mktemp -d)"
trap 'rm -rf "$temporary_directory"' EXIT
for diagram in architecture deployment-pipeline; do
  source="docs/aws-tech-blog/figures/$diagram.drawio"
  "$drawio" --export --format png --scale 1.5 --border 22 --embed-diagram --output "$temporary_directory/$diagram.png" "$source"
  test -s "$temporary_directory/$diagram.png"
  "$drawio" --export --format svg --border 22 --embed-diagram --output "$temporary_directory/$diagram.svg" "$source"
  test -s "$temporary_directory/$diagram.svg"
  mv "$temporary_directory/$diagram.png" "docs/aws-tech-blog/figures/$diagram.png"
  mv "$temporary_directory/$diagram.svg" "docs/aws-tech-blog/figures/$diagram.svg"
done
