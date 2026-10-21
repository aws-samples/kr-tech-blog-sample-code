#!/usr/bin/env python3
"""CDK app entry point for AV 3.0 Blueprint Lab."""

import os

import aws_cdk as cdk

from stacks.av30_stack import Av30BlueprintLabStack

app = cdk.App()

# Region resolution order: -c region, then CDK_DEFAULT_REGION. There is deliberately NO
# literal default. The old `os.environ.get("CDK_DEFAULT_REGION", "us-west-2")` meant that
# an unset environment silently synthesized the PRIMARY region's stack — so an operator
# intending to deploy a second region could redeploy over the live one instead. Two
# independent region sources (this and scripts/deploy.sh) with a shared silent default is
# exactly how that goes unnoticed; deploy.sh now passes -c region so they cannot disagree.
_region = app.node.try_get_context("region") or os.environ.get("CDK_DEFAULT_REGION")
if not _region:
    raise SystemExit(
        "No region: pass -c region=<region> or set CDK_DEFAULT_REGION/AWS_REGION. "
        "This app will not default, because defaulting deploys to the wrong region."
    )

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=_region,
)

Av30BlueprintLabStack(
    app,
    "Av30BlueprintLabStack",
    env=env,
    description="AV 3.0 Blueprint Lab - Multi-user NVIDIA + AWS Physical AI Platform",
)

app.synth()
