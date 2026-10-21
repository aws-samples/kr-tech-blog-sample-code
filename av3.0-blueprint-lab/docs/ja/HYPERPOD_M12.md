# HyperPod (M12) — 実際の分散トレーニングデモ、設計上 CPU

**ステータス:** M12 は、M3 のキュレーション済みキャプションに対して **実際の分散 PyTorch DDP
トレーニングジョブ** (SageMaker Training Job、`instance_count=2`) を実行し、ジョブ自身の
アーティファクトから **測定された** エポックごとの損失とスループットを可視化します。何も
シミュレートされていません。これは HyperPod クラスターでは **ありません** — それはノートブックが
プロビジョニングできない別のインフラです (下記参照)。M12 は、HyperPod がスケールさせる
*分散トレーニングのパターン* を、手頃な CPU インスタンス上で実演します。

## M12 が何だったか、そして今何であるか

出荷された M12 は、M5/M6/M9/M10 のような **ハルシネーション API の失敗ではありませんでした** —
すべてのインポートと AWS 呼び出しは実在しました (`sagemaker.pytorch.PyTorch`、
`torch.distributed`、`describe_training_job`)。その問題は別のものでした:

| 出荷された M12 | 修正された M12 |
|---|---|
| タイトルは「HyperPod」と言っていたが、素の SageMaker Training Job を使っていた | 正直に位置づけ: 分散 *パターン*、HyperPod = 概念 (冒頭で明記) |
| M3 入力を宣言していたが決して読まなかった (`estimator.fit()` に `inputs=` がなかった) | `fit(inputs={"training": …})` が M3 の `curated_captions.json` をマウントする; スクリプトは実際のキャプションから特徴量を設計する |
| メトリクスは `np.random` のシミュレーションだった | 損失/スループットはジョブの実際の `training_log.json` から解析 (rank-0 が書いた) |
| `backend="nccl"` がハードコード (GPU が必要) | `gloo` (CPU) / `nccl` (GPU) を自動選択するので CPU **と** GPU で動作する |
| `ml.g5.xlarge` × 2 を要求 (GPU クォータ = 1 → 失敗する) | `ml.m5.xlarge` × 2 (CPU トレーニングクォータが利用可能) |
| コストはハードコードされた定数だった | 実際のデモコストは `BillableTimeInSeconds` から; HyperPod のコストは明確に「概念的」とラベル付け |

## なぜ CPU なのか (そしてなぜそれが正しい選択なのか)

デモモデルは小さな MLP (`QualityPredictor`、8 個の設計された特徴量) です。教育上のポイントは
**本物のマルチノード `torch.distributed` の all-reduce** であり、GPU のスループットではありません
— 小さなモデルでは GPU の優位性を示せません。そのため:

- **`ml.m5.xlarge` × 2、`gloo` バックエンド** — 実際の 2-rank DDP: `init_process_group`、
  `DistributedSampler` のシャーディング、`DDP` の勾配 all-reduce、rank-0 のチェックポイント。
  そのすべてが本物として、わずかな費用で行われます。
- CPU トレーニングクォータは最初から利用可能です; デモは GPU を必要としません。

## CPU 対 GPU のトレードオフ (将来の GPU 実行のために)

**同じトレーニングスクリプト** が GPU/`nccl` で変更なしに動作します — `torch.cuda.is_available()`
を検出し、バックエンド + デバイスを選択します。M12 を GPU で実行するには:

1. **GPU トレーニングクォータを引き上げる。** 2026-07 の事前テスト時点で、リファレンスラボ
   アカウント (`us-west-2`; あなたのリージョンは異なる場合があります — 自身のクォータを確認してください) では:
   - `ml.g5.xlarge for training job usage` = **1** (クォータコード `L-B6D80D9C`、
     Adjustable) → 2 ノードジョブのために ≥2 をリクエスト。承認には ~数日かかります。
   - `ml.m5.xlarge for training job usage` = **30** (今日 CPU が動作する理由)。
2. ノートブックで `INSTANCE_TYPE = "ml.g5.xlarge"` を設定 (cell-4)。他に変更なし —
   スクリプトが自動的に `nccl` と `cuda` に切り替わります。

| | CPU (`ml.m5.xlarge` × 2) | GPU (`ml.g5.xlarge` × 2) |
|---|---|---|
| バックエンド | `gloo` | `nccl` (本番のコレクティブ) |
| クォータ (リファレンスデプロイ例: us-west-2、2026-07) | 30 — 今すぐ利用可能 | 1 — 引き上げが必要 (~数日) |
| コスト | ~$0.23/hr × 2 | ~$1.41/hr × 2 |
| DDP all-reduce 検証済み | ✅ (gloo) | ✅ (nccl) |
| デモモデルが GPU の恩恵を受けるか | いいえ (小さな MLP) | いいえ (小さな MLP) |

**結論:** 両方とも「2 ノードが本当に分散トレーニングした」ことを証明します。GPU は実際の
`nccl` パスを追加するだけです; 小さなモデルはどちらでも速度の恩恵を示しません。CPU は
ワークショップにとって実用的な選択です; GPU は、クォータが引き上げられた場合の、文書化された
1 行の切り替えです。

## なぜ本物の HyperPod がノートブックの対象外なのか

