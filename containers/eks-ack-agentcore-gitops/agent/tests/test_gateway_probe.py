import pytest

from gateway_probe import invocation_url, verify_response


def test_runtime_target_url():
    gateway = {"gatewayUrl": "https://sample-1234567890.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"}
    assert invocation_url(gateway, "agent", "us-east-1").endswith("/agent/invocations")


@pytest.mark.parametrize("url", ["http://example.com", "https://example.com", "https://test.gateway.bedrock-agentcore.us-west-2.amazonaws.com"])
def test_signed_request_rejects_unexpected_host(url):
    with pytest.raises(ValueError):
        invocation_url({"gatewayUrl": url}, "agent", "us-east-1")


def test_old_runtime_response_fails_gate():
    with pytest.raises(RuntimeError, match="Release mismatch"):
        verify_response({"release": "v2", "response": "ok"}, "v3", None)


def test_wrong_image_build_fails_gate():
    with pytest.raises(RuntimeError, match="Build mismatch"):
        verify_response({"release": "v3", "response": "ok", "build_revision": "old"}, "v3", "new")


def test_valid_gateway_response():
    verify_response({"release": "v3", "build_revision": "build-3", "response": "ready"}, "v3", "build-3")
