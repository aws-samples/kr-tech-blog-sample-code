<!-- Language: [English](../en/README.md) · [한국어](../ko/README.md) · **日本語** -->

# AV 3.0 Blueprint Lab

**ドキュメント言語:** [English](../en/README.md) · [한국어](../ko/README.md) · **日本語**

[Building an End-to-End Physical AI Data Pipeline for Autonomous Vehicle 3.0 on AWS with NVIDIA](https://aws.amazon.com/blogs/industries/building-an-end-to-end-physical-ai-data-pipeline-for-autonomous-vehicle-3-0-on-aws-with-nvidia/) をハンズオンで実行するための、セルフサービス型 AWS プラットフォームです。参加者は <strong>13 個の Jupyter ノートブックモジュール（M0〜M12）</strong>に取り組み、自動運転車データパイプラインの全体像 — データ探索、動画キャプション生成（Cosmos Reason）、データキュレーション（Cosmos Curator）、合成データ拡張（Cosmos Transfer & Predict）、Vision-Language-Action 推論（Alpamayo）、クローズドループシミュレーション（AlpaSim）、セマンティック検索、分散学習、3D 再構成、本番パイプライン自動化 — を通して学びます。

このプラットフォームは、管理者ダッシュボードと参加者ダッシュボード、マルチユーザー SageMaker Studio のプロビジョニング、自動コスト管理を備えた**単一の AWS CDK スタック**としてデプロイされます。誰でも**自分自身の AWS アカウント**にデプロイできます。

> このリポジトリが提供するのは**ワークショップのコードとドキュメントのみ**です。サードパーティのモデルおよびデータセット（NVIDIA Cosmos/Alpamayo、nuScenes、NuRec）をオーケストレーションしますが、それらはご自身で**各自のライセンス**に従ってダウンロードするものであり、一部は**商用利用不可**です。[NOTICE](../../NOTICE) を参照してください。

---

## 13 のモジュール（M0〜M12）

| モジュール | ブログのステージ | 内容 | 推奨インスタンス |
|---|---|---|---|
| **M0** | — | パイプライン概要 — エンドツーエンドのパイプラインを各モジュールにマッピング（コンピュートなし） | `ml.t3.medium`（CPU） |
| **M1** | 1–2 | データ探索 — 実際の **nuScenes-mini** センサーデータの取り込みと探索、シーンの選択 | `ml.t3.medium`（CPU） |
| **M2** | 3 | Cosmos Reason キャプション生成 — サンプリングしたクリップの VLM キャプション | `ml.g5.12xlarge`（GPU） |
| **M3** | 3 | Cosmos Curator — **NeMo Curator** による動画キュレーション（分割、トランスコード、モーションフィルタ） | `ml.g5.12xlarge`（GPU） |
| **M4** | 4 | OpenSearch セマンティック検索 — キャプション埋め込みに対する k-NN 検索 | `ml.t3.medium`（CPU） |
| **M5** | 5 | Cosmos Transfer — 実クリップの天候・条件拡張 | GPU（`ml.g5.12xlarge`） |
| **M6** | 5 (ext) | Cosmos Predict — 合成シナリオ（video2world）生成 | GPU（`ml.g5.12xlarge`） |
| **M7** | 6 | Nerfstudio 3D 再構成 — NeRF / 3D Gaussian Splatting（オプション/デモ） | `ml.g5.xlarge`（GPU） |
| **M8** | 7 | Cosmos Reason LoRA SFT — nuScenes の**人手ラベル**でパラメータ効率ファインチューニング | GPU（`ml.g5.12xlarge`、4× 24 GB でネイティブ解像度を実測） |
| **M9** | 7 | Alpamayo VLA — **Alpamayo-1.5-10B** による Vision-Language-Action 推論 + 軌道生成 | GPU（`ml.g5.12xlarge`） |
| **M10** | 8 | AlpaSim クローズドループ評価 — 本物のクローズドループポリシー評価を可視化 | `ml.t3.medium`（CPU）+ GPU EC2 |
| **M11** | — (ext) | パイプライン自動化 — 本物の SageMaker Pipeline（Caption→Curate→Augment） | `ml.t3.medium`（CPU）+ 処理ジョブ |
| **M12** | — (ext) | HyperPod 分散学習 — 本物の 2 ノード `torch.distributed` DDP ジョブ | `ml.t3.medium`（CPU）+ ジョブノード |

推奨の進め方: **M0 → M1 → M2 → M3** の順に進み、その後は合成データ（M5/M6）、ポリシー + シミュレーション（M9/M10）、検索（M4）、本番パターン（M12/M11）へと分岐します。表示されているインスタンスはダッシュボードのデフォルト値であり、各 GPU モジュールには代替インスタンスも用意されています（ダッシュボードはデプロイ先リージョンが販売するタイプのみを提示し、クォータ 0 のタイプは拒否します）。

上記の AWS ブログ記事で説明されている **8 ステージのパイプライン**に各モジュールがどう対応するかは、[参加者向け事前学習ガイド § 2「8 ステージのパイプライン（とモジュールの対応関係）」](PRE_LEARNING_GUIDE.md#the-8-stage-pipeline)を参照してください。

---

## インストール前のプレビュー

デプロイする前に、このラボが何を生成するのか見てみたいですか？

**実行済みノートブックの結果。** [`examples/notebooks-with-outputs.tar.gz`](https://github.com/aws-samples/kr-tech-blog-sample-code/raw/main/av3.0-blueprint-lab/examples/notebooks-with-outputs.tar.gz) には、13 個のモジュールノートブック（M0–M12）すべてが `ap-northeast-2` の `ml.g5.12xlarge` での一気通貫の実行後の**出力セル付き**で含まれています — グラフ 11 点、再生可能な H.264 埋め込み動画 3 点（M5・M6・M10）、メトリクス、ログ。すべてのコードセルに実行番号があり、エラー出力は 1 つもありません。ダウンロードして任意の Jupyter ビューアーで開けば、**インストールも実行もせずに**各モジュールの実際の結果を確認できます。実行時点のヘルパースクリプト 8 本も `scripts/` に同梱されています。（AWS アカウント ID は `<aws-account-id>` に置換し、取得した出力の他の内容は書き換えていません。）

```bash
curl -L -O https://github.com/aws-samples/kr-tech-blog-sample-code/raw/main/av3.0-blueprint-lab/examples/notebooks-with-outputs.tar.gz
tar xzf notebooks-with-outputs.tar.gz
```

**エンドツーエンドの検証済み実行記録.** 以下の表は主張ではなく実測値です — すべての数値は実行完了後に
デプロイ済みアカウントから読み取ったものです。

| | |
|---|---|
| リージョン | `ap-northeast-2`（ソウル） |
| インスタンス | `ml.g5.12xlarge` — 4× A10G、合計 96 GB |
| スペースボリューム | 200 GB（ドメインの既定値） |
| 日付 | 2026-09-27 |
| モジュール | **M0 → M12、進捗マーカー 12 個すべて `completed`**、途中停止なし |
| 出力 | 参加者ワークスペースの `m1`–`m12` に 72 オブジェクト（最大は M8 の 154.5 MiB） |

`m10` に専用プレフィックスが無いのは意図的です — M10 は管理者の `m10-reference/` 評価結果を
可視化するモジュールなので、参加者ごとに書き出すものがありません。

ここに至るには 4 つの前提条件が必要で、いずれも先に実際の失敗として現れました。雑学ではなく
セットアップの一部として扱ってください:

1. **このリージョンでの** `hf-cache/` の投入（README ステップ 6b）。無いと M5/M6/M9 は gated repo
   の拒否により `torchrun` 開始から数秒で停止します。
2. 200 GB のスペースボリューム。従来の 5 GB 既定値は Cosmos のビルド中に枯渇します。
3. M2/M4/M8 の `USE_TF=0`（M2・M8 は `USE_TORCH=1` も設定）— transformers のインポート連鎖から
   TensorFlow を除外します。M4 をデバッグするときは `USE_TORCH` ではなく `USE_TF` で grep して
   ください。M4 は `USE_TF=0` + `USE_FLAX=0` のみを設定し、`USE_TORCH` は設定しません。
4. M7 がアプリセッションの残り全体で `protobuf` をダウングレードすること（M7 が自ら出力します）。

**管理者ダッシュボード。** 管理者はここで参加者を追加・削除します。各行の **Dashboard Link → Copy link** をクリックすると、その参加者専用のダッシュボード URL がコピーされて配布できます。読み取り専用の **Region** 列には、そのプロファイルがプロビジョニングされたリージョンが記録されます — Studio ドメインはリージョンごとに存在するため、この列がないとリージョンを誤って割り当てられた参加者も正常に見えてしまいます。**Sessions** タブは 30 秒ごとに更新され、**Costs** タブは直近 14 日間の日次コストを表示します。

![管理者ダッシュボード](../images/admin-dashboard.png)

**参加者ダッシュボード。** 各参加者は自分のダッシュボードを開いて SageMaker ワークスペースを起動し、ノートブックを実行します。パイプラインマップは 12 個のモジュールを INGEST → CURATE → AUGMENT → TRAIN → VALIDATE の 5 つのフェーズ列に配置し、各モジュールを Completed / In Progress / Locked で示し、あるモジュールの出力が別のモジュールへ渡る箇所には矢印を描きます。JupyterLab ワークスペースは 1 つで全モジュールを兼ねるため、参加者は次のノートブックに必要なインスタンス（CPU または GPU）にワークスペースを切り替えて起動し、ワークスペースを開いてノートブックを実行します。

![参加者ダッシュボード](../images/participant-dashboard.png)

---

## どのドキュメントを読むべきか

完全なガイドは **`docs/<lang>/`** 配下に **English / 한국어 / 日本語** で用意されています（以下のリンクはこの言語ディレクトリ内のドキュメントを指します。ページ上部の言語スイッチャーで言語を切り替えられます）:

| あなたは… | 読むもの（順番に） |
|---|---|
| **管理者 — ラボのセットアップ** | [PREREQUISITES](PREREQUISITES.md) → [ADMIN_GUIDE](ADMIN_GUIDE.md) → [DATA_CONTRACT](DATA_CONTRACT.md) |
| **参加者** | [PRE_LEARNING_GUIDE](PRE_LEARNING_GUIDE.md) → [PARTICIPANT_GUIDE](PARTICIPANT_GUIDE.md) |
| **モジュール別の詳細解説** | [COSMOS_M5_M6](COSMOS_M5_M6.md) · [ALPAMAYO_M9](ALPAMAYO_M9.md) · [ALPASIM_M10](ALPASIM_M10.md) · [HYPERPOD_M12](HYPERPOD_M12.md) · [PIPELINE_M11](PIPELINE_M11.md) |
| **M10 GPU / SSM（応用）** | [M10_MANUAL_TEST_RUNBOOK](M10_MANUAL_TEST_RUNBOOK.md)（管理者向け） · [M10_PARTICIPANT_SSM_RUNBOOK](M10_PARTICIPANT_SSM_RUNBOOK.md)（参加者向け） |

---

## 前提条件

| 要件 | バージョン | 備考 |
|---|---|---|
| AWS アカウント | — | SageMaker、S3、DynamoDB、Cognito、CloudFront へのアクセス権を持つこと |
| AWS CLI | v2.x | 設定済みであること（`aws sts get-caller-identity`） |
| Node.js | 18+ | CDK CLI + フロントエンドビルド |
| Python | 3.12+ | CDK インフラストラクチャコード |
| AWS CDK | 2.x | `npm install -g aws-cdk` |
| jq | — | デプロイスクリプト内での JSON パース |
| Hugging Face トークン | — | **管理者のみ** — ゲート付きモデル（M2/M5/M6/M9）を事前キャッシュし、M10 のリファレンス評価を実行します。**参加者に HF トークンは不要です。** [docs/ja/PREREQUISITES.md](PREREQUISITES.md) を参照してください。 |
| NGC API キー | — | **管理者のみ、M10 のみ** — AlpaSim NuRec レンダラーイメージ用。 |

### サービスクォータ（早めに申請 — 24〜48 時間のリードタイム）

GPU **Studio JupyterLab App** のクォータは、新規アカウントではデフォルトで低い値または **0** になっています。ワークショップの前に増加申請してください。M12/M11 用には別途**ジョブ**クォータもあり、見落としがちなので注意してください。完全な表と CLI コマンドは **[docs/ja/ADMIN_GUIDE.md](ADMIN_GUIDE.md)** および **[docs/ja/PREREQUISITES.md](PREREQUISITES.md)** にあります。

現在の値を確認する:
```bash
aws service-quotas list-service-quotas \
  --service-code sagemaker --region "${AWS_REGION:-us-west-2}" \
  --query 'Quotas[?contains(QuotaName, `Studio JupyterLab Apps`) || contains(QuotaName, `for training job`) || contains(QuotaName, `for processing job`)].{Name:QuotaName,Value:Value,Code:QuotaCode}' \
  --output table
```

---

## クイックスタート

すべてのコマンドは、アカウントとリージョンを環境から導出します。ハードコードされている値はありません。

```bash
# 1. クローン
git clone https://github.com/aws-samples/kr-tech-blog-sample-code.git
cd kr-tech-blog-sample-code/av3.0-blueprint-lab

# 2. 必須の環境変数
export ADMIN_EMAIL="<admin-email>"           # 例: you@example.com
export REGION="us-west-2"                     # デプロイ先の唯一のリージョン
export AWS_REGION="$REGION"                   # 下のシーディングスクリプトが使用                 # デフォルト。「リージョンの選択」を参照
export HF_TOKEN="hf_..."                      # 管理者の Hugging Face 読み取りトークン
# 任意だが推奨: 管理者ダッシュボードへのアクセスを自分の IP/CIDR に制限する
export ADMIN_IP_ALLOWLIST="203.0.113.0/24"    # デフォルト 0.0.0.0/0 = WAF は全開放

# 2b. Hugging Face 上でゲート付きモデル/データセットのライセンスに同意する（ステップ 6 の前に）。
#     huggingface.co にログインし、各ゲート付きリポジトリで "Agree and access repository" を
#     クリックする — 完全なリストは docs/ja/PREREQUISITES.md にあります。

# 3. CDK のブートストラップ（アカウント + リージョンごとに 1 回）
cd infra && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
npx cdk bootstrap "aws://$(aws sts get-caller-identity --query Account --output text)/$REGION"
cd ..

# 4. インフラストラクチャ + ダッシュボードのデプロイ（約 25 分）
./scripts/refresh_instance_rates.py --region "$REGION" --merge   # 必須: このリージョンの料金表を生成
./scripts/deploy.sh --region "$REGION"

# 5. 最初の Cognito 管理者ユーザーを作成
#    （deploy.sh が、あなたのプール ID を含む正確なコマンドを出力します。ユーザー名は必ずメールアドレスにすること）
aws cognito-idp admin-create-user \
    --user-pool-id <cognito-pool-id> \
    --username "$ADMIN_EMAIL" \
    --user-attributes Name=email,Value="$ADMIN_EMAIL" Name=email_verified,Value=true \
    --temporary-password 'TempPass1!' \
    --region "$REGION"

# 6. NVIDIA モデルを S3 に事前キャッシュ（バックグラウンド、30〜60 分）
AWS_REGION="$REGION" ./scripts/cache_models.sh
#    このスクリプトは model-cache/ のみ（M2、M8）を投入します。M5/M6/M9 が読む
#    HuggingFace オフラインキャッシュは投入しません。6b は任意ではありません。

# 6b. HuggingFace オフラインキャッシュの投入 — M5、M6、M9、M10 に必須。
#     2 つの経路があり、どちらも実行可能なコマンドです。既存の seeded リージョンの有無で選択:
#  すでに別リージョンでラボを運用している場合（2 つ目以降の一般的なケース）:
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
SEEDED=us-west-2                      # ラボが既に動作しているリージョン
aws s3 sync "s3://av30lab-shared-data-$ACCOUNT-$SEEDED/hf-cache/" \
            "s3://av30lab-shared-data-$ACCOUNT-$REGION/hf-cache/" \
            --source-region "$SEEDED" --region "$REGION"       # 約 115 GiB、25〜55 分
aws s3 sync "s3://av30lab-shared-data-$ACCOUNT-$SEEDED/m10-reference/" \
            "s3://av30lab-shared-data-$ACCOUNT-$REGION/m10-reference/" \
            --source-region "$SEEDED" --region "$REGION"
#     hf-cache/hub/ ではなく hf-cache/ を同期してください — さもないとツリーが 1 階層
#     深く入れ子になり（hub/hub/）、M9 のデモクリップが誤った場所に置かれます。
#  最初のリージョンなら（コピー元がない） — 固定マニフェストからツリーを構築します。
#  GPU もノートブック実行も不要、スクラッチ約 65 GiB と 30〜60 分:
AWS_REGION="$REGION" HF_TOKEN="$HF_TOKEN" ./scripts/cache_hf_tree.sh
#     トークンなしで取得内容を確認:  ./scripts/cache_hf_tree.sh --dry-run
#     M9 は追加でデモクリップが必要です — ADMIN_GUIDE.md §6.3。
#
# 6c. 検証 — 参加者を作成する前に必ず exit 0 になること。6b を飛ばすと
#     M5/M6/M9/M10 が動かないリージョンができ、他のすべての検査は緑のままです。
./scripts/check_seeding.sh --region "$REGION"

# 7. nuScenes-mini データセットを S3 にステージング（M1 / M3 / M7 で必須）
AWS_REGION="$REGION" ./scripts/stage_nuscenes.sh
#    公開の AWS Open Data ミラーから取得します（ログイン不要。nuScenes の利用規約が適用されます）。

# 8. ノートブックテンプレート + ヘルパースクリプトを共有バケットにアップロード
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
aws s3 sync notebooks/ "s3://av30lab-shared-data-$ACCOUNT-$REGION/notebook-templates/" --region "$REGION"
aws s3 sync scripts/   "s3://av30lab-shared-data-$ACCOUNT-$REGION/notebook-templates/scripts/" --region "$REGION"
```

その後、`deploy.sh` が出力した **Admin Dashboard URL** を開き、ステップ 5 のメールアドレス + 仮パスワードでログインし、テストユーザーをプロビジョニングして、**Participant Dashboard Link** を開いてパイプラインマップを確認します。日ごとの完全なランブック — スモークテスト、一括プロビジョニング、モニタリング、撤去 — は **[docs/ja/ADMIN_GUIDE.md](ADMIN_GUIDE.md)** にあります。

---

## アーキテクチャ

```
        CloudFront (2x)  ─────────  Admin Dashboard  |  User Dashboard
              │                              │
        S3 static (admin)               S3 static (user)
              │
        API Gateway + Lambda  ── create_user, delete_user, bulk_provision,
              │                    list_sessions, terminate_session,
              │                    change_instance, get_costs, update_progress, …
   ┌──────────┼───────────────────────────────┐
 Cognito   DynamoDB                    SageMaker Studio Domain
 (auth)    (sessions,                  └─ per-user profile + JupyterLab space
            progress)                        │
                                       S3 shared-data bucket
                                        (model-cache / datasets / hf-cache /
                                         notebook-templates / m10-reference)
```

- **ネットワーク:** NAT なしの VPC — 分離プライベートサブネット ＋ 無料の S3 *ゲートウェイ* エンドポイント。
  **NAT Gateway はありません。** Studio ドメインは `PublicInternetOnly` なので、ノートブックの
  トラフィックは SageMaker マネージド VPC を経由し、この VPC は EFS/ホームディレクトリの
  トラフィックのみを扱います。有料の *インターフェース* エンドポイント 6 種はデフォルトで無効です
  （VPC 内に利用者がいません — Lambda は VPC に接続されていません）。ドメインを `VpcOnly` に
  切り替える場合は `-c vpc_interface_endpoints=true` で有効化してください。
- **ストレージ:** KMS 暗号化 S3（共有データ + ユーザーごとのワークスペース）、事前キャッシュされたモデル。
- **コンピュート:** 自動セットアップ用のライフサイクル設定を持つ SageMaker Studio ドメイン。
- **認証:** 管理プレーン用のオプションの **WAF IP 許可リスト**を備えた Cognito ユーザープール。
- **API:** ユーザー管理、セッション、進捗管理のための Lambda ベースの REST API。
- **モニタリング:** CloudWatch アラーム、SNS 通知、日次の予算アラート。
- **フロントエンド:** CloudFront 上の React SPA（管理者ダッシュボード + ユーザーパイプラインマップ）。

---

## プロジェクト構成

```
av3.0-blueprint-lab/
├── infra/                  # AWS CDK app (Python): stack, constructs, Lambdas
│   ├── app.py  cdk.json  requirements.txt
│   ├── stacks/av30_stack.py
│   ├── av30_constructs/    # network, storage, database, sagemaker, auth, api, dashboards, monitoring
│   └── lambda/             # create_user, delete_user, bulk_provision, change_instance, get_costs, update_progress, …
├── notebooks/              # 13 workshop notebooks M0–M12
├── web/
│   ├── admin/              # Admin dashboard (React + Vite)
│   └── user/               # Participant pipeline map (React + Vite)
├── scripts/                # deploy.sh, teardown.sh, cache_models.sh, stage_nuscenes.sh,
│                           # setup_*.sh, alpasim_ec2_setup.sh, grab_gpu_instance.py, …
├── docs/{en,ko,ja}/        # Full trilingual documentation set
├── LICENSE                 # MIT-0 (workshop code)
├── NOTICE                  # third-party model/dataset licenses (incl. non-commercial)
└── README.md               # this file
```

---

## コストとクリーンアップ

| シナリオ | コスト | 備考 |
|---|---|---|
| アイドル状態（インフラのみ） | **リージョンあたり約 $1/月** | KMS キー。S3 ゲートウェイエンドポイントは無料で、NAT Gateway はありません。DynamoDB（オンデマンド）・CloudFront・Cognito はアイドル時ほぼ $0。VPC インターフェースエンドポイント 6 種を有効にした場合のみ **リージョンあたり約 $87.60/月** が加算されます（ENI 12 個 × $0.01/AZ・時間）。モデルキャッシュの S3 保管料は別途（リージョンあたり約 $2/月）。 |
| GPU モジュール | 時間課金 | `ml.g5.xlarge` 約 $1.41/時（M7）、`ml.g5.12xlarge` 約 $7.09/時（M2/M3）、`ml.g5.12xlarge` は M5/M6/M8/M9 のデフォルトでもあります。フル解像度の出力には GPU あたり ≥38 GB が必要です: `ml.g7e.2xlarge` 約 $4.20/時 が最も安価な経路（96 GB 1 枚 — デフォルトより安価だが、クォータの初期値は 0 で、このラボでは未検証）、それ以外は `ml.p4d.24xlarge` 約 $25.25/時 |
| M10 AlpaSim（EC2 上） | 約 $30 の一度きり（管理者） | `g6e.12xlarge` でのリファレンス評価。任意で参加者が自身で実行する場合は約 $10.5/時/ホスト |
| 1 週間フル（混在） | 約 $400〜600+ | p4d モジュールとユーザー数が支配的 |

**コスト管理:** 日次予算アラーム（SNS → `<admin-email>`）、Sessions タブからの管理者による強制終了、JupyterLab アプリのアイドル自動停止（デフォルト 90 分。`-c idle_timeout_minutes=<60..180>`）。**撤去:** `scripts/teardown.sh`（デフォルトはドライラン。`--yes`、`--user <id>`、`--destroy`）は、ユーザーごとのアプリ/スペース/プロファイルを削除し、孤立した OpenSearch Serverless コレクションを一掃し、タグ付けされた GPU EC2 ホストを終了します。イベント終了後は、**管理者の HF トークンを失効させ、NGC キーをローテーション**してください。詳細は [docs/ja/ADMIN_GUIDE.md](ADMIN_GUIDE.md) にあります。

---

## リージョンの選択

リージョンはデプロイごとに `./scripts/deploy.sh --region <region>` で選択します — **一度に 1 リージョン**。
後から別リージョンを追加する場合は [docs/en/ADDING_A_REGION.md](../en/ADDING_A_REGION.md) を参照してください。

GPU タイプが使えるかは**異なる 2 つの事実**で決まりますが、以前の表は両者を混同していました —
このアカウントは us-east-1 で `ml.p5.48xlarge` のクォータが 0 なのに利用可能と表示し、
可能なリージョンが 3 つだけのように見せていました（実際には p5 のクォータは 10 リージョンに存在）。

1. **そのリージョンが Studio-JupyterLab 用に販売しているか？** リージョンごとの実測生成値
   （`$/hr`、`—` = 非販売）:

   | リージョン | g5.12xlarge | g5.24xlarge | g6.24xlarge | g7e.2xlarge | p4d.24xlarge | p5.48xlarge |
   |---|---|---|---|---|---|---|
   | us-west-2 | $7.09 | $10.18 | $8.34 | $4.20 | $25.25 | $63.30 |
   | us-east-1 | $7.09 | $10.18 | $8.34 | $4.20 | $25.25 | $63.30 |
   | ap-northeast-1 | $10.28 | $14.76 | $12.10 | — | $34.61 | $79.12 |
   | ap-northeast-2 | $8.72 | $12.52 | $10.26 | — | $34.97 | — |
   | eu-west-1 | $7.92 | $11.36 | — | — | $27.27 | — |

   再生成／リージョン追加: `./scripts/refresh_instance_rates.py --region <region> --merge`
   生成されていないリージョンでは Lambda が import 時に例外を発生させます（他リージョンの
   価格を黙って引用しないため）。

2. **自分のアカウントがそのリージョンで、参加者数ぶんのクォータを持っているか？**
   クォータのスコープは `(アカウント × リージョン)` であり、あるリージョンの増枠は他リージョンには
   適用されません。大きな GPU タイプの既定値は 0 のことが多いです:

   ```bash
   ./scripts/check_quotas.py --region <region> --participants 10
   ```

   料金表・ライブクォータ・各モジュールの推奨インスタンスを相互照合します。このアカウントの実測:
   us-west-2 と ap-northeast-2 はどちらも推奨タイプすべてを**同時 5 名**まで実行でき、10 名では
   どちらも通りません — 両リージョンの上限が同じく `ml.g5.12xlarge`/`ml.g5.xlarge` のクォータ 5 だからです。
   ap-northeast-2 は `ml.g6` ファミリー全体がクォータ **0** で、`ml.g7e.*`/`ml.p5.*` はそもそも
   販売されていません — ダッシュボードの推奨値に `g6` タイプが 1 つもないのはこのためです。

S3 モデルキャッシュのパスはリージョンローカルです — デプロイしたリージョンにデータを配置してください
（`AWS_REGION=<region> ./scripts/cache_models.sh`; スクリプトはリージョンを推測しません）。

---

## ライセンス

このリポジトリ内の**ワークショップコード**（CDK インフラ、Lambda、ノートブック、ダッシュボード、スクリプト）は **MIT-0** ライセンスの下で提供されます — [LICENSE](../../LICENSE) を参照してください。

ノートブックがダウンロードする**モデルおよびデータセット**は、そのライセンスの対象**ではなく**、ここでは**再配布されません**。それぞれが独自の規約を保持しています — 特に <strong>Alpamayo-1.5-10B（M9/M10）は商用利用不可（研究/評価目的のみ）</strong>であり、**nuScenes** も商用利用不可です。適用されるすべてのライセンスを確認し、遵守してください。完全なリストは [NOTICE](../../NOTICE) を参照してください。
