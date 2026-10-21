# AV 3.0 Blueprint Lab — 管理者ガイド

ワークショップ管理者がイベントの**前・最中・後**に行うすべての作業を、実際に行う
順序で説明します。参加者はダッシュボードのリンクだけあれば十分です（
[PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md) を参照）。それ以外はすべて管理者の責任です。

> **黄金律:** 重い処理、ゲート付き、GPU、認証情報にまつわる作業はすべて管理者が担います。
> 以下の事前チェックリストを完了すれば、参加者は **AWS アカウントなし、Hugging Face トークンなし、
> ライセンス同意クリックなし**でブラウザから M0–M12 を実行できます
> （唯一の例外はオプションの M10 セルフラン — §7 を参照）。

---

## 0. あなたが運用するもの

- **1 つの CDK スタック** (`Av30PlatformStack`) → VPC、KMS で暗号化された S3（共有 + ユーザー
  ごとのワークスペース）、DynamoDB、Cognito、WAF、API Gateway + Lambda、2 つの CloudFront ダッシュボード
  （管理者用 + ユーザー用）、そして参加者全員が**1 つの**実行ロール
  `av30lab-sagemaker-execution-role` を共有する SageMaker Studio ドメイン（ユーザーごとの
  ロールではありません）。参加者間の分離は、スペースの所有者を
  `${sagemaker:UserProfileName}` と比較する IAM 条件によって行われます —
  `infra/av30_constructs/sagemaker.py` の残存リスクの注記を参照してください。
- **2 つの S3 バケット**（名前は**あなたの**アカウント + リージョンから導出されます。本ガイドの
  例ではリファレンスデプロイであるアカウント `<aws-account-id>` / `us-west-2` を使用しています。
  ご自身の値に置き換えてください — §1.5 を参照）:
  - `av30lab-shared-data-<account>-<region>` — モデル、データセット、ノートブックテンプレート、M10 リファレンス。
  - `av30lab-user-workspace-<account>-<region>` — 参加者ごとに 1 つの `users/<id>/` プレフィックス。

> **本ガイドの ID に関する注記。** `<aws-account-id>` や `us-west-2` を目にする箇所
> （バケット名、ARN、クォータの「Current」値、CLI 例）はすべて、リファレンスデプロイの値です。
> これらはスタックに**ハードコードされていません** — アカウントはあなたの認証情報から、
> リージョンはデプロイ時（§5）の `$AWS_REGION` から取得されます。§1.5 でご自身の値を選び、
> 例はその値に置き換えて読んでください。
- **12 個のノートブック M0–M12**。ほとんどは参加者のセルフサービスですが、いくつかは一度だけ
  管理者の事前作業（モデル、データセット、M10 リファレンスラン）を必要とします。§4 のマトリクスを参照。

---

## 1. イベント前のタイムライン

| いつ | タスク | リードタイムの理由 |
|---|---|---|
| **Day −7** | GPU + ジョブのクォータ引き上げを申請（§2） | 承認に 24–48 時間、時にはそれ以上かかる |
| **Day −7** | 管理者アカウントですべてのゲート付き HF ライセンスに同意（§3） | 即時だが、1 つ忘れやすい |
| **Day −3** | `cdk bootstrap` + `deploy.sh`（§5） | 約 25 分。問題修正の余裕を残す |
| **Day −3** | nuScenes のステージング + モデルの事前キャッシュ + HF オフラインキャッシュ（§6） | バックグラウンド転送に 30–90 分 |
| **Day −2** | M10 を使う場合、EC2 で M10 AlpaSim リファレンス評価を実行（§6.4） | 約 $30、GPU マシンで数十分〜2 時間 |
| **Day −1** | ノートブックテンプレートのアップロード、1 ユーザーをエンドツーエンドでスモークテスト（§8） | プロビジョニング/クォータの不足を検出 |
| **Day 0** | 参加者のプロビジョニング、ダッシュボードリンクの配布（§9）、監視（§10） | — |
| **Day +0** | ユーザーの削除、**HF トークンの無効化、NGC キーのローテーション**（§12） | セキュリティ衛生 |

---

## 1.5. AWS アカウントとリージョンの選択（まずこれを行う）

このプラットフォームは**アカウント・リージョンに依存しません** — スタック内でリファレンス
アカウント（`<aws-account-id>`）やリージョン（`us-west-2`）を固定している箇所はありません。
すべてはデプロイ時に導出されます。**アカウント**はあなたの AWS 認証情報から、**リージョン**は
§5 でエクスポートする `AWS_REGION` から取得されます。GPU クォータとゲート付きモデルの提供状況は
アカウントごと**かつ**リージョンごとなので、クォータを申請する（§2）前に両方を決めてください。

**アカウントの選択**
- あなたが**管理者権限を持つ**アカウント（またはロール、Cognito プール、CloudFront、VPC、
  SageMaker ドメインを作成する IAM 権限を持つアカウント）を使用してください。`deploy.sh` は
  `cdk bootstrap` を実行し、これはアカウント + リージョンごとに一度だけ昇格した権限を必要とします。
- **専用 / サンドボックス**アカウントを推奨します: スタックは Studio ドメイン、バケット、WAF を
  作成し、ティアダウン（`scripts/teardown.sh`）は無関係な本番リソースとアカウントを共有していない
  ときが最もクリーンです。
- `deploy.sh` を実行したときに認証情報が指しているアカウントが、デプロイ先になります。
  デプロイ前に確認してください:
  ```bash
  aws sts get-caller-identity --query Account --output text
  ```
  このアカウント ID が、すべてのバケット名と ARN の `<account>` を埋めます。

**リージョンの選択** — こちらはアカウントよりも重要です。GPU 容量とモデルアクセスを左右するためです:
- **GPU の提供状況はリージョンによって異なります。** このラボが使う GPU ファミリー（`g5`、
  `g6`、オプションで `p4d`/`p5`）は**すべての**リージョンにあるわけではなく、クォータ承認は
  リージョンごとです。GPU 容量の潤沢なリージョンを選んでください — `us-west-2`（オレゴン）と
  `us-east-1`（バージニア北部）が最も安全です。**特に `ml.p5.48xlarge` は
  いくつかのリージョン（us-west-2 / us-east-1）でしか提供されていません。**
- **レイテンシ:** インタラクティブな Studio UI では参加者に近い方が快適ですが、
  容量を優先すべきです — GPU を確保できないリージョンは役に立ちません。
- **データレジデンシー / 組織ポリシー:** 組織がリージョンを制限している場合は、上記の GPU
  ファミリーを持つ準拠リージョンを選んでください。
- **モデル + データセットのステージングはリージョンローカルです。** HF/モデルキャッシュと nuScenes は
  **選択したリージョン内の**共有バケットにステージングされます（§6）。後でリージョンを移す場合は
  再ステージングが必要です（`README.md` の「Region portability」の注記を参照）。

