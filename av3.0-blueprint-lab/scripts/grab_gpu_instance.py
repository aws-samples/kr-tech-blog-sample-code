#!/usr/bin/env python3
"""Auto-grab an available GPU instance for a SageMaker Studio JupyterLab space.

Big GPU instances (ml.g5.24xlarge+, ml.g6.24xlarge+, ml.p4d, ml.p5) are chronically
capacity-constrained in us-west-2. Manually retrying the Studio "change instance
type" dialog until one lands is tedious. This CLI does it for you: it walks a list
of candidate instance types (cheapest-first by default) and keeps trying to launch
the JupyterLab app on each until one succeeds, then stops and prints the console URL.

WHY "try -> fail -> next" and not "check capacity first": SageMaker exposes NO
pre-flight capacity API. create_app returns instantly and *succeeds*; a capacity
shortage only surfaces asynchronously as the app landing in Failed state with a
FailureReason containing "InsufficientCapacity". So the only way to know an instance
is available is to actually ask for it and watch the app come up. This mirrors how
the workshop's own app_status Lambda detects capacity errors
(infra/lambda/app_status/handler.py).

The change-instance dance (delete app -> wait deleted -> update_space -> wait
InService -> create_app -> poll) and its retry-on-storage-not-ready are lifted from
infra/lambda/shared/config.py, which has been hardened against the same failure
modes in production.

IMAGE SELECTION (important): the workshop provisions every space on the CPU
SageMaker Distribution image (create_user uses ml.t3.medium). Moving that space
onto a GPU box needs a CUDA-capable image, or torch.cuda.is_available() is False
even though nvidia-smi shows the GPUs. This script therefore, by default, selects
the GPU Distribution image automatically whenever the TARGET instance is a GPU
family (ml.g*/ml.p*) and keeps the space's current image for CPU targets. Override
explicitly with --image-arn if you need a specific image.

CREDENTIALS / REGION
    Uses the standard boto3 credential chain (env vars, ~/.aws, SSO, instance role).
    Region is REQUIRED (--region or AWS_REGION); it is never defaulted.

TYPICAL USAGE
    # Auto-detect the (single) domain and JupyterLab space, loop until a GPU lands:
    python scripts/grab_gpu_instance.py
    # Target a specific space, cheapest-first over the default candidate tier:
    python scripts/grab_gpu_instance.py --domain-id d-xxxx --space-name my-space
    # Only p4d/p5, strongest-first, single pass (no retry loop):
    python scripts/grab_gpu_instance.py --instances ml.p5.48xlarge,ml.p4d.24xlarge --once
    # See exactly what it would do without touching anything:
    python scripts/grab_gpu_instance.py --space-name my-space --dry-run

Stop a running loop any time with Ctrl-C; it exits cleanly without leaving a
half-created app behind (a failed/capacity app is auto-deleted by SageMaker and
also cleaned up here before the next attempt).
"""

import argparse
import importlib.util
import json
import os
import pathlib
import sys
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

# --- SageMaker Distribution images -------------------------------------------
# The owning account differs PER REGION, so the ARN cannot be built by dropping the
# region into a template. The table is shared with the CDK stack and the Lambdas —
# loaded by path because this script runs standalone, outside the Lambda bundle and
# outside the CDK app. See infra/lambda/shared/smd_images.py for why a hardcoded
# us-west-2 account was a real bug here.
_SMD_TABLE = pathlib.Path(__file__).resolve().parent.parent / "infra" / "lambda" / "shared" / "smd_images.py"
_spec = importlib.util.spec_from_file_location("av30_smd_images", _SMD_TABLE)
if _spec is None or _spec.loader is None:  # pragma: no cover
    raise SystemExit(f"cannot load the SageMaker Distribution image table at {_SMD_TABLE}")
_smd_images = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_smd_images)

SMD_IMAGE_VERSION_ALIAS = "4.2.1"


def _cpu_image_arn(region: str) -> str:
    return _smd_images.smd_image_arn(region, "cpu")


def _gpu_image_arn(region: str) -> str:
    return _smd_images.smd_image_arn(region, "gpu")


# GPU-accelerated SageMaker instance-family prefixes (match config.py).
# Trailing dots are load-bearing: "ml.g7e.2xlarge" does not start with "ml.g7.".
_GPU_INSTANCE_PREFIXES = (
    "ml.g4dn.",
    "ml.g5.",
    "ml.g6.",
    "ml.g7e.",
    "ml.p3.",
    "ml.p4d.",
    "ml.p5.",
)

