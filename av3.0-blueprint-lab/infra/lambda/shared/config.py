"""Shared configuration for AV 3.0 Blueprint Lab Lambda functions."""

import json
import logging
import os
import re
import time

import boto3
from botocore.exceptions import ClientError

_logger = logging.getLogger()


def aoss_collection_name(user_id: str) -> str:
    """AOSS collection name for a user — MUST byte-match M4's _aoss_name().

    M4 (notebooks/M4_OpenSearch_Semantic_Search.ipynb, cell 1) creates the
    OpenSearch Serverless collection with exactly this algorithm. delete_user
    and the teardown script must reproduce it precisely, or they look up the
    WRONG collection name and silently orphan a continuously-billing collection
    (the root cause of the av30-semantic-ky-5-34x orphan seen in the field).

    Keep this identical to M4's _aoss_name: lowercase, non [a-z0-9-] -> '-',
    first 8 chars, strip stray leading/trailing hyphens, ensure a letter start.
    """
    slug = re.sub(r"[^a-z0-9-]", "-", user_id.lower())[:8].strip("-") or "user"
    if not slug[0].isalpha():
        slug = f"u{slug}"[:8]
    return f"av30-semantic-{slug}"

# Environment variables
SAGEMAKER_DOMAIN_ID = os.environ.get("SAGEMAKER_DOMAIN_ID", "")
SESSIONS_TABLE_NAME = os.environ.get("SESSIONS_TABLE_NAME", "")
SHARED_BUCKET_NAME = os.environ.get("SHARED_BUCKET_NAME", "")
USER_BUCKET_NAME = os.environ.get("USER_BUCKET_NAME", "")
NOTEBOOK_TEMPLATES_PREFIX = os.environ.get("NOTEBOOK_TEMPLATES_PREFIX", "notebook-templates/")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")

# --- SageMaker Distribution image selection ---------------------------------
# JupyterLab apps must pin a Distribution image; without it SageMaker uses the
# domain/account default (a CPU build), so torch.cuda.is_available() is False on
# GPU instances and the GPU pre-flight checks in the GPU modules (M2, M3, M5-M9) fail.
# NOTE: this is NOT the jupyter-server-3 image used for the JupyterServer default in
# the CDK stack — the JupyterLab Distribution images are different.
#
# The owning account is region-specific (it is NOT one account published per-region),
# so the ARN is built from the table in smd_images.py rather than a hardcoded literal.
# See that module for why getting this wrong fails silently and per-participant.
from smd_images import smd_image_arn  # noqa: E402  (shared layer, same directory)


def _smd_arn(env_key: str, variant: str) -> str:
    """Env var if the stack supplied one, else derive it from the region table.

    Written as a function rather than os.environ.get(key, smd_image_arn(...)) because
    that form evaluates the default EAGERLY: a region missing from the table would
    raise at import time even when the env var already held the correct ARN, turning a
    working deploy into a cold-start crash.
    """
    return os.environ.get(env_key) or smd_image_arn(AWS_REGION, variant)


SMD_CPU_IMAGE_ARN = _smd_arn("SMD_CPU_IMAGE_ARN", "cpu")
SMD_GPU_IMAGE_ARN = _smd_arn("SMD_GPU_IMAGE_ARN", "gpu")
# "4.2.1" is the version verified working. Overridable via env; avoid "latest"
# so the image can't silently drift across workshop runs.
SMD_IMAGE_VERSION_ALIAS = os.environ.get("SMD_IMAGE_VERSION_ALIAS", "4.2.1")

# Size of the EBS volume a participant's space is created with, in GB. Injected by CDK from
# the SAME literal that sets the domain's DefaultEbsVolumeSizeInGb
# (infra/av30_constructs/sagemaker.py), so the provisioned volume and every Lambda that
# reasons about it cannot drift apart. Before this existed, expand_storage fell back to a
# hardcoded 5 while the domain default was separately whatever SageMaker chose.
#
# Growing is possible (expand_storage, +50/+200, ceiling MAX_STORAGE_GB). SHRINKING IS NOT —
# AWS does not allow reducing a space's EBS volume — so this value is a floor for the whole
# cohort's storage bill, not a starting guess.
DEFAULT_SPACE_STORAGE_GB = int(os.environ.get("DEFAULT_SPACE_STORAGE_GB", "200"))

