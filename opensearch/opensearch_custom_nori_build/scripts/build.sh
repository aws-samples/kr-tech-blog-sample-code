#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
PHASE="${1:-all}"
case "$PHASE" in prepare|mecab|mecab-engine|mecab-dictionary|verify-mecab|lucene|plugin|verify|all) ;; *) echo 'Unknown phase. Run make help.' >&2; exit 2 ;; esac
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

logged() {
    local log="$1"
    shift
    printf '  Log: %s\n' "$log"
    if "$@" > "$log" 2>&1; then
        return 0
    else
        local status=$?
        printf 'Build step failed (exit %s). Last log lines:\n' "$status" >&2
        tail -n 30 "$log" >&2
        return "$status"
    fi
}

prepare() {
    printf '\n[3] Prepare high/low MeCab-Ko dictionary sources\n'
    "$PYTHON_BIN" "$NORI_SAMPLE_ROOT/scripts/prepare_dictionary.py" "$NORI_BUILD_DIR"
}

mecab-engine() {
    printf '\n[4] Build MeCab-Ko engine from source: configure, make, make install\n'
    logged "$NORI_BUILD_DIR/mecab-engine.log" "$PYTHON_BIN" "$NORI_SAMPLE_ROOT/scripts/build_native.py"
}

mecab-dictionary() {
    prepare
    printf '\n[5] Compile native high/low dictionaries with the locally built MeCab\n'
    if [ ! -f "$NORI_BUILD_DIR/native-build.json" ] || [ -e "$NORI_BUILD_DIR/native-build-pending.json" ]; then
        echo 'Complete make mecab-engine before compiling the native dictionaries.' >&2
        exit 1
    fi
    for variant in high low; do
        local destination="$NORI_BUILD_DIR/native-$variant"
        mkdir -p "$destination"
        logged "$NORI_BUILD_DIR/mecab-$variant.log" "$NORI_BUILD_DIR/toolchain/libexec/mecab/mecab-dict-index" \
            -d "$NORI_BUILD_DIR/dictionary-$variant" -o "$destination" -f UTF-8 -t UTF-8
        cp "$NORI_BUILD_DIR/dictionary-$variant/dicrc" "$destination/dicrc"
        printf '노을빛무선청소기에서 먼지를 제거한다\n구름결캠핑의자를 구매했다\n' | \
            "$NORI_BUILD_DIR/toolchain/bin/mecab" -r "$NORI_BUILD_DIR/toolchain/etc/mecabrc" -d "$destination" > "$NORI_BUILD_DIR/native-$variant.txt"
    done
}

verify-mecab() {
    printf '\n[6] Verify native tools, binary dictionaries, costs, POS, and compounds\n'
    "$PYTHON_BIN" "$NORI_SAMPLE_ROOT/tests/verify_native.py" "$NORI_BUILD_DIR"
}

mecab() {
    prepare
    mecab-engine
    mecab-dictionary
    verify-mecab
    "$PYTHON_BIN" "$NORI_SAMPLE_ROOT/scripts/build_summary.py" "$NORI_BUILD_DIR" mecab
}

lucene() {
    prepare
    printf '\n[7] Build Lucene and generate Nori resources from the same dictionary sources\n'
    logged "$NORI_BUILD_DIR/lucene-build.log" run_gradle -p "$NORI_SOURCE_ROOT/lucene" -Dversion.release="$LUCENE_VERSION" \
        :lucene:core:jar :lucene:analysis:common:jar :lucene:analysis:nori:jar
    local core="$NORI_SOURCE_ROOT/lucene/lucene/core/build/libs/lucene-core-$LUCENE_VERSION.jar"
    local common="$NORI_SOURCE_ROOT/lucene/lucene/analysis/common/build/libs/lucene-analysis-common-$LUCENE_VERSION.jar"
    local nori="$NORI_SOURCE_ROOT/lucene/lucene/analysis/nori/build/libs/lucene-analysis-nori-$LUCENE_VERSION.jar"
    for variant in high low; do
        local resources="$NORI_BUILD_DIR/nori-resources-$variant"
        mkdir -p "$resources"
        logged "$NORI_BUILD_DIR/nori-dictionary-$variant.log" java -Xmx2g -cp "$core:$common:$nori" \
            org.apache.lucene.analysis.ko.dict.DictionaryBuilder "$NORI_BUILD_DIR/dictionary-$variant" "$resources" UTF-8 false
        cp "$nori" "$NORI_BUILD_DIR/lucene-analysis-nori-$variant.jar.pending"
        jar --update --file "$NORI_BUILD_DIR/lucene-analysis-nori-$variant.jar.pending" -C "$resources" .
        mv "$NORI_BUILD_DIR/lucene-analysis-nori-$variant.jar.pending" "$NORI_BUILD_DIR/lucene-analysis-nori-$variant.jar"
    done
}

plugin() {
    printf '\n[8] Package the isolated Nori plugin and verify same-JVM coexistence\n'
    if [ ! -f "$NORI_BUILD_DIR/lucene-analysis-nori-low.jar" ]; then
        echo 'Run make lucene before make plugin.' >&2
        exit 1
    fi
    logged "$NORI_BUILD_DIR/plugin-build.log" run_gradle -p "$NORI_SAMPLE_ROOT/plugin" \
        -PnoriJar="$NORI_BUILD_DIR/lucene-analysis-nori-low.jar" -PoutputDir="$NORI_BUILD_DIR/plugin" assemble verifyCoexistence
}

verify() {
    printf '\n[9] Verify 108 tokenizer cases and the plugin ZIP\n'
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

if [ "$PHASE" = all ]; then
    mecab
    lucene
    plugin
    verify
    "$PYTHON_BIN" "$NORI_SAMPLE_ROOT/scripts/build_summary.py" "$NORI_BUILD_DIR" all
else
    "$PHASE"
fi
printf '\nBuild outputs: %s\n' "$NORI_BUILD_DIR"
