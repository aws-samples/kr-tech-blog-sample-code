import argparse
import hashlib
import json
from pathlib import Path
import re

import yaml


CRD_KINDS = {
    "agentruntimes": "AgentRuntime",
    "agentruntimeendpoints": "AgentRuntimeEndpoint",
    "gateways": "Gateway",
    "gatewaytargets": "GatewayTarget",
}
COMMON_CRD_KINDS = {
    "adoptedresources": "AdoptedResource",
    "fieldexports": "FieldExport",
    "iamroleselectors": "IAMRoleSelector",
}


def crd_hashes(directory: Path) -> dict[str, str]:
    hashes = {}
    for resource, kind in CRD_KINDS.items():
        path = directory / f"bedrockagentcorecontrol.services.k8s.aws_{resource}.yaml"
        content = path.read_bytes()
        document = yaml.safe_load(content)
        if document["spec"]["names"]["kind"] != kind:
            raise ValueError(f"Unexpected CRD kind in {path.name}")
        version = next(item for item in document["spec"]["versions"] if item["name"] == "v1alpha1")
        spec = version["schema"]["openAPIV3Schema"]["properties"]["spec"]
        if kind == "Gateway" and "protocolType" in spec.get("required", []):
            raise ValueError("Gateway CRD must allow HTTP targets without protocolType")
        if kind == "GatewayTarget":
            target = spec["properties"]["targetConfiguration"]["properties"]
            runtime = target["http"]["properties"]["agentcoreRuntime"]
            if not {"arn", "qualifier"}.issubset(runtime["properties"]):
                raise ValueError("GatewayTarget CRD is missing HTTP Runtime fields")
        hashes[path.name] = hashlib.sha256(content).hexdigest()
    for resource, kind in COMMON_CRD_KINDS.items():
        path = directory / f"services.k8s.aws_{resource}.yaml"
        content = path.read_bytes()
        if yaml.safe_load(content)["spec"]["names"]["kind"] != kind:
            raise ValueError(f"Unexpected CRD kind in {path.name}")
        hashes[path.name] = hashlib.sha256(content).hexdigest()
    return hashes


def build_metadata(versions: dict, directory: Path) -> dict:
    return {
        "chartVersion": versions["ackAgentCoreChart"],
        "controllerVersion": versions["ackControllerPatch"],
        "sourceRevision": versions["ackControllerSourceRevision"],
        "crdSha256": crd_hashes(directory),
    }


def verify_values(values: dict, versions: dict, directory: Path) -> None:
    if not isinstance(values, dict) or not isinstance(values.get("image"), dict):
        raise ValueError("ACK image values must contain an image object")
    image = values.get("image", {})
    tag = image.get("tag", "")
    prefix = f"ack-{versions['ackControllerPatch']}-"
    if not image.get("repository") or not isinstance(tag, str) or not tag.startswith(prefix) or not re.fullmatch(r"[^@]+@sha256:[0-9a-f]{64}", tag):
        raise ValueError("ACK image must use the configured controller version and an immutable digest")
    metadata = values.get("ackBuild", {})
    if not isinstance(metadata, dict):
        raise ValueError("ACK build metadata must be an object")
    for name, expected in build_metadata(versions, directory).items():
        if metadata.get(name) != expected:
            raise ValueError(f"ACK image/CRD build metadata mismatch: {name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["create", "verify"])
    parser.add_argument("--versions", type=Path, default=Path("config/versions.json"))
    parser.add_argument("--crd-dir", type=Path, default=Path(".state/ack-crds"))
    parser.add_argument("--values", type=Path, required=True)
    parser.add_argument("--repository")
    parser.add_argument("--tag")
    args = parser.parse_args()
    try:
        versions = json.loads(args.versions.read_text())
        if args.operation == "create":
            if not args.repository or not args.tag:
                parser.error("create requires --repository and --tag")
            values = {
                "image": {"repository": args.repository, "tag": args.tag},
                "ackBuild": build_metadata(versions, args.crd_dir),
            }
        else:
            values = yaml.safe_load(args.values.read_text())
        verify_values(values, versions, args.crd_dir)
        if args.operation == "create":
            args.values.write_text(json.dumps(values, indent=2) + "\n")
    except (OSError, ValueError, KeyError, TypeError, StopIteration, yaml.YAMLError) as error:
        parser.exit(1, f"ACK assets are not ready: {error}. Run bash scripts/build-ack-controller.sh.\n")
    print(f"ACK chart {versions['ackAgentCoreChart']}: image and seven CRDs match the configured build")


if __name__ == "__main__":
    main()