コミットする前に、**候補リージョンが必要な容量を持っているか検証**してください（あるファミリーの
出力が空なら、そのリージョンでは提供されていません）:
```bash
export AWS_REGION="us-west-2"     # your candidate
# GPU instance types offered for SageMaker Studio apps in this region:
aws service-quotas list-service-quotas --service-code sagemaker --region "$AWS_REGION" \
  --query "Quotas[?contains(QuotaName,'Studio JupyterLab Apps running on ml.g6') || contains(QuotaName,'Studio JupyterLab Apps running on ml.g5')].{Name:QuotaName,Current:Value,Code:QuotaCode}" \
  --output table
```

アカウント + リージョンが決まったら、`AWS_REGION` をエクスポートし（§5 全体で使用します）、
**そのリージョンで** §2 のクォータを申請し、**そのリージョンで**キャッシュをステージング
してください（§6）。どちらかを後で変更すると、再ブートストラップ、クォータ再申請、
再ステージングが必要になります — 今のうちに確定させてください。

---

## 2. サービスクォータ（Day −7 に申請）

2 系統のクォータが重要です。README のクォータ表が 1 つ目をカバーしています。以下の
**ジョブクォータ**は見落としやすく、部屋全体で M12/M11 をブロックします。

### 2a. Studio JupyterLab App クォータ（インタラクティブノートブック）
Service Quotas コンソールで「**Studio JupyterLab Apps running on**」を検索します。これらは
**ユーザーダッシュボードの Instance Options** が実際に提示するインスタンスタイプ（推奨 +
代替）であり、参加者はこのセットからしか選べません — 以下のクォータはそのすべてをカバーします。
クォータ**コードはリージョンに依存しません**（us-west-2 / ap-northeast-2 / eu-west-1 で同一と確認済み）。
しかし**値は依存します**し、そもそもどのタイプにクォータが存在するかもリージョンごとに異なります。

**GPU 主力機: `ml.g5.12xlarge`（4× A10G、96 GB）。** ダッシュボードが現在 M2、M3 と重量級の
4 モジュール（M5、M6、M8、M9）に推奨するタイプで、根拠はすべて実測です。`ml.g6.24xlarge` と
形状が*同一*であり（`describe-instance-types` はどちらも 4 GPU × 22,888 MiB と報告するため、
GPU あたり VRAM のゲートはすべて同じ分岐を通ります）、両リージョンで安く（us-west-2 は
$7.09 対 $8.34、ap-northeast-2 は $8.72 対 $10.26）、クォータも高く（us-west-2 は 5 対 2、
ap-northeast-2 は 5 対 **0**）、そしてラボが捕捉した合格実行から到達できるファミリーです。何が実測かを正確に書きます。
`examples/notebooks-with-outputs.tar.gz` には現在、**4× NVIDIA A10G**（すなわち g5.12xlarge
そのもの）で実行した M0–M12 の全区間の実行が含まれ、M9 は minADE 0.3779、`Status: PASS`
です。したがってこのインスタンス自体が直接の実測であり、もはや形状の論証に依存しません。
（以前のバンドルは同じパイプラインを **4× NVIDIA L4** で M9 minADE 0.3805 として記録し、
`docs/en/ALPAMAYO_M9.md:181-187` は M9 の **8× A10G**（g5.48xlarge）合格を別に記録して
います。どちらも実測のままで、単に公開バンドルの内容ではなくなっただけです。）その実行が
残した注意点が 1 つ: M7 の novel-view レンダーは `rc=1` で終了し**フレーム 0 枚**でした —
学習は完了、レンダーは未完了です。g5.12xlarge を選ぶ理由はクォータと価格です。
p4d/p5 は、クォータがある場合のネイティブ解像度 / フル 720p パスとして残ります。

> **下記の `us-west-2` 列はあなたのリージョンではありません。** クォータは（アカウント × リージョン）
> 単位の事実です: `ml.g6.*` ファミリーは ap-northeast-2 で販売されていますがクォータは **0** で、
> `ml.g7e.*`/`ml.p5.*` はそもそも販売されていません。実際の値は
> `./scripts/check_quotas.py --region <対象>` で確認してください — 不足ごとに正確な
> `request-service-quota-increase` コマンドを出力します。（クォータ 0 のタイプは、受理された後に
> 起動失敗するのではなく、ダッシュボードが手前で拒否するようになりました。）

| インスタンス | クォータコード | us-west-2 (2026-09) | 10 人の部屋に必要な最小値 | ダッシュボードでの役割 |
|---|---|---|---|---|
| ml.t3.medium | L-71FAF417 | 2500 | ≥20 | すべての CPU ノートブック（M0, M1, M10, M4, M12, M11）に**推奨** |
| ml.t3.large | L-2733D4D5 | 30 | ≥0 | CPU 代替 |
| ml.t3.xlarge | L-61F9C762 | 30 | ≥0 | CPU 代替（M1） |
| ml.m5.large | L-3BDCD216 | 11 | ≥0 | CPU 代替 |
| ml.m5.xlarge | L-77B8159A | 11 | ≥0 | CPU 代替（M12） |
| ml.g5.xlarge | L-988CE6C5 | 5 | ≥5 | M7（Nerfstudio）に**推奨** |
| ml.g5.2xlarge | L-F73C7DB9 | 5 | ≥0 | M7 代替 |
| ml.g5.4xlarge | L-81940D85 | 5 | ≥0 | M7 代替 |
| **ml.g5.12xlarge** | **L-8D2ED7BF** | **5** | **≥5** | **推奨主力機 — M2、M3、M5、M6、M8、M9（4× A10G、96 GB）** |
| ml.g5.24xlarge | L-F087CCFC | 2 | ≥1 | M2/M3/M5–M9 代替 |
| ml.g5.48xlarge | L-83AB5D73 | 2 | ≥1 | M2/M3/M5–M9 代替 / OOM フォールバック |
| ml.g6.xlarge | L-AABA5942 | 5 | ≥0 | M7 代替（L4） — **ap-northeast-2 では 0** |
| ml.g6.2xlarge | L-92D1521D | 5 | ≥0 | M7 代替（L4） — **ap-northeast-2 では 0** |
| ml.g6.4xlarge | L-692B8304 | 5 | ≥0 | M7 代替（L4） — **ap-northeast-2 では 0** |
| ml.g6.12xlarge | L-962247BA | 2 | ≥0 | M2/M3 の容量フォールバック（4× L4、96 GB） — **ap-northeast-2 では 0** |
| ml.g6.24xlarge | L-8ACE1754 | 2 | ≥0 | M2/M3/M5–M9 代替（4× L4、96 GB） — g5.12xlarge と同形状だが高価; **ap-northeast-2 では 0** |
| ml.g6.48xlarge | L-125B7142 | 2 | ≥0 | M5/M6/M9 代替（8× L4） — **ap-northeast-2 では 0** |
| ml.g7e.2xlarge | L-7A3E0A2C | **0** | ≥0 | M2/M3/M5–M9 の**最も安価なネイティブ解像度パス**（RTX PRO 6000 1 枚、96 GB; **デフォルトは 0 — 申請が必要**） |
| ml.g7e.24xlarge | L-E481E4F8 | **0** | ≥0 | M5/M6/M9 代替（RTX PRO 6000 4 枚; **デフォルトは 0**） |
| ml.p4d.24xlarge | L-AD63F1D2 | 2 | ≥2 | M5, M6, M9 のネイティブ解像度パス（8× A100; **デフォルトは 0 — 申請が必要**） |
| ml.p5.48xlarge | L-B41FBF28 | 1 | ≥0 | 重量モデルのフォールバック（8× H100; **ap-northeast-2 では未販売**） |

