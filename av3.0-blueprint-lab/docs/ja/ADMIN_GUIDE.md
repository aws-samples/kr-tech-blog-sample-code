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
  `av30lab-sagemaker-execution-role-<region>` を共有する SageMaker Studio ドメイン（ユーザー
  ごとのロールではありません）。このロールで何が分離され、何が分離されないかは、下の
  **参加者の分離**にまとめています。
- **2 つの S3 バケット**（名前は**あなたの**アカウント + リージョンから導出されます。本ガイドの
  例ではリファレンスデプロイであるアカウント `<aws-account-id>` / `us-west-2` を使用しています。
  ご自身の値に置き換えてください — §1.5 を参照）:
  - `av30lab-shared-data-<account>-<region>` — モデル、データセット、ノートブックテンプレート、M10 リファレンス。
  - `av30lab-user-workspace-<account>-<region>` — 参加者ごとに 1 つの `users/<id>/` プレフィックス。

> **参加者の分離（信頼モデル）。** 参加者のノートブック、ターミナル、ジョブはすべてこの
> 1 つのロールで動きます。参加者を区別する値は 2 つあります。ドメインに
> `ExecutionRoleIdentityConfig = USER_PROFILE_NAME` が設定されているため、SageMaker はこの
> ロールのセッションごとに `aws:SourceIdentity` = ユーザープロファイル名（参加者 ID、S3
> プレフィックスと同じ値）を付けます。また SageMaker API の呼び出しには
> `${sagemaker:UserProfileName}` が含まれます。これにより、参加者が触れられるのは次の点で
> 自分のものだけになります。
> - **S3 ワークスペース。** ワークスペースバケットの読み取り、書き込み、削除、一覧取得は
>   `users/${aws:SourceIdentity}/` に限られます。他の参加者のノートブックや
>   `.av30-progress.env`（その人のダッシュボードトークンが入っています）は読めず、他の参加者の
>   ホームに `.bashrc` や IPython の起動ファイルを仕込むこともできず（アプリは起動のたびに
>   `users/<id>/` をホームにコピーします）、他の参加者の成果物を消すこともできません。
>   source identity のないセッションは `users/` 全体が拒否されます（fail-closed）。
> - **M11 パイプラインと M12 トレーニングジョブ**（`av30-data-pipeline-<id>`、
>   `av30-m12-distributed-<id>-*`）。
> - **プライベートスペース。** `UpdateSpace` と Studio 自身の presigned URL は、呼び出した
>   本人のスペースとプロファイルに限られます。
>
> **引き続き共有されるもの。** コホートは互いを攻撃しない人たちだという前提に立ち、次の
> 場所には、他の参加者に見られたり変えられたりしては困るものを置かないでください。
> - スペース、アプリ、プロファイルの Describe/List: 誰が何を動かしているかは誰でも見えます。
> - `*` に対する `CreateApp`/`DeleteApp`: boto3 を使えば他の参加者のアプリを起動・停止
>   できます（狭められるかどうかは §8 の手順 4b で判断します）。
> - OpenSearch Serverless: `collection/*` に `aoss:APIAccessAll` が許可されており、M4 の
>   データアクセスポリシーは共有ロールをプリンシパルにしているため、他の参加者の M4
>   コレクションを読んだり変更したりできます。
> - Processing ジョブ（`processing-job/*`）: M11 のステップジョブ名は Pipelines サービスが
>   プロファイルを含めずに付けるため、他の参加者のステップジョブを参照・停止できます。
> - トレーニングジョブの例外が 1 つ: `av30-m12-distributed-<id>-*` は、ID が
>   `<id>-<続き>` のプロファイルにも一致します（例: `kim-abc123` と `kim-abc123-q1w2e3`）。
> - 共有データバケットは誰でも読め、CloudWatch Logs の `/aws/sagemaker/*` には誰でも
>   書き込めます（読み出しは誰にもできません）。
> - M10 セルフラン用の EC2 インスタンスプロファイル（§7）を作成した場合、それは
>   `users/*/m10/*` に書き込めます。
> - 参加者トークンには有効期限がなく、ローテーションの手段もありません。再発行するには
>   ユーザーを削除して作り直してください。
>
> 管理者も同じ制限を受けます。Studio アプリからは、管理者自身のプロファイルも自分の
> プレフィックスにしか触れられません。参加者のプレフィックスは、ワークステーションから
> 管理者の認証情報で確認してください。
>
> これらはすべて、SageMaker が新しい Studio の JupyterLab セッション、ライフサイクル
> スクリプト、M11/M12 のジョブに実際に source identity を付けることを前提にしています。
> AWS のドキュメントに記載された仕組みですが、証明できるのは実際のデプロイだけなので、新しい
> スタックごとに §8 のユーザー間チェックを実行してください。これに合格すれば、§6.3 の前提
> 条件（「ユーザーワークスペースのバケットがユーザーごとに分離された後」）は、以後に書かれる
> ファイルについて満たされます。アップグレード前に管理者のプレフィックスへ仕込まれたファイルは
> そのまま残り、その場合は §6.3 で扱っています。

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
  `g6`、オプションで `p4d`）は**すべての**リージョンにあるわけではなく、クォータ承認は
  リージョンごとです。GPU 容量の潤沢なリージョンを選んでください — `us-west-2`（オレゴン）と
  `us-east-1`（バージニア北部）が最も安全です。
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
Service Quotas コンソールで「**Studio JupyterLab Apps running on**」を検索します。下の表は
**ユーザーダッシュボードの Instance Options** が提示するタイプ（推奨 + 代替）そのもので、API も
この一覧を強制します。`cdk synth` が `web/user/src/data/pipeline-config.ts` から一覧を読み取って
このリージョンで販売されているタイプだけを残し、`change_instance` はそれ以外のタイプを、API が
直接呼び出された場合でも、実行中のアプリに触れる前に 400 で拒否します。Studio の中でも、実行
ロールが同じ一覧を適用します（下記）。一覧を変えるには、このファイルを編集してスタックを再デプロイ
してください。
クォータ**コードはリージョンに依存しません**（us-west-2 / ap-northeast-2 / eu-west-1 で同一と確認済み）。
しかし**値は依存します**し、そもそもどのタイプにクォータが存在するかもリージョンごとに異なります。

