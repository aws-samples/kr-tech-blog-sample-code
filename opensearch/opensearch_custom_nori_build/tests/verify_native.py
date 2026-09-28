import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fetch_sources import checksum, versions


def parse_analysis(output):
    rows = []
    lines = output.splitlines()
    if not lines or lines[-1] != "EOS" or lines.count("EOS") != 1:
        raise ValueError("Expected exactly one EOS-terminated MeCab sentence")
    for line in lines[:-1]:
        surface, separator, encoded = line.partition("\t")
        features = encoded.split(",")
        if not separator or not surface or len(features) != 8:
            raise ValueError("Expected surface and eight MeCab-Ko feature columns")
        rows.append({"surface": surface, "features": features})
    if not rows:
        raise ValueError("MeCab returned no morphology")
    return rows


def verify(output):
    if (output / "native-build-pending.json").exists():
        raise RuntimeError("Native build is incomplete. Rebuild the engine before verification.")
    manifest = json.loads((output / "native-build.json").read_text())
    pinned = versions()
    if manifest.get("source_build_executed") is not True or manifest["archive_sha256"] != pinned["MECAB_SHA256"]:
        raise ValueError("A successful build of the pinned MeCab source is required")
    prefix = output / "toolchain"
    for name, expected in manifest["artifacts_sha256"].items():
        if checksum(prefix / name) != expected:
            raise ValueError(f"Installed native executable differs from the build record: {name}")
    binary_dictionaries = {}
    analyses = {}
    cases = ("노을빛무선청소기", "구름결캠핑의자", "노을빛무선청소기에서 먼지를 제거한다", "아버지가 가방에 들어가신다")
    for variant in ("high", "low"):
        dictionary = output / f"native-{variant}"
        for filename in ("sys.dic", "unk.dic", "matrix.bin", "char.bin", "dicrc"):
            path = dictionary / filename
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError(f"Missing compiled native dictionary artifact: {path}")
            binary_dictionaries[f"native-{variant}/{filename}"] = checksum(path)
        analyses[variant] = {}
        for text in cases:
            result = subprocess.run([str(prefix / "bin/mecab"), "-r", str(prefix / "etc/mecabrc"),
                                     "-d", str(dictionary)], input=text + "\n", capture_output=True, text=True, check=True)
            rows = parse_analysis(result.stdout)
            if "".join(row["surface"] for row in rows) != "".join(text.split()):
                raise ValueError("Native morphology did not preserve the input surface")
            analyses[variant][text] = rows
    noun = analyses["low"][cases[0]]
    if len(noun) != 1 or noun[0]["surface"] != cases[0] or noun[0]["features"][0] != "NNP":
        raise ValueError("Low-cost dictionary did not preserve the product as NNP")
    if len(analyses["high"][cases[0]]) <= 1:
        raise ValueError("High-cost control did not select an alternative segmentation")
    compound = analyses["low"][cases[1]]
    if len(compound) != 1 or compound[0]["features"][4] != "Compound" or compound[0]["features"][7] != "구름결/NNP/*+캠핑/NNG/*+의자/NNG/*":
        raise ValueError("Compound morphology was not preserved")
    sentence = analyses["low"][cases[2]]
    if sentence[0]["surface"] != cases[0] or sentence[1]["surface"] != "에서" or sentence[1]["features"][0] != "JKB":
        raise ValueError("Product/particle separation failed")
    if analyses["high"][cases[3]] != analyses["low"][cases[3]]:
        raise ValueError("General-sentence regression failed")
    report = {"status": "PASS", "native_analysis_cases": len(cases) * 2, "source_build_executed": True,
              "mecab_version": manifest["mecab_version"], "binary_dictionaries_sha256": binary_dictionaries,
              "checks": ["native executable hashes", "complete binary dictionaries", "word-cost intervention",
                         "Compound features", "noun/particle separation", "general-sentence regression"],
              "analyses": analyses}
    (output / "native-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"Native MeCab verification PASS: {report['native_analysis_cases']} actual analyses", flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    verify(arguments.output.resolve())
