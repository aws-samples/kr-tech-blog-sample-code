import argparse
import json
from pathlib import Path

import yaml


def render_application(application: dict, values: dict) -> dict:
    application["spec"]["source"]["helm"]["valuesObject"] = values
    application["metadata"].setdefault("annotations", {})["demo.agentcore/values-source"] = "local-validation-override"
    return application


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--application", type=Path, default=Path("gitops/application.yaml"))
    parser.add_argument("--values", type=Path, required=True)
    args = parser.parse_args()
    application = yaml.safe_load(args.application.read_text())
    values = yaml.safe_load(args.values.read_text())
    if not isinstance(values, dict):
        parser.error("values must be a YAML mapping")
    print(json.dumps(render_application(application, values)))


if __name__ == "__main__":
    main()
