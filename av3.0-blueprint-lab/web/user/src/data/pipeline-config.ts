export type ModuleStatus = "completed" | "in-progress" | "locked";

// Blog-aligned pipeline phases (columns in the map). The AWS+NVIDIA AV 3.0 blog
// groups its 8 stages; here we group the 12 lab modules into 5 balanced columns.
export type Phase = "ingest" | "curate" | "augment" | "train" | "validate";

export interface ModuleConfig {
  id: string;
  title: string;
  phase: Phase;
  tool: string;
  version: string;
  status: ModuleStatus;
  license: string;
  sourceUrl: string;
  // IMPORTANT: instance names MUST be SageMaker-prefixed ("ml.<family>.<size>")
  // and MUST exist in the backend INSTANCE_RATES table (infra/lambda/shared/
  // config.py). The change-instance Lambda rejects any type not in that table,
  // and the GPU-image auto-selection keys off the "ml.g*/ml.p*" prefix.
  recommendedInstance: string;
  alternatives: string[];
  // RECOMMENDED capacity for this module, in GB — NOT the provisioned volume.
  //
  // Every space is created at the domain's DefaultEbsVolumeSizeInGb
  // (DEFAULT_SPACE_STORAGE_GB in infra/av30_constructs/__init__.py), which is the same for
  // all modules. The panel shows the live size from app-status and uses this only as the
  // "recommended for this module" hint next to it. It used to be rendered AS the volume,
  // which is how a 5 GB space came to be displayed as 100 GB.
  storageGB: number;
  estimatedMinutes: number;
  awsAdvantage: string;
  inputPath: string;
  outputPath: string;
  feedsModules: string[];
  errorHints: Record<string, string>;
  // Optional: for a module whose heavy compute runs OUTSIDE the SageMaker
  // workspace (e.g. M10's AlpaSim on a GPU EC2 host reached over SSM). When set,
  // the detail panel renders a callout with the steps + a cost warning + a link
  // to the runbook. The SageMaker instance for such a module is CPU (this
  // notebook only visualizes the results the external host produced).
  externalExecution?: {
    label: string;
    summary: string;
    steps: string[];
    costWarning: string;
    guideHref: string;
  };
}

export const PHASE_COLORS: Record<Phase, string> = {
  ingest: "#0972d3",
  curate: "#7d56c2",
  augment: "#d97706",
  train: "#037f0c",
  validate: "#b91c1c",
};

export const STATUS_COLORS: Record<ModuleStatus, string> = {
  completed: "#037f0c",
  "in-progress": "#d97706",
  locked: "#5f6b7a",
};