# Default candidate tier: the 24xlarge+ GPU boxes, cheapest-first. g6 (L4) before
# g5 (A10G) of the same size — L4 capacity is usually easier and the workshop's
# GPU modules are verified on g6.24xlarge.
#
# g7e is deliberately NOT in this list. It is recognised (prefix + rate above) so
# `--instances ml.g7e.2xlarge` works and prices correctly, but it stays opt-in:
# the lab has no g7e quota by default and no verified run on it, so it must not
# silently become what an unattended grab loop lands on.
DEFAULT_CANDIDATES = [
    "ml.g6.24xlarge",
    "ml.g5.24xlarge",
    "ml.g6.48xlarge",
    "ml.g5.48xlarge",
    "ml.p4d.24xlarge",
    "ml.p5.48xlarge",
]

# USD/hour, loaded from the SAME generated table the Lambdas use — keyed by REGION.
# It used to be a duplicated literal here, with the note "if you change one, change both",
# and the two copies had in fact already diverged (this file said g6.24xlarge 8.10 and
# p4d 32.77 where config.py said 8.344 and 25.251). Loaded by path for the same reason as
# the image table above: this script runs standalone, outside the Lambda bundle and the CDK
# app. instance_rates.py is pure generated data with no imports, so path-loading is safe.
_RATES_TABLE = (pathlib.Path(__file__).resolve().parent.parent
                / "infra" / "lambda" / "shared" / "instance_rates.py")
_rspec = importlib.util.spec_from_file_location("av30_instance_rates", _RATES_TABLE)
if _rspec is None or _rspec.loader is None:  # pragma: no cover
    raise SystemExit(f"cannot load the instance rate table at {_RATES_TABLE}")
_rates_mod = importlib.util.module_from_spec(_rspec)
_rspec.loader.exec_module(_rates_mod)
RATES_BY_REGION = _rates_mod.RATES_BY_REGION


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def log(msg: str) -> None:
    print(f"[{_now()}] {msg}", file=sys.stderr, flush=True)


def is_gpu_instance(instance_type: str) -> bool:
    """True if instance_type belongs to a GPU-accelerated family."""
    return instance_type.startswith(_GPU_INSTANCE_PREFIXES)


def hourly_rate(instance_type: str, region: str) -> float:
    """Informational $/hr for (type, region), or 0.0 if unknown.

    Returns 0.0 rather than raising: unlike the Lambdas — where an unpriced region means
    participants would be shown another region's prices — this figure only decorates a log
    line, and this script exists to RESCUE a stuck GPU app. Refusing to run because a rate
    is missing would be the wrong trade.
    """
    return RATES_BY_REGION.get(region, {}).get(instance_type, 0.0)


def is_capacity_failure(failure_reason: str) -> bool:
    """True if a FailureReason string looks like an AWS capacity shortage."""
    if not failure_reason:
        return False
    fr = failure_reason.lower()
    return any(
        s in fr
        for s in (
            "insufficientcapacity",
            "insufficientinstancecapacity",
            "capacityerror",
            "capacity",
        )
    )


# --- domain / space resolution ------------------------------------------------

def resolve_domain_id(sm, explicit: str | None) -> str:
    if explicit:
        return explicit
    domains = sm.list_domains().get("Domains", [])
    if len(domains) == 1:
        return domains[0]["DomainId"]
    if not domains:
        log("No SageMaker domains found in this account/region.")
        sys.exit(2)
    listing = ", ".join(d["DomainId"] for d in domains)
    log(f"Multiple domains found ({listing}); pass --domain-id.")
    sys.exit(2)


def _list_spaces(sm, domain_id: str) -> list:
    spaces = []
    paginator = sm.get_paginator("list_spaces")
    for page in paginator.paginate(DomainIdEquals=domain_id):
        spaces.extend(page.get("Spaces", []))
    return spaces


def resolve_space(sm, domain_id: str, space_name: str | None,
                  user_profile: str | None) -> str:
    if space_name:
        return space_name
    spaces = _list_spaces(sm, domain_id)
    if user_profile:
        owned = [
            s for s in spaces
            if (s.get("OwnershipSettings") or {}).get("OwnerUserProfileName")
            == user_profile
        ]
        if len(owned) == 1:
            return owned[0]["SpaceName"]
        log(f"Could not uniquely resolve a space for user profile {user_profile}.")
        sys.exit(2)
    if len(spaces) == 1:
        return spaces[0]["SpaceName"]
    listing = ", ".join(s["SpaceName"] for s in spaces)
    log(f"Multiple/zero spaces ({listing}); pass --space-name.")
    sys.exit(2)