> **Studio でも同じ一覧が適用されます。** 参加者の実行ロールには明示的な Deny
> `DenyNonParticipantInstanceTypes` があり、`sagemaker:CreateApp` と `sagemaker:UpdateSpace`
> で要求された `sagemaker:InstanceTypes` に、この一覧（と JupyterServer アプリのインスタンス
> タイプである `system`）以外の値が 1 つでも含まれていれば拒否します。synth が API と同じ一覧から
> 作るため、Studio の **Run space** やノートブックの boto3 で `ml.p5.48xlarge` を要求しても
> `AccessDenied` になります。この Deny はドメイン内のすべての Studio セッションに効き、管理者
> 自身のプロファイルも例外ではありません。API の Lambda と、ワークステーション上の管理者認証情報
> （例: `scripts/grab_gpu_instance.py`）には影響しません。デプロイ前から別のタイプで動いていた
> アプリは、そのまま動き続けます。
>
> **実デプロイでの確認はまだです。** この Deny が効くのは、インスタンスタイプを含むリクエスト
> だけです。AWS のドキュメントは両アクションにこのキーがあると記載していますが、スペースの
> `DefaultResourceSpec` だけを変える `UpdateSpace` や、`ResourceSpec` なしで送った `CreateApp`
> （スペースのデフォルトを使う）でも SageMaker がこのキーを埋めるかどうかは書かれていません。
> どちらも埋めないなら「デフォルトを変えてから ResourceSpec なしで起動する」方法で今も回避でき、
> その場合そのタイプを止めるのは再びクォータだけです。下の確認がスタックで通るまでは、提供する
> つもりのないタイプのクォータは申請しないでください（p4d の行を参照）。確認は §8 の手順 7
> （そのスペースはどのみち削除されます）の直前に、§8 のテストユーザーの JupyterLab ターミナルで
> 実行します。確認 1 で何も起動しないよう、アプリは動かしたままにしてください。`ml.c5.large` は
> 一覧にない安価なタイプです。
> ```bash
> DOMAIN_ID=$(python3 -c "import json;print(json.load(open('/opt/ml/metadata/resource-metadata.json'))['DomainId'])")
> SPACE="$USER_PROFILE-space"
> # 1. AccessDenied になるはずです。ResourceInUse なら Deny は効いていません（何も起動しません）。
> aws sagemaker create-app --domain-id "$DOMAIN_ID" --space-name "$SPACE" \
>   --app-type JupyterLab --app-name default --resource-spec InstanceType=ml.c5.large
> # 2. AccessDenied になるはずです。それ以外の結果なら、このリクエストではキーが埋められていません。
> aws sagemaker update-space --domain-id "$DOMAIN_ID" --space-name "$SPACE" \
>   --space-settings '{"JupyterLabAppSettings":{"DefaultResourceSpec":{"InstanceType":"ml.c5.large"}}}'
> ```
> 続いて、許可された経路が引き続き動くことを確認します。一覧にあるタイプでの Studio の
> **Run space**（§8 の手順 4b）と、Studio のスペースページからのストレージ変更です。どちらかが
> *explicit deny* で失敗したら、`infra/av30_constructs/sagemaker.py` から
> `DenyNonParticipantInstanceTypes` 文を削除して再デプロイしてください。API の上限はこの文が
> なくても動作します。

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
ダッシュボードでネイティブ解像度 / フル 720p に届くのは `ml.p4d.24xlarge` だけです。クォータを
申請する前に、下の表の p4d の行を読んでください。

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
| ml.m5.xlarge | L-77B8159A | 11 | ≥0 | CPU 代替（M4） |
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
| ml.g6.24xlarge | L-8ACE1754 | 2 | ≥0 | M2/M3 代替（4× L4、96 GB） — g5.12xlarge と同形状だが高価; **ap-northeast-2 では 0** |
| ml.p4d.24xlarge | L-AD63F1D2 | 2 | 0（意図する場合のみ引き上げ） | M2、M3、M5、M6、M8、M9 の代替 — 唯一のネイティブ解像度パス（8× A100、us-west-2 で約 $25.25/時）。**デフォルトは 0 で、提供するつもりがなければそのままにしてください** — 0 ならダッシュボードは実行中のアプリに触れる前に拒否します |

> **提供しないタイプ: `ml.g7e.*`、`ml.p5.*`、`ml.g6.48xlarge`**、および表にないすべての
> タイプ。`change_instance` が 400 で拒否するため、ダッシュボードのためにクォータを取る必要は
> ありません。g7e はネイティブ解像度への最も安価な経路（96 GB カード 1 枚、約 $4.20/時）ですが、
> ap-northeast-2 では Studio 向けに販売されておらず、このラボで実行したモジュールもないため一覧に
> 入れていません。Studio でもこれらのタイプは拒否されます（上記）。確認の結果、Deny が届かない
> 経路があれば、その経路ではクォータが最後の歯止めです。

部屋のサイジング: 各モジュールの**推奨**インスタンスを同時参加者数以上で申請し、案内するつもりの
1〜2 個のフォールバックについては、少なくとも表示された最小値を申請してください（容量エラーが
発生すると、ダッシュボードに代替が表示されます）。すべての代替のクォータは**不要**です —
実際に部屋に案内するものだけです。GPU モジュールを **g5.12xlarge**（推奨 — 重量級モジュールの推奨値のうち、us-west-2 と
ap-northeast-2 の両方で 0 でない唯一のタイプ）に統一する場合は、
それを参加人数以上に申請し、p4d は提供するつもりがなければデフォルトの 0 のままにしてください。

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

