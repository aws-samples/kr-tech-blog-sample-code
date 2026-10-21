# リージョンの追加

すでに運用しているリージョンに手を触れることなく、同じアカウント内の別の AWS リージョンに
ラボの**2 つ目の独立したコピー**を立ち上げる手順です。

これはマルチリージョンデプロイ*ではありません*。各リージョンは自己完結したラボであり、独自の
Studio ドメイン、バケット、API、Cognito プール、ダッシュボード、予算を持ちます。共有されるのは
AWS アカウントそのものだけです — そして落とし穴はまさにそこにあります。ごく一部の AWS 名前空間が
リージョン単位ではなく**アカウントグローバル**だからです。

以下のすべては、稼働中の `us-west-2` と並行して `ap-northeast-2` をデプロイしながら、アカウント
`<aws-account-id>` で実測した値です。*(定価)* と記した数値は AWS の公表価格によるもので、そのセッション
中の API 呼び出しによるものではありません。

---

## 0. 対象リージョンは本当に空か？

まずこれを実行してください。このアカウントでは「空のリージョン」という前提がすでに崩れていました —
`ap-northeast-2` には無関係な `FAST-stack` が存在します。

```bash
export R=ap-northeast-2
# アカウント番号は貼り付けずに取得してください: §3 でこの値を EXPECTED_ACCOUNT_ID として
# エクスポートし、scripts/deploy.sh は不一致ならデプロイを拒否します
# ("ERROR: account mismatch")。ハードコードすると所有者以外の全員がブロックされます。
export ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

aws cloudformation describe-stacks --region $R --stack-name Av30BlueprintLabStack
aws s3api list-buckets --query "Buckets[?ends_with(Name,'$R')].Name"
aws sagemaker list-domains --region $R
aws sagemaker list-apps --region $R --query 'Apps[?Status==`InService`]'   # billing NOW
aws efs describe-file-systems --region $R --query 'FileSystems[].Name'     # orphan source
aws apigateway get-account --region $R --query cloudwatchRoleArn           # see §3
aws iam get-role --role-name av30-alpasim-m7                              # account-global
```

それぞれが重要な理由:

- **S3 のバケット名はグローバルです。** 中断した試行で `av30lab-*-$ACCOUNT-$R` バケットが
  残っていると、`cdk deploy` がバケット作成時に失敗します。
- **Studio はドメインごと・リージョンごとに EFS ファイルシステムを作成し**、経路によっては
  スタック削除後も残存します。このアカウントには、まさにそれが原因の孤立したファイルシステムがあります。
- **すでに `InService` の `ml.*` アプリは今まさに課金されています** — そのリージョンがアイドルだと
  決めつける前に確認してください。
- **`av30-alpasim-m7`**（M10 の IAM ロール + インスタンスプロファイル）は**アカウントグローバルで
  サフィックスが付きません**。どこであっても M10 を実行する前に、後述の「既知の落とし穴」を参照してください。

---

## 1. CDK のブートストラップ

```bash
aws cloudformation describe-stacks --region $R --stack-name CDKToolkit >/dev/null 2>&1 \
  || npx cdk bootstrap aws://$ACCOUNT/$R
```

衝突は起きません: ブートストラップのロール名にはすべて `-{account}-{region}` が付きます。

---

## 2. クォータ（1 週間ほど前に実施）

**スコープ: クォータは `(アカウント × リージョン)` 単位です。** コンソールの
「Applied **account-level** quota value」列や「Adjustability: **Account level**」という表示は
「アカウント全体で 1 つの値」のように読めます — しかし、そういう意味ではありません。これらのラベルが
表示しているのは、リージョンの問いに答えるフィールドとは**別のフィールド**であり、API はこの 2 つを
明示的に区別します:

| フィールド | 何に答えるか | ここでの値 |
|---|---|---|
| `QuotaAppliedAtLevel` | アカウント **対 リソース** — コンソールがラベル表示しているもの | `ACCOUNT` |
| `GlobalQuota` | アカウントグローバル **対 リージョンごと** | `false` |

`list-service-quotas --quota-applied-at-level` は列挙値 `[ALL, ACCOUNT, RESOURCE]` を取り、その
help 自身が「filters the response to return applied quota values for the ACCOUNT, RESOURCE, or ALL
levels」と述べています。つまり *アカウントレベル* は *リソースレベル* の対概念であり（個々の
リソース単位ではなくアカウント単位で調整されている、という意味）、それは**コンソールがそのとき
表示しているリージョンの内側での**話です。クロスリージョンでの共有については何も述べていません。

