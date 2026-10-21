#!/usr/bin/env python3
"""M9 Alpamayo 1.5 VLA inference — runs INSIDE the a1_5 venv (alpamayo_env.sh).

Why this script exists
----------------------
The shipped M9 notebook imported a hallucinated `alpamayo` package
(`AlpamayoForConditionalGeneration`, `AlpamayoInferencePipeline`, ...) that does
not exist. The REAL workflow is the NVlabs/alpamayo1.5 repo (package
`alpamayo1_5`). The bespoke inference is ~40 lines with no repo CLI equivalent
to Cosmos's `examples/inference.py`, so we commit it here and the notebook calls
it via `bash -lc 'source alpamayo_env.sh && python scripts/alpamayo_infer.py ...'`
(same shape as M5/M6). The model is loaded ONCE and looped over every demo clip.

Offline / no-token design
--------------------------
`load_physical_aiavdataset` (physical_ai_av) CANNOT run offline — it calls
`list_repo_refs()` unconditionally, needing a network + gated HF token. So the
admin pre-saves each demo clip's `data` dict with `torch.save` (see
scripts/README or docs/en/ALPAMAYO_M9.md); this script only `torch.load`s those
`.pt` files and NEVER imports physical_ai_av. The model + its hidden
Cosmos-Reason2-8B VLM backbone load from the S3-restored HF cache with
`HF_HUB_OFFLINE=1` (set by alpamayo_env.sh when the cache is present).

flash-attn is not installed on the SMD image, so we pass
`attn_implementation="sdpa"` explicitly (the repo default is flash_attention_2).

Outputs (plain .npy/.txt/.json so the notebook kernel needs no torch):
  <out>/<clip_id>_pred.npy   predicted trajectory  (num_samples, 64, 3)
  <out>/<clip_id>_gt.npy     ground-truth future   (64, 3)
  <out>/<clip_id>_cot.txt    Chain-of-Causation reasoning text
  <out>/metrics.json         {"results": [{clip_id, minADE_m, cot_chars}, ...]}
"""
import argparse
import json
import os

import numpy as np
import torch

from alpamayo1_5 import helper
from alpamayo1_5.models.alpamayo1_5 import Alpamayo1_5


def min_ade(pred_xyz, gt_future_xyz):
    """minADE over trajectory samples, in metres (X-Y plane).

    Reproduces the verified computation (minADE 0.375 m on clip 030c760c):
        gt = ego_future_xyz[0,0,:,:2].T            -> (2, T)
        pr = pred_xyz[0,0,:,:,:2].transpose(0,2,1) -> (S, 2, T)
        minADE = ||pr - gt||_2 over xy, mean over T, min over samples.
    """
    gt = gt_future_xyz.float().cpu().numpy()[0, 0, :, :2].T          # (2, T)
    pr = pred_xyz.float().cpu().numpy()[0, 0, :, :, :2].transpose(0, 2, 1)  # (S, 2, T)
    per_sample_ade = np.linalg.norm(pr - gt[None, ...], axis=1).mean(-1)     # (S,)
    return float(per_sample_ade.min())


def _coerce_cot(x):
    """Chain-of-Causation text can come back as a plain str, a numpy.str_, bytes,
    or a 0-d/1-element numpy array wrapping one of those (varies by run). Normalize
    to a plain Python str so it can be written to a .txt file."""
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    if isinstance(x, bytes):
        return x.decode("utf-8", "replace")
    item = getattr(x, "item", None)   # numpy scalar / 0-d array
    if callable(item):
        try:
            v = x.item()
            return v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)
        except Exception:
            pass
    return str(x)


# Top-level Alpamayo1_5 submodules that make up the diffusion "action stack".
# The rollout does `device = input_ids.device` and `self.diffusion.sample(device=device)`,
# so the expert + its projections + diffusion must ALL live on the SAME device as
# the inputs, or the diffusion KV-cache loop hits a cross-device torch.cat.
_ACTION_STACK_PREFIXES = (
    "expert",
    "diffusion",
    "action_space",
    "action_in_proj",
    "action_out_proj",
)