> **ユーザーごとの S3 分離（§0）より前にデプロイしたスタックを更新する場合: まずすべての
> アプリを停止してください。** このバージョンは Studio ドメインの
> `ExecutionRoleIdentityConfig` を `USER_PROFILE_NAME` に切り替えますが、SageMaker は
> ドメイン内に実行中のアプリが 1 つもないときにしかこの変更を受け付けません。ライブの
> ドメインにまだこの設定がない場合、`deploy.sh` はドメインのアプリ一覧を取得し、`Deleted`
> でも `Failed` でもないアプリが 1 つでもあれば、アプリごとに `delete-app` コマンドを表示して
> **デプロイを拒否します**。スタック、ドメイン、アプリ一覧のいずれかを取得できない場合も、
> 推測せずに拒否します。アプリを停止してもホームボリュームと S3 のデータは残り、ドメインは
> その場で更新されます（domain id は変わりません）。その後:
> - 参加者はアプリを起動し直します。切り替え前に起動したセッションには source identity が
>   なく、自分の `users/<id>/` でも `AccessDenied` になります（§13）。
> - 旧ポリシーのまま既にコホートを運用したスタックでは、どの参加者も他の参加者の
>   `.av30-progress.env` のトークンをコピーできた可能性があります。気になる場合は、該当
>   ユーザーを削除して作り直し、トークンを再発行してください。
> - **以前のコミットを再デプロイしてロールバックしないでください。** trust policy 変更より
>   前のコミットは `sts:SetSourceIdentity` を外してしまう一方、ドメインは引き続き source
>   identity を要求するため、アプリとジョブの作成が失敗します。ロールバックは
>   `execution_role_identity_config="DISABLED"` と旧 S3 ステートメントを明示したコミットで行い、
>   trust のステートメントは残したまま、すべてのアプリを停止した状態でデプロイしてください。
> - 未確認の点: 以後ドメインを変更するデプロイ（LCC の変更、
>   `-c idle_timeout_minutes=...`）のたびに、すべてのアプリを停止する必要があるかどうか。
>   ガードが確認するのは最初の切り替えだけです。そのようなデプロイがドメインの更新で失敗
>   したら、アプリを停止して再実行してください。


```bash
# 必須の環境変数
export ADMIN_EMAIL="you@example.com"       # Cognito 管理者アカウント兼 SNS アラートの送信先
export REGION="us-west-2"                  # 自分で選んだリージョン（§1.5）。以下のコマンドに明示的に渡す
export AWS_REGION="$REGION"                # §6 のシーディングスクリプトが参照
export HF_TOKEN="hf_..."                    # §6 のキャッシュ手順で使用
# 任意: 管理者 API を自分の IP/CIDR に制限（参加者向けルートは開いたまま）
export ADMIN_IP_ALLOWLIST="203.0.113.0/24" # デフォルト 0.0.0.0/0 = WAF なし

# CDK のブートストラップ（アカウント + リージョンごとに 1 回）
cd infra && source .venv/bin/activate && pip install -r requirements.txt
npx cdk bootstrap aws://$(aws sts get-caller-identity --query Account --output text)/$REGION
cd ..

# このリージョンのインスタンス料金表を生成（必須 — ないと Lambda は別リージョンの価格を
# 表示する代わりに import 時に例外を送出します）
./scripts/refresh_instance_rates.py --region "$REGION" --merge

# スタックをデプロイし、両ダッシュボードをビルド/アップロード（約 25 分）。リージョンは明示指定。
./scripts/deploy.sh --region "$REGION"
```

`deploy.sh` は `ADMIN_EMAIL` と `ADMIN_IP_ALLOWLIST` を `--context` 経由で CDK に渡します
（env 変数**ではありません** — `deploy.sh` をスキップして手動で `cdk deploy` を実行する場合は、
`--context admin_email=...` を渡す必要があります。さもないと SNS 予算アラートがプレースホルダーに
戻ります）。最後に**管理者ダッシュボード URL** と **API エンドポイント**を出力します。

**`ADMIN_IP_ALLOWLIST` が制限する範囲。** 指定すると API Gateway のステージに WAF WebACL が
関連付けられ、リスト外の IP からの**管理者 API** 呼び出しをブロックします。参加者向けルート
（`/presigned-url/{userId}`、`/sessions/{id}/instance-type|storage|progress|app-status`、
`/modules/{id}/instance-options`）はどの IP からでも許可されます。参加者ダッシュボードは各参加者の
ブラウザで動き、ノートブックは SageMaker マネージドの egress から進捗を送信するためです。
もちろん、これらのルートも参加者トークンがなければ呼び出せません。2 つの CloudFront
ディストリビューションには WAF がないため、リスト外の IP からでも管理者ダッシュボードと Cognito の
サインイン画面は開きます。ただしデータの呼び出しはすべて **"Failed to fetch"** で失敗し、
ブラウザの Network タブでは `OPTIONS` プリフライトが **403** になります。管理者の呼び出しは常に `Authorization` と
JSON の `Content-Type` を送るため、ブラウザが毎回プリフライトを行うからです。対処は自分の IP を
リストに追加することです。**参加者や SageMaker の IP レンジは追加しないでください。** 追加する
必要はなく、追加するとそのアドレスから管理者 API への経路が開くだけです。

**どの IP を登録するか。** ターミナルではなく**ブラウザ**が AWS に出ていくアドレスを登録して
ください。社内プロキシや VPN を使っていると、ブラウザの通信は別のアドレスから出ていくことが
よくあります。管理者ダッシュボードを開く**ブラウザで** https://checkip.amazonaws.com を開いて
確認し、各管理者が使うすべてのネットワーク（オフィス、VPN、自宅）をカンマ区切りの CIDR で
登録してください。プロキシの出口アドレスは変わることがあり、変わると上記の "Failed to fetch"
が発生します。リストを変更するには新しい値で `deploy.sh` を再実行すると、IP セットがその場で
更新されます。