リージョンスコープであることの、独立した 3 つの証拠:

- **`GlobalQuota`** は SageMaker のクォータ **2,258** 件すべてで `false` です（ページネーションを
  完走した件数）。対比として、IAM は 23/23、Route 53 は 9/9 が `true`、S3 は混在しています —
  `General purpose buckets` は `true` ですが、そのレプリケーション関連クォータは `false` です。
- `QuotaArn` にリージョンが埋め込まれているため、これらは別個のリソースです:
  `arn:aws:servicequotas:us-west-2:…:sagemaker/L-8ACE1754` と
  `arn:aws:servicequotas:ap-northeast-2:…:sagemaker/L-8ACE1754`。
- 同じアカウント、同じコードでも**適用値が異なり**（2 対 0）、
  `list-requested-service-quota-change-history` の履歴も完全に別系統です — 引き上げはリージョンごとに
  申請され、承認されます。

したがって、リージョン A で承認された引き上げはリージョン B には何の効果もありません。クォータ
**コード**は共通ですが、**値、申請、さらにはどのクォータが存在するか**は共通ではありません —
`ml.g6.24xlarge for notebook instance usage` は us-west-2 には存在し、ap-northeast-2 にはまったく
存在しません（"g6.24xlarge" の検索ヒット数が 10 対 9）。

### このラボが実際に提供するインスタンスタイプでの実測値

| クォータ（Studio JupyterLab アプリ） | コード | us-west-2 | ap-northeast-2 | 使用箇所 |
|---|---|---|---|---|
| `ml.t3.medium` | `L-71FAF417` | 2500 | 2500 | デフォルトのワークスペース |
| `ml.g5.xlarge` | `L-988CE6C5` | 5 | 5 | M7 (Nerfstudio) |
| `ml.g5.12xlarge` | `L-8D2ED7BF` | 5 | 5 | M2/M3 |
| `ml.g5.24xlarge` | `L-F087CCFC` | 2 | 2 | M5/M6/M8/M9 の代替（24 GB ティア） |
| `ml.g5.48xlarge` | `L-83AB5D73` | 2 | 2 | M6 のシャード実行 |
| `ml.p4d.24xlarge` | `L-AD63F1D2` | 2 | **2** | 40 GB ティア — 720p、ガードレール ON |
| **`ml.g6.12xlarge`** | `L-962247BA` | 2 | **0** ⚠ | M2/M3 の代替 |
| `ml.g6.24xlarge` | `L-8ACE1754` | 2 | **0** | ダッシュボードは推奨しない（g5.12xlarge と同ティアでより高価） |
| `ml.p5.48xlarge` | `L-B41FBF28` | 1 | **0** | 80 GB ティア |
| `ml.m5.xlarge` *学習* | `L-CCE2AFA6` | 30 | 30 | M12 |
| `ml.m5.xlarge` *処理* | `L-0307F515` | 16 | 16 | M11 |

> **上限はクォータだけではありません — AZ カバレッジも上限です。** Studio アプリはドメインが
> サブネットを持つアベイラビリティゾーンでしか起動できず、GPU タイプはすべての AZ で販売されて
> いません。2026-09-25 にこのアカウントで
> `describe-instance-type-offerings --location-type availability-zone-id` により実測
> （AZ *ID* 基準。a/b/c の*名前*はアカウントごとに別の AZ を指します）:
>
> | リージョン | g5.* 販売 AZ | p4d 販売 AZ | ドメイン到達（`max_azs` 修正前） |
> |---|---|---|---|
> | ap-northeast-2 | apne2-az1, az3, az4 | apne2-az2, az4 | g5 は **3 中 1**。p4d は g5 と**共有 AZ が 0** |
> | us-west-2 | usw2-az1, az2, az3 | 4 つすべて | 3 中 2 |
>
> `apne2-az2` は g5 も g6 も一切販売していません。VPC はすべての AZ にサブネットを作るように
> なり（`infra/av30_constructs/network.py`, `max_azs=99`）構造的に解消されますが、**再デプロイ**
> しないと反映されず、`check_quotas.py` はまだカバレッジを報告しません。したがって「OK 5」と
> 表示されたタイプでもアプリ起動時に
> `EC2InsufficientCapacityError: … unavailable in supported availability zones [...]`
> で失敗しえます。クォータ 5 / 使用 0 の状態で 3 タイプ連続でこの失敗を実測しました。

**ap-northeast-2 では `g6` と `g6e` ファミリー全体が 0 です** — 24xlarge だけではありません。`g7e`
は*両方の*リージョンで 0 です。

