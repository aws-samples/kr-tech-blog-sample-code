# AV 3.0 Blueprint Lab — 前提条件

## 参加者向け：ノートブックのために準備するものはありません 🎉

**どのノートブックモジュールについても、Hugging Face アカウント、トークン、モデルライセンスの
承認はいずれも不要です。** ノートブックが使うすべてのモデル（Cosmos Reason、Cosmos
Transfer、Cosmos Predict、Alpamayo）は**ワークショップ管理者によって S3 に事前キャッシュ**
されており、ノートブックはそれらを**オフラインで**読み込みます。ダッシュボードリンクを開いて
モジュールを実行するだけです — [PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md) を参照。

> 必要なのは、管理者が送付する**参加者用ダッシュボードリンク**だけです。

### 唯一の例外 — オプションの M10 自己実行には自分自身の HF トークンが必要 🔑
M10 の*ノートブック*（結果の可視化）は、他のすべてのモジュールと同様、トークンを必要としません。
しかし、GPU ホスト上で SSM 経由で実際の AlpaSim シミュレーションを自分で実行する
**オプションの上級パス**を取る場合（[M10_PARTICIPANT_SSM_RUNBOOK.md](M10_PARTICIPANT_SSM_RUNBOOK.md)
を参照）、自分自身の Hugging Face トークンが**必要**です。AlpaSim がゲート付きの
**`nvidia/PhysicalAI-Autonomous-Vehicles-NuRec`** シーンを実行時にダウンロードするためです
（このデータセットは、モデルとは違って共有オフラインキャッシュには*含まれていません*）。
M10 の自己実行の前に：

