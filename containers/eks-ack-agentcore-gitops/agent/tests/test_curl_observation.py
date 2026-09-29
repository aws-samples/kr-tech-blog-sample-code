import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import ssl
import subprocess
import threading

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("curl_observation", ROOT / "scripts/watch-gateway-curl.py")
WATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WATCH)
URL = "https://example-gateway.gateway.bedrock-agentcore.us-east-1.amazonaws.com"
CREDENTIALS = {"AccessKeyId": "testing-access", "SecretAccessKey": "testing-secret", "SessionToken": "testing-token"}


def agent_response(release="v1", build="build-v1"):
    return {"response": "OK", "release": release, "build_revision": build}


def test_gateway_url_matches_selected_region():
    assert WATCH.gateway_url(URL + "/", "us-east-1", "agent") == URL + "/agent/invocations"


@pytest.mark.parametrize("value", [
    "http://example-gateway.gateway.bedrock-agentcore.us-east-1.amazonaws.com",
    "https://example.com", URL + ".example.com", URL + ":443", URL + "/agent/invocations",
    URL + "?key=value", URL + "#fragment", URL.replace("https://", "https://user@"),
    URL.replace("us-east-1", "us-west-2"),
])
def test_untrusted_urls_rejected_before_credential_lookup(value, monkeypatch):
    monkeypatch.setattr(WATCH, "aws_json", lambda *arguments: pytest.fail("credentials must not be fetched"))
    with pytest.raises(SystemExit):
        WATCH.parse_args(["--gateway-url", value])


@pytest.mark.parametrize("arguments", [
    ["--count", "0"], ["--count", "301"], ["--interval", "0"], ["--interval", "nan"],
    ["--timeout", "121"], ["--duration", "601"], ["--target", "../agent"], ["--region", "invalid"],
])
def test_observation_limits_are_enforced(arguments):
    with pytest.raises(SystemExit):
        WATCH.parse_args(arguments)


def test_credentials_only_reach_curl_stdin(monkeypatch):
    observed = {}

    def execute(command, **options):
        observed.update(command=command, **options)
        return subprocess.CompletedProcess(command, 0, json.dumps(agent_response()) + "\n200", "")

    monkeypatch.setattr(WATCH.subprocess, "run", execute)
    result = WATCH.curl_request(URL + "/agent/invocations", "us-east-1", "unique-session", CREDENTIALS, 15)
    assert result["ok"]
    assert observed["command"][:4] == ["curl", "-q", "--config", "-"]
    assert "aws:amz:us-east-1:bedrock-agentcore" in observed["command"]
    assert "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: unique-session" in observed["command"]
    assert "--location" not in observed["command"]
    assert observed["command"][observed["command"].index("--retry") + 1] == "0"
    assert observed["command"][observed["command"].index("--proto") + 1] == "=https"
    for secret in CREDENTIALS.values():
        assert secret in observed["input"]
        assert secret not in json.dumps(observed["command"])
        assert secret not in json.dumps(result)


def test_optional_session_token_and_escaped_credentials():
    config = WATCH.credential_config({"AccessKeyId": "testing", "SecretAccessKey": 'quote"slash\\value'})
    assert config == 'user = "testing:quote\\"slash\\\\value"\n'
    assert "X-Amz-Security-Token" not in config
    with pytest.raises(ValueError, match="incomplete"):
        WATCH.credential_config({"AccessKeyId": "testing", "SecretAccessKey": ""})


@pytest.mark.parametrize("body", [json.dumps(agent_response()), json.dumps(json.dumps(agent_response()))])
def test_normal_and_encoded_json_responses(body, monkeypatch):
    monkeypatch.setattr(WATCH.subprocess, "run", lambda command, **options: subprocess.CompletedProcess(command, 0, body + "\n200", ""))
    assert WATCH.curl_request(URL, "us-east-1", "session", CREDENTIALS, 10)["ok"]


@pytest.mark.parametrize("body,returncode,status,error", [
    ('{"message":"unavailable"}', 22, "503", "http_error"),
    ("", 28, "000", "curl_transport_error"),
    ("not JSON", 0, "200", "invalid_json_response"),
    ('{"release":"v1","build_revision":"build","response":""}', 0, "200", "missing_release_metadata_or_model_response"),
    ("[]", 0, "200", "missing_release_metadata_or_model_response"),
])
def test_error_responses_are_recorded_without_body_or_stderr(body, returncode, status, error, monkeypatch):
    monkeypatch.setattr(WATCH.subprocess, "run", lambda command, **options: subprocess.CompletedProcess(command, returncode, body + "\n" + status, "sensitive diagnostics"))
    result = WATCH.curl_request(URL, "us-east-1", "session", CREDENTIALS, 10)
    assert not result["ok"]
    assert result["error"] == error
    assert result["http_status"] == int(status)
    assert "sensitive diagnostics" not in json.dumps(result)


def test_curl_timeout_is_recorded(monkeypatch):
    def execute(command, **options):
        raise subprocess.TimeoutExpired(command, 10)

    monkeypatch.setattr(WATCH.subprocess, "run", execute)
    result = WATCH.curl_request(URL, "us-east-1", "session", CREDENTIALS, 10)
    assert result["error"] == "curl_execution_failed"


def test_cli_failures_do_not_expose_stderr(monkeypatch):
    monkeypatch.setattr(WATCH.subprocess, "run", lambda command, **options: subprocess.CompletedProcess(command, 1, "", "secret-from-cli"))
    with pytest.raises(RuntimeError) as error:
        WATCH.aws_json(["configure", "export-credentials", "--format", "process"], "default", "us-east-1")
    assert "secret-from-cli" not in str(error.value)