> **g7e は任意であり、このラボでは未検証です。** このアカウントの `us-west-2` では
> 6 つの `ml.g7e.*` Studio クォータがすべて **0** です（`list-service-quotas` で
> 確認）。引き上げを申請するまで誰も選択できません。掲載している理由は、
> ネイティブ解像度ティアへの *最も安価な* 経路だからです — 96 GB カード 1 枚が
> 時間あたり約 $4.20 で、`ml.p4d.24xlarge`（約 $25.25/時）より安く、24 GB の
> デフォルト（約 $8.34/時）も下回ります。ただし **このラボで g7e 上でエンドツー
> エンド実行したモジュールはありません。** クォータを取得したら、部屋全体に案内する
> 前にユーザー 1 名で M5 をスモークテストしてください。他の g7e サイズ
> （4xl/8xl/12xl/48xl）にもクォータコードがあります（L-B7228EBF, L-0407753C,
> L-5F015F52, L-A48244DF）が、ダッシュボードには表示されません。

部屋のサイジング: 各モジュールの**推奨**インスタンスを同時参加者数以上で申請し、案内するつもりの
1〜2 個のフォールバックについては、少なくとも表示された最小値を申請してください（容量エラーが
発生すると、ダッシュボードに代替が表示されます）。すべての代替のクォータは**不要**です —
実際に部屋に案内するものだけです。GPU モジュールを **g5.12xlarge**（推奨 — 重量級モジュールの推奨値のうち、us-west-2 と
ap-northeast-2 の両方で 0 でない唯一のタイプ）に統一する場合は、
それを参加人数以上に申請すれば、p4d/p5 はデフォルトのままで構いません。

### 2b. SageMaker **ジョブ**クォータ（M12 と M11 — 忘れられがちなもの）
M12 は実際の**トレーニングジョブ**を送信し、M11 は（ノートブックのインスタンスとは別の）
別個のマネージドインスタンス上で実際の**処理ジョブ**を実行します。これらには独自の
クォータがあります:

| クォータ | コード | 検証済みの値（リファレンスデプロイ例: us-west-2） | 必要とするもの |
|---|---|---|---|
| **トレーニング**ジョブ使用向け ml.m5.xlarge | L-CCE2AFA6 | 30 | M12（≥2 必要 — 2 ノードジョブ） |
| **処理**ジョブ使用向け ml.m5.xlarge | L-0307F515 | 16 | M11（≥1 必要 — 順次実行の 3 ステップ DAG） |

いずれも今日のワークショップの必要量を余裕で上回っていますが、**検証**してください — どちらかが
あなたのアカウントで 0 の場合、ノートブックは開いても M12/M11 はジョブ送信時に失敗します。
`ml.g5.*` の**処理**ジョブクォータはここでは 0 ですが、M11 は設計上 CPU で実行されるため問題ありません。

```bash
# Check everything at once:
aws service-quotas list-service-quotas --service-code sagemaker --region "$AWS_REGION" \
  --query "Quotas[?contains(QuotaName,'Studio JupyterLab Apps') || contains(QuotaName,'for training job') || contains(QuotaName,'for processing job')].{Name:QuotaName,Value:Value,Code:QuotaCode}" \
  --output table

# Request an increase（ダッシュボードが実際に推奨する 2 タイプを 10 に — 満席想定）:
aws service-quotas request-service-quota-increase \
  --service-code sagemaker --quota-code L-8D2ED7BF --desired-value 10 --region "$AWS_REGION"   # ml.g5.12xlarge
aws service-quotas request-service-quota-increase \
  --service-code sagemaker --quota-code L-988CE6C5 --desired-value 10 --region "$AWS_REGION"   # ml.g5.xlarge
```

> 上記のクォータ**コード**はどのリージョンでも同じです。実際にデプロイする場所で容量を申請できるよう、
> **あなたの** `$AWS_REGION`（§5）に対して実行してください。GPU の提供状況はリージョンによって
> 異なります — 選択については §1.5 を参照。

---

## 3. ゲート付き Hugging Face + NGC ライセンス（Day −7 に同意）

**あなたの管理者 HF アカウント**で、各リポジトリの「Agree and access repository」をクリックします。
ライセンスに同意するのはこの 1 か所だけです — 参加者はこれを目にすることはありません。

| リポジトリ | 必要とするモジュール | ライセンス |
|---|---|---|
| nvidia/Cosmos-Reason1-7B | M2 | NVIDIA Open Model（ゲートなしだがログインが必要） |
| nvidia/Cosmos-Guardrail1 | M5, M6 | NVIDIA Open Model |
| nvidia/Cosmos-Transfer2.5-2B | M5 | NVIDIA Open Model |
| nvidia/Cosmos-Predict2.5-2B | M6 | NVIDIA Open Model |
| nvidia/Alpamayo-1.5-10B | M9, M10 | **非商用**（研究/評価のみ） |
| nvidia/Cosmos-Reason2-8B | M9, M10（隠れた Alpamayo バックボーン） | NVIDIA Open Model |
| nvidia/PhysicalAI-Autonomous-Vehicles | M9（デモクリップ） | NVIDIA AV Dataset（12 か月で失効） |
| nvidia/PhysicalAI-Autonomous-Vehicles-NuRec | M10（AlpaSim シーン） | NVIDIA AV NuRec Dataset |

**M10 は NGC も必要とします**（HF とは別）: NuRec レンダラーイメージ
`nvcr.io/nvidia/nre/nre-ga:26.04`。キーは
`https://org.ngc.nvidia.com/setup/api-key` で取得します。（テストではこのイメージは
匿名でプル可能でしたが、変更に備えてキーを用意しておいてください。）

> すべてに同意したら `export HF_TOKEN=hf_...` を設定してください。§6 で使用します。

---

## 4. モジュールごとの管理者事前作業マトリクス

これが本ガイドの核心です — **どのモジュールが管理者作業を必要とし、どれが自力で動くか。**

