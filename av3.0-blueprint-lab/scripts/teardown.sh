#!/bin/bash
# ── AV 3.0 Blueprint Lab — post-event teardown ──────────────────────────────
# Reclaims workshop resources directly via the AWS CLI (admin creds on the
# default SDK chain, same as deploy.sh — it does NOT call the Cognito-protected
# API). DRY-RUN by default: it enumerates what WOULD be deleted and changes
# nothing until you pass --yes.
#
#   ./scripts/teardown.sh                          # DRY-RUN: enumerate only
#   ./scripts/teardown.sh --yes                    # LIVE: delete ALL users + sweep
#   ./scripts/teardown.sh --yes --user <userId>    # LIVE: scope to ONE user
#   ./scripts/teardown.sh --yes --destroy          # + cdk destroy the stack
#
# Per-user teardown mirrors the delete_user Lambda's dependency order:
#   app(s) -> space -> user-profile -> AOSS -> S3 workspace prefix -> DDB row.
# A global AOSS sweep (§2) reaps any orphaned av30-semantic-* collection left by
# the delete_user cleanup_aoss best-effort path. Skipped when --user is set, so a
# single-user teardown never touches another participant's live collection.
#
# Safety: dry-run default, typed account-id confirmation before any mutation,
# account/role/region echoed up front, set -uo pipefail with per-item warn+continue
# (never `set -e` — one failed item must not abort the sweep). The EC2 branch is
# double-guarded (tag:Participant AND tag:Name=av30-alpasim-*).
set -uo pipefail

# Region must be explicit. It used to default to the literal "us-west-2", which made
# this script actively dangerous once a second region exists: running it with AWS_REGION
# unset to reclaim region B would silently delete the FIRST, live deployment — its Studio
# apps, spaces, user profiles, AOSS collections and, with --destroy, the whole stack.
# The old confirmation prompt could not catch it either, because it only asked for the
# ACCOUNT id, which is identical for every region.
STACK_NAME="Av30BlueprintLabStack"
TABLE="av30-sessions-v2"

YES=false; DESTROY=false; ONLY_USER=""; REGION_CLI=""
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) YES=true ;;
    --destroy) DESTROY=true; YES=true ;;   # --destroy implies --yes
    --user) shift; ONLY_USER="${1:-}" ;;
    --region) shift; REGION_CLI="${1:-}" ;;
    --region=*) REGION_CLI="${1#*=}" ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown flag: $1" >&2; exit 2 ;;
  esac; shift
done

# --region mirrors deploy.sh, so the two halves of an operation are spelled the same way
# (the runbook used to document a --region flag this script did not have).
# Precedence: --region > AWS_REGION > profile region. Flag parsing must run BEFORE this,
# since the flag participates in resolution.
REGION="${REGION_CLI:-${AWS_REGION:-$(aws configure get region 2>/dev/null)}}"
if [ -z "$REGION" ]; then
  echo "ERROR: no region. Pass --region <region> or set AWS_REGION explicitly — this" >&2
  echo "       script will not guess, because guessing deletes the wrong region." >&2
  exit 2
fi
# Exported so every nested `aws` call inherits it even where --region is not passed.
export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"

warn() { echo "  WARN: $*" >&2; }
act()  { if $YES; then "$@"; else echo "  [dry-run] $*"; fi; }

# ── Preamble: who/where, so the operator can abort a wrong-account run ───────
CALLER=$(aws sts get-caller-identity --query '[Account,Arn]' --output text 2>/dev/null) \
  || { echo "No AWS credentials on the default chain." >&2; exit 1; }
ACCOUNT="${CALLER%%$'\t'*}"
echo "================================================================"
echo "  AV3.0 TEARDOWN — $($YES && echo 'LIVE (WILL DELETE)' || echo 'DRY-RUN (no changes)')"
echo "  Account/Role: $CALLER"
echo "  Region:       $REGION"
echo "  Stack:        $STACK_NAME"
[ -n "$ONLY_USER" ] && echo "  Scoped to:    $ONLY_USER  (global AOSS sweep §2 skipped)"
echo "================================================================"
if $YES; then
  # Require account/REGION, not just the account: the account id is the same for every
  # region, so it could never distinguish "tear down region B" from "tear down the live
  # primary". Typing the region is the only thing that makes the target unambiguous.
  read -r -p "Type \"$ACCOUNT/$REGION\" to proceed: " CONF
  [ "$CONF" = "$ACCOUNT/$REGION" ] || { echo "Aborted."; exit 1; }
  # And confirm a stack actually exists in the region being torn down, so a typo'd or
  # stale region cannot start sweeping resources that belong to something else.
  if ! aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
        --region "$REGION" >/dev/null 2>&1; then
    echo "ERROR: no stack $STACK_NAME in $REGION — refusing to sweep a region this" >&2
    echo "       lab was never deployed to." >&2
    exit 1
  fi