# --- resource spec (the image-selection fix) ---------------------------------

def build_resource_spec(sm, domain_id: str, space_name: str, instance_type: str,
                        region: str, image_arn: str | None,
                        image_version_alias: str | None) -> dict:
    """Build a JupyterLab ResourceSpec for the target instance.

    Image selection (in priority order):
      1. --image-arn, if the caller passed one (explicit override wins).
      2. Otherwise, if the TARGET instance is a GPU family (ml.g*/ml.p*), the GPU
         Distribution image — so moving a CPU-provisioned space onto a GPU box is
         automatically CUDA-capable (the whole point of this script).
      3. Otherwise (CPU target), preserve the space's existing image.

    We deliberately never carry SageMakerImageVersionArn: pinning a specific
    version arn overrides SageMakerImageArn and freezes the image (same rationale
    as infra/lambda/shared/config.py:jupyterlab_resource_spec).
    """
    # Read the space's existing spec so we can preserve image (CPU case) + LCC.
    existing = {}
    try:
        desc = sm.describe_space(DomainId=domain_id, SpaceName=space_name)
        existing = (
            (desc.get("SpaceSettings") or {})
            .get("JupyterLabAppSettings", {})
            .get("DefaultResourceSpec", {})
        ) or {}
    except ClientError:
        pass

    if image_arn:
        resolved_image = image_arn
    elif is_gpu_instance(instance_type):
        # GPU target with no explicit override -> force the GPU CUDA image, even
        # if the space was provisioned on the CPU image. This is the fix: without
        # it, torch.cuda.is_available() is False on the GPU box.
        resolved_image = _gpu_image_arn(region)
    else:
        # CPU target -> keep whatever the space already had.
        resolved_image = existing.get("SageMakerImageArn") or _cpu_image_arn(region)

    resolved_alias = image_version_alias or SMD_IMAGE_VERSION_ALIAS

    spec = {
        "SageMakerImageArn": resolved_image,
        "SageMakerImageVersionAlias": resolved_alias,
        "InstanceType": instance_type,
    }
    # Preserve the notebook-sync lifecycle config if the space had one.
    lcc = existing.get("LifecycleConfigArn")
    if lcc:
        spec["LifecycleConfigArn"] = lcc
    return spec


# --- app lifecycle (mirrors config.py hardening) -----------------------------

def safe_delete_app(sm, domain_id: str, space_name: str,
                    app_type: str = "JupyterLab", app_name: str = "default") -> bool:
    try:
        sm.delete_app(DomainId=domain_id, SpaceName=space_name,
                      AppType=app_type, AppName=app_name)
        return True
    except sm.exceptions.ResourceNotFound:
        return False
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        msg = e.response.get("Error", {}).get("Message", "")
        if code == "ValidationException" and (
            "previously failed" in msg or "automatically deleted" in msg
            or "does not exist" in msg
        ):
            return False
        raise


def wait_for_app_deleted(sm, domain_id: str, space_name: str,
                         max_wait: int = 240) -> None:
    """Poll DescribeApp until the app is gone (Deleted/Failed or ResourceNotFound)."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            resp = sm.describe_app(DomainId=domain_id, SpaceName=space_name,
                                   AppType="JupyterLab", AppName="default")
            if resp.get("Status") in ("Deleted", "Failed"):
                return
        except sm.exceptions.ResourceNotFound:
            return
        time.sleep(5)
    raise TimeoutError(f"Timed out waiting for app to delete on {space_name}")


def wait_for_space_in_service(sm, domain_id: str, space_name: str,
                              max_wait: int = 180) -> None:
    """Poll DescribeSpace until the space returns to InService after update_space."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            resp = sm.describe_space(DomainId=domain_id, SpaceName=space_name)
            if resp.get("Status") == "InService":
                return
        except sm.exceptions.ResourceNotFound:
            return
        time.sleep(5)
    raise TimeoutError(f"Timed out waiting for space {space_name} to return to InService")


def create_app_when_ready(sm, domain_id: str, space_name: str, resource_spec: dict,
                          max_wait: int = 240) -> None:
    """create_app, retrying while the space's EBS volume is still re-attaching."""
    deadline = time.time() + max_wait
    attempt = 0
    while True:
        attempt += 1
        try:
            sm.create_app(DomainId=domain_id, SpaceName=space_name,
                          AppType="JupyterLab", AppName="default",
                          ResourceSpec=resource_spec)
            return
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            msg = e.response.get("Error", {}).get("Message", "")
            storage_not_ready = code == "ResourceInUse" and (
                "storage is not in Available" in msg or "not in Available status" in msg
            )
            if storage_not_ready and time.time() < deadline:
                log(f"  create_app attempt {attempt}: storage still settling, "
                    f"retrying in 10s")
                time.sleep(10)
                continue
            raise


