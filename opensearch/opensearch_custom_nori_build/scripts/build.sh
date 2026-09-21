#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
PHASE="${1:-all}"
case "$PHASE" in prepare|mecab|lucene|plugin|verify|verify-http|all) ;; *) echo 'Unknown phase. Run make help.' >&2; exit 2 ;; esac
mkdir -p "$NORI_BUILD_DIR"
bash "$NORI_SAMPLE_ROOT/scripts/doctor.sh"
"$PYTHON_BIN" - <<'PY'
import os
import sys
from pathlib import Path

root = Path(os.environ["NORI_SAMPLE_ROOT"])
sys.path.insert(0, str(root / "scripts"))
from fetch_sources import checksum, verify_checkout, versions
pinned = versions()
verify_checkout(root / "sources/OpenSearch", "https://github.com/opensearch-project/OpenSearch.git", pinned["OPENSEARCH_COMMIT"])
verify_checkout(root / "sources/lucene", "https://github.com/apache/lucene.git", pinned["LUCENE_COMMIT"])
for name, expected in ((f"mecab-{pinned['MECAB_VERSION']}", pinned["MECAB_SHA256"]),
                       (f"mecab-ko-dic-{pinned['MECAB_DIC_VERSION']}", pinned["MECAB_DIC_SHA256"])):
    archive = root / ".cache/downloads" / f"{name}.tar.gz"
    if archive.is_symlink() or checksum(archive) != expected:
        raise ValueError(f"Archive checksum mismatch: {archive}")
PY

run_gradle() {
    "$NORI_SOURCE_ROOT/lucene/gradlew" --no-daemon --no-scan --console=plain \
        --max-workers="$NORI_BUILD_JOBS" "$@"
}

prepare() {
    "$PYTHON_BIN" "$NORI_SAMPLE_ROOT/scripts/prepare_dictionary.py" "$NORI_BUILD_DIR"
}

mecab() {
    prepare
    if [ ! -x "$NORI_BUILD_DIR/toolchain/bin/mecab" ]; then
        mkdir -p "$NORI_BUILD_DIR/engine"
        tar -xzf "$NORI_SAMPLE_ROOT/.cache/downloads/mecab-$MECAB_VERSION.tar.gz" -C "$NORI_BUILD_DIR/engine"
        (
            cd "$NORI_BUILD_DIR/engine/mecab-$MECAB_VERSION"
            cp "$(automake --print-libdir)/config.guess" "$(automake --print-libdir)/config.sub" .
            ./configure --prefix="$NORI_BUILD_DIR/toolchain" --with-charset=utf8 --enable-utf8-only \
                CC=clang CXX=clang++ CXXFLAGS='-O2 -std=c++11'
            make -j"$NORI_BUILD_JOBS" CXXFLAGS='-O2 -std=c++11'
            make install
        ) > "$NORI_BUILD_DIR/mecab-engine.log" 2>&1
    fi
    for variant in high low; do
        local destination="$NORI_BUILD_DIR/native-$variant"
        mkdir -p "$destination"
        "$NORI_BUILD_DIR/toolchain/libexec/mecab/mecab-dict-index" -d "$NORI_BUILD_DIR/dictionary-$variant" \
            -o "$destination" -f UTF-8 -t UTF-8 > "$NORI_BUILD_DIR/mecab-$variant.log" 2>&1
        cp "$NORI_BUILD_DIR/dictionary-$variant/dicrc" "$destination/dicrc"
        printf '노을빛무선청소기에서 먼지를 제거한다\n구름결캠핑의자를 구매했다\n' | \
            "$NORI_BUILD_DIR/toolchain/bin/mecab" -r "$NORI_BUILD_DIR/toolchain/etc/mecabrc" -d "$destination" > "$NORI_BUILD_DIR/native-$variant.txt"
    done
}

