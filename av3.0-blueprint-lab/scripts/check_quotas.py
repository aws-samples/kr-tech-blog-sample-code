#!/usr/bin/env python3
"""Pre-flight: can this region actually run the lab, for this many participants?

WHY THIS EXISTS
---------------
Three DIFFERENT facts decide whether a participant can start an instance, and they fail in
three different ways:

  1. Does the region SELL the type for Studio-JupyterLab?  -> a price exists
     If not, the app never starts. Measured: eu-west-1 sells no ml.g6.* for Studio at all.
  2. Does THIS ACCOUNT have quota for it IN THIS REGION?    -> Service Quotas value > 0
     Quota is scoped to (account x region), and the default for big GPU types is often 0.
     Measured: ap-northeast-2 has quota 0 for the ENTIRE ml.g6/g6e family while us-west-2
     has 2. An increase approved in one region does nothing for another.
  3. Is the quota big enough for the COHORT?                -> value >= concurrent users
     Quota 2 means two participants at a time, not two per person.

(1) is baked into the generated rate table. (2) and (3) change over time and per account,
so they are resolved live here.

The failure this prevents: the participant dashboard's recommendations are STATIC
(web/user/src/data/pipeline-config.ts) and recommend ml.g6.24xlarge for four modules. Deploy
to a region where g6 quota is 0 and those four modules are dead on arrival — discovered by a
participant mid-workshop rather than by the admin the week before.

USAGE
-----
    ./scripts/check_quotas.py --region ap-northeast-2
    ./scripts/check_quotas.py --region ap-northeast-2 --participants 10

Exit codes: 0 = every recommended type is runnable; 1 = at least one is not.
Read-only: needs servicequotas:GetServiceQuota / ListServiceQuotas.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

try:
    import boto3
except ImportError:  # pragma: no cover
    sys.exit("boto3 is required: pip install boto3")

REPO = pathlib.Path(__file__).resolve().parent.parent
SHARED = REPO / "infra" / "lambda" / "shared"
PIPELINE_CONFIG = REPO / "web" / "user" / "src" / "data" / "pipeline-config.ts"

_QUOTA_PREFIX = "Studio JupyterLab Apps running on "


def region_rates(region: str) -> dict[str, float]:
    """The generated Studio-JupyterLab rate table for this region."""
    ns: dict = {}
    path = SHARED / "instance_rates.py"
    if not path.exists():
        sys.exit("infra/lambda/shared/instance_rates.py is missing — run "
                 "./scripts/refresh_instance_rates.py --region <region>")
    exec(compile(path.read_text(), str(path), "exec"), ns)  # noqa: S102
    table = ns.get("RATES_BY_REGION", {})
    if region not in table:
        sys.exit(f"No rate table for {region}. Generate it:\n"
                 f"    ./scripts/refresh_instance_rates.py --region {region} --merge\n"
                 f"Generated: {', '.join(sorted(table))}")
    return table[region]


def _parse_pipeline_config() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """(recommended, alternatives): instance type -> module titles, from the participant UI.

    Parsed rather than duplicated: this file is the ONLY place the participant-facing
    recommendation lives (the instance_options Lambda is dead code — getInstanceOptions has
    zero call sites), so a hand-copied list here would drift from what users actually see.

    ALTERNATIVES matter as much as the recommendation. They are what the dashboard offers
    on a capacity error and what every errorHint tells a stuck participant to pick, so a
    fallback with quota 0 is a dead end at the worst possible moment. This used to read
    only recommendedInstance, which is how ml.g6.12xlarge and ml.g7e.2xlarge sat at the
    FRONT of M2/M3's alternatives — both unusable in ap-northeast-2 — while the report
    said everything was fine.
    """
    if not PIPELINE_CONFIG.exists():
        return {}, {}
    text = PIPELINE_CONFIG.read_text()
    rec_out: dict[str, list[str]] = {}
    alt_out: dict[str, list[str]] = {}
    # Walk module blocks so a type can be attributed to a module title.
    for block in re.split(r"\n  \{\n", text):
        title_m = re.search(r'title:\s*"([^"]+)"', block)
        title = title_m.group(1) if title_m else "(unknown module)"
        rec = re.search(r'recommendedInstance:\s*"(ml\.[a-z0-9.]+)"', block)
        if rec:
            rec_out.setdefault(rec.group(1), []).append(title)
        alts = re.search(r'alternatives:\s*\[([^\]]*)\]', block)
        if alts:
            for t in re.findall(r'"(ml\.[a-z0-9.]+)"', alts.group(1)):
                alt_out.setdefault(t, []).append(title)
    return rec_out, alt_out


def recommended_types() -> dict[str, list[str]]:
    """Back-compat wrapper — recommendations only."""
    return _parse_pipeline_config()[0]


def live_quotas(region: str) -> dict[str, tuple[float, str]]:
    """instance type -> (quota value, quota code) in this (account, region).

    SageMaker publishes ~2,258 quotas, so this pages ~23 times and Service Quotas rate-limits
    ListServiceQuotas — a plain call reliably dies with TooManyRequestsException partway
    through. Adaptive retries make the client back off and slow down on its own; without it
    this returned a PARTIAL map, which is the dangerous failure here: a type missing from the
    map is indistinguishable from a type with no quota row, so a throttle would be reported
    to the admin as "QUOTA 0 — blocked".
    """
    from botocore.config import Config

    sq = boto3.client(
        "service-quotas",
        region_name=region,
        config=Config(retries={"mode": "adaptive", "max_attempts": 12}),
    )
    values: dict[str, tuple[float, str]] = {}
    pages = 0
    try:
        for page in sq.get_paginator("list_service_quotas").paginate(
            ServiceCode="sagemaker", PaginationConfig={"PageSize": 100}
        ):
            pages += 1
            for q in page["Quotas"]:
                name = q["QuotaName"]
                if name.startswith(_QUOTA_PREFIX):
                    itype = name[len(_QUOTA_PREFIX):].replace(" instances", "").strip()
                    values[itype] = (q["Value"], q["QuotaCode"])
    except Exception as exc:  # noqa: BLE001
        # Refuse to report a partial map as fact — see the docstring.
        sys.exit(
            f"Could not read quotas for {region} after {pages} page(s): "
            f"{type(exc).__name__}: {exc}\n"
            f"Refusing to continue: a partial quota map would show available types as "
            f"'QUOTA 0'. Re-run in a minute."
        )
    return values


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", required=True)
    ap.add_argument("--participants", type=int, default=1,
                    help="concurrent participants per instance type (default 1)")
    args = ap.parse_args()

    rates = region_rates(args.region)
    quotas = live_quotas(args.region)
    recs, alts = _parse_pipeline_config()

    print(f"Region: {args.region}   participants (concurrent): {args.participants}")
    print(f"Account: {boto3.client('sts').get_caller_identity()['Account']}")
    print()

    blocked: list[tuple[str, str | None]] = []
    tight: list[str] = []

    print("Types the participant dashboard RECOMMENDS:")
    if not recs:
        print("  (could not parse web/user/src/data/pipeline-config.ts)")
    for itype in sorted(recs, key=lambda t: -rates.get(t, 0)):
        modules = recs[itype]
        sold = itype in rates
        entry = quotas.get(itype)
        quota, code = entry if entry else (None, None)
        if not sold:
            status, note = "NOT SOLD", f"{args.region} has no Studio-JupyterLab product"
            blocked.append((itype, None))
        elif quota is None:
            status, note = "NO QUOTA ROW", "quota does not exist in this region"
            blocked.append((itype, None))
        elif quota <= 0:
            status = "QUOTA 0"
            note = f"code {code} — request an increase, or steer modules elsewhere"
            blocked.append((itype, code))
        elif quota < args.participants:
            status = f"TIGHT {quota:.0f}"
            note = f"only {quota:.0f} concurrent, need {args.participants}"
            tight.append(itype)
        else:
            status, note = f"OK {quota:.0f}", f"${rates[itype]:.4f}/hr"
        print(f"  {status:14s} {itype:20s} {note}")
        print(f"                 used by: {', '.join(sorted(set(modules)))}")

    # ALTERNATIVES — what the dashboard offers on a capacity error, and what every
    # errorHint points a stuck participant at. A dead fallback is worse than no fallback,
    # because it is reached at the moment the first choice already failed. Not fatal: an
    # alternative is a convenience, so these DOWNGRADE to a warning rather than exit 1.
    dead_alts: list[tuple[str, str | None, str]] = []
    print()
    print("Types offered as ALTERNATIVES (what a capacity error steers people to):")
    if not alts:
        print("  (none parsed)")
    for itype in sorted(alts, key=lambda t: -rates.get(t, 0)):
        if itype in recs:
            continue          # already reported above
        sold = itype in rates
        entry = quotas.get(itype)
        quota, code = entry if entry else (None, None)
        if not sold:
            status, note, bad = "NOT SOLD", f"{args.region} has no Studio-JupyterLab product", True
        elif quota is None:
            status, note, bad = "NO QUOTA ROW", "quota does not exist in this region", True
        elif quota <= 0:
            status, note, bad = "QUOTA 0", f"code {code} — a dead end for a stuck participant", True
        else:
            status, note, bad = f"ok {quota:.0f}", f"${rates[itype]:.4f}/hr", False
        if bad:
            dead_alts.append((itype, code, ", ".join(sorted(set(alts[itype])))))
        print(f"  {status:14s} {itype:20s} {note}")
        print(f"                 offered by: {', '.join(sorted(set(alts[itype])))}")

    print()
    print("Other lab types sold here, by quota:")
    # quotas[t] is (value, code); sort on the value only. A type with no quota row sorts last.
    for itype in sorted(rates, key=lambda t: (-(quotas[t][0] if t in quotas else 0), t)):
        if itype in recs or itype in alts:
            continue
        e = quotas.get(itype)
        q_s = "no quota row" if e is None else f"{e[0]:.0f}"
        print(f"  quota {q_s:>13s}  {itype:20s} ${rates[itype]:.4f}/hr")

    if dead_alts:
        print()
        print(f"WARNING: {len(dead_alts)} alternative(s) cannot run in {args.region}. A")
        print("  participant hitting EC2InsufficientCapacityError will be steered to one of")
        print("  these and get a second failure. Reorder the alternatives arrays in")
        print("  web/user/src/data/pipeline-config.ts so region-available types come first:")
        for itype, code, mods in dead_alts:
            print(f"    {itype:20s} offered by {mods}")

    print()
    if blocked:
        print(f"BLOCKED: {len(blocked)} recommended type(s) cannot run here: "
              f"{', '.join(t for t, _ in blocked)}")
        print("  Either request quota IN THIS REGION, or point the affected modules at a")
        print("  type that is available (check the 'Other lab types' list above).")
        for itype, code in blocked:
            if code:
                print(f"  aws service-quotas request-service-quota-increase "
                      f"--region {args.region} \\")
                print(f"    --service-code sagemaker --quota-code {code} "
                      f"--desired-value {max(args.participants, 2)}   # {itype}")
    if tight:
        print(f"TIGHT: {', '.join(tight)} — enough to run, not enough for "
              f"{args.participants} at once.")
    if not blocked and not tight:
        print(f"All recommended types are runnable for {args.participants} "
              f"concurrent participant(s).")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
