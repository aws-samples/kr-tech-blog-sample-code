#!/usr/bin/env python3
"""ADMIN one-time helper — pre-save an Alpamayo demo clip's `data` dict to a .pt.

Run this ONCE per demo clip on a GPU app WITH an HF token + accepted licenses
(online). It calls `load_physical_aiavdataset` — which needs the network + a
gated token — and `torch.save`s the resulting `data` dict (~100 MB, mostly the
4-camera image frames). Participants then `torch.load` that .pt and NEVER touch
physical_ai_av (which cannot run offline), so they need no HF token.

PRECONDITION: run this only on a stack where no participant profile exists yet, or
once the user-workspace bucket is isolated per user. Until then every participant can
write users/<your-profile>/, which the app copies into this home directory at every
start, so a planted .bashrc, IPython startup file or replaced copy of THIS script would
control both the .pt and the sha256 printed for it, and would see the HF_TOKEN you
export here. The hash only proves the file did not change after it left the app. On a
stack that already ran a workshop, delete the participants' profiles first and use a
fresh profile of your own (a new space under the old profile copies the same prefix).

Usage (inside the a1_5 venv, HF_TOKEN set, HF_HUB_OFFLINE unset):
    source /mnt/sagemaker-nvme/cosmos-work/alpamayo_env.sh
    unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE            # this step MUST be online
    export HF_TOKEN=hf_xxx                                # accepted PhysicalAI-AV license
    python scripts/alpamayo_save_clip.py \
        --clip 030c760c-ae38-49aa-9ad8-f5650a545d26 --t0-us 5100000 \
        --out /mnt/sagemaker-nvme/m6_work/clips

The script prints the .pt's sha256. Publishing is NOT done from this terminal:
    1. Copy the printed sha256 by hand into your own notes. Do not store it in S3
       next to the clip, where it could be replaced together with the clip.
    2. Move the .pt off the app: copy it into your home directory and Download it
       from the JupyterLab file browser, or
       aws s3 cp <out>/<clip>.pt s3://$USER_BUCKET/users/$USER_PROFILE/staging/
    3. On your admin workstation, with admin credentials: recompute the sha256,
       require it to match step 1, then
       aws s3 cp <clip>.pt s3://<shared>/hf-cache/alpamayo-demo/
    Full procedure: docs/en/ADMIN_GUIDE.md §6.3.

Why not upload from here: the SageMaker execution role is shared by every
participant and has no write on the shared bucket, on purpose. Participants'
M9 kernels unpickle these files (torch.load(weights_only=False) runs code), so
hf-cache/ must be writable only with admin credentials, and those credentials
must never be pasted into a Studio terminal — its home directory is synced from
S3 at every app start. (The participant notebook's DEMO_PREFIX matches:
hf-cache/alpamayo-demo/.)
"""
import argparse
import hashlib
import os

import torch

from alpamayo1_5.load_physical_aiavdataset import load_physical_aiavdataset


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


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

    print("PRECONDITION: no participant profile exists on this stack yet, or the "
          "user-workspace bucket is isolated per user (see this script's docstring and "
          "docs/en/ADMIN_GUIDE.md §6.3). Otherwise stop: a participant could have planted "
          "files in this home directory.", flush=True)
    print(f"Loading clip {a.clip} @ t0_us={a.t0_us} (online, streaming from HF) ...", flush=True)
    data = load_physical_aiavdataset(a.clip, t0_us=a.t0_us)
    out_pt = os.path.join(a.out, f"{a.clip}.pt")
    torch.save(data, out_pt)
    size_mb = os.path.getsize(out_pt) / 1e6
    print(f"Saved {out_pt} ({size_mb:.1f} MB)", flush=True)
    print("keys:", list(data.keys()), flush=True)

    digest = _sha256(out_pt)
    user_bucket = os.environ.get("USER_BUCKET", "<user-bucket>")
    profile = os.environ.get("USER_PROFILE", "<your-admin-profile>")
    name = os.path.basename(out_pt)
    print(f"sha256  {digest}  {name}", flush=True)
    print("  (This hash proves only that the file does not change after it leaves this "
          "app. It is trustworthy only if the precondition above held.)", flush=True)
    print("", flush=True)
    print("Next — do NOT upload to hf-cache/ from this terminal (the execution role "
          "cannot write the shared bucket, by design):", flush=True)
    print("  1. Copy the sha256 above by hand into your own notes (not into S3).", flush=True)
    print("  2. Move the .pt off this app: copy it into ~ and Download it from the file "
          "browser, or", flush=True)
    print(f"       aws s3 cp {out_pt} s3://{user_bucket}/users/{profile}/staging/", flush=True)
    print("  3. On your admin workstation (admin credentials): check the sha256 matches "
          "step 1, then", flush=True)
    print(f"       aws s3 cp {name} s3://<shared>/hf-cache/alpamayo-demo/", flush=True)
    print("  Full procedure: docs/en/ADMIN_GUIDE.md §6.3", flush=True)


if __name__ == "__main__":
    main()
