SHELL := /bin/bash
.DEFAULT_GOAL := help
.PHONY: help setup fetch doctor prepare mecab mecab-engine mecab-dictionary verify-mecab lucene plugin verify test all

help:
	@printf '%s\n' 'bash build-all.sh --install-deps  Prepare macOS tools and build everything, including MeCab' 'make all              Download, build MeCab/Nori/plugin, and verify' 'make mecab            Download, build and verify MeCab-Ko engine and dictionaries only' 'make mecab-engine     Rebuild MeCab-Ko from source (configure/make/install)' 'make mecab-dictionary Compile high/low CSVs with the built mecab-dict-index' 'make verify-mecab     Verify native binaries and eight actual morphology cases' 'make setup            Download pinned sources and check local tools' 'make lucene           Build Lucene and replace Nori dictionary resources' 'make plugin           Package the isolated custom plugin' 'make verify           Run 108 tokenizer cases and validate the ZIP' 'make test             Run offline regression tests' 'AWS comparison        Follow SERVICE_COMPARISON.md with two existing domains'

fetch:
	bash scripts/fetch-sources.sh

doctor:
	bash scripts/doctor.sh

setup:
	$(MAKE) fetch
	$(MAKE) doctor

prepare mecab-engine mecab-dictionary verify-mecab lucene plugin verify:
	bash scripts/build.sh $@

mecab:
	bash build-all.sh --mecab-only

test:
	$${PYTHON_BIN:-python3.12} -m unittest discover -s tests -p 'test_*.py' -v

all:
	bash build-all.sh
