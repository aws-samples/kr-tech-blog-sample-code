import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fetch_sources import ROOT, checksum, versions


TOOL_PATHS = (
    "bin/mecab",
    "libexec/mecab/mecab-dict-index",
    "libexec/mecab/mecab-cost-train",
    "libexec/mecab/mecab-dict-gen",
)


def build_native(output, jobs):
    pinned = versions()
    archive = ROOT / ".cache/downloads" / f"mecab-{pinned['MECAB_VERSION']}.tar.gz"
    if archive.is_symlink() or checksum(archive) != pinned["MECAB_SHA256"]:
        raise ValueError("MeCab source archive checksum mismatch")
    engine_runs = output / "engine"
    engine_runs.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="build-", dir=engine_runs))
    with tarfile.open(archive) as package:
        package.extractall(run, filter="data")
    source = run / f"mecab-{pinned['MECAB_VERSION']}"
    prefix = output / "toolchain"
    pending = output / "native-build-pending.json"
    started = datetime.now(timezone.utc).isoformat()
    pending.write_text(json.dumps({"source": str(source), "started": started}, indent=2) + "\n")
    automake = Path(subprocess.check_output(["automake", "--print-libdir"], text=True).strip())
    for filename in ("config.guess", "config.sub"):
        shutil.copy2(automake / filename, source / filename)
    commands = [
        ["./configure", f"--prefix={prefix}", "--with-charset=utf8", "--enable-utf8-only",
         "CC=clang", "CXX=clang++", "CXXFLAGS=-O2 -std=c++11"],
        ["make", f"-j{jobs}", "CXXFLAGS=-O2 -std=c++11"],
        ["make", "install"],
    ]
    for command in commands:
        print("Running:", " ".join(command), flush=True)
        subprocess.run(command, cwd=source, check=True)
    artifacts = {}
    for relative in TOOL_PATHS:
        path = prefix / relative
        if not path.is_file() or not os.access(path, os.X_OK):
            raise RuntimeError(f"Native build did not install {relative}")
        artifacts[relative] = checksum(path)
    version = subprocess.check_output([str(prefix / "bin/mecab"), "--version"], text=True).strip()
    manifest = {
        "status": "PASS", "source_build_executed": True, "reused_prebuilt_engine": False,
        "source_version": pinned["MECAB_VERSION"], "archive_sha256": pinned["MECAB_SHA256"],
        "started": started, "completed": datetime.now(timezone.utc).isoformat(),
        "source_directory": str(source), "install_prefix": str(prefix), "mecab_version": version,
        "commands": commands, "artifacts_sha256": artifacts,
    }
    (output / "native-build.json").write_text(json.dumps(manifest, indent=2) + "\n")
    pending.unlink()
    print(f"Built {version} from source and installed {len(artifacts)} native tools.", flush=True)
    return manifest


if __name__ == "__main__":
    build_native(Path(os.environ["NORI_BUILD_DIR"]), int(os.environ["NORI_BUILD_JOBS"]))