| モジュール | コンピュート（参加者が見るもの） | 必要な管理者事前作業 | ドキュメント |
|---|---|---|---|
| M0 概要 | CPU t3.medium | なし | — |
| M1 データ探索 | CPU t3.medium | nuScenes-mini のステージング（§6.1） | — |
| M2 Cosmos Reason | GPU g5.12xlarge（または g6.24xlarge） | モデルを `model-cache/` に事前キャッシュ（§6.2） | — |
| M3 Cosmos Curator | GPU g5.12xlarge（または g6.24xlarge） | （M2 の出力を使用。追加キャッシュなし） | — |
| M4 OpenSearch | CPU t3.medium | （M2 の出力を使用。追加キャッシュなし） | — |
| M5 Cosmos Transfer | GPU g5.12xlarge（または 720p 用に p4d.24xlarge） | HF **オフラインキャッシュ**を `hf-cache/hub/` へ（§6.3） | [COSMOS_M5_M6.md](COSMOS_M5_M6.md) |
| M6 Cosmos Predict | GPU g5.12xlarge（またはネイティブ用に p4d.24xlarge） | HF オフラインキャッシュ（§6.3） | [COSMOS_M5_M6.md](COSMOS_M5_M6.md) |
| M7 Nerfstudio | GPU g5.xlarge（または g6.xlarge） | gsplat CUDA ビルドがセッションごとに `scripts/setup_gsplat_env.sh` で実行される（§11） | 以下の §11 を参照 |
| M8 Cosmos Reason SFT | GPU g5.12xlarge（または g6.24xlarge） | （M2 の `model-cache/cosmos-reason1/` を再利用; 追加キャッシュ不要） | — |
| M9 Alpamayo VLA | GPU g5.12xlarge（または p4d.24xlarge） | HF オフラインキャッシュ **+ デモクリップ**（§6.3） | [ALPAMAYO_M9.md](ALPAMAYO_M9.md) |
| M10 AlpaSim | CPU t3.medium（ビジュアライザー） | **EC2 でリファレンス評価を一度実行**（§6.4） | [ALPASIM_M10.md](ALPASIM_M10.md) |
| M11 Pipeline | CPU t3.medium（実際の SageMaker Pipeline を実行） | なし（ジョブクォータ §2b） | [PIPELINE_M11.md](PIPELINE_M11.md) |
| M12 HyperPod | CPU t3.medium（実際の DDP ジョブを送信） | なし（ジョブクォータ §2b） | [HYPERPOD_M12.md](HYPERPOD_M12.md) |

**要点:** 必須の一度きりの管理者キャッシュは **nuScenes（M1）+ model-cache（M2）+ hf-cache
（M5/M6/M9）+ M9 デモクリップ**、加えて M10 を実行する場合は **M10 リファレンスラン**です。
M12 と M11 には**キャッシュ不要** — §2b のジョブクォータだけです。

---

### 4b. 実際の IAM 縮小を可能にする 1 分の確認（無料）

現在、共有実行ロールに `CreateApp` / `DeleteApp` が `resources=["*"]` で付与されています。つまり
ターミナルを持つ参加者は CLI で**他人の**スペースのアプリを作成・削除できます（ダッシュボードには
その経路はありません）。`${sagemaker:UserProfileName}` の所有者条件で絞るのが解決策ですが、その
ポリシー変数がリクエスト時に実際に置換される場合に限られ、**シミュレーションでは判定できません**:

* `iam:SimulateCustomPolicy` は `${sagemaker:*}` 変数を置換**しません**。変数を含むケースはすべて
  `implicitDeny`、リテラルなら `allowed` を返すため、どちらの証拠にもなりません。
* Studio の外からロールを assume しても同じです。アプリコンテキストが無いため変数が空になり、
  `Resource` 内の未解決変数は何にもマッチせず fail-closed になります。これも情報になりません。

信頼できる唯一の検査はライブ検査で、費用はかかりません:

1. 参加者のスペースを**その参加者として**開き、**Run space**、続いて **Open JupyterLab** をクリック。
2. **`AccessDenied` が出なければ** ⇒ リクエスト時に変数が置換される ⇒
   `infra/av30_constructs/sagemaker.py` の `CreateApp`/`DeleteApp` を `resources=["*"]` から
   `SageMakerOwnPrivateSpaceUpdate` が既に使う所有者条件に変更して安全です。
3. **`AccessDenied` が出たら**絞っては**いけません**。未解決のポリシー変数は fail-closed なので、
   この証拠なしに締めると参加者全員が自分のワークスペースからロックアウトされます。

実施したら結果をここに記録し、次の管理者が再導出しなくて済むようにしてください。

---

## 5. プラットフォームのデプロイ（Day −3）

> **リージョンは明示指定で、再デプロイにはガードがあります。** `--region` を渡してください —
> デプロイ経路のどこにも既定値はありません。既存スタックを**更新**する場合、`deploy.sh` は
> ライブ状態を読み取り、破壊的な動作を黙って実行する代わりに**拒否**します: スタックの
> `Owner` タグが変わるデプロイ（Studio ドメインが置き換えられ、全参加者のワークスペースが
> 失われ EFS が孤立します）と、`HOSTED_UI_DOMAIN_EXISTS` の誤った組み合わせ（既存の非管理
> Cognito ドメインを宣言する、逆にスタックが管理中のドメインを削除してしまう）の両方を
> 止めます。拒否のたびに再実行すべき正確なコマンドを出力します。**新しいリージョンでは
> これらのフラグは一切不要です。**
> リージョンを**追加**する場合は [ADDING_A_REGION.md](ADDING_A_REGION.md) を参照してください。


```bash
# Required env
export ADMIN_EMAIL="you@example.com"       # becomes the Cognito admin + SNS alert target
export REGION="us-west-2"                  # YOUR chosen region (§1.5) — passed explicitly below
export AWS_REGION="$REGION"                # the seeding scripts in §6 read this
export HF_TOKEN="hf_..."                    # for the caching steps in §6
# Optional: lock the admin dashboard to your IP
export ADMIN_IP_ALLOWLIST="203.0.113.0/24" # default 0.0.0.0/0

# One-time CDK bootstrap (per account+region)
cd infra && source .venv/bin/activate && pip install -r requirements.txt
npx cdk bootstrap aws://$(aws sts get-caller-identity --query Account --output text)/$REGION
cd ..

# Generate this region's instance rate table (REQUIRED — the Lambdas raise at import
# without it rather than quoting another region's prices)
./scripts/refresh_instance_rates.py --region "$REGION" --merge

# Deploy stack + build/upload both dashboards (~25 min). Region is explicit.
./scripts/deploy.sh --region "$REGION"
```

