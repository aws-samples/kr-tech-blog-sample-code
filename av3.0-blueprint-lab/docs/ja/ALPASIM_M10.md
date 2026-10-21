# AlpaSim (M10) — EC2 上でホストされる実際のクローズドループ評価

**ステータス:** M10 は Alpamayo 1.5 ポリシーを、実際の **AlpaSim** シミュレータ
([NVlabs/alpasim](https://github.com/NVlabs/alpasim)、Apache-2.0) を用いた
**クローズドループ** で評価します。M5/M6/M9 とは異なり、AlpaSim は **SageMaker Studio
ノートブック内では実行できません** — これは ≥40 GB GPU を必要とする gRPC マイクロサービスの
Docker-Compose フリートだからです。そのため、実際のシミュレーションは **GPU EC2 ホスト** 上で
実行され、M10 ノートブック (CPU) は、それが生成した本物の結果をダウンロードして可視化します。

**2 つのモード (ノートブックが自動検出し、あなた自身の実行を優先):**
1. **参加者のセルフラン** — 各参加者は、管理者が事前にプロビジョニングした GPU ホスト上で
   AlpaSim を実行し、**SSM** 経由でアクセスして、自身の
   `s3://<user-workspace>/users/<id>/m10/` に書き込みます。本物の「自分で走らせた」体験ですが、
   **~$10.5/hr/ホスト**、同時実行 ≤16 (G-vCPU クォータ)、初回ビルドは数十分から ~2〜3 時間。
   参加者ガイド: `M10_PARTICIPANT_SSM_RUNBOOK.md`; 管理者のプロビジョニング + IAM:
   `M10_MANUAL_TEST_RUNBOOK.md` の Part C。
2. **管理者のリファレンスラン** — 管理者が AlpaSim を一度実行して
   `s3://<shared>/m10-reference/` にアップロードします; すべての参加者が **ユーザーごとの
   GPU コスト $0** でその同じ本物の評価を検査します。これは、参加者が自身の実行を持たない場合の
   ノートブックのフォールバックです。

両方とも同一のアーティファクトレイアウトを書き込みます; 同じ `scripts/alpasim_ec2_setup.sh`
が両方に対応します (出力パスは `PARTICIPANT_ID`/`M10_OUTPUT_PREFIX`/`OUTPUT_BUCKET` env で
選択される — 未設定の場合 ⇒ 従来の管理者 `m10-reference/`)。

## このモジュールが抱えていた中核的な問題

出荷されたノートブックは、**ハルシネーションによる `alpasim` パッケージ**
(`import alpasim`、`alpasim.env.NuRecEnvironment`、
`alpasim.policy.PolicyWrapper.from_alpamayo`、
`alpasim.metrics.{CollisionMetric,RouteCompletionMetric,ComfortMetric,MetricAggregator}`)
と、捏造されたメトリクス (`route_completion`、`comfort_score`) を持つ作り物の gym スタイル
`env.reset()/env.step()` ループをインポートしていました。そのどれも存在しません — M5/M6 の
偽の `cosmos1` や M9 の偽の `alpamayo` と同じ種類のバグです。`pip install alpasim` は
存在しません。実際のインターフェースは Docker Compose を駆動する **`alpasim_wizard` Hydra CLI**
であり、実際のメトリクスは `collision_at_fault`、`collision_rear`、`dist_to_gt_trajectory`、
`offroad` です。

## M10 がノートブックで実行できない理由 (そして M5/M6/M9 ができた理由)

M5/M6/M9 は、SageMaker Studio JupyterLab アプリが **Docker デーモンを持たないマネージド
コンテナ** であるがゆえに、まさにインプロセスの `uv` venv として再構築されました。AlpaSim の
実行モデルは根本的に異なります:

- これは **マイクロサービス** のセットです — `renderer` (NuRec/NRE)、`driver` (Alpamayo
  ポリシー)、`physics`、`runtime`、`controller` — それぞれが **コンテナ** であり、gRPC で
  接続され、**Docker Compose** (`run_method: DOCKER_COMPOSE`) で立ち上げられます。
  `deploy=local` でも依然として *ローカルコンテナ* を意味し、コンテナなしの実行ではありません。
  純粋な Python モードは存在しません。
- **Alpamayo 1.5 ドライバーは ~40 GB VRAM を必要とし** (CFG-nav ありでは ≥60 GB)、
  NuRec レンダラーは独自の VRAM を持って同居します。

ノートブックのセルは `docker compose up` できないため、M10 は別の場所で実行されます。

## 採用したアーキテクチャ: 管理者実行のリファレンス評価

1. **管理者、一度、GPU EC2 ホスト上で** (`scripts/alpasim_ec2_setup.sh`): 共有 HF キャッシュ
   (Alpamayo-1.5-10B + Cosmos-Reason2-8B、M9 で既にステージング済み) を復元し、AlpaSim を
   クローンし、`source setup_local_env.sh`、`docker login nvcr.io`、ウィザードを実行し、
   本物の出力を `s3://<shared>/m10-reference/` にアップロードします。
2. **参加者、M10 ノートブック内で (CPU `ml.t3.medium`)**: リファレンス結果を `aws s3 sync`
   し、実際の `metrics_results.txt` テーブル、ロールアウトごとの `metrics.parquet`
   (`collision_at_fault`/`collision_rear`/`offroad` の棒グラフ、`dist_to_gt_trajectory` の
   ヒストグラム)、AlpaSim 自身の `metrics_results.png`、および実際の評価ビデオを可視化します。

これは M9 が実行するまさにそのモデルの **本物の** クローズドループ評価です — シミュレートされた
数値ではありません。あらゆる箇所で、ユーザーごとのシミュレーションではなく管理者の
リファレンスランとして正直に位置づけられています。

## 正直な M9 → M10 のつながり

AlpaSim は M9 の予測軌跡の `.npy` を **消費しません**。それは **同じ
`nvidia/Alpamayo-1.5-10B` チェックポイント** (共有 hf-cache から) を `driver=alpamayo1_5`
プラグインとしてロードし、クローズドループで駆動します。したがって:

- **M9** = Alpamayo モデルが軌跡を **オープンループ** で予測 (minADE)。
- **M10** = **同じモデル** が AlpaSim 内で **クローズドループ** で駆動 (安全メトリクス)。

共有されるアーティファクトはチェックポイントであり、軌跡ファイルではありません。ノートブックは
この由来を表示するためだけに M9 の `manifest.json` を読み取ります。

## インスタンス & GPU 配置 (リポジトリのトポロジー設定より)

AlpaSim の `topology` 設定はサービスを GPU に固定します (`src/wizard/configs/topology/`):

| topology | driver | renderer | physics | 収まる環境 |
|---|---|---|---|---|
| `1gpu` | GPU 0 | GPU 0 | GPU 0 | 1 枚の **≥80 GB** カード (A100 80GB / H100) — driver ~40 GB + 同居する renderer |
| `2gpu` | GPU 0 (×3 レプリカ) | GPU 1 | GPU 0+1 | **≥40 GB を 2 枚** のカード → **L40S 48 GB ×2 = g6e.12xlarge** |

24 GB のカード (A10G/L4) は、どちらのトポロジーでも 40 GB のドライバーに **収まりません** —
そして AlpaSim はドライバーを我々が制御できないコンテナとして実行するため、M9 の
`balanced-expert` によるマルチ 24 GB カードの技はここでは適用できません。

> ### ⚠️ M10 は **≥2 個の GPU** が必要 — そしてインスタンス名の数字は GPU 数では *ない*
> `topology=2gpu` (デフォルト) は renderer を **GPU 1** に配置するため、ホストは
> **少なくとも 2 個の GPU** を公開している必要があります。g6e ファミリーでは、**vCPU サイズが
> 大きいことは GPU が多いことを意味しません** — GPU が複数あるのは 3 つのサイズだけです。
> 「12xlarge より大きく見える」という理由で `g6e.16xlarge` を選ぶと、**1 個の GPU** しか得られず、
> 起動時に `Service renderer requested GPUs [1] but only 0 .. 0 are available` で実行が死にます。
>
> | g6e サイズ | GPU 数 | vCPU | M10 (2gpu) で OK? |
> |---|---|---|---|
> | g6e.xlarge / 2xlarge / 4xlarge / 8xlarge | **1** | 4–32 | ❌ シングル GPU |
> | **g6e.12xlarge** | **4** | 48 | ✅ **推奨** |
> | g6e.16xlarge | **1** | 64 | ❌ シングル GPU (大きいボックスでも、依然 1 GPU!) |
> | g6e.24xlarge | **4** | 96 | ✅ (M10 にはオーバースペック) |
> | g6e.48xlarge | **8** | 192 | ✅ (オーバースペック) |
>
> 経験則: **マルチ GPU の g6e = 12xlarge (4)、24xlarge (4)、48xlarge (8)**。それ以外の
> すべてのサイズ — 16xlarge を含む — は **シングル GPU** のボックスです。実行前に確認してください:
> `nvidia-smi --query-gpu=index,name,memory.total --format=csv` は **≥2** 行をリストする必要があります。

- **推奨 (コスト最適): `g6e.12xlarge` (4× L40S 48 GB) + `topology=2gpu`**、
  オンデマンドで ~$10.5/hr (リファレンスデプロイ例リージョン: us-west-2; 価格はリージョンごとに異なる)。
- **安全なフォールバック:** `p4de.24xlarge` / `p5.48xlarge` (80 GB カード) + `topology=1gpu`
  (1gpu には 1 枚の ≥80 GB カードで十分; 2gpu には依然 2 枚のカードが必要)。
- CFG-nav は **オフ** のまま (デフォルト) にして、ドライバーが ~40 GB に収まるようにします。

## ゲート付き依存関係

- **HF:** `nvidia/Alpamayo-1.5-10B` + `nvidia/Cosmos-Reason2-8B` (共有 hf-cache から
  オフラインでロード) と **`nvidia/PhysicalAI-Autonomous-Vehicles-NuRec`** データセット。
  ⚠️ **NuRec はランタイムにダウンロードされ、共有オフラインキャッシュには含まれません**
  (モデルとは異なります) — そのため `HF_TOKEN` は `alpasim_ec2_setup.sh` の **必須要件** です
  (それがないと preflight が `HF_TOKEN not set` で失敗します)。また、そのトークンのアカウントは
  NuRec ライセンスに同意している必要があります (そうでないと `GatedRepoError`)。**管理者
  リファレンス** モードでは管理者が自身のトークンを供給します; **参加者のセルフラン** モードでは
  **各参加者が自身のトークンを供給します** — これは「参加者は HF トークン不要」ルールが
  当てはまらない唯一の箇所です (`PREREQUISITES.md` と `M10_PARTICIPANT_SSM_RUNBOOK.md` を参照)。
- **NGC:** renderer イメージ `nvcr.io/nvidia/nre/nre-ga:26.04` は NGC から取得されます。
  NGC API キー (`https://org.ngc.nvidia.com/setup/api-key`) とそのイメージへのアクセスが
  必要です。これは **M10 のハードゲート** です — `alpasim_ec2_setup.sh` は長時間のビルドの前に
  `docker manifest inspect` でこれを検証します。

## 管理者による一度きりのシーケンス

Docker 対応の GPU ホスト (AWS **Deep Learning Base GPU AMI** — Docker + NVIDIA Container
Toolkit + ドライバー ≥570 を同梱) を、**インターネットへの egress を持つパブリックサブネット**
で起動します (ラボ VPC は隔離されているため; デフォルト VPC を使用してください)。その後:

```bash
export HF_TOKEN=hf_xxx            # Alpamayo + Cosmos-Reason2 + NuRec accepted
export NGC_API_KEY=nvapi-xxx      # NGC access to nre-ga
# SHARED_BUCKET is deliberately NOT exported: the script derives
# av30lab-shared-data-<acct>-<region> from STS + IMDS and exits 1 if it cannot.
bash scripts/alpasim_ec2_setup.sh
# verify the m10-reference/ upload, then TERMINATE the instance.
```

スクリプトの処理: preflight (nvidia-smi / docker / NVIDIA runtime / uv / cargo) →
`hf-cache/hub` を `$HF_HOME` へ復元 → AlpaSim をクローン (ピン留め) → NGC ログイン +
`docker manifest inspect` ゲート → `source setup_local_env.sh` →
`uv run alpasim_wizard deploy=local topology=2gpu driver=alpamayo1_5
scenes.scene_ids="['clipgt-01d503d4-449b-46fc-8d78-9085e70d3554']"
wizard.log_dir=$PWD/out eval.video.video_layouts=[REASONING_OVERLAY]` →
`aggregate/metrics_results.txt`、`rollouts/**/metrics.parquet`、評価 `.mp4` を検証 →
`s3://<shared>/m10-reference/` へアップロード (`aggregate/`、`rollouts/`、`eval/eval.mp4`、
`run.json`)。

リファレンスバンドルは、**共有** バケット上の `hf-cache/` の兄弟プレフィックス
`m10-reference/` の下に書き込まれます: EC2 ホスト上の管理者認証情報がそれを書き込み;
参加者は共有バケット全体を読み取ります。(コスト: g6e.12xlarge で一度きり ~$30; 参加者ごとは $0。)

## 実際の出力アーティファクト (ノートブックが可視化するもの)

- `aggregate/metrics_results.txt` — 整形されたドライビングスコアテーブル (平均/標準偏差/分位数)。
- `aggregate/metrics_results.png` — AlpaSim のビジュアルサマリー。
- `rollouts/{scene}/{batch}/metrics.parquet` — ロールアウトごとのメトリクス
  (`collision_at_fault`、`collision_rear`、`dist_to_gt_trajectory`、`offroad`、…)。
- `eval/eval.mp4` — Chain-of-Causation オーバーレイ付きのクローズドループ・ロールアウト。
- `run.json` — 由来情報 (driver、scene、topology、renderer イメージ、instance)。

## 検証済みの実行 (2026-07-12、リファレンスデプロイ例 account <aws-account-id>)

**g6e.12xlarge** (4× L40S 46 GB)、alpasim **v0.96.0** *(このタグは上流から削除されました。現在のピンは v2026.5 で、**未検証**です — 下の注記を参照)*、renderer
`nvcr.io/nvidia/nre/nre-ga:26.04`、scene `clipgt-01d503d4-449b-46fc-8d78-9085e70d3554`、
topology `m7_4gpu` (driver が GPU 0 単独) 上での、`nvidia/Alpamayo-1.5-10B` の実際の
AlpaSim クローズドループ評価。ドライバーは S3 hf-cache から Alpamayo を **オフライン** で
ロードしました (トークンなし、ダウンロードなし)。本物のドライビングスコア:

| メトリクス | 値 |
|---|---|
| collision_any / collision_at_fault / collision_rear | 0.00 (衝突なし) |
| offroad / offroad_or_collision | 0.00 |
| dist_to_gt_trajectory (max) | 4.37 m |
| dist_traveled_m (vs GT 73.77 m) | 78.12 m |
| progress_rel / progress | 0.92 / 1.00 (ルートは実質的に完走) |
| min_distance_to_obstacle_m | 1.12 m |
| duration_frac_20s | 0.78 |

出力は `s3://<shared>/m10-reference/` にアップロードされました (aggregate/、rollouts/、
reasoning オーバーレイ付きの eval/eval.mp4、run.json)。一度きりのコストは ≈ $30
(キャッシュミスの初回ビルドを含む g6e.12xlarge の数時間)。

### 実行の配線中に見つかった落とし穴 (scripts/alpasim_ec2_setup.sh で修正済み)
- **SSM シェルの `set -u` 下で `$HOME` が未束縛** → 早い段階で `HOME=/root` を export。
- **`Mount point does not exist: data/drivers`** → ウィザードは
  `data/{drivers,nre-artifacts/ego-hoods,trafficsim-models}` をバインドマウントする;
  先に `mkdir -p` する。
- **ドライバー 401 gated repo** → ベースの `driver` サービスに `environments` がないため、
  オンラインで HF に到達しようとした; `driver.environments` =
  `HF_TOKEN, HF_HOME, HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1` を設定する
  `deploy/local_m7.yaml` を追加。(M9 と同じオフラインキャッシュの教訓。)
- **CUDA OOM** → 標準の `topology=2gpu` は **3 つ** のドライバーレプリカを GPU 0 に置く;
  40 GB の Alpamayo コピー 3 つは L40S に収まらない。ドライバーに GPU 0 を単独で与える
  (renderer GPU 1、physics GPU 2、trafficsim GPU 3)、1 レプリカ、1 ロールアウトのカスタム
  `topology=m7_4gpu` を使う。

## ライセンス

Alpamayo-1.5-10B の重みは **非商用** です (研究/評価のみ)。AlpaSim のコードは Apache-2.0 です。
NuRec のシーンは NVIDIA AV NuRec Dataset License の下にあります。M10 ノートブックはこの通知を表示します。

---

### ピン留めされた alpasim タグ（ワークショップ前に読んでください）

`scripts/alpasim_ec2_setup.sh` は `ALPASIM_TAG`（デフォルト `v2026.5`）をピン留めします。
上に記録された実測実行は `alpasim-base-v0.96.0` を使用しましたが、そのタグは**もう存在しません** —
`git ls-remote --tags https://github.com/NVlabs/alpasim` は `v2026.4` と `v2026.5` のみを
返します。スクリプトは以前タグミス時に黙ってデフォルトブランチへフォールバックしていたため、
実行が動く `main` を使う可能性がありました。現在は**明示的に失敗し**、利用可能なタグを出力します。

`v2026.5` について確認済みのこと: このスクリプトが触れる上流パスはすべて存在し
（`deploy/local.yaml`、`driver/alpamayo1_5.yaml`、6 項目の `topology/`、
`data/scenes/sim_scenes.csv`）、ピン留めした `SCENE_ID` は 916 シーンの CSV にちょうど 1 回
現れます。`main` はそのシーンを 2 回列挙します。

**未確認のこと**: `v2026.5` に対する M10 の実行記録はありません。イベント前に管理者 EC2
ホストで一度実行してください。失敗した場合は `ALPASIM_TAG=v2026.4`（910 シーン、ピン留めした
シーンを含む）を試し、デフォルトブランチには戻さないでください。
