#!/bin/bash
set -euo pipefail

# --- Target region ------------------------------------------------------------------
# This lab supports deploying an ADDITIONAL, independent copy into another region in the
# same account (see docs/en/ADDING_A_REGION.md). Choose it explicitly:
#
#     ./scripts/deploy.sh --region ap-northeast-2
#     REGION=ap-northeast-2 ./scripts/deploy.sh
#     AWS_REGION=ap-northeast-2 ./scripts/deploy.sh
#
# Precedence: --region > REGION > AWS_REGION > the profile's region. There is NO literal
# default. It used to be "us-west-2" here while infra/app.py independently defaulted the
# same way, so the two could disagree — the CDK would build region B while every later
# step in this script operated on region A. The resolved value is now pinned into the CDK
# with -c region so they cannot diverge.
REGION_CLI=""
ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --region) shift; REGION_CLI="${1:-}" ;;
        --region=*) REGION_CLI="${1#*=}" ;;
        -h|--help)
            sed -n '1,40p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) ARGS+=("$1") ;;
    esac
    shift
done
[ ${#ARGS[@]} -gt 0 ] && { echo "Unknown argument: ${ARGS[0]}" >&2; exit 2; }

ADMIN_EMAIL="${ADMIN_EMAIL:?Set ADMIN_EMAIL environment variable}"
ADMIN_IP_ALLOWLIST="${ADMIN_IP_ALLOWLIST:-0.0.0.0/0}"
REGION="${REGION_CLI:-${REGION:-${AWS_REGION:-$(aws configure get region 2>/dev/null)}}}"
if [ -z "$REGION" ]; then
    echo "ERROR: no region. Pass --region <region>, or set REGION/AWS_REGION." >&2
    echo "       This script will not guess: guessing deploys to the wrong region." >&2
    exit 2
fi
# Everything downstream (aws CLI calls, the CDK, S3 syncs) must use this one value.
export AWS_REGION="$REGION"
export AWS_DEFAULT_REGION="$REGION"
STACK_NAME="Av30BlueprintLabStack"

# --- Where am I actually deploying? -------------------------------------------
# This script uses the ambient credential chain (no --profile anywhere), so an
# AWS_PROFILE left over from unrelated work silently sends the WHOLE lab — Studio
# domain, buckets, Cognito, CloudFront — into someone else's account. That is not
# hypothetical: it nearly happened here, with AWS_PROFILE=bedrock / us-east-1
# resolving to a different account than the lab's.
#
# So: print the resolved identity before doing anything, and hard-fail on a
# mismatch when EXPECTED_ACCOUNT_ID is set. Setting it is strongly recommended and
# costs nothing:
#     EXPECTED_ACCOUNT_ID=123456789012 AWS_PROFILE=... AWS_REGION=... ./scripts/deploy.sh
CALLER=$(aws sts get-caller-identity --output json 2>/dev/null) || {
    echo "ERROR: cannot resolve AWS credentials. Set AWS_PROFILE (and AWS_REGION)." >&2
    exit 1
}
ACCOUNT_ID=$(echo "$CALLER" | jq -r '.Account')
CALLER_ARN=$(echo "$CALLER" | jq -r '.Arn')
if [ -n "${AWS_PROFILE:-}" ]; then
    CRED_SOURCE="AWS_PROFILE=$AWS_PROFILE"
else
    CRED_SOURCE="the default credential chain"
fi

echo "=== AV 3.0 Blueprint Lab Deployment ==="
echo "Account:       $ACCOUNT_ID"
echo "Region:        $REGION"
echo "Identity:      $CALLER_ARN"
echo "Credentials:   $CRED_SOURCE"
echo "Admin:         $ADMIN_EMAIL"
echo "IP Allowlist:  $ADMIN_IP_ALLOWLIST"
echo ""

if [ -n "${EXPECTED_ACCOUNT_ID:-}" ] && [ "$ACCOUNT_ID" != "$EXPECTED_ACCOUNT_ID" ]; then
    echo "ERROR: account mismatch — refusing to deploy." >&2
    echo "  EXPECTED_ACCOUNT_ID = $EXPECTED_ACCOUNT_ID" >&2
    echo "  resolved account    = $ACCOUNT_ID  (from $CRED_SOURCE)" >&2
    echo "  Fix AWS_PROFILE / AWS_REGION and re-run." >&2
    exit 1
fi
if [ -z "${EXPECTED_ACCOUNT_ID:-}" ]; then
    echo "NOTE: EXPECTED_ACCOUNT_ID is not set, so the account above is NOT being checked."
    echo "      Set it to guard against deploying into the wrong account."
    echo ""
fi

cd "$(dirname "$0")/.."

# --- GPU quota pre-flight — BEFORE cdk deploy, and BEFORE the venv ------------------
#
# Runs here for two reasons, both measured:
#
#   1. BEFORE `cdk deploy`. It used to run at the very end, after ~25 min of deploying.
#      Learning that the region cannot launch the types the dashboard recommends is only
#      useful while you can still change region.
#   2. BEFORE `source infra/.venv/bin/activate`. That venv installs
#      infra/requirements.txt, which historically did NOT include boto3, and the script
#      never deactivates it — so the check ran under an interpreter that exits with
#      "boto3 is required". Combined with a `2>/dev/null` and an `if …; then : fi` that
#      swallowed the status, the pre-flight README.md advertises was a SILENT NO-OP for
#      every user on a fresh clone. Measured: 0 lines of output. boto3 is now in
#      requirements.txt too, but running before the venv means a broken venv cannot
#      silence this again.
#
# Non-fatal on purpose: a shortfall is an admin decision (raise quota, change region, cap
# the cohort), not a reason to refuse a deploy. But the exit status is REPORTED, never
# discarded, and stderr is left attached so a missing rate table is visible.
if [ -x ./scripts/check_quotas.py ]; then
    echo ""
    echo ">>> Pre-flight: GPU quota for $REGION (before deploying) ..."
    if ./scripts/check_quotas.py --region "$REGION" --participants "${PARTICIPANTS:-10}"; then
        echo "    quota pre-flight: OK for ${PARTICIPANTS:-10} concurrent participant(s)"
    else
        rc=$?
        echo ""
        echo "    >>> quota pre-flight reported a problem (exit $rc)." >&2
        echo "        Read the report above BEFORE continuing: a recommended type with" >&2
        echo "        quota 0 is accepted by SageMaker and then fails to start." >&2
        echo "        Deploying anyway in 10s — Ctrl-C to stop and fix it first." >&2
        sleep 10
    fi
fi

echo ">>> Step 1/6: CDK Deploy (infrastructure)..."
cd infra
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -q -r requirements.txt
else
    source .venv/bin/activate
fi
CDK_CONTEXT=(--context admin_email="$ADMIN_EMAIL"
             --context admin_ip_allowlist="$ADMIN_IP_ALLOWLIST"
             # Pin the CDK to the same region this script resolved, so infra/app.py
             # cannot pick a different one from the ambient environment.
             --context region="$REGION")

# --- Live-state guards for the two contexts that destroy things when forgotten ------
#
# OWNER_TAG and HOSTED_UI_DOMAIN_EXISTS were documented-only, in one file the deploy
# runbook does not even link. Forgetting either on an UPDATE is destructive, so decide
# both from the LIVE state and REFUSE on a mismatch — the same shape this script already
# uses for APIGW_ACCOUNT_ROLE below, rather than trusting the operator to have read a doc.
#
# Defaults are READ FROM THE CDK SOURCE, not duplicated here. A literal copy would drift
# silently, and drift means this guard would compare against the wrong value and either
# refuse a correct deploy or wave through a destructive one.
OWNER_DEFAULT=$(sed -n 's/.*try_get_context("owner_tag") or "\([^"]*\)".*/\1/p' \
    stacks/av30_stack.py | head -1)
UI_PREFIX_DEFAULT=$(sed -n 's/.*try_get_context("hosted_ui_prefix") or "\([^"]*\)".*/\1/p' \
    stacks/av30_stack.py | head -1)
if [ -z "$OWNER_DEFAULT" ] || [ -z "$UI_PREFIX_DEFAULT" ]; then
    echo "ERROR: could not read the owner_tag / hosted_ui_prefix defaults from" >&2
    echo "       infra/stacks/av30_stack.py. The shape of that file changed, so these" >&2
    echo "       guards cannot be trusted — fix the extraction rather than bypassing it." >&2
    exit 1
fi

STACK_STATUS_NOW=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --region "$REGION" --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "")

# 1. Owner tag. SageMaker treats domain TAGS as replacement-requiring, so a changed value
#    rebuilds the Studio domain — new domain id, every participant's workspace gone, the
#    EFS filesystem orphaned and still billing. Only matters on an update.
OWNER_EFFECTIVE="${OWNER_TAG:-$OWNER_DEFAULT}"
if [ -n "$STACK_STATUS_NOW" ]; then
    OWNER_LIVE=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
        --region "$REGION" --query "Stacks[0].Tags[?Key=='Owner'].Value|[0]" \
        --output text 2>/dev/null || echo "None")
    if [ "$OWNER_LIVE" != "None" ] && [ -n "$OWNER_LIVE" ] \
       && [ "$OWNER_LIVE" != "$OWNER_EFFECTIVE" ]; then
        echo "REFUSING: this would change the stack's Owner tag from" >&2
        echo "            '$OWNER_LIVE'  ->  '$OWNER_EFFECTIVE'" >&2
        echo "          SageMaker treats domain tags as replacement-requiring, so that" >&2
        echo "          REPLACES the Studio domain: new domain id, every participant" >&2
        echo "          workspace lost, and the EFS filesystem orphaned but still billing." >&2
        echo "          Re-run with:  OWNER_TAG='$OWNER_LIVE' $0 --region $REGION" >&2
        echo "          (Only change the Owner tag deliberately, with the domain empty.)" >&2
        exit 1
    fi