`deploy.sh` は `ADMIN_EMAIL` と `ADMIN_IP_ALLOWLIST` を `--context` 経由で CDK に渡します
（env 変数**ではありません** — `deploy.sh` をスキップして手動で `cdk deploy` を実行する場合は、
`--context admin_email=...` を渡す必要があります。さもないと SNS 予算アラートがプレースホルダーに
戻ります）。最後に**管理者ダッシュボード URL** と **API エンドポイント**を出力します。

**管理者ログインを作成**します（ユーザー名はメールでなければなりません — Cognito はメールを
サインインエイリアスとして使用します）:
```bash
aws cognito-idp admin-create-user \
  --user-pool-id <POOL_ID_FROM_DEPLOY_OUTPUT> \
  --username "$ADMIN_EMAIL" \
  --user-attributes Name=email,Value=$ADMIN_EMAIL Name=email_verified,Value=true \
  --temporary-password 'TempPass1!' --region $AWS_REGION
```
管理者ダッシュボードにログインすると、新しいパスワードの設定を求められます。

---

## 6. 一度きりのデータ + モデルステージング（Day −3 〜 −2）

これらはすべて**共有**バケットに書き込みます。ステップ 6.3/6.4 は、あなたのトークンでゲート付き
リポジトリに到達できるマシンで実行する必要があります。

### 6.1 nuScenes-mini（M1/M2/M7）
```bash
./scripts/stage_nuscenes.sh    # pulls the public AWS Open Data mirror → datasets/nuscenes-mini/
```

### 6.2 シンプルなモデルキャッシュ（M2/M3）
```bash
pip install huggingface_hub && hf auth login --token "$HF_TOKEN"
./scripts/cache_models.sh      # → s3://<shared>/model-cache/ (Cosmos-Reason1-7B, Transfer2.5, Predict2.5)
```

### 6.3 HF オフラインキャッシュ（M5/M6/M9） — 「参加者トークン不要」のトリック

> **`cache_models.sh` は `hf-cache/hub/` を作りません** — `scripts/cache_hf_tree.sh` を使ってください。
> 2026-09-26 まで、このリポジトリのどれもそのツリーを生成できませんでした: `scripts/` 内のすべての
> `hf-cache` 参照は S3 から*読む*側で、書く側が存在せず、唯一のレシピが下の手動手順でした。
> `cache_models.sh` は代替になりません — 別のプレフィックス（`model-cache/`）に別のレイアウト
> （フラットな `hf download --local-dir`。`models--org--name/snapshots/<sha>/…` ではない）で書きます。
>
> 結果として 2 点が実際に問題になりました:
> * **新しいリージョンでは再構築ではなくコピー。** シード済みリージョンからバケット間 `aws s3 sync`
>   （[ADDING_A_REGION.md](ADDING_A_REGION.md) §4）。2026-09-26 に ap-northeast-2 を
>   `cache_models.sh` でシードし、M5/M6/M9/M10 が動かない状態で出荷しました。
> * **推測せず検証する。** `./scripts/check_seeding.sh --region <r>` がランタイムの glob がテストする
>   `models--nvidia--*` ディレクトリ 5 つと、固定された `tokenizer.pth` blob をアサートします。
>   `cache_models.sh` が正常終了したことは、このプレフィックスについて何も証明しません。

M5/M6/M9 はゲート付きチェックポイントを実行時に HF **独自のキャッシュレイアウト**経由で
ロードします（M9 は隠れた Cosmos-Reason2-8B バックボーンもプルします）。これを確実に
埋める方法は、**あなたの管理者トークンで GPU JupyterLab アプリ上で M5、M6、M9 を一度ずつ実行し**、
その後キャッシュツリーを同期することです:
```bash
aws s3 sync /mnt/sagemaker-nvme/hf/hub s3://<shared>/hf-cache/hub/ --only-show-errors
```
`setup_cosmos_env.sh` はこれを `HF_HOME` に復元し `HF_HUB_OFFLINE=1` を設定するため、
参加者はトークンなしでオフライン実行できます。**M9 はデモクリップも必要とします**（その
データセットはオフラインでは読めません）:
```bash
source /mnt/sagemaker-nvme/cosmos-work/alpamayo_env.sh
unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE   # this save must be online
python scripts/alpamayo_save_clip.py --clip 030c760c-ae38-49aa-9ad8-f5650a545d26 \
  --t0-us 5100000 --out /mnt/sagemaker-nvme/m6_work/clips
aws s3 cp /mnt/sagemaker-nvme/m6_work/clips/030c760c-*.pt s3://<shared>/hf-cache/alpamayo-demo/
```
完全な手順: [COSMOS_M5_M6.md](COSMOS_M5_M6.md)、[ALPAMAYO_M9.md](ALPAMAYO_M9.md)。

### 6.4 M10 AlpaSim リファレンス評価（M10 を実行する場合のみ）
AlpaSim は ≥40 GB の GPU を必要とする Docker-Compose マイクロサービスシステムで、
**Studio ノートブックでは実行できません**。Docker 対応の GPU EC2 ホストで一度だけ実行してください:
```bash
# On a Deep Learning Base GPU AMI box (g6e.12xlarge, public subnet):
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export HF_TOKEN=hf_... NGC_API_KEY=nvapi-...
# Do NOT export SHARED_BUCKET: the script derives av30lab-shared-data-<acct>-<region>
# itself and exits 1 if it cannot. An exported value overrides that and, if it is
# missing the region suffix, silently targets a bucket that does not exist.
bash scripts/alpasim_ec2_setup.sh    # → uploads s3://<shared>/m10-reference/
# then TERMINATE the instance.
```
M10 ノートブック（CPU）は、全参加者向けにこれらの結果をダウンロードして可視化します。
一度きり約 $30、参加者コストは $0。完全な詳細 + オプションの参加者セルフランパス:
[ALPASIM_M10.md](ALPASIM_M10.md)、[M10_MANUAL_TEST_RUNBOOK.md](M10_MANUAL_TEST_RUNBOOK.md)。

### 6.5 ノートブックテンプレート + スクリプトのアップロード（これは最後に、ノートブック編集後に行う）
```bash
# <shared> = av30lab-shared-data-<account>-<region>. $AWS_REGION は §5 で export した値（または: export AWS_REGION=...）
aws s3 sync notebooks/ s3://<shared>/notebook-templates/ --region "$AWS_REGION" \
    --exclude "*__pycache__*" --exclude "*.pyc"
aws s3 sync scripts/   s3://<shared>/notebook-templates/scripts/ --region "$AWS_REGION" \
    --exclude "*__pycache__*" --exclude "*.pyc"
```