fi

# ── Resolve resources from stack outputs (deterministic-name fallback) ───────
OUTPUTS=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
            --query 'Stacks[0].Outputs' --region "$REGION" 2>/dev/null || echo "[]")
val() { echo "$OUTPUTS" | jq -r --arg k "$1" '.[]|select(.OutputKey==$k)|.OutputValue' 2>/dev/null; }
DOMAIN=$(val SageMakerDomainId); [ -z "$DOMAIN" ] && DOMAIN="d-on0ous0ufsac"
WS_ARN=$(val UserWorkspaceBucketArn)
USER_WS_BUCKET="${WS_ARN#arn:aws:s3:::}"
# $REGION is part of the bucket name. Without it this fallback names a bucket that
# does not exist, so the sweep below would report success while the real workspace
# bucket (and its per-participant data) is left behind, still billing.
[ -z "$USER_WS_BUCKET" ] && USER_WS_BUCKET="av30lab-user-workspace-${ACCOUNT}-${REGION}"
echo "  Domain: $DOMAIN   Workspace bucket: $USER_WS_BUCKET"; echo ""

# AOSS collection name — byte-matches infra/lambda/shared/config.aoss_collection_name
# and M4's _aoss_name (lower, [^a-z0-9-]->-, first 8, strip stray -, letter start).
aoss_name() {
  local slug
  slug=$(echo "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g' \
         | cut -c1-8 | sed 's/^-*//; s/-*$//')
  [ -z "$slug" ] && slug="user"
  case "$slug" in [a-z]*) ;; *) slug=$(echo "u$slug" | cut -c1-8) ;; esac
  echo "av30-semantic-$slug"
}

cleanup_aoss_collection() {
  local name="$1" id s
  id=$(aws opensearchserverless batch-get-collection --names "$name" --region "$REGION" \
        --query 'collectionDetails[0].id' --output text 2>/dev/null || echo "")
  if [ -n "$id" ] && [ "$id" != "None" ]; then
    act aws opensearchserverless delete-collection --id "$id" --region "$REGION" \
      || warn "delete-collection $name"
    # Wait until the collection is gone before dropping policies (else Conflict).
    if $YES; then for _ in $(seq 1 60); do
        s=$(aws opensearchserverless batch-get-collection --ids "$id" --region "$REGION" \
              --query 'collectionDetails[0].status' --output text 2>/dev/null || echo "")
        { [ -z "$s" ] || [ "$s" = "None" ]; } && break; sleep 5; done; fi
  fi
  act aws opensearchserverless delete-security-policy --name "${name}-enc" \
      --type encryption --region "$REGION" || warn "policy ${name}-enc"
  act aws opensearchserverless delete-security-policy --name "${name}-net" \
      --type network --region "$REGION" || warn "policy ${name}-net"
  act aws opensearchserverless delete-access-policy --name "${name}-access" \
      --type data --region "$REGION" || warn "policy ${name}-access"
}

teardown_user() {
  local uid="$1" space="$2"
  [ -z "$space" ] && space="${uid}-space"
  echo "  User $uid (space=$space)"
  # 1. Delete every non-Deleted app on the space, then wait for them to go.
  aws sagemaker list-apps --domain-id "$DOMAIN" --space-name-equals "$space" \
      --region "$REGION" --query 'Apps[?Status!=`Deleted`].[AppType,AppName]' \
      --output text 2>/dev/null | while read -r atype aname; do
        [ -z "$atype" ] && continue
        act aws sagemaker delete-app --domain-id "$DOMAIN" --space-name "$space" \
            --app-type "$atype" --app-name "$aname" --region "$REGION" \
          || warn "delete-app $atype/$aname"
      done
  if $YES; then for _ in $(seq 1 48); do
      n=$(aws sagemaker list-apps --domain-id "$DOMAIN" --space-name-equals "$space" \
            --region "$REGION" \
            --query 'length(Apps[?Status!=`Deleted`&&Status!=`Failed`])' \
            --output text 2>/dev/null || echo 0)
      [ "$n" = "0" ] && break; sleep 5; done; fi
  # 2. Space -> 3. Profile (each guarded; wait between).
  act aws sagemaker delete-space --domain-id "$DOMAIN" --space-name "$space" \
      --region "$REGION" || warn "delete-space $space"
  if $YES; then for _ in $(seq 1 36); do
      aws sagemaker describe-space --domain-id "$DOMAIN" --space-name "$space" \
        --region "$REGION" >/dev/null 2>&1 || break; sleep 5; done; fi
  act aws sagemaker delete-user-profile --domain-id "$DOMAIN" \
      --user-profile-name "$uid" --region "$REGION" || warn "delete-profile $uid"
  if $YES; then for _ in $(seq 1 36); do
      aws sagemaker describe-user-profile --domain-id "$DOMAIN" \
        --user-profile-name "$uid" --region "$REGION" >/dev/null 2>&1 || break; sleep 5; done; fi
  # 4. AOSS for this user (global sweep §2 is the backstop for stragglers).
  cleanup_aoss_collection "$(aoss_name "$uid")"
  # 5. S3 workspace prefix.
  act aws s3 rm "s3://$USER_WS_BUCKET/users/$uid/" --recursive --region "$REGION" \
    || warn "s3 rm users/$uid/"
  # 6. DDB row LAST (so a re-run can still resolve the user).
  act aws dynamodb delete-item --table-name "$TABLE" --region "$REGION" \
      --key "{\"userId\":{\"S\":\"$uid\"}}" || warn "ddb delete $uid"
}