# Notebook-sync JupyterLab LCC ARN (the domain default), passed by the stack so
# apps recreated by change_instance / expand_storage re-run notebook sync + env
# injection. Empty string => omit the LifecycleConfigArn.
NOTEBOOK_LIFECYCLE_CONFIG_ARN = os.environ.get("NOTEBOOK_LIFECYCLE_CONFIG_ARN", "")

# --- Region model: ONE region per deployment --------------------------------
# This lab deploys to exactly ONE region at a time (`./scripts/deploy.sh --region <r>`);
# a second region is a SEPARATE, independent deployment of the same stack — its own Studio
# domain, buckets, API, Cognito pool, dashboards and budget. See
# docs/en/ADDING_A_REGION.md.
#
# A multi-region control plane (REGION_CONFIG / TARGET_REGIONS / CONTROL_REGION plus
# client_for / domain_id_for / buckets_for / region_config) used to live here for a design
# where one control plane governed Studio domains in up to three regions. It was REMOVED,
# not just disabled, because:
#
#   * The CDK never set REGION_CONFIG or CONTROL_REGION, so it always collapsed to the
#     single deploy region — it was never exercised.
#   * The four cross-region factories had ZERO call sites in any handler.
#   * Left in place, a future change that populated REGION_CONFIG would silently convert
#     two independent labs into one control plane managing both, which is the opposite of
#     the chosen model — and the conversion would look like a config change, not a
#     redesign.
#
# The scalars above (SAGEMAKER_DOMAIN_ID, SHARED_BUCKET_NAME, USER_BUCKET_NAME, the image
# ARNs, the LCC ARN) describe THIS deployment's one region and are the only source of
# regional identity. AWS_REGION is a Lambda RESERVED variable, always populated by the
# runtime, so it is exactly "the region this deployment runs in".
#
# Participant rows still carry a `region` attribute. It is written once at provisioning and
# is IMMUTABLE — a UserProfile belongs to one Domain and a Domain is regional, so "move this
# participant" does not exist, only delete and re-provision. It is kept as a record of which
# deployment owns the row (useful when one team runs two regional labs), NOT as an
# instruction to act cross-region.



# GPU-accelerated SageMaker instance-family prefixes.
# NOTE the trailing dots: they are load-bearing. "ml.g6e.24xlarge" does NOT start
# with "ml.g6." (the char after g6 is "e", not "."), so every family needs its own
# entry. Getting this wrong fails SILENTLY — is_gpu_instance() returns False, the
# space gets the CPU image, and the notebook dies on
# `assert torch.cuda.is_available()` on a box with 4 idle GPUs.
# Only families that also have INSTANCE_RATES entries belong here. A prefix
# without a rate is harmless (change_instance rejects on the rate table) but
# implies support that does not exist — so g6e and g7 are deliberately absent.
#
# Keyed by prefix so the family -> GPU-model mapping and the "is this a GPU box"
# test cannot drift apart: _GPU_INSTANCE_PREFIXES is DERIVED from this dict, so
# adding a family here automatically teaches both. Models match the reference
# table further down this file (g4dn=T4, g5=A10G, g6=L4, p4d=A100, p5=H100).
_GPU_MODEL_BY_PREFIX = {
    "ml.g4dn.": "T4",
    "ml.g5.": "A10G",
    "ml.g6.": "L4",
    "ml.g7e.": "RTX PRO 6000",
    "ml.p3.": "V100",
    "ml.p4d.": "A100",
    "ml.p5.": "H100",
}
_GPU_INSTANCE_PREFIXES = tuple(_GPU_MODEL_BY_PREFIX)


def is_gpu_instance(instance_type: str) -> bool:
    """True if instance_type belongs to a GPU-accelerated family."""
    return instance_type.startswith(_GPU_INSTANCE_PREFIXES)


def gpu_model(instance_type: str) -> str | None:
    """GPU model name for an instance type, or None for a CPU instance.

    Returns None rather than "" or "none" because the admin Sessions page counts
    GPU sessions with `gpuType !== null`. Any non-null placeholder would make every
    CPU session count as a GPU session — which is exactly what happened while this
    field was absent from the API response entirely (undefined !== null is true).
    """
    for prefix, model in _GPU_MODEL_BY_PREFIX.items():
        if instance_type.startswith(prefix):
            return model
    return None