> **番号変更前のノートブックが既に入っているバケットへ再同期しますか？**
> `aws s3 sync` は削除しないため、旧名（`M4_Cosmos_Transfer_…`、`M8_OpenSearch_…`、
> `M9_HyperPod_…`、`M10_Nerfstudio_…`）が新名と併存し、参加者に両方が見えてしまいます。
> `--delete` は**使わないでください** — この同期が再作成しない
> `notebook-templates/scripts/` フォルダまで消えます。代わりに旧オブジェクトを明示的に
> 削除してください:
> ```bash
> for f in M4_Cosmos_Transfer_Augmentation M5_Cosmos_Predict_Synthesis \
>          M6_Alpamayo_VLA_Inference M7_AlpaSim_ClosedLoop \
>          M8_OpenSearch_Semantic_Search M9_HyperPod_Distributed_Training \
>          M10_Nerfstudio_3D_Reconstruction; do
>   aws s3 rm "s3://av30lab-shared-data-$ACCOUNT-$AWS_REGION/notebook-templates/$f.ipynb" \
>     --region "$AWS_REGION"
> done
> ```
> `teardown.sh` 後の新規デプロイでは不要です。
これらはプロビジョニング時に各ユーザーのワークスペースにコピーされます（そしてノートブックは
このパスからのスクリプトダウンロードにフォールバックします）。**ノートブックやスクリプトを
変更したら必ずこれを再実行してください** — さもないと参加者は古いバージョンを受け取ります。
すでにプロビジョニング済みの参加者は、JupyterLab ターミナルから再同期できます:
`aws s3 cp s3://<shared>/notebook-templates/<NB>.ipynb ~/`。

> **`scripts/patch_notebooks.py` に関する注記:** 以前のブートストラップ由来の、手動でその場で
> `.ipynb` を変換するツールです。これは**どの自動化にも組み込まれていません**（デプロイ、CDK、
> プロビジョニングのいずれにも） — リポジトリの `notebooks/*.ipynb` が唯一の信頼できる情報源です。
> 現在すべてのモジュールエントリは `[]`（no-op）です。このツールはノートブックが期待される
> パターンから逸脱した場合に**ハードフェイル**するため、パッチ未適用のノートブックを黙って
> 出荷することは決してありません。通常は実行する必要はありません — ノートブックを直接編集し、
> §6.5 で再同期してください。これらのノートブックが依存するモジュール間の S3 コントラクトは
> [DATA_CONTRACT.md](DATA_CONTRACT.md) にあります。

---

## 7. オプション: M10 参加者セルフラン（上級）

デフォルトでは全参加者があなたの 1 つの M10 リファレンス評価（§6.4）を共有し、トークンは
不要です。代わりに、**各参加者が自分専用の管理者プロビジョニング GPU ホスト上で SSM 経由で
AlpaSim を自分自身で実行する**ようにしたい場合:
- 参加者ごとに GPU EC2 ホストを事前プロビジョニングし、最小権限の SSM アクセス（厳密な ARN
  または ABAC）を付与します。**参加者はホストを終了できません — あなたが行います**
  （コスト暴走ガード）。
- 各参加者は**自分専用の HF トークン**を必要とします（NuRec データセットはゲート付きで、
  共有キャッシュには含まれません）。
- コストは約 $10.5/時/ホスト、G-vCPU クォータにより最大 16 同時。

完全なランブック: [M10_MANUAL_TEST_RUNBOOK.md](M10_MANUAL_TEST_RUNBOOK.md) の Part C（管理者
プロビジョニング + IAM）と [M10_PARTICIPANT_SSM_RUNBOOK.md](M10_PARTICIPANT_SSM_RUNBOOK.md)
（参加者の手順）。これはオプトインです。標準的なワークショップではスキップしてください。

---

## 8. スモークテスト（Day −1） — 1 ユーザーがエンドツーエンドで動くことを証明する

1. 管理者ダッシュボード → **Add User** → テスト名 + メール → **Provision**。
2. 成功ダイアログから**参加者ダッシュボードリンク**をコピーします（永続的な
   `?userId=&token=` リンク — 5 分間の「Direct workspace URL」**ではありません**）。
3. そのリンクを新しいブラウザで開く → 12 個のモジュールノード（M1〜M12。M0 は概要ノートブックでノードを持ちません）を持つ Pipeline Map が表示されます。
4. **M2** をクリック → **Instance Options** → 推奨の `ml.g5.12xlarge` が事前選択済み →
   **Apply & Restart** → **Open Workspace** → JupyterLab が開きます。
4b. **スコープ付き IAM 条件が実際に解決されるかを確定（無料、約 1 分）。** そのアプリが
   実行中の状態で、テストユーザーとして Studio **自体**を開きます（ディープリンクではなく
   Studio コンソール）。スペースのページで **Run space**、続いて **Open JupyterLab** を
   クリックし、`sagemaker:UpdateSpace` / `sagemaker:CreatePresignedDomainUrl` に対する
   `AccessDenied` が出るかを記録します。
   - **AccessDenied なし** → `${sagemaker:DomainId}` / `${sagemaker:UserProfileName}`
     のポリシー変数が実行時に解決されます。したがって `CreateApp`/`DeleteApp` を
     `resources=["*"]` から同じ所有者条件へ狭められます。
     `infra/av30_constructs/sagemaker.py` の `SageMakerStudioAppLifecycle` 文の注記を参照。
   - **AccessDenied が出る** → このアカウントでは解決されません。`CreateApp` は広いままにし、
     参加者にはダッシュボードのボタンを使わせ続けてください。
5. **M1**（CPU）をエンドツーエンドで実行し、続いて **M2**（GPU）を実行 — GPU イメージが
   自動選択され、モデルキャッシュが解決されることを確認します。
6. M12/M11 を実行する場合は、テストユーザーとして各 1 回ずつ実行し、ジョブクォータ（§2b）と
   IAM が整っていることを確認してください — これらは実際のマネージドジョブを送信します。
7. テストユーザーを**削除**します（Users タブ → Delete） — アプリ/スペース/プロファイル + S3 を削除します。

---

## 9. 参加者のプロビジョニング（Day 0）

**単一ユーザー:** 管理者ダッシュボード → **Add User** → 名前 + メール → **Provision**。
**参加者ダッシュボードリンク**（永続的、失効しない）を渡します。Users テーブルには
ユーザーごとにコピーボタン付きの **Dashboard Link** 列があります。

**一括（CSV）:** 管理者ダッシュボード → 一括アップロード。CSV には `name` と `email` 列を持つ
ヘッダー行が必要です（大文字小文字を区別しません）。プロビジョニングは並列で実行されます。
失敗したものは個別に再試行してください。

各参加者は次を受け取ります: SageMaker ユーザープロファイル + スペース、ノートブック
テンプレートで初期化された `users/<id>/` S3 プレフィックス、そして個人用ダッシュボードリンク。

**参加者には 2 つのものを送ってください:**
- **イベント前** — [PRE_LEARNING_GUIDE.md](PRE_LEARNING_GUIDE.md)（コンセプト +
  オプションの深掘り読み物、約 45–60 分）。文脈を持って参加できるように。
