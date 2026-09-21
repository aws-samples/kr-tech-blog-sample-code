import copy
import csv
import io
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_sources
import prepare_dictionary


class DictionaryTests(unittest.TestCase):
    def setUp(self):
        with (ROOT / "dictionaries/low.csv").open() as source:
            self.low = list(csv.reader(source))
        with (ROOT / "dictionaries/high.csv").open() as source:
            self.high = list(csv.reader(source))
        self.left = {"1786": "NNP,*,*,*,*,*,*,*"}
        self.right = {"3545": "NNP,*,F,*,*,*,*,*"}

    def validate(self, rows):
        prepare_dictionary.validate_rows(rows, self.left, self.right, set())

    def test_valid_cost_only_variants(self):
        self.validate(self.low)
        self.validate(self.high)
        prepare_dictionary.validate_variants(self.high, self.low)

    def test_cost_out_of_range(self):
        rows = copy.deepcopy(self.low)
        rows[0][3] = "-32769"
        with self.assertRaises(ValueError):
            self.validate(rows)

    def test_duplicate_or_existing_surface(self):
        with self.assertRaises(ValueError):
            self.validate(self.low + self.low[:1])
        with self.assertRaises(ValueError):
            prepare_dictionary.validate_rows(self.low, self.left, self.right, {self.low[0][0]})

    def test_incorrect_coda_or_context(self):
        for column, value in ((6, "T"), (1, "9999"), (2, "9999")):
            rows = copy.deepcopy(self.low)
            rows[0][column] = value
            with self.assertRaises(ValueError):
                self.validate(rows)

    def test_invalid_compound(self):
        for value in ("구름/NNP/*+캠핑/NNG/*+의자/NNG/*", "구름결/XYZ/*+캠핑/NNG/*+의자/NNG/*"):
            rows = copy.deepcopy(self.low)
            rows[1][11] = value
            with self.assertRaises(ValueError):
                self.validate(rows)

    def test_variants_must_differ_only_in_cost(self):
        rows = copy.deepcopy(self.low)
        rows[0][7] = "different-reading"
        with self.assertRaises(ValueError):
            prepare_dictionary.validate_variants(self.high, rows)
        with self.assertRaises(ValueError):
            prepare_dictionary.validate_variants(self.low, self.low)
        with self.assertRaises(ValueError):
            prepare_dictionary.validate_variants(self.high, self.low[:1])

    def test_working_csv_edit_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "dictionaries"
            inputs.mkdir()
            for variant in ("high", "low"):
                (inputs / f"{variant}.csv").write_bytes((ROOT / "dictionaries" / f"{variant}.csv").read_bytes())
            cache = root / ".cache/downloads"
            cache.mkdir(parents=True)
            archive = cache / "mecab-ko-dic-fixture.tar.gz"
            with tarfile.open(archive, "w:gz") as package:
                for name, content in {"left-id.def": "1786 NNP,*,*,*,*,*,*,*\n", "right-id.def": "3545 NNP,*,F,*,*,*,*,*\n"}.items():
                    entry = tarfile.TarInfo("mecab-ko-dic-fixture/" + name)
                    payload = content.encode()
                    entry.size = len(payload)
                    package.addfile(entry, io.BytesIO(payload))
            pinned = {"MECAB_DIC_VERSION": "fixture", "MECAB_DIC_SHA256": fetch_sources.checksum(archive)}
            output = root / "build"
            with patch.object(prepare_dictionary, "ROOT", root), patch.object(prepare_dictionary, "versions", return_value=pinned):
                prepare_dictionary.prepare(output)
                prepare_dictionary.prepare(output)
                changed = output / "dictionary-low/commerce.csv"
                changed.write_text("user changes\n")
                with self.assertRaisesRegex(ValueError, "Working dictionary changed"):
                    prepare_dictionary.prepare(output)
                self.assertEqual(changed.read_text(), "user changes\n")


class SourceSafetyTests(unittest.TestCase):
    def test_corrupted_download_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "source.tar.gz"
            target.write_bytes(b"corrupted")
            with patch.object(fetch_sources.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    fetch_sources.download("https://example.invalid/source", target, "0" * 64)
            run.assert_not_called()
            self.assertEqual(target.read_bytes(), b"corrupted")

    def test_tar_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "source.tar.gz"
            with tarfile.open(archive, "w:gz") as package:
                entry = tarfile.TarInfo("../escaped")
                entry.size = 1
                package.addfile(entry, io.BytesIO(b"x"))
            with self.assertRaises(tarfile.FilterError):
                fetch_sources.extract(archive, root / "source", fetch_sources.checksum(archive))
            self.assertFalse((root / "escaped").exists())

    def test_checkout_revision_and_dirty_tree_guards(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "remote", "add", "origin", "https://example.invalid/repo.git"], check=True)
            (root / "source.txt").write_text("original\n")
            subprocess.run(["git", "-C", str(root), "add", "source.txt"], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                            "-c", "commit.gpgsign=false", "commit", "-qm", "Fixture"], check=True)
            revision = fetch_sources.git_output(root, "rev-parse", "HEAD")
            fetch_sources.verify_checkout(root, "https://example.invalid/repo.git", revision)
            with self.assertRaisesRegex(ValueError, "revision"):
                fetch_sources.verify_checkout(root, "https://example.invalid/repo.git", "0" * 40)
            (root / "source.txt").write_text("user changes\n")
            with self.assertRaisesRegex(ValueError, "Tracked source changes"):
                fetch_sources.verify_checkout(root, "https://example.invalid/repo.git", revision)
            self.assertEqual((root / "source.txt").read_text(), "user changes\n")


if __name__ == "__main__":
    unittest.main()
