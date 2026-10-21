"""Shared constants for the lab's CDK constructs.

Values here are ones that MUST be identical in two places that cannot see each other:
the CloudFormation resource that creates something, and the Lambda environment that later
reasons about it. Duplicating such a value as two literals is how the storage display came
to disagree with the actual volume — the domain created 5 GB while
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
