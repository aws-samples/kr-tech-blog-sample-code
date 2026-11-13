"""Shared constants for the lab's CDK constructs.

Values here are ones that MUST be identical in two places that cannot see each other:
the CloudFormation resource that creates something, and the Lambda environment (or the WAF
rule) that later reasons about it. Duplicating such a value as two literals is how the
storage display came to disagree with the actual volume — the domain created 5 GB while
`expand_storage` assumed 5 and `pipeline-config.ts` displayed 20/50/100/200.
"""

# EBS volume size, in GB, that a participant's JupyterLab space is created with.
#
# Consumed in exactly two places, which is the point:
#   * infra/av30_constructs/sagemaker.py — the domain's DefaultEbsVolumeSizeInGb, i.e. what
#     create_space() inherits.
#   * infra/av30_constructs/api.py — injected as the DEFAULT_SPACE_STORAGE_GB env var so
#     infra/lambda/shared/config.py reads the same number.
#
# 200 GB matches the largest per-module recommendation in
# web/user/src/data/pipeline-config.ts, so no module needs a mid-lab resize. gp3 in
# ap-northeast-2 is $0.0912/GB-month => ~$18.24 per participant per month. AWS does not
# allow SHRINKING a space's EBS volume, so raising this is a one-way decision for every
# space created afterwards; growing later is available to participants via +50/+200
# (expand_storage, ceiling MAX_STORAGE_GB = 500).
DEFAULT_SPACE_STORAGE_GB = 200

# SageMaker Distribution image version the dashboard and the Lambdas must agree on.
#
# This was the "next one" the note here used to point at: the literal "4.2.1" lived in BOTH
# infra/av30_constructs/api.py (as the SMD_IMAGE_VERSION_ALIAS env value) and
# infra/lambda/shared/config.py (as the os.environ.get fallback). Same drift hazard as the
# storage constant above, and the failure is quieter: if the two disagree, the Lambda that
# builds a space's ResourceSpec asks for a different image than the one the rest of the lab
# was verified against, and nothing reports a mismatch — the app just starts on an image
# whose CUDA/conda layout the setup scripts were never tested on.
#
# 4.2.1 is the version this lab is verified on. Do NOT use "latest": the alias floats, so a
# silent upstream bump would change the image under a cohort mid-workshop.
#
# config.py keeps `os.environ.get("SMD_IMAGE_VERSION_ALIAS", "4.2.1")`. That fallback is
# defence in depth for a Lambda invoked without the env var, NOT a second source of truth —
# api.py injects this value, and this file is where the number changes.
SMD_IMAGE_VERSION_ALIAS = "4.2.1"

# API Gateway stage name. api.py uses it for the stage and for the API_URL env var, and the
# WAF rule below matches it as an optional path prefix.
API_STAGE_NAME = "prod"

# Raw URI paths of the participant (token-authorizer) routes, for the WAF rule in auth.py.
#
# With admin_ip_allowlist set, the WebACL is attached to the WHOLE stage and its default
# action is Block, so an IP rule alone also blocks every participant: the dashboard runs in
# their browser and the notebooks POST progress from SageMaker-managed egress, neither from
# an admin IP. A second Allow rule lets these paths through from any IP. They still need a
# valid participant token, which the token authorizer checks after WAF. Everything else,
# including any route added later, stays IP-restricted unless it is added here (fail closed).
#
# Must match exactly the token-auth routes in api.py, and nothing else:
#   /presigned-url/{userId}
#   /sessions/{id}/instance-type | storage | progress | app-status
#   /modules/{id}/instance-options
# Method-agnostic on purpose: the browser's OPTIONS preflight on these paths must pass too.
#
# Written against the RAW path, because auth.py applies TextTransformation NONE:
#   * "/+" because both SPAs join the ApiUrl output (which ends in "/prod/") with a path
#     that starts with "/", so real requests look like /prod//sessions/... .
#   * The stage prefix is optional, so the rule holds whether or not WAF sees it.
#   * NO URL_DECODE or NORMALIZE_PATH. API Gateway keeps "%2F" inside a single {param}, so
#     it routes DELETE /prod/users/..%2Fpresigned-url%2Fx to DELETE /users/{id}, while a WAF
#     that decodes and resolves ".." would see /prod/presigned-url/x, a participant path.
#     The segment class has no "%" and no ".", so a raw path this matches cannot route
#     anywhere else in API Gateway.
#   * Non-capturing groups only: WAF regex does not support capturing subexpressions.
# A participant id is a SageMaker user-profile name, so [A-Za-z0-9-] covers every valid
# one; module ids are the m01-... slugs in web/user/src/data/pipeline-config.ts.
_SEG = "[A-Za-z0-9-]+"
PARTICIPANT_ROUTE_REGEX = (
    rf"^(?:/+{API_STAGE_NAME})?/+(?:presigned-url/+{_SEG}"
    rf"|sessions/+{_SEG}/+(?:instance-type|storage|progress|app-status)"
    rf"|modules/+{_SEG}/+instance-options)/*$"
)
