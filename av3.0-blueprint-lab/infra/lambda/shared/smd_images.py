"""SageMaker Distribution image ARNs — region → OWNING ACCOUNT.

SINGLE SOURCE OF TRUTH, read by BOTH runtimes:
  * the Lambda shared layer (`config.py`) at run time, and
  * the CDK stack (`infra/av30_constructs/api.py`) at synth time, loaded by path.

Deliberately DEPENDENCY-FREE (no boto3/botocore/aws_cdk imports) so the CDK side can
load it during synth without dragging the Lambda runtime's dependencies in, and so
there is no second copy of the table to drift.

WHY THIS TABLE HAS TO EXIST
---------------------------
The AWS account that OWNS the SageMaker Distribution images is DIFFERENT IN EVERY
REGION. It is NOT one account "published per-region":

    us-west-2       542918446943
    us-east-1       885854791233
    ap-northeast-2  064688005998
    eu-west-1       819792524951        ... and so on

So an image ARN CANNOT be built by substituting the region into a template. Doing
that was a real bug in this repo: both `config.py` and `api.py` hardcoded
`542918446943` and interpolated the deploy region, which is correct ONLY in
us-west-2. A deploy to any other region produced an ARN for an image that does not
exist there — and it does not fail at deploy time. It fails later, per participant,
when SageMaker tries to start the JupyterLab app, which is the worst possible place
to discover it.

Source (verified 2026-09-23), "SageMaker Distribution Image ARN Format" column of:
https://docs.aws.amazon.com/sagemaker/latest/dg/notebooks-available-images.html

Accounts are STRINGS: three of them have a leading zero (us-west-1, eu-west-2,
ap-northeast-2), which an int would silently eat.

Commercial partition (`aws`) only. GovCloud and China are not in the AWS table above
and are not supported by this lab.
"""

from __future__ import annotations

# region -> account that owns the SageMaker Distribution images in that region
SMD_OWNER_ACCOUNT_BY_REGION: dict[str, str] = {
    "us-east-1": "885854791233",
    "us-east-2": "137914896644",
    "us-west-1": "053634841547",
    "us-west-2": "542918446943",
    "af-south-1": "238384257742",
    "ap-east-1": "523751269255",
    "ap-south-1": "245090515133",
    "ap-northeast-1": "010972774902",
    "ap-northeast-2": "064688005998",
    "ap-northeast-3": "564864627153",
    "ap-southeast-1": "022667117163",
    "ap-southeast-2": "648430277019",
    "ap-southeast-3": "370607712162",
    "ca-central-1": "481561238223",
    "eu-central-1": "545423591354",
    "eu-west-1": "819792524951",
    "eu-west-2": "021081402939",
    "eu-west-3": "856416204555",
    "eu-north-1": "175620155138",
    "eu-south-1": "810671768855",
    "sa-east-1": "567556641782",
    "me-south-1": "523774347010",
    "me-central-1": "358593528301",
}

# region -> account that owns the FIRST-PARTY SageMaker images in that region.
#
# A SECOND, UNRELATED SERIES. The same AWS page publishes two columns: "Image ARN
# Format" (first-party images such as `jupyter-server-3`, `sagemaker-data-science-v5`)
# and "SageMaker Distribution Image ARN Format". The accounts differ between the two
# even within one region — us-west-2 is 236514542706 for first-party and
# 542918446943 for Distribution. Mixing them up produces a valid-looking ARN for an
# image that does not exist, with the same silent, per-participant failure mode.
#
# Used for the Studio domain's JupyterServer default image
# (infra/stacks/av30_stack.py), which was likewise pinned to the us-west-2 account.
FIRST_PARTY_IMAGE_ACCOUNT_BY_REGION: dict[str, str] = {
    "us-east-1": "081325390199",
    "us-east-2": "429704687514",
    "us-west-1": "742091327244",
    "us-west-2": "236514542706",
    "af-south-1": "559312083959",
    "ap-east-1": "493642496378",
    "ap-south-1": "394103062818",
    "ap-northeast-1": "102112518831",
    "ap-northeast-2": "806072073708",
    "ap-northeast-3": "792733760839",
    "ap-southeast-1": "492261229750",
    "ap-southeast-2": "452832661640",
    "ap-southeast-3": "276181064229",
    "ca-central-1": "310906938811",
    "eu-central-1": "936697816551",
    "eu-west-1": "470317259841",
    "eu-west-2": "712779665605",
    "eu-west-3": "615547856133",
    "eu-north-1": "243637512696",
    "eu-south-1": "592751261982",
    "sa-east-1": "782484402741",
    "me-south-1": "117516905037",
    "me-central-1": "103105715889",
}

