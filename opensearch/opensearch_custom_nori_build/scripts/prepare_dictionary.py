import argparse
import csv
import json
import shutil
import tarfile
import tempfile
from pathlib import Path

from fetch_sources import ROOT, checksum, versions


def validate_rows(rows, left_ids, right_ids, existing):
    surfaces = set()
    for row in rows:
        if len(row) != 12 or not -32768 <= int(row[3]) <= 32767:
            raise ValueError("Expected 12-column CSV with a signed 16-bit word cost")
        surface = row[0]
        if not surface or any(character.isspace() for character in surface) or surface in surfaces or surface in existing:
            raise ValueError(f"Duplicate, existing, or invalid sample surface: {surface}")
        surfaces.add(surface)
        if row[4:7] != ["NNP", "*", "T" if "가" <= surface[-1] <= "힣" and (ord(surface[-1]) - 0xAC00) % 28 else "F"]:
            raise ValueError("This example requires NNP, unspecified semantics, and the correct surface coda")
        if left_ids.get(row[1]) != "NNP,*,*,*,*,*,*,*" or right_ids.get(row[2]) != f"NNP,*,{row[6]},*,*,*,*,*":
            raise ValueError("Context IDs do not match the pinned dictionary/POS/coda")
        if row[8] == "Compound":
            parts = [part.split("/") for part in row[11].split("+")]
            if any(len(part) != 3 or part[1] not in {"NNP", "NNG"} or part[2] != "*" for part in parts):
                raise ValueError("Expected compound parts surface/NNP-or-NNG/*")
            if "".join(part[0] for part in parts) != surface or row[9:11] != ["*", "*"]:
                raise ValueError("Compound parts must reconstruct the surface")
        elif row[8:] != ["*", "*", "*", "*"]:
            raise ValueError("Use a simple noun or Compound in this example")


def validate_variants(high_rows, low_rows):
    if not high_rows or len(high_rows) != len(low_rows):
        raise ValueError("High and low dictionaries must contain the same nonempty entries")
    for high, low in zip(high_rows, low_rows, strict=True):
        if high[:3] + high[4:] != low[:3] + low[4:] or int(high[3]) <= int(low[3]):
            raise ValueError("High and low experiments must differ only in decreasing word cost")


def prepare(output):
    pinned = versions()
    archive = ROOT / ".cache/downloads" / f"mecab-ko-dic-{pinned['MECAB_DIC_VERSION']}.tar.gz"
    if checksum(archive) != pinned["MECAB_DIC_SHA256"]:
        raise ValueError("Dictionary archive checksum mismatch")
    inputs = {variant: ROOT / "dictionaries" / f"{variant}.csv" for variant in ("high", "low")}
    expected = {"versions": pinned, "inputs": {variant: checksum(path) for variant, path in inputs.items()}}
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / "sample-manifest.json"
    if manifest.exists():
        if json.loads(manifest.read_text()) != expected:
            raise ValueError("Inputs changed: use a fresh NORI_BUILD_DIR")
        for variant, source in inputs.items():
            copied = output / f"dictionary-{variant}" / "commerce.csv"
            if copied.read_bytes() != source.read_bytes():
                raise ValueError("Working dictionary changed: preserving edits; use a fresh NORI_BUILD_DIR")
        print("Using unchanged isolated sample dictionaries")
        return
    destinations = [output / f"dictionary-{variant}" for variant in inputs]
    if any(path.exists() for path in destinations):
        raise FileExistsError("Incomplete dictionary preparation: use a fresh NORI_BUILD_DIR")
    with tempfile.TemporaryDirectory(prefix="dictionary-", dir=output) as temporary:
        staging = Path(temporary)
        with tarfile.open(archive) as package:
            package.extractall(staging, filter="data")
        reference = staging / f"mecab-ko-dic-{pinned['MECAB_DIC_VERSION']}"
        left_ids = dict(line.split(" ", 1) for line in (reference / "left-id.def").read_text().splitlines())
        right_ids = dict(line.split(" ", 1) for line in (reference / "right-id.def").read_text().splitlines())
        existing = set()
        for source in reference.glob("*.csv"):
            with source.open(encoding="utf-8") as stream:
                existing.update(row[0] for row in csv.reader(stream) if row)
        variants = {}
        for variant, source in inputs.items():
            with source.open(encoding="utf-8") as stream:
                variants[variant] = list(csv.reader(stream))
            validate_rows(variants[variant], left_ids, right_ids, existing)
        validate_variants(variants["high"], variants["low"])
        for variant, source in inputs.items():
            destination = output / f"dictionary-{variant}"
            shutil.copytree(reference, destination)
            shutil.copy2(source, destination / "commerce.csv")
    manifest.write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n")
    print("Prepared independent high/low dictionaries; only word cost differs")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    prepare(arguments.output.resolve())


if __name__ == "__main__":
    main()