def image_for_instance(instance_type: str) -> str:
    """Return the SageMaker Distribution image ARN matching the instance family."""
    return SMD_GPU_IMAGE_ARN if is_gpu_instance(instance_type) else SMD_CPU_IMAGE_ARN


def jupyterlab_resource_spec(instance_type: str, *, include_lcc: bool = True) -> dict:
    """Build a JupyterLab ResourceSpec/DefaultResourceSpec dict for an instance.

    Includes the correct CPU/GPU Distribution image + version alias, the instance
    type, and (optionally) the notebook-sync lifecycle config so a recreated app
    re-syncs notebooks and injects env vars. Never sets SageMakerImageVersionArn
    (it would override SageMakerImageArn and freeze the image).
    """
    spec = {
        "SageMakerImageArn": image_for_instance(instance_type),
        "SageMakerImageVersionAlias": SMD_IMAGE_VERSION_ALIAS,
        "InstanceType": instance_type,
    }
    if include_lcc and NOTEBOOK_LIFECYCLE_CONFIG_ARN:
        spec["LifecycleConfigArn"] = NOTEBOOK_LIFECYCLE_CONFIG_ARN
    return spec


def safe_delete_app(sagemaker_client, domain_id: str, space_name: str,
                    app_type: str = "JupyterLab", app_name: str = "default") -> bool:
    """Delete a space's app, tolerating the cases where there is nothing to delete.

    Returns True if a delete was issued, False if the app was already gone.

    Two "already gone" cases must both be swallowed, or an instance change /
    storage resize / user delete 502s when the previous app is not cleanly
    running:
      * ResourceNotFound     — no app was ever created for the space.
      * ValidationException  — the app *previously failed* (e.g.
        EC2InsufficientCapacityError) and SageMaker AUTO-DELETED it. delete_app
        then raises "App [default] previously failed and was automatically
        deleted. For tracking purposes, apps are available in the ListApps API
        results for only 24 hours after failure." That is not an error for us —
        the app is already gone, so proceed to update_space/create_app.
    """
    try:
        sagemaker_client.delete_app(
            DomainId=domain_id,
            SpaceName=space_name,
            AppType=app_type,
            AppName=app_name,
        )
        return True
    except sagemaker_client.exceptions.ResourceNotFound:
        return False
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        msg = e.response.get("Error", {}).get("Message", "")
        # A previously-failed, auto-deleted app surfaces as ValidationException.
        if code == "ValidationException" and (
            "previously failed" in msg or "automatically deleted" in msg
            or "does not exist" in msg
        ):
            return False
        raise


def wait_for_app_deleted(sagemaker_client, domain_id: str, space_name: str,
                         app_type: str = "JupyterLab", app_name: str = "default",
                         max_wait: int = 240) -> None:
    """Poll DescribeApp until the app is gone (Deleted/Failed or ResourceNotFound).

    Raises TimeoutError if the app is still shutting down after max_wait. Kept
    free of HTTP concerns (no ApiError) so it can be shared by both the async
    apply path (where a raise simply fails the invocation) and any HTTP caller.
    """
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            resp = sagemaker_client.describe_app(
                DomainId=domain_id,
                SpaceName=space_name,
                AppType=app_type,
                AppName=app_name,
            )
            if resp.get("Status") in ("Deleted", "Failed"):
                return
        except sagemaker_client.exceptions.ResourceNotFound:
            return
        time.sleep(5)
    raise TimeoutError(f"Timed out waiting for app to delete on space {space_name}")


