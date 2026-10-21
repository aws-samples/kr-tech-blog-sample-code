#!/usr/bin/env python3
"""One-shot renumbering of the lab's modules into the blog's 8-stage order.

WHY THIS IS A SCRIPT AND NOT A sed ONE-LINER
--------------------------------------------
The mapping is a PERMUTATION, so sequential substitution clobbers itself. It even
contains a 2-cycle: M7 (AlpaSim) -> M10 and M10 (Nerfstudio) -> M7. Any
old-to-new pass that rewrites M7 first will then rewrite the result again when it
reaches M10. Every substitution here is therefore computed from the ORIGINAL text
in a single pass (one re.sub with a callback), never chained.

It also has to tell apart token shapes that look alike but mean different things:

    M4              module label in prose / tables / "M4/M5" ranges
    M4_Cosmos...    notebook filename stem
    ALPAMAYO_M6     doc filename stem (M6 is preceded by '_', so \b fails here)
    m4/             S3 prefix — the DATA CONTRACT between modules
    m7-reference/   shared-bucket prefix, and IAM role/policy name fragments
    m04-cosmos-...  zero-padded long module id used by the frontend + API
    ml.m5.xlarge    an INSTANCE TYPE — must never be touched

The lowercase patterns anchor on a following '/' or '-', which is exactly what
keeps `ml.m5.xlarge` and `ml.m5.large` safe (they are followed by '.').

Run with --dry-run first: it prints every distinct replacement per file so false
positives can be eyeballed before anything is written.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import subprocess
import sys

# --- the mapping ------------------------------------------------------------
# old module number -> new module number. Derived from the blog's stage order:
#   stage 1-2 M1 | stage 3 M2,M3 | stage 4 M8 | stage 5 M4,M5 | stage 6 M10
#   stage 7 (new SFT), M6 | stage 8 M7 | no stage: M11, M9
# New module 8 (Cosmos Reason LoRA SFT) has no source and is added separately.
RENUMBER = {
    0: 0,    # Pipeline Overview        (unchanged)
    1: 1,    # Data Exploration         stage 1-2
    2: 2,    # Cosmos Reason Captioning stage 3
    3: 3,    # Cosmos Curator           stage 3
    8: 4,    # OpenSearch Semantic      stage 4   <- was M8
    4: 5,    # Cosmos Transfer          stage 5   <- was M4
    5: 6,    # Cosmos Predict           stage 5ext<- was M5
    10: 7,   # Nerfstudio 3D            stage 6   <- was M10
    #        NEW M8 = Cosmos Reason LoRA SFT      stage 7
    6: 9,    # Alpamayo VLA Inference   stage 7   <- was M6
    7: 10,   # AlpaSim Closed-Loop      stage 8   <- was M7
    11: 11,  # Pipeline Automation      (no stage, unchanged)
    9: 12,   # HyperPod Distributed     (no stage) <- was M9
}
assert len(set(RENUMBER.values())) == len(RENUMBER), "mapping is not injective"
assert 8 not in RENUMBER.values(), "slot 8 must stay free for the new module"

SKIP_DIRS = {".git", "node_modules", "cdk.out", "dist", ".venv", "__pycache__",
             "build", ".pytest_cache"}
SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".tar", ".gz", ".zip",
               ".pdf", ".woff", ".woff2", ".svg", ".mp4", ".webm", ".pyc"}

# Patterns share one alternation so each character is examined ONCE against the
# original text. Named groups tell the callback which shape matched.
TOKEN = re.compile(
    r"(?P<up>(?<![A-Za-z0-9])M(?P<upn>\d{1,2})(?![0-9]))"
    r"|(?P<lowslash>(?<![A-Za-z0-9])m(?P<lsn>\d{1,2})(?=/))"
    r"|(?P<lowdash>(?<![A-Za-z0-9])m(?P<ldn>\d{1,2})(?=-[a-z]))"
)


def _remap(num: int) -> int | None:
    return RENUMBER.get(num)


def rewrite(text: str, counter: collections.Counter | None = None) -> str:
    def sub(m: re.Match) -> str:
        whole = m.group(0)
        if m.group("up") is not None:
            old = int(m.group("upn"))
            new = _remap(old)
            if new is None:
                return whole
            out = f"M{new}"
        elif m.group("lowslash") is not None:
            old = int(m.group("lsn"))
            new = _remap(old)
            if new is None:
                return whole
            out = f"m{new}"
        else:
            digits = m.group("ldn")
            old = int(digits)
            new = _remap(old)
            if new is None:
                return whole
            # Preserve zero-padding: m04-cosmos-transfer -> m05-cosmos-transfer,
            # but m7-reference -> m10-reference (no padding to preserve).
            out = f"m{new:0{len(digits)}d}" if len(digits) > 1 else f"m{new}"
        if counter is not None and out != whole:
            counter[f"{whole} -> {out}"] += 1
        return out

    return TOKEN.sub(sub, text)


def rename_path(p: pathlib.Path) -> pathlib.Path:
    """Apply the same rewrite to the FILE NAME only (never the directory part)."""
    return p.with_name(rewrite(p.name))


def iter_files(root: pathlib.Path):
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True,
                         capture_output=True, text=True).stdout
    for rel in out.split("\0"):
        if not rel:
            continue
        p = root / rel
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() in SKIP_SUFFIX:
            continue
        if not p.is_file():
            continue
        yield p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    root = pathlib.Path(args.root).resolve()

    content_changes: dict[str, collections.Counter] = {}
    renames: list[tuple[pathlib.Path, pathlib.Path]] = []

    for p in iter_files(root):
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print(f"SKIP (not utf-8): {p.relative_to(root)}", file=sys.stderr)
            continue

        counter: collections.Counter = collections.Counter()
        new_text = rewrite(text, counter)
        if counter:
            content_changes[str(p.relative_to(root))] = counter
        if new_text != text and not args.dry_run:
            # .ipynb must stay valid JSON in nbformat's exact serialization.
            if p.suffix == ".ipynb":
                nb = json.loads(new_text)
                new_text = json.dumps(nb, indent=1, ensure_ascii=False) + "\n"
            p.write_text(new_text, encoding="utf-8")

        target = rename_path(p)
        if target != p:
            renames.append((p, target))

    print("=" * 72)
    print("FILE RENAMES")
    print("=" * 72)
    for src, dst in sorted(renames):
        print(f"  {src.relative_to(root)}\n    -> {dst.relative_to(root)}")
    if not renames:
        print("  (none)")

    print()
    print("=" * 72)
    print("CONTENT REPLACEMENTS (distinct token -> token, per file)")
    print("=" * 72)
    grand: collections.Counter = collections.Counter()
    for f in sorted(content_changes):
        c = content_changes[f]
        grand.update(c)
        print(f"\n{f}  ({sum(c.values())} replacements)")
        for k, n in sorted(c.items(), key=lambda kv: -kv[1]):
            print(f"    {n:5}  {k}")

    print()
    print("=" * 72)
    print(f"TOTALS: {len(content_changes)} files, {sum(grand.values())} replacements, "
          f"{len(renames)} renames")
    print("distinct token transitions:")
    for k, n in sorted(grand.items(), key=lambda kv: -kv[1]):
        print(f"  {n:5}  {k}")

    if not args.dry_run:
        # Renames last, via git mv, using a two-phase hop so the M7<->M10 cycle
        # cannot clobber: everything goes to a temp name first.
        for i, (src, dst) in enumerate(renames):
            tmp = src.with_name(f".renumber-tmp-{i}-{src.name}")
            subprocess.run(["git", "mv", str(src), str(tmp)], cwd=root, check=True)
        for i, (src, dst) in enumerate(renames):
            tmp = src.with_name(f".renumber-tmp-{i}-{src.name}")
            subprocess.run(["git", "mv", str(tmp), str(dst)], cwd=root, check=True)
        print(f"\nAPPLIED: {len(renames)} renames via two-phase git mv")
    else:
        print("\nDRY RUN — nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