1. Hugging Face アカウントとトークンを作成します（`https://huggingface.co/settings/tokens`）。
2. そのアカウントで
   [`nvidia/PhysicalAI-Autonomous-Vehicles-NuRec`](https://huggingface.co/datasets/nvidia/PhysicalAI-Autonomous-Vehicles-NuRec)
   のライセンスに同意します（「Agree and access repository」）。
3. SSM セッション内で `export HF_TOKEN=hf_…` できるよう、トークンを手元に用意します。

M10 ノートブックのみを実行する場合（デフォルト）は、これをスキップしてください — トークンは不要です。

### ライセンスに関する注記（M9 / M10）
M9/M10 が使用する Alpamayo-1.5-10B の重みは、**非商用**ライセンス（研究・評価のみ）の下にあります。
自分でダウンロードすることはありませんが、M9/M10 を実行することでそのライセンスに同意したことになります。

---

## ワークショップ管理者向け：モデルを事前キャッシュする（イベント前に一度だけ実施）

ノートブックが参加者に Hugging Face への認証を求めることは決してありません。代わりに、管理者が
一度だけすべてをダウンロードし（HF トークン ＋ 承認済みライセンスで）、S3 にステージングします。
別々の 2 つのキャッシュがあります：

### A. シンプルなモデルキャッシュ — M2（`model-cache/`）
`scripts/cache_models.sh` は、各リポジトリを `hf download --local-dir` でダウンロードし、
`s3://<shared>/model-cache/<name>/` に `aws s3 sync` します。**M2** ノートブックはそこから
`aws s3 sync` します — プレーンなファイルツリーです。（M3 は純粋な Python のキュレーション
ステップで、モデルは読み込みません。M2 の `captions.json` 出力を消費します。）

```bash
export HF_TOKEN=hf_...            # admin token, licenses accepted (see list below)
./scripts/cache_models.sh          # resolves the shared bucket from the stack
```

### B. HF オフラインキャッシュ — M5、M6、M9（`hf-cache/hub/`）
M5/M6/M9 は、実行時に Hugging Face 独自のキャッシュレイアウトを通じてゲート付きの
チェックポイントを読み込みます（M5/M6 は Cosmos リポジトリの `examples/inference.py` を経由し、
M9 は `Alpamayo1_5.from_pretrained` を経由します。後者は隠れた `Cosmos-Reason2-8B` VLM
バックボーンも取得します）。これを**参加者のトークンなしで**動作させるために、管理者は
**HF キャッシュツリー**を `s3://<shared>/hf-cache/hub/` にステージングします。
`setup_cosmos_env.sh` がそれを `HF_HOME` に復元し、`HF_HUB_OFFLINE=1` を設定します。

このキャッシュを投入する最も信頼性の高い方法（各モデルが必要とするすべてのリビジョン ＋
サイドファイルが確実に存在することを保証します）は、**管理者の HF トークンを使って GPU
インスタンス上で M5、M6、M9 を一度実行し**、その結果生じたキャッシュを sync することです：

```bash
# On a GPU JupyterLab app, after M5 + M6 + M9 have each run once successfully:
aws s3 sync /mnt/sagemaker-nvme/hf/hub \
  s3://<shared-bucket>/hf-cache/hub/ --only-show-errors
```

その後は、参加者にトークンは不要です：`setup_cosmos_env.sh` が S3 キャッシュを認識し、
それを復元してオフラインで実行します。

> **M9 にはデモクリップも必要です。** M9 の `PhysicalAI-Autonomous-Vehicles` データセットは
> オフラインで読み込めないため、管理者がデモクリップを一度事前保存し
> （`scripts/alpamayo_save_clip.py`）、`s3://<shared>/hf-cache/alpamayo-demo/` にアップロード
> します（`hf-cache/` の下に置くことで、exec ロールの書き込みスコープを持つ GPU アプリの
> ターミナルからアップロードできます）。一度限りの完全な手順は
> [ALPAMAYO_M9.md](ALPAMAYO_M9.md) を参照。

### C. AlpaSim クローズドループリファレンス評価 — M10（`m10-reference/`）
M10 は Alpamayo ポリシーを、本物の AlpaSim シミュレータで**クローズドループ**評価します。
これは Docker-Compose のマイクロサービスシステムであり、**Studio ノートブックでは実行できず**
（Docker デーモンがない）、40 GB 以上の GPU が必要です。そのため管理者はこれを **GPU EC2
ホスト上で一度だけ**実行し（`scripts/alpasim_ec2_setup.sh`）、本物の結果を
`s3://<shared>/m10-reference/` にアップロードします。M10 ノートブック（CPU）はそれらを
ダウンロードして可視化します。管理者の HF トークン（NuRec データセット）**および NGC API
キー**（ゲート付き NuRec レンダラーイメージ）が必要です。一度限りで約 $30、参加者のコストは $0。
完全な手順、インスタンスの選択、GPU 配置の詳細：[ALPASIM_M10.md](ALPASIM_M10.md)。

### 管理者：一度だけ承認するライセンス（管理者の HF アカウントで）
各リポジトリで<strong>「Agree and access repository」</strong>に同意し、それから `HF_TOKEN` を設定します：

| リポジトリ | 使用箇所 | ライセンス |
|---|---|---|
| [nvidia/Cosmos-Reason1-7B](https://huggingface.co/nvidia/Cosmos-Reason1-7B) | M2, M5, M6 | NVIDIA Open Model |
| [nvidia/Cosmos-Guardrail1](https://huggingface.co/nvidia/Cosmos-Guardrail1) | M5, M6 | NVIDIA Open Model |
| [nvidia/Cosmos-Transfer2.5-2B](https://huggingface.co/nvidia/Cosmos-Transfer2.5-2B) | M5 | NVIDIA Open Model |
| [nvidia/Cosmos-Predict2.5-2B](https://huggingface.co/nvidia/Cosmos-Predict2.5-2B) | M6 | NVIDIA Open Model |
| [nvidia/Alpamayo-1.5-10B](https://huggingface.co/nvidia/Alpamayo-1.5-10B) | M9, M10 | **非商用** |
| [nvidia/Cosmos-Reason2-8B](https://huggingface.co/nvidia/Cosmos-Reason2-8B) | M9, M10（Alpamayo VLM バックボーン） | NVIDIA Open Model |
| [nvidia/PhysicalAI-Autonomous-Vehicles](https://huggingface.co/datasets/nvidia/PhysicalAI-Autonomous-Vehicles) | M9（デモクリップ、データセット） | NVIDIA |
| [nvidia/PhysicalAI-Autonomous-Vehicles-NuRec](https://huggingface.co/datasets/nvidia/PhysicalAI-Autonomous-Vehicles-NuRec) | M10（AlpaSim 評価シーン） | NVIDIA AV NuRec Dataset License |

**M10 には NGC も必要です**（HuggingFace ではありません）：AlpaSim の NuRec レンダラーイメージ
`nvcr.io/nvidia/nre/nre-ga:26.04` は NVIDIA NGC から取得します。`https://org.ngc.nvidia.com/setup/api-key`
で API キーを取得し、そのイメージへのアクセスを確保してください。これは管理者専用です
（M10 は EC2 ホスト上で実行されます。[ALPASIM_M10.md](ALPASIM_M10.md) を参照）。

> **セキュリティ：** 管理者トークンは秘密です — コミットしないでください。また、キャッシュが
> 完了した後は失効させてください（参加者が触れるのは S3 上のキャッシュだけです）。

### フォールバック（S3 の HF キャッシュがステージングされていない場合）
`hf-cache/hub/` が S3 にない場合、M5/M6 は**オンライン**ダウンロードにフォールバックし、その場合は
参加者に `HF_TOKEN` が*必要*になります（ノートブックの最初のセルに貼り付けます）— 加えて
承認済みライセンスも必要です。M9 はさらにデモの `.pt` がステージングされている必要があります
（そのデータセットはオフラインではまったく読み込めません）。キャッシュ ＋ デモクリップ（§B）を
ステージングすれば、これらすべてを回避できます — 推奨。