**ただしソウルが GPU 不可というわけではありません。** `g5` は全レンジで利用でき、
`p4d.24xlarge` はすでに 2 で承認済みなので、**クォータ申請をまったく行わずに**今日からラボを
ソウルで実行できます。ダッシュボードの推奨タイプに `g6` が 1 つも含まれていないからです:
M2/M3 と重量級の 4 モジュール（M5/M6/M8/M9）はいずれも `ml.g5.12xlarge`（ソウルのクォータ 5）を
デフォルトとし、代替が `ml.g5.24xlarge`（同じ 22.5 GB ティアで約 44% 高価）、品質重視の選択肢が
`ml.p4d.24xlarge`（40 GB ティア）です。この 4 モジュールは以前 `ml.g6.24xlarge`（ソウルのクォータ
**0**）をデフォルトにしていましたが、形状が同一（4 GPU × 22,888 MiB）で安価、かつ両リージョンで
クォータ 5 の `ml.g5.12xlarge` に変更されました。ただしソウルの価格が us-west-2 より約 23% 高い
ことには留意してください。

この表を読むのではなく、プリフライトを実行してください — ライブのクォータ値を解決し、生成済みの
料金表と突き合わせ、各不足がどのモジュールに影響するかを名指しします:

```bash
./scripts/check_quotas.py --region $R --participants 10
```

参加者ダッシュボードが推奨するタイプのいずれかが実行できない場合、非ゼロで終了します。`deploy.sh`
も `cdk deploy` の**前に**これを自動実行します。このアカウントでの実測結果: **どちらのリージョンも同時 5 名までは
合格し、10 名ではどちらも合格しません** — 上限は両リージョンとも `ml.g5.12xlarge` /
`ml.g5.xlarge` のクォータ 5 で同じなので、この点でソウルが不利ということはありません。これを前提に
受講者数を計画するか、その 2 タイプのクォータを引き上げてください:

```bash
# Must be filed IN the target region. The script prints the exact code for each shortfall.
aws service-quotas request-service-quota-increase --region $R \
  --service-code sagemaker --quota-code L-8D2ED7BF --desired-value 10   # ml.g5.12xlarge
aws service-quotas request-service-quota-increase --region $R \
  --service-code sagemaker --quota-code L-988CE6C5 --desired-value 10   # ml.g5.xlarge
```

**申請する前に、そのインスタンスがそのリージョンで Studio 向けにそもそも提供されているかを
確認してください。** 提供状況はリージョンごと*かつ利用タイプごと*です — 「そのファミリーは
そのリージョンにあるか」は誤った問いであり、判断を誤らせます:

```bash
aws pricing get-products --region us-east-1 --service-code AmazonSageMaker \
  --filters Type=TERM_MATCH,Field=instanceType,Value=ml.g6.24xlarge \
            Type=TERM_MATCH,Field=regionCode,Value=$R \
            Type=TERM_MATCH,Field=platoinstancetype,Value=Studio-JupyterLab \
  --query 'length(PriceList)'
```

実測: `ap-northeast-2` は実在する `APN2-Studio:JupyterLab-ml.g6.24xlarge` プロダクトを返すため、
0 というクォータは引き上げる価値があります。**`eu-west-1` はそのタイプの Studio プロダクトを
0 件返します** — そこでのクォータ申請は無駄です。代わりに `g5` の経路へ誘導してください。

---

## 2.5. このリージョンの料金表を生成 — デプロイの**前に**

**スキップせず、§3 の後にも回さないでください。** 事前生成されているのは 5 リージョンだけです
(`ap-northeast-1`, `ap-northeast-2`, `eu-west-1`, `us-east-1`, `us-west-2`)。それ以外の
リージョンではデプロイが**成功した後**に API 全体が 500 を返します。
`infra/lambda/shared/config.py` が **モジュール import 時**に `INSTANCE_RATES` を解決するためです:

```python
INSTANCE_RATES = _rates_for_region(AWS_REGION)   # UnpricedRegionError が発生
```

15 個の Lambda ハンドラのうち **14 個**がこのモジュールを import します —
`token_authorizer` と `create_user` も含むため、**サインインすらできません**。
「あるエンドポイントの価格が違う」という話ではありません。

```bash
./scripts/refresh_instance_rates.py --region $R --merge   # --merge は他リージョンを保持
grep -c "\"$R\":" infra/lambda/shared/instance_rates.py  # 1 が返るはず
```