fi
if [ -n "${OWNER_TAG:-}" ]; then
    echo "    (preserving Owner tag: $OWNER_TAG)"
    CDK_CONTEXT+=(--context owner_tag="$OWNER_TAG")
fi

# 2. Cognito hosted-UI domain. The prefix is unique per REGION (not globally), so a second
#    region needs no rename — but if a domain with this prefix already exists in THIS region
#    and the stack does not own it, declaring it fails the create. Conversely, setting the
#    flag when no domain exists yields a user pool with NO sign-in endpoint.
UI_PREFIX="${HOSTED_UI_PREFIX:-$UI_PREFIX_DEFAULT}"
[ -n "${HOSTED_UI_PREFIX:-}" ] && CDK_CONTEXT+=(--context hosted_ui_prefix="$HOSTED_UI_PREFIX")
UI_DOMAIN_POOL=$(aws cognito-idp describe-user-pool-domain --domain "$UI_PREFIX" \
    --region "$REGION" --output json 2>/dev/null | jq -r '.DomainDescription.UserPoolId // empty')
# list-stack-resources, NOT describe-stack-resources: the latter caps at 100 resources with
# no pagination and this stack has 176, so it reported "0 UserPoolDomain" for a region that
# demonstrably manages one. Counting non-empty lines sums across pages.
UI_DOMAIN_MANAGED=$(aws cloudformation list-stack-resources --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "StackResourceSummaries[?ResourceType=='AWS::Cognito::UserPoolDomain'].LogicalResourceId" \
    --output text 2>/dev/null | tr '\t' '\n' | grep -c . || true)