**以後のデプロイでも維持する。** `ADMIN_IP_ALLOWLIST` を未設定にすると `0.0.0.0/0` となり、
WAF が削除されます。そのため、スタックにすでに許可リストがある場合、`deploy.sh` はこの変数なしの
実行を**拒否**し、再利用する現在のリストを表示します。許可リストを意図的に外すには
`ADMIN_IP_ALLOWLIST=0.0.0.0/0` を明示してください。

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
> `hf-cache` 参照は S3 から*読む*側で、書く側が存在せず、唯一のレシピが GPU アプリ上の手動手順でした
> （現在は廃止しています。下の警告を参照）。`cache_models.sh` は代替になりません — 別のプレフィックス
> （`model-cache/`）に別のレイアウト（フラットな `hf download --local-dir`。`models--org--name/snapshots/<sha>/…`
> ではない）で書きます。
>
> 結果として 2 点が実際に問題になりました:
> * **新しいリージョンでは再構築ではなくコピー。** シード済みリージョンからバケット間 `aws s3 sync`
>   （[ADDING_A_REGION.md](ADDING_A_REGION.md) §4）。2026-09-26 に ap-northeast-2 を
>   `cache_models.sh` でシードし、M5/M6/M9/M10 が動かない状態で出荷しました。
> * **推測せず検証する。** `./scripts/check_seeding.sh --region <r>` がランタイムの glob がテストする
>   `models--nvidia--*` ディレクトリ 5 つと、固定された `tokenizer.pth` blob をアサートします。
>   `cache_models.sh` が正常終了したことは、このプレフィックスについて何も証明しません。

M5/M6/M9 はゲート付きチェックポイントを実行時に HF **独自のキャッシュレイアウト**経由で
ロードします（M9 は隠れた Cosmos-Reason2-8B バックボーンもプルします）。`setup_cosmos_env.sh` が
`hf-cache/hub/` を `HF_HOME` に復元し `HF_HUB_OFFLINE=1` を設定するため、参加者はトークンなしで
オフライン実行できます。シードは**管理者ワークステーションから、管理者の認証情報で**行います:
```bash
# 2 つ目以降のリージョン: すでに動いているリージョンからバイト単位でそのままコピー（README step 6b）。
aws s3 sync s3://av30lab-shared-data-<account>-<seeded-region>/hf-cache/ \
            s3://<shared>/hf-cache/ --source-region <seeded-region> --region "$AWS_REGION"
# 最初のリージョン: 固定されたマニフェストからツリーを構築（GPU 不要、スクラッチ約 65 GiB）。
AWS_REGION="$AWS_REGION" HF_TOKEN=hf_... ./scripts/cache_hf_tree.sh
./scripts/check_seeding.sh --region "$AWS_REGION"
```

**`.no_exist` マーカー（M9）。** `check_seeding.sh` は、`Alpamayo-1.5-10B` と `Cosmos-Reason2-8B` の下に
ある 0 バイトの `models--*/.no_exist/<revision>/<file>` ファイル数個も数えます。HuggingFace は、
*オンライン*でのロード中にあるファイルがアップストリームに存在しないと分かったときにこのファイルを残します。
ダウンロードでは作られないため、`cache_hf_tree.sh` は `scripts/hf_cache_manifest.tsv` に `no_exist` 行として
記録されたマーカーだけを作成します。バケット間コピーではマーカーも一緒にコピーされます。マニフェストに
マーカーが記録されていない場合、`cache_hf_tree.sh` だけで作ったツリーは 2 つのリポジトリのオブジェクト数が
それぞれ 15/16、17/22 となり、チェックは失敗します。マーカーがないときに M9 が実際にオフラインで失敗するか
はまだ試していないため、チェックは引き続きマーカーを数えます。マーカーを一度記録してから、マーカーだけを
アップロードしてください（トークンもダウンロードも不要です）:
```bash
# マーカーを持つツリーから記録（例: 以前の GPU アプリ手順でシードしたリージョン。読み取り専用の一覧取得）:
aws s3 ls s3://av30lab-shared-data-<account>-<seeded-region>/hf-cache/hub/ --recursive \
  --region <seeded-region> | ./scripts/cache_hf_tree.sh --record-markers
AWS_REGION="$AWS_REGION" ./scripts/cache_hf_tree.sh --markers-only
```
そのようなツリーがない場合は、自分の GPU アプリで M9 をオンラインで一度実行するとマーカーが作られます。
下のクリップ手順のステップ 1 と 3 を参照してください。`--record-markers` はキー名だけを読み、オブジェクトの
中身は読みません。空でないマーカーや、マニフェストがダウンロードするファイルを隠してしまうマーカーは拒否し、
マニフェストが固定していないリビジョンはスキップします。更新したマニフェストは自分のリポジトリのコピーに
コミットしておいてください。そうすれば、次に最初のリージョンを立ち上げるときは `cache_hf_tree.sh` が
マーカーまで直接作成します。

> **Studio のターミナルから `hf-cache/` に書き込まないでください。管理者の AWS キーを Studio の
> ターミナルに貼り付けることもしないでください。** このガイドの以前の版では GPU JupyterLab アプリから
> キャッシュをアップロードしており、そのために SageMaker 実行ロールが `hf-cache/*` に書き込める必要が
> ありました。しかしこのロールは全参加者で共有され、全参加者のカーネルがこのプレフィックスを読み込みます。
> M9 は `hf-cache/alpamayo-demo/*.pt` を `torch.load(weights_only=False)` で開きますが、これはファイルを
> unpickle するため、中に含まれるコードが実行されます。つまり 1 人の参加者が、他のすべての参加者の権限で
> コードを実行できる状態でした。この書き込み権限は削除したため、Studio アプリから `hf-cache/` への
> `aws s3 cp`/`sync` は意図どおり `AccessDenied` になります。これを避けるために管理者キーをターミナルに
> 入れるのはさらに危険です。アプリのホームディレクトリは起動のたびに S3 の `users/<profile>/` から
> 同期されるため、そこに仕込まれた `.bashrc` にキーを盗まれる可能性があります。

