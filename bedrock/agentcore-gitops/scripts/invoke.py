import argparse
import json
import os
import sys
import uuid
from pathlib import Path

import boto3
from botocore.config import Config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arn", required=True)
    parser.add_argument("--qualifier", default="live")
    parser.add_argument("--expect-release")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--prompt", default="deployment_info 도구로 현재 배포 버전을 확인하고 한 문장으로 알려주세요.")
    args = parser.parse_args()
    session = boto3.Session(
        profile_name=os.getenv("AWS_PROFILE", "default"),
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )
    client = session.client("bedrock-agentcore", config=Config(
        read_timeout=300, connect_timeout=10,
        retries={"total_max_attempts": 3, "mode": "standard"},
    ))
    response = client.invoke_agent_runtime(
        agentRuntimeArn=args.arn,
        qualifier=args.qualifier,
        runtimeSessionId=str(uuid.uuid4()),
        payload=json.dumps({"prompt": args.prompt}).encode(),
        contentType="application/json",
        accept="application/json",
    )
    result = json.loads(response["response"].read())
    if isinstance(result, str):
        result = json.loads(result)
    if args.expect_release and result.get("release") != args.expect_release:
        raise RuntimeError(f"Expected {args.expect_release}, received {result}")
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
