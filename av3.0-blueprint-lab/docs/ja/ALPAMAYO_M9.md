# Alpamayo 1.5 (M9) — SMD イメージ上での実際の VLA 推論

**ステータス:** M9 (Alpamayo 1.5、Vision-Language-Action の軌跡予測) は
SageMaker Distribution (SMD) GPU イメージ上で **エンドツーエンドで検証済み** です
— `PhysicalAI-Autonomous-Vehicles` のデモクリップに対する実際の推論で、
Chain-of-Causation の説明と予測された自車軌跡を生成します (検証済みクリップで
**minADE 0.375 m**)。M5/M6 と同様に、オフライン S3 チェックポイントキャッシュと
事前保存したデモクリップを介して、**参加者の HF トークンなし** で動作します。

## このモジュールが抱えていた中核的な問題

出荷されたノートブックは、**存在しない** **ハルシネーションによる `alpamayo` パッケージ**
(`from alpamayo.model import AlpamayoForConditionalGeneration`、
`alpamayo.inference.AlpamayoInferencePipeline`、`alpamayo.utils.load_frames_from_video`、
`pipeline.predict_trajectory` / `predict_trajectory_multicam` / `visual_qa`) を
インポートしていました — M5/M6 の偽の `cosmos1` と同じ種類のバグです。
`pip install alpamayo` は存在しません。実際のワークフローは公式リポジトリ
[`NVlabs/alpamayo1.5`](https://github.com/NVlabs/alpamayo1.5)、パッケージ
`alpamayo1_5` (アンダースコア) です。

M5/M6 とは異なり、Alpamayo は **別のスタック** です: Python **3.12** (Cosmos は
3.10 に固定)、torch 2.8、transformers 4.57.1、`physical-ai-av==0.2.0`、**transformer-engine
なし**、そして **flash-attn を除外** (そのソースビルドは SMD イメージ上で失敗します)。
そのため、独自の venv と独自のセットアップパスを持ちます。

## 実際の推論フロー (検証済み)

```python
import torch, numpy as np
from alpamayo1_5 import helper
from alpamayo1_5.load_physical_aiavdataset import load_physical_aiavdataset  # admin only
from alpamayo1_5.models.alpamayo1_5 import Alpamayo1_5

data = load_physical_aiavdataset("030c760c-...", t0_us=5_100_000)   # gated dataset, online
messages = helper.create_message(frames=data["image_frames"].flatten(0, 1),
                                 camera_indices=data["camera_indices"])
model = Alpamayo1_5.from_pretrained("nvidia/Alpamayo-1.5-10B",
                                    dtype=torch.bfloat16,
                                    attn_implementation="sdpa").to("cuda")   # sdpa REQUIRED
processor = helper.get_processor(model.tokenizer)
inputs = processor.apply_chat_template(messages, tokenize=True,
    add_generation_prompt=False, continue_final_message=True,
    return_dict=True, return_tensors="pt")
mi = helper.to_device({"tokenized_data": inputs,
                       "ego_history_xyz": data["ego_history_xyz"],
                       "ego_history_rot": data["ego_history_rot"]}, "cuda")
pred_xyz, _, extra = model.sample_trajectories_from_data_with_vlm_rollout(
    data=mi, top_p=0.98, temperature=0.6, num_traj_samples=1,
    max_generation_length=256, return_extra=True)
# extra["cot"][0] = Chain-of-Causation reasoning; pred_xyz = trajectory;
# minADE vs data["ego_future_xyz"].
```

`attn_implementation="sdpa"` は **必須** です: リポジトリのデフォルトは
`flash_attention_2` ですが、flash-attn がインストールされていないため
`ImportError` になります。

## 決定的な 2 つのオフラインに関する知見

M9 は M5/M6 と同様にトークンなしで動作する必要がありますが、2 つの部分は異なる挙動をします:

1. **モデルはオフラインでロードされる — hf-cache を使う (M5/M6 と同じ)。** `HF_TOKEN`
   を未設定にし、`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` にすると、
   `Alpamayo1_5.from_pretrained(...)` + `helper.get_processor` は S3 から復元された
   HF キャッシュから **トークンなし、ネットワークなし** でロードされます — これには、
   `from_pretrained` が透過的に取得する *隠れた* VLM バックボーン
   **`nvidia/Cosmos-Reason2-8B`** (Alpamayo の Qwen3-VL ベース) も含まれます。
   したがって、共有の `hf-cache/hub/` ツリーには `models--nvidia--Alpamayo-1.5-10B`
   **と** `models--nvidia--Cosmos-Reason2-8B` の **両方** が含まれている必要があります。

   > これが、フラットな `model-cache/alpamayo-1.5/` コピー (生の重みのみ) が
   > ランタイムで **使用されない** 理由です — Reason2 バックボーンが欠けているためです。
   > `cache_models.sh` はもうそれをダウンロードしません。

2. **データはオフラインでロード *できない* — 代わりにデモクリップを事前保存する。**
   `load_physical_aiavdataset` は `PhysicalAIAVDatasetInterface` を構築しますが、その
   `__init__` はゲート付き `PhysicalAI-Autonomous-Vehicles` データセット
   (`physical_ai_av/utils/hf_interface.py`) に対して無条件に `self.api.list_repo_refs()`
   を呼び出します。これは `HF_HUB_OFFLINE=1` を無視し、次のエラーを出します:
   `OfflineModeIsEnabled: Cannot reach .../datasets/nvidia/PhysicalAI-Autonomous-Vehicles/refs`。
   そのため **管理者** はオンラインで `load_physical_aiavdataset` を一度実行し、結果の
   `data` dict (~100 MB、大部分は 4 カメラの画像フレーム) を S3 に `torch.save` します。
   **参加者** のノートブックはその `.pt` を `torch.load` するだけで、
   **`physical_ai_av` を一切インポートしません** — トークンゼロ、ネットワークゼロです。

## `scripts/setup_cosmos_env.sh alpamayo`

Cosmos のセットアップスクリプトに `alpamayo` モード (`bash scripts/setup_cosmos_env.sh
alpamayo`) が追加されました。共有のプリアンブル (バケット解決 + `hf-cache/hub/` を
`$HF_HOME` へ復元) を再利用し、専用の `prepare_alpamayo()` を追加します:

- `NVlabs/alpamayo1.5` をクローン (Cosmos リポジトリと同様に LFS フィルターは無効);
- `uv venv a1_5 --python 3.12` の後、
  `VIRTUAL_ENV=$venv uv sync --active --no-install-package flash-attn`;
- transformer-engine の `.so` シンボリックリンク / `CUDA_HOME` / `ldconfig` の手順を
  **スキップ** (Alpamayo に TE はなく、torch 2.8 にバンドルされた CUDA が問題なくロードされます);
- `alpamayo_env.sh` を書き出す。これは `a1_5` venv をアクティベートし、source された
  cosmos env から漏れた **`CUDA_HOME`/`LD_LIBRARY_PATH` をすべてクリア** し、
  `$HF_HOME/hub/models--nvidia--Alpamayo-*` が存在する場合に `HF_HUB_OFFLINE=1` を有効にします。

`alpamayo` は `both` の一部では **ありません** (`both` は 2 つの Cosmos リポジトリです)
— 明示的に要求してください。

## `scripts/alpamayo_infer.py`

コミット済みのスクリプト (リポジトリの CLI ではありません — 実際のフローは独自仕様です)
で、ノートブックは `bash -lc 'source alpamayo_env.sh && python scripts/alpamayo_infer.py
--clips ... --out ...'` を介して実行します。モデルを **一度** ロードし、デモクリップを
ループ処理し、ノートブックカーネルが torch なしで読み取れるプレーンなアーティファクトを
書き出します: `<clip>_pred.npy`、`<clip>_gt.npy`、`<clip>_cot.txt`、そして `metrics.json`
(クリップごとの minADE)。各 `.pt` を `weights_only=False` でロードします (torch 2.8
のデフォルトは `True` で、これだと dict 内の `int`/`str` エントリを拒否してしまいます)。

`scripts/alpamayo_save_clip.py` は、それらの `.pt` ファイルを生成する管理者専用の
コンパニオンです (オンラインで、トークンを使用)。

## M9 ノートブックのフロー (書き直し済み)

`notebooks/M9_Alpamayo_VLA_Inference.ipynb` (11 セル):

1. **タイトル** + **ライセンス** (非商用の重み) の markdown。
2. **設定** — プロファイル/バケット、NVMe 作業ディレクトリ、`DEMO_CLIPS`、`HF_TOKEN` はオプション。
3. **GPU チェック** — **デバイスごと** の最大値が ≥ 40 GB (モデルは `.to("cuda")` で単一
   デバイスにロードされるため、GPU 全体の合計は誤解を招きます)。
4. **セットアップ** — `setup_cosmos_env.sh alpamayo` を実行 (冪等)。
5. **入力** — `hf-cache/alpamayo-demo/` からデモ `.pt` をダウンロード +
   `alpamayo_infer.py` を特定。
6. **推論** — `a1_5` venv に `bash -lc` で入り、`alpamayo_infer.py` を実行。
7. **可視化** — 予測軌跡と正解軌跡の比較 + 推論内容を出力。
8. **アップロード** — 出力 → `users/{profile}/m9/`; マニフェストは M10 が読み取るキー
   (`model` / `modes_run` / `timestamp` / `results`) を保持します。
9. **コスト。**
10. **検証 + インラインプレビュー + 次のモジュール (M10)。**

ワークショップの実行を安価に保つため、デフォルトは `DEMO_CLIPS = ["030c760c-..."]`
(1 クリップ) です; すべて実行するには、ステージングされた他のクリップのコメントを解除してください。

## 管理者による一度きりのセットアップ

管理者の `HF_TOKEN` (`Alpamayo-1.5-10B`、その `Cosmos-Reason2-8B` バックボーン、および
`PhysicalAI-Autonomous-Vehicles` のライセンスに同意済み) を持つ GPU アプリ上で:

```bash
export HF_TOKEN=hf_xxx
bash scripts/setup_cosmos_env.sh alpamayo          # build the a1_5 venv (online)
source /mnt/sagemaker-nvme/cosmos-work/alpamayo_env.sh
unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE          # data prep MUST be online

# For each demo clip: save the data dict, run one inference to fill the HF cache.
python scripts/alpamayo_save_clip.py --clip 030c760c-ae38-49aa-9ad8-f5650a545d26 \
    --t0-us 5100000 --out /mnt/sagemaker-nvme/m6_work/clips
python scripts/alpamayo_infer.py \
    --clips /mnt/sagemaker-nvme/m6_work/clips/030c760c-ae38-49aa-9ad8-f5650a545d26.pt \
    --out /mnt/sagemaker-nvme/m6_work/out

# Publish: add Alpamayo + Reason2 to the shared HF cache, and upload the .pt(s).
aws s3 sync /mnt/sagemaker-nvme/hf/hub s3://<shared>/hf-cache/hub/ --only-show-errors
aws s3 cp /mnt/sagemaker-nvme/m6_work/clips/030c760c-...pt s3://<shared>/hf-cache/alpamayo-demo/
```

管理者による両方のアップロードは `hf-cache/*` を対象とします。これは SageMaker 実行ロールが
共有バケット上で **書き込み** できる唯一のプレフィックスです — したがって、シーケンス全体が
GPU アプリのターミナルから直接実行されます (管理者ワークステーションは不要、IAM の変更も不要)。
参加者は共有バケット全体を読み取れるため、`hf-cache/hub/` ツリーと
`hf-cache/alpamayo-demo/*.pt` の両方を取得できます。

> **ノートブック + スクリプトのステージング** (`aws s3 sync notebooks/ scripts/ →
> notebook-templates/`) は例外です: `notebook-templates/*` は実行ロールにとって
> 読み取り専用なので、その 1 ステップだけは管理者ワークステーション (または共有バケットへの
> 書き込み権限を持つ任意の認証情報) から実行してください。

## 検証済みの実行 (リファレンスデプロイ例: アカウント <aws-account-id>)

クリップ `030c760c-ae38-49aa-9ad8-f5650a545d26 @ t0_us=5_100_000`; Chain-of-Causation
*"Nudge to the left to clear the construction equipment blocking the right side of
our lane."* (89 文字)。

- **p5.48xlarge (H100 80 GB)、シングル GPU** (2026-07-10): `HF_TOKEN` を未設定 +
  `HF_HUB_OFFLINE=1` で `MODEL+PROCESSOR OFFLINE LOAD OK` (5 シャード) (モデル +
  Cosmos-Reason2-8B バックボーンをキャッシュから)。**minADE 0.375 m。**
- **g5.48xlarge (8× A10G 24 GB)、`balanced-expert`** (2026-07-12): `pinned 42
  action-stack keys -> cuda:0`、オフライン (キャッシュのみ、ダウンロードなし)。**minADE
  0.378 m** — H100 の実行から 0.003 m の差 (アーキテクチャ間での bf16 演算順序; 許容範囲内)。
- **g5 でのノートブック全体の Restart & Run All** (2026-07-12、参加者パス、HF トークンなし):
  cell-3 が `balanced-expert` を自動選択、cell-6 で minADE 0.3779 m、cell-10 で
  `Status: PASS`、出力は `users/<profile>/m9/` に書き込まれました。

## マルチ GPU (24 GB カード) — `balanced-expert` デバイスマップ

p4d/p5 はしばしば容量制約を受けます。M9 は **24 GB のマルチ GPU** ボックス
(g5.48xlarge = 8× A10G 24 GB、g6.48xlarge = 8× L4 24 GB) でも動作しますが、単純な
`device_map="auto"` では **動作しません**:

- **`auto` が失敗する理由。** Alpamayo1_5 は `_no_split_modules` を定義していないため、
  accelerate は diffusion アクション `expert` (`Qwen3VLTextModel`、~2.3 B) を GPU 間で
  分割します。すると `sample_trajectories_from_data_with_vlm_rollout` は `device =
  input_ids.device` と `self.diffusion.sample(device=device)` を実行し、diffusion ループ
  内で expert の KV キャッシュの `torch.cat` が 2 つの GPU のテンソルを混在させ →
  `Expected all tensors to be on the same device (cuda:6 vs cuda:1)` になります。
- **単一の 24 GB GPU が失敗する理由。** ~21 GB のモデル全体が 1 つの A10G を埋め尽くし、
  その後 VLM の `generate` の KV キャッシュ増加が OOM を起こします。
- **修正: `--device-map balanced-expert`** (`scripts/alpamayo_infer.py` 内)。
  まず `auto` で一度ロードして *実際の* `hf_device_map` を読み取り、次に明示的なマップを
  再構築します。これは **アクションスタック** 全体 (`expert`、`diffusion`、`action_space`、
  `action_in_proj`、`action_out_proj`) を **cuda:0** に固定し、大きな VLM は他の GPU 間で
  シャーディングしたままにします。また `expert.forward` をラップして、VLM が生成した
  `past_key_values` を cuda:0 へ移行させます (accelerate は Cache オブジェクトの内部
  テンソルを自動移動 *しません*)。これで diffusion ロールアウト全体で `device == cuda:0`
  となり、キャッシュは自己整合します。cuda:0 はアクションスタック (~5 GB) + 移行された
  キャッシュ + diffusion のアクティベーションのみを保持します (合計 ~10 GB で、24 GB を
  十分に下回ります)。40 GB 以上の単一 GPU が存在しない場合、ノートブックの cell-3 は
  これを自動的に選択します。

## インスタンス / コストに関する注記

- **p5.48xlarge (H100 80 GB)** (シングル GPU) と **g5.48xlarge (8× A10G 24 GB)**
  (`balanced-expert`、下記参照) で検証済み。モデルは ~10.5 B パラメータ (~21 GB bf16) に
  加えて VLM ロールアウトのアクティベーションです。
  - **単一 GPU ≥ 40 GB** (p5、p4d A100、g6e L40S 48 GB): 1 つのデバイスにロード
    (`.to("cuda")`)、これが検証済みのパスです。p4d A100 40 GB は収まるはずですが、
    未検証の下限です; OOM になる場合は、p5 を使うか `balanced-expert` を強制してください。
  - **24 GB マルチ GPU** (g5、g6): `balanced-expert` は VLM をシャーディングし、
    アクションスタックを cuda:0 に固定します。これは **容量のヘッジ** です — p4d/p5 が
    利用できない場合でも、M9 は空いている任意のマルチ GPU ボックスで動作します。
- env + チェックポイントは NVMe 上に存在し、**アプリ再起動時にリセットされます**;
  セットアップセルは冪等で、新しいアプリは再ダウンロードする代わりに S3 (高速、同一リージョン)
  からチェックポイントを復元します。

## ライセンス

Alpamayo-1.5-10B の重みは **非商用** です (研究/評価のみ)。M9 と M10 の両方がこの通知を
表示します; 推論コードは Apache-2.0 です。