if [ -n "$UI_DOMAIN_POOL" ] && [ "$UI_DOMAIN_MANAGED" = "0" ] \
   && [ -z "${HOSTED_UI_DOMAIN_EXISTS:-}" ]; then
    echo "REFUSING: '$UI_PREFIX' already exists as a Cognito hosted-UI domain in $REGION" >&2
    echo "          (user pool $UI_DOMAIN_POOL) and this stack does NOT manage it." >&2
    echo "          Declaring it would fail the create partway through the deploy." >&2
    echo "          Re-run with:  HOSTED_UI_DOMAIN_EXISTS=true $0 --region $REGION" >&2
    echo "          Or pick an unused prefix:  HOSTED_UI_PREFIX=<other> $0 --region $REGION" >&2
    exit 1
fi
if [ -n "${HOSTED_UI_DOMAIN_EXISTS:-}" ] && [ -z "$UI_DOMAIN_POOL" ]; then
    echo "REFUSING: HOSTED_UI_DOMAIN_EXISTS is set, but no hosted-UI domain named" >&2
    echo "          '$UI_PREFIX' exists in $REGION. With the flag set the stack does not" >&2
    echo "          declare one, so you would get a user pool with NO sign-in endpoint" >&2
    echo "          and this script would abort later on the missing CognitoHostedUiUrl." >&2
    echo "          Unset it for a region that needs its own domain." >&2
    exit 1
fi
# The mirror-image mistake, and the easier one to make once the flag is in your shell
# history: setting it in a region where the stack DOES manage the domain removes that
# resource from the template, so CloudFormation DELETES the live Cognito domain and
# sign-in stops working. Nothing about that reads as destructive at the command line.
if [ -n "${HOSTED_UI_DOMAIN_EXISTS:-}" ] && [ "$UI_DOMAIN_MANAGED" != "0" ]; then
    echo "REFUSING: HOSTED_UI_DOMAIN_EXISTS is set, but this stack MANAGES the hosted-UI" >&2
    echo "          domain '$UI_PREFIX' in $REGION. Setting the flag drops the resource" >&2
    echo "          from the template, so CloudFormation would DELETE the live domain and" >&2
    echo "          admin sign-in would stop working." >&2
    echo "          Unset it here — it exists only for a domain the stack does not own." >&2
    exit 1
fi
if [ -n "${HOSTED_UI_DOMAIN_EXISTS:-}" ]; then
    echo "    (hosted-UI domain '$UI_PREFIX' exists and stays unmanaged)"
    CDK_CONTEXT+=(--context hosted_ui_domain_exists="$HOSTED_UI_DOMAIN_EXISTS")
fi
# API Gateway account-level CloudWatch role. AWS::ApiGateway::Account is a per-account
# PER-REGION singleton implemented as an unconditional PATCH /account, so creating it
# OVERWRITES whatever role the region already has — measured in this account,
# ap-northeast-1 and ap-northeast-2 each already have one owned by an unrelated stack.
# It therefore defaults OFF. But with it off in a region that has none, the stage is
# configured for INFO logging while the account has no role, and execution logs are
# silently absent. So decide it explicitly, per region, from the live value.
APIGW_ROLE_NOW=$(aws apigateway get-account --region "$REGION" \
    --query cloudwatchRoleArn --output text 2>/dev/null)
