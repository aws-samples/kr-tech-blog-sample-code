"""The participant instance list, read from the participant dashboard's module table.

web/user/src/data/pipeline-config.ts is the ONLY place the participant-facing instance
choice lives: each module's `recommendedInstance` plus its `alternatives` are exactly what
the Instance Options panel offers. Two consumers need that same set and must not drift from
it, so both parse it here instead of keeping a hand-copied list:

  * the CDK app, at synth — intersects it with the deploy region's rate table and passes the
    result to the Lambdas as PARTICIPANT_INSTANCE_TYPES, the server-side cap that
    change_instance and expand_storage enforce;
  * scripts/check_quotas.py — reports quota for every type the dashboard can steer a
    participant to.

Deliberately dependency-free (stdlib only) and loaded BY PATH by both, like smd_images.py:
neither the CDK app nor the script has infra/lambda/shared on its import path.

Strict on purpose. The result is an allowlist, so a parse that silently returned fewer
types would cap participants below what the dashboard shows them, and one that read a
commented-out line would let a type through that nobody chose. Anything that is not a plain
string literal / literal array raises ValueError, which fails `cdk synth`.
"""

from __future__ import annotations

import re
from pathlib import Path

# The type every space is created on (create_user / bulk_provision) and the fallback
# change_instance / expand_storage assume for a row with no recorded instanceType. It MUST be
# in the participant set, or a brand-new participant's first storage resize is refused.
DEFAULT_INSTANCE_TYPE = "ml.t3.medium"

_MODULES_START = "export const PIPELINE_MODULES"
_TYPE_LITERAL = r'"(ml\.[a-z0-9]+\.[a-z0-9]+)"'


def _module_blocks(text: str) -> list[str]:
    """The PIPELINE_MODULES entries, one string each, with full-line // comments removed.

    Comments are dropped first because they are full of instance names (the rationale for
    each list is written next to it), and a commented-out `alternatives: [...]` must not
    count. Entries are split on the top-level "  {" line, the same shape every module uses.
    """
    start = text.find(_MODULES_START)
    if start < 0:
        raise ValueError(f"{_MODULES_START} not found")
    end = text.find("\n];", start)
    if end < 0:
        raise ValueError(f"{_MODULES_START} has no closing '];'")
    body = "\n".join(
        line for line in text[start:end].splitlines() if not line.lstrip().startswith("//")
    )
    return re.split(r"\n  \{\n", body)[1:]


def parse_pipeline_config(text: str) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """(recommended, alternatives): instance type -> titles of the modules that offer it.

    Raises ValueError if any module's recommendedInstance is not a single string literal,
    if its alternatives are not a single literal array of "ml.<family>.<size>" strings, or
    if no module is found at all.
    """
    rec_out: dict[str, list[str]] = {}
    alt_out: dict[str, list[str]] = {}
    blocks = _module_blocks(text)
    if not blocks:
        raise ValueError(f"no module entries found under {_MODULES_START}")
    for block in blocks:
        title_m = re.search(r'title:\s*"([^"]+)"', block)
        title = title_m.group(1) if title_m else "(unknown module)"

        if len(re.findall(r"\brecommendedInstance:", block)) != 1:
            raise ValueError(f"{title}: expected exactly one recommendedInstance")
        rec = re.search(rf"\brecommendedInstance:\s*{_TYPE_LITERAL}\s*,", block)
        if not rec:
            raise ValueError(f"{title}: recommendedInstance is not an ml.* string literal")
        rec_out.setdefault(rec.group(1), []).append(title)

        if len(re.findall(r"\balternatives:", block)) != 1:
            raise ValueError(f"{title}: expected exactly one alternatives array")
        alts = re.search(r"\balternatives:\s*\[([^\]]*)\]\s*,", block)
        if not alts:
            raise ValueError(f"{title}: alternatives is not a literal array")
        # Everything inside the brackets must be a type literal, a comma or whitespace.
        # A spread, an identifier or a malformed name would otherwise just vanish here.
        if re.sub(_TYPE_LITERAL, "", alts.group(1)).strip(" \t\r\n,"):
            raise ValueError(
                f"{title}: alternatives must hold only \"ml.<family>.<size>\" literals"
            )
        for itype in re.findall(_TYPE_LITERAL, alts.group(1)):
            alt_out.setdefault(itype, []).append(title)
    return rec_out, alt_out


def dashboard_instance_types(text: str) -> frozenset[str]:
    """Every type the dashboard offers (recommended or alternative), validated.

    Raises ValueError on a parse failure, an empty result, or a set without
    DEFAULT_INSTANCE_TYPE.
    """
    recs, alts = parse_pipeline_config(text)
    types = frozenset(recs) | frozenset(alts)
    if not types:
        raise ValueError("pipeline-config.ts yielded no instance types")
    if DEFAULT_INSTANCE_TYPE not in types:
        raise ValueError(
            f"{DEFAULT_INSTANCE_TYPE} is missing from pipeline-config.ts. It is the type every "
            f"space starts on, so leaving it out would refuse every new participant."
        )
    return types


def participant_instance_types(pipeline_config: Path, region_rates: dict) -> list[str]:
    """Sorted dashboard types the region also sells: the value of PARTICIPANT_INSTANCE_TYPES.

    A dashboard type the region does not sell (ml.g6.* in eu-west-1, for example) is dropped
    rather than rejected: it could never start there anyway, and change_instance names the
    region when it refuses it.
    """
    types = dashboard_instance_types(Path(pipeline_config).read_text(encoding="utf-8"))
    allowed = sorted(t for t in types if t in region_rates)
    if DEFAULT_INSTANCE_TYPE not in allowed:
        raise ValueError(
            f"{DEFAULT_INSTANCE_TYPE} is not in this region's Studio-JupyterLab rate table"
        )
    return allowed