1 回の取得で**2 つのファイル**を書きます: 上記の Lambda アセットと
`scripts/av30_instance_rates.py`。後者は §4 が全参加者ワークスペースへ同期するため、
ノートブックのコストセルが**このリージョン**の価格を示します。したがって後から生成すると
§3 **と** §4 を再実行する必要があります。

`pricing:GetProducts`（Price List API は us-east-1 のみ。スクリプトはそこを呼び、`$R` を
フィルタとして渡します）と、クォータコード取得のための `servicequotas:ListServiceQuotas`
が必要です。

---

## 3. デプロイ

```bash
export EXPECTED_ACCOUNT_ID=$ACCOUNT
export ADMIN_EMAIL=you@example.com
export ADMIN_IP_ALLOWLIST=1.2.3.4/32          # omit to allow all
./scripts/deploy.sh --region $R
```

`deploy.sh` は `admin_email`、`admin_ip_allowlist`、`region` の各コンテキストを自動で設定し、
`--context region=$R` を固定します。これにより `infra/app.py` が、シェルのガードが直前に確認したのと
別のリージョンを解決してしまうことがなくなります。観測された実行時間は**約 3 分**、リソース数 176 です。

**新しいリージョンでは以下を設定しないでください:**

| コンテキスト / 環境変数 | 設定してはいけない理由 |
|---|---|
| `OWNER_TAG` | `Owner` タグがデフォルトと異なるスタックを更新する場合のみ使います。SageMaker はドメインの**タグ**を置換が必要な属性として扱うため、不一致があると Studio ドメインが置換され、その EFS が孤立します。別の `Owner` タグで作成された既存スタックを更新する場合にのみ必要です — `deploy.sh` が不一致を拒否し、再実行用の正確な `OWNER_TAG=...` コマンドを出力します。 |
| `HOSTED_UI_DOMAIN_EXISTS` | ここで最も危険なレバーです。Cognito ホステッド UI ドメインの宣言をスキップするため、**サインインエンドポイントを持たない**プールができてしまいます。これは us-west-2 に既存の、管理外のドメインが 1 つだけあるという事情のためだけに存在します。 |
| `APIGW_ACCOUNT_ROLE` | `AWS::ApiGateway::Account` は名前を持たない**アカウント・リージョンごとのシングルトン**で、無条件の `PATCH /account` として実装されています。そのリージョンに既に CloudWatch ロールがある場合（ソウルには `FAST-stack` に属するものがあります）、これを有効にすると**別のスタックのロールを奪い取ります**。`aws apigateway get-account --region $R --query cloudwatchRoleArn` が `None` を返す場合にのみ設定してください。既存のロールが自分たちのものでない場合、`deploy.sh` は実行を拒否します。 |

> **素の `cdk deploy` ではなく `deploy.sh` を使ってください。** `admin_email` のデフォルトは
> `placeholder@example.com` です。そのため `-c admin_email=...` を省略した `cdk deploy` は、
> **アラートメールをプレースホルダーに置き換え、本物のサブスクリプションを削除します** —
> *確認済み*のものであっても削除されます。このリージョンでの作業を繰り返す中で、まさにこれが
> 発生しました。復旧には確認リンクのクリックをやり直すコストがかかります。再作成された
> サブスクリプションは `PendingConfirmation` の状態で戻ってくるからです。しかもプレースホルダーの
> サブスクリプションは削除すらできず
> （`Cannot delete a subscription which is pending confirmation. Detaching subscription
> from stack.`）— SNS が約 3 日後に破棄するまで残り続けます。どうしても `cdk` を直接
> 呼ぶ必要がある場合は、必ず `-c admin_email=` を渡してください（us-west-2 では加えて
> `-c owner_tag=` と `-c hosted_ui_domain_exists=true` も渡します）。

**新しい Cognito プレフィックスは不要です。** ホステッド UI のプレフィックスが一意である範囲は
グローバルではなく**リージョン**単位です — リージョンはホスト名の中に含まれます
（`<prefix>.auth.<region>.amazoncognito.com`）。`av30lab-admin` はこのアカウントの us-west-2 と
ap-northeast-2 の*両方*で ACTIVE であり、それぞれ別のプールの前面に立っています。
`-c hosted_ui_prefix=...` で上書きするのは、下のプローブがそのリージョンで別アカウントが
所有していると示した場合のみです:

```bash
aws cognito-idp describe-user-pool-domain --domain av30lab-admin --region $R
```

| レスポンス | 意味 |
|---|---|
| 200、`DomainDescription` が埋まっている | すでに自分のもの |
| 200、`DomainDescription` が**空** | 空いている — 使ってよい |
| `ResourceNotFoundException` | そのリージョンで**別のアカウント**が使用中 → 新しいプレフィックスを選ぶ |