def write_progress_env(s3_client, bucket: str, user_id: str,
                      participant_token: str, api_url: str) -> bool:
    """Write users/<id>/.av30-progress.env so the notebooks can report progress.

    The notebook-sync LCC `aws s3 sync`s users/<id>/ into the home dir at app launch,
    so this lands as ~/.av30-progress.env and the mark-complete cells source
    AV30_API_URL + AV30_PROGRESS_TOKEN from it.

    This used to claim "no new IAM grant is needed: the file holds only this participant's
    own token — the same trust boundary as their browser session." That reasoning was
    WRONG. All participants share ONE execution role holding s3:GetObject on
    .../users/* with no condition (object actions have no s3:prefix condition key, so it
    cannot be scoped without per-participant roles), so writing the token here put a full
    impersonation credential — it authorizes the presigned-URL, instance-type and storage
    routes AS its owner — into a prefix every peer can read.

    Mitigated, not eliminated: the LCC DELETES this object right after injecting it into
    the app environment, so the window is provisioning -> first app launch rather than the
    whole workshop. The home-directory copy on EFS is what the notebooks actually read
    afterwards. Closing it fully needs per-participant execution roles.

    Shared because create_user wrote it and bulk_provision did not, so every
    bulk-provisioned participant silently had no progress tracking and their dashboard
    never lit up as they finished modules. Best-effort by design (a failed progress
    ping must not fail provisioning); returns True if written.
    """
    if not api_url:
        return False
    try:
        s3_client.put_object(
            Bucket=bucket,
            Key=f"users/{user_id}/.av30-progress.env",
            Body=(
                f'export AV30_API_URL="{api_url.rstrip("/")}"\n'
                f'export AV30_PROGRESS_TOKEN="{participant_token}"\n'
            ).encode("utf-8"),
            ContentType="text/plain",
        )
        return True
    except Exception:  # noqa: BLE001 — non-fatal; progress ping is best-effort
        return False


def wait_for_user_profile_in_service(sagemaker_client, domain_id: str,
                                     user_profile_name: str,
                                     max_wait: int = 120) -> None:
    """Poll DescribeUserProfile until the profile is InService.

    CreateUserProfile is asynchronous and CreateSpace rejects a profile that has not
    settled ("Unable to create Space ... because UserProfile ... is not in
    InService"). create_user waited for this inline; bulk_provision did not, so every
    bulk row failed on CreateSpace once the request/response shapes were fixed.
    Shared so the two provisioning paths cannot drift apart again.

    Raises RuntimeError on a terminal profile status and TimeoutError if it never
    settles — both surface as that row's `error` in the bulk response rather than
    failing the whole batch.
    """
    deadline = time.time() + max_wait
    while time.time() < deadline:
        status = sagemaker_client.describe_user_profile(
            DomainId=domain_id, UserProfileName=user_profile_name
        ).get("Status")
        if status == "InService":
            return
        if status in ("Failed", "Delete_Failed", "Update_Failed"):
            raise RuntimeError(
                f"UserProfile {user_profile_name} creation failed with status: {status}"
            )
        time.sleep(3)
    raise TimeoutError(
        f"Timed out waiting for UserProfile {user_profile_name} to become InService"
    )


def rollback_partial_provision(sagemaker_client, domain_id: str, user_id: str) -> str:
    """Delete the space/profile a failed provision left behind. NEVER raises.

    Compensation for a half-finished provision. Without it the leftover UserProfile is
    unreachable from the dashboard: delete_user keys on the DynamoDB row, which is
    written LAST, so it answers 404 while the profile (and its EFS home directory)
    lingers invisibly — and the user_id is random, so the admin cannot even name it.

    Both provisioning paths need this, not just the bulk one. A single-user create can
    fail at the same points, and one failure mode is now GUARANTEED by design: an
    unseeded region makes copy_notebook_templates raise on purpose (rather than hand out
    an empty workspace), which is exactly when a fresh region is first exercised.

    Returns "" when nothing needed removing, else a " (cleanup: ...)" suffix stating
    per-resource outcome, so a remaining orphan is visible instead of assumed gone.
    """
    notes = []
    space_name = f"{user_id}-space"

    # Ordering and waits here are not defensive padding — both were established by
    # running this against a real half-provisioned user in ap-northeast-2:
    #
    #  1. DeleteSpace is ASYNCHRONOUS and DeleteUserProfile refuses while any space is
    #     still attached ("ResourceInUse: Unable to delete UserProfile [...] because
    #     Space(s) are associated with it"). Measured: the space took ~20 s to vanish,
    #     so deleting the profile straight after failed every single time.
    #  2. CreateSpace is also asynchronous, and the failure this compensates for
    #     usually lands within a second of it — so the space is typically still
    #     Pending, and DeleteSpace on a Pending space raises ValidationException.
    #     Classifying ValidationException as "already gone" (which it means for
    #     DescribeSpace) silently skipped the space delete, left space_clear True, and
    #     produced exactly "(cleanup: profile NOT removed (ResourceInUse))" with the
    #     space still live. ValidationException is therefore treated as RETRY, never
    #     as absent; only ResourceNotFound* means absent.
    space_clear, note = _delete_space_and_wait(sagemaker_client, domain_id, space_name)
    if note:
        notes.append(note)

    if space_clear:
        try:
            sagemaker_client.delete_user_profile(
                DomainId=domain_id, UserProfileName=user_id)
            notes.append("profile removed")
        except Exception as ce:  # noqa: BLE001 — cleanup must not mask the real error
            code = _err_code(ce)
            if code not in _ABSENT_CODES:
                notes.append(f"profile NOT removed ({code or type(ce).__name__})")
    else:
        notes.append("profile left in place (space not gone)")

    return f" (cleanup: {'; '.join(notes)})" if notes else ""


