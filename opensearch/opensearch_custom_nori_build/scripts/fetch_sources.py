import hashlib
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def versions():
    return dict(line.split("=", 1) for line in (ROOT / "versions.env").read_text().splitlines() if line)


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_output(directory, *arguments):
    return subprocess.check_output(["git", "-C", str(directory), *arguments], text=True).strip()


def verify_checkout(destination, repository, commit):
    if destination.is_symlink() or not (destination / ".git").is_dir():
        raise ValueError(f"Not a regular standalone checkout: {destination}")
    if git_output(destination, "remote", "get-url", "origin") != repository:
        raise ValueError(f"Unexpected source repository: {destination}")
    if git_output(destination, "rev-parse", "HEAD") != commit:
        raise ValueError(f"Unexpected source revision; preserving checkout: {destination}")
    if git_output(destination, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError(f"Tracked source changes detected; preserving checkout: {destination}")


def checkout(repository, tag, commit, destination):
    if destination.exists() or destination.is_symlink():
        verify_checkout(destination, repository, commit)
        return
    with tempfile.TemporaryDirectory(prefix=".checkout-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "source"
        subprocess.run(["git", "clone", "--depth", "1", "--single-branch", "--branch", tag,
                        repository, str(staging)], check=True)
        verify_checkout(staging, repository, commit)
        staging.rename(destination)


def download(url, destination, expected):
    if destination.is_symlink():
        raise ValueError(f"Refusing a symlink download: {destination}")
    if not destination.exists():
        with tempfile.TemporaryDirectory(prefix=".download-", dir=destination.parent) as temporary:
            staging = Path(temporary) / destination.name
            subprocess.run(["curl", "--fail", "--location", "--retry", "3", "--connect-timeout", "20",
                            "--max-time", "900", "--output", str(staging), url], check=True)
            if checksum(staging) != expected:
                raise ValueError(f"Downloaded archive checksum mismatch: {url}")
            staging.rename(destination)
    if checksum(destination) != expected:
        raise ValueError(f"Cached archive checksum mismatch; preserving file: {destination}")


def extract(archive, destination, expected):
    marker = destination / ".archive-sha256"
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not marker.is_file() or marker.read_text().strip() != expected:
            raise ValueError(f"Unknown or incomplete extracted source; preserving directory: {destination}")
        return
    with tempfile.TemporaryDirectory(prefix=".extract-", dir=destination.parent) as temporary:
        staging = Path(temporary)
        with tarfile.open(archive) as package:
            package.extractall(staging, filter="data")
        unpacked = staging / destination.name
        if not unpacked.is_dir() or unpacked.is_symlink() or len(list(staging.iterdir())) != 1:
            raise ValueError(f"Unexpected archive root: {archive}")
        (unpacked / marker.name).write_text(expected + "\n")
        unpacked.rename(destination)


def main():
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("Use Python 3.12")
    pinned = versions()
    sources = ROOT / "sources"
    cache = ROOT / ".cache/downloads"
    sources.mkdir(exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    repositories = [
        ("OpenSearch", "https://github.com/opensearch-project/OpenSearch.git", pinned["OPENSEARCH_VERSION"], pinned["OPENSEARCH_COMMIT"]),
        ("lucene", "https://github.com/apache/lucene.git", "releases/lucene/" + pinned["LUCENE_VERSION"], pinned["LUCENE_COMMIT"]),
    ]
    for name, repository, tag, commit in repositories:
        print(f"Preparing {name} at {commit}", flush=True)
        checkout(repository, tag, commit, sources / name)
    archives = [
        (f"mecab-{pinned['MECAB_VERSION']}", "https://bitbucket.org/eunjeon/mecab-ko/downloads/", pinned["MECAB_SHA256"]),
        (f"mecab-ko-dic-{pinned['MECAB_DIC_VERSION']}", "https://s3.amazonaws.com/lucene-testdata/mecab/", pinned["MECAB_DIC_SHA256"]),
    ]
    for name, base_url, digest in archives:
        archive = cache / f"{name}.tar.gz"
        print(f"Preparing {name} with SHA-256 verification", flush=True)
        download(base_url + archive.name, archive, digest)
        extract(archive, sources / name, digest)
    (sources / "source-manifest.json").write_text(json.dumps(pinned, indent=2) + "\n")
    print("Pinned public sources are ready. No upstream source is tracked by this sample.")


if __name__ == "__main__":
    main()
