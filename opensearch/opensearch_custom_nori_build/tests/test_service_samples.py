import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def requests_for(variant):
    text = (ROOT / f"samples/analyze-{variant}.http").read_text()
    requests = []
    for block in text.split("\n\n"):
        lines = [line for line in block.splitlines() if line and not line.startswith("#")]
        if not lines:
            continue
        method, path = lines[0].split()
        payload = json.loads("\n".join(lines[1:])) if len(lines) > 1 else None
        requests.append((method, path, payload))
    return requests


def normalize_custom(value):
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return (serialized.replace("nori_custom_", "nori_")
            .replace('"nori_custom"', '"nori"')
            .replace("commerce-nori-custom-lab-v1", "commerce-nori-stock-lab-v1"))


class ServiceSamplesTests(unittest.TestCase):
    def test_index_settings_differ_only_in_plugin_components(self):
        stock = json.loads((ROOT / "samples/index-settings-stock.json").read_text())
        custom = json.loads((ROOT / "samples/index-settings-custom.json").read_text())
        self.assertEqual(normalize_custom(custom), normalize_custom(stock))
        self.assertEqual(stock["settings"]["number_of_replicas"], 1)

    def test_each_domain_requires_only_its_own_components(self):
        for variant, prefix in (("stock", "nori_"), ("custom", "nori_custom_")):
            settings = json.loads((ROOT / f"samples/index-settings-{variant}.json").read_text())
            analysis = settings["settings"]["analysis"]
            for tokenizer in analysis["tokenizer"].values():
                self.assertEqual(tokenizer["type"], prefix + "tokenizer")
            for analyzer in analysis["analyzer"].values():
                self.assertIn(analyzer["tokenizer"], analysis["tokenizer"])
                for token_filter in analyzer.get("filter", []):
                    self.assertIn(token_filter, {prefix + "part_of_speech", prefix + "readingform", "lowercase"})

    def test_paired_requests_keep_comparison_conditions_equal(self):
        stock = requests_for("stock")
        custom = requests_for("custom")
        self.assertEqual(len(stock), 10)
        self.assertEqual(normalize_custom(custom), normalize_custom(stock))
        self.assertEqual(sum(path == "/_analyze" for method, path, payload in stock), 6)
        for variant, requests in (("stock", stock), ("custom", custom)):
            for method, path, payload in requests:
                self.assertIn(method, {"GET", "POST"})
                if path.startswith("/commerce-"):
                    self.assertTrue(path.startswith(f"/commerce-nori-{variant}-lab-v1/"))

    def test_user_dictionary_matches_build_input(self):
        rules = (ROOT / "dictionaries/user_dictionary.txt").read_text().splitlines()
        for variant in ("stock", "custom"):
            settings = json.loads((ROOT / f"samples/index-settings-{variant}.json").read_text())
            tokenizer = settings["settings"]["analysis"]["tokenizer"]["commerce_user_mixed"]
            self.assertEqual(tokenizer["user_dictionary_rules"], rules)
            user_requests = [payload for method, path, payload in requests_for(variant)
                             if isinstance(payload, dict) and isinstance(payload.get("tokenizer"), dict)
                             and "user_dictionary_rules" in payload["tokenizer"]]
            self.assertEqual(len(user_requests), 1)
            self.assertEqual(user_requests[0]["tokenizer"]["user_dictionary_rules"], rules)


if __name__ == "__main__":
    unittest.main()
