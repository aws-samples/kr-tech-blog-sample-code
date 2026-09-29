from copy import deepcopy
from pathlib import Path
import runpy
import os
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
ASSETS = runpy.run_path(str(ROOT / "scripts/ack-assets.py"))


@pytest.fixture
def bundle(tmp_path):
    versions = {
        "ackAgentCoreChart": "1.15.1",
        "ackControllerPatch": "1.15.1-http-runtime.1",
        "ackControllerSourceRevision": "ba36b95fc5ec9ad1e8fa306fe339d227246bf601",
    }
    for resource, kind in ASSETS["CRD_KINDS"].items():
        schema = {"type": "object", "properties": {}}
        if kind == "GatewayTarget":
            schema["properties"]["targetConfiguration"] = {
                "properties": {
                    "http": {"properties": {"agentcoreRuntime": {"properties": {
                        "arn": {"type": "string"}, "qualifier": {"type": "string"},
                    }}}},
                    "mcp": {"type": "object"},
                },
            }
        document = {"spec": {
            "names": {"kind": kind},
            "versions": [{"name": "v1alpha1", "schema": {
                "openAPIV3Schema": {"properties": {"spec": schema}},
            }}],
        }}
        path = tmp_path / f"bedrockagentcorecontrol.services.k8s.aws_{resource}.yaml"
        path.write_text(yaml.safe_dump(document))
    for resource, kind in ASSETS["COMMON_CRD_KINDS"].items():
        path = tmp_path / f"services.k8s.aws_{resource}.yaml"
        path.write_text(yaml.safe_dump({"spec": {"names": {"kind": kind}}}))
    values = {
        "image": {
            "repository": "123456789012.dkr.ecr.us-east-1.amazonaws.com/ack",
            "tag": "ack-1.15.1-http-runtime.1-test@sha256:" + "a" * 64,
        },
        "ackBuild": ASSETS["build_metadata"](versions, tmp_path),
    }
    return versions, values, tmp_path


def test_matching_controller_and_seven_crds_are_accepted(bundle):
    versions, values, directory = bundle
    ASSETS["verify_values"](values, versions, directory)
    assert len(values["ackBuild"]["crdSha256"]) == 7


@pytest.mark.parametrize("resource", ["adoptedresources", "fieldexports", "iamroleselectors"])
def test_missing_common_crd_is_rejected(bundle, resource):
    versions, values, directory = bundle
    (directory / f"services.k8s.aws_{resource}.yaml").unlink()
    with pytest.raises(FileNotFoundError):
        ASSETS["verify_values"](values, versions, directory)


def test_helm_install_skips_separately_managed_crds():
    script = (ROOT / "scripts/install-platform.sh").read_text()
    command = script.split("helm upgrade --install ack-agentcore", 1)[1].split("helm upgrade --install argo-rollouts", 1)[0]
    assert "--skip-crds" in command


@pytest.mark.parametrize("tag", [
    "ack-1.15.0-http-runtime-test@sha256:" + "a" * 64,
    "ack-1.15.1-http-runtime.1-test",
    "ack-1.15.1-http-runtime.1-test@sha256:invalid",
    1151,
])
def test_old_or_mutable_controller_image_is_rejected(bundle, tag):
    versions, values, directory = bundle
    values["image"]["tag"] = tag
    with pytest.raises(ValueError, match="immutable digest"):
        ASSETS["verify_values"](values, versions, directory)


@pytest.mark.parametrize("field", ["chartVersion", "controllerVersion", "sourceRevision"])
def test_controller_build_metadata_must_match_configuration(bundle, field):
    versions, values, directory = bundle
    values["ackBuild"][field] = "older-build"
    with pytest.raises(ValueError, match=field):
        ASSETS["verify_values"](values, versions, directory)


def test_crd_changes_require_matching_build_metadata(bundle):
    versions, values, directory = bundle
    path = directory / "bedrockagentcorecontrol.services.k8s.aws_agentruntimes.yaml"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="crdSha256"):
        ASSETS["verify_values"](values, versions, directory)


def test_runtime_crd_is_required(bundle):
    versions, values, directory = bundle
    path = directory / "bedrockagentcorecontrol.services.k8s.aws_agentruntimes.yaml"
    path.unlink()
    with pytest.raises(FileNotFoundError):
        ASSETS["verify_values"](values, versions, directory)


def test_stock_gateway_target_crd_is_rejected(bundle):
    versions, values, directory = bundle
    path = directory / "bedrockagentcorecontrol.services.k8s.aws_gatewaytargets.yaml"
    resource = yaml.safe_load(path.read_text())
    spec = resource["spec"]["versions"][0]["schema"]["openAPIV3Schema"]["properties"]["spec"]
    del spec["properties"]["targetConfiguration"]["properties"]["http"]
    path.write_text(yaml.safe_dump(resource))
    with pytest.raises(KeyError, match="http"):
        ASSETS["verify_values"](values, versions, directory)


def test_gateway_protocol_type_must_be_optional(bundle):
    versions, values, directory = bundle
    path = directory / "bedrockagentcorecontrol.services.k8s.aws_gateways.yaml"
    resource = yaml.safe_load(path.read_text())
    spec = resource["spec"]["versions"][0]["schema"]["openAPIV3Schema"]["properties"]["spec"]
    spec["required"] = ["protocolType"]
    path.write_text(yaml.safe_dump(resource))
    with pytest.raises(ValueError, match="without protocolType"):
        ASSETS["verify_values"](values, versions, directory)


@pytest.mark.parametrize("values", [None, {}, {"image": None}])
def test_missing_image_values_fail_clearly(bundle, values):
    versions, _, directory = bundle
    with pytest.raises(ValueError, match="image object"):
        ASSETS["verify_values"](deepcopy(values), versions, directory)


def test_invalid_build_metadata_fails_clearly(bundle):
    versions, values, directory = bundle
    values["ackBuild"] = None
    with pytest.raises(ValueError, match="metadata must be an object"):
        ASSETS["verify_values"](values, versions, directory)


@pytest.mark.parametrize("override,has_local,expected", [
    ("custom-values.json", True, "custom-values.json"),
    (None, True, ".state/ack-image-values.json"),
    (None, False, "config/ack-image-values.yaml"),
])
def test_installer_checks_selected_assets_before_cloud_commands(tmp_path, override, has_local, expected):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    installer = scripts / "install-platform.sh"
    installer.write_text((ROOT / "scripts/install-platform.sh").read_text())
    if has_local:
        state = tmp_path / ".state"
        state.mkdir()
        (state / "ack-image-values.json").write_text("{}")
    executable_directory = tmp_path / "bin"
    executable_directory.mkdir()
    arguments_path = tmp_path / "uv-arguments.txt"
    runner = executable_directory / "uv"
    runner.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$TEST_UV_ARGUMENTS"\nexit 9\n')
    runner.chmod(0o755)
    environment = dict(os.environ)
    environment.pop("ACK_IMAGE_VALUES", None)
    environment["PATH"] = f"{executable_directory}:{environment['PATH']}"
    environment["TEST_UV_ARGUMENTS"] = str(arguments_path)
    if override:
        environment["ACK_IMAGE_VALUES"] = override
    result = subprocess.run(["bash", str(installer)], env=environment, capture_output=True, text=True)
    assert result.returncode == 9
    assert arguments_path.read_text().splitlines() == [
        "run", "--project", "agent", "python", "scripts/ack-assets.py", "verify", "--values", expected,
    ]
    assert "environment.sh" not in result.stderr
