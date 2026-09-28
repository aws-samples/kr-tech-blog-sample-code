import argparse
import collections
import concurrent.futures
import datetime
import json
import math
import os
import sys
import threading
import time
import uuid
from pathlib import Path

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.config import Config

from gateway_probe import find_gateway, invocation_url


def timestamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def classify_phase(start: float, finish: float, deployment: float, completion: float) -> str:
    if finish < deployment:
        return "before"
    if start >= completion:
        return "after"
    return "during_or_crossing"


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]


def request_summary(records: list[dict]) -> dict:
    successful = [record for record in records if record["ok"]]
    latency = [record["latency_seconds"] for record in records]
    return {
        "requests": len(records), "successful": len(successful),
        "failed": len(records) - len(successful),
        "error_rate": (len(records) - len(successful)) / len(records) if records else None,
        "latency_seconds": {"p50": percentile(latency, 0.5), "p95": percentile(latency, 0.95), "max": max(latency, default=None)},
        "status_counts": dict(collections.Counter(str(record.get("http_status")) for record in records)),
        "release_counts": dict(collections.Counter(record.get("release", "unknown") for record in successful)),
    }


class Recorder:
    def __init__(self, directory: Path, max_requests: int):
        self.directory = directory
        self.max_requests = max_requests
        self.lock = threading.Lock()
        self.request_count = 0

    def claim(self) -> int | None:
        with self.lock:
            if self.request_count >= self.max_requests:
                return None
            self.request_count += 1
            return self.request_count

    def append(self, filename: str, record: dict) -> None:
        with self.lock, (self.directory / filename).open("a") as output:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            output.flush()


def send_request(client, credentials, region, url, session_id, lane, sequence, baseline, candidate) -> dict:
    prompt = "Reply with exactly OK. Do not call tools."
    if lane == "long":
        prompt = "Write a detailed English explanation of how GitOps deploys an AI agent. Use approximately 350 words. Do not call tools."
    body = json.dumps({"prompt": prompt}).encode()
    started = time.time()
    record = {"sequence": sequence, "lane": lane, "session_id": session_id, "started_epoch": started, "started_at": timestamp(), "ok": False}
    try:
        request = AWSRequest(method="POST", url=url, data=body, headers={
            "Content-Type": "application/json", "Accept": "application/json",
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
        })
        SigV4Auth(credentials, "bedrock-agentcore", region).add_auth(request)
        response = client.post(url, content=body, headers=dict(request.headers))
        record.update({
            "http_status": response.status_code, "content_type": response.headers.get("content-type"),
            "request_id": response.headers.get("x-amzn-requestid", response.headers.get("x-amzn-request-id")),
            "returned_session_id": response.headers.get("x-amzn-bedrock-agentcore-runtime-session-id"),
            "response_bytes": len(response.content),
        })
        if response.status_code != 200:
            record["error"] = response.text[:1500]
        else:
            result = response.json()
            if isinstance(result, str):
                result = json.loads(result)
            record.update({"release": result.get("release"), "build_revision": result.get("build_revision"), "model_id": result.get("model_id")})
            if not isinstance(result.get("response"), str) or not result["response"].strip():
                record["error"] = "empty_model_response"
            elif result.get("release") not in [baseline, candidate]:
                record["error"] = "unexpected_release"
            else:
                record["ok"] = True
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as error:
        record["error_type"] = type(error).__name__
        record["error"] = str(error)[:1500]
    record["finished_epoch"] = time.time()
    record["finished_at"] = timestamp()
    record["latency_seconds"] = round(record["finished_epoch"] - started, 6)
    return record


