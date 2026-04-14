"""
End-to-end deployment verification for the Agentic AI Platform on EKS.

Usage:
    # Port-forward services first:
    kubectl port-forward svc/vllm 8000:8000 -n ai-inference &
    kubectl port-forward svc/bifrost 8080:8080 -n ai-inference &
    kubectl port-forward svc/langfuse-web 3000:3000 -n observability &

    # Run tests:
    pytest tests/integration/test_e2e_verification.py -v

Environment variables (optional overrides):
    VLLM_URL          default: http://localhost:8000
    BIFROST_URL       default: http://localhost:8080
    LANGFUSE_URL      default: http://localhost:3000
    BIFROST_API_KEY   default: test-1234
"""

import os
import json
import subprocess
import pytest
import requests

VLLM_URL = os.getenv("VLLM_URL", "http://localhost:8000")
BIFROST_URL = os.getenv("BIFROST_URL", "http://localhost:8080")
LANGFUSE_URL = os.getenv("LANGFUSE_URL", "http://localhost:3000")
BIFROST_API_KEY = os.getenv("BIFROST_API_KEY", "test-1234")

TIMEOUT = 60


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _kubectl_get_pods(namespace: str) -> list[dict]:
    """Get pod list from a namespace via kubectl."""
    result = subprocess.run(
        ["kubectl", "get", "po", "-n", namespace, "-o", "json"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        pytest.skip(f"kubectl failed for namespace {namespace}: {result.stderr}")
    data = json.loads(result.stdout)
    return data.get("items", [])


def _chat_completion(base_url: str, model: str, message: str,
                     headers: dict | None = None) -> dict:
    """Send a chat completion request and return the JSON response."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": message}],
        "max_tokens": 200,
    }
    resp = requests.post(
        f"{base_url}/v1/chat/completions",
        json=payload,
        headers=headers or {},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# 1. Pod health checks
# ---------------------------------------------------------------------------

class TestPodHealth:
    """Verify all expected pods are Running."""

    def test_ai_inference_pods_running(self):
        pods = _kubectl_get_pods("ai-inference")
        assert len(pods) > 0, "No pods found in ai-inference namespace"

        for pod in pods:
            name = pod["metadata"]["name"]
            phase = pod["status"]["phase"]
            assert phase == "Running", f"Pod {name} is {phase}, expected Running"

    def test_observability_pods_running(self):
        pods = _kubectl_get_pods("observability")
        assert len(pods) > 0, "No pods found in observability namespace"

        for pod in pods:
            name = pod["metadata"]["name"]
            phase = pod["status"]["phase"]
            # Completed pods (validators, etc.) are acceptable
            assert phase in ("Running", "Succeeded"), (
                f"Pod {name} is {phase}, expected Running or Succeeded"
            )

    def test_bifrost_replicas(self):
        pods = _kubectl_get_pods("ai-inference")
        bifrost_pods = [p for p in pods if "bifrost" in p["metadata"]["name"]]
        running = [p for p in bifrost_pods if p["status"]["phase"] == "Running"]
        assert len(running) >= 3, (
            f"Expected >= 3 Bifrost replicas Running, got {len(running)}"
        )

    def test_vllm_running(self):
        pods = _kubectl_get_pods("ai-inference")
        vllm_pods = [p for p in pods if "vllm" in p["metadata"]["name"]]
        running = [p for p in vllm_pods if p["status"]["phase"] == "Running"]
        assert len(running) >= 1, "No vLLM pod Running"


# ---------------------------------------------------------------------------
# 2. vLLM inference
# ---------------------------------------------------------------------------

class TestVLLMInference:
    """Verify vLLM serves Qwen3-8B correctly."""

    def test_vllm_health(self):
        resp = requests.get(f"{VLLM_URL}/health", timeout=10)
        assert resp.status_code == 200

    def test_vllm_models_endpoint(self):
        resp = requests.get(f"{VLLM_URL}/v1/models", timeout=10)
        assert resp.status_code == 200
        models = resp.json()
        model_ids = [m["id"] for m in models["data"]]
        assert "qwen3-8b" in model_ids, f"Expected qwen3-8b in {model_ids}"

    def test_vllm_chat_completion(self):
        data = _chat_completion(VLLM_URL, "qwen3-8b", "Say hello in Korean.")
        assert "choices" in data
        assert len(data["choices"]) > 0
        content = data["choices"][0]["message"]["content"]
        assert len(content) > 0, "Empty response from vLLM"

    def test_vllm_returns_usage(self):
        data = _chat_completion(VLLM_URL, "qwen3-8b", "What is 2+2?")
        assert "usage" in data
        usage = data["usage"]
        assert usage.get("prompt_tokens", 0) > 0
        assert usage.get("completion_tokens", 0) > 0


# ---------------------------------------------------------------------------
# 3. Bifrost gateway
# ---------------------------------------------------------------------------

class TestBifrostGateway:
    """Verify Bifrost proxies requests correctly."""

    def test_bifrost_chat_completion(self):
        headers = {"Authorization": f"Bearer {BIFROST_API_KEY}"}
        data = _chat_completion(
            BIFROST_URL, "qwen3-8b",
            "S3 버킷 생성 방법을 간단히 알려주세요.",
            headers=headers,
        )
        assert "choices" in data
        content = data["choices"][0]["message"]["content"]
        assert len(content) > 0, "Empty response from Bifrost"


# ---------------------------------------------------------------------------
# 4. Langfuse dashboard
# ---------------------------------------------------------------------------

class TestLangfuse:
    """Verify Langfuse web UI is accessible."""

    def test_langfuse_web_reachable(self):
        resp = requests.get(LANGFUSE_URL, timeout=10, allow_redirects=True)
        assert resp.status_code == 200, (
            f"Langfuse returned {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# 5. Demo scenario — three query types
# ---------------------------------------------------------------------------

DEMO_QUERIES = [
    ("S3 버킷 생성 방법", "simple"),
    ("EKS 클러스터에서 OOM 에러 발생 시 트러블슈팅", "complex"),
    ("AWS 청구서 분석", "document"),
]


class TestDemoQueries:
    """Run the three canonical demo queries through vLLM and verify responses."""

    @pytest.mark.parametrize("query,expected_type", DEMO_QUERIES)
    def test_query_produces_response(self, query, expected_type):
        data = _chat_completion(VLLM_URL, "qwen3-8b", query)
        assert "choices" in data
        content = data["choices"][0]["message"]["content"]
        assert len(content) > 10, (
            f"Response too short for '{query}': {content!r}"
        )

    @pytest.mark.parametrize("query,expected_type", DEMO_QUERIES)
    def test_query_returns_usage_tokens(self, query, expected_type):
        data = _chat_completion(VLLM_URL, "qwen3-8b", query)
        usage = data.get("usage", {})
        assert usage.get("prompt_tokens", 0) > 0
        assert usage.get("completion_tokens", 0) > 0
        total = usage.get("total_tokens", 0)
        assert total == usage["prompt_tokens"] + usage["completion_tokens"]
