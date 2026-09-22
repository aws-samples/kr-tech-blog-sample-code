import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.config import Config


def find_gateway(control, name: str) -> dict:
    matches = [item for page in control.get_paginator("list_gateways").paginate()
               for item in page.get("items", []) if item["name"] == name]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one gateway named {name}, found {len(matches)}")
    return control.get_gateway(gatewayIdentifier=matches[0]["gatewayId"])


def invocation_url(gateway: dict, target: str, region: str) -> str:
    parsed = urlsplit(gateway["gatewayUrl"])
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(f".gateway.bedrock-agentcore.{region}.amazonaws.com"):
        raise ValueError("Unexpected AgentCore Gateway URL")
    if not target or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in target):
        raise ValueError("Invalid target name")
    return f"https://{parsed.hostname}/{target}/invocations"


def invoke_gateway(session, gateway: dict, target: str, prompt: str) -> dict:
    region = session.region_name
    url = invocation_url(gateway, target, region)
    body = json.dumps({"prompt": prompt}).encode()
    request = AWSRequest(method="POST", url=url, data=body, headers={
        "Content-Type": "application/json", "Accept": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": str(uuid.uuid4()),
    })
    SigV4Auth(session.get_credentials().get_frozen_credentials(), "bedrock-agentcore", region).add_auth(request)
    with httpx.Client(timeout=httpx.Timeout(300, connect=10), follow_redirects=False) as client:
        response = client.post(url, content=body, headers=dict(request.headers))
        response.raise_for_status()
        result = response.json()
    return json.loads(result) if isinstance(result, str) else result


def verify_response(result: dict, release: str, build: str | None) -> None:
    if result.get("release") != release:
        raise RuntimeError(f"Release mismatch: expected {release}, received {result.get('release')}")
    if build and result.get("build_revision") != build:
        raise RuntimeError(f"Build mismatch: expected {build}, received {result.get('build_revision')}")
    if not isinstance(result.get("response"), str) or not result["response"].strip():
        raise RuntimeError("The model response was empty")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway-name", default="eks-ack-devops-gateway")
    parser.add_argument("--target", default="agent")
    parser.add_argument("--runtime-id", required=True)
    parser.add_argument("--expect-release", required=True)
    parser.add_argument("--expect-image", required=True)
    parser.add_argument("--expect-build")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    session = boto3.Session(region_name=os.getenv("AWS_REGION", "us-east-1"))
    control = session.client("bedrock-agentcore-control", config=Config(
        retries={"total_max_attempts": 4, "mode": "standard"}, read_timeout=30, connect_timeout=10,
    ))
    deadline = time.monotonic() + 300
    while True:
        runtime = control.get_agent_runtime(agentRuntimeId=args.runtime_id)
        endpoint = control.get_agent_runtime_endpoint(agentRuntimeId=args.runtime_id, endpointName="DEFAULT")
        actual_image = runtime["agentRuntimeArtifact"]["containerConfiguration"]["containerUri"]
        if (runtime["status"] == "READY" and endpoint["status"] == "READY"
                and endpoint["liveVersion"] == runtime["agentRuntimeVersion"] and actual_image == args.expect_image):
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("Runtime did not converge to the expected image and DEFAULT version")
        time.sleep(5)
    gateway = find_gateway(control, args.gateway_name)
    if gateway["status"] != "READY":
        raise RuntimeError(f"Gateway is {gateway['status']}")
    result = invoke_gateway(session, gateway, args.target, "deployment_info 도구로 현재 릴리스와 빌드 버전을 한 문장으로 알려주세요.")
    verify_response(result, args.expect_release, args.expect_build)
    evidence = {
        "gateway_id": gateway["gatewayId"], "gateway_url": invocation_url(gateway, args.target, session.region_name),
        "runtime_id": args.runtime_id, "runtime_version": runtime["agentRuntimeVersion"],
        "image": actual_image, "result": result, "check": "Successful",
    }
    rendered = json.dumps(evidence, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
