#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DEPS=false
TARGET=all
for argument in "$@"; do
    case "$argument" in
        --install-deps) INSTALL_DEPS=true ;;
        --mecab-only) TARGET=mecab ;;
        --help|-h)
            printf '%s\n' 'Usage: bash build-all.sh [--install-deps] [--mecab-only]' \
                '  --install-deps  Install missing build tools with Homebrew on macOS.' \
                '  --mecab-only    Stop after building and verifying MeCab-Ko and its dictionaries.' \
                'Default: prerequisites, source download, MeCab build, dictionary compilation,' \
                'native verification, Lucene/Nori build, plugin ZIP, and final verification.'
            exit 0 ;;
        *) printf 'Unknown argument: %s\n' "$argument" >&2; exit 2 ;;
    esac
done
source "$ROOT/scripts/bootstrap.sh"
bootstrap "$INSTALL_DEPS"
source "$ROOT/scripts/env.sh"
mkdir -p "$NORI_BUILD_DIR"
printf '\n[1] Download and verify pinned public sources\n'
bash "$ROOT/scripts/fetch-sources.sh"
printf '\n[2] Check toolchain and OpenSearch/Lucene compatibility\n'
bash "$ROOT/scripts/doctor.sh"
bash "$ROOT/scripts/build.sh" "$TARGET"