# Does THIS stack own the live role? Both branches below need that answer, and they used to
# disagree: only the flag-IS-set branch tested ownership, so the unset branch told an
# operator whose OWN stack owned the role "leave it alone, do not set the flag" — advice
# that DELETES it. api.py gates AWS::ApiGateway::Account *and* its IAM role on this one
# context value, so omitting the flag drops both from the template. Resolve it once here.
APIGW_ROLE_EXISTS=false
APIGW_ROLE_IS_OURS=false
if [ "$APIGW_ROLE_NOW" != "None" ] && [ -n "$APIGW_ROLE_NOW" ]; then
    APIGW_ROLE_EXISTS=true
    # `if`, not `grep -q ... && VAR=true`: under `set -e` that AND-list ends non-zero
    # whenever grep does NOT match, which is the common case here. A grep inside an `if`
    # condition is explicitly exempt from set -e; as a bare statement it is not.
    if printf '%s' "$APIGW_ROLE_NOW" | grep -q "$STACK_NAME"; then
        APIGW_ROLE_IS_OURS=true
    fi
fi
if [ -z "${APIGW_ACCOUNT_ROLE:-}" ]; then
    if [ "$APIGW_ROLE_EXISTS" != true ]; then
        echo "    NOTE: $REGION has no API Gateway account-level CloudWatch role, so API"
        echo "          execution logs will not be emitted. This deploy will NOT create"
        echo "          one (creating it is an account-wide overwrite). If this region is"
        echo "          yours alone, re-run with APIGW_ACCOUNT_ROLE=true to create it."
    elif [ "$APIGW_ROLE_IS_OURS" = true ]; then
        # The destructive case, and the one that reads as harmless. Refuse, like the
        # Owner-tag and hosted-UI guards above, rather than warn: there is no way to
        # PRESERVE a role this stack owns other than passing the flag.
        echo "REFUSING: the API Gateway account-level CloudWatch role in $REGION is owned" >&2
        echo "          by THIS stack:" >&2
        echo "          $APIGW_ROLE_NOW" >&2
        echo "          Deploying without APIGW_ACCOUNT_ROLE drops AWS::ApiGateway::Account" >&2
        echo "          and its IAM role from the template, so CloudFormation DELETES the" >&2
        echo "          live role and API execution logging stops for the whole region." >&2
        echo "          Re-run with:  APIGW_ACCOUNT_ROLE=true $0 --region $REGION" >&2
        exit 1
    else
        echo "    NOTE: $REGION already has an API Gateway account role, owned by another"
        echo "          stack:"
        echo "          $APIGW_ROLE_NOW"
        echo "          Leaving it alone. Do NOT set APIGW_ACCOUNT_ROLE here — creating it"
        echo "          is an account-wide overwrite that breaks that stack's API logging."
    fi
else
    if [ "$APIGW_ROLE_EXISTS" = true ] && [ "$APIGW_ROLE_IS_OURS" != true ]; then
        echo "REFUSING: APIGW_ACCOUNT_ROLE=true would overwrite an existing account-level" >&2
        echo "          API Gateway role in $REGION that this stack does not own:" >&2
        echo "          $APIGW_ROLE_NOW" >&2
        echo "          That silently breaks another stack's API access logging." >&2
        exit 1
    fi
    echo "    (creating the API Gateway account-level CloudWatch role)"
    CDK_CONTEXT+=(--context apigw_account_role="$APIGW_ACCOUNT_ROLE")
fi
# ACCOUNT_BUDGET: set on exactly ONE deployment in the account. Budget names are
# account-global, so a second deployment declaring it hard-fails DuplicateRecordException.
if [ -n "${ACCOUNT_BUDGET:-}" ]; then
    echo "    (declaring the account-wide budget — only ONE deployment may own it)"
    CDK_CONTEXT+=(--context account_budget="$ACCOUNT_BUDGET")
    [ -n "${ACCOUNT_BUDGET_LIMIT:-}" ] \
        && CDK_CONTEXT+=(--context account_budget_limit="$ACCOUNT_BUDGET_LIMIT")
fi
npx cdk deploy --require-approval never "${CDK_CONTEXT[@]}"
cd ..

echo ">>> Step 2/6: Reading stack outputs..."
OUTPUTS=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query 'Stacks[0].Outputs' --region "$REGION")
ADMIN_BUCKET=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="AdminBucketName") | .OutputValue')
USER_BUCKET=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="UserBucketName") | .OutputValue')
# The stack exports the shared bucket as an ARN; strip the prefix to get the name. Used
# only in the "Next steps" staging commands printed at the end — but it must be resolved
# HERE, because `set -u` turns an undefined variable in those echoes into a hard abort.
SHARED_BUCKET=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="SharedDataBucketArn") | .OutputValue' | sed 's|^arn:aws:s3:::||')
ADMIN_CF=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="AdminDistributionId") | .OutputValue')
USER_CF=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="UserDistributionId") | .OutputValue')
API_URL=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="ApiUrl") | .OutputValue')
POOL_ID=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="UserPoolId") | .OutputValue')
CLIENT_ID=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="UserPoolClientId") | .OutputValue')
ADMIN_URL=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="AdminUrl") | .OutputValue')
USER_URL=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="UserUrl") | .OutputValue')

