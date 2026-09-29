import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
import uuid
from urllib.parse import urlsplit


def aws_json(arguments, profile, region):
    command = ["aws", *arguments, "--profile", profile, "--region", region]
    if arguments[:2] != ["configure", "export-credentials"]:
        command.extend(["--output", "json", "--no-cli-pager"])
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("AWS CLI could not complete; check the installation, profile and connectivity") from error
    if completed.returncode:
        raise RuntimeError(f"AWS CLI {arguments[0]} {arguments[1]} failed with exit code {completed.returncode}")
    try:
        value = json.loads(completed.stdout)
    except ValueError as error:
        raise RuntimeError("AWS CLI did not return valid JSON") from error
    if not isinstance(value, dict):
        raise RuntimeError("AWS CLI did not return a JSON object")
    return value


def gateway_url(value, region, target):
    parsed = urlsplit(value)
    hostname = parsed.hostname or ""
    expected = rf"[a-z0-9-]+\.gateway\.bedrock-agentcore\.{re.escape(region)}\.amazonaws\.com"
    if parsed.scheme != "https" or not re.fullmatch(expected, hostname):
        raise ValueError("Gateway URL must be an HTTPS AgentCore Gateway URL in the selected region")
    if parsed.netloc != hostname or parsed.path not in ["", "/"] or parsed.query or parsed.fragment:
        raise ValueError("Use the Gateway base URL without credentials, port, target path, query or fragment")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", target):
        raise ValueError("Target must contain only letters, digits, hyphens or underscores")
    return f"https://{hostname}/{target}/invocations"


def resolve_url(args):
    if args.gateway_url:
        return gateway_url(args.gateway_url, args.region, args.target)
    response = aws_json(["bedrock-agentcore-control", "list-gateways"], args.profile, args.region)
    matches = [gateway for gateway in response.get("items", []) if gateway.get("name") == args.gateway_name]
    if len(matches) != 1:
        raise RuntimeError("Expected exactly one matching Gateway; deploy the environment or pass --gateway-url")
    gateway = aws_json(["bedrock-agentcore-control", "get-gateway", "--gateway-identifier", matches[0]["gatewayId"]], args.profile, args.region)
    if gateway.get("status") != "READY" or gateway.get("authorizerType") != "AWS_IAM":
        raise RuntimeError("Gateway must be READY and use AWS_IAM authentication")
    return gateway_url(gateway["gatewayUrl"], args.region, args.target)


def credential_config(credentials):
    for field in ["AccessKeyId", "SecretAccessKey"]:
        if not isinstance(credentials.get(field), str) or not credentials[field].strip():
            raise ValueError("AWS CLI returned incomplete signing credentials")
    lines = ["user = " + json.dumps(credentials["AccessKeyId"] + ":" + credentials["SecretAccessKey"])]
    token = credentials.get("SessionToken")
    if token:
        if not isinstance(token, str):
            raise ValueError("AWS CLI returned an invalid session token")
        lines.append("header = " + json.dumps("X-Amz-Security-Token: " + token))
    return "\n".join(lines) + "\n"