# ── §0. Enumerate users from DynamoDB (paginated) ────────────────────────────
scan_users() {
  local tok="" page
  while :; do
    if [ -n "$tok" ]; then
      page=$(aws dynamodb scan --table-name "$TABLE" --region "$REGION" \
               --projection-expression 'userId, spaceName' --max-items 100 \
               --starting-token "$tok") || return 1
    else
      page=$(aws dynamodb scan --table-name "$TABLE" --region "$REGION" \
               --projection-expression 'userId, spaceName' --max-items 100) || return 1
    fi
    echo "$page" | jq -r '.Items[] | [.userId.S, (.spaceName.S // "")] | @tsv'
    tok=$(echo "$page" | jq -r '.NextToken // empty'); [ -z "$tok" ] && break
  done
}

echo ">>> §0 Users in $TABLE:"
USERS=$(scan_users) || { echo "  scan failed"; USERS=""; }
[ -n "$ONLY_USER" ] && USERS=$(echo "$USERS" | awk -F'\t' -v u="$ONLY_USER" '$1==u')
echo "$USERS" | sed 's/^/    /'; echo ""

# ── §1. Per-user teardown ────────────────────────────────────────────────────
echo ">>> §1 Per-user teardown"
echo "$USERS" | while IFS=$'\t' read -r uid space; do
  [ -z "$uid" ] && continue
  teardown_user "$uid" "$space"
done

# ── §2. Global AOSS sweep — backstop for orphaned av30-semantic-* ────────────
# Skipped under --user so a single-user teardown can't touch another
# participant's live collection.
if [ -z "$ONLY_USER" ]; then
  echo ">>> §2 Global AOSS sweep (av30-semantic-*)"
  aws opensearchserverless list-collections --region "$REGION" \
      --query 'collectionSummaries[?starts_with(name,`av30-semantic-`)].name' \
      --output text 2>/dev/null | tr '\t' '\n' | while read -r name; do
        [ -z "$name" ] && continue
        echo "  orphan candidate: $name"; cleanup_aoss_collection "$name"; done
else
  echo ">>> §2 Global AOSS sweep SKIPPED (--user scope)"
fi

# ── §3. M10 AlpaSim participant EC2 (double-guarded) ──────────────────────────
echo ">>> §3 Participant EC2 termination"
IDS=$(aws ec2 describe-instances --region "$REGION" \
  --filters 'Name=tag-key,Values=Participant' \
            'Name=tag:Name,Values=av30-alpasim-*' \
            'Name=instance-state-name,Values=running,pending,stopping,stopped' \
  --query 'Reservations[].Instances[].InstanceId' --output text 2>/dev/null || echo "")
if [ -n "$IDS" ]; then
  echo "  instances: $IDS"
  act aws ec2 terminate-instances --region "$REGION" --instance-ids $IDS \
    || warn "terminate $IDS"
else
  echo "  none (no Participant-tagged av30-alpasim-* hosts)"
fi

# ── §4. Optional: cdk destroy behind --destroy ──────────────────────────────
if $DESTROY; then
  echo ">>> §4 cdk destroy $STACK_NAME"
  ( cd "$(dirname "$0")/../infra" && { [ -d .venv ] && . .venv/bin/activate; }
    npx cdk destroy "$STACK_NAME" --force ) || warn "cdk destroy"
  echo "  NOTE: the shared-data bucket is RETAIN (auto_delete_objects off) — it"
  echo "        and its cached models SURVIVE and must be emptied by hand."
fi

# ── §5. Manual security checklist (echo only) ────────────────────────────────
cat <<'EOF'

============ MANUAL POST-EVENT SECURITY CHECKLIST ============
  [ ] Revoke the admin Hugging Face token used to stage model caches.
  [ ] Rotate the NGC API key if M10 (AlpaSim) was run this event.
  [ ] Scrub any HF/NGC creds from staged scripts in the RETAINED
      shared-data bucket before archiving or deleting it.
==============================================================
EOF
$YES || echo "(DRY-RUN complete — nothing was changed.)"