echo ">>> Step 3/6: Generating frontend config..."
mkdir -p web/admin/public web/user/public
# Read the hosted-UI URL from the stack rather than assuming the prefix exists. The
# old hardcoded value made config.json look correct even while the UserPoolDomain was
# not declared in the CDK at all, so a fresh account got a config pointing at a
# hostname that does not resolve.
COGNITO_DOMAIN=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="CognitoHostedUiUrl") | .OutputValue')
if [ -z "$COGNITO_DOMAIN" ] || [ "$COGNITO_DOMAIN" = "null" ]; then
    echo "ERROR: stack output CognitoHostedUiUrl is missing — the Cognito hosted-UI" >&2
    echo "       domain is not deployed, so admin sign-in cannot work. Refusing to" >&2
    echo "       write a config.json that points at a nonexistent host." >&2
    exit 1
fi
ADMIN_CONFIG="{\"apiBaseUrl\":\"$API_URL\",\"cognitoPoolId\":\"$POOL_ID\",\"cognitoClientId\":\"$CLIENT_ID\",\"region\":\"$REGION\",\"cognitoDomain\":\"$COGNITO_DOMAIN\",\"cognitoRedirectUri\":\"$ADMIN_URL\",\"userDashboardUrl\":\"$USER_URL\"}"
echo "$ADMIN_CONFIG" > web/admin/public/config.json
USER_CONFIG="{\"apiBaseUrl\":\"$API_URL\",\"region\":\"$REGION\"}"
echo "$USER_CONFIG" > web/user/public/config.json

echo ">>> Step 4/6: Building frontends..."
cd web/admin && npm ci --silent && npm run build && cd ../..
cd web/user && npm ci --silent && npm run build && cd ../..

echo ">>> Step 5/6: Uploading to S3..."
aws s3 sync web/admin/dist/ "s3://$ADMIN_BUCKET/" --delete --region "$REGION" --quiet
aws s3 sync web/user/dist/ "s3://$USER_BUCKET/" --delete --region "$REGION" --quiet

echo ">>> Step 6/6: Invalidating CloudFront caches..."
aws cloudfront create-invalidation --distribution-id "$ADMIN_CF" --paths "/*" --output text > /dev/null
aws cloudfront create-invalidation --distribution-id "$USER_CF" --paths "/*" --output text > /dev/null

echo ""
# ---------------------------------------------------------------------------------
# Budget-alert deliverability check.
#
# An SNS EMAIL subscription is only live once the recipient clicks the confirmation
# link. CloudFormation reports CREATE_COMPLETE for the REQUEST, never waits, never
# retries, and SNS deletes an unconfirmed pending subscription after ~3 days. So a
# perfectly green stack can have a budget alarm with nowhere to deliver.
#
# That happened here: the subscription created 2026-07-02 was CREATE_COMPLETE in
# CloudFormation while SNS reported "Subscription does not exist" for the same ARN, so
# three days of ~$269 spend against a $200/day budget alerted nobody. Check every time.
ALERT_TOPIC=$(aws sns list-topics --region "$REGION" \
    --query "Topics[?contains(TopicArn,'av30lab-admin-notifications')].TopicArn" \
    --output text 2>/dev/null | head -1)
if [ -n "$ALERT_TOPIC" ]; then
    CONFIRMED=$(aws sns list-subscriptions-by-topic --region "$REGION" \
        --topic-arn "$ALERT_TOPIC" \
        --query "length(Subscriptions[?SubscriptionArn!='PendingConfirmation'])" \
        --output text 2>/dev/null)
    PENDING=$(aws sns list-subscriptions-by-topic --region "$REGION" \
        --topic-arn "$ALERT_TOPIC" \
        --query "length(Subscriptions[?SubscriptionArn=='PendingConfirmation'])" \
        --output text 2>/dev/null)
    if [ "${CONFIRMED:-0}" = "0" ]; then
        echo
        echo "!!! BUDGET ALERTS ARE NOT DELIVERABLE ($ALERT_TOPIC)"
        echo "    confirmed subscriptions: ${CONFIRMED:-0}   pending: ${PENDING:-0}"
        if [ "${PENDING:-0}" != "0" ]; then
            echo "    A confirmation email is waiting for $ADMIN_EMAIL — click the link in it."
            echo "    SNS DELETES the pending request after ~3 days and CloudFormation will"
            echo "    NOT recreate it, because it already considers the resource created."
        else
            echo "    There is no subscription at all. CloudFormation may still show one as"
            echo "    CREATE_COMPLETE — that is the request, not a live subscription."
            echo "    Re-request it, then click the link in the email:"
            echo "      aws sns subscribe --region $REGION --topic-arn $ALERT_TOPIC \\"
            echo "        --protocol email --notification-endpoint $ADMIN_EMAIL"
        fi
        echo "    Until this is confirmed the daily budget alarm alerts nobody."
        echo
    else
        echo ">>> Budget alerts deliverable: ${CONFIRMED} confirmed subscription(s)."
    fi
