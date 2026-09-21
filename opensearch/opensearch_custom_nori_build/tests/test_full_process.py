import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import build_native
import build_summary
import fetch_sources
import verify_native


class NativeProcessTests(unittest.TestCase):
    def fixture(self, root):
        cache = root / ".cache/downloads"
        cache.mkdir(parents=True)
        archive = cache / "mecab-fixture.tar.gz"
        with tarfile.open(archive, "w:gz") as package:
            entry = tarfile.TarInfo("mecab-fixture/configure")
            payload = b"fixture configure\n"
            entry.size = len(payload)
            package.addfile(entry, io.BytesIO(payload))
        automake = root / "automake"
        automake.mkdir()
        for filename in ("config.guess", "config.sub"):
            (automake / filename).write_text("fixture\n")
        output = root / "build"
        output.mkdir()
        for relative in build_native.TOOL_PATHS:
            executable = output / "toolchain" / relative
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.write_text("already installed fixture\n")
            executable.chmod(0o755)
        return output, automake, {"MECAB_VERSION": "fixture", "MECAB_SHA256": fetch_sources.checksum(archive)}

    def test_existing_native_binary_does_not_skip_source_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output, automake, pinned = self.fixture(root)
            with patch.object(build_native, "ROOT", root), patch.object(build_native, "versions", return_value=pinned), \
                    patch.object(build_native.subprocess, "run") as run, \
                    patch.object(build_native.subprocess, "check_output", side_effect=[str(automake), "mecab fixture"] * 2), \
                    contextlib.redirect_stdout(io.StringIO()):
                first = build_native.build_native(output, 2)
                second = build_native.build_native(output, 2)
            self.assertEqual(run.call_count, 6)
            self.assertEqual(run.call_args_list[1].args[0], ["make", "-j2", "CXXFLAGS=-O2 -std=c++11"])
            self.assertEqual(run.call_args_list[2].args[0], ["make", "install"])
            self.assertNotEqual(first["source_directory"], second["source_directory"])
            self.assertTrue(first["source_build_executed"])
            self.assertFalse(first["reused_prebuilt_engine"])
            self.assertFalse((output / "native-build-pending.json").exists())

    def test_native_failure_leaves_incomplete_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output, automake, pinned = self.fixture(root)
            with patch.object(build_native, "ROOT", root), patch.object(build_native, "versions", return_value=pinned), \
                    patch.object(build_native.subprocess, "check_output", return_value=str(automake)), \
                    patch.object(build_native.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "configure")), \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(subprocess.CalledProcessError):
                    build_native.build_native(output, 2)
            self.assertTrue((output / "native-build-pending.json").exists())
            self.assertFalse((output / "native-build.json").exists())
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                verify_native.verify(output)

    def test_bad_archive_is_rejected_before_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output, automake, pinned = self.fixture(root)
            pinned["MECAB_SHA256"] = "0" * 64
            with patch.object(build_native, "ROOT", root), patch.object(build_native, "versions", return_value=pinned), \
                    patch.object(build_native.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    build_native.build_native(output, 2)
            run.assert_not_called()

    def test_native_output_parser(self):
        rows = verify_native.parse_analysis("상품\tNNG,*,T,상품,*,*,*,*\nEOS\n")
        self.assertEqual(rows[0]["surface"], "상품")
        for invalid in ("", "EOS\n", "상품\tNNG\nEOS\n", "상품\tNNG,*,T,상품,*,*,*,*\n", "EOS\nEOS\n"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                verify_native.parse_analysis(invalid)

    def test_full_summary_requires_native_and_nori_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            native = {"status": "PASS", "source_build_executed": True, "artifacts_sha256": {"bin/mecab": "fixture"}}
            (output / "native-build.json").write_text(json.dumps(native))
            (output / "native-verification.json").write_text(json.dumps({"status": "PASS", "native_analysis_cases": 8}))
            with self.assertRaises(FileNotFoundError):
                build_summary.summarize(output, "all")
            self.assertFalse((output / "build-summary.json").exists())
            with contextlib.redirect_stdout(io.StringIO()):
                build_summary.summarize(output, "mecab")
            summary = json.loads((output / "build-summary.json").read_text())
            self.assertTrue(summary["mecab_built_from_source"])
            self.assertEqual(summary["native_analysis_cases"], 8)
            self.assertIsNone(summary["plugin_zip"])


class EntryPointTests(unittest.TestCase):
    def test_help_and_invalid_option_do_not_start_build(self):
        result = subprocess.run(["bash", str(ROOT / "build-all.sh"), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("--mecab-only", result.stdout)
        result = subprocess.run(["bash", str(ROOT / "build-all.sh"), "--unknown"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("[1]", result.stdout)

    def test_entrypoint_executes_dependency_and_build_stages_in_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copy2(ROOT / "build-all.sh", root / "build-all.sh")
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "bootstrap.sh").write_text('bootstrap() { printf "BOOTSTRAP=%s\\n" "$1"; }\n')
            (scripts / "env.sh").write_text('export NORI_BUILD_DIR="$ROOT/output"\n')
            (scripts / "fetch-sources.sh").write_text('echo FETCH\n')
            (scripts / "doctor.sh").write_text('echo DOCTOR\n')
            (scripts / "build.sh").write_text('printf "TARGET=%s\\n" "$1"\n')
            for options, target in ((["--install-deps"], "all"), (["--install-deps", "--mecab-only"], "mecab")):
                result = subprocess.run(["bash", str(root / "build-all.sh"), *options], capture_output=True, text=True, check=True)
                self.assertLess(result.stdout.index("BOOTSTRAP=true"), result.stdout.index("FETCH"))
                self.assertLess(result.stdout.index("FETCH"), result.stdout.index("DOCTOR"))
                self.assertLess(result.stdout.index("DOCTOR"), result.stdout.index("TARGET=" + target))

    def test_bootstrap_selects_jdk21_without_mutating_parent_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / "bin"
            binary.mkdir()
            jdk = root / "openjdk/libexec/openjdk.jdk/Contents/Home"
            (jdk / "bin").mkdir(parents=True)
            (jdk / "bin/javac").write_text('#!/bin/sh\necho "javac 21.0.fixture"\n')
            (jdk / "bin/javac").chmod(0o755)
            programs = {
                "brew": f'#!/bin/sh\nif [ "$1" = --prefix ]; then echo "{root}/openjdk"; else exit 0; fi\n',
                "uname": '#!/bin/sh\necho Darwin\n',
                "xcode-select": '#!/bin/sh\nexit 0\n',
                "glibtool": '#!/bin/sh\nexit 0\n',
            }
            for name, contents in programs.items():
                path = binary / name
                path.write_text(contents)
                path.chmod(0o755)
            environment = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ["PATH"], JAVA_HOME="/fixture/jdk17", PYTHON_BIN=sys.executable)
            environment.pop("NORI_JAVA_HOME", None)
            command = f'source "{ROOT}/scripts/bootstrap.sh"; bootstrap false; printf "JAVA=%s\\n" "$JAVA_HOME"'
            result = subprocess.run(["bash", "-e", "-c", command], env=environment, capture_output=True, text=True, check=True)
            self.assertIn("JAVA=" + str(jdk), result.stdout)
            self.assertEqual(environment["JAVA_HOME"], "/fixture/jdk17")


if __name__ == "__main__":
    unittest.main()