def _load_balanced_expert(model_id, *, dtype, attn_implementation, expert_gpu=0):
    """g5 fallback: shard the big VLM across GPUs (as accelerate's `auto` does) but
    pin the ENTIRE action stack (expert, diffusion, action_* projections) onto ONE
    GPU so the diffusion rollout + its KV cache are device-self-consistent.

    Zero-guess: we first load with device_map="auto" (known-good on g5), read the
    REAL hf_device_map, override only the action-stack keys to `expert_gpu`, then
    reload with that explicit map. No hardcoded layer names.
    """
    print("[balanced-expert] probing accelerate 'auto' layout ...", flush=True)
    probe = Alpamayo1_5.from_pretrained(
        model_id, dtype=dtype, attn_implementation=attn_implementation,
        device_map="auto",
    )
    auto_map = dict(getattr(probe, "hf_device_map", {}) or {})
    del probe
    torch.cuda.empty_cache()

    if not auto_map:
        raise RuntimeError("balanced-expert: empty hf_device_map from the auto probe.")

    # Pin every action-stack key to expert_gpu; leave the VLM sharding as auto placed it.
    device_map = dict(auto_map)
    pinned = []
    for k in device_map:
        top = k.split(".")[0]
        if top in _ACTION_STACK_PREFIXES:
            device_map[k] = expert_gpu
            pinned.append(k)
    print(f"[balanced-expert] pinned {len(pinned)} action-stack keys -> cuda:{expert_gpu} "
          f"(e.g. {pinned[:4]})", flush=True)

    model = Alpamayo1_5.from_pretrained(
        model_id, dtype=dtype, attn_implementation=attn_implementation,
        device_map=device_map,
    )
    _wrap_expert_cache_to_device(model, torch.device(f"cuda:{expert_gpu}"))
    return model, f"cuda:{expert_gpu}"


def _move_cache_to_device(pkv, dev):
    """Move a transformers Cache's interior key/value tensors onto `dev` in place."""
    if pkv is None:
        return pkv
    if hasattr(pkv, "to"):
        try:
            return pkv.to(dev)
        except Exception:
            pass
    # DynamicCache variants: either flat key_cache/value_cache lists, or per-layer objects.
    for attr in ("key_cache", "value_cache"):
        lst = getattr(pkv, attr, None)
        if isinstance(lst, list):
            for i, t in enumerate(lst):
                if t is not None and hasattr(t, "device") and t.device != dev:
                    lst[i] = t.to(dev)
    layers = getattr(pkv, "layers", None)
    if layers is not None:
        for layer in layers:
            for attr in ("keys", "values"):
                t = getattr(layer, attr, None)
                if t is not None and hasattr(t, "device") and t.device != dev:
                    setattr(layer, attr, t.to(dev))
    return pkv


def _wrap_expert_cache_to_device(model, dev):
    """Wrap expert.forward so the VLM-produced past_key_values is migrated onto the
    expert's device before use (accelerate does NOT auto-move Cache interiors)."""
    orig = model.expert.forward

    def fwd(*args, **kwargs):
        if kwargs.get("past_key_values") is not None:
            kwargs["past_key_values"] = _move_cache_to_device(kwargs["past_key_values"], dev)
        return orig(*args, **kwargs)

    model.expert.forward = fwd


def _first_input_device(model):
    """Device where the input ids should go on a sharded model — the embedding
    layer's device. Falls back to the first hf_device_map entry, then plain cuda."""
    dev_map = getattr(model, "hf_device_map", None) or {}
    for k, v in dev_map.items():
        if "embed_tokens" in k:
            return f"cuda:{v}" if isinstance(v, int) else str(v)
    first = next(iter(dev_map.values()), None)
    if isinstance(first, int):
        return f"cuda:{first}"
    if isinstance(first, str) and first not in ("cpu", "disk"):
        return first
    return "cuda"


