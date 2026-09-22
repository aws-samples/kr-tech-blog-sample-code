import json

import httpx
import pytest
from botocore.credentials import ReadOnlyCredentials

from rollout_probe import classify_phase, percentile, request_summary, send_request, summarize


def test_crossing_request_is_not_counted_as_baseline():
    assert classify_phase(8, 12, 10, 20) == "during_or_crossing"
    assert classify_phase(1, 9, 10, 20) == "before"
    assert classify_phase(21, 22, 10, 20) == "after"


def test_statistics_include_failures():
    result = request_summary([
        {"ok": True, "latency_seconds": 1, "http_status": 200, "release": "v5"},
        {"ok": False, "latency_seconds": 10, "http_status": 503},
    ])
    assert result["failed"] == 1
    assert result["error_rate"] == 0.5
    assert result["latency_seconds"]["p95"] == 10
    assert percentile([], 0.95) is None


@pytest.mark.parametrize("status", [200, 503])
def test_http_errors_are_not_retried(status):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"] == "same-session"
        return httpx.Response(status, json={"release": "v5", "response": "OK", "build_revision": "gateway-v5"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = send_request(client, ReadOnlyCredentials("testing", "testing", None), "us-east-1", "https://example.com", "same-session", "existing", 1, "v5", "v6")
    assert len(calls) == 1
    assert result["ok"] == (status == 200)
    assert result["http_status"] == status


def test_request_timeout_is_counted():
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = send_request(client, ReadOnlyCredentials("testing", "testing", None), "us-east-1", "https://example.com", "same-session", "existing", 1, "v5", "v6")
    assert not result["ok"]
    assert result["error_type"] == "ReadTimeout"


def test_failed_baseline_does_not_claim_rollout_was_tested(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"candidate_release": "v6"}))
    (tmp_path / "observations.jsonl").write_text(json.dumps({"epoch": 10, "runtime_status": "READY", "live_version": "5", "endpoint_status": "READY"}) + "\n")
    (tmp_path / "requests.jsonl").write_text(json.dumps({"ok": False, "lane": "existing", "session_id": "session", "started_epoch": 10, "finished_epoch": 20, "http_status": 424, "latency_seconds": 10}) + "\n")
    result = summarize(tmp_path)
    assert result["mode"] == "baseline_only"
    assert result["overall"]["failed"] == 1
    assert result["by_phase"]["during_or_crossing"]["requests"] == 0
    assert result["deployment_started_epoch"] is None


def test_partial_rollout_boundaries_are_rejected(tmp_path):
    for name in ["requests", "observations"]:
        (tmp_path / f"{name}.jsonl").write_text("")
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "deployment-start.json").write_text('{"epoch":10}')
    with pytest.raises(ValueError, match="both deployment boundary markers"):
        summarize(tmp_path)
