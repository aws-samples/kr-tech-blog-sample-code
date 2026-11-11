"""AV 3.0 Blueprint Lab - SageMaker Construct.

SageMaker Studio Domain in PublicInternetOnly mode with execution role and lifecycle config.
"""

import base64
import hashlib
import importlib.util
from pathlib import Path

from constructs import Construct

from av30_constructs import DEFAULT_SPACE_STORAGE_GB

import aws_cdk as cdk
from aws_cdk import (
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_s3 as s3,
    aws_sagemaker as sagemaker,
)


def _load_smd_images():
    """region -> SageMaker Distribution owner account, from the Lambda shared layer.

    Same loader as api.py: the table is read by path so the stack and the Lambda
    runtime share ONE copy. See infra/lambda/shared/smd_images.py.
    """
    path = Path(__file__).resolve().parent.parent / "lambda" / "shared" / "smd_images.py"
    spec = importlib.util.spec_from_file_location("av30_smd_images", path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_smd_images = _load_smd_images()
# Re-exported so av30_stack.py (and anything else in the CDK app) can reach the
# tables without a third copy of the by-path loader.
smd_image_arn = _smd_images.smd_image_arn
first_party_image_arn = _smd_images.first_party_image_arn
supported_regions = _smd_images.supported_regions


# NOT the idle control that actually applies to participants. This LCC is registered for
# app type JupyterServer (see studio_lifecycle_config_app_type below), and participants
# launch JupyterLab apps, so this script never runs for them. The effective setting is the
# domain's AppLifecycleManagement.IdleSettings — see SageMakerConstruct._idle_timeout_minutes.
# Lowering the 10800 below would change nothing; it is kept only so a JupyterServer app,
# if one is ever created, is not left with no idle handling at all.
_IDLE_SHUTDOWN_SCRIPT = """\
#!/bin/bash
set -eu
IDLE_TIMEOUT_SECONDS=10800
echo "Configuring idle kernel shutdown after ${IDLE_TIMEOUT_SECONDS}s (3 hours)"
cat > /etc/jupyter/jupyter_notebook_config.py <<EOF
c.MappingKernelManager.cull_idle_timeout = ${IDLE_TIMEOUT_SECONDS}
c.MappingKernelManager.cull_connected = True
c.MappingKernelManager.cull_busy = False
EOF
echo "Restarting Jupyter server to apply idle shutdown configuration"
restart-jupyter-server
"""


# JupyterLab bootstrap script. Two jobs on app launch:
#   1. Sync the participant's notebooks from their S3 workspace prefix into the
#      JupyterLab home (the space's EBS volume) so they appear in the file browser.
#   2. Inject config env vars (USER_PROFILE, SHARED_BUCKET, USER_BUCKET, plus
#      BLUEPRINT_* aliases) so the tutorial notebooks resolve the correct
#      per-user profile and the real deployed bucket names instead of the
#      hardcoded placeholders they ship with.
#
# The bucket names are injected via .replace with their CDK tokens, then the
# whole script is base64-encoded with cdk.Fn.base64 (a DEPLOY-time intrinsic) so
# the tokens resolve — Python's base64.b64encode would freeze the unresolved
# ${Token[...]} markers into the output. The per-user profile name is read at
# runtime from the app metadata file.
#
# Env injection targets an IPython startup file, NOT ~/.bashrc or
# /etc/profile.d: the Jupyter kernel is launched non-interactively, so login/
# profile shells never run and their exports would be invisible to os.environ
# in a notebook cell (this is exactly why USER_PROFILE previously fell back to
# "default"). The startup file runs inside every kernel process. bashrc +
# profile.d exports are also written for terminal convenience.
#
# Non-fatal throughout: neither a sync failure nor an env-write failure may
# block the app from starting.
# Bump ONLY for changes the template-text hash cannot see — i.e. changes to the
# *substituted values* rather than the script body (the bucket rename that added
# the -{region} suffix is exactly such a change). Ordinary edits to
# _NOTEBOOK_SYNC_SCRIPT_TEMPLATE below rotate the LCC name on their own.
_LCC_CONTENT_REV = "r2-region-suffixed-buckets"
# Same idea for the idle-shutdown LCC (see SageMakerConstruct).
_IDLE_CONTENT_REV = "r1"

_NOTEBOOK_SYNC_SCRIPT_TEMPLATE = """\
#!/bin/bash
set -eux
USER_BUCKET="__USER_BUCKET_NAME__"
SHARED_BUCKET="__SHARED_BUCKET_NAME__"
META=/opt/ml/metadata/resource-metadata.json
if [ ! -f "$META" ]; then
  echo "resource-metadata.json not found; skipping notebook bootstrap"
  exit 0
fi
USER_PROFILE=$(python3 -c "import json;print(json.load(open('$META')).get('UserProfileName',''))")
if [ -z "$USER_PROFILE" ]; then
  echo "UserProfileName empty; skipping notebook bootstrap"
  exit 0
fi

# --- 1. Sync notebooks S3 -> EFS home (non-fatal) ---
echo "Syncing s3://${USER_BUCKET}/users/${USER_PROFILE}/ -> /home/sagemaker-user/"
aws s3 sync "s3://${USER_BUCKET}/users/${USER_PROFILE}/" /home/sagemaker-user/ --exact-timestamps \\
  || echo "WARN: notebook sync failed (non-fatal)"

# --- 2. Inject config env vars for the tutorial notebooks (non-fatal) ---
# IPython startup file: sourced by every kernel process (login shells are not).
STARTUP_DIR=/home/sagemaker-user/.ipython/profile_default/startup
mkdir -p "$STARTUP_DIR" || true
cat > "$STARTUP_DIR/00-av30-env.py" <<PYEOF || true
import os
os.environ.setdefault("USER_PROFILE", "${USER_PROFILE}")
os.environ.setdefault("SHARED_BUCKET", "${SHARED_BUCKET}")
os.environ.setdefault("USER_BUCKET", "${USER_BUCKET}")
os.environ.setdefault("BLUEPRINT_PROFILE", "${USER_PROFILE}")
os.environ.setdefault("BLUEPRINT_S3_BUCKET", "${USER_BUCKET}")
PYEOF

# --- 3. B2 progress env: source the participant's own progress credentials ---
# create_user wrote users/<id>/.av30-progress.env (AV30_API_URL +
# AV30_PROGRESS_TOKEN); step 1's `aws s3 sync` above pulled it to the home dir.
# Parse those two exports into the SAME IPython startup file so the notebook
# mark-complete cells can POST progress. No DDB read / no new IAM — it is just a
# file already in the participant's own workspace. Best-effort (non-fatal).
#
# `set +x` IS THE SECURITY CONTROL HERE — do not remove it, and do not move the
# token handling outside it. This script runs under `set -eux` (top of file), and
# xtrace leaks the token to CloudWatch by TWO separate routes, both measured:
#   1. sourcing the env file traces the expanded assignment
#        ++ export AV30_PROGRESS_TOKEN=<the participant's token>
#   2. the heredoc below traces its expanded body as well
# Those traces land in /aws/sagemaker/<...>/LifecycleConfigOnStart — ONE log group
# shared by every participant — and at the time the single shared execution role GRANTED
# logs:GetLogEvents + logs:DescribeLogStreams on /aws/sagemaker/*. So any participant
# could read any other participant's API token out of the log, and the token does not
# expire. Verified end to end: role av30lab-sagemaker-execution-role-us-west-2, Sid
# CloudWatchLogsAccess.
#
# Both halves are now closed: this script wraps the token handling in `set +x` (below),
# and GetLogEvents was dropped from CloudWatchLogsAccess. Keep the `set +x` regardless —
# it is what stops the leak at the source, and the IAM change is only defence in depth.
set +x
PROGRESS_ENV=/home/sagemaker-user/.av30-progress.env
if [ -f "$PROGRESS_ENV" ]; then
  # shellcheck disable=SC1090
  . "$PROGRESS_ENV" || true
  if [ -n "${AV30_API_URL:-}" ] && [ -n "${AV30_PROGRESS_TOKEN:-}" ]; then
    cat >> "$STARTUP_DIR/00-av30-env.py" <<PROGEOF || true
os.environ.setdefault("AV30_API_URL", "${AV30_API_URL}")
os.environ.setdefault("AV30_PROGRESS_TOKEN", "${AV30_PROGRESS_TOKEN}")
PROGEOF
    # Shrink the token's exposure window from "the whole workshop" to "until first app
    # launch". Every participant shares one execution role with
    # s3:GetObject on .../users/* and no condition (object actions have no s3:prefix
    # condition key, so it cannot be scoped without per-participant roles), which means a
    # peer could read this file — and the token it holds is a full impersonation
    # credential: it authorizes the presigned-URL, instance-type and storage routes AS
    # its owner.
    #
    # Safe to delete because it is no longer needed from S3: it has just been injected
    # into this app's IPython startup file, the copy in the home directory lives on EFS
    # and survives app restarts, and the sync above runs WITHOUT --delete so a later
    # launch will not remove the local copy. reset_workspace already clears this prefix
    # without recreating the file, so "no S3 copy" is an existing, working state.
    aws s3 rm "s3://${USER_BUCKET}/users/${USER_PROFILE}/.av30-progress.env" \\
      >/dev/null 2>&1 || true
  fi
fi
set -x

# Terminal convenience: write the same vars to a home env file and source it
# from .bashrc for interactive shells (independent of the kernel path above).
cat > /home/sagemaker-user/.av30-env.sh <<SHEOF || true
export USER_PROFILE="${USER_PROFILE}"
export SHARED_BUCKET="${SHARED_BUCKET}"
export USER_BUCKET="${USER_BUCKET}"
export BLUEPRINT_PROFILE="${USER_PROFILE}"
export BLUEPRINT_S3_BUCKET="${USER_BUCKET}"
SHEOF
grep -q 'av30-env.sh' /home/sagemaker-user/.bashrc 2>/dev/null \\
  || echo '[ -f /home/sagemaker-user/.av30-env.sh ] && . /home/sagemaker-user/.av30-env.sh' >> /home/sagemaker-user/.bashrc \\
  || true

echo "Notebook bootstrap complete (sync + env injection)"
"""


class SageMakerConstruct(Construct):
    """SageMaker Studio Domain with execution role and lifecycle configuration.

    Attributes:
        domain_id: The SageMaker Studio Domain ID.
        execution_role: IAM role assumed by SageMaker Studio users.
        lifecycle_config_arn: ARN of the lifecycle configuration for idle shutdown.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.Vpc,
        shared_data_bucket: s3.Bucket,
        user_workspace_bucket: s3.Bucket,
        sagemaker_image_arn: str,
        participant_instance_types: list[str],
    ) -> None:
        super().__init__(scope, construct_id)

        # The instance types the execution role may start a Studio app on: the SAME list the
        # Lambdas get as PARTICIPANT_INSTANCE_TYPES (resolved once at synth by
        # _participant_instance_types in stacks/av30_stack.py). Refuse at synth what would
        # make the Deny below wrong: an empty list (every app refused but "system"), or a
        # value with an IAM wildcard (StringNotLike would treat "*" or "?" as a pattern and
        # let other types through).
        if not participant_instance_types:
            raise ValueError("participant_instance_types is empty; refusing to synth")
        _bad = [t for t in participant_instance_types if "*" in t or "?" in t]
        if _bad:
            raise ValueError(f"participant_instance_types holds wildcard values: {_bad}")

        # Execution role for SageMaker Studio users.
        # REGION SUFFIX IS REQUIRED: IAM is a global, account-scoped namespace, so
        # an unsuffixed physical name makes the SECOND region's stack fail at
        # CREATE with EntityAlreadyExists. Aws.REGION resolves at deploy time.
        self._execution_role = iam.Role(
            self,
            "ExecutionRole",
            role_name=f"av30lab-sagemaker-execution-role-{cdk.Aws.REGION}",
            assumed_by=iam.ServicePrincipal("sagemaker.amazonaws.com"),
            description="Execution role for AV 3.0 Blueprint Lab SageMaker Studio users",
        )

        # Let SageMaker stamp each role session with aws:SourceIdentity (the user
        # profile name). STEP 1 of a two-step upgrade: this is a no-op until the
        # domain's ExecutionRoleIdentityConfig is set to USER_PROFILE_NAME in a
        # later deploy. KEEP IT even if that setting is later turned back to
        # DISABLED: while the domain asks for SourceIdentity, a trust policy
        # without sts:SetSourceIdentity makes CreateApp and job creation fail.
        self._execution_role.assume_role_policy.add_statements(
            iam.PolicyStatement(
                actions=["sts:SetSourceIdentity"],
                principals=[iam.ServicePrincipal("sagemaker.amazonaws.com")],
            )
        )

        # S3 read access on shared-data bucket (all objects)
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="SharedDataBucketRead",
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:GetObject",
                    "s3:GetObjectVersion",
                    "s3:ListBucket",
                ],
                resources=[
                    shared_data_bucket.bucket_arn,
                    f"{shared_data_bucket.bucket_arn}/*",
                ],
            )
        )

        # NO WRITE anywhere on the shared-data bucket — deliberately, and do not add
        # one back "just for hf-cache/". Every participant runs as this one role, and
        # every participant's kernel loads hf-cache/: M5/M6/M9 restore hf-cache/hub/
        # as their HF_HOME, and M9 opens hf-cache/alpamayo-demo/*.pt with
        # torch.load(weights_only=False), which unpickles and so runs code. A write
        # grant here lets participant A run code as participant B, which also
        # defeats any per-user isolation of the user-workspace bucket below.
        # The admin seeds hf-cache/ from a workstation with admin credentials
        # (scripts/cache_hf_tree.sh or a bucket-to-bucket copy) — never by putting
        # admin keys into a Studio terminal (ADMIN_GUIDE §6.3).

        # PER-PARTICIPANT S3 ISOLATION WITH ONE SHARED ROLE: aws:SourceIdentity.
        #
        # The domain sets DomainSettings.ExecutionRoleIdentityConfig = USER_PROFILE_NAME
        # (see the CfnDomain below), so SageMaker stamps every session of this role with
        # sts:SourceIdentity = the caller's user profile name, which the trust statement
        # above allows. create_user makes UserProfileName == userId == the S3 prefix, so
        # ${aws:SourceIdentity} names exactly the caller's own users/<id>/ prefix.
        #
        # This replaces two wrong claims that used to sit here: that the object grant was
        # "scoped via the SageMakerUserProfile principal tag when present" (no condition was
        # ever attached, so it was users/* for everyone), and that per-user scoping needed
        # one IAM role per participant. Principal tags never reached the app session; the
        # source identity is the per-session value that does.
        #
        # FAIL-CLOSED by construction. Per the IAM docs, a policy variable whose key is
        # absent from the request matches nothing, so a session without a source identity
        # (an app started before the domain setting was applied, or a job the identity did
        # not propagate to) gets AccessDenied on every key under users/, its own included.
        # It never falls back to the whole prefix. Whether new-Studio
        # JupyterLab apps, the LCC, and M11/M12 jobs carry the value is confirmed only by a
        # live deployment (ADMIN_GUIDE §8).
        #
        # Object actions: the resource itself is the scope.
        # The doubled braces are f-string escapes: the template must carry the literal
        # policy variable ${aws:SourceIdentity}.
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="UserWorkspaceObjectReadWrite",
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                ],
                resources=[
                    f"{user_workspace_bucket.bucket_arn}/users/${{aws:SourceIdentity}}/*",
                ],
            )
        )

        # ListBucket: the bucket ARN is the resource, so the scope has to be the s3:prefix
        # condition. Two shapes are deliberately NOT used:
        #   * StringLikeIfExists: a list with no prefix (the whole bucket) would match.
        #   * a slash-less "users/${aws:SourceIdentity}" pattern: listing prefix "users/abc"
        #     returns the key names of users/abcd/... as well.
        # Every caller in the lab lists with a prefix that starts "users/<own id>/"
        # (LCC sync, M10 `aws s3 ls`, M11 pre-flight, the SDK's default_bucket_prefix probe
        # "users/<id>/m11"). HeadBucket and a bare `aws s3 ls s3://<bucket>/` carry no
        # prefix and are denied, as they already were under the users/* condition.
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="UserWorkspaceListBucket",
                effect=iam.Effect.ALLOW,
                actions=["s3:ListBucket"],
                resources=[user_workspace_bucket.bucket_arn],
                conditions={
                    "StringLike": {
                        "s3:prefix": ["users/${aws:SourceIdentity}/*"],
                    },
                },
            )
        )

        # CORRECTIONS TO THE NOTEBOOK-SYNC LCC TEXT (_NOTEBOOK_SYNC_SCRIPT_TEMPLATE), kept
        # here because the template must not change by a single byte in this revision:
        #   * "Shrink the token's exposure window" says every participant holds s3:GetObject
        #     on .../users/* with no condition, so a peer could read
        #     users/<id>/.av30-progress.env. No longer true: with the two statements above,
        #     only sessions whose source identity is <id> (plus the admin's own credentials
        #     and the provisioning Lambdas' roles) can read it. The delete-after-inject step
        #     stays as defence in depth.
        #   * "S3 -> EFS home" and "lives on EFS": a JupyterLab space's home is the space's
        #     EBS volume, not the domain EFS.
        # Why not just edit the template: its hash is part of the LCC name (_lcc_rev below),
        # so any byte change rotates the LCC, and every existing space keeps a
        # DefaultResourceSpec naming the old LCC ARN. Whether Studio's "Run space" still
        # works in that state is unverified. Fix the text together with a planned rotation.

        # Scoped SageMaker permissions (not full AmazonSageMakerFullAccess).
        #
        # EVERY participant shares THIS ONE ROLE — it is the domain's
        # default_user_settings.execution_role and create_user does not override it per
        # profile. So at run time participant A's notebook and participant B's notebook
        # present the SAME ROLE ARN. What differs is request context SageMaker adds per
        # participant: ${sagemaker:UserProfileName} on SageMaker API calls (used below),
        # and, since the domain sets ExecutionRoleIdentityConfig = USER_PROFILE_NAME, the
        # session's aws:SourceIdentity on calls to every service (used for S3 above and for
        # the M11 pipeline and M12 training-job ARNs below).
        #
        # An earlier version of this comment claimed that made per-participant isolation
        # impossible without one IAM role per user profile. THAT WAS WRONG, and the error
        # participants hit proved it: SageMaker publishes the caller's own identity as the
        # policy variables ${sagemaker:DomainId} and ${sagemaker:UserProfileName}, and
        # publishes the target space's owner as the condition key
        # sagemaker:OwnerUserProfileArn. Comparing the two isolates peers with ONE shared
        # role. AWS documents exactly this policy for private spaces
        # ("Give your users access to spaces", SMStudioRestrictSpacesToOwnerUserProfile),
        # and the AWS ML blog "Implement user-level access control for multi-tenant ML
        # platforms on Amazon SageMaker AI" names this as the mechanism for a shared domain.
        #
        # The prerequisite is already met: create_user creates every space with
        # OwnershipSettings.OwnerUserProfileName = <userId> and SharingType = Private
        # (infra/lambda/create_user/handler.py), verified on a live deployment.
        #
        # Resource ARNs use ${sagemaker:DomainId} rather than the real domain id ON PURPOSE.
        # This role IS the domain's default execution role, so the domain depends on the
        # role; referencing domain.attr_domain_id here would invert that and make
        # CloudFormation reject the stack with a circular dependency. The policy variable
        # resolves at request time to the caller's own domain, which is the same value.
        #
        # WHY EACH PARTICIPANT-FACING GRANT EXISTS — measured in ap-northeast-2, 2026-09-26,
        # by clicking the buttons as a participant:
        #   UpdateSpace                Studio's space page "Run space" button calls it to
        #                              persist the form before CreateApp. Without it:
        #                              "not authorized to perform: sagemaker:UpdateSpace".
        #   CreatePresignedDomainUrl   Studio's "Open JupyterLab" button calls it for the
        #                              participant's OWN user profile. Without it the app
        #                              runs but cannot be opened from Studio, and Studio
        #                              shows a permanent "Permission issue detected"
        #                              banner. An earlier comment here asserted
        #                              participants "never need" this because the
        #                              dashboard's Lambda mints the URL — true only for the
        #                              dashboard's own button, not for Studio's.
        #   CreateApp / DeleteApp      launching and stopping their JupyterLab app.
        #   AddTags                    SageMaker auto-tags the App on launch; without it
        #                              CreateApp fails with AccessDenied on AddTags.
        #
        # STILL NOT GRANTED, deliberately: CreateSpace and DeleteSpace (create_user /
        # delete_user own the lifecycle), ListUserProfiles and ListDomains (cohort
        # enumeration), DeleteTags (unused).
        #
        # RESIDUAL RISK, reduced but not zero:
        #   * Describe*/List* is still resources=["*"], so a participant can SEE peer
        #     spaces and apps. Narrowing it breaks sagemaker.get_execution_role() (used by
        #     M11/M12), which resolves the role through
        #     DescribeDomain/DescribeUserProfile/DescribeSpace. Reads are information
        #     disclosure inside a trusted cohort, not control.
        #   * CreateApp/DeleteApp is still resources=["*"] with no owner condition — see
        #     the long note on that statement for why it is staged rather than scoped now.
        #     Until it is tightened, a participant who runs boto3 in their notebook can
        #     start or stop an app on any space in this domain. The instance type is capped
        #     separately, by DenyNonParticipantInstanceTypes below, to the dashboard's list;
        #     how far that Deny reaches is itself only confirmed live (see its note). Past
        #     it, the per-type Studio quota and the daily budget alarm still bound the cost.
        #   * Not scoped by aws:SourceIdentity, so still shared across the cohort:
        #     processing-job/* (pipeline-generated names carry no profile, so a peer can
        #     Describe/Stop another's M11 step), aoss:APIAccessAll on collection/* (M4),
        #     CloudWatch Logs writes on /aws/sagemaker/*, and read of the whole shared-data
        #     bucket. ADMIN_GUIDE §0 lists these for operators.

        _sm_region = cdk.Stack.of(self).region
        _sm_account = cdk.Stack.of(self).account
        # The caller's own user-profile ARN, resolved per request. Used both as the resource
        # of CreatePresignedDomainUrl and as the value the space/app owner must equal.
        _own_user_profile = (
            f"arn:aws:sagemaker:{_sm_region}:{_sm_account}:user-profile/"
            "${sagemaker:DomainId}/${sagemaker:UserProfileName}"
        )
        # "this resource belongs to the caller, and it is a private space" — the pair that
        # turns one shared role into per-participant isolation.
        _owned_private = {
            "ArnLike": {"sagemaker:OwnerUserProfileArn": _own_user_profile},
            "StringEquals": {"sagemaker:SpaceSharingType": "Private"},
        }

        # Reads: broad on purpose (see RESIDUAL RISK above).
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="SageMakerStudioRead",
                effect=iam.Effect.ALLOW,
                actions=[
                    "sagemaker:DescribeDomain",
                    "sagemaker:DescribeUserProfile",
                    "sagemaker:DescribeSpace",
                    "sagemaker:DescribeApp",
                    "sagemaker:ListApps",
                    "sagemaker:ListSpaces",
                    "sagemaker:ListTags",
                ],
                resources=["*"],
            )
        )

        # Start/stop the participant's app.
        #
        # STILL resources=["*"] WITH NO CONDITION, ON PURPOSE — this is the one grant that
        # must not be gated on an unverified condition. It is the only thing that lets a
        # participant get a workspace at all, and if the ${sagemaker:*} variables below do
        # not resolve the way AWS documents, a scoped version here would deny EVERY
        # participant EVERY app. That is strictly worse than the information disclosure it
        # would close.
        #
        # Measured 2026-09-26 with iam:SimulateCustomPolicy: a statement whose Resource or
        # Condition value contains ${sagemaker:DomainId} / ${sagemaker:UserProfileName}
        # evaluates to implicitDeny in the simulator, while the identical statement with
        # those values spelled out literally evaluates to allowed. The IAM docs for
        # SimulateCustomPolicy say the simulator "results can differ from your live AWS
        # environment", and AWS's own reference policy for private spaces uses exactly
        # these variables, so the most likely reading is that the simulator does not
        # substitute service-specific variables. "Most likely" is not good enough to put in
        # front of the workspace-start path.
        #
        # TIGHTEN THIS ONCE THE VARIABLES ARE PROVEN LIVE. The two scoped statements below
        # are the proof: they are additive, so if the variables do NOT resolve they simply
        # match nothing and today's behaviour is unchanged. When a participant can click
        # Studio's "Run space" (needs the scoped UpdateSpace) and "Open JupyterLab" (needs
        # the scoped CreatePresignedDomainUrl) without an AccessDenied, the variables DO
        # resolve — at that point replace this statement with:
        #     resources=[f"arn:aws:sagemaker:{region}:{account}:app/${{sagemaker:DomainId}}/*"],
        #     conditions=_owned_private,
        # and re-verify that a participant can still start an app.
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="SageMakerStudioAppLifecycle",
                effect=iam.Effect.ALLOW,
                actions=["sagemaker:CreateApp", "sagemaker:DeleteApp"],
                resources=["*"],
            )
        )

        # Reconfigure their OWN private space (Studio's "Run space" / storage + instance
        # edits). DeleteSpace is intentionally absent.
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="SageMakerOwnPrivateSpaceUpdate",
                effect=iam.Effect.ALLOW,
                actions=["sagemaker:UpdateSpace"],
                resources=[
                    f"arn:aws:sagemaker:{_sm_region}:{_sm_account}:space/"
                    "${sagemaker:DomainId}/*"
                ],
                conditions=_owned_private,
            )
        )

        # Open Studio/JupyterLab as THEMSELVES. The resource IS the scope: a participant
        # cannot mint a session for another profile, which is what made the unscoped form
        # the worst grant in the original set.
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="SageMakerPresignedUrlOwnProfileOnly",
                effect=iam.Effect.ALLOW,
                actions=["sagemaker:CreatePresignedDomainUrl"],
                resources=[_own_user_profile],
            )
        )

        # Explicit DENY so it cannot be satisfied by the Allow above. The UpdateSpace grant
        # conditions on WHOSE space it is, not on WHAT is being changed, so without this a
        # participant could flip their own space's RemoteAccess to ENABLED and open a Remote
        # IDE path to a workspace the lab only ever intends to be reached through the
        # dashboard's presigned URL. Bounded today (the role has no sagemaker:StartSession),
        # but the posture change would happen with no admin action and no dashboard record.
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="DenyEnablingSpaceRemoteAccess",
                effect=iam.Effect.DENY,
                actions=["sagemaker:CreateSpace", "sagemaker:UpdateSpace"],
                resources=[f"arn:aws:sagemaker:{_sm_region}:{_sm_account}:space/*"],
                conditions={"StringEquals": {"sagemaker:RemoteAccess": "ENABLED"}},
            )
        )

        # Explicit DENY on any Studio app instance type outside the participant list, so
        # Studio's own controls ("Run space", or boto3 in a notebook) cannot start what
        # change_instance refuses. Without it, SageMakerStudioAppLifecycle (CreateApp on *)
        # and SageMakerOwnPrivateSpaceUpdate let a participant put their space on, say,
        # ml.p5.48xlarge ($63.30/hr in us-west-2), stopped only by its quota.
        #
        # Shape: AWS's documented guardrail for Studio instance types. sagemaker:InstanceTypes
        # is an ArrayOfString key that the Service Authorization Reference lists for both
        # CreateApp and UpdateSpace. ForAnyValue:StringNotLike is true when any requested type
        # matches none of the values, so one off-list type is enough to deny. "system" is the
        # instance type of a JupyterServer app, which has no ml.* type.
        #
        # What it does NOT cover, or covers only if SageMaker populates the key — UNVERIFIED
        # until a live deployment (ADMIN_GUIDE §2a has the probes):
        #   * a request that carries no instance type. ForAnyValue over an absent key is
        #     false, so the Deny does not apply. That is what keeps a storage-only
        #     UpdateSpace working, and it is also the gap: whether SageMaker fills the key
        #     from SpaceSettings...DefaultResourceSpec.InstanceType on UpdateSpace, and from
        #     the space's default on a CreateApp sent without ResourceSpec, is not
        #     documented. If neither is filled, "set the space default, then CreateApp with
        #     no ResourceSpec" still gets around it.
        #   * an app already running on an off-list type keeps running.
        #   * training and processing jobs (M11/M12): different actions, out of scope.
        #
        # Who it binds: only this role, so every Studio session in the domain, admins'
        # profiles included. The API Lambdas (change_instance, expand_storage) call
        # CreateApp/UpdateSpace with their own roles and are unaffected, and so is an
        # operator running scripts/grab_gpu_instance.py with admin credentials from a
        # workstation. Run from a Studio terminal, that script now gets AccessDenied on any
        # off-list type, which is the point.
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="DenyNonParticipantInstanceTypes",
                effect=iam.Effect.DENY,
                actions=["sagemaker:CreateApp", "sagemaker:UpdateSpace"],
                resources=["*"],
                conditions={
                    "ForAnyValue:StringNotLike": {
                        "sagemaker:InstanceTypes": [*participant_instance_types, "system"],
                    },
                },
            )
        )

        # AddTags stays broad and unconditional. SageMaker tags the App on launch, and
        # M11/M12 pass Tags to processing/training jobs; the documented
        # Null:sagemaker:TaggingAction condition covers only tag-on-create, so adopting it
        # risks an AccessDenied on a path that is hard to test. Left as-is deliberately.
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="SageMakerAddTags",
                effect=iam.Effect.ALLOW,
                actions=["sagemaker:AddTags"],
                resources=["*"],
            )
        )

        # SageMaker Training Jobs — needed by M12, which submits a real 2-node
        # torch.distributed DDP job from the notebook via the PyTorch estimator.
        # Scoped to the caller's OWN job names: M12 submits
        # JOB_NAME = f"av30-m12-distributed-{PROFILE}-{int(time.time())}", and PROFILE is
        # the user profile name, which is also the session's aws:SourceIdentity. So a
        # participant can create, describe and stop only jobs named after themselves.
        # Before this, training-job/av30-m12-* let any participant stop a peer's job.
        # Describe/Stop are needed for estimator.fit(wait=True) polling and the
        # metrics/cleanup cells.
        #
        # Narrowing, not a strict boundary: the trailing "-*" also matches the jobs of a
        # profile whose id is <this id>-<more>. create_user ids are <slug>-<6 chars>, so
        # that needs a participant whose name slugifies to another participant's full id
        # (e.g. "kim-abc123" and "kim-abc123-q1w2e3"). The pipeline ARNs below have no
        # such gap. How SageMaker cases names inside ARNs is unverified; create_user ids
        # are lowercase, so either way they match.
        #
        # The prefix MUST track the notebook's JOB_NAME. The module renumber moved
        # HyperPod from M9 to M12 and the notebook now submits
        # f"av30-m12-distributed-{PROFILE}-{ts}", but this stayed av30-m9-*, so every
        # participant hit AccessDenied on CreateTrainingJob. Nothing else rescued it:
        # the execution role has no attached managed policies. Worse, the ADMIN_GUIDE
        # troubleshooting table blamed the m5.xlarge training-job quota, which is
        # genuinely fine (30) — so an admin would verify the quota, find no problem,
        # and conclude the module was simply broken.
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="SageMakerTrainingJobs",
                effect=iam.Effect.ALLOW,
                actions=[
                    "sagemaker:CreateTrainingJob",
                    "sagemaker:DescribeTrainingJob",
                    "sagemaker:StopTrainingJob",
                ],
                resources=[
                    f"arn:aws:sagemaker:{cdk.Stack.of(self).region}:"
                    f"{cdk.Stack.of(self).account}:training-job/"
                    "av30-m12-distributed-${aws:SourceIdentity}-*",
                ],
            )
        )

        # SageMaker Pipelines + Processing — needed by M11, which upserts and runs
        # a 3-step SageMaker Pipeline (each step is a ProcessingJob) from the
        # notebook.
        #
        # Pipelines are scoped to the caller's OWN pipeline: M11 uses
        # PIPELINE_NAME = f"av30-data-pipeline-{PROFILE}" (PROFILE = user profile name =
        # aws:SourceIdentity). The second ARN covers that pipeline's executions
        # (pipeline/<name>/execution/<id>), which DescribePipelineExecution and the two
        # List* actions are authorized against. The old pipeline/av30-* let participant A
        # UpdatePipeline B's pipeline, so B's next run would execute A's step code.
        #
        # ProcessingJob names are NOT scoped: the Pipelines service names the step jobs
        # pipelines-<execution-id>-<step>-<suffix>, with no profile in them, so those
        # actions keep processing-job/* (this account and region only). A peer can still
        # Describe/Stop another participant's M11 step job.
        _region = cdk.Stack.of(self).region
        _account = cdk.Stack.of(self).account
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="SageMakerPipelines",
                effect=iam.Effect.ALLOW,
                actions=[
                    "sagemaker:CreatePipeline",
                    "sagemaker:UpdatePipeline",
                    "sagemaker:DescribePipeline",
                    "sagemaker:DeletePipeline",
                    "sagemaker:StartPipelineExecution",
                    "sagemaker:DescribePipelineExecution",
                    "sagemaker:ListPipelineExecutionSteps",
                    "sagemaker:ListPipelineParametersForExecution",
                ],
                resources=[
                    f"arn:aws:sagemaker:{_region}:{_account}:pipeline/"
                    "av30-data-pipeline-${aws:SourceIdentity}",
                    f"arn:aws:sagemaker:{_region}:{_account}:pipeline/"
                    "av30-data-pipeline-${aws:SourceIdentity}/*",
                ],
            )
        )
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="SageMakerProcessingJobs",
                effect=iam.Effect.ALLOW,
                actions=[
                    "sagemaker:CreateProcessingJob",
                    "sagemaker:DescribeProcessingJob",
                    "sagemaker:StopProcessingJob",
                    "sagemaker:AddTags",
                ],
                resources=[
                    f"arn:aws:sagemaker:{_region}:{_account}:processing-job/*",
                ],
            )
        )

        # PassRole — CreateTrainingJob (M12) and the pipeline's ProcessingSteps
        # (M11) must hand the containers an execution role; the notebook passes
        # THIS role to itself. Scope the PassRole to this role's own ARN, and only
        # when SageMaker is the consuming service, so it cannot be used to pass any
        # other role. Reused by both M12 training and M11 processing.
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="PassSelfToSageMakerTraining",
                effect=iam.Effect.ALLOW,
                actions=["iam:PassRole"],
                # Use the role's own ARN attribute — NEVER re-spell the name here.
                # This used to be a hand-built literal, which would silently point
                # at a non-existent role the moment role_name gained its required
                # region suffix: the deploy stays green and M12 training / M11
                # processing fail at submit time with AccessDenied on PassRole.
                resources=[self._execution_role.role_arn],
                conditions={
                    "StringEquals": {"iam:PassedToService": "sagemaker.amazonaws.com"}
                },
            )
        )

        # CloudWatch Logs permissions for kernel and notebook logs.
        #
        # WRITE-ONLY ON PURPOSE. `logs:GetLogEvents` used to be here, and combined with
        # the resource wildcard below it was a cross-participant credential-read path:
        # EVERY participant shares this one role, /aws/sagemaker/* is ONE log group set
        # shared by the whole cohort, and the notebook-sync lifecycle script runs under
        # `set -eux`, which traced each participant's AV30_PROGRESS_TOKEN into
        # .../LifecycleConfigOnStart. Any participant could therefore read any other
        # participant's non-expiring API token straight out of the log.
        #
        # The lifecycle script now wraps the token handling in `set +x` (see
        # _NOTEBOOK_SYNC_SCRIPT_TEMPLATE), which stops the leak at the source — measured:
        # 3 occurrences in the trace before, 0 after. Dropping the read action is defence
        # in depth, so the next script that echoes something sensitive is not instantly a
        # cohort-wide disclosure.
        #
        # The aws:SourceIdentity scoping that isolates the S3 workspace does NOT extend to
        # this grant: the resource is the whole /aws/sagemaker/* log-group set, shared by
        # every participant. That is the reason it must stay write-only.
        #
        # DescribeLogStreams is kept: it returns stream NAMES only, not contents, and the
        # platform uses it. The admin dashboard reads log content with its own Lambda roles.
        #
        # ONE NOTEBOOK DID read log content and had to be changed to match: M12 called
        # `estimator.fit(..., logs="All")`, which makes the SageMaker SDK stream the
        # training job's log via GetLogEvents. Removing the action here turned that into
        # an AccessDeniedException that also skipped the cell's `total_train_time`
        # assignment, so the following cell died on NameError and the job was billed
        # without producing training_metadata.json. M12 now passes `logs=False`;
        # describe_training_job already supplies status and billable seconds. If a future
        # notebook needs live log tailing, change the notebook — do not re-add this action.
        # Verify with: grep -rn 'logs=' notebooks/  (expect no logs="All")
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudWatchLogsAccess",
                effect=iam.Effect.ALLOW,
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogStreams",
                ],
                resources=[
                    cdk.Arn.format(
                        cdk.ArnComponents(
                            service="logs",
                            resource="log-group",
                            resource_name="/aws/sagemaker/*",
                            arn_format=cdk.ArnFormat.COLON_RESOURCE_NAME,
                        ),
                        cdk.Stack.of(self),
                    ),
                ],
            )
        )

        # KMS permissions for decrypting objects in encrypted buckets
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="KmsDecryptForBuckets",
                effect=iam.Effect.ALLOW,
                actions=[
                    "kms:Decrypt",
                    "kms:GenerateDataKey",
                ],
                resources=["*"],
                conditions={
                    "StringEquals": {
                        "kms:ViaService": [
                            f"s3.{cdk.Stack.of(self).region}.amazonaws.com",
                        ],
                    },
                },
            )
        )

        # OpenSearch Serverless (aoss) access for M4 (semantic search).
        # Two-layer model:
        #   control-plane: create/read the security + data-access policies and the
        #     VECTORSEARCH collection (policy-management actions do NOT support
        #     resource ARNs, so Resource must be "*").
        #   data-plane: aoss:APIAccessAll gates all HTTPS index/search calls
        #     (required since 2023-05); scoped to this account/region collections.
        # The collection stays protected even with a public network policy: the
        # data-access policy names ONLY this execution role as principal, and
        # APIAccessAll is required on top — no unauthenticated access is possible.
        _region = cdk.Stack.of(self).region
        _account = cdk.Stack.of(self).account
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="OpenSearchServerlessControlPlane",
                effect=iam.Effect.ALLOW,
                actions=[
                    "aoss:CreateSecurityPolicy",
                    "aoss:GetSecurityPolicy",
                    "aoss:ListSecurityPolicies",
                    "aoss:CreateAccessPolicy",
                    "aoss:GetAccessPolicy",
                    "aoss:ListAccessPolicies",
                    "aoss:CreateCollection",
                    "aoss:BatchGetCollection",
                    "aoss:ListCollections",
                ],
                resources=["*"],
            )
        )
        # aoss:APIAccessAll ALONE is deliberate — do NOT add aoss:DashboardsAccessAll.
        #
        # The AWS data-access-control page states the opposite: "An associated principal
        # must also be granted access to the IAM permissions aoss:APIAccessAll and
        # aoss:DashboardsAccessAll ... If a principal doesn't have both of these IAM
        # permissions, they will receive 403 errors when attempting to send requests to
        # the collection." Read literally, that says M4 cannot work with this statement.
        #
        # Measured 2026-09-28 against a live VECTORSEARCH collection with exactly this
        # grant: index create, 24 document writes, k-NN search, match_all search, _count,
        # get_mapping and cat.indices ALL succeeded. So APIAccessAll alone is sufficient
        # for the signed data-plane API path; the Dashboards permission gates the
        # Dashboards UI, which this lab never opens.
        #
        # This note exists because M4 spent a long session throwing 403 on reads, and the
        # doc sentence above is the first thing anyone debugging that will find. The
        # actual cause was the notebook freezing rotating credentials into its signer
        # (see notebooks/M4_OpenSearch_Semantic_Search.ipynb, the client cell). Granting
        # DashboardsAccessAll would have widened participant access for nothing and left
        # the real bug in place.
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="OpenSearchServerlessDataPlane",
                effect=iam.Effect.ALLOW,
                actions=["aoss:APIAccessAll"],
                resources=[f"arn:aws:aoss:{_region}:{_account}:collection/*"],
            )
        )
        # NOTE: no iam:CreateServiceLinkedRole — the aoss service-linked role
        # (AWSServiceRoleForAmazonOpenSearchServerless) already exists in this
        # account, so the execution role does not need to create it.

        # Lifecycle configuration for 3-hour idle kernel shutdown
        encoded_script = base64.b64encode(
            _IDLE_SHUTDOWN_SCRIPT.encode("utf-8")
        ).decode("utf-8")
        # Revision suffix for the name (see the comment on the resource below).
        # Derived from the script so editing the script moves the name automatically;
        # bump _IDLE_CONTENT_REV by hand if only the surrounding props change.
        _idle_rev = hashlib.sha256(
            (_IDLE_CONTENT_REV + _IDLE_SHUTDOWN_SCRIPT).encode()
        ).hexdigest()[:8]

        self._lifecycle_config = sagemaker.CfnStudioLifecycleConfig(
            self,
            "IdleShutdownLifecycleConfig",
            studio_lifecycle_config_app_type="JupyterServer",
            studio_lifecycle_config_content=encoded_script,
            # Content-derived name, for the same reason as the notebook LCC below: a
            # StudioLifecycleConfig is immutable, so ANY change to the script (or even
            # to a stack tag, which SageMaker treats as replacement-requiring) forces
            # replacement — and CloudFormation cannot replace a custom-named resource
            # whose name stays the same. With a fixed name the deploy hard-fails with
            # "Rename av30lab-idle-shutdown-3h and update the stack again". Nothing
            # resolves this LCC by name (the domain references it by ARN), so the name
            # is free to move.
            studio_lifecycle_config_name=(
                f"av30lab-idle-shutdown-{_idle_rev}"
            ),
        )

        # JupyterLab lifecycle config: sync notebooks from S3 to the home volume and
        # inject config env vars on app launch. Both bucket names are baked into
        # the script at synth time; the per-user profile name is resolved at
        # runtime from the app metadata file.
        notebook_sync_script = (
            _NOTEBOOK_SYNC_SCRIPT_TEMPLATE
            .replace("__USER_BUCKET_NAME__", user_workspace_bucket.bucket_name)
            .replace("__SHARED_BUCKET_NAME__", shared_data_bucket.bucket_name)
        )
        # cdk.Fn.base64 defers encoding to deploy time so the bucket-name tokens
        # inside the script resolve; Python base64 here would embed the raw
        # ${Token[...]} placeholders and break the shell script.
        encoded_notebook_sync = cdk.Fn.base64(notebook_sync_script)

        # A custom-named StudioLifecycleConfig cannot be updated in place when its
        # content changes: CloudFormation requires replacement and then collides on
        # the fixed name. CloudFormation also REQUIRES the name (it is not
        # optional), so auto-naming is not available — the name has to change
        # whenever the content does.
        #
        # Instead of a hand-bumped "-vN" that someone must remember, derive the
        # suffix from a hash of the script TEMPLATE, so ordinary script edits
        # rotate the name automatically. Token-level changes (e.g. renaming the
        # buckets, which only alters the substituted values, not the template
        # text) do NOT move that hash, so bump _LCC_CONTENT_REV for those.
        #
        # Nothing resolves this LCC by name — every consumer uses the ARN
        # (stacks/av30_stack.py -> api.py NOTEBOOK_LIFECYCLE_CONFIG_ARN ->
        # shared/config.py jupyterlab_resource_spec) — so the name is free to move.
        _lcc_rev = hashlib.sha256(
            (_LCC_CONTENT_REV + _NOTEBOOK_SYNC_SCRIPT_TEMPLATE).encode()
        ).hexdigest()[:8]
        self._notebook_lcc = sagemaker.CfnStudioLifecycleConfig(
            self,
            "NotebookSyncLifecycleConfig",
            studio_lifecycle_config_app_type="JupyterLab",
            studio_lifecycle_config_content=encoded_notebook_sync,
            studio_lifecycle_config_name=f"av30lab-notebook-sync-{_lcc_rev}",
        )

        # Security group for SageMaker Studio Domain
        studio_sg = ec2.SecurityGroup(
            self,
            "StudioSg",
            vpc=vpc,
            description="Security group for SageMaker Studio Domain",
            allow_all_outbound=True,
        )
        studio_sg.add_ingress_rule(
            peer=studio_sg,
            connection=ec2.Port.all_traffic(),
            description="Allow intra-domain traffic between Studio apps",
        )

        # SageMaker Studio Domain in VpcOnly mode
        private_subnet_ids = [
            subnet.subnet_id for subnet in vpc.isolated_subnets
        ]

        default_user_settings = sagemaker.CfnDomain.UserSettingsProperty(
            execution_role=self._execution_role.role_arn,
            security_groups=[studio_sg.security_group_id],
            # SERVICE-SIDE storage ceiling. Keep maximum_ebs_volume_size_in_gb in sync with
            # MAX_STORAGE_GB in infra/lambda/expand_storage/handler.py (500).
            #
            # Why it has to live here and not only in that Lambda: the participant execution
            # role now has sagemaker:UpdateSpace on its own private space, and UpdateSpace is
            # the same API expand_storage uses to resize the volume
            # (expand_storage/handler.py). The IAM statement can condition on WHOSE space it
            # is, but there is no condition key for the requested EbsVolumeSizeInGb and
            # policy variables cannot be used with numeric operators — so a participant
            # running boto3 in their own notebook could ask for the service maximum of 16 TB
            # and the Lambda's MAX_STORAGE_GB would never be consulted, because the Lambda is
            # not in that request path.
            #
            # The damage would have been hard to undo and hard to see: AWS does not allow
            # shrinking a space's EBS volume once grown ("after you increase the Space's EBS
            # volume size, you will not be able to lower it back down"), the volume keeps
            # billing after the idle timer deletes the app, and list_sessions prices a
            # session from instanceType only — so the admin Sessions view would not move.
            # Measured before this change: describe-domain returned
            # DefaultUserSettings.SpaceStorageSettings = null, i.e. no ceiling at all.
            space_storage_settings=sagemaker.CfnDomain.DefaultSpaceStorageSettingsProperty(
                default_ebs_storage_settings=sagemaker.CfnDomain.DefaultEbsStorageSettingsProperty(
                    # 200 GB, matching the largest per-module recommendation in
                    # web/user/src/data/pipeline-config.ts, so no module needs a mid-lab
                    # resize. Measured cost: gp3 in ap-northeast-2 is $0.0912/GB-month, so
                    # 200 GB is ~$18.24 per participant per month — and it CANNOT be
                    # shrunk, so it is a floor until teardown.
                    #
                    # Keep in sync with DEFAULT_SPACE_STORAGE_GB, which is injected into the
                    # Lambdas from this same value (see api.py). The Lambdas must agree with
                    # the volume or the dashboard's +50/+200 arithmetic drifts.
                    default_ebs_volume_size_in_gb=DEFAULT_SPACE_STORAGE_GB,
                    maximum_ebs_volume_size_in_gb=500,
                )
            ),
            jupyter_server_app_settings=sagemaker.CfnDomain.JupyterServerAppSettingsProperty(
                default_resource_spec=sagemaker.CfnDomain.ResourceSpecProperty(
                    sage_maker_image_arn=sagemaker_image_arn,
                    lifecycle_config_arn=self._lifecycle_config.attr_studio_lifecycle_config_arn,
                ),
                lifecycle_config_arns=[
                    self._lifecycle_config.attr_studio_lifecycle_config_arn,
                ],
            ),
            # JupyterLab is the app type participants actually launch. Attach the
            # notebook-sync LCC as the default (and allowlist it) so notebooks
            # appear automatically, and enable idle shutdown (see
            # _idle_timeout_minutes) — the JupyterServer LCC above never runs on
            # these apps. Pin the CPU
            # SageMaker Distribution image as the default (initial spaces are
            # t3.medium); the Lambdas swap to the GPU image when a participant
            # picks a GPU instance. The Distribution images' OWNING ACCOUNT differs
            # per region, so the ARN comes from the shared table rather than a
            # hardcoded literal (a us-west-2 literal here silently gave every other
            # region an ARN for an image that does not exist).
            jupyter_lab_app_settings=sagemaker.CfnDomain.JupyterLabAppSettingsProperty(
                default_resource_spec=sagemaker.CfnDomain.ResourceSpecProperty(
                    sage_maker_image_arn=smd_image_arn(
                        cdk.Stack.of(self).region, "cpu"
                    ),
                    lifecycle_config_arn=self._notebook_lcc.attr_studio_lifecycle_config_arn,
                ),
                lifecycle_config_arns=[
                    self._notebook_lcc.attr_studio_lifecycle_config_arn,
                ],
                app_lifecycle_management=sagemaker.CfnDomain.AppLifecycleManagementProperty(
                    idle_settings=sagemaker.CfnDomain.IdleSettingsProperty(
                        lifecycle_management="ENABLED",
                        idle_timeout_in_minutes=self._idle_timeout_minutes(),
                        min_idle_timeout_in_minutes=60,
                        max_idle_timeout_in_minutes=180,
                    ),
                ),
            ),
        )

        # PublicInternetOnly: Studio traffic (including presigned-URL app access)
        # flows through a SageMaker-managed VPC with direct internet access, so
        # participants can open their workspace from any browser. A VPC + subnets
        # are still supplied for EFS/home-directory traffic. Switching this value
        # is an in-place update (no domain replacement, domain ID preserved).
        # domain_name is also how scripts/teardown.sh finds the domain when the
        # stack outputs are unavailable — keep the two in step.
        self._domain = sagemaker.CfnDomain(
            self,
            "Domain",
            auth_mode="IAM",
            domain_name="av30-blueprint-lab",
            vpc_id=vpc.vpc_id,
            subnet_ids=private_subnet_ids,
            app_network_access_type="PublicInternetOnly",
            default_user_settings=default_user_settings,
            # STEP 2 of the two-step upgrade (step 1 is sts:SetSourceIdentity in the trust
            # policy, above). SageMaker sets sts:SourceIdentity = the user profile name on
            # every session of the execution role; the users/${aws:SourceIdentity}/ S3
            # scope and the M11/M12 ARNs depend on it. Allowed values: USER_PROFILE_NAME |
            # DISABLED.
            #
            # OPERATIONAL CONSTRAINTS:
            #   * Per the API reference the setting can change only while no app in the
            #     domain is InService or Pending, so the first deploy of it needs every
            #     app stopped. scripts/deploy.sh checks the live domain and refuses
            #     otherwise.
            #   * Sessions created before the change carry no source identity and are
            #     denied on users/ (fail-closed). Participants restart their app.
            #   * Rolling back is NOT "redeploy the previous commit". Keep the trust
            #     statement, and deploy an explicit "DISABLED" together with the old S3
            #     statements, again with all apps stopped.
            #   * Unverified: whether later deploys that touch this domain (LCC rotation,
            #     idle_timeout_minutes) resend the setting and so also need apps stopped.
            domain_settings=sagemaker.CfnDomain.DomainSettingsProperty(
                execution_role_identity_config="USER_PROFILE_NAME",
            ),
        )

    _IDLE_TIMEOUT_DEFAULT_MINUTES = 90
    _IDLE_TIMEOUT_MIN_MINUTES = 60
    _IDLE_TIMEOUT_MAX_MINUTES = 180

    def _idle_timeout_minutes(self) -> int:
        """Minutes of idleness before a JupyterLab app is shut down.

        Override per deployment with `-c idle_timeout_minutes=<60..180>`.

        Lowered from the 180-minute MAXIMUM to 90. An abandoned app is billed the whole
        time, and the amount is not small on the types the heavy modules recommend:
        ml.g5.12xlarge is $8.718/hr in ap-northeast-2, so 180 idle minutes is $26.15 per
        participant versus $13.08 at 90. It also holds one of the region's quota slots
        (5 for that type in ap-northeast-2, 2 for ml.g5.24xlarge/48xlarge), so one
        forgotten app can block another participant for three hours.

        Shutting down does NOT interrupt work in progress. Per the Idle shutdown
        documentation, the timer "doesn't start until the instance becomes idle", and a
        JupyterLab app only counts as idle when there are no active Jupyter kernel
        sessions AND no active terminal sessions — so a training cell or a shell job keeps
        the app alive for as long as it runs. M8's LoRA SFT cannot be killed by this.
        The home directory is on the space's EBS volume and survives shutdown;
        relaunching is one click.

        Not lowered further than 90 on purpose: relaunching a GPU app takes minutes and,
        in a region where the heavy types have a quota of 2, the freed slot may be taken
        by another participant in the meantime. Shutting someone down aggressively can
        lock them out mid-module, which is worse than the idle cost it saves.

        min/max stay 60/180: those bound what a USER PROFILE may override to (user-profile
        idle settings take precedence over the domain's), not what the domain uses.
        """
        raw = self.node.try_get_context("idle_timeout_minutes")
        if raw is None or raw == "":
            return self._IDLE_TIMEOUT_DEFAULT_MINUTES
        # CDK context arrives as a STRING even when written as a number on the command
        # line, and CfnDomain type-checks this field as an int — passing the string
        # through fails synth with a confusing jsii error rather than a clear one.
        try:
            minutes = int(raw)
        except (TypeError, ValueError):
            raise ValueError(
                f"idle_timeout_minutes must be an integer, got {raw!r}"
            ) from None
        if not (self._IDLE_TIMEOUT_MIN_MINUTES <= minutes
                <= self._IDLE_TIMEOUT_MAX_MINUTES):
            # SageMaker rejects this at deploy time; failing at synth costs nothing and
            # names the bound, instead of surfacing as a CloudFormation rollback.
            raise ValueError(
                f"idle_timeout_minutes must be between {self._IDLE_TIMEOUT_MIN_MINUTES} "
                f"and {self._IDLE_TIMEOUT_MAX_MINUTES} minutes (SageMaker's own limits "
                f"for this domain), got {minutes}"
            )
        return minutes

    @property
    def domain_id(self) -> str:
        """The SageMaker Studio Domain ID."""
        return self._domain.attr_domain_id

    @property
    def execution_role(self) -> iam.Role:
        """IAM execution role for SageMaker Studio users."""
        return self._execution_role

    @property
    def lifecycle_config_arn(self) -> str:
        """ARN of the idle shutdown lifecycle configuration."""
        return self._lifecycle_config.attr_studio_lifecycle_config_arn

    @property
    def notebook_lifecycle_config_arn(self) -> str:
        """ARN of the JupyterLab notebook-sync lifecycle configuration."""
        return self._notebook_lcc.attr_studio_lifecycle_config_arn