def poll_app_status(sm, domain_id: str, space_name: str, poll_timeout: int) -> str:
    """Poll DescribeApp until InService / Failed, or poll_timeout elapses.

    Returns the terminal status: 'InService', 'Failed', or 'Timeout' (treated as a
    silent capacity wait — move on to the next candidate).
    """
    deadline = time.time() + poll_timeout
    while time.time() < deadline:
        try:
            resp = sm.describe_app(DomainId=domain_id, SpaceName=space_name,
                                   AppType="JupyterLab", AppName="default")
        except sm.exceptions.ResourceNotFound:
            time.sleep(5)
            continue
        status = resp.get("Status")
        if status == "InService":
            return "InService"
        if status == "Failed":
            fr = resp.get("FailureReason", "")
            log(f"  app Failed: {fr}")
            return "Failed"
        time.sleep(10)
    return "Timeout"


def console_url(region: str, domain_id: str, space_name: str) -> str:
    return (
        f"https://{region}.console.aws.amazon.com/sagemaker/home?region={region}"
        f"#/studio/{domain_id}/spaces/{space_name}"
    )


def try_instance(sm, domain_id: str, space_name: str, instance_type: str,
                 region: str, args) -> bool:
    """One full attempt on a single instance type. Returns True if it lands."""
    rate = hourly_rate(instance_type, region)
    rate_str = f" (~${rate:.2f}/hr)" if rate else ""
    log(f"Trying {instance_type}{rate_str} on {space_name} ...")

    spec = build_resource_spec(sm, domain_id, space_name, instance_type, region,
                               args.image_arn, args.image_version_alias)
    log(f"  image: {spec['SageMakerImageArn'].split('/')[-1]} "
        f"@ {spec.get('SageMakerImageVersionAlias')}")

    if args.dry_run:
        log(f"  [dry-run] would delete app, update_space to {instance_type}, "
            f"create_app with the spec above.")
        return True

    # delete -> wait deleted -> update_space -> wait InService -> create_app -> poll
    if safe_delete_app(sm, domain_id, space_name):
        wait_for_app_deleted(sm, domain_id, space_name)

    sm.update_space(
        DomainId=domain_id,
        SpaceName=space_name,
        SpaceSettings={"JupyterLabAppSettings": {"DefaultResourceSpec": spec}},
    )
    wait_for_space_in_service(sm, domain_id, space_name)

    create_app_when_ready(sm, domain_id, space_name, spec)
    status = poll_app_status(sm, domain_id, space_name, args.poll_timeout)

    if status == "InService":
        log(f"SUCCESS: {instance_type} is InService on {space_name}.")
        print(console_url(region, domain_id, space_name))
        return True

    # Failed (capacity) or Timeout -> clean up the failed app before the next try.
    if safe_delete_app(sm, domain_id, space_name):
        try:
            wait_for_app_deleted(sm, domain_id, space_name)
        except TimeoutError:
            pass
    log(f"  {instance_type}: {status} — moving on.")
    return False