// Real AV 3.0 Blueprint Lab pipeline (NVIDIA Cosmos + AWS). Instance types match
// the notebook headers (notebooks/M*.ipynb) and the backend rate table. GPU
// modules (ml.g5/ml.g6/ml.p4d) get the SageMaker Distribution GPU image
// automatically when selected — the participant only picks the instance.
export const PIPELINE_MODULES: ModuleConfig[] = [
  {
    id: "m01-data-exploration",
    title: "Data Exploration",
    phase: "ingest",
    tool: "nuScenes devkit + S3",
    version: "1.1",
    status: "completed",
    license: "CC BY-NC-SA 4.0",
    sourceUrl: "https://www.nuscenes.org/",
    recommendedInstance: "ml.t3.medium",
    alternatives: ["ml.t3.large", "ml.t3.xlarge", "ml.m5.large"],
    storageGB: 20,
    estimatedMinutes: 15,
    awsAdvantage:
      "nuScenes-mini is pre-staged in a shared S3 bucket, so exploration starts instantly with no download — CPU-only, a few cents per hour.",
    inputPath: "s3://av30lab-shared-data/datasets/nuscenes-mini/",
    outputPath: "s3://av30lab-user-workspace/users/{userId}/m1/",
    feedsModules: ["m02-cosmos-reason"],
    errorHints: {
      CalledProcessError:
        "Bucket/prefix mismatch. SHARED_BUCKET and USER_BUCKET env vars are injected by the notebook-sync lifecycle config — restart the app if they are missing.",
      EmptyManifest:
        "nuScenes sample_data has no `channel` field. Join calibrated_sensor → sensor to resolve CAM_FRONT keyframes.",
    },
  },
  {
    id: "m02-cosmos-reason",
    title: "Cosmos Reason Captioning",
    phase: "curate",
    tool: "NVIDIA Cosmos Reason 1 (7B VLM)",
    version: "1.0",
    status: "in-progress",
    license: "NVIDIA Open Model License",
    sourceUrl: "https://github.com/nvidia-cosmos/cosmos-cookbook/tree/main/docs/recipes/post_training/reason1/av_video_caption_vqa",
    // Stage 3 — Cosmos Reason 1 (Qwen2.5-VL) needs ~96 GB VRAM.
    recommendedInstance: "ml.g5.12xlarge",
    // Ordered so the first fallback is a type every deploy region sells. ml.g6.* trails:
    // it is quota 0 in ap-northeast-2, where change_instance rejects it with a 400. g7e is
    // omitted entirely — not sold for Studio in ap-northeast-2, so it would be a dead end.
    // ml.g6.12xlarge (4× L4 24 GB) is the capacity fallback when g5 is unavailable
    // — same 96 GB total as g5.12xlarge, so it clears M2's gate identically.
    // ml.g7e.2xlarge reaches the same 96 GB on ONE card and is cheaper ($4.20 vs
    // $7.09); M2's gate is on TOTAL VRAM (with 10% tolerance), so it passes.
    alternatives: ["ml.g5.24xlarge", "ml.g5.48xlarge", "ml.p4d.24xlarge", "ml.g6.12xlarge", "ml.g6.24xlarge"],
    storageGB: 100,
    estimatedMinutes: 45,
    awsAdvantage:
      "ml.g5.12xlarge (4× A10G, 96 GB total VRAM) shards the 7B VLM across GPUs via device_map=\"auto\"; the SageMaker Distribution GPU image is selected automatically. M2 gates on TOTAL VRAM (96 GB, 10% tolerance), so any box reaching that total passes — 4× 24 GB, or a single 96 GB card such as ml.g7e.2xlarge (~$4.20/hr, cheaper than the default).",
    inputPath: "s3://av30lab-user-workspace/users/{userId}/m1/",
    outputPath: "s3://av30lab-user-workspace/users/{userId}/m2/",
    feedsModules: ["m03-cosmos-curator", "m04-opensearch"],
    errorHints: {
      "No GPU detected":
        "You are on a CPU instance. Open Instance Options and switch to ml.g5.12xlarge. The GPU image is applied automatically — reopen the workspace after it restarts.",
      "EC2InsufficientCapacity":
        "ml.g5.12xlarge capacity is tight in the region. Pick ml.g5.24xlarge or ml.g5.48xlarge from Instance Options — M2 gates on TOTAL VRAM, so any of them behaves identically. (ml.g6.12xlarge also matches on paper but has quota 0 in ap-northeast-2, where the dashboard will refuse it.)",
    },
  },
  {
    id: "m03-cosmos-curator",
    title: "Cosmos Curator",
    phase: "curate",
    tool: "NVIDIA NeMo Curator",
    version: "0.8",
    status: "locked",
    license: "Apache-2.0",
    // NVIDIA/NeMo-Curator silently redirects to a new org + name; pin the real one.
    sourceUrl: "https://github.com/NVIDIA-NeMo/Curator",
    recommendedInstance: "ml.g5.12xlarge",
    alternatives: ["ml.g5.24xlarge", "ml.g5.48xlarge", "ml.p4d.24xlarge", "ml.g6.12xlarge", "ml.g6.24xlarge"],
    storageGB: 100,
    estimatedMinutes: 40,
    awsAdvantage:
      "GPU-accelerated semantic dedup and quality filtering process the captioned clips in minutes rather than hours of CPU work.",
    inputPath: "s3://av30lab-user-workspace/users/{userId}/m1/ + users/{userId}/m2/",
    outputPath: "s3://av30lab-user-workspace/users/{userId}/m3/",
    feedsModules: [
      "m05-cosmos-transfer",
      "m06-cosmos-predict",
      "m09-alpamayo-vla",
      "m12-hyperpod",
    ],
    errorHints: {
      OutOfMemory:
        "Reduce the curation batch size, or step up to ml.g5.24xlarge / ml.p4d.24xlarge.",
    },
  },
  {
    id: "m04-opensearch",
    title: "OpenSearch Semantic Search",
    phase: "curate",
    tool: "Amazon OpenSearch Serverless",
    version: "2.x",
    status: "locked",
    license: "Apache-2.0",
    sourceUrl: "https://opensearch.org/",
    // Stage 4 — search & indexing runs client-side on CPU; the vector store is
    // OpenSearch Serverless (separate managed service).
    recommendedInstance: "ml.t3.medium",
    alternatives: ["ml.t3.large", "ml.m5.large", "ml.m5.xlarge"],
    storageGB: 50,
    estimatedMinutes: 20,
    awsAdvantage:
      "OpenSearch Serverless provides managed k-NN vector search — the AWS-native replacement for Cosmos Dataset Search; the notebook itself only needs CPU.",
    inputPath: "s3://av30lab-user-workspace/users/{userId}/m2/",
    outputPath: "s3://av30lab-user-workspace/users/{userId}/m4/",
    feedsModules: [],
    errorHints: {
      AccessDenied:
        "The execution role needs aoss (OpenSearch Serverless) data-access permissions on the collection.",
    },
  },
  {
    id: "m05-cosmos-transfer",
    title: "Cosmos Transfer — Weather Aug",
    phase: "augment",
    tool: "NVIDIA Cosmos Transfer 2.5",
    version: "2.5",
    status: "locked",
    license: "NVIDIA Open Model License",
    sourceUrl: "https://github.com/nvidia-cosmos/cosmos-transfer2.5",
    // Stage 5 — diffusion world model; shards across a multi-GPU box. g6.24xlarge
    // (4× L4, 96 GB) is the verified workshop default at 480p; p4d/p5 give 720p.
    // ml.g5.12xlarge, NOT ml.g6.24xlarge. The two are GEOMETRICALLY IDENTICAL to every
    // gate in this module — `aws ec2 describe-instance-types` reports 4 GPUs of 22,888 MiB
    // for both (A10G vs L4 is the only difference) — and the pre-flight branches only on
    // per-GPU VRAM and GPU count. So the run, the resolution, the guardrail setting and the
    // torchrun --nproc_per_node are byte-for-byte the same.
    //
    // g5.12xlarge is strictly better on everything else, in BOTH regions:
    //   price   us-west-2 $7.090 vs $8.344 | ap-northeast-2 $8.718 vs $10.260
    //   quota   us-west-2 5 vs 2           | ap-northeast-2 5 vs 0  <-- g6 cannot run there
    // Recommending a quota-0 type is not a soft problem: nothing in the request path checks
    // quota, so the change is accepted, the app never starts, and a failed instance change
    // leaves the space pinned to an unlaunchable type.
    //
    // WHAT IS ACTUALLY MEASURED — an earlier version of this comment had it backwards and
    // called the "g6.24xlarge verified" label a misattribution. It was not. There are two
    // independent bodies of evidence, on different axes:
    //
    //   4 GPUs: examples/notebooks-with-outputs.tar.gz holds captured Run-All output for
    //           M2, M5, M6 and M9 on 4x NVIDIA L4, 88.1 GB aggregate -- i.e. exactly the
    //           ml.g6.24xlarge geometry AND its silicon. M9 recorded minADE 0.3805,
    //           "Status: PASS", device_map=balanced-expert. The inference cells are
    //           unchanged since (M9 cell 3, the deciding gate, is byte-identical).
    //   A10G:   docs/en/ALPAMAYO_M9.md:181-187 records M9 passing on 8x A10G
    //           (ml.g5.48xlarge), minADE 0.378 / 0.3779.
    //
    // So (4 GPUs) and (A10G) are each measured; the (4x A10G) PAIR is not itself captured.
    // Nothing in any heavy module branches on GPU name, compute capability or driver -- the
    // gates read per-GPU VRAM and GPU count only, and props.name appears solely inside
    // print f-strings -- so there is no mechanism by which this pair can diverge from the
    // captured 4x L4 runs. The reason to prefer g5.12xlarge is quota and price, NOT a
    // better verification story.
    //
    // GENUINELY UNVERIFIED: M8 has no end-to-end run on ANY hardware. Its cell 2 carries a
    // targeted VRAM bench on 4x L4 (11.28 GiB peak / 10.76 GiB spare at native 1600x900),
    // but the train / A-B generate / adapter-save cells have never been watched to finish.
    recommendedInstance: "ml.g5.12xlarge",
    // Ordered so the first thing offered on a capacity error is a type the deploy region
    // actually sells. g7e is NOT listed: ap-northeast-2 does not sell it for Studio at all,
    // so it would be a dead end there (and it remains unrun in this lab anyway).
    // ml.g5.24xlarge / ml.g5.48xlarge are 24 GB/GPU like the default -- capacity fallbacks,
    // NOT upgrades; g5.24xlarge is the same 4-GPU tier at +44% cost. ml.p4d.24xlarge is the
    // only genuine tier-up here (40 GB/GPU), and it has quota 2 in both regions.
    alternatives: ["ml.g5.24xlarge", "ml.g5.48xlarge", "ml.p4d.24xlarge"],
    storageGB: 200,
    estimatedMinutes: 60,
    awsAdvantage:
      "ml.g5.12xlarge (4× A10G, 22.4 GB/GPU, $7.09/hr in us-west-2, $8.72 in ap-northeast-2) generates weather-augmented clips by sharding across GPUs; EBS-backed scratch keeps intermediate frames off S3. The notebook branches on PER-GPU VRAM: under 38 GB it runs 480p with guardrails OFF (16 of 57 frames). For full 720p with guardrails ON you need ≥38 GB per GPU, and in both regions that means ml.p4d.24xlarge (8× A100 40 GB, ~$25.25/hr). No g5 or g6 size reaches that tier: a bigger size adds GPUs, not per-GPU VRAM. ml.g7e.2xlarge would clear it on ONE 96 GB card for ~$4.20/hr — cheaper than the default — but ap-northeast-2 does not sell it for Studio, and this lab has never run it.",
    inputPath: "s3://av30lab-user-workspace/users/{userId}/m1/",
    outputPath: "s3://av30lab-user-workspace/users/{userId}/m5/",
    feedsModules: [],
    errorHints: {
      CUDAOutOfMemory:
        "On 24 GB cards the notebook runs 480p sharded across all GPUs — first close any OTHER open notebooks (their kernels hold GPU memory), then re-run. For full 720p with guardrails ON you need ≥38 GB per GPU: move to ml.p4d.24xlarge (40 GB/GPU) — the option available in every region this lab deploys to.",
    },
  },
  {
    id: "m06-cosmos-predict",
    title: "Cosmos Predict — Scenario Gen",
    phase: "augment",
    tool: "NVIDIA Cosmos Predict 2.5",
    version: "2.5",
    status: "locked",
    license: "NVIDIA Open Model License",
    sourceUrl: "https://github.com/nvidia-cosmos/cosmos-predict2.5",
    // ml.g5.12xlarge, NOT ml.g6.24xlarge. The two are GEOMETRICALLY IDENTICAL to every
    // gate in this module — `aws ec2 describe-instance-types` reports 4 GPUs of 22,888 MiB
    // for both (A10G vs L4 is the only difference) — and the pre-flight branches only on
    // per-GPU VRAM and GPU count. So the run, the resolution, the guardrail setting and the
    // torchrun --nproc_per_node are byte-for-byte the same.
    //
    // g5.12xlarge is strictly better on everything else, in BOTH regions:
    //   price   us-west-2 $7.090 vs $8.344 | ap-northeast-2 $8.718 vs $10.260
    //   quota   us-west-2 5 vs 2           | ap-northeast-2 5 vs 0  <-- g6 cannot run there
    // Recommending a quota-0 type is not a soft problem: nothing in the request path checks
    // quota, so the change is accepted, the app never starts, and a failed instance change
    // leaves the space pinned to an unlaunchable type.
    //
    // WHAT IS ACTUALLY MEASURED — an earlier version of this comment had it backwards and
    // called the "g6.24xlarge verified" label a misattribution. It was not. There are two
    // independent bodies of evidence, on different axes:
    //
    //   4 GPUs: examples/notebooks-with-outputs.tar.gz holds captured Run-All output for
    //           M2, M5, M6 and M9 on 4x NVIDIA L4, 88.1 GB aggregate -- i.e. exactly the
    //           ml.g6.24xlarge geometry AND its silicon. M9 recorded minADE 0.3805,
    //           "Status: PASS", device_map=balanced-expert. The inference cells are
    //           unchanged since (M9 cell 3, the deciding gate, is byte-identical).
    //   A10G:   docs/en/ALPAMAYO_M9.md:181-187 records M9 passing on 8x A10G
    //           (ml.g5.48xlarge), minADE 0.378 / 0.3779.
    //
    // So (4 GPUs) and (A10G) are each measured; the (4x A10G) PAIR is not itself captured.
    // Nothing in any heavy module branches on GPU name, compute capability or driver -- the
    // gates read per-GPU VRAM and GPU count only, and props.name appears solely inside
    // print f-strings -- so there is no mechanism by which this pair can diverge from the
    // captured 4x L4 runs. The reason to prefer g5.12xlarge is quota and price, NOT a
    // better verification story.
    //
    // GENUINELY UNVERIFIED: M8 has no end-to-end run on ANY hardware. Its cell 2 carries a
    // targeted VRAM bench on 4x L4 (11.28 GiB peak / 10.76 GiB spare at native 1600x900),
    // but the train / A-B generate / adapter-save cells have never been watched to finish.
    recommendedInstance: "ml.g5.12xlarge",
    // Ordered so the first thing offered on a capacity error is a type the deploy region
    // actually sells. g7e is NOT listed: ap-northeast-2 does not sell it for Studio at all,
    // so it would be a dead end there (and it remains unrun in this lab anyway).
    // ml.g5.24xlarge / ml.g5.48xlarge are 24 GB/GPU like the default -- capacity fallbacks,
    // NOT upgrades; g5.24xlarge is the same 4-GPU tier at +44% cost. ml.p4d.24xlarge is the
    // only genuine tier-up here (40 GB/GPU), and it has quota 2 in both regions.
    alternatives: ["ml.g5.24xlarge", "ml.g5.48xlarge", "ml.p4d.24xlarge"],
    storageGB: 200,
    estimatedMinutes: 60,
    awsAdvantage:
      "Synthetic traffic scenarios extend the dataset beyond what was collected — an AWS-native alternative to physical re-drives. ml.g5.12xlarge (4× A10G, 22.4 GB/GPU, $7.09/hr in us-west-2, $8.72 in ap-northeast-2) runs it at 480×832 with guardrails OFF (45 frames), because the notebook branches on PER-GPU VRAM and 24 GB is under its 38 GB threshold. For native resolution with guardrails ON, ml.p4d.24xlarge (8× A100 40 GB, ~$25.25/hr) is the route in both regions; no g5 or g6 size can reach that tier. ml.g7e.2xlarge would clear it on ONE 96 GB card for ~$4.20/hr, but ap-northeast-2 does not sell it for Studio and this lab has never run it.",
    // Required input is M1. M6 REUSES m5/source/nuscenes_cam_front.mp4 when M5 has
    // already run, and rebuilds the clip from M1 otherwise (M6 cell 4) — so M5 is an
    // optimisation, not a prerequisite. Was listed as m3/, which no cell reads.
    inputPath: "s3://av30lab-user-workspace/users/{userId}/m1/",
    outputPath: "s3://av30lab-user-workspace/users/{userId}/m6/",
    feedsModules: [],
    errorHints: {
      CUDAOutOfMemory:
        "On 24 GB cards the notebook runs 480×832 sharded across all GPUs — first close any OTHER open notebooks (their kernels hold GPU memory), then re-run. For native resolution, step up to ml.p4d.24xlarge (40 GB/GPU) — the ≥38 GB option available in every region this lab deploys to.",
    },
  },
  {
    id: "m07-nerfstudio",
    title: "Nerfstudio 3D Reconstruction",
    phase: "augment",
    tool: "Nerfstudio",
    version: "1.1",
    status: "locked",
    license: "Apache-2.0",
    sourceUrl: "https://github.com/nerfstudio-project/nerfstudio",
    // Stage 6 — neural reconstruction from CAM_FRONT frames; single-GPU is fine.
    recommendedInstance: "ml.g5.xlarge",
    alternatives: ["ml.g5.2xlarge", "ml.g5.4xlarge", "ml.g6.xlarge", "ml.g6.2xlarge", "ml.g6.4xlarge"],
    storageGB: 100,
    estimatedMinutes: 90,
    awsAdvantage:
      "A single A10G reconstructs neural radiance fields from nuScenes CAM_FRONT images — an independent branch reading the dataset directly.",
    inputPath: "s3://av30lab-shared-data/datasets/nuscenes-mini/ (CAM_FRONT)",
    outputPath: "s3://av30lab-user-workspace/users/{userId}/m7/",
    feedsModules: [],
    errorHints: {
      "No GPU detected":
        "Nerfstudio needs a GPU — select ml.g5.xlarge in Instance Options.",
    },
  },
  {
    id: "m08-cosmos-sft",
    title: "Cosmos Reason LoRA SFT",
    phase: "train",
    tool: "NVIDIA Cosmos Reason 1 (7B VLM) + PEFT/LoRA",
    version: "1.0",
    status: "locked",
    license: "NVIDIA Open Model License",
    sourceUrl: "https://github.com/nvidia-cosmos/cosmos-cookbook/tree/main/docs/recipes/post_training/reason1/av_video_caption_vqa",
    // Stage 7 — model TRAINING. Measured on ml.g6.24xlarge (4x L4 22.04 GiB):
    // weights 15.61 GiB sharded by device_map="auto", worst-GPU peak 11.28 GiB at
    // NATIVE 1600x900 with 10.76 GiB headroom. A single 24 GB card OOMs (weights
    // alone take 15.6 of 22.04 GiB), so this needs >=2 GPUs or one card >=40 GB.
    // ml.g5.12xlarge, NOT ml.g6.24xlarge. The two are GEOMETRICALLY IDENTICAL to every
    // gate in this module — `aws ec2 describe-instance-types` reports 4 GPUs of 22,888 MiB
    // for both (A10G vs L4 is the only difference) — and the pre-flight branches only on
    // per-GPU VRAM and GPU count. So the run, the resolution, the guardrail setting and the
    // torchrun --nproc_per_node are byte-for-byte the same.
    //
    // g5.12xlarge is strictly better on everything else, in BOTH regions:
    //   price   us-west-2 $7.090 vs $8.344 | ap-northeast-2 $8.718 vs $10.260
    //   quota   us-west-2 5 vs 2           | ap-northeast-2 5 vs 0  <-- g6 cannot run there
    // Recommending a quota-0 type is not a soft problem: nothing in the request path checks
    // quota, so the change is accepted, the app never starts, and a failed instance change
    // leaves the space pinned to an unlaunchable type.
    //
    // WHAT IS ACTUALLY MEASURED — an earlier version of this comment had it backwards and
    // called the "g6.24xlarge verified" label a misattribution. It was not. There are two
    // independent bodies of evidence, on different axes:
    //
    //   4 GPUs: examples/notebooks-with-outputs.tar.gz holds captured Run-All output for
    //           M2, M5, M6 and M9 on 4x NVIDIA L4, 88.1 GB aggregate -- i.e. exactly the
    //           ml.g6.24xlarge geometry AND its silicon. M9 recorded minADE 0.3805,
    //           "Status: PASS", device_map=balanced-expert. The inference cells are
    //           unchanged since (M9 cell 3, the deciding gate, is byte-identical).
    //   A10G:   docs/en/ALPAMAYO_M9.md:181-187 records M9 passing on 8x A10G
    //           (ml.g5.48xlarge), minADE 0.378 / 0.3779.
    //
    // So (4 GPUs) and (A10G) are each measured; the (4x A10G) PAIR is not itself captured.
    // Nothing in any heavy module branches on GPU name, compute capability or driver -- the
    // gates read per-GPU VRAM and GPU count only, and props.name appears solely inside
    // print f-strings -- so there is no mechanism by which this pair can diverge from the
    // captured 4x L4 runs. The reason to prefer g5.12xlarge is quota and price, NOT a
    // better verification story.
    //
    // GENUINELY UNVERIFIED: M8 has no end-to-end run on ANY hardware. Its cell 2 carries a
    // targeted VRAM bench on 4x L4 (11.28 GiB peak / 10.76 GiB spare at native 1600x900),
    // but the train / A-B generate / adapter-save cells have never been watched to finish.
    recommendedInstance: "ml.g5.12xlarge",
    // g7e clears it on ONE 96 GB card and costs half the default; p4d/p5 also fit.
    // g5/g6 entries are the same 24 GB tier — capacity fallbacks, not upgrades.
    alternatives: ["ml.g5.24xlarge", "ml.g5.48xlarge", "ml.p4d.24xlarge"],
    storageGB: 200,
    estimatedMinutes: 45,
    awsAdvantage:
      "LoRA fine-tunes the 8.33B Cosmos Reason VLM by training 40.4M adapter params (0.48%) while the base weights and the vision tower stay frozen — so an ml.g5.12xlarge ($7.09/hr in us-west-2, $8.72 in ap-northeast-2) trains at NATIVE nuScenes resolution. The VRAM figures were measured on 4× L4 — the same 22,888 MiB geometry, so the same tier — at 11.28 GiB worst-GPU peak with 10.76 GiB spare. A full fine-tune of the same model would need ~123 GiB of weight+gradient+optimizer state, more than this box has in total. Targets are nuScenes HUMAN annotation (scene descriptions + category labels), never M2's own captions, so the loss is not self-referential.",
    inputPath: "s3://av30lab-user-workspace/users/{userId}/m1/",
    outputPath: "s3://av30lab-user-workspace/users/{userId}/m8/",
    feedsModules: [],
    errorHints: {
      CUDAOutOfMemory:
        "Close any OTHER open notebooks first — their kernels hold GPU memory and the pre-flight cell halts on it. This module needs >=2 GPUs on 24 GB cards (the 15.61 GiB of weights must shard) or one card >=40 GB — ml.p4d.24xlarge (40 GB/GPU) is the option available in every region this lab deploys to.",
      "M1 output not found":
        "Run M1 (Data Exploration) first. M8 trains on the frames M1 selected — it reads users/{userId}/m1/manifest.json to know which ones.",
    },
  },
  {
    id: "m09-alpamayo-vla",
    title: "Alpamayo VLA Inference",
    phase: "train",
    tool: "NVIDIA Alpamayo 1.5 (VLA)",
    version: "1.5",
    status: "locked",
    license: "NVIDIA Open Model License",
    sourceUrl: "https://github.com/NVlabs/alpamayo1.5",
    // Stage 7 — Vision-Language-Action policy. Balanced-expert placement shards
    // the VLM across GPUs and pins the action stack to cuda:0, so 4× L4 fits.
    // ml.g5.12xlarge, NOT ml.g6.24xlarge. The two are GEOMETRICALLY IDENTICAL to every
    // gate in this module — `aws ec2 describe-instance-types` reports 4 GPUs of 22,888 MiB
    // for both (A10G vs L4 is the only difference) — and the pre-flight branches only on
    // per-GPU VRAM and GPU count. So the run, the resolution, the guardrail setting and the
    // torchrun --nproc_per_node are byte-for-byte the same.
    //
    // g5.12xlarge is strictly better on everything else, in BOTH regions:
    //   price   us-west-2 $7.090 vs $8.344 | ap-northeast-2 $8.718 vs $10.260
    //   quota   us-west-2 5 vs 2           | ap-northeast-2 5 vs 0  <-- g6 cannot run there
    // Recommending a quota-0 type is not a soft problem: nothing in the request path checks
    // quota, so the change is accepted, the app never starts, and a failed instance change
    // leaves the space pinned to an unlaunchable type.
    //
    // WHAT IS ACTUALLY MEASURED — an earlier version of this comment had it backwards and
    // called the "g6.24xlarge verified" label a misattribution. It was not. There are two
    // independent bodies of evidence, on different axes:
    //
    //   4 GPUs: examples/notebooks-with-outputs.tar.gz holds captured Run-All output for
    //           M2, M5, M6 and M9 on 4x NVIDIA L4, 88.1 GB aggregate -- i.e. exactly the
    //           ml.g6.24xlarge geometry AND its silicon. M9 recorded minADE 0.3805,
    //           "Status: PASS", device_map=balanced-expert. The inference cells are
    //           unchanged since (M9 cell 3, the deciding gate, is byte-identical).
    //   A10G:   docs/en/ALPAMAYO_M9.md:181-187 records M9 passing on 8x A10G
    //           (ml.g5.48xlarge), minADE 0.378 / 0.3779.
    //
    // So (4 GPUs) and (A10G) are each measured; the (4x A10G) PAIR is not itself captured.
    // Nothing in any heavy module branches on GPU name, compute capability or driver -- the
    // gates read per-GPU VRAM and GPU count only, and props.name appears solely inside
    // print f-strings -- so there is no mechanism by which this pair can diverge from the
    // captured 4x L4 runs. The reason to prefer g5.12xlarge is quota and price, NOT a
    // better verification story.
    //
    // GENUINELY UNVERIFIED: M8 has no end-to-end run on ANY hardware. Its cell 2 carries a
    // targeted VRAM bench on 4x L4 (11.28 GiB peak / 10.76 GiB spare at native 1600x900),
    // but the train / A-B generate / adapter-save cells have never been watched to finish.
    recommendedInstance: "ml.g5.12xlarge",
    // Ordered by capability-per-dollar. g7e (96 GB/card) clears M9's 40 GB
    // single-device threshold and is CHEAPER than the default, so it leads;
    // p4d/p5 also clear it but cost more. The g5/g6 entries are 24 GB/GPU like
    // the default — capacity fallbacks, NOT upgrades (+22% cost, same tier).
    alternatives: ["ml.g5.48xlarge", "ml.g5.24xlarge", "ml.p4d.24xlarge"],
    storageGB: 200,
    estimatedMinutes: 60,
    awsAdvantage:
      "ml.g5.12xlarge (4× A10G, 22.4 GB/GPU, $7.09/hr in us-west-2, $8.72 in ap-northeast-2) runs the 10B VLA policy via balanced-expert placement — the VLM shards across GPUs while the action stack is pinned to cuda:0; results feed closed-loop simulation. The passing reference run was on g5/A10G hardware (docs/en/ALPAMAYO_M9.md: minADE 0.3779 m, Status: PASS) — at 8 GPUs (g5.48xlarge), so this 4-GPU size takes the same branch but has not itself been captured. Any single GPU ≥40 GB takes the simpler single-device path instead: ml.g7e.2xlarge (1× RTX PRO 6000, 96 GB, ~$4.20/hr) is the cheapest such box — half the default's price, though not yet run in this lab and needing its own quota — and ml.p4d.24xlarge (~$25.25/hr) also qualifies. No g5/g6 size has a 40 GB card.",
    inputPath: "s3://av30lab-shared-data/hf-cache/alpamayo-demo/",
    outputPath: "s3://av30lab-user-workspace/users/{userId}/m9/",
    feedsModules: ["m10-alpasim"],
    errorHints: {
      CUDAOutOfMemory:
        "The VLA policy is large — first close any OTHER open notebooks (their kernels hold GPU memory), then re-run. On 24 GB cards it must shard, so use a multi-GPU box — ml.g5.48xlarge (8× A10G) has the most recorded evidence for this path — and not a single-GPU one. Any card ≥40 GB instead takes the simpler single-device path: ml.p4d.24xlarge is 40 GB/GPU and is available in every region this lab deploys to.",
    },
  },
  {
    id: "m10-alpasim",
    title: "AlpaSim Closed-Loop Eval",
    phase: "validate",
    tool: "NVIDIA AlpaSim",
    version: "0.96.0",
    status: "locked",
    license: "Apache-2.0 (sim) · Alpamayo weights non-commercial",
    sourceUrl: "https://github.com/NVlabs/alpasim",
    // Stage 8 — closed-loop evaluation. This SageMaker notebook is CPU: it only
    // downloads + visualizes the genuine AlpaSim results. The real simulation
    // (Docker-Compose gRPC microservices, >=40 GB GPU) runs on a GPU EC2 host
    // reached over SSM — see externalExecution below and the participant runbook.
    recommendedInstance: "ml.t3.medium",
    alternatives: ["ml.t3.large", "ml.m5.large"],
    storageGB: 20,
    estimatedMinutes: 10,
    awsAdvantage:
      "Closed-loop, software-in-the-loop testing scores the policy before any road test — the final validation gate.",
    inputPath: "s3://av30lab-user-workspace/users/{userId}/m9/",
    outputPath: "s3://av30lab-user-workspace/users/{userId}/m10/",
    feedsModules: [],
    errorHints: {
      "reference eval not found":
        "Run AlpaSim on your GPU host first (see the SSM runbook), or ask the admin to stage the shared reference run.",
    },
    externalExecution: {
      label: "Runs on a GPU EC2 host (over SSM), not in this workspace",
      summary:
        "AlpaSim is a Docker-Compose gRPC microservice fleet needing a ≥40 GB GPU, which a SageMaker notebook can't host. Your admin pre-provisions a GPU host for you; you SSH in via SSM, run the sim, then visualize the results here (CPU). This path needs your OWN Hugging Face token (the NuRec scene is gated and not in the shared cache).",
      steps: [
        "Prepare a Hugging Face token and accept the nvidia/PhysicalAI-Autonomous-Vehicles-NuRec dataset license (see Prerequisites).",
        "Get your AWS access key + GPU instance ID from the workshop admin.",
        // {region} is substituted at render time from config.json (see
        // ModuleDetailPanel). It was hardcoded "us-west-2", which in any other
        // deployment region told participants to target the WRONG region: either the
        // instance is not found, or — if that region happens to have a GPU host up —
        // they attach to a box that is not theirs.
        "aws ssm start-session --target <instance-id> --region {region}",
        "In the session, export PARTICIPANT_ID / M10_OUTPUT_PREFIX / OUTPUT_BUCKET / HF_TOKEN (one per line), then run alpasim_ec2_setup.sh (first build tens of minutes to ~2–3 h).",
        "When it prints DONE, tell the admin so they terminate the host.",
        "Back here: open this notebook (CPU) and Run All — it auto-loads your results.",
      ],
      costWarning:
        "⚠️ The GPU host bills ~$10.5/hr while running. You cannot terminate it yourself — notify the admin the moment you are done.",
      guideHref: "https://github.com/NVlabs/alpasim",
    },
  },
  {
    id: "m11-orchestration",
    title: "Pipeline Automation",
    phase: "validate",
    tool: "SageMaker Pipelines",
    version: "2.x",
    status: "locked",
    license: "AWS Service",
    sourceUrl: "https://aws.amazon.com/sagemaker/pipelines/",
    // Extension — orchestrates M1→M2→M3→M5 as one SageMaker Pipeline. Notebook + all 3
    // steps run on CPU (steps are pure Python over M1 metadata); the pipeline
    // pattern is identical to a GPU production run. See docs/en/PIPELINE_M11.md.
    recommendedInstance: "ml.t3.medium",
    alternatives: ["ml.t3.large", "ml.m5.large"],
    storageGB: 20,
    estimatedMinutes: 15,
    awsAdvantage:
      "SageMaker Pipelines turns the manual M1→M2→M3→M5 notebook steps into one repeatable, parameterized DAG — authoring runs on CPU, steps auto start/stop.",
    inputPath: "s3://av30lab-user-workspace/users/{userId}/m1/",
    outputPath: "s3://av30lab-user-workspace/users/{userId}/m11/",
    feedsModules: [],
    errorHints: {
      "ModuleNotFoundError sagemaker":
        "Run cell-1 first — it pins SageMaker SDK v2 and auto-restarts the kernel; then Run All again.",
      "Step failed / 0 captions":
        "Run M1 first so users/<id>/m1/selected_scenes.json exists — Step 1 captions those scenes.",
      "Unsupported image scope":
        "sklearn has no 'processing' image scope — call image_uris.retrieve without image_scope (already fixed in the current notebook; re-sync from notebook-templates if you still see this).",
    },
  },
  {
    id: "m12-hyperpod",
    title: "HyperPod Distributed Training",
    phase: "train",
    tool: "SageMaker HyperPod",
    version: "1.0",
    status: "locked",
    license: "AWS Service",
    sourceUrl: "https://aws.amazon.com/sagemaker/hyperpod/",
    // Extension — the notebook is CPU: it submits a real 2-node torch.distributed
    // DDP training job (ml.m5.xlarge x2, gloo) on M3's captions and visualizes the
    // measured metrics. True HyperPod (p4d cluster, Slurm/EKS/FSx/EFA) is separate
    // infrastructure a notebook can't provision — covered conceptually. See
    // docs/en/HYPERPOD_M12.md.
    recommendedInstance: "ml.t3.medium",
    alternatives: ["ml.t3.large", "ml.m5.large"],
    storageGB: 20,
    estimatedMinutes: 20,
    awsAdvantage:
      "HyperPod manages resilient multi-node clusters with automatic node replacement — training continues through hardware failures. This module demonstrates the distributed-training pattern it scales.",
    inputPath: "s3://av30lab-user-workspace/users/{userId}/m3/",
    outputPath: "s3://av30lab-user-workspace/users/{userId}/m12/",
    feedsModules: [],
    errorHints: {
      ResourceLimitExceeded:
        "The training job (ml.m5.xlarge x2) needs SageMaker training quota. CPU training quota is usually available; if not, ask the admin. GPU (g5) is optional — see docs/en/HYPERPOD_M12.md.",
    },
  },
];
