#!/usr/bin/env bash

NORI_SAMPLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$NORI_SAMPLE_ROOT/versions.env"

export NORI_SAMPLE_ROOT
export NORI_SOURCE_ROOT="$NORI_SAMPLE_ROOT/sources"
export NORI_BUILD_DIR="${NORI_BUILD_DIR:-$NORI_SAMPLE_ROOT/build}"
export NORI_BUILD_JOBS="${NORI_BUILD_JOBS:-4}"
export PYTHON_BIN="${PYTHON_BIN:-python3.12}"
export GRADLE_USER_HOME="${GRADLE_USER_HOME:-$NORI_SAMPLE_ROOT/.cache/gradle}"

if [[ "$NORI_BUILD_DIR" != /* ]] || [[ "$NORI_BUILD_DIR" == / ]] || [[ "$NORI_BUILD_DIR" == "$NORI_SAMPLE_ROOT" ]]; then
    echo 'NORI_BUILD_DIR must be an absolute output directory, not / or the sample root.' >&2
    return 1
fi
if ! [[ "$NORI_BUILD_JOBS" =~ ^[1-9][0-9]*$ ]]; then
    echo 'NORI_BUILD_JOBS must be a positive integer.' >&2
    return 1
fi
if [ -z "${JAVA_HOME:-}" ] && command -v brew >/dev/null 2>&1 && brew --prefix openjdk@21 >/dev/null 2>&1; then
    export JAVA_HOME="$(brew --prefix openjdk@21)/libexec/openjdk.jdk/Contents/Home"
fi
if [ -n "${JAVA_HOME:-}" ]; then
    export PATH="$JAVA_HOME/bin:$PATH"
    export JAVA21_HOME="$JAVA_HOME"
    export RUNTIME_JAVA_HOME="$JAVA_HOME"
fi