lucene() {
    prepare
    run_gradle -p "$NORI_SOURCE_ROOT/lucene" -Dversion.release="$LUCENE_VERSION" \
        :lucene:core:jar :lucene:analysis:common:jar :lucene:analysis:nori:jar > "$NORI_BUILD_DIR/lucene-build.log" 2>&1
    local core="$NORI_SOURCE_ROOT/lucene/lucene/core/build/libs/lucene-core-$LUCENE_VERSION.jar"
    local common="$NORI_SOURCE_ROOT/lucene/lucene/analysis/common/build/libs/lucene-analysis-common-$LUCENE_VERSION.jar"
    local nori="$NORI_SOURCE_ROOT/lucene/lucene/analysis/nori/build/libs/lucene-analysis-nori-$LUCENE_VERSION.jar"
    for variant in high low; do
        local resources="$NORI_BUILD_DIR/nori-resources-$variant"
        mkdir -p "$resources"
        java -Xmx2g -cp "$core:$common:$nori" org.apache.lucene.analysis.ko.dict.DictionaryBuilder \
            "$NORI_BUILD_DIR/dictionary-$variant" "$resources" UTF-8 false > "$NORI_BUILD_DIR/nori-dictionary-$variant.log" 2>&1
        cp "$nori" "$NORI_BUILD_DIR/lucene-analysis-nori-$variant.jar.pending"
        jar --update --file "$NORI_BUILD_DIR/lucene-analysis-nori-$variant.jar.pending" -C "$resources" .
        mv "$NORI_BUILD_DIR/lucene-analysis-nori-$variant.jar.pending" "$NORI_BUILD_DIR/lucene-analysis-nori-$variant.jar"
    done
}

plugin() {
    if [ ! -f "$NORI_BUILD_DIR/lucene-analysis-nori-low.jar" ]; then
        echo 'Run make lucene before make plugin.' >&2
        exit 1
    fi
    run_gradle -p "$NORI_SAMPLE_ROOT/plugin" -PnoriJar="$NORI_BUILD_DIR/lucene-analysis-nori-low.jar" \
        -PoutputDir="$NORI_BUILD_DIR/plugin" assemble verifyCoexistence > "$NORI_BUILD_DIR/plugin-build.log" 2>&1
}

verify() {
    local core="$NORI_SOURCE_ROOT/lucene/lucene/core/build/libs/lucene-core-$LUCENE_VERSION.jar"
    local common="$NORI_SOURCE_ROOT/lucene/lucene/analysis/common/build/libs/lucene-analysis-common-$LUCENE_VERSION.jar"
    local stock="$NORI_SOURCE_ROOT/lucene/lucene/analysis/nori/build/libs/lucene-analysis-nori-$LUCENE_VERSION.jar"
    java -cp "$core:$common:$stock" "$NORI_SAMPLE_ROOT/tests/NoriCompare.java" baseline > "$NORI_BUILD_DIR/baseline.jsonl"
    for variant in high low; do
        java -cp "$core:$common:$NORI_BUILD_DIR/lucene-analysis-nori-$variant.jar" "$NORI_SAMPLE_ROOT/tests/NoriCompare.java" "$variant" > "$NORI_BUILD_DIR/$variant.jsonl"
    done
    java -cp "$core:$common:$stock" "$NORI_SAMPLE_ROOT/tests/NoriCompare.java" user "$NORI_SAMPLE_ROOT/dictionaries/user_dictionary.txt" > "$NORI_BUILD_DIR/user.jsonl"
    "$PYTHON_BIN" "$NORI_SAMPLE_ROOT/tests/verify_artifacts.py" "$NORI_BUILD_DIR"
}

verify-http() {
    "$PYTHON_BIN" "$NORI_SAMPLE_ROOT/tests/verify_http.py" "$NORI_BUILD_DIR" --endpoint "${NORI_TEST_ENDPOINT:-http://127.0.0.1:19235}"
}

if [ "$PHASE" = all ]; then
    mecab
    lucene
    plugin
    verify
else
    "$PHASE"
fi
printf '\nBuild outputs: %s\n' "$NORI_BUILD_DIR"