- **当日** — ダッシュボードリンク + [PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md)
  （クリックごとのランブック）。

---

## 10. ワークショップ中 — 監視 & 制御

- **Sessions タブ** — 誰が何を、どのインスタンスで実行しているか、そしてコストのライブビュー。
- **容量エラー**（`EC2InsufficientCapacityError`）: そのモジュールに対して Instance Options が
  提示する代替のどれでも選ぶよう伝えてください — 一覧はすでにこのリージョンが販売するタイプに
  絞られており、クォータ 0 のタイプは受理されず理由付きで拒否されます。特定のフォールバックを
  記憶で指定しないでください: `ml.g6.12xlarge` は以前の案内で、ap-northeast-2 ではクォータ 0 です。
- **インスタンス変更が黙って行われなかった場合。** 参加者がインスタンス変更が何も起きなかったと
  言う場合、新しいタイプでのアプリ起動が失敗し（多くは `ResourceLimitExceeded` — クォータはあるが
  全スロットが使用中）、以前のタイプにロールバックされてワークスペースは残っている状態です。
  理由は `GET /sessions/{id}/app-status` の `lastInstanceChangeError` にあります。アイドルの
  セッションを強制終了してスロットを空け、再試行させてください。これは容量不足であり、クォータの問題では
  ありません。
- **コスト制御** — 日次予算アラームが SNS 経由で `ADMIN_EMAIL` にメールします。ライフサイクル
  アイドルの JupyterLab アプリは 90 分後に自動停止します（変更は `-c idle_timeout_minutes=<60..180>`）。実行中のセルやターミナルジョブは「アクティブ」と判定されるため、進行中の作業が中断されることはありません。Sessions タブから任意のセッションを
  **強制終了**できます。アイドルの GPU マシンに注意してください — 単価はリージョンごとなので
  自分のリージョンの値を使ってください: `ml.g5.12xlarge`（5 モジュールのデフォルト）は
  ap-northeast-2 で **$8.72/時**、us-west-2 で $7.09。`ml.p4d.24xlarge` は ap-northeast-2 で
  **$34.97/時**、us-west-2 で $25.25 です。自分のリージョンは
  `infra/lambda/shared/instance_rates.py` を参照してください。
- **ストレージ費用は参加者ごとで、一方向にしか動きません。** すべてのスペースは 200 GB の gp3
  ボリュームで作成されます（`infra/av30_constructs/__init__.py` の
  `DEFAULT_SPACE_STORAGE_GB`）。ap-northeast-2 の $0.0912/GB-月 で **参加者あたり月約 $18.24**、
  アプリが動いているかどうかに関わらず課金されます — アイドルタイマーが削除するのはアプリで、
  ボリュームは残ります。AWS はスペースのボリュームの**縮小を許可しません**。参加者は拡大できるため
  （+50/+200、上限 500 GB）、ティアダウンでスペースを削除するまで増える一方です。
- **GPU イメージのリマインダー** — 参加者が GPU インスタンスで「No GPU detected」と報告した場合、
  CPU イメージを起動しています。Instance Options → GPU インスタンス → Apply で GPU イメージが
  再選択されます。

---

## 11. M7 Nerfstudio — gsplat ビルド（セッションごと）

**M7 のトレーニングセルは未検証です — リポジトリが自己矛盾しています。** 本節は以前
「M7 は現在トレーニングします」と断定していました。しかしノートブックの cell 0 は逆のことを
述べており（「現在のイメージでは実行されない」）、両方の主張が同じコミットで入り、捕捉された
実行は 9 セル中 2 セルしか出力を残していません — つまり合格も失敗も誰も見ていません。
`ml.g5.xlarge` で 1 回実行すれば（約 $0.25、約 15 分）決着します。
`docs/en/TODO_M7_nerfstudio.md` を参照。それまでは PARTICIPANT_GUIDE が記述する
オプションの概念 + データ準備デモとして扱ってください。

セッションごとの gsplat CUDA ビルド後に*意図されている*動作は次のとおりです:`gsplat` は純粋な Python ホイールを出荷し、初回使用時に CUDA カーネルをソースから
コンパイルしますが、SageMaker Distribution イメージの conda CUDA 開発パッケージは不完全です。
**`scripts/setup_gsplat_env.sh`**（M7 セル 3 がこれを呼び出します）がチェーン全体を修正します:
不足している開発ヘッダーをインストールし、`nvcc` が `cicc` を見つけられるよう `nvvm` をシンボリック
リンクし、CUDA ヘッダー/ライブラリを標準の `$CUDA_HOME` パスにミラーリングし（env 変数ゼロで
ビルドが動作するよう、`ns-train` のサブプロセス内でも）、そして `gsplat==1.4.0` をソースビルドします。

- これは**エフェメラル**です — SMD アプリは再起動時に `/opt/conda` をリセットするため、
  セットアップセルはセッションごとに再実行されます（コールドで約 3–5 分、ビルド済みなら数秒）。
- デモは**合成のサインウェーブカメラポーズ**を使うため、トレーニングはエンドツーエンドで実行
  されます（本物の Gaussian-Splatting パイプライン）が、再構成はスモークテストであり、計量的に
  正しいシーンではありません。実際の nuScenes キャリブレーションの配線が次のステップです。
- **M7 の注意点:** gsplat CUDA ビルドはセッションごとに `scripts/setup_gsplat_env.sh` で
  実行されます。M7 はオプション/デモモジュールとして扱い、最終トレーニングセルは GPU イメージの
  CUDA ツールチェーンに敏感であると想定してください。

---

## 12. ティアダウン & イベント後のセキュリティ

- **ワンショットティアダウン:** **`scripts/teardown.sh`** は管理者 AWS 認証情報ですべてを
  回収します。デフォルトはドライラン（列挙するだけで何も変更しません）。`--yes` で実行、
  `--user <id>` で単一ユーザーに限定、`--destroy` で `cdk destroy` も実行します。
  ユーザーごとに app→space→profile→AOSS→S3→DDB を削除し（delete_user Lambda と同じ順序）、
  その後、孤立した OpenSearch Serverless コレクションを捕捉するために**グローバルな
  `av30-semantic-*` AOSS スイープ**を実行し（これらは継続的に課金されます — スイープが
  セーフティネットです）、`Participant` + `av30-alpasim-*` タグの付いた GPU EC2 ホストを
  終了します。最後に手動の HF/NGC キー無効化チェックリストを出力します。
- **単一ユーザーを対話的に削除:** 管理者ダッシュボード → Users → **Delete**
  （1 アクションで同じ依存順序）。
- **スタックのティアダウン**（プラットフォームが一時的な場合）: `scripts/teardown.sh
  --yes --destroy`、または `cd infra && npx cdk destroy`。共有データバケットは RETAIN で
  あることに注意してください — バケットとキャッシュされたモデルは destroy を生き延びるため、
  手動で空にする必要があります。