---

## 4. 共有バケットのシーディング

**`AWS_REGION` は必ず明示的に渡してください。** シーディングスクリプトは、これがないと実行を
拒否するようになりました。デフォルトに任せると、黙って*最初の*リージョンに再シードしてしまうからです
（スクリプトは `$REGION` の CloudFormation スタックから宛先バケットを解決します）。

ノートブックテンプレートは**必須**です — プロビジョニングは、参加者に空のワークスペースを渡すのでは
なく、意図的に `HTTP 500 "Notebook templates are not staged in this region"` で失敗します:

```bash
SHARED=av30lab-shared-data-$ACCOUNT-$R
aws s3 sync notebooks/ "s3://$SHARED/notebook-templates/"        --region $R \
    --exclude "*__pycache__*" --exclude "*.pyc"
aws s3 sync scripts/   "s3://$SHARED/notebook-templates/scripts/" --region $R \
    --exclude "*__pycache__*" --exclude "*.pyc"
```

### 次にデータ — 再ダウンロードではなく、バケット間コピーで

`cache_models.sh` は Hugging Face から取得し（`HF_TOKEN` と、gated リポジトリごとのライセンス
同意が必要）、そのうえでアップロードします。**2 つめ**のリージョンではこれは方向が逆です —
バイトはすでに最初のリージョンのバケットにあります。代わりにリージョン間でコピーしてください。
トークンもライセンス手続きも不要で、インターネット→手元→S3 ではなく S3→S3 で済みます:

```bash
SRC=av30lab-shared-data-$ACCOUNT-us-west-2     # すでにシード済みのリージョン
DST=av30lab-shared-data-$ACCOUNT-$R

# 大きいものから — 最も時間のかかる処理を先に開始させます。各コマンドは再開可能なので、再実行すれば続きから完了します。
aws s3 sync "s3://$SRC/model-cache/"   "s3://$DST/model-cache/"   --source-region us-west-2 --region $R
aws s3 sync "s3://$SRC/hf-cache/"      "s3://$DST/hf-cache/"      --source-region us-west-2 --region $R
aws s3 sync "s3://$SRC/datasets/"      "s3://$DST/datasets/"      --source-region us-west-2 --region $R
aws s3 sync "s3://$SRC/m10-reference/" "s3://$DST/m10-reference/" --source-region us-west-2 --region $R
```

`stage_nuscenes.sh` / `cache_models.sh` を使うのは、コピー元になるシード済みリージョンが
**ない場合だけ**です:

```bash
AWS_REGION=$R ./scripts/stage_nuscenes.sh                      # 公開ミラー、トークン不要
AWS_REGION=$R HF_TOKEN=hf_... ./scripts/cache_models.sh        # 約 157 GiB を再ダウンロード
```

> **この 2 つのスクリプトは上の 4 行のうち 2 行しか置き換えません。** `cache_models.sh` は
> `model-cache/` だけ、`stage_nuscenes.sh` は `datasets/` だけを書き込みます。どちらも
> `hf-cache/` を作れず、そのツリーを構築するのは **`scripts/cache_hf_tree.sh`** です
> （管理者の `HF_TOKEN` が必要）。`hf-cache/` は HuggingFace の*オフラインキャッシュ*
> レイアウト（`models--org--name/snapshots/<sha>/…`）ですが、`cache_models.sh` は
> `hf download --local-dir` のフラットな構造を使います。`m10-reference/` にも生成
> スクリプトはないのでコピーしてください。
>
> 仮定の話ではありません。2026-09-26 に ap-northeast-2 を上のブロックの代わりに
> `cache_models.sh` でシードし、スクリプトは正常終了し `deploy.sh` も成功を報告し Day-1 の
> スモークテスト（M1 + M2 — そのプレフィックスがカバーする唯一の 2 モジュール）も通過した
> のに、リージョンは **M5・M6・M9・M10 が動かない状態で**出荷されました。参加者が 4 つ
> モジュールを進めてから判明しました。下の 10 を実行してください。

us-west-2 のソースバケットでの実測値:

| プレフィックス | サイズ | オブジェクト数 | 欠けると壊れるモジュール |
|---|---|---|---|
| `notebook-templates/` | 0.55 MiB | 31 | **すべて** — プロビジョニングが即座に失敗 |
| `datasets/`（nuScenes-mini） | 5.01 GiB | 31,225 | M1, M2, M3, M5, M6, M7, M8, M9 |
| `model-cache/` | 157.45 GiB | 1,707 | M2, M8 |
| `hf-cache/` | 115.00 GiB | 481 | M5, M6, M9 |
| `m10-reference/` | 0.03 GiB | 16 | M10 の可視化 |
| **合計** | **277.49 GiB** | **33,457** | |