fi

echo "=== Deployment Complete ==="
echo "Admin Dashboard: $ADMIN_URL"
echo "API Endpoint:    $API_URL"
echo ""
# --- Stage notebook templates (repo -> S3) --------------------------------------------
# This was a MANUAL step printed under "Next steps", and that split of responsibilities bit
# real deployments twice. create_user copies templates OUT OF
# s3://<shared>/notebook-templates/ at provisioning time, so a participant created after a
# notebook change silently received the PREVIOUS notebooks — the copy step is automatic, the
# publish step was not. Measured 2026-09-26: a brand-new participant got a 9-cell M2 and an
# M5 whose pre-flight predated its own fix, because nobody had run this sync.
#
# The check below did not catch it either: it tests for PRESENCE of two helper files, so a
# stale-but-present M5 passes.
#
# Running it here is also SAFER than printing it. The comment on the Next-steps block records
# that copy-pasting the printed command into a fresh shell once re-seeded the FIRST region's
# bucket, because the standalone scripts defaulted to us-west-2. $SHARED_BUCKET and $REGION
# here are the ones that were actually deployed.
#
# --exclude is load-bearing, not tidiness: a local scripts/__pycache__ otherwise stages .pyc
# files that then sync into every participant workspace.
#
# Under `set -e` a failure here aborts the script. That is deliberate: provisioning returns
# HTTP 500 without these objects, so a deploy that cannot stage them is not a usable deploy.
if [ -n "${SHARED_BUCKET:-}" ]; then
    echo ">>> Staging notebook templates -> s3://$SHARED_BUCKET/notebook-templates/"
    aws s3 sync notebooks/ "s3://$SHARED_BUCKET/notebook-templates/" --region "$REGION" \
        --exclude '*__pycache__*' --exclude '*.pyc' --only-show-errors
    # scripts/ is staged as an EXPLICIT ALLOW-LIST, not a whole-directory sync.
    #
    # Whatever lands here is synced into EVERY participant's home directory by the
    # notebook-sync lifecycle config. A plain `aws s3 sync scripts/` therefore handed each
    # participant deploy.sh, teardown.sh, cache_models.sh and check_seeding.sh — measured in
    # users/0926-ky-s8g6e6/scripts/ on 2026-09-27. They cannot successfully RUN them (the
    # execution role has no CloudFormation/IAM rights), but shipping a file called
    # teardown.sh into a workshop attendee's home directory is indefensible, and the noise
    # buries the six files they actually need.
    #
    # ALLOW-list, not deny-list: with a deny-list every new admin script leaks by default,
    # which is exactly how these four got there. The list below was derived by grepping the
    # notebooks for what they actually LOAD (sys.path.insert + import, or `bash <script>`)
    # rather than what they merely mention in a message string — cache_models.sh,
    # refresh_instance_rates.py and stage_nuscenes.sh appear only inside printed "Admin:"
    # hints and are NOT needed here.
    #
    # Two entries are non-obvious and must not be pruned:
    #   * alpasim_ec2_setup.sh  — docs/en/M10_PARTICIPANT_SSM_RUNBOOK.md:76 does
    #     `aws s3 cp s3://$SHARED_BUCKET/notebook-templates/scripts/alpasim_ec2_setup.sh`,
    #     so removing it breaks M10's participant self-run path.
    #   * alpamayo_save_clip.py — ADMIN_GUIDE §6.3 runs it from a GPU JupyterLab terminal.
    #
    # Getting this list WRONG fails late and confusingly: the notebooks fall back to
    # `aws s3 cp .../notebook-templates/scripts/<file>` with check=True, so a missing entry
    # surfaces as a CalledProcessError in the middle of a module. If you add a notebook that
    # needs a new helper, add it here in the same commit.
    echo ">>> Staging participant scripts (allow-list) ..."
    for _s in av30_progress.py \
              av30_instance_rates.py \
              setup_cosmos_env.sh \
              setup_gsplat_env.sh \
              setup_nemo_curator_env.sh \
              alpamayo_infer.py \
              alpamayo_save_clip.py \
              alpasim_ec2_setup.sh
    do
        if [ ! -f "scripts/$_s" ]; then
            echo "ERROR: scripts/$_s is in the staging allow-list but does not exist." >&2
            echo "       A participant notebook will fail on its S3 fallback. Fix the" >&2
            echo "       allow-list in this script or restore the file." >&2
            exit 1
        fi
        aws s3 cp "scripts/$_s" \
            "s3://$SHARED_BUCKET/notebook-templates/scripts/$_s" \
            --region "$REGION" --only-show-errors
    done
    # Sweep everything under notebook-templates/scripts/ that is NOT in the allow-list
    # above. DENY BY DEFAULT — this replaces a list of 12 exact admin filenames.
    #
    # That list could only match names directly under scripts/, so it left
    # scripts/__pycache__/ behind. Measured 2026-09-27 in ap-northeast-2: the .pyc of
    # grab_gpu_instance.py, patch_notebooks.py and renumber_modules.py were still
    # published after their sources had been removed. .pyc decompiles, so removing only
    # the sources did not actually un-publish the tooling. A deny-list also leaks every
    # future admin script by default, which is how those got there in the first place.
    #
    # A file the notebooks genuinely need but that is missing from the allow-list gets
    # deleted here. That is correct: the cp loop above never publishes it, so its only
    # presence in S3 would be a leftover from an older whole-directory sync, and silently
    # depending on a leftover is worse than the loud failure the existence check above
    # gives. Strictly scoped to the scripts/ prefix — the notebooks themselves are
    # governed by the sync at the top of this block.
    _keep=" av30_progress.py av30_instance_rates.py setup_cosmos_env.sh setup_gsplat_env.sh\
 setup_nemo_curator_env.sh alpamayo_infer.py alpamayo_save_clip.py alpasim_ec2_setup.sh "
    _swept=0
    # Heredoc, not a pipe: `while read` in a pipeline runs in a subshell, and _swept
    # would not survive it. `|| true` because `aws s3 ls` exits non-zero on an absent
    # prefix and this script runs under `set -e`.
    while read -r _key; do
        [ -n "$_key" ] || continue
        _base="${_key#notebook-templates/scripts/}"
        case "$_keep" in *" $_base "*) continue ;; esac
        if aws s3 rm "s3://$SHARED_BUCKET/$_key" --region "$REGION" >/dev/null 2>&1; then
            echo "    swept (admin-only, not for participants): $_base"
            _swept=$((_swept + 1))
        fi
    done <<SWEEP