> **この変更より前にデプロイしたスタックをアップグレードする場合。** これまでは全参加者が `hf-cache/*` に
> 書き込めたため、監査するまではこのプレフィックスを信頼しないでください。このプレフィックスに依存する前、
> そしてこのリージョンをコピー元として使う前に監査してください。コピーすると差し替えられたオブジェクトも
> 新しいリージョンにそのまま持ち込まれ、`check_seeding.sh --source-region` は 2 つのリージョンを互いに
> 比べるだけなので、それに気づけません。共有バケットはバージョニングが有効なので、読み取り専用の一覧取得
> だけですべての書き込みの履歴を確認できます。読み取り専用の認証情報を使ってください:
> ```bash
> # 最新でないバージョンと削除マーカー: 1 つ 1 つが最初のアップロード後に行われた書き込みです。
> aws s3api list-object-versions --bucket <shared> --prefix hf-cache/ --region <r> \
>   --query 'Versions[?IsLatest==`false`].[LastModified,Key]' --output text
> aws s3api list-object-versions --bucket <shared> --prefix hf-cache/ --region <r> \
>   --query 'DeleteMarkers[].[LastModified,Key]' --output text      # "None" = 削除なし
> # 現在のバージョンを新しい順に: 最初にシードした時点より後のものは確認が必要です。
> aws s3api list-object-versions --bucket <shared> --prefix hf-cache/ --region <r> \
>   --query 'Versions[?IsLatest].[LastModified,Key]' --output text | sort -r | head -20
> ```
> 見つかった項目はすべて調査してください。最も重要なのは、ロードするとコードが実行される pickle 形式の
> ファイルです。`alpamayo-demo/*.pt`、そして hub ツリーにある Cosmos-Transfer2.5 と Cosmos-Predict2.5 の
> `*_ema_bf16.pt`、Predict2.5 の `tokenizer.pth`、Guardrail1 の `safety_filter.pt` と
> `Resnet50_Final.pth` がこれに当たります。監査の結果にかかわらず、`alpamayo-demo/*.pt` は引き継がずに、
> 下の手順で作り直して公開してください。オブジェクトのバージョン削除は破壊的な操作なので、実行する前に
> 別途承認を得てください。

**M9 はデモクリップも必要とします。** そのデータセットはオフラインでは読めず、クリップは GPU アプリ上の
`a1_5` venv の中で生成する必要があります。そこで、クリップの*生成*は GPU アプリで、*公開*は
ワークステーションで行います。参加者をプロビジョニングする（§9）前に実施してください。シード済みの
リージョンから `hf-cache/` をコピーした場合はクリップも一緒にコピーされているので（`check_seeding.sh` で
確認できます）、公開し直すのでなければステップ 1-3 は飛ばしてください。コピー元のリージョンがこの変更
より前にデプロイされたものなら、一度は公開し直してください（上のアップグレードの注記を参照）。

**始める前に、どの参加者も自分のワークスペースに書き込めないことを確認してください。** クリップは、
参加者のプロファイルが 1 つも存在しないうちに作るか、ユーザーワークスペースのバケットがユーザーごとに
分離された後に作ってください。それまでは、全参加者で共有する実行ロールがすべての `users/<profile>/`
プレフィックスに書き込めます。そしてアプリは起動のたびに `users/<your-profile>/` をホームディレクトリに
コピーします。そのため、仕込まれた `.bashrc` や IPython の起動ファイル、差し替えられた
`scripts/alpamayo_save_clip.py` が、`.pt` とそれについて表示される sha256 の両方を左右でき、あなたが
export した `HF_TOKEN` も見えてしまいます。ハッシュが証明するのは、ファイルがアプリを出た後に変更されて
いないことだけです。すでにワークショップを一度実施したスタックでは、先に参加者のプロファイルを削除してから、
新しく作った自分のプロファイルを使ってください。以前のプレフィックスに仕込まれたファイルはそのまま残り、
同じプロファイルの下に新しいスペースを作っても、そのプレフィックスがそのままコピーされるからです。

1. 自分のプロファイルの GPU JupyterLab アプリで、ライセンス（§3）に同意済みのアカウントの
   `HF_TOKEN` を使って:
   ```bash
   export HF_TOKEN=hf_...
   bash scripts/setup_cosmos_env.sh alpamayo     # build the a1_5 venv
   source /mnt/sagemaker-nvme/cosmos-work/alpamayo_env.sh
   unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE     # this save must be online
   python scripts/alpamayo_save_clip.py --clip 030c760c-ae38-49aa-9ad8-f5650a545d26 \
     --t0-us 5100000 --out /mnt/sagemaker-nvme/m6_work/clips
   ```
   スクリプトは最後に `sha256  <hash>  030c760c-….pt` を出力します。**このハッシュは手で書き写し、
   自分のメモに保管してください。** クリップの横に S3 のファイルとして保存すると、クリップと一緒に
   差し替えられるおそれがあります。

   *`.no_exist` マーカーが必要な場合のみ（上を参照）:* 同じターミナルで推論をオンラインで一度実行し、
   そのとき作られたマーカーを staging に移します。マーカーは空のファイルで、使われるのは名前だけです。
   ```bash
   python scripts/alpamayo_infer.py \
     --clips /mnt/sagemaker-nvme/m6_work/clips/030c760c-ae38-49aa-9ad8-f5650a545d26.pt \
     --out /mnt/sagemaker-nvme/m6_work/out
   aws s3 sync /mnt/sagemaker-nvme/hf/hub "s3://$USER_BUCKET/users/$USER_PROFILE/staging/hub-markers/" \
     --exclude '*' --include '*/.no_exist/*' --exclude '*/snapshots/*'
   ```