- **管理者 HF トークン `hf_...` を無効化** — 参加者が触れるのは S3 キャッシュだけなので、
  ステージング後にトークンは不要です。
- M10 を使った場合は **NGC API キーをローテーション**してください。
- アイドルのスタックでも約 $80/月かかります（NAT、VPC エンドポイント、DynamoDB、CloudFront） —
  終わったら破棄してください。

---

## 13. 管理者トラブルシューティングのクイックテーブル

| 症状 | 原因 / 対処 |
|---|---|
| `ResourceLimitExceeded: ...Studio JupyterLab Apps... is 0` | GPU アプリクォータが未引き上げ — §2a。 |
| M12 ジョブが送信時に失敗（`CreateTrainingJob` で `AccessDeniedException`） | 実行ロールの training-job ARN プレフィックスがノートブックの `JOB_NAME` と一致する 必要があります。モジュール再採番で HyperPod が M9→M12 に移動しノートブックは `av30-m12-distributed-*` を送信しますが、その修正より前のデプロイは `av30-m9-*` のみを 許可するため全ての送信が拒否されます。m5.xlarge の**ジョブ**クォータ（§2b）は別の稀な 原因です — まずエラーを確認してください: `AccessDenied` は IAM プレフィックス、`ResourceLimitExceeded` はクォータ。|
| GPU インスタンスで参加者が「No GPU detected」 | CPU イメージが選択されている — Instance Options で再 Apply。 |
| M5/M6/M9 のセットアップセルが "this region has no usable offline HuggingFace cache and no HF_TOKEN" で停止（exit 2） | このリージョンに `hf-cache/hub/` が未シード（§6.3）。シード後 `./scripts/check_seeding.sh --region <r>`。このメッセージは*修正後*の挙動です — 2026-09-26 より前は同じ条件が沈黙で、セットアップセルが "environment ready" を表示した後、M5 が `torchrun` の中で 4 秒で `ChildFailedError` により停止し CUDA out-of-memory を指していました。まだ古い形が見える場合、参加者は古いステージング済み `setup_cosmos_env.sh` を使っています。 |
| M5/M6/M9 が `Local entry not found … offline mode is enabled` で失敗 | 復元されたキャッシュが**部分的**です。中断された `aws s3 sync` が典型的な原因で — **同じ sync をもう一度実行してください**。欠けているもの・サイズ違いのものを再コピーして再開します。`sync` が検出できないのはサイズが正しく内容が誤ったオブジェクトです（size+mtime 比較）。`check_seeding.sh --source-region <seeded>` が CRC64 不一致を報告したら、そのオブジェクトだけ削除して再 sync してください。 |
| M7 トレーニングセルが gsplat で失敗する | M7 セル 3（`scripts/setup_gsplat_env.sh`）を再実行 — CUDA ビルドはセッションごとで、アプリ再起動時にリセットされます。§11。 |
| M9 がクリップのロードに失敗する | デモの `.pt` が `hf-cache/alpamayo-demo/` にアップロードされていない（§6.3）。 |
| M10 ノートブックに何も表示されない（cell-4 が "No M10 AlpaSim results found in S3" を出す） | `m10-reference/` リファレンス評価が未実行（§6.4）。 |
| M10 のメトリクス・グラフは出るが**動画だけ**が空白 | **バンドル欠落ではなく、§6.4 を再実行してはいけない。** コーデックの問題: AlpaSim レンダラーが MPEG-4 Part 2 で書き出し、Chrome/Firefox/Edge はこれをデコードできない。cell-7 が検出したコーデックを出力する。GPU ホスト不要で、そのオブジェクト 1 つを H.264 に置き換えればよい: `aws s3 cp s3://$SHARED_BUCKET/m10-reference/eval/eval.mp4 .` の後 `ffmpeg -i eval.mp4 -vf scale=1280:-2 -c:v libx264 -pix_fmt yuv420p -movflags +faststart -an eval_h264.mp4` を実行し `m10-reference/eval/eval.mp4` に上書きする。`scripts/alpasim_ec2_setup.sh` はアップロード時に変換するようになったので、その変更以降に作られたバンドルは既に H.264 である。 |
| M4 の検索デモが**同じキャプションを複数回**ランクし、インデックスセルが削除で `403 authorization_exception` を出力 | コレクションのデータアクセスポリシーが **`aoss:DeleteIndex`** 付与より前のもので、M4 がインデックスを空にできません。AOSS は呼び出し側指定の `_id` を拒否するため `index()` は常に INSERT — 再実行ごとに全文書のコピーが追加されます（実測: キャプション 24 件に対し文書 24 → 48 → 72 → 96 → 120）。参加者ロールはポリシーを修正できません: `aoss:UpdateAccessPolicy` は意図的に付与していません（`collection/*` 範囲では、ある参加者が他の参加者のコレクションに到達できてしまうため）。admin 認証情報で**コレクションとデータポリシーの両方**を削除してください（ポリシーが残ればそれが古いものです）。その後参加者が Run All すると M4 が権限込みで再作成します: `aws opensearchserverless list-collections --region $REGION --query 'collectionSummaries[?starts_with(name,\`av30-semantic-\`)].[id,name]' --output text` → `aws opensearchserverless delete-collection --id <id> --region $REGION` → `aws opensearchserverless delete-access-policy --name <name>-access --type data --region $REGION`. |
| SNS 予算アラートが placeholder@example.com に届いた | `--context admin_email` なしでデプロイされた — `deploy.sh` で再デプロイ。 |
| 参加者リンクが「Demo Mode」と表示される | 素の URL を開いた。完全な `?userId=&token=` リンクを再送してください。 |
| 一括プロビジョニングが部分的に失敗 | 失敗した行を個別に再試行。`bulk_provision` の CloudWatch ログを確認。 |

---

## 関連ドキュメント
- [PRE_LEARNING_GUIDE.md](PRE_LEARNING_GUIDE.md) — イベント前に参加者へ送付。
- [PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md) — 当日参加者に渡す。
- [PREREQUISITES.md](PREREQUISITES.md) — §3/§6 の背景にあるトークン/ライセンスの詳細。
- モジュールの深掘り: [COSMOS_M5_M6.md](COSMOS_M5_M6.md)、[ALPAMAYO_M9.md](ALPAMAYO_M9.md)、
  [ALPASIM_M10.md](ALPASIM_M10.md)、[HYPERPOD_M12.md](HYPERPOD_M12.md)、
  [PIPELINE_M11.md](PIPELINE_M11.md)。
- [ADDING_A_REGION.md](ADDING_A_REGION.md) — 独立した追加リージョンの構築（クォータ、
  データ配置、再デプロイに必要なコンテキスト）。
- [README.md](../../README.md) — 完全なデプロイ + アーキテクチャリファレンス。