def run_probe(args) -> None:
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "requests.jsonl").exists():
        raise ValueError("Use a new output directory; previous request data must not be mixed")
    session = boto3.Session(profile_name=os.getenv("AWS_PROFILE", "default"), region_name=os.getenv("AWS_REGION", "us-east-1"))
    control = session.client("bedrock-agentcore-control", config=Config(
        retries={"total_max_attempts": 1, "mode": "standard"}, read_timeout=10, connect_timeout=5,
    ))
    gateway = find_gateway(control, args.gateway_name)
    baseline_runtime = control.get_agent_runtime(agentRuntimeId=args.runtime_id)
    url = invocation_url(gateway, args.target, session.region_name)
    credentials = session.get_credentials().get_frozen_credentials()
    recorder = Recorder(args.output, args.max_requests)
    stop = threading.Event()
    persistent_session = str(uuid.uuid4())
    initial = time.time()
    config = {
        "started_at": timestamp(), "started_epoch": initial, "gateway_id": gateway["gatewayId"],
        "gateway_url": url, "runtime_id": args.runtime_id, "baseline_release": args.baseline,
        "candidate_release": args.candidate, "persistent_session_id": persistent_session,
        "baseline_runtime_version": baseline_runtime["agentRuntimeVersion"],
        "new_workers": args.new_workers, "interval_seconds": args.interval,
        "request_timeout_seconds": args.timeout, "max_duration_seconds": args.duration,
        "max_requests": args.max_requests, "client_retries": 0,
    }
    (args.output / "config.json").write_text(json.dumps(config, indent=2))

    def worker(lane: str):
        with httpx.Client(timeout=httpx.Timeout(args.timeout, connect=10), follow_redirects=False, transport=httpx.HTTPTransport(retries=0)) as client:
            while not stop.is_set():
                if recorder.request_count >= recorder.max_requests:
                    return
                if lane == "long" and not (args.output / "start-long").exists():
                    stop.wait(0.2)
                    continue
                if lane == "long" and (args.output / "deployment-complete.json").exists():
                    return
                sequence = recorder.claim()
                if sequence is None:
                    return
                session_id = persistent_session if lane == "existing" else str(uuid.uuid4())
                if lane == "long":
                    recorder.append("long-starts.jsonl", {"sequence": sequence, "started_epoch": time.time(), "time": timestamp()})
                result = send_request(client, credentials, session.region_name, url, session_id, lane, sequence, args.baseline, args.candidate)
                recorder.append("requests.jsonl", result)
                if not result["ok"]:
                    print(json.dumps({"request_failed": result}), flush=True)
                stop.wait(args.interval)

    def observe():
        while not stop.is_set():
            record = {"time": timestamp(), "epoch": time.time()}
            try:
                runtime = control.get_agent_runtime(agentRuntimeId=args.runtime_id)
                endpoint = control.get_agent_runtime_endpoint(agentRuntimeId=args.runtime_id, endpointName="DEFAULT")
                record.update({"runtime_version": runtime["agentRuntimeVersion"], "runtime_status": runtime["status"], "endpoint_status": endpoint["status"], "live_version": endpoint.get("liveVersion"), "image": runtime["agentRuntimeArtifact"]["containerConfiguration"]["containerUri"]})
            except Exception as error:
                record["observation_error"] = f"{type(error).__name__}: {error}"
            recorder.append("observations.jsonl", record)
            stop.wait(3)

    workers = [f"new-{index + 1}" for index in range(args.new_workers)] + ["existing", "long"]
    futures = []
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(workers) + 1) as executor:
            futures = [executor.submit(worker, lane) for lane in workers]
            observer = executor.submit(observe)
            try:
                while time.time() - initial < args.duration:
                    if (args.output / "stop").exists():
                        break
                    for future in futures:
                        if future.done() and future.exception():
                            raise future.exception()
                    if recorder.request_count >= args.max_requests and all(future.done() for future in futures):
                        break
                    time.sleep(0.25)
            finally:
                stop.set()
            for future in futures + [observer]:
                future.result()
    finally:
        (args.output / "finished.json").write_text(json.dumps({"time": timestamp(), "epoch": time.time(), "claimed_requests": recorder.request_count}))