2. 次のどちらかの方法で `.pt` をアプリの外へ移します:
   * `cp /mnt/sagemaker-nvme/m6_work/clips/030c760c-*.pt ~/` の後、JupyterLab のファイルブラウザで
     ファイルを右クリックして **Download**。または
   * `aws s3 cp /mnt/sagemaker-nvme/m6_work/clips/030c760c-*.pt "s3://$USER_BUCKET/users/$USER_PROFILE/staging/"`
     （自分のワークスペースのプレフィックスです。実行ロールはここには書き込めますが、`hf-cache/` には書き込めません）。
3. 管理者ワークステーションで、管理者の認証情報を使って:
   ```bash
   CLIP=030c760c-ae38-49aa-9ad8-f5650a545d26.pt
   USERB=av30lab-user-workspace-<account>-$AWS_REGION
   aws s3 cp "s3://$USERB/users/<your-profile>/staging/$CLIP" . --region "$AWS_REGION"   # skip if downloaded
   shasum -a 256 "$CLIP"       # MUST equal the hash from step 1 (Linux: sha256sum "$CLIP")
   aws s3 cp "$CLIP" "s3://<shared>/hf-cache/alpamayo-demo/" --region "$AWS_REGION"
   aws s3 rm "s3://$USERB/users/<your-profile>/staging/$CLIP" --region "$AWS_REGION"
   # ステップ 1 で .no_exist マーカーを staging に置いた場合のみ:
   aws s3 ls "s3://$USERB/users/<your-profile>/staging/hub-markers/" --recursive \
     --region "$AWS_REGION" | ./scripts/cache_hf_tree.sh --record-markers
   AWS_REGION="$AWS_REGION" ./scripts/cache_hf_tree.sh --markers-only
   aws s3 rm "s3://$USERB/users/<your-profile>/staging/hub-markers/" --recursive --region "$AWS_REGION"
   ./scripts/check_seeding.sh --region "$AWS_REGION"
   ```
   ハッシュが一致しない場合、ファイルはアプリを出た後に変更されています。アップロードせず、
   クリップを作り直してください。

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

> **ノートブックの編集:** リポジトリの `notebooks/*.ipynb` が唯一の信頼できる情報源なので、
> ノートブックは直接編集して §6.5 で再同期し、ノートブックが依存するモジュール間の S3
> コントラクトは [DATA_CONTRACT.md](DATA_CONTRACT.md) を参照してください。

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

1. 管理者ダッシュボード → **Add User** → テスト名 + メール → **Provision**。テストユーザーを
   もう 1 人（B）作成してください。手順 4c で比較する相手が必要です。
2. 成功ダイアログから**参加者ダッシュボードリンク**をコピーします（永続的な
   `#userId=&token=` リンク — 5 分間の「Direct workspace URL」**ではありません**）。
3. そのリンクを新しいブラウザで開く → 12 個のモジュールノード（M1〜M12。M0 は概要ノートブックでノードを持ちません）を持つ Pipeline Map が表示され、
   アドレスバーから `#userId=…&token=…` の部分が消えます。
4. **M2** をクリック → **Instance Options** → 推奨の `ml.g5.12xlarge` が事前選択済み →
   **Apply & Restart** → **Open Workspace** → JupyterLab が開きます。
4b. **スコープ付き IAM 条件が実際に解決されるかを確定（無料、約 1 分）。** そのアプリが
   実行中の状態で、テストユーザーとして Studio **自体**を開きます（ディープリンクではなく
   Studio コンソール）。スペースのページで **Run space**、続いて **Open JupyterLab** を
   クリックし、`sagemaker:UpdateSpace` / `sagemaker:CreatePresignedDomainUrl` に対する
   `AccessDenied` が出るかを記録します。メッセージに *explicit deny* とある場合は別の問題です。
   インスタンスタイプの Deny（§2a）によるものなので、フォームがどのタイプを送ったかを確認して
   ください。
   - **AccessDenied なし** → `${sagemaker:DomainId}` / `${sagemaker:UserProfileName}`
     のポリシー変数が実行時に解決されます。したがって `CreateApp`/`DeleteApp` を
     `resources=["*"]` から同じ所有者条件へ狭められます。
     `infra/av30_constructs/sagemaker.py` の `SageMakerStudioAppLifecycle` 文の注記を参照。
   - **AccessDenied が出る** → このアカウントでは解決されません。`CreateApp` は広いままにし、
     参加者にはダッシュボードのボタンを使わせ続けてください。
4c. **ユーザーごとの S3 分離を証明する（新しいスタックごとに必須、§0）。** まずライフ
   サイクルスクリプトのログを確認します。CloudWatch Logs のロググループ
   `/aws/sagemaker/studio` で、テストユーザーのスペースのストリームのうち名前が
   `LifecycleConfigOnStart` で終わる最新のものを開きます。`Notebook bootstrap complete` が
   あり、`WARN: notebook sync failed` や `AccessDenied` が**ない**ことを確認してください。
   同期に失敗してもアプリは止まらないため、この確認をしないとホームディレクトリが空に
   見えるだけです。次に、テストユーザーの JupyterLab ターミナル（`$USER_BUCKET` と
   `$USER_PROFILE` が設定されています）で、2 人目のテストユーザーの ID を `<B-id>` に入れて
   実行します。
   ```bash
   aws s3 ls "s3://$USER_BUCKET/users/$USER_PROFILE/"                  # 成功: 自分のファイル
   aws s3 ls "s3://$USER_BUCKET/users/<B-id>/"                         # AccessDenied
   aws s3 cp "s3://$USER_BUCKET/users/<B-id>/.av30-progress.env" -     # 403 / AccessDenied
   echo probe | aws s3 cp - "s3://$USER_BUCKET/users/<B-id>/probe.txt" # AccessDenied
   aws s3 rm "s3://$USER_BUCKET/users/<B-id>/M1_Data_Exploration.ipynb" # AccessDenied
   aws s3 ls "s3://$USER_BUCKET/"                                      # AccessDenied
   aws sagemaker describe-pipeline --pipeline-name "av30-data-pipeline-<B-id>"  # AccessDenied
   ```
   1 行目が成功すること自体が、セッションに正しい source identity が付いている証拠です。
   source identity がなければ 1 行目も拒否されます。1 行目が拒否された場合は §13 を参照して
   ください。AccessDenied と書いた行のどれかが成功した場合、このスタックは分離されていない
   ので、コホートをプロビジョニングしないでください。