def main():
    ap = argparse.ArgumentParser(description="M9 Alpamayo 1.5 VLA inference")
    ap.add_argument("--clips", nargs="+", required=True,
                    help="Local .pt paths (from load_physical_aiavdataset + torch.save)")
    ap.add_argument("--out", required=True, help="Output directory")
    ap.add_argument("--model", default="nvidia/Alpamayo-1.5-10B")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--top-p", type=float, default=0.98)
    ap.add_argument("--temperature", type=float, default=0.6)
    ap.add_argument("--num-samples", type=int, default=1)
    ap.add_argument("--max-gen-len", type=int, default=256)
    ap.add_argument(
        "--device-map", default="",
        help="Placement. Empty (default) = single GPU via .to('cuda') (verified on "
             "p5/p4d, one >=40GB GPU). 'balanced-expert' = shard the VLM across GPUs "
             "but pin the action stack (expert/diffusion/action_*) onto cuda:0 "
             "(g5.48xlarge = 8x A10G 24GB, no single 40GB GPU). 'auto' = plain "
             "accelerate shard (NOTE: breaks the diffusion KV cache — use "
             "balanced-expert instead).",
    )
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    if not torch.cuda.is_available():
        raise SystemExit("ERROR: no CUDA device visible — M9 needs a GPU instance.")

    device_map = a.device_map.strip() or None
    print(f"Loading {a.model} (sdpa, bf16, device_map={device_map or 'single-cuda'}) ...",
          flush=True)
    # attn_implementation="sdpa" is REQUIRED: flash-attn is excluded on the SMD
    # image, and the repo default would try flash_attention_2 and ImportError.
    if device_map == "balanced-expert":
        model, input_device = _load_balanced_expert(
            a.model, dtype=torch.bfloat16, attn_implementation="sdpa",
        )
    elif device_map:
        # Plain accelerate shard — placement decided by accelerate; do NOT call .to().
        model = Alpamayo1_5.from_pretrained(
            a.model,
            dtype=torch.bfloat16,
            attn_implementation="sdpa",
            device_map=device_map,
        )
        input_device = _first_input_device(model)
    else:
        model = Alpamayo1_5.from_pretrained(
            a.model,
            dtype=torch.bfloat16,
            attn_implementation="sdpa",
        ).to("cuda")
        input_device = "cuda"
    processor = helper.get_processor(model.tokenizer)
    print(f"Model + processor ready. input_device={input_device}", flush=True)

    results = []
    for pt in a.clips:
        # Trusted admin-produced file; torch 2.8 defaults weights_only=True which
        # would reject the int/str entries in the dict, so load with False.
        data = torch.load(pt, weights_only=False)
        clip_id = str(data.get("clip_id") or os.path.splitext(os.path.basename(pt))[0])
        print(f"=== {clip_id} ===", flush=True)

        messages = helper.create_message(
            frames=data["image_frames"].flatten(0, 1),
            camera_indices=data["camera_indices"],
        )
        inputs = processor.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=False,
            continue_final_message=True,
            return_dict=True,
            return_tensors="pt",
        )
        mi = helper.to_device(
            {
                "tokenized_data": inputs,
                "ego_history_xyz": data["ego_history_xyz"],
                "ego_history_rot": data["ego_history_rot"],
            },
            input_device,
        )
        torch.cuda.manual_seed_all(a.seed)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            pred_xyz, _, extra = model.sample_trajectories_from_data_with_vlm_rollout(
                data=mi,
                top_p=a.top_p,
                temperature=a.temperature,
                num_traj_samples=a.num_samples,
                max_generation_length=a.max_gen_len,
                return_extra=True,
            )

        cot = ""
        cot_list = (extra or {}).get("cot")
        if cot_list is not None and len(cot_list) > 0:
            cot = _coerce_cot(cot_list[0])
        m = min_ade(pred_xyz, data["ego_future_xyz"])

        np.save(os.path.join(a.out, f"{clip_id}_pred.npy"),
                pred_xyz.float().cpu().numpy())
        np.save(os.path.join(a.out, f"{clip_id}_gt.npy"),
                data["ego_future_xyz"].float().cpu().numpy())
        with open(os.path.join(a.out, f"{clip_id}_cot.txt"), "w") as f:
            f.write(cot)

        print(f"  minADE = {m:.3f} m   cot_chars = {len(cot)}", flush=True)
        results.append({"clip_id": clip_id, "minADE_m": round(m, 4),
                        "cot_chars": len(cot)})

    with open(os.path.join(a.out, "metrics.json"), "w") as f:
        json.dump({"results": results}, f, indent=2)
    print(f"DONE: {len(results)} clip(s) -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