def test_gateway_discovery_uses_aws_iam_and_ready(monkeypatch):
    calls = []

    def aws_json(arguments, profile, region):
        calls.append(arguments)
        if arguments[1] == "list-gateways":
            return {"items": [{"name": "eks-ack-devops-gateway", "gatewayId": "example"}]}
        return {"gatewayUrl": URL, "status": "READY", "authorizerType": "AWS_IAM"}

    monkeypatch.setattr(WATCH, "aws_json", aws_json)
    assert WATCH.resolve_url(WATCH.parse_args([])) == URL + "/agent/invocations"
    assert len(calls) == 2
    monkeypatch.setattr(WATCH, "aws_json", lambda *arguments: {"items": []})
    with pytest.raises(RuntimeError, match="exactly one"):
        WATCH.resolve_url(WATCH.parse_args([]))


def test_both_session_lanes_refresh_credentials_and_detect_change(monkeypatch, capsys):
    credentials_calls = []
    requests = []

    def aws_json(arguments, profile, region):
        credentials_calls.append((arguments, profile, region))
        return dict(CREDENTIALS)

    def curl_request(url, region, session, credentials, timeout):
        requests.append(session)
        release = "v2" if len(requests) == 4 else "v1"
        return {"ok": True, "http_status": 200, "release": release, "build_revision": "build-" + release}

    monkeypatch.setattr(WATCH, "aws_json", aws_json)
    monkeypatch.setattr(WATCH, "curl_request", curl_request)
    monkeypatch.setattr(WATCH.time, "sleep", lambda duration: None)
    args = WATCH.parse_args(["--gateway-url", URL, "--session-mode", "both", "--count", "4"])
    assert WATCH.observe(args) == 0
    output = capsys.readouterr()
    rows = [json.loads(line) for line in output.out.splitlines()]
    assert len(credentials_calls) == 4
    assert requests[0] == requests[2]
    assert len({requests[0], requests[1], requests[3]}) == 3
    assert [row["lane"] for row in rows] == ["existing", "new", "existing", "new"]
    assert [row["changed"] for row in rows] == [False, False, False, True]
    assert json.loads(output.err)["requests"] == 4
    assert not any(secret in output.out + output.err for secret in CREDENTIALS.values())


def test_request_failures_do_not_stop_observation(monkeypatch, capsys):
    results = iter([
        {"ok": True, "http_status": 200, "release": "v1", "build_revision": "build-v1"},
        {"ok": False, "http_status": 503, "error": "http_error"},
        {"ok": True, "http_status": 200, "release": "v2", "build_revision": "build-v2"},
    ])
    monkeypatch.setattr(WATCH, "aws_json", lambda *arguments: dict(CREDENTIALS))
    monkeypatch.setattr(WATCH, "curl_request", lambda *arguments: next(results))
    monkeypatch.setattr(WATCH.time, "sleep", lambda duration: None)
    assert WATCH.observe(WATCH.parse_args(["--gateway-url", URL, "--count", "3"])) == 1
    output = capsys.readouterr()
    rows = [json.loads(line) for line in output.out.splitlines()]
    assert len(rows) == 3 and not rows[1]["ok"] and rows[2]["changed"]
    assert json.loads(output.err)["failed"] == 1


def test_real_curl_signs_local_tls_request(tmp_path, monkeypatch):
    if not shutil.which("curl") or not shutil.which("openssl"):
        pytest.skip("curl and openssl are required for the local TLS transport test")
    supported = subprocess.run(["curl", "--help", "all"], capture_output=True, text=True, check=True).stdout
    if "--aws-sigv4" not in supported or "--fail-with-body" not in supported:
        pytest.skip("curl lacks the signing options used by this sample")
    hostname = "example-gateway.gateway.bedrock-agentcore.us-east-1.amazonaws.com"
    certificate = tmp_path / "certificate.pem"
    private_key = tmp_path / "private.key"
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
        "-subj", "/CN=curl-local-test", "-addext", f"subjectAltName=DNS:{hostname}",
        "-keyout", str(private_key), "-out", str(certificate),
    ], check=True, capture_output=True)
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append({"path": self.path, "headers": dict(self.headers), "body": json.loads(body)})
            response = json.dumps(agent_response()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, format, *arguments):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(certificate, private_key)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    run_command = subprocess.run

    def local_transport(command, **options):
        assert command[0] == "curl"
        return run_command(command + [
            "--connect-to", f"{hostname}:443:127.0.0.1:{server.server_port}",
            "--cacert", str(certificate), "--noproxy", "*",
        ], **options)

    monkeypatch.setattr(WATCH.subprocess, "run", local_transport)
    try:
        result = WATCH.curl_request(URL + "/agent/invocations", "us-east-1", "local-tls-session", CREDENTIALS, 10)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    assert result["ok"] and len(received) == 1
    request = received[0]
    headers = {name.lower(): value for name, value in request["headers"].items()}
    assert request["path"] == "/agent/invocations"
    assert "/us-east-1/bedrock-agentcore/aws4_request" in headers["authorization"]
    assert headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=testing-access/")
    assert headers["x-amz-security-token"] == "testing-token"
    assert headers["x-amzn-bedrock-agentcore-runtime-session-id"] == "local-tls-session"
    assert request["body"] == {"prompt": "Reply with exactly OK. Do not call tools."}
