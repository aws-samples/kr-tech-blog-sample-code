#!/usr/bin/env bash

bootstrap() {
    local install_deps="${1:-false}"
    local host="$(uname -s)"
    local candidate
    if [[ "$install_deps" == true ]]; then
        if [[ "$host" != Darwin ]]; then
            echo '--install-deps supports macOS Homebrew only. Install the Linux prerequisites in README.md first.' >&2
            return 1
        fi
        command -v brew >/dev/null || { echo 'Install Homebrew first: https://brew.sh' >&2; return 1; }
        xcode-select -p >/dev/null 2>&1 || { echo 'Run xcode-select --install, complete installation, then retry.' >&2; return 1; }
        local missing=()
        for formula in openjdk@21 python@3.12 autoconf automake libtool; do
            if ! brew list --versions "$formula" >/dev/null 2>&1; then
                missing+=("$formula")
            fi
        done
        if [ "${#missing[@]}" -gt 0 ]; then
            HOMEBREW_NO_AUTO_UPDATE=1 brew install "${missing[@]}"
        else
            echo 'Homebrew build dependencies are already installed.'
        fi
    fi

    if [ -n "${NORI_JAVA_HOME:-}" ]; then
        export JAVA_HOME="$NORI_JAVA_HOME"
    elif [ -n "${JAVA_HOME:-}" ] && [[ "$("$JAVA_HOME/bin/javac" -version 2>/dev/null || true)" == 'javac 21.'* ]]; then
        :
    elif command -v brew >/dev/null 2>&1 && candidate="$(brew --prefix openjdk@21 2>/dev/null)" \
            && [ -x "$candidate/libexec/openjdk.jdk/Contents/Home/bin/javac" ]; then
        export JAVA_HOME="$candidate/libexec/openjdk.jdk/Contents/Home"
    elif [[ "$host" == Darwin ]] && candidate="$(/usr/libexec/java_home -v 21 2>/dev/null)"; then
        export JAVA_HOME="$candidate"
    elif [[ "$(javac -version 2>/dev/null || true)" == 'javac 21.'* ]]; then
        if [[ "$host" == Linux ]] && command -v readlink >/dev/null 2>&1; then
            export JAVA_HOME="$(dirname "$(dirname "$(readlink -f "$(command -v javac)")")")"
        fi
    else
        echo 'JDK 21 is required. Use --install-deps on macOS or set NORI_JAVA_HOME.' >&2
        return 1
    fi
    if [ -n "${JAVA_HOME:-}" ]; then
        export PATH="$JAVA_HOME/bin:$PATH"
    fi
    [[ "$(javac -version 2>/dev/null || true)" == 'javac 21.'* ]] || { echo 'Selected JDK must be version 21.' >&2; return 1; }

    if [ -n "${PYTHON_BIN:-}" ]; then
        :
    elif command -v python3.12 >/dev/null 2>&1; then
        export PYTHON_BIN="$(command -v python3.12)"
    elif command -v brew >/dev/null 2>&1 && candidate="$(brew --prefix python@3.12 2>/dev/null)"; then
        export PYTHON_BIN="$candidate/bin/python3.12"
    else
        echo 'Python 3.12 is required. Use --install-deps on macOS or set PYTHON_BIN.' >&2
        return 1
    fi
    "$PYTHON_BIN" -c 'import sys; assert sys.version_info[:2] == (3, 12), "Python 3.12 required"'
    for tool in git curl tar make clang clang++ automake autoconf jar; do
        command -v "$tool" >/dev/null || { printf 'Missing build tool: %s. See README.md or use --install-deps.\n' "$tool" >&2; return 1; }
    done
    if [[ "$host" == Darwin ]]; then
        xcode-select -p >/dev/null
        command -v glibtool >/dev/null || { echo 'Install Homebrew libtool.' >&2; return 1; }
    else
        command -v libtoolize >/dev/null || { echo 'Install GNU libtool.' >&2; return 1; }
    fi
    printf 'Selected JDK: %s\nSelected Python: %s\n' "$(javac -version 2>&1)" "$PYTHON_BIN"
}