5. **M1**（CPU）をエンドツーエンドで実行し、続いて **M2**（GPU）を実行 — GPU イメージが
   自動選択され、モデルキャッシュが解決されることを確認します。
6. テストユーザーとして **M11** と **M12** を 1 回ずつ実行してください。実データが入るよう、
   M1 と M3 の後に実行します。ジョブクォータ（§2b）と IAM の確認に加え、source identity が
   マネージドジョブまで届くかを確かめる方法はこれしかありません。届かない場合は送信時では
   なくジョブの中で、パイプラインのステップ 1 またはトレーニングジョブが S3 の
   `AccessDenied` で失敗します。
7. 2 人のテストユーザーを両方とも**削除**します（Users タブ → Delete） — アプリ/スペース/プロファイル + S3 を削除します。

---

## 9. 参加者のプロビジョニング（Day 0）

**単一ユーザー:** 管理者ダッシュボード → **Add User** → 名前 + メール → **Provision**。
**参加者ダッシュボードリンク**（永続的、失効しない）を渡します。Users テーブルには
ユーザーごとにコピーボタン付きの **Dashboard Link** 列があります。

**このリンクは bearer credential です。パスワードと同じように扱ってください。** リンクを
持っている人は、ユーザーを削除するまで（§12）その参加者のワークスペースを開き、インスタンスを
変更できます。共有チャンネルではなく、参加者本人に直接送ってください。
- トークンは URL フラグメント（`#userId=…&token=…`）に載せています。ブラウザはフラグメントを
  サーバーに送らないため、CloudFront のログや `Referer` ヘッダーには残りません。
- ダッシュボードはページを開いた時点でトークンをタブの session storage に移し、アドレスバーから
  消します。そのため画面共有やコピーした URL にトークンは現れません。再読み込みしてもログインは
  保たれますが、開いているページを新しいタブで開いたりブックマークしたりした URL では Demo Mode になります。
  参加者には、元のリンクを手元に残して開き直すよう案内してください。
