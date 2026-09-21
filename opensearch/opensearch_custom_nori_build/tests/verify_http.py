import argparse
import json
import uuid
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description="Validate the blog example on a loopback-only local OpenSearch node")
    parser.add_argument("output", type=Path)
    parser.add_argument("--endpoint", default="http://127.0.0.1:19235")
    arguments = parser.parse_args()
    endpoint = arguments.endpoint.rstrip("/")
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.path:
        raise ValueError("This unauthenticated test is restricted to a local loopback endpoint")
    output = arguments.output / "http-verification"
    output.mkdir(parents=True, exist_ok=False)

    def request(method, path, payload=None):
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        with urlopen(Request(endpoint + path, data=body, method=method, headers={"Content-Type": "application/json"}), timeout=30) as response:
            return json.load(response)

    def save(name, value):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    version = request("GET", "/")
    assert version["version"]["number"] == "3.5.0" and version["version"]["lucene_version"] == "10.3.2"
    save("version.json", version)
    plugins = request("GET", "/_cat/plugins?format=json")
    assert {"analysis-nori", "analysis-nori-commerce"} <= {plugin["component"] for plugin in plugins}
    save("plugins.json", plugins)
    count = 0
    for variant, tokenizer in (("baseline", "nori_tokenizer"), ("low", "nori_custom_tokenizer"), ("user", "nori_tokenizer")):
        for line in (arguments.output / f"{variant}.jsonl").read_text().splitlines():
            expected = json.loads(line)
            configuration = {"type": tokenizer, "decompound_mode": expected["mode"]}
            if variant == "user":
                configuration["user_dictionary_rules"] = ["초록별접이식선반 초록별 접이식 선반"]
            payload = {"tokenizer": configuration, "text": expected["text"], "explain": True}
            response = request("POST", "/_analyze", payload)
            actual = response["detail"]["tokenizer"]["tokens"]
            normalized = [{"token": token["token"], "pos": token["leftPOS"].split("(")[0],
                           "start": token["start_offset"], "end": token["end_offset"],
                           "position": token["position"], "positionLength": token.get("positionLength", 1)} for token in actual]
            assert normalized == expected["tokens"], (variant, expected["text"], expected["mode"], normalized)
            save(f"analyze-{count:03d}.json", {"request": payload, "response": response})
            count += 1
    index = "commerce-blog-check-" + uuid.uuid4().hex[:12]
    created = False
    try:
        settings = json.loads((Path(__file__).resolve().parents[1] / "samples/index-settings.json").read_text())
        request("PUT", "/" + index, settings)
        created = True
        cases = [
            ("stock_none_analyzer", "노을빛무선청소기", ["노을빛", "무선", "청소기"]),
            ("commerce_none_analyzer", "노을빛무선청소기", ["노을빛무선청소기"]),
            ("commerce_discard_analyzer", "구름결캠핑의자", ["구름결", "캠핑", "의자"]),
            ("commerce_mixed_analyzer", "구름결캠핑의자", ["구름결캠핑의자", "구름결", "캠핑", "의자"]),
            ("commerce_user_analyzer", "초록별접이식선반을 설치했다", ["초록별접이식선반", "초록별", "접이식", "선반", "설치"]),
        ]
        for analyzer, text, expected in cases:
            payload = {"analyzer": analyzer, "text": text}
            response = request("POST", "/" + index + "/_analyze", payload)
            assert [token["token"] for token in response["tokens"]] == expected
            save(f"index-{analyzer}.json", {"request": payload, "response": response})
            count += 1
        for source, expected in (("nori", ["구름", "결", "캠핑", "의자", "구매"]),
                                 ("nori_custom", ["구름결", "캠핑", "의자", "구매"])):
            response = request("POST", "/_analyze", {"analyzer": source, "text": "구름결캠핑의자를 구매했다"})
            assert [token["token"] for token in response["tokens"]] == expected
            save(f"registered-{source}.json", response)
            count += 1
    finally:
        if created:
            request("DELETE", "/" + index)
    report = {"status": "PASS", "successful_analyze_requests": count, "stock_and_custom_plugins_loaded": True,
              "index_analyzers_and_matching_custom_filters": True, "temporary_test_index_deleted": True,
              "aws_package_validation": False, "aws_domain_association": False}
    save("report.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