# The two Distribution images this lab uses. "cpu" / "gpu" are the resource-identifier
# suffixes, not tags — the version is pinned separately via SageMakerImageVersionAlias.
_VARIANTS = ("cpu", "gpu")


class UnsupportedRegionError(ValueError):
    """Raised for a region with no known SageMaker Distribution owner account.

    Raised rather than falling back to a default account ON PURPOSE. A wrong account
    produces a syntactically valid ARN for a nonexistent image, so a fallback would
    convert a loud synth-time error into a silent per-participant app failure.
    """


def smd_image_arn(region: str, variant: str) -> str:
    """Full SageMaker Distribution image ARN for a region.

    >>> smd_image_arn("us-west-2", "gpu")
    'arn:aws:sagemaker:us-west-2:542918446943:image/sagemaker-distribution-gpu'
    """
    if variant not in _VARIANTS:
        raise ValueError(f"variant must be one of {_VARIANTS}, got {variant!r}")
    try:
        account = SMD_OWNER_ACCOUNT_BY_REGION[region]
    except KeyError:
        raise UnsupportedRegionError(
            f"No SageMaker Distribution owner account known for region {region!r}. "
            f"The owning account differs per region, so it cannot be guessed. Look up "
            f"the 'SageMaker Distribution Image ARN Format' column at "
            f"https://docs.aws.amazon.com/sagemaker/latest/dg/notebooks-available-images.html "
            f"and add it to SMD_OWNER_ACCOUNT_BY_REGION in "
            f"infra/lambda/shared/smd_images.py. Supported today: "
            f"{', '.join(sorted(SMD_OWNER_ACCOUNT_BY_REGION))}"
        ) from None
    return f"arn:aws:sagemaker:{region}:{account}:image/sagemaker-distribution-{variant}"


def first_party_image_arn(region: str, resource_identifier: str) -> str:
    """Full ARN for a FIRST-PARTY SageMaker image (not a Distribution image).

    >>> first_party_image_arn("us-west-2", "jupyter-server-3")
    'arn:aws:sagemaker:us-west-2:236514542706:image/jupyter-server-3'
    """
    if not resource_identifier:
        raise ValueError("resource_identifier is required, e.g. 'jupyter-server-3'")
    try:
        account = FIRST_PARTY_IMAGE_ACCOUNT_BY_REGION[region]
    except KeyError:
        raise UnsupportedRegionError(
            f"No first-party SageMaker image account known for region {region!r}. "
            f"Note this is a DIFFERENT account series from the Distribution images — "
            f"take it from the 'Image ARN Format' column (not 'SageMaker Distribution "
            f"Image ARN Format') at "
            f"https://docs.aws.amazon.com/sagemaker/latest/dg/notebooks-available-images.html "
            f"and add it to FIRST_PARTY_IMAGE_ACCOUNT_BY_REGION in "
            f"infra/lambda/shared/smd_images.py. Supported today: "
            f"{', '.join(sorted(FIRST_PARTY_IMAGE_ACCOUNT_BY_REGION))}"
        ) from None
    return f"arn:aws:sagemaker:{region}:{account}:image/{resource_identifier}"


def supported_regions() -> list[str]:
    """Regions with BOTH account series known — the ones this lab can deploy to."""
    return sorted(set(SMD_OWNER_ACCOUNT_BY_REGION) & set(FIRST_PARTY_IMAGE_ACCOUNT_BY_REGION))
