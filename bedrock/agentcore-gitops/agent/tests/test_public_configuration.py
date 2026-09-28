from pathlib import Path
import os
import runpy
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
VALIDATE = runpy.run_path(str(ROOT / "scripts/validate-gitops.py"))["validate_repository"]


def configuration(path="bedrock/agentcore-gitops/charts/agentcore-agent"):
    source = {"repoURL": "ssh://git@github.com/example/sample.git", "path": path,
              "helm": {"valueFiles": ["../../gitops/environments/dev.yaml"]}}
    return {"spec": {"source": source}}, {"spec": {"sourceRepos": [source["repoURL"]]}}


def test_monorepo_chart_path_and_repository_match():
    application, project = configuration()
    assert VALIDATE(application, project, "example/sample", "bedrock/agentcore-gitops/charts/agentcore-agent") == "example/sample"


@pytest.mark.parametrize("change", ["repository", "project", "path", "values"])
def test_mismatched_gitops_configuration_is_rejected(change):
    application, project = configuration()
    requested = "example/sample"
    if change == "repository":
        requested = "different/repository"
    elif change == "project":
        project["spec"]["sourceRepos"] = ["*"]
    elif change == "path":
        application["spec"]["source"]["path"] = "charts/agentcore-agent"
    else:
        application["spec"]["source"]["helm"]["valueFiles"] = ["../../wrong.yaml"]
    with pytest.raises(ValueError):
        VALIDATE(application, project, requested, "bedrock/agentcore-gitops/charts/agentcore-agent")


def test_public_repository_placeholder_must_be_replaced():
    application, project = configuration()
    application["spec"]["source"]["repoURL"] = "ssh://git@github.com/YOUR_GITHUB_ORG/sample.git"
    project["spec"]["sourceRepos"] = [application["spec"]["source"]["repoURL"]]
    with pytest.raises(ValueError, match="same repository"):
        VALIDATE(application, project, "YOUR_GITHUB_ORG/sample", "bedrock/agentcore-gitops/charts/agentcore-agent")


def test_environment_stops_when_aws_identity_lookup_fails(tmp_path):
    binary = tmp_path / "aws"
    binary.write_text("#!/bin/sh\nexit 17\n")
    binary.chmod(0o755)
    environment = dict(os.environ)
    environment["PATH"] = f"{tmp_path}:{environment['PATH']}"
    result = subprocess.run(["bash", "-c", f'source "{ROOT / "scripts/environment.sh"}"; touch should-not-exist'], cwd=tmp_path, env=environment)
    assert result.returncode == 17
    assert not (tmp_path / "should-not-exist").exists()