SageMaker HyperPod は **永続的なクラスター** であり、`aws sagemaker create-cluster` (Slurm
または EKS オーケストレーション) に加えて VPC/サブネット/セキュリティグループ、共有ストレージ
用の FSx for Lustre、EFA ネットワーキングで作成されます。クラスターの作成だけで ~20 分かかり、
その後クラスターは継続的に課金されます — これは長時間稼働する大規模トレーニングのインフラで
あり、ノートブックのセルではありません。(概念的には、M10 の AlpaSim がノートブックの外の GPU EC2
ホストで実行されるのと同じ理由です。) さらに、`ml.p4d.24xlarge for cluster usage` と
`... for training job usage` はどちらもこのラボアカウントで **0** なので、本物の HyperPod p4d
クラスターはいずれにせよここでは作成できません。したがって M12 は、HyperPod がスケールさせる
パターンを教え、HyperPod の付加価値 (自動ノード置換、FSx、Slurm/EKS スケジューリング、
EFA/NCCL) を説明し、実際にプロビジョニングはしません。

## 出力アーティファクト

- `users/<profile>/m12/training_metadata.json` — ジョブサマリー、データソース
  (`real_m3` | `synthetic`)、測定されたエポックごとのメトリクス、HyperPod ノート。
- `users/<profile>/m12/<job-name>/output/model.tar.gz` — チェックポイント +
  `training_log.json` (ノートブックがプロットする実際のメトリクス)。
- `users/<profile>/m12/input/curated_captions.json` — トレーニングチャネルとして
  ステージングされた M3 データ (M3 が実行された場合のみ)。

## 検証済みの実行

**ローカルドライラン (2026-07-13、$0)** — まさに埋め込まれた `train_distributed.py` を、M3 の
実際の `curated_captions.json` (`ky-5-34x1bx`、12 キャプション) に対して、実際の 2 プロセス
gloo DDP ジョブ (`torchrun --nproc_per_node=2`) として実行:

```
Backend: gloo | world_size: 2 | nodes: 2
Dataset: REAL M3 captions | samples: 12 | feature_dim: 8
Epoch 1/5 | Loss: 0.134977 ...
Epoch 5/5 | Loss: 0.000053 | Throughput: 7 samples/s
Checkpoint + training_log.json saved
```

これは重要な部分を確認します: 本物の 2-rank `torch.distributed` の init + all-reduce (gloo)、
実際の M3 キャプションの取り込み (`dataset: real_m3`)、キーがノートブックの cell-6 パーサーと
一致する実際のエポックごとの `training_log.json`、そしてロード可能なチェックポイント
(`model_state_dict` + `optimizer_state_dict` + `final_loss`)。損失は 0.135 → 5.3e-5 に
低下します — シミュレートではなく、測定されたものです。

**マネージド実行の検証済み (2026-07-14、Studio Run-All、参加者プロファイル ky-5-34x1bx):**
**`ml.m5.xlarge`×2** での `estimator.fit()` が完了しました — `Training job completed`、
320 課金秒、**`Data source: real_m3`** (`training` チャネル経由で M3 のキュレーション済み
キャプションでトレーニング)、モデルアーティファクトは
`users/ky-5-34x1bx/m12/.../output/model.tar.gz`、デモコスト ~$0.02。実際の Studio 環境で
M3→M12→メトリクスの完全なパイプラインがエンドツーエンドで確認されました。

### 参加者の Run-All が浮上させた 6 つの実際のバグ (どれもローカルでは再現不可)
Studio カーネル + マネージドトレーニングジョブは、ローカルドライランでは決して当たれない
一連の問題を露呈しました:
1. **SDK v3 カーネル** — SageMaker Distribution は Python SDK v3 (モジュール化された
   `sagemaker.core`/`sagemaker.train`、トップレベルの `Session` や `sagemaker.pytorch.PyTorch`
   はない) を同梱している。修正: cell-1 で v2 をピン留め (`sagemaker>=2.257.2,<3`)。
2. **v2/v3 のメモリ内混在** — pip はファイルを入れ替えるが、カーネルは v3 をインポート済みの
   まま保持する (`cannot import name ModelMetrics`)。修正: cell-1 が v2 のインストール後に
   カーネルを自動再起動する (再起動後に cell-1 を一度再実行する)。
3. **`torch_distributed` は SDK で GPU/Trainium 専用** — CPU では拒否される
   (`ValueError: ... only for GPU and Trainium`)。修正: `distribution={"mpi":
   {"processes_per_host": 1}}` を使う。
4. **exec ロールの書き込みスコープは `users/*`** — estimator のデフォルトのコードアップロード先
   であるバケットルート `<job>/source/...` は拒否される。修正: `code_location=
   s3://<bucket>/users/<profile>/m12/code`。
5. **`iam:PassRole` + `sagemaker:CreateTrainingJob` の欠如** — exec ロールは Studio アプリ
   管理用に構築されており、トレーニングジョブの投入用ではなかった。修正:
   `infra/av30_constructs/sagemaker.py` にスコープ付きの `SageMakerTrainingJobs` (av30-m12-* ARN)
   + 自分自身のみの `PassRole` (`iam:PassedToService=sagemaker.amazonaws.com`) ステートメントを
   追加してデプロイした。
6. **MPI の rank 順 ≠ SM_HOSTS の順 → ランデブーハング。** 最初の CPU 試行では
   `SM_HOSTS` (ソート済み) から rank/master を導出したが、MPI の rank-0 ホストは `algo-2` で
   `SM_HOSTS[0]` は `algo-1` だったため、`dist.init_process_group` が
   "Waiting for orted process" で永遠にハングした。修正: **mpi4py** (`MPI.COMM_WORLD`) から
   rank/world_size を読み取り、rank-0 自身のホスト名を `MASTER_ADDR` としてブロードキャストする。

**GPU の注記は依然として適用:** `ml.g5.xlarge` では distribution を `torch_distributed`
(torchrun) に戻し、スクリプトが nccl を自動選択します; 上記の mpi4py ランデブーは CPU パスです。