def curl_request(url, region, session_id, credentials, timeout):
    command = [
        "curl", "-q", "--config", "-", "--proto", "=https",
        "--aws-sigv4", f"aws:amz:{region}:bedrock-agentcore",
        "--silent", "--show-error", "--fail-with-body", "--retry", "0",
        "--connect-timeout", str(min(10, timeout)), "--max-time", str(timeout),
        "--header", "Content-Type: application/json", "--header", "Accept: application/json",
        "--header", f"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: {session_id}",
        "--data", json.dumps({"prompt": "Reply with exactly OK. Do not call tools."}),
        "--write-out", "\n%{http_code}", "--url", url,
    ]
    started = time.monotonic()
    try:
        result = subprocess.run(command, input=credential_config(credentials), capture_output=True, text=True, timeout=timeout + 5)
    except (OSError, subprocess.TimeoutExpired):
        return {"ok": False, "http_status": None, "error": "curl_execution_failed", "latency_seconds": round(time.monotonic() - started, 3)}
    record = {"ok": False, "http_status": None, "curl_exit_code": result.returncode, "latency_seconds": round(time.monotonic() - started, 3)}
    body, separator, status = result.stdout.rpartition("\n")
    if separator and re.fullmatch(r"\d{3}", status):
        record["http_status"] = int(status)
    if result.returncode or record["http_status"] != 200:
        record["error"] = "http_error" if record["http_status"] and record["http_status"] >= 400 else "curl_transport_error"
        return record
    try:
        response = json.loads(body)
        if isinstance(response, str):
            response = json.loads(response)
    except ValueError:
        record["error"] = "invalid_json_response"
        return record
    if not isinstance(response, dict) or any(not isinstance(response.get(key), str) or not response[key].strip() for key in ["release", "build_revision", "response"]):
        record["error"] = "missing_release_metadata_or_model_response"
        return record
    record.update({"ok": True, "release": response["release"], "build_revision": response["build_revision"]})
    return record


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Observe AgentCore Gateway release changes with real SigV4-signed curl requests")
    parser.add_argument("--profile", default=os.getenv("AWS_PROFILE", "default"))
    parser.add_argument("--region", default=os.getenv("AWS_REGION", "us-east-1"))
    parser.add_argument("--gateway-name", default="eks-ack-devops-gateway")
    parser.add_argument("--gateway-url", help="Optional Gateway base URL; otherwise resolve --gateway-name through AWS CLI")
    parser.add_argument("--target", default="agent")
    parser.add_argument("--session-mode", choices=["new", "existing", "both"], default="new")
    parser.add_argument("--count", type=int, default=60, help="Maximum total requests, not per session lane (1-300)")
    parser.add_argument("--interval", type=float, default=3, help="Seconds after each response (1-60)")
    parser.add_argument("--timeout", type=float, default=60, help="Per-request timeout (1-120 seconds)")
    parser.add_argument("--duration", type=float, default=300, help="Stop scheduling after this duration (1-600 seconds)")
    args = parser.parse_args(argv)
    if not 1 <= args.count <= 300 or not 1 <= args.interval <= 60 or not 1 <= args.timeout <= 120 or not 1 <= args.duration <= 600:
        parser.error("Requested observation exceeds the sample safety limits")
    if not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", args.region) or not re.fullmatch(r"[A-Za-z0-9_-]+", args.target):
        parser.error("Invalid AWS region or Gateway target")
    if args.gateway_url:
        try:
            gateway_url(args.gateway_url, args.region, args.target)
        except ValueError as error:
            parser.error(str(error))
    return args


def observe(args):
    url = resolve_url(args)
    existing_session = str(uuid.uuid4())
    previous = {}
    failures = 0
    completed = 0
    deadline = time.monotonic() + args.duration
    for index in range(args.count):
        if time.monotonic() >= deadline:
            break
        lane = "existing" if args.session_mode == "existing" or args.session_mode == "both" and index % 2 == 0 else "new"
        session_id = existing_session if lane == "existing" else str(uuid.uuid4())
        credentials = aws_json(["configure", "export-credentials", "--format", "process"], args.profile, args.region)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        record = curl_request(url, args.region, session_id, credentials, min(args.timeout, remaining))
        del credentials
        record.update({"time": datetime.datetime.now(datetime.timezone.utc).isoformat(), "request": index + 1, "lane": lane, "session_id": session_id})
        if record["ok"]:
            current = (record["release"], record["build_revision"])
            record["changed"] = lane in previous and previous[lane] != current
            previous[lane] = current
        else:
            failures += 1
        print(json.dumps(record, ensure_ascii=False), flush=True)
        completed += 1
        if index + 1 < args.count:
            time.sleep(max(0, min(args.interval, deadline - time.monotonic())))
    print(json.dumps({"requests": completed, "failed": failures, "session_mode": args.session_mode}), file=sys.stderr)
    return 1 if failures or not completed else 0


def main():
    args = parse_args()
    try:
        return observe(args)
    except (RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
