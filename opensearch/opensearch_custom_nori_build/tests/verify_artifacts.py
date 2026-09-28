import hashlib
import json
import sys
import zipfile
from pathlib import Path


output = Path(sys.argv[1])
records = {variant: [json.loads(line) for line in (output / f"{variant}.jsonl").read_text().splitlines()]
           for variant in ("baseline", "high", "low", "user")}


def result(variant, text, mode):
    return next(row for row in records[variant] if row["text"] == text and row["mode"] == mode)


def terms(variant, text, mode):
    return [token["token"] for token in result(variant, text, mode)["tokens"]]


product = "노을빛무선청소기"
assert terms("baseline", product, "none") != [product]
assert terms("high", product, "none") != [product]
assert terms("low", product, "none") == [product]
assert terms("low", "구름결캠핑의자", "none") == ["구름결캠핑의자"]
assert terms("low", "구름결캠핑의자", "discard") == ["구름결", "캠핑", "의자"]
assert terms("low", "구름결캠핑의자", "mixed") == ["구름결캠핑의자", "구름결", "캠핑", "의자"]
assert result("low", "구름결캠핑의자", "mixed")["tokens"][0]["positionLength"] == 3
assert terms("user", "초록별접이식선반", "discard") == ["초록별", "접이식", "선반"]
assert terms("user", "초록별접이식선반", "none") == ["초록별접이식선반"]
for mode in ("none", "discard", "mixed"):
    text = "아버지가 가방에 들어가신다"
    assert result("baseline", text, mode)["tokens"] == result("low", text, mode)["tokens"]
plugin = output / "plugin/distributions/analysis-nori-commerce-1.0.0-os-3.5.0.zip"
with zipfile.ZipFile(plugin) as archive:
    assert "plugin-descriptor.properties" in archive.namelist()
    descriptor = archive.read("plugin-descriptor.properties").decode()
    assert "opensearch.version=3.5.0" in descriptor and "name=analysis-nori-commerce" in descriptor
    assert not any(name.endswith((".dylib", ".so", "sys.dic", "matrix.bin")) for name in archive.namelist())
jar = output / "plugin/libs/analysis-nori-commerce-1.0.0.jar"
with zipfile.ZipFile(jar) as archive:
    names = archive.namelist()
    assert not any(name.startswith("org/apache/lucene/analysis/ko/") for name in names)
    assert any(name.startswith("example/opensearch/nori/internal/ko/dict/") and name.endswith(".dat") for name in names)
    assert not any(name.startswith("META-INF/services/org.apache.lucene.analysis.") for name in names)
(plugin.with_suffix(".zip.sha256")).write_text(hashlib.sha256(plugin.read_bytes()).hexdigest() + "  " + plugin.name + "\n")
report = {"status": "PASS", "tokenizer_cases": sum(map(len, records.values())),
          "checks": ["same-entry word-cost intervention", "compound none/discard/mixed", "user dictionary segmentation",
                     "unchanged general-sentence regression", "relocated classes/resources", "plugin descriptor and ZIP layout"],
          "opensearch_http_test": False, "aws_package_validation": False, "aws_domain_association": False,
          "plugin": str(plugin)}
(output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(report, ensure_ascii=False, indent=2))