# Only these mean "the resource is not there". NOT ValidationException: SageMaker uses
# it for "wrong state" too, and conflating the two is what stranded the space above.
_ABSENT_CODES = ("ResourceNotFound", "ResourceNotFoundException")


def _err_code(exc) -> str:
    return getattr(exc, "response", {}).get("Error", {}).get("Code", "")


def _delete_space_and_wait(sagemaker_client, domain_id: str, space_name: str,
                           max_wait: int = 90) -> tuple[bool, str]:
    """Delete the space and wait until it is really gone. Never raises.

    Returns (space_is_gone, note). Retries DeleteSpace while the space is in a
    not-yet-deletable state, then polls until it 404s.

    Budget: 90 s. create_user's Lambda timeout is 300 s and the UserProfile wait can
    already consume 120 s of it, and bulk_provision runs up to 20 of these
    concurrently inside ONE 300 s invocation — a rollback that hung would convert a
    failed provision into a timeout with no error body at all.
    """
    deadline = time.time() + max_wait
    requested = False
    while time.time() < deadline:
        if not requested:
            try:
                sagemaker_client.delete_space(DomainId=domain_id, SpaceName=space_name)
                requested = True
                continue  # poll for actual removal
            except Exception as ce:  # noqa: BLE001
                code = _err_code(ce)
                if code in _ABSENT_CODES:
                    return True, ""  # never created / already gone
                if code != "ValidationException":
                    return False, f"space NOT removed ({code or type(ce).__name__})"
                # Still settling (typically Pending) — fall through and retry.
        else:
            try:
                sagemaker_client.describe_space(
                    DomainId=domain_id, SpaceName=space_name)
            except ClientError as e:
                if _err_code(e) in _ABSENT_CODES:
                    return True, "space removed"
                return False, f"space state unknown ({_err_code(e)})"
            except Exception:  # noqa: BLE001
                return False, "space state unknown"
        time.sleep(3)

    return False, ("space removed but still deleting" if requested
                   else "space NOT removed (still not deletable after 90s)")


def wait_for_space_in_service(sagemaker_client, domain_id: str, space_name: str,
                              max_wait: int = 180) -> None:
    """Poll DescribeSpace until the space returns to InService.

    update_space briefly transitions the space out of InService; create_app
    would 502 in that window. Raises TimeoutError if it never settles.
    """
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            resp = sagemaker_client.describe_space(
                DomainId=domain_id, SpaceName=space_name
            )
            if resp.get("Status") == "InService":
                return
        except sagemaker_client.exceptions.ResourceNotFound:
            # Space gone entirely — nothing to wait for.
            return
        time.sleep(5)
    raise TimeoutError(
        f"Timed out waiting for space {space_name} to return to InService"
    )