`m8-lora-probe/`（1 オブジェクト、3 KiB）は**意図的に除外**しています。一度きりの probe が
残した日付付きの SageMaker 学習ジョブ `sourcedir.tar.gz` で、読み込むノートブックはなく、
到達できないプレフィックスを表に載せると表全体を参考情報として読ませてしまいます — その
読み方が `hf-cache/` を飛ばさせた原因です。

推測ではなくノートブックを読んで確認した点: M5 と M6 は `scripts/setup_cosmos_env.sh` を通じて
`hf-cache/hub/` を**間接的に**参照するため、この 2 つのノートブックでプレフィックスを grep しても
見つかりません。**欠けたときに実際に起こること**（実測、ap-northeast-2、2026-09-26 — 以前の記述は 2 か所
誤っていました）:

* `setup_cosmos_env.sh` は現在 `=== STOP ===` ブロックで停止し、その 1 行目は
  `Reason : no HF cache at <uri> (prefix does not exist in this region)` です。`HF_TOKEN` が
  あれば代わりに続行し `[hf-cache] No usable offline cache (…)` を出力します。いずれも以前の
  版が grep せよと書いていた `WARNING: restore failed…` ではありません — それは常に*別の*
  分岐（`aws s3 sync` の失敗）で、その文字列を探す運用者は何も見つけられません。
* 修正前は**参加者ごとのトークン探しではなく、沈黙**でした。スクリプトは exit 0 で終わり
  ノートブックは "environment ready" を表示し、15〜20 分後に M5 が `torchrun` の中で 4 秒で
  `ChildFailedError` により停止し、唯一見えた助言は CUDA out-of-memory でした。HuggingFace の
  401 はキャプチャされた stderr にありましたが、ノートブックが表示した 25 行の窓の外でした。
* 現在は使用可能なキャッシュも `HF_TOKEN` もない場合、**起動そのものを拒否**し（exit 2）
  2 つの解決策を示します。つまりシードされていないリージョンは GPU 時間を使う前に数秒で
  失敗します — それでも失敗です。プレフィックスをシードしてください。

コスト: ap-northeast-2 でおよそ**一度きりの $5.73**（転送 + リクエスト）と、ストレージが
**月 $6.94** です*（転送/リクエストの単価は定価。ソウルのストレージ単価 $0.025/GB-月 は
API で確認済み）*。

なお `stage_nuscenes.sh` は `ap-northeast-1` にある公開の `s3://motional-nuscenes` から
`--no-sign-request` で取得します。これは正しい挙動であり、リージョンに依存しません。

> `aws s3 ls` が報告するのは**現行オブジェクトのみ**です。新しいバケットでバージョニングが有効な
> 場合、実際に課金されるフットプリントはこれより大きくなります — このアカウントでは、報告値 298 GB に
> 対して実際には 441.7 GB が課金された事例がすでに発生しています。

---

## 5. 検証チェックリスト

1. `aws cloudformation describe-stacks --region $R --stack-name Av30BlueprintLabStack`
   → `CREATE_COMPLETE` であること。
2. **予算がそのリージョンを計測しており、$0.00 ではないこと。** これは、静かなリグレッションを
   すでに実際に捕まえたことのある唯一のチェックです:
   ```bash
   aws budgets describe-budget --account-id $ACCOUNT \
     --budget-name av30lab-daily-budget-$R \
     --query 'Budget.[CostFilters,CalculatedSpend.ActualSpend.Amount]'
   ```
   `CostFilters` は `{"Region": ["<region-code>"]}` でなければなりません。ここに**表示名**
   （`"Asia Pacific (Seoul)"`）を入れても拒否されません — 何にもマッチしないため、予算は
   永遠に `0.0` を返し、決してアラームを出しません。Cost Explorer と突き合わせてください:
   ```bash
   aws ce get-cost-and-usage --time-period Start=$YDAY,End=$TODAY --granularity DAILY \
     --metrics UnblendedCost \
     --filter "{\"Dimensions\":{\"Key\":\"REGION\",\"Values\":[\"$R\"]}}"
   ```
   予算が `0.0` なのに CE が `> 0` ⇒ フィルタが壊れています。
