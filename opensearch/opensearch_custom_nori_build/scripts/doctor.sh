#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

for tool in git curl tar make clang clang++ automake autoconf java javac jar "$PYTHON_BIN"; do
    command -v "$tool" >/dev/null || { printf 'Missing tool: %s\n' "$tool" >&2; exit 1; }
done
if [[ "$(uname -s)" == Darwin ]]; then
    xcode-select -p >/dev/null
    command -v glibtool >/dev/null || { echo 'Install Homebrew libtool.' >&2; exit 1; }
else
    command -v libtoolize >/dev/null || { echo 'Install GNU libtool.' >&2; exit 1; }
fi
[[ "$(javac -version 2>&1)" == 'javac 21.'* ]] || { echo 'Set JAVA_HOME to JDK 21.' >&2; exit 1; }
"$PYTHON_BIN" - <<'PY'
import os
import re
import sys
from pathlib import Path

if sys.version_info[:2] != (3, 12):
    raise RuntimeError("Use Python 3.12")
root = Path(os.environ["NORI_SAMPLE_ROOT"])
pinned = dict(line.split("=", 1) for line in (root / "versions.env").read_text().splitlines() if line)
dependency_file = root / "sources/OpenSearch/gradle/libs.versions.toml"
match = re.search(r'^lucene\s*=\s*"([^"]+)"', dependency_file.read_text(), re.MULTILINE)
if match is None or match.group(1) != pinned["LUCENE_VERSION"]:
    raise ValueError("OpenSearch source and selected Lucene versions do not match")
for filename in ("char.def", "unk.def", "matrix.def", "left-id.def", "right-id.def"):
    assert (root / "sources" / f"mecab-ko-dic-{pinned['MECAB_DIC_VERSION']}" / filename).stat().st_size > 0
print("Python 3.12 and OpenSearch/Lucene source compatibility: PASS")
PY
printf 'Host: %s\nJava: %s\nOutput: %s\n' "$(uname -sm)" "$(javac -version 2>&1)" "$NORI_BUILD_DIR"
