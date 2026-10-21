#!/usr/bin/env python3
"""Regenerate infra/lambda/shared/instance_rates.py from the AWS Price List API.

WHY THIS EXISTS
---------------
`INSTANCE_RATES` used to be a hand-maintained us-west-2 price snapshot that ALSO served as
the participant-facing instance allowlist. Two things went wrong with that, both measured:

  1. Prices drifted and disagreed across five separate copies of the table (config.py,
     grab_gpu_instance.py, and three notebook `_RATES` dicts), and every one of them was
     wrong for any region other than us-west-2. ap-northeast-2 is ~+23% across the board,
     so every cost shown to a participant or admin read ~23% LOW — the wrong direction for
     a lab whose documented failure mode is unnoticed spend.

  2. Because the allowlist was the table's keys, a region was offered instance types it
     cannot run. The whole ml.g6/g6e family has no Studio quota in ap-northeast-2, and
     eu-west-1 has no Studio-JupyterLab product for ml.g6.24xlarge at all — the participant
     picked it and their app failed to start.

So the table is now GENERATED per region from the authoritative source, and a region that
has not been generated fails LOUDLY at import rather than silently quoting another region's
prices.

WHAT IT RECORDS
---------------
Only types in CANDIDATE_TYPES (the curated set the lab's modules and docs actually
reference) AND that the target region really prices for Studio-JupyterLab. A type the
region does not offer is simply absent, which is what removes it from the dropdown.

Prices come from `platoinstancetype=Studio-JupyterLab`, which is the dimension a Studio
JupyterLab space is billed under. Do NOT substitute Studio-Notebook / Training / Hosting:
they can differ per type, and mixing them is how a table becomes quietly wrong.

QUOTA IS NOT PRICE
------------------
A price existing does NOT mean the account can launch it — quota is a separate,
per-(account x region) fact that changes over time, so quota VALUES are deliberately not
baked in here. What IS recorded is each type's Studio-JupyterLab quota CODE, so the
change_instance Lambda can resolve the live value with a single GetServiceQuota call
instead of paginating 2,258 SageMaker quotas inside a request.

Codes are safe to record because they are region-independent: measured across us-west-2
(169 codes), ap-northeast-2 (151) and eu-west-1 (136), every type present in more than one
region had an IDENTICAL code, zero mismatches. Only WHICH types have a quota differs. So
one flat map serves every region, while the value stays a runtime lookup.

USAGE
-----
    ./scripts/refresh_instance_rates.py --region us-west-2 --region ap-northeast-2
    ./scripts/refresh_instance_rates.py --region <new-region> --merge   # keep existing

Needs `pricing:GetProducts` (the Price List API lives in us-east-1 / eu-central-1 only;
this script always calls us-east-1 and passes the target region as a FILTER).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import re
import sys

try:
    import boto3
except ImportError:  # pragma: no cover
    sys.exit("boto3 is required: pip install boto3")

_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Two destinations, written from ONE fetch so they cannot diverge:
#   - the Lambda bundle (infra/lambda/ is asset-bundled whole, so this is picked up)
#   - scripts/, which is staged into every participant workspace by the notebook-sync LCC,
#     so the cost cells in M3/M5/M6/M8/M9 can show THIS region's prices. Those cells used
#     to hardcode a us-west-2 table, which understated cost ~23% in ap-northeast-2.
# A copy is unavoidable (Lambdas get infra/lambda/, workspaces get scripts/), but a
# GENERATED copy cannot drift — the previous hand-maintained duplicates already had.
OUT_PATH = _ROOT / "infra" / "lambda" / "shared" / "instance_rates.py"
WORKSPACE_OUT_PATH = _ROOT / "scripts" / "av30_instance_rates.py"

# The curated set. Deliberately NOT "everything the region prices" (that is ~148 types per
# region, which is noise for a participant dropdown). Keep in step with the module defaults
# in MODULE_CONFIG and with what the docs tell participants to pick.
CANDIDATE_TYPES = [
    # CPU
    "ml.t3.medium", "ml.t3.large", "ml.t3.xlarge", "ml.t3.2xlarge",
    "ml.m5.large", "ml.m5.xlarge", "ml.m5.2xlarge", "ml.m5.4xlarge",
    "ml.c5.large", "ml.c5.xlarge", "ml.c5.2xlarge",
    # g4dn — 1x T4 16 GB
    "ml.g4dn.xlarge", "ml.g4dn.2xlarge",
    # g5 — A10G 24 GB/card; 1 GPU to 8xlarge, 4 on 12/24xlarge, 8 on 48xlarge
    "ml.g5.xlarge", "ml.g5.2xlarge", "ml.g5.4xlarge", "ml.g5.8xlarge",
    "ml.g5.12xlarge", "ml.g5.24xlarge", "ml.g5.48xlarge",
    # g6 — L4 24 GB/card (NOT L40S; that is g6e). Same per-GPU VRAM tier as g5.
    "ml.g6.xlarge", "ml.g6.2xlarge", "ml.g6.4xlarge",
    "ml.g6.12xlarge", "ml.g6.24xlarge", "ml.g6.48xlarge",
    # g7e — RTX PRO 6000 Blackwell 96 GB/card. GPU count is NOT the size:
    # 2xl/4xl/8xl = 1 GPU, 12xl = 2, 24xl = 4, 48xl = 8.
    "ml.g7e.2xlarge", "ml.g7e.4xlarge", "ml.g7e.8xlarge",
    "ml.g7e.12xlarge", "ml.g7e.24xlarge", "ml.g7e.48xlarge",
    # p-family — 40 GB and 80 GB per-GPU tiers
    "ml.p3.2xlarge", "ml.p4d.24xlarge", "ml.p5.48xlarge",
]

_GPU_RE = re.compile(r"^ml\.(g\d|p\d|inf\d?|trn\d?)")


def fetch_region_rates(region: str) -> dict[str, float]:
    """All Studio-JupyterLab on-demand rates the region publishes, keyed by instance type."""
    pricing = boto3.client("pricing", region_name="us-east-1")
    rates: dict[str, float] = {}
    pages = pricing.get_paginator("get_products").paginate(
        ServiceCode="AmazonSageMaker",
        Filters=[
            {"Type": "TERM_MATCH", "Field": "regionCode", "Value": region},
            {"Type": "TERM_MATCH", "Field": "platoinstancetype", "Value": "Studio-JupyterLab"},
        ],
    )
    for page in pages:
        for raw in page["PriceList"]:
            doc = json.loads(raw)
            attrs = doc["product"]["attributes"]
            itype = attrs.get("instanceType") or attrs.get("instancename")
            if not itype:
                continue
            for term in doc["terms"].get("OnDemand", {}).values():
                for dim in term["priceDimensions"].values():
                    price = float(dim["pricePerUnit"].get("USD", 0) or 0)
                    # A $0 entry is a free-tier/placeholder row, not a real rate.
                    if price > 0:
                        rates[itype] = price
    return rates


_QUOTA_NAME_PREFIX = "Studio JupyterLab Apps running on "
_QUOTA_NAME_SUFFIX = " instances"


def fetch_quota_codes(region: str) -> dict[str, str]:
    """Map instance type -> Studio-JupyterLab quota code, e.g. ml.g5.12xlarge -> L-8D2ED7BF.

    Paginates all ~2,258 SageMaker quotas, which is fine here (operator machine, once per
    regeneration) and is exactly what the Lambda must NOT do per request.

    Adaptive retries because ListServiceQuotas throttles readily at this page count.
    """
    from botocore.config import Config

    client = boto3.client(
        "service-quotas",
        region_name=region,
        config=Config(retries={"mode": "adaptive", "max_attempts": 12}),
    )
    codes: dict[str, str] = {}
    pages = client.get_paginator("list_service_quotas").paginate(
        ServiceCode="sagemaker", PaginationConfig={"PageSize": 100}
    )
    for page in pages:
        for quota in page["Quotas"]:
            name = quota["QuotaName"]
            if name.startswith(_QUOTA_NAME_PREFIX) and name.endswith(_QUOTA_NAME_SUFFIX):
                itype = name[len(_QUOTA_NAME_PREFIX) : -len(_QUOTA_NAME_SUFFIX)]
                codes[itype] = quota["QuotaCode"]
    return codes


def load_existing() -> tuple[dict[str, dict[str, float]], dict[str, str]]:
    """Read the currently generated tables so --merge can keep other regions."""
    if not OUT_PATH.exists():
        return {}, {}
    ns: dict = {}
    try:
        exec(compile(OUT_PATH.read_text(), str(OUT_PATH), "exec"), ns)  # noqa: S102
    except Exception:  # noqa: BLE001 — a corrupt file must not block regeneration
        return {}, {}
    return ns.get("RATES_BY_REGION", {}), ns.get("QUOTA_CODES", {})


def render(by_region: dict[str, dict[str, float]], quota_codes: dict[str, str],
           stamp: str) -> str:
    lines = [
        '"""AUTO-GENERATED by scripts/refresh_instance_rates.py — DO NOT EDIT BY HAND.',
        "",
        "Studio-JupyterLab on-demand rates (USD/hour), keyed by REGION then instance type.",
        "",
        "Source : AWS Price List API, ServiceCode=AmazonSageMaker,",
        "         platoinstancetype=Studio-JupyterLab",
        f"Fetched: {stamp}",
        "",
        "A type absent from a region's dict is NOT offered for Studio-JupyterLab there, which",
        "is what keeps it out of the participant dropdown. A REGION absent from this file makes",
        "config.py raise at import rather than quote another region's prices — regenerate with:",
        "",
        "    ./scripts/refresh_instance_rates.py --region <region> --merge",
        "",
        "Prices are NOT quotas. A rate here only means the region sells the type; whether this",
        "account may launch it is a separate per-(account x region) fact. QUOTA_CODES below lets",
        "change_instance resolve that live value with one GetServiceQuota call per request.",
        '"""',
        "",
        "RATES_BY_REGION = {",
    ]
    for region in sorted(by_region):
        rates = by_region[region]
        lines.append(f'    "{region}": {{')
        cpu = {k: v for k, v in rates.items() if not _GPU_RE.match(k)}
        gpu = {k: v for k, v in rates.items() if _GPU_RE.match(k)}
        for label, group in (("CPU", cpu), ("GPU", gpu)):
            if not group:
                continue
            lines.append(f"        # --- {label} ---")
            for itype in sorted(group, key=lambda k: (group[k], k)):
                lines.append(f'        "{itype}": {group[itype]},')
        lines.append("    },")
    lines += ["}", ""]

    lines += [
        "",
        "# Studio-JupyterLab service-quota code per instance type, for GetServiceQuota.",
        "#",
        "# NOT keyed by region: codes were measured identical across us-west-2 / ap-northeast-2 /",
        "# eu-west-1 (zero mismatches on every shared type). Which types HAVE a quota does differ",
        "# per region, so a lookup can legitimately miss — callers must treat a miss as 'unknown',",
        "# never as 'quota 0', or they would block a launchable type.",
        "#",
        "# Values are deliberately absent: a quota can be raised minutes after this file is",
        "# generated, so baking one in would make the lab reject a type the account now owns.",
        "QUOTA_CODES = {",
    ]
    for itype in sorted(quota_codes):
        lines.append(f'    "{itype}": "{quota_codes[itype]}",')
    lines += ["}", ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", action="append", required=True, dest="regions",
                    help="target region (repeatable)")
    ap.add_argument("--merge", action="store_true",
                    help="keep regions already in the file instead of replacing it")
    args = ap.parse_args()

    existing_rates, existing_codes = load_existing()
    by_region = existing_rates if args.merge else {}
    # Codes are region-independent, so ALWAYS start from what we already know and union in
    # anything new. Replacing them on a non-merge run would silently drop codes for types
    # this run's regions do not offer, disabling the quota check for other regions' types.
    quota_codes = dict(existing_codes)

    for region in args.regions:
        published = fetch_region_rates(region)
        if not published:
            print(f"  {region}: NO Studio-JupyterLab products returned — refusing to write "
                  f"an empty region (wrong credentials, or the region has no Studio?)",
                  file=sys.stderr)
            return 2
        kept = {t: published[t] for t in CANDIDATE_TYPES if t in published}
        missing = [t for t in CANDIDATE_TYPES if t not in published]
        by_region[region] = kept
        print(f"  {region}: {len(kept)}/{len(CANDIDATE_TYPES)} candidate types priced")
        if missing:
            print(f"     not offered for Studio-JupyterLab here: {', '.join(missing)}")

        found = fetch_quota_codes(region)
        new = {t: c for t, c in found.items() if t in kept}
        conflicts = [t for t, c in new.items()
                     if t in quota_codes and quota_codes[t] != c]
        if conflicts:
            # Would break the region-independence assumption the flat map rests on.
            print(f"  {region}: quota code CONFLICT for {conflicts} — codes were assumed "
                  f"region-independent; refusing to write an ambiguous map", file=sys.stderr)
            return 2
        added = [t for t in new if t not in quota_codes]
        quota_codes.update(new)
        no_quota = sorted(t for t in kept if t not in found)
        print(f"     quota codes: {len(new)}/{len(kept)} priced types ({len(added)} new)")
        if no_quota:
            # Priced but no Studio quota here -> quota check must say "unknown", not "0".
            print(f"     priced but NO Studio quota in this region: {', '.join(no_quota)}")

    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    body = render(by_region, quota_codes, stamp)
    for path in (OUT_PATH, WORKSPACE_OUT_PATH):
        path.write_text(body)
        try:
            shown = path.relative_to(pathlib.Path.cwd())
        except ValueError:
            shown = path
        print(f"  wrote {shown}")
    print(f"  {len(by_region)} region(s): {', '.join(sorted(by_region))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