$(aws s3 ls "s3://$SHARED_BUCKET/notebook-templates/scripts/" --recursive --region "$REGION" 2>/dev/null \
    | awk '{ $1=""; $2=""; $3=""; sub(/^ +/, ""); print }' || true)
SWEEP
    [ "$_swept" -eq 0 ] || echo ">>> Swept $_swept non-allow-listed object(s) from notebook-templates/scripts/."
    STAGED_COUNT=$(aws s3 ls "s3://$SHARED_BUCKET/notebook-templates/" --recursive \
        --region "$REGION" | wc -l | tr -d ' ')
    echo ">>> Staged. notebook-templates/ now holds $STAGED_COUNT objects."
    echo ""
    # Existing participants are NOT refreshed by this. copy_notebook_templates runs once, at
    # provisioning; their users/<id>/ copy is whatever was staged back then.
    echo ">>> NOTE: participants provisioned BEFORE this deploy keep the notebooks they were"
    echo "    given. To hand them the new ones: admin dashboard -> Reset (clears that"
    echo "    participant's users/<id>/ outputs and re-copies templates), or Delete +"
    echo "    Add User. Newly added participants get the templates just staged."
    echo ""
fi

# Staged-template check — now a POST-condition on the sync above, not the mechanism.
# It tests for PRESENCE only, which is why it passed while a staged M5 was stale; the sync
# above is what keeps content current. Kept because head-object also proves the objects are
# READABLE, which a successful sync does not (a bucket policy or KMS change could break
# reads without breaking writes).
#
# The notebook cost cells in M3/M5/M6/M8/M9 read
# scripts/av30_instance_rates.py out of the participant workspace to price THIS region. If
# that file is not staged the conversion is INERT and nothing fails: four notebooks print
# "[cost] rate table unavailable" and M3 silently falls back to a us-west-2 rate regardless
# of box or region. Measured: absent from both regions' notebook-templates/scripts/ after
# the file was added, because the staging sync predates it.
if [ -n "${SHARED_BUCKET:-}" ]; then
    echo ""
    MISSING_STAGED=""
    for f in notebook-templates/scripts/av30_instance_rates.py \
             notebook-templates/scripts/av30_progress.py; do
        aws s3api head-object --bucket "$SHARED_BUCKET" --key "$f" --region "$REGION" \
            >/dev/null 2>&1 || MISSING_STAGED="$MISSING_STAGED $f"
    done
    if [ -n "$MISSING_STAGED" ]; then
        echo ">>> WARNING: helper files missing from the shared bucket:$MISSING_STAGED"
        echo "    Participant notebooks degrade SILENTLY without them (wrong prices, or no"
        echo "    progress reporting). Re-run the scripts/ sync in Next steps below."
    else
        echo ">>> Staged helpers present (instance rates + progress)."
    fi
fi