def create_app_when_ready(sagemaker_client, domain_id: str, space_name: str,
                          resource_spec: dict, app_type: str = "JupyterLab",
                          app_name: str = "default", max_wait: int = 240) -> None:
    """create_app, retrying while the space's EBS volume is still settling.

    After update_space changes the instance type, the space returns to
    InService BEFORE its EBS volume finishes re-attaching. Calling create_app in
    that window raises:
        ResourceInUse: Unable to create app [...] because storage is not in
        Available status.
    describe_space exposes no storage-status field to poll, so we retry
    create_app with backoff until the volume is Available (or a genuinely
    different error surfaces). This is common when switching between two GPU
    instances (e.g. g6 -> g5) where the volume must re-attach.
    """
    deadline = time.time() + max_wait
    attempt = 0
    while True:
        attempt += 1
        try:
            sagemaker_client.create_app(
                DomainId=domain_id,
                SpaceName=space_name,
                AppType=app_type,
                AppName=app_name,
                ResourceSpec=resource_spec,
            )
            return
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            msg = e.response.get("Error", {}).get("Message", "")
            storage_not_ready = code == "ResourceInUse" and (
                "storage is not in Available" in msg or "not in Available status" in msg
            )
            if storage_not_ready and time.time() < deadline:
                _logger.info(
                    f"create_app attempt {attempt}: storage not ready for "
                    f"{space_name}, retrying in 10s"
                )
                time.sleep(10)
                continue
            raise

# Presigned URL expiry in seconds (8 hours)
PRESIGNED_URL_EXPIRY = 28800

# SageMaker instance rates (USD per hour) — THE authoritative table for this repo.
#
# SOURCE OF TRUTH: generated per region by scripts/refresh_instance_rates.py from the AWS
# Price List API (ServiceCode=AmazonSageMaker, platoinstancetype=Studio-JupyterLab). Never
# hand-edit instance_rates.py.
#
# This was a single hand-maintained us-west-2 snapshot that ALSO served as the participant
# instance allowlist (VALID_INSTANCE_TYPES in change_instance, and the dropdown built by
# instance_options). Both halves were wrong outside us-west-2, and both failed quietly:
#
#   * PRICES. ap-northeast-2 is ~+23% on every type (measured: t3.medium 0.050 -> 0.062,
#     g5.12xlarge 7.09 -> 8.718, g6.24xlarge 8.344 -> 10.26). Every figure shown to a
#     participant and every admin session estimate read ~23% LOW — the wrong direction for
#     a lab whose documented failure mode is spend nobody noticed.
#   * OFFERINGS. The keys were offered regardless of region, so a participant could pick a
#     type the region does not sell for Studio and their app simply failed to start.
#     Measured, per region, for the curated candidate set:
#         us-west-2 / us-east-1   34/35
#         ap-northeast-1          28/35   (no g7e)
#         ap-northeast-2          27/35   (no g7e, no p5)
#         eu-west-1               21/35   (no g6 family AT ALL, no g7e, no p5)
#     ml.p3.2xlarge has no Studio-JupyterLab product in any of the five.
#
# A region that has not been generated raises at import. That is deliberate: the previous
# behaviour — quote us-west-2 and hope — is exactly the silent-wrongness this replaces.
#
# NOT A QUOTA. A rate here only means the region SELLS the type. Whether this account may
# launch it is a separate per-(account x region) fact: ml.g6.* is priced in ap-northeast-2
# but its Studio quota there is 0.
#
# NOTHING IN THE REQUEST PATH CHECKS QUOTA TODAY. An earlier version of this comment said
# "instance_options resolves live quota at request time" — that was false: instance_options
# is dead code (zero call sites, keyed to placeholder module ids, imports no boto3), and
# change_instance validates only membership in this table. So a participant can still pick
# a type this region sells but the account has 0 quota for, and the failure surfaces as a
# stalled app rather than a rejection. The admin-side check is
# scripts/check_quotas.py --region <r> --participants N, which deploy.sh runs at the end of
# a deployment; wiring a GetServiceQuota call into change_instance is the real fix and has
# not been done.
#
# GPU GEOMETRY (the recurring source of confusion — size is NOT GPU count, and within a
# family a bigger size adds GPUs, never per-GPU VRAM):
#   g4dn = T4 16 GB | g5 = A10G 24 GB | g6 = L4 24 GB (NOT L40S — that is g6e)
#   g7e  = RTX PRO 6000 Blackwell 96 GB | p4d = A100 40 GB | p5 = H100 80 GB
#   4-GPU sizes: g5/g6 .12xlarge and .24xlarge ;  8-GPU: .48xlarge
#   g7e differs: 2xl/4xl/8xl = 1 GPU, 12xl = 2, 24xl = 4, 48xl = 8
# M5/M6 branch on PER-GPU VRAM (>=38 GB -> 720p + guardrails ON), and M9 on >=40 GB
# (single-GPU "verified path"). So no g5/g6 size reaches the top tier; g7e (96 GB), p4d
# (40 GB) and p5 (80 GB) do. 24 GB cards still COMPLETE the lab — see
# docs/en/ALPAMAYO_M9.md "Verified runs" (minADE 0.3779 m, Status: PASS).
from instance_rates import (  # noqa: E402  (shared layer, same directory)
    QUOTA_CODES,
    RATES_BY_REGION,
)