3. **予算アラートが実際に配信できること。** 新しいリージョンは新しい SNS トピックを意味し、
   したがって**新しい未確認のメールサブスクリプション**を意味します。CloudFormation は*リクエスト*に
   対して `CREATE_COMPLETE` を報告し、再試行は一切せず、SNS は未確認のサブスクリプションを
   約 3 日後に破棄します。`deploy.sh` は警告を出します — 無視しないでください。
   ```bash
   aws sns list-subscriptions-by-topic --region $R --topic-arn <topic> \
     --query 'Subscriptions[?Protocol==`email`].[Endpoint,SubscriptionArn]'
   ```
   `SubscriptionArn` が `PendingConfirmation` の場合、アラームには行き先がありません。
4. SPA の設定がリージョンローカルであること:
   `aws s3 cp s3://av30lab-admin-dashboard-$ACCOUNT-$R/config.json -` が言及するのは
   `$R` だけでなければなりません。
5. `aws cognito-idp describe-user-pool-domain --domain av30lab-admin --region $R` →
   `ACTIVE` で、プール ID の接頭辞が `$R` であること。
6. **料金表はデプロイ前（§2.5）に生成され**、デプロイ後も残っていること:
   ```bash
   grep -c "\"$R\":" infra/lambda/shared/instance_rates.py   # 1 が返るはず
   ./scripts/check_quotas.py --region $R --participants <人数>
   ```
7. Cognito 管理者を作成し、ホステッド UI からサインインし、参加者を**1 人**プロビジョニングして、
   ワークスペースが**空でない**ことを確認します（実測: **32** オブジェクト — ステージング済み
   テンプレート 31 個 + `.av30-progress.env`）。
8. `aws apigateway get-account --region $R --query cloudwatchRoleArn` が §0 の値から変わって
   いないこと。
9. **元からあったリージョンが無傷であること:** そのスタックは引き続き `UPDATE_COMPLETE`、予算も
   残っており、`apigateway get-account` も変わっていないこと。

10. **データが実際に存在すること — 参加者を作成する前に実行:**

    ```bash
    ./scripts/check_seeding.sh --region $R --source-region us-west-2
    ```

    必ず exit 0 になること。1〜9 は **M5・M6・M9・M10 が動かないリージョンでもすべて通過します**
    — 2026-09-26 の ap-northeast-2 がまさにそれでした — どの項目も §4 がコピーせよと告げた
    277.49 GiB のバイトを 1 つも検査しないためです。この検査は*存在*ではなく*ツリーの形*を
    アサートします: ランタイムの glob が実際にテストする `models--nvidia--*` ディレクトリ 5 つ、
    Cosmos が固定したコミット sha の `tokenizer.pth` blob、そして `--source-region` を渡せば
    CRC64 チェックサムとオブジェクト数の照合まで。存在だけでは不十分です — HuggingFace の
    オフラインモードは整合性検査を**まったく**行わないため 0 バイトのファイルも成功した
    ダウンロードとして読み、中断された `aws s3 sync` は空のプレフィックスより**悪い**です:
    ディレクトリが 1 つあるだけで `HF_HUB_OFFLINE=1` が有効になり、まだ欠けている
    チェックポイントがダウンロードではなく不透明な `Local entry not found` に変わります。

### 安価で正直なスモークテスト（$1 を十分に下回る）

デプロイ（§3）し、**`notebook-templates/` のみ**をシードし（0.55 MiB ≈ $0.00）、参加者を 1 人
プロビジョニングし、**`ml.t3.medium` を 1 つ**起動し（クォータはすでに 2500）、チェックリストを
実行し、アプリを削除してから `./scripts/teardown.sh --region $R` を実行します。

これで証明できること: 176 個のリソースすべてが既存のリージョンと並行して作成されること。Cognito
プレフィックスが実際に共存できること。予算の名前とフィルタ。`ApiGateway::Account` が手つかずで
あること。SageMaker のイメージアカウントマッピングが実在するイメージに解決されること（アプリが
実際に起動する）。エンドツーエンドのサインイン。空バケットのガード。そしてリージョン 1 が
無事であること。

証明**できない**こと: GPU のキャパシティやクォータ（`t3.medium` は、ソウルではクォータ 0 の
`ml.g6.24xlarge` について何も語りません）。スキップした 272 GiB が存在すること（無ければ
M2/M3/M5/M6/M9 はモデルのロードで失敗します）。同時実行性（1 ユーザーは 10 ユーザーではありません）。
予算アラートが実際に配信されること。

---

## 既知の落とし穴

**`INSTANCE_RATES` は us-west-2 の価格スナップショットです — しかもインスタンスの許可リストも
兼ねています。** `infra/lambda/shared/config.py` はリージョンをキーにしておらず、
`change_instance` はそのキーから `VALID_INSTANCE_TYPES` を導出し、`instance_options` はそれをもとに
参加者向けのドロップダウンを構築します。結果は 2 つあります:

| Studio-JupyterLab | us-west-2 | ap-northeast-2 | 表示値のずれ |
|---|---|---|---|
| `ml.t3.medium` | $0.0500 | $0.0620 | −24% |
| `ml.g5.12xlarge` | $7.0900 | $8.7180 | −23% |
| `ml.g6.24xlarge` | $8.3440 | $10.2600 | −23% |

1. ソウルでは、参加者と管理者に表示されるすべてのコストが約 23% **低く**出ます — 気づかれない支出
   こそが既知の失敗モードであるラボにとって、ずれる方向が最悪です。
2. ドロップダウンはリージョンでフィルタされないため、そのリージョンの Studio では提供されていない
   インスタンスが提示されることがあり（例: `eu-west-1` の `ml.g6.24xlarge`）、参加者ごとに
   アプリ起動時に失敗します。

ソウルの差分が一律で約 23% なのは偶然であり、法則ではありません — 係数を掛けてこれを「修正」しようと
せず、料金表をリージョンでキーにしてください。

**`av30-alpasim-m7`（M10）はアカウントグローバルでサフィックスが付きません。** IAM ロール名と
インスタンスプロファイル名はアカウントグローバルなので、2 つ目のリージョンで M10 を実行すると
`EntityAlreadyExists` で失敗します。さらに悪いことに、M10 ランブックのティアダウンは「次回実行時の
名前衝突を防ぐため」に両方を*無条件で*削除します — つまり**どちらか一方の**リージョンで M10 を
ティアダウンすると、もう一方のリージョンで稼働中の GPU ホストが使っているロールを破壊します。
複数のリージョンで M10 を実行する前に、作成時*と*ティアダウン時の両方で、両方の名前にリージョンの
サフィックスを付けてください。また、稼働中のロールのインラインポリシーはリージョンセグメントを
まったく含まないバケット名を指定しているため、現在のバケット名と一致しなくなっています。

**`REGION_CONFIG` / `TARGET_REGIONS` は未設定のままにしてください。**
`infra/lambda/shared/config.py` には休眠状態のクロスリージョン制御プレーンが定義されており、
`create_user` / `bulk_provision` はすでにリクエストボディの `region` フィールドを受け付けます。
どちらの環境変数も CDK からは設定されないため、現状ではすべてが単一のデプロイリージョンに収束します
— これが本ドキュメントで説明している独立コピーのモデルです。これらを設定すると、2 つの独立した
ラボが、黙って両方を管理する 1 つの制御プレーンに変わってしまいます。

**CloudFront ディストリビューションはアカウントグローバルなクォータです。** 各リージョンで 2 つ
増えます（加えて、カウント対象外の Cognito 管理のものが 2 つ）。デフォルトの上限は 200 なので実用上の
リスクはありませんが、確認コマンドは
`aws service-quotas get-service-quota --service-code cloudfront --quota-code L-24B04930` です。

---

## ティアダウン

```bash
./scripts/teardown.sh --region $R      # or AWS_REGION=$R ./scripts/teardown.sh
```

リージョンは明示指定であり、確認には `<account>/<region>` の入力が必要です — 以前このスクリプトは
`us-west-2` をデフォルトにしていたため、リージョン B を回収するつもりで実行するとリージョン A を
削除しかねませんでした（旧プロンプトはアカウント ID しか尋ねず、それはどのリージョンでも同一だから
です）。実行後は、CloudFormation が追跡していない既知の孤立リソースの発生源を確認してください:

```bash
aws efs describe-file-systems --region $R          # Studio's per-domain filesystem
aws ec2 describe-security-groups --region $R \
  --filters "Name=group-name,Values=security-group-for-*-nfs-*"
aws s3api list-buckets --query "Buckets[?ends_with(Name,'$R')].Name"
aws budgets describe-budgets --account-id $ACCOUNT --query "Budgets[].BudgetName"
```

Studio ドメインの削除順序は、アプリ → スペース → **ユーザープロファイル**（実行時に作成される
ため、スタックはこれらを所有していません）→ スタックです。その後、残存した EFS の
**マウントターゲット**がサブネットを掴んだままにし、SageMaker が自動作成した NFS セキュリティ
グループ（`security-group-for-{inbound,outbound}-nfs-<domainId>`、これらは tcp/988 で相互参照して
います）が VPC を掴んだままにします。グループを削除する前に、この相互参照を解除してください。