def summarize(directory: Path) -> dict:
    records = [json.loads(line) for line in (directory / "requests.jsonl").read_text().splitlines()]
    observations = [json.loads(line) for line in (directory / "observations.jsonl").read_text().splitlines()]
    config = json.loads((directory / "config.json").read_text())
    deployment_path = directory / "deployment-start.json"
    completion_path = directory / "deployment-complete.json"
    if deployment_path.exists() != completion_path.exists():
        raise ValueError("A rollout report requires both deployment boundary markers")
    baseline_only = not deployment_path.exists()
    deployment = math.inf if baseline_only else json.loads(deployment_path.read_text())["epoch"]
    completion = math.inf if baseline_only else json.loads(completion_path.read_text())["epoch"]
    for record in records:
        record["phase"] = classify_phase(record["started_epoch"], record["finished_epoch"], deployment, completion)
    updated = [record for record in observations if record.get("runtime_status") == "UPDATING" or record.get("endpoint_status") == "UPDATING"]
    baseline_version = config.get("baseline_runtime_version")
    first_candidate = next((record for record in observations if baseline_version is not None and record.get("live_version") is not None and record["live_version"] != baseline_version and record.get("endpoint_status") == "READY"), None)
    boundary = updated[0]["epoch"] if updated else deployment
    inflight = [record for record in records if record["started_epoch"] < boundary < record["finished_epoch"]]
    overlap = [record for record in records if record["started_epoch"] < (first_candidate["epoch"] if first_candidate else completion) and record["finished_epoch"] >= boundary]
    by_lane = {lane: request_summary([record for record in records if record["lane"] == lane]) for lane in sorted({record["lane"] for record in records})}
    by_phase = {phase: request_summary([record for record in records if record["phase"] == phase]) for phase in ["before", "during_or_crossing", "after"]}
    existing = [record for record in records if record["lane"] == "existing"]
    result = {
        "mode": "baseline_only" if baseline_only else "rollout",
        "configuration": config, "overall": request_summary(records), "by_phase": by_phase, "by_lane": by_lane,
        "deployment_started_epoch": None if baseline_only else deployment,
        "deployment_completed_epoch": None if baseline_only else completion,
        "observed_update_start": updated[0] if updated else None, "first_observed_candidate_ready": first_candidate,
        "inflight_at_update_observation": inflight, "overlapping_update": request_summary(overlap),
        "same_session": {"session_id_count": len({record["session_id"] for record in existing}),
                         "releases_by_phase": {phase: dict(collections.Counter(record.get("release", "error") for record in existing if record["phase"] == phase)) for phase in by_phase}},
        "errors": [record for record in records if not record["ok"]],
        "observation_errors": [record for record in observations if record.get("observation_error")],
        "limitations": ["Sampled low-load JSON requests, not a universal zero-downtime guarantee", "No client retries; AWS internal retries are not observable", "Same session ID does not prove microVM identity or conversation-state durability", "No SSE streaming implementation exists in the tested agent", "Boundary timestamps are sampled control-plane observations"],
    }
    (directory / "summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    runner = subparsers.add_parser("run")
    runner.add_argument("--output", required=True, type=Path)
    runner.add_argument("--runtime-id", required=True)
    runner.add_argument("--gateway-name", default="eks-ack-devops-gateway")
    runner.add_argument("--target", default="agent")
    runner.add_argument("--baseline", required=True)
    runner.add_argument("--candidate", required=True)
    runner.add_argument("--new-workers", type=int, default=2)
    runner.add_argument("--interval", type=float, default=2)
    runner.add_argument("--timeout", type=float, default=60)
    runner.add_argument("--duration", type=float, default=360)
    runner.add_argument("--max-requests", type=int, default=180)
    report = subparsers.add_parser("summarize")
    report.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "run":
        if not 1 <= args.new_workers <= 2 or args.interval < 1 or not 1 <= args.duration <= 600 or not 1 <= args.max_requests <= 300 or not 1 <= args.timeout <= 120:
            raise ValueError("Probe exceeds demo safety limits")
        run_probe(args)
    else:
        print(json.dumps(summarize(args.output), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