class UnpricedRegionError(RuntimeError):
    """No generated rate table for this deploy region."""


def _rates_for_region(region: str) -> dict:
    try:
        return RATES_BY_REGION[region]
    except KeyError:
        raise UnpricedRegionError(
            f"No Studio-JupyterLab rate table for {region!r}. Costs shown to participants "
            f"and admins would be another region's prices, and the instance dropdown would "
            f"offer types {region} may not sell. Generate it:\n"
            f"    ./scripts/refresh_instance_rates.py --region {region} --merge\n"
            f"Generated regions: {', '.join(sorted(RATES_BY_REGION))}"
        ) from None


INSTANCE_RATES = _rates_for_region(AWS_REGION)


def studio_quota_for(instance_type: str, *, client=None):
    """Live Studio-JupyterLab quota for `instance_type` in THIS region, or None if unknown.

    Prices and quotas are independent facts. A type can be priced here (so it passes the
    INSTANCE_RATES allowlist) yet have a quota of 0, in which case SageMaker accepts
    CreateApp and the app then fails to start. Measured in ap-northeast-2: the entire
    ml.g6.* family is priced but quota 0. Resolving the quota BEFORE acting turns that
    into an immediate, explainable rejection.

    One GetServiceQuota call (~55-110 ms measured) using the code baked into
    instance_rates.QUOTA_CODES — as opposed to paginating 2,258 SageMaker quotas, which is
    why the code is generated ahead of time and only the VALUE is fetched live.

    Returns None — meaning "unknown, do not block" — for every case where the number
    cannot be trusted, because blocking on a bad read would deny a type the account
    legitimately owns:

      * no code for the type (region has no such quota; a raise cannot be requested either)
      * NoSuchResourceException (the code is not offered in this region)
      * AccessDeniedException (the servicequotas grant is missing — must degrade, not fail)
      * throttling or any other ClientError

    Callers MUST therefore branch on `== 0`, never on falsiness: `not 0.0` and `not None`
    are both True, which would collapse "quota is zero" into "unknown" and vice versa.
    """
    code = QUOTA_CODES.get(instance_type)
    if not code:
        return None
    try:
        if client is None:
            import boto3  # local: keeps the import off the cold path of every Lambda

            client = boto3.client("service-quotas", region_name=AWS_REGION)
        response = client.get_service_quota(ServiceCode="sagemaker", QuotaCode=code)
        return float(response["Quota"]["Value"])
    except Exception as exc:  # noqa: BLE001 — availability beats precision here
        _logger.warning(
            "Could not resolve Studio quota for %s (%s=%s) in %s: %s; "
            "treating as unknown and allowing the request",
            instance_type,
            "QuotaCode",
            code,
            AWS_REGION,
            exc,
        )
        return None

# Module configuration for the workshop
MODULE_CONFIG = {
    "module-1": {
        "name": "Data Preparation",
        "notebook": "01-data-preparation.ipynb",
        "instance_type": "ml.t3.medium",
        "estimated_duration_minutes": 45,
    },
    "module-2": {
        "name": "Model Training",
        "notebook": "02-model-training.ipynb",
        "instance_type": "ml.m5.xlarge",
        "estimated_duration_minutes": 60,
    },
    "module-3": {
        "name": "Model Evaluation",
        "notebook": "03-model-evaluation.ipynb",
        "instance_type": "ml.m5.large",
        "estimated_duration_minutes": 30,
    },
    "module-4": {
        "name": "Model Deployment",
        "notebook": "04-model-deployment.ipynb",
        "instance_type": "ml.m5.large",
        "estimated_duration_minutes": 45,
    },
    "module-5": {
        "name": "Inference and Testing",
        "notebook": "05-inference-testing.ipynb",
        "instance_type": "ml.t3.medium",
        "estimated_duration_minutes": 30,
    },
}

# CORS headers
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,X-Api-Key,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
    "Content-Type": "application/json",
}