- 以前 `?userId=&token=` 形式で配布したリンクも引き続き使え、同じようにアドレスバーから消えます。
  トークン自体は変わりません（ローテーション機能はありません）。漏れたリンクを無効にしたうえで
  参加を続けてもらうには、ユーザーを削除し（ワークスペースのファイルも削除されます）、
  プロビジョニングし直してください。

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
  提示する代替のどれでも選ぶよう伝えてください。パネルはどのリージョンでも同じ一覧を表示するため、
  絞り込みは API が行います。このリージョンで販売されていないタイプやクォータ 0 のタイプは、実行中の
  アプリに触れる前に理由付きで拒否されます。特定のフォールバックを
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
- **削除・無効化した参加者もすぐには遮断されません。** Delete を実行するか、
  `av30-sessions-v2` テーブルでユーザーの `status` を `active` 以外に変更すると、参加者の
  ダッシュボードトークンは無効になります。ただし API Gateway は token authorizer の判定を
  **最大 60 秒**キャッシュするため、その間はそのトークンで参加者向けのルートを呼び出せて
  しまいます。Open Workspace、インスタンス変更、ストレージ拡張はハンドラー側で `status` を
  確認するので、即座に拒否されます。すぐに遮断したい場合は、削除の直後に stage の
  authorizer キャッシュをフラッシュしてください。

  ```bash
  API_ID=$(aws cloudformation describe-stacks --stack-name Av30BlueprintLabStack --region "$AWS_REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text | cut -d/ -f3 | cut -d. -f1)
  aws apigateway flush-stage-authorizers-cache --rest-api-id "$API_ID" --stage-name prod --region "$AWS_REGION"
  ```

  フラッシュはすべてのトークンが対象ですが、他の参加者は次のリクエストで authorizer が
  もう一度呼ばれるだけです。すでに開いている Studio のブラウザセッションはこのキャッシュを
  通りません。そのセッションは、Delete が app・space・user profile を削除した時点で終了します。
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
| M12 ジョブが送信時に失敗（`CreateTrainingJob` で `AccessDeniedException`） | 実行ロールが許可するのは `av30-m12-distributed-<自分のプロファイル>-*` という名前のトレーニングジョブだけで（プロファイルはセッションの source identity から来ます）、ノートブックの `JOB_NAME` がこれに一致する必要があります。外れるケースは 2 つです。M9→M12 の再採番より前のデプロイは `av30-m9-*` のみを許可したままです。あるいはカーネルに `USER_PROFILE` がなく、`PROFILE` が `default` にフォールバックして名前に誤ったプロファイルが入っています（ライフサイクルスクリプトが値を設定するよう、アプリを再起動してください）。m5.xlarge の**ジョブ**クォータ（§2b）は別の稀な原因です — まずエラーを確認してください: `AccessDenied` は IAM の名前スコープ、`ResourceLimitExceeded` はクォータ。|
| ユーザーごとの分離へのアップグレード（§5）後: ホームディレクトリが空、またはノートブックがない、`aws s3 ls s3://$USER_BUCKET/users/$USER_PROFILE/` が `AccessDenied`、あるいは M11/M12 のジョブがジョブ内で S3 の `AccessDenied` により失敗する | セッションに source identity がないため、`users/${aws:SourceIdentity}/` のスコープが何にも一致しません（fail-closed）。順に確認してください。(1) ドメインの切り替え前に起動したアプリです: 停止して起動し直してください。(2) 管理者の認証情報で `aws sagemaker describe-domain --domain-id <id> --query DomainSettings.ExecutionRoleIdentityConfig` が `USER_PROFILE_NAME` を出力し、`aws iam get-role --role-name av30lab-sagemaker-execution-role-<region> --query Role.AssumeRolePolicyDocument` に `sts:SetSourceIdentity` が含まれている必要があります。(3) ライフサイクルスクリプトの `LifecycleConfigOnStart` ログで、同期が拒否されたかどうかを確認します（§8 の手順 4c）。(4) 両方の設定が正しいのに、新しく起動したアプリやジョブが拒否され続ける場合、このアカウントではそのセッション種別に source identity が届いていません。§5 の手順でロールバックしてください。S3 ステートメントを `users/*` に広げないでください。全員の分離が失われます。 |
| GPU インスタンスで参加者が「No GPU detected」 | CPU イメージが選択されている — Instance Options で再 Apply。 |
| M5/M6/M9 のセットアップセルが "this region has no usable offline HuggingFace cache and no HF_TOKEN" で停止（exit 2） | このリージョンに `hf-cache/hub/` が未シード（§6.3）。シード後 `./scripts/check_seeding.sh --region <r>`。このメッセージは*修正後*の挙動です — 2026-09-26 より前は同じ条件が沈黙で、セットアップセルが "environment ready" を表示した後、M5 が `torchrun` の中で 4 秒で `ChildFailedError` により停止し CUDA out-of-memory を指していました。まだ古い形が見える場合、参加者は古いステージング済み `setup_cosmos_env.sh` を使っています。 |
| M5/M6/M9 が `Local entry not found … offline mode is enabled` で失敗 | 復元されたキャッシュが**部分的**です。中断された `aws s3 sync` が典型的な原因で — **同じ sync をもう一度実行してください**。欠けているもの・サイズ違いのものを再コピーして再開します。`sync` が検出できないのはサイズが正しく内容が誤ったオブジェクトです（size+mtime 比較）。`check_seeding.sh --source-region <seeded>` が CRC64 不一致を報告したら、そのオブジェクトだけ削除して再 sync してください。 |
| M7 トレーニングセルが gsplat で失敗する | M7 セル 3（`scripts/setup_gsplat_env.sh`）を再実行 — CUDA ビルドはセッションごとで、アプリ再起動時にリセットされます。§11。 |
| M9 がクリップのロードに失敗する | デモの `.pt` が `hf-cache/alpamayo-demo/` にアップロードされていない（§6.3）。 |
| Studio のターミナルから `hf-cache/` への `aws s3 cp`/`sync` が `AccessDenied` になる | 想定どおりです。全参加者で共有する実行ロールには、共有バケットへの書き込み権限を意図的に付けていません（§6.3）。シードと公開は管理者ワークステーションから行い、管理者キーを Studio のターミナルに貼り付けないでください。 |
| M10 ノートブックに何も表示されない（cell-4 が "No M10 AlpaSim results found in S3" を出す） | `m10-reference/` リファレンス評価が未実行（§6.4）。 |
| M10 のメトリクス・グラフは出るが**動画だけ**が空白 | **バンドル欠落ではなく、§6.4 を再実行してはいけない。** コーデックの問題: AlpaSim レンダラーが MPEG-4 Part 2 で書き出し、Chrome/Firefox/Edge はこれをデコードできない。cell-7 が検出したコーデックを出力する。GPU ホスト不要で、そのオブジェクト 1 つを H.264 に置き換えればよい: `aws s3 cp s3://$SHARED_BUCKET/m10-reference/eval/eval.mp4 .` の後 `ffmpeg -i eval.mp4 -vf scale=1280:-2 -c:v libx264 -pix_fmt yuv420p -movflags +faststart -an eval_h264.mp4` を実行し `m10-reference/eval/eval.mp4` に上書きする。`scripts/alpasim_ec2_setup.sh` はアップロード時に変換するようになったので、その変更以降に作られたバンドルは既に H.264 である。 |
| M4 の検索デモが**同じキャプションを複数回**ランクし、インデックスセルが削除で `403 authorization_exception` を出力 | コレクションのデータアクセスポリシーが **`aoss:DeleteIndex`** 付与より前のもので、M4 がインデックスを空にできません。AOSS は呼び出し側指定の `_id` を拒否するため `index()` は常に INSERT — 再実行ごとに全文書のコピーが追加されます（実測: キャプション 24 件に対し文書 24 → 48 → 72 → 96 → 120）。参加者ロールはポリシーを修正できません: `aoss:UpdateAccessPolicy` は意図的に付与していません（`collection/*` 範囲では、ある参加者が他の参加者のコレクションに到達できてしまうため）。admin 認証情報で**コレクションとデータポリシーの両方**を削除してください（ポリシーが残ればそれが古いものです）。その後参加者が Run All すると M4 が権限込みで再作成します: `aws opensearchserverless list-collections --region $REGION --query 'collectionSummaries[?starts_with(name,\`av30-semantic-\`)].[id,name]' --output text` → `aws opensearchserverless delete-collection --id <id> --region $REGION` → `aws opensearchserverless delete-access-policy --name <name>-access --type data --region $REGION`. |
| SNS 予算アラートが placeholder@example.com に届いた | `--context admin_email` なしでデプロイされた — `deploy.sh` で再デプロイ。 |
| 参加者リンクが「Demo Mode」と表示される | 素の URL を開いたか、開いているダッシュボードを新しいタブやブックマークから開いた（トークンはページを開いた時点でアドレスバーから消える）。元の `#userId=&token=` リンクを開き直してもらうか、再送してください。 |
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
