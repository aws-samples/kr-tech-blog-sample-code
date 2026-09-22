import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

import yaml


def validate_repository(application: dict, project: dict, requested: str, expected_path: str) -> str:
    source = application["spec"]["source"]
    match = re.fullmatch(r"ssh://git@github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)\.git", source["repoURL"])
    if not match:
        raise ValueError("Use a GitHub SSH repoURL of the form ssh://git@github.com/OWNER/REPOSITORY.git")
    repository = match.group(1)
    if "YOUR_" in repository or repository != requested:
        raise ValueError("Set GITHUB_REPOSITORY and both GitOps manifests to the same repository you control")
    if project["spec"]["sourceRepos"] != [source["repoURL"]]:
        raise ValueError("AppProject sourceRepos must match the Application repoURL exactly")
    if source["path"] != expected_path or ".." in PurePosixPath(source["path"]).parts:
        raise ValueError(f"Application source.path must be {expected_path}")
    if source["helm"]["valueFiles"] != ["../../gitops/environments/dev.yaml"]:
        raise ValueError("Unexpected environment values path")
    return repository


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    try:
        requested = os.environ.get("GITHUB_REPOSITORY", "")
        if not requested:
            raise ValueError("Set GITHUB_REPOSITORY=YOUR_GITHUB_ORG/YOUR_REPOSITORY before configuring GitOps")
        git_root = Path(subprocess.check_output(["git", "-C", str(root), "rev-parse", "--show-toplevel"], text=True).strip()).resolve()
        expected_path = (root / "charts/agentcore-agent").relative_to(git_root).as_posix()
        application = yaml.safe_load((root / "gitops/application.yaml").read_text())
        project = yaml.safe_load((root / "gitops/project.yaml").read_text())
        print(validate_repository(application, project, requested, expected_path))
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        sys.exit(f"GitOps configuration is not ready: {error}")


if __name__ == "__main__":
    main()
