from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from main import Invocation, app, deployment_info, invoke


def test_ping_contract():
    with TestClient(app) as client:
        assert client.get("/ping").status_code == 200


@pytest.mark.parametrize("prompt", ["", "x" * 8001])
def test_input_limits(prompt):
    with pytest.raises(ValidationError):
        Invocation(prompt=prompt)


def test_unexpected_input_is_rejected():
    with pytest.raises(ValidationError):
        Invocation(prompt="hello", command="delete")


def test_release_metadata(monkeypatch):
    monkeypatch.setenv("RELEASE_VERSION", "v2")
    assert deployment_info()["release"] == "v2"


def test_sonnet_does_not_send_temperature():
    with patch("main.BedrockModel") as model, patch("main.Agent") as agent:
        agent.return_value = Mock(return_value="ok")
        response = invoke({"prompt": "hello"})
        assert response["response"] == "ok"
        assert model.call_args.kwargs["max_tokens"] == 512
        assert "temperature" not in model.call_args.kwargs
        assert model.call_args.kwargs["model_id"] == "global.anthropic.claude-sonnet-5"