def main() -> int:
    p = argparse.ArgumentParser(
        description="Auto-grab an available GPU instance for a JupyterLab space.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # No region literal. This tool DELETES and recreates the target JupyterLab app, so a
    # wrong-region default is destructive: with AWS_REGION unset it used to build a
    # us-west-2 client, auto-resolve the single domain there, and kill a live region-1
    # participant's workspace while the operator believed they were acting on region 2.
    p.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION"),
        help="Target region. Required: set --region or AWS_REGION. Never defaulted, "
             "because this tool recreates a participant's app and a wrong region "
             "destroys the wrong person's workspace.",
    )
    p.add_argument("--profile", default=None,
                   help="AWS profile name (default: standard credential chain)")
    p.add_argument("--domain-id", default=None,
                   help="SageMaker domain id (auto-detected if only one exists)")
    p.add_argument("--space-name", default=None,
                   help="JupyterLab space name (auto-detected if unambiguous)")
    p.add_argument("--user-profile", default=None,
                   help="Resolve the space owned by this user profile")
    p.add_argument(
        "--instances", default=None,
        help="Comma-separated candidate instance types, in the order to try them. "
             f"Default: cheapest-first over the 24xlarge+ GPU tier ({','.join(DEFAULT_CANDIDATES)}).",
    )
    p.add_argument(
        "--image-arn", default=None,
        help="Override SageMakerImageArn. Default: GPU Distribution image when the "
             "target instance is a GPU family, else keep the space's current image.",
    )
    p.add_argument("--image-version-alias", default=None,
                   help="Override SageMakerImageVersionAlias (e.g. '4.2.1').")
    p.add_argument("--poll-timeout", type=int, default=180,
                   help="Seconds to wait for an app to reach InService before "
                        "treating the attempt as a silent capacity wait and moving "
                        "on (default: 180)")
    p.add_argument("--retry-interval", type=int, default=60,
                   help="Seconds to sleep between full passes over the candidate "
                        "list (default: 60)")
    p.add_argument("--max-wait", type=int, default=3600,
                   help="Give up after this many seconds of looping (default: 3600)")
    p.add_argument("--once", action="store_true",
                   help="Single pass over the candidate list; do not loop.")
    p.add_argument("--force", action="store_true",
                   help="Replace an already-running GPU app instead of leaving it.")
    p.add_argument("--dry-run", action="store_true",
                   help="Resolve domain/space and print the plan without mutating.")
    args = p.parse_args()
    if not args.region:
        p.error("no region: pass --region or set AWS_REGION. This tool recreates a\n"
                "participant's JupyterLab app, so it refuses to guess.")

    session = (boto3.Session(profile_name=args.profile)
               if args.profile else boto3.Session())
    sm = session.client("sagemaker", region_name=args.region)

    domain_id = resolve_domain_id(sm, args.domain_id)
    space_name = resolve_space(sm, domain_id, args.space_name, args.user_profile)
    candidates = ([s.strip() for s in args.instances.split(",") if s.strip()]
                  if args.instances else list(DEFAULT_CANDIDATES))

    # SELF-SPACE GUARD: this script's first step is delete_app on the target
    # space. If you run it from a terminal INSIDE that very space, delete_app
    # tears down the JupyterLab app hosting this process — the script dies mid-way
    # (after delete, before update_space/create_app), so the space image is never
    # updated and the app comes back on the OLD image. (Observed in the field: a
    # CPU->GPU move that left the space on the CPU image because the terminal was
    # killed at delete_app.) Refuse to run against our own space unless the caller
    # really means it. Run this from a DIFFERENT machine/space, CloudShell, or a
    # laptop with the same credentials instead.
    if not args.dry_run:
        try:
            with open("/opt/ml/metadata/resource-metadata.json") as _f:
                _self_space = (json.load(_f) or {}).get("SpaceName")
        except Exception:
            _self_space = None
        if _self_space and _self_space == space_name and not args.force:
            log(f"REFUSING: this process is running INSIDE {space_name}, and the "
                f"first action is delete_app on that space — which would kill this "
                f"terminal before the image/instance change completes. Run this "
                f"from another space, CloudShell, or a laptop with the same AWS "
                f"credentials. (Pass --force to override, but the app restart WILL "
                f"drop your terminal.)")
            return 2

    log(f"Domain {domain_id}, space {space_name}, region {args.region}")
    log(f"Candidates (in order): {', '.join(candidates)}")

    # Unless --force, if a GPU app is already InService, leave it.
    if not args.force and not args.dry_run:
        try:
            resp = sm.describe_app(DomainId=domain_id, SpaceName=space_name,
                                   AppType="JupyterLab", AppName="default")
            cur = (resp.get("ResourceSpec") or {}).get("InstanceType")
            if resp.get("Status") == "InService" and cur and is_gpu_instance(cur):
                log(f"A GPU app is already InService ({cur}); pass --force to replace.")
                print(console_url(args.region, domain_id, space_name))
                return 0
        except sm.exceptions.ResourceNotFound:
            pass

    start = time.time()
    while True:
        for inst in candidates:
            try:
                if try_instance(sm, domain_id, space_name, inst, args.region, args):
                    return 0
            except KeyboardInterrupt:
                log("Interrupted — cleaning up any half-created app.")
                safe_delete_app(sm, domain_id, space_name)
                return 130
            except (ClientError, TimeoutError) as e:
                log(f"  {inst}: {type(e).__name__}: {e} — moving on.")
                continue
        if args.once:
            log("Single pass complete; no instance landed.")
            return 1
        if time.time() - start > args.max_wait:
            log(f"Reached --max-wait ({args.max_wait}s) without landing an instance. "
                f"Giving up.")
            return 1
        log(f"Full pass done; sleeping {args.retry_interval}s before retrying.")
        time.sleep(args.retry_interval)


if __name__ == "__main__":
    sys.exit(main())
