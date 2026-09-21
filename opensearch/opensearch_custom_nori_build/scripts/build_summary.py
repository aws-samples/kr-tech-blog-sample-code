import argparse
import json
from pathlib import Path


def summarize(output, target):
    expected = ["native-build.json", "native-verification.json"]
    if target == "all":
        expected.append("verification.json")
    reports = {name: json.loads((output / name).read_text()) for name in expected}
    if any(report["status"] != "PASS" for report in reports.values()):
        raise ValueError("Cannot summarize an incomplete or failing build")
    manifest = reports["native-build.json"]
    result = {
        "status": "PASS", "target": target,
        "mecab_built_from_source": manifest["source_build_executed"],
        "native_tools": [str(output / "toolchain" / name) for name in manifest["artifacts_sha256"]],
        "native_dictionaries": [str(output / f"native-{variant}") for variant in ("high", "low")],
        "native_analysis_cases": reports["native-verification.json"]["native_analysis_cases"],
        "nori_tokenizer_cases": reports.get("verification.json", {}).get("tokenizer_cases", 0),
        "plugin_zip": reports.get("verification.json", {}).get("plugin"),
        "aws_resources_changed": False,
    }
    (output / "build-summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("target", choices=("all", "mecab"))
    arguments = parser.parse_args()
    summarize(arguments.output.resolve(), arguments.target)