# Account-wide budget check. Every per-region budget is Region-filtered, so with only
# those, NOTHING measures the account total: two regions at $199/day each never alarm, and
# spend outside both is invisible. Budget names are account-global, so exactly ONE
# deployment may declare it (-c account_budget=true) — report the state rather than guess.
# `!CostFilters`, not `CostFilters==\`{}\``: for an UNFILTERED budget the API omits the
# CostFilters key entirely rather than returning an empty object, so the equality form
# matches nothing and would report "no account-wide budget" while one exists. Measured
# against this account: `==\`{}\`` -> 0, `!CostFilters` -> 1. Single-quoted so bash leaves
# the `!` alone.
ACCT_WIDE=$(aws budgets describe-budgets --account-id "$ACCOUNT_ID" \
    --query 'length(Budgets[?!CostFilters])' --output text 2>/dev/null || echo "?")
echo ""
if [ "$ACCT_WIDE" = "0" ]; then
    echo ">>> WARNING: this account has NO account-wide budget."
    echo "    Every av30lab budget is Region-filtered, so the account total is unmonitored."
    echo "    Own it from ONE deployment:  ACCOUNT_BUDGET=true ./scripts/deploy.sh --region $REGION"
elif [ "$ACCT_WIDE" = "?" ]; then
    echo ">>> NOTE: could not read budgets (needs budgets:DescribeBudgets); account-wide"
    echo "    coverage unverified."
else
    echo ">>> Account-wide budget(s): $ACCT_WIDE — account total is monitored."
fi

# The quota pre-flight already ran, BEFORE cdk deploy — see the top of this script.
# It used to run here, after the deploy, piped through `2>/dev/null | sed | grep` inside
# an `if …; then : fi`. That discarded stderr, the exit status, and (because the grep was
# case-sensitive while the report prints lowercase "quota 0 ml.…") most of the signal.
echo ""
echo "    Quota pre-flight ran before the deploy. Full report any time:"
echo "      ./scripts/check_quotas.py --region $REGION --participants N"

echo "Next steps:"
echo "  1. Create Cognito admin user: aws cognito-idp admin-create-user --user-pool-id $POOL_ID --username admin"
# Notebook templates are no longer listed here: this script stages them itself (see the
# staging block above). Leaving them as a manual step meant a deploy could finish "green"
# while the notebooks participants receive were the previous ones.
#
# AWS_REGION is spelled out on purpose on the lines below. They used to omit it, and the
# seeding scripts defaulted to us-west-2 — so copy-pasting into a fresh shell after deploying
# a second region re-seeded the FIRST region's bucket. Both scripts now refuse to guess, and
# these commands carry the region that was actually deployed.
echo "  2. Stage nuScenes:   AWS_REGION=$REGION ./scripts/stage_nuscenes.sh"
echo "  3. Pre-cache models: AWS_REGION=$REGION HF_TOKEN=xxx ./scripts/cache_models.sh"
# Steps 4-6 were MISSING, and their absence is the whole reason ap-northeast-2 shipped
# broken (2026-09-26). An operator who followed steps 1-3 verbatim got a region where
# M5, M6, M9 and M10 could not run: cache_models.sh seeds model-cache/ only, and
# nothing here even named the other three prefixes. Step 7 is what makes that
# detectable instead of discoverable-by-participant.
echo "  4. Copy HF cache:    aws s3 sync s3://av30lab-shared-data-$ACCOUNT_ID-<seeded-region>/hf-cache/ \\"
echo "                                   s3://$SHARED_BUCKET/hf-cache/ \\"
echo "                                   --source-region <seeded-region> --region $REGION"
echo "                       (~115 GiB / ~25-55 min. No seeded region to copy from? Build"
echo "                        it: AWS_REGION=$REGION HF_TOKEN=hf_... ./scripts/cache_hf_tree.sh"
echo "                        cache_models.sh writes a DIFFERENT prefix in a DIFFERENT"
echo "                        layout and cannot produce it. Needed by M5, M6, M9.)"
echo "  5. Copy M10 ref:     aws s3 sync s3://av30lab-shared-data-$ACCOUNT_ID-<seeded-region>/m10-reference/ \\"
echo "                                   s3://$SHARED_BUCKET/m10-reference/ \\"
echo "                                   --source-region <seeded-region> --region $REGION"
echo "  6. (hf-cache/alpamayo-demo/ comes along with step 4 — that is why step 4 syncs"
echo "      hf-cache/ and not hf-cache/hub/.)"
echo "  7. VERIFY before provisioning anyone:"
echo "                       ./scripts/check_seeding.sh --region $REGION --source-region <seeded-region>"

# Run it now, non-fatally. The real seeding happens AFTER this script returns, so a
# failure here is expected on a fresh region and must not look like a deploy failure —
# but printing the result turns "which prefixes still need seeding" into a fact rather
# than something the operator has to remember to check.
if [ -x ./scripts/check_seeding.sh ]; then
    echo ""
    echo "--- Seeding status right now (informational; seed then re-run step 7) ---"
    ./scripts/check_seeding.sh --region "$REGION" 2>&1 | sed 's/^/    /' || true
fi
