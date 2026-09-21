SHELL := /bin/bash
.DEFAULT_GOAL := help
.PHONY: help setup fetch doctor prepare mecab lucene plugin verify verify-http test all

help:
	@printf '%s\n' 'make setup       Download pinned sources and check local tools' 'make all         Download, build MeCab/Nori/plugin, and verify' 'make mecab       Build native MeCab and high/low dictionaries' 'make lucene      Build Lucene and replace Nori dictionary resources' 'make plugin      Package the isolated custom plugin' 'make verify      Run 108 tokenizer cases and validate the ZIP' 'make verify-http Verify an existing loopback OpenSearch node' 'make test        Run offline preparation regression tests'

fetch:
	bash scripts/fetch-sources.sh

doctor:
	bash scripts/doctor.sh

setup:
	$(MAKE) fetch
	$(MAKE) doctor

prepare mecab lucene plugin verify:
	bash scripts/build.sh $@

verify-http:
	bash scripts/build.sh verify-http

test:
	$${PYTHON_BIN:-python3.12} -m unittest discover -s tests -p 'test_*.py' -v

all:
	$(MAKE) setup
	bash scripts/build.sh all
