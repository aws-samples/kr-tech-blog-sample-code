"""Shared test fixtures for the Agentic AI Platform test suite."""

import os
import pytest
import yaml


# --- Configuration Fixtures ---

@pytest.fixture
def bifrost_endpoint():
    """Bifrost AI Gateway endpoint URL."""
    return os.getenv(
        "BIFROST_ENDPOINT",
        "http://bifrost.ai-gateway.svc.cluster.local:8080/v1",
    )


@pytest.fixture
def vllm_endpoint():
    """vLLM inference server endpoint URL."""
    return os.getenv(
        "VLLM_ENDPOINT",
        "http://vllm.ai-inference.svc.cluster.local:8000/v1",
    )


@pytest.fixture
def langfuse_endpoint():
    """Langfuse observability platform endpoint URL."""
    return os.getenv(
        "LANGFUSE_ENDPOINT",
        "http://langfuse.ai-observability.svc.cluster.local",
    )


# --- Model / Routing Fixtures ---

@pytest.fixture
def model_mapping():
    """Classification-to-model mapping used by the Orchestrator Agent."""
    return {
        "simple": "qwen3-8b",
        "complex": "claude-3-sonnet",
        "document": "gpt-4o",
    }


@pytest.fixture
def valid_query_types():
    """Set of valid query classification types."""
    return {"simple", "complex", "document"}


@pytest.fixture
def agent_routing():
    """Classification-to-agent routing rules."""
    return {
        "simple": "rag_agent",
        "complex": "rag_agent",
        "document": "document_agent",
    }


# --- YAML Loading Helpers ---

@pytest.fixture
def load_yaml():
    """Helper to load a YAML manifest file from the manifests/ directory."""
    def _load(filename):
        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "manifests", filename
        )
        with open(path) as f:
            return yaml.safe_load(f)
    return _load


# --- Sample Test Queries ---

@pytest.fixture
def sample_queries():
    """Three canonical test queries used for end-to-end verification."""
    return [
        {"query": "S3 버킷 생성 방법", "expected_type": "simple"},
        {
            "query": "EKS 클러스터에서 OOM 에러 발생 시 트러블슈팅",
            "expected_type": "complex",
        },
        {"query": "AWS 청구서 분석", "expected_type": "document"},
    ]


# --- Evaluation Fixtures ---

@pytest.fixture
def evaluation_score_bounds():
    """Bounds for evaluation sub-scores and total."""
    return {
        "accuracy": (0, 4),
        "completeness": (0, 3),
        "friendliness": (0, 3),
        "total": (0, 10),
    }
