#!/usr/bin/env python3
"""ADMIN one-time helper — pre-save an Alpamayo demo clip's `data` dict to a .pt.

Run this ONCE per demo clip on a GPU app WITH an HF token + accepted licenses
(online). It calls `load_physical_aiavdataset` — which needs the network + a
gated token — and `torch.save`s the resulting `data` dict (~100 MB, mostly the
4-camera image frames). Participants then `torch.load` that .pt and NEVER touch
physical_ai_av (which cannot run offline), so they need no HF token.

Usage (inside the a1_5 venv, HF_TOKEN set, HF_HUB_OFFLINE unset):
    source /mnt/sagemaker-nvme/cosmos-work/alpamayo_env.sh
    unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE            # this step MUST be online
    export HF_TOKEN=hf_xxx                                # accepted PhysicalAI-AV license
    python scripts/alpamayo_save_clip.py \
        --clip 030c760c-ae38-49aa-9ad8-f5650a545d26 --t0-us 5100000 \
        --out /mnt/sagemaker-nvme/m6_work/clips
Then upload:
    aws s3 cp <out>/<clip>.pt s3://<shared>/hf-cache/alpamayo-demo/

The upload target is under hf-cache/ on purpose: the SageMaker execution role can
write only hf-cache/* on the shared bucket, so both this admin upload and the
participant read line up with one prefix. (The participant notebook's DEMO_PREFIX
matches: hf-cache/alpamayo-demo/.)
"""
import argparse
import os

import torch

from alpamayo1_5.load_physical_aiavdataset import load_physical_aiavdataset


def main():
    ap = argparse.ArgumentParser(description="Pre-save an Alpamayo demo clip to .pt")
    ap.add_argument("--clip", required=True, help="Alpamayo clip_id")
    ap.add_argument("--t0-us", type=int, default=5_100_000, help="Clip start time (microseconds)")
    ap.add_argument("--out", required=True, help="Output directory for <clip>.pt")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    if os.environ.get("HF_HUB_OFFLINE"):
        raise SystemExit(
            "ERROR: HF_HUB_OFFLINE is set. This admin step streams the gated "
            "PhysicalAI-Autonomous-Vehicles dataset and MUST run online. "
            "`unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE` and export a valid HF_TOKEN."
        )

    print(f"Loading clip {a.clip} @ t0_us={a.t0_us} (online, streaming from HF) ...", flush=True)
    data = load_physical_aiavdataset(a.clip, t0_us=a.t0_us)
    out_pt = os.path.join(a.out, f"{a.clip}.pt")
    torch.save(data, out_pt)
    size_mb = os.path.getsize(out_pt) / 1e6
    print(f"Saved {out_pt} ({size_mb:.1f} MB)", flush=True)
    print("keys:", list(data.keys()), flush=True)
    print(f"Next: aws s3 cp {out_pt} s3://<shared>/hf-cache/alpamayo-demo/", flush=True)


if __name__ == "__main__":
    main()
