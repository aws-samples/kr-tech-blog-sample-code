import os
from pathlib import Path
import subprocess
import runpy

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def foundation_workspace(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (tmp_path / ".state").mkdir()
    (scripts / "deploy-foundation.sh").write_text((ROOT / "scripts/deploy-foundation.sh").read_text())
    (scripts / "environment.sh").write_text(
        'export CLUSTER_NAME=eks-ack-agentcore KUBE_CONTEXT=eks-ack-agentcore CNI_BOOTSTRAP=false AWS_REGION=us-east-1 AWS_PROFILE=default\n'
    )
    binaries = tmp_path / "bin"
    binaries.mkdir()
    commands = {
        "aws": '''#!/bin/sh
if [ "$2" = describe-cluster ]; then
  if [ "$TEST_CLUSTER_STATE" = missing ]; then
    printf 'ResourceNotFoundException\\n' >&2
    exit 254
  elif [ "$TEST_CLUSTER_STATE" = denied ]; then
    printf 'AccessDeniedException\\n' >&2
    exit 254
  elif [ "$TEST_CLUSTER_STATE" = foreign ]; then
    printf '{"cluster":{"tags":{"Project":"other-project"}}}\\n'
  else
    printf '{"cluster":{"tags":{"Project":"eks-ack-agentcore"}}}\\n'
  fi
fi
''',
        "npx": '''#!/bin/sh
printf '%s %s\\n' "$CNI_BOOTSTRAP" "$*" >> "$TEST_CALLS"
if [ "$2" = deploy ] && [ "$CNI_BOOTSTRAP" = false ] && [ "$TEST_FAIL_FINAL" = true ]; then
  exit 9
fi
''',
        "npm": "#!/bin/sh\nexit 0\n",
        "kubectl": "#!/bin/sh\nexit 0\n",
    }
    for name, content in commands.items():
        executable = binaries / name
        executable.write_text(content)
        executable.chmod(0o755)
    environment = dict(os.environ)
    environment["PATH"] = f"{binaries}:{environment['PATH']}"
    environment["TEST_CALLS"] = str(tmp_path / "calls.txt")
    environment["TEST_FAIL_FINAL"] = "false"
    return tmp_path, environment


def run_foundation(workspace, state):
    directory, environment = workspace
    environment["TEST_CLUSTER_STATE"] = state
    return subprocess.run(
        ["bash", str(directory / "scripts/deploy-foundation.sh")],
        env=environment, capture_output=True, text=True,
    )


def test_fresh_cluster_resets_stale_cni_state_and_imports_retained_resources(foundation_workspace):
    directory, _ = foundation_workspace
    (directory / ".state/cni-migrated").touch()
    result = run_foundation(foundation_workspace, "missing")
    assert result.returncode == 0, result.stderr
    commands = (directory / "calls.txt").read_text().splitlines()
    deploys = [command for command in commands if "cdk deploy" in command]
    assert deploys[0].startswith("true cdk deploy --import-existing-resources")
    assert deploys[1].startswith("false cdk deploy")


def test_existing_cluster_preserves_migrated_cni_configuration(foundation_workspace):
    directory, _ = foundation_workspace
    result = run_foundation(foundation_workspace, "present")
    assert result.returncode == 0, result.stderr
    assert all(command.startswith("false ") for command in (directory / "calls.txt").read_text().splitlines())


@pytest.mark.parametrize("state", ["denied", "foreign"])
def test_cluster_lookup_failure_does_not_start_deployment(foundation_workspace, state):
    directory, _ = foundation_workspace
    result = run_foundation(foundation_workspace, state)
    assert result.returncode != 0
    assert not (directory / "calls.txt").exists()


def test_cni_migration_marker_is_written_only_after_final_deploy(foundation_workspace):
    directory, environment = foundation_workspace
    environment["TEST_FAIL_FINAL"] = "true"
    result = run_foundation(foundation_workspace, "missing")
    assert result.returncode == 9
    assert not (directory / ".state/cni-migrated").exists()


def test_destroy_requires_explicit_confirmation():
    environment = dict(os.environ)
    environment.pop("CONFIRM_DESTROY", None)
    result = subprocess.run(["bash", str(ROOT / "scripts/destroy.sh")], env=environment, capture_output=True, text=True)
    assert result.returncode == 1
    assert "CONFIRM_DESTROY=eks-ack-agentcore" in result.stderr


def test_validation_values_override_keeps_git_chart_and_marks_non_git_release():
    renderer = runpy.run_path(str(ROOT / "scripts/render-application.py"))["render_application"]
    application = {
        "metadata": {"name": "devops-agent"},
        "spec": {"source": {"repoURL": "ssh://git@example.test/demo.git", "helm": {
            "valueFiles": ["../../gitops/environments/dev.yaml"],
        }}},
    }
    result = renderer(application, {"gateway": {"enabled": False}, "runtime": {"release": "v1"}})
    assert result["spec"]["source"]["repoURL"] == "ssh://git@example.test/demo.git"
    assert result["spec"]["source"]["helm"]["valuesObject"]["gateway"]["enabled"] is False
    assert result["metadata"]["annotations"]["demo.agentcore/values-source"] == "local-validation-override"


def test_destroy_rejects_unowned_resources_before_deletion(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (tmp_path / ".state").mkdir()
    (scripts / "destroy.sh").write_text((ROOT / "scripts/destroy.sh").read_text())
    (scripts / "environment.sh").write_text('export CLUSTER_NAME=eks-ack-agentcore KUBE_CONTEXT=eks-ack-agentcore\n')
    binaries = tmp_path / "bin"
    binaries.mkdir()
    executables = {
        "aws": '''#!/bin/sh
if [ "$1" = cloudformation ]; then
  printf '{"Stacks":[{"Tags":[{"Key":"Project","Value":"eks-ack-agentcore"}]}]}\\n'
else
  printf '{"cluster":{"tags":{"Project":"eks-ack-agentcore","aws:cloudformation:stack-name":"EksAckAgentCore"}}}\\n'
fi
''',
        "kubectl": '''#!/bin/sh
printf '%s\\n' "$*" >> "$TEST_CALLS"
printf '{"items":[{"metadata":{"name":"unrelated","annotations":{}}}]}\\n'
''',
    }
    for name, content in executables.items():
        executable = binaries / name
        executable.write_text(content)
        executable.chmod(0o755)
    environment = dict(os.environ)
    environment["CONFIRM_DESTROY"] = "eks-ack-agentcore"
    environment["PATH"] = f"{binaries}:{environment['PATH']}"
    environment["TEST_CALLS"] = str(tmp_path / "calls.txt")
    result = subprocess.run(["bash", str(scripts / "destroy.sh")], env=environment, capture_output=True, text=True)
    assert result.returncode == 1
    assert "not owned by devops-agent" in result.stderr
    assert "delete" not in (tmp_path / "calls.txt").read_text()
