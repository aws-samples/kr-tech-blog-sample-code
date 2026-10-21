# M10 手動テストランブック (Part A: admin GPU 実行 → Part B: 参加者ノートブック)

M10 は 2 層構造です。**Part A** = admin が GPU EC2 上で本物の AlpaSim を実行して `m10-reference/`
を作る (重く、1 回限り)。**Part B** = 参加者が CPU ノートブックでその結果を可視化する (軽く、
反復可能)。「両方を順番に」とは、A で参照結果を新たに作り → B でそれをノートブックで見る流れです。

> リファレンス配備で既に正常に実行され、`s3://av30lab-shared-data-<aws-account-id>-<region>/m10-reference/`
> に本物の結果がアップロードされたことがあります。そのような参照結果が既にあれば、**Part B だけを
> 単独で実行しても完全な検証**になります。Part A は「最初からやり直して再現」したいときにのみ
> 必要です (~$30、2〜3 時間)。

---

## 0. 資格情報の更新 (両方に共通、最初に)

ローカルセッショントークンが失効しています。**このラボを配備した AWS アカウントの admin** で
再ログインした後、すべての aws 呼び出しを **6-env-unset ラッパー** で包みます (別アカウントの
資格情報が混ざって漏れるのを防ぐため)。

> **⚠️ このステップを飛ばさないこと。** 下の `UN()` はシェル**関数**です — これ以降のすべての
> `UN aws …` コマンドがこの関数に依存します。定義せずに A2/A3/C* ブロックを貼り付けると
> `command not found: UN` が出て (例: `AMI=` が空の値になる)、以降すべて失敗します。
> シェル関数は**現在のターミナルセッション内でのみ**有効なので、**新しいターミナルを開くたびに
> (または資格情報が失効するたびに) このブロックを再実行**する必要があります。

> **アカウント/リージョンはハードコードしません。** 下で `ACCOUNT` を `sts` で自動導出し、
> バケット名をそこから派生させます — この文書の以降すべてのコマンドはこれらの変数を使うので、
> **別の AWS アカウント/リージョンでもそのまま**動作します。(文書本文の `<aws-account-id>` /
> `<region>` は例示のプレースホルダーにすぎません。)

```bash
# Isengard/SSO など普段使う方法でログインした後:
UN() { env -u AWS_PROFILE -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY \
             -u AWS_SESSION_TOKEN -u AWS_SHARED_CREDENTIALS_FILE -u AWS_CONFIG_FILE "$@"; }
UN aws sts get-caller-identity --query '[Account,Arn]' --output text
# → <あなたのアカウント id>  arn:aws:...:assumed-role/...

# このラボが配備されたアカウント/リージョン → 以降すべてのブロックが使う変数 (ハードコードの代わりにここで一度定義)
export REGION=<region>                                    # あなたが配備したリージョンに (例: us-west-2)
export ACCOUNT=$(UN aws sts get-caller-identity --query Account --output text)
export SHARED_BUCKET=av30lab-shared-data-${ACCOUNT}-${REGION}       # モデル/データ/ノートブックテンプレート + m10-reference
export USER_BUCKET=av30lab-user-workspace-${ACCOUNT}-${REGION}      # 参加者ごとの users/<id>/ (Part C で使用)
echo "ACCOUNT=$ACCOUNT REGION=$REGION"
echo "SHARED_BUCKET=$SHARED_BUCKET"
```

---

# Part A — admin: GPU EC2 で本物の AlpaSim を再実行 (~$30、任意)

## A1. 事前準備物
- **HF トークン**: Alpamayo-1.5-10B + Cosmos-Reason2-8B + PhysicalAI NuRec データセットのライセンスが
  すべて承認されたトークン (admin 本人の HF アカウントで事前に承認しておく)。
- **NGC API キー**: 実はレンダラーイメージ `nvcr.io/nvidia/nre/nre-ga:26.04` は **公開 pull 可能**
  (ゲート 0 で確認済み) なのでキーがなくても大丈夫。スクリプトはキーがなければ anonymous pull に
  フォールバックします。

## A2. GPU ホストの launch (手動 — launch スクリプトはなし)

> **⚠️ インスタンスは必ず GPU ≥2 枚。名前の数字 ≠ GPU 枚数。** デフォルトの topology (`2gpu`) は
> renderer を **GPU 1** に載せるので **最低 2 GPU** が必要です。g6e 系列では **vCPU が大きい
> サイズだから GPU が多いわけではありません** — マルチ GPU は **12xlarge(4)、24xlarge(4)、48xlarge(8)**
> だけで、それ以外 (**16xlarge を含む**) はすべて **GPU 1 枚**です。「16 > 12 だから大きいだろう」で
> `g6e.16xlarge` を選ぶと GPU 1 枚なので実行直前に
> `Service renderer requested GPUs [1] but only 0 .. 0 are available` で落ちます。
>
> | g6e size | GPUs | vCPU | M10(2gpu) |
> |---|---|---|---|
> | xlarge / 2xlarge / 4xlarge / 8xlarge | **1** | 4–32 | ❌ |
> | **g6e.12xlarge** | **4** | 48 | ✅ **推奨** |
> | g6e.16xlarge | **1** | 64 | ❌ (より大きいのに GPU は 1 枚!) |
> | g6e.24xlarge | **4** | 96 | ✅ (過剰) |
> | g6e.48xlarge | **8** | 192 | ✅ (過剰) |
>
> launch 後は必ず確認: `nvidia-smi --query-gpu=index,name --format=csv` が **2 行以上**。
> (80 GB シングルカードの p4de/p5 は `topology=1gpu` で 1 枚でも可能。)

ゲート 2 のときこのステップは手動でした。以下を順番に:

```bash
# ⟸ 先に §0 の UN() ラッパー + ACCOUNT/REGION/SHARED_BUCKET 変数を定義しておくこと
#    (しないと 'command not found: UN' または空のバケット名)。
# (a) Deep Learning Base GPU AMI の最新 ID を取得 (Docker+NVIDIA toolkit+driver 内蔵)
AMI=$(UN aws ssm get-parameter --region $REGION \
  --name /aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-22.04/latest/ami-id \
  --query Parameter.Value --output text)
echo "AMI=$AMI"

# (b) デフォルト VPC のパブリックサブネット (ラボ VPC は isolated で egress 不可 → default VPC を使用)
# 前提: このアカウント/リージョンに default VPC + パブリックサブネット (map-public-ip-on-launch=true) があること。
#   - 組織アカウントなどで default VPC が削除されていたりパブリックサブネットがない場合、VPC/SUBNET が 'None'/空の値に
#     なり、下の run-instances が不明なエラーで失敗します。その場合:
#       * 直接指定: SUBNET=subnet-xxxx (IGW で egress するパブリックサブネット)、SG もその VPC のものに
#       * または `aws ec2 create-default-vpc --region $REGION` で default VPC を作成。
#   - Subnets[0] は最初のサブネット (=AZ は任意) です。その AZ に g6e.12xlarge の容量がない場合、launch が
#     InsufficientInstanceCapacity で失敗することがあります → 別 AZ のサブネット id に SUBNET を変えて再試行。
VPC=$(UN aws ec2 describe-vpcs --region $REGION --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].VpcId' --output text)
SUBNET=$(UN aws ec2 describe-subnets --region $REGION \
  --filters Name=vpc-id,Values=$VPC Name=map-public-ip-on-launch,Values=true \
  --query 'Subnets[0].SubnetId' --output text)
echo "VPC=$VPC SUBNET=$SUBNET"
# VPC/SUBNET が None/空の値ならここで止めて上のコメント通りに対処 (空のまま進めると run-instances が失敗)。
[ -n "$VPC" ] && [ "$VPC" != "None" ] && [ -n "$SUBNET" ] && [ "$SUBNET" != "None" ] \
  || { echo "ERROR: default VPC/パブリックサブネットが見つからない — 上の (b) コメント参照 (直接指定または create-default-vpc)"; }

# (c) セキュリティグループ (egress のみ必要; SSM 接続なのでインバウンド不要)
SG=$(UN aws ec2 create-security-group --region $REGION \
  --group-name av30-alpasim-m7 --description "M10 AlpaSim egress" \
  --vpc-id $VPC --query GroupId --output text)
# (インバウンドルールは追加しない — SSM Session Manager で接続)

# (d) IAM instance-profile (ラボアカウントにない → その場で作成)。hf-cache read + m10-reference write + KMS + SSM。
UN aws iam create-role --role-name av30-alpasim-m7-$REGION \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
UN aws iam attach-role-policy --role-name av30-alpasim-m7-$REGION \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
# ポリシー JSON は $SHARED_BUCKET が展開されるよう heredoc で作る (single-quote だと展開されない)。
UN aws iam put-role-policy --role-name av30-alpasim-m7-$REGION --policy-name s3-hfcache-m7ref \
  --policy-document "$(cat <<JSON
{"Version":"2012-10-17","Statement":[
  {"Effect":"Allow","Action":["s3:GetObject","s3:ListBucket"],"Resource":["arn:aws:s3:::${SHARED_BUCKET}","arn:aws:s3:::${SHARED_BUCKET}/*"]},
  {"Effect":"Allow","Action":["s3:PutObject"],"Resource":"arn:aws:s3:::${SHARED_BUCKET}/m10-reference/*"},
  {"Effect":"Allow","Action":["kms:Decrypt","kms:GenerateDataKey"],"Resource":"*"}]}
JSON
)"
UN aws iam create-instance-profile --instance-profile-name av30-alpasim-m7-$REGION
UN aws iam add-role-to-instance-profile --instance-profile-name av30-alpasim-m7-$REGION --role-name av30-alpasim-m7-$REGION

> **IAM 名に `-$REGION` を付ける理由。** IAM ロール名とインスタンスプロファイル名は**アカウント全体で
> グローバル**です（上のセキュリティグループは VPC 単位なので接尾辞なしのまま）。接尾辞がないと 2 つ目の
> リージョンの M10 実行が `EntityAlreadyExists` で失敗し、さらに深刻なことに、下の teardown ブロックは
> 「次回実行時の名前衝突を防ぐため」これらを無条件に削除するので、**どちらか一方のリージョンで M10 を
> teardown すると、もう一方のリージョンで稼働中の GPU ホストが使っているロールが消えます**。作成と
> teardown の両方で接尾辞を付けることで 2 つのデプロイが独立します（本ラボのモデル: 1 デプロイ 1
> リージョン — `docs/en/ADDING_A_REGION.md` 参照）。
sleep 15   # IAM 伝播待ち

# (e) launch: g6e.12xlarge (4× L40S 48GB)、gp3 300GB、パブリック IP
IID=$(UN aws ec2 run-instances --region $REGION \
  --image-id $AMI --instance-type g6e.12xlarge \
  --subnet-id $SUBNET --security-group-ids $SG --associate-public-ip-address \
  --iam-instance-profile Name=av30-alpasim-m7-$REGION \
  --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=300,VolumeType=gp3}' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=av30-alpasim-m7}]' \
  --query 'Instances[0].InstanceId' --output text)
echo "INSTANCE=$IID"
UN aws ec2 wait instance-status-ok --region $REGION --instance-ids $IID   # ~2-3分
```

## A3. ホスト上で実行 (SSM Session Manager で接続)
```bash
# ⟸ 先に §0 の UN() ラッパー + REGION 変数を定義しておくこと (しないと 'command not found: UN')。
UN aws ssm start-session --region $REGION --target $IID
# --- セッション内で (root) --- (ここからは GPU ホスト上。ローカル §0 の変数はないので再定義)
sudo su -
export HF_TOKEN=hf_xxx                 # A1 の承認済みトークン
export NGC_API_KEY=nvapi-xxx           # 任意 (なければ省略 — anonymous pull)
# アカウントをインスタンスロールで導出 → バケット名を派生 (ハードコードの代わり)。ホストには aws CLI 内蔵。
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export SHARED_BUCKET=av30lab-shared-data-${ACCOUNT}-${REGION}
# スクリプト取得 (S3 ステージング版を使用):
aws s3 cp s3://$SHARED_BUCKET/notebook-templates/scripts/alpasim_ec2_setup.sh /root/
# ── 実行 (DETACHED がデフォルト — 下の警告参照) ─────────────────────────────────────
# setsid でセッションから切り離してバックグラウンド実行。SSM セッションが切れても (再ログイン/タイムアウト)
# 死なず、ログはリダイレクトなのでバッファ喪失もない。再接続後 tail -f で再び追える。
setsid bash /root/alpasim_ec2_setup.sh > /var/log/alpasim_m7.log 2>&1 &
echo "started PID $!"
tail -f /var/log/alpasim_m7.log   # Ctrl-C で抜けてもバックグラウンド実行は続く
```

> **⚠️ `... | tee` (フォアグラウンド) で走らせないこと — 長時間実行でセッションが切れると丸ごと死ぬ。**
> `bash setup.sh 2>&1 | tee log` は **SSM セッションに付いている**パイプラインなので、Claude Code の
> 再ログイン・ネットワーク切断・SSM アイドルタイムアウトが来ると SIGHUP で **パイプライン全体
> (スクリプトを含む) が終了**し、tee バッファにあったログも flush されず **ログファイルが 0 バイト**に
> なることがあります (実際に遭遇した落とし穴)。このスクリプトは wizard 実行 + docker コンテナ起動まで
> 数十分かかるので、**必ず上の `setsid` 方式**を使います。(ごく短時間フォアグラウンドで見守るときだけ tee。)
>
> **中断してから再実行するとき** (プロセス/コンテナの残骸を整理してから再開 — clone/ビルド/キャッシュは
> 残っているので速い):
> ```bash
> docker ps -aq | xargs -r docker rm -f    # 中断されたコンテナを整理
> setsid bash /root/alpasim_ec2_setup.sh > /var/log/alpasim_m7.log 2>&1 &
> tail -f /var/log/alpasim_m7.log
> ```
スクリプトがやること: preflight(nvidia-smi/docker/uv/cargo) → hf-cache 復元 → alpasim clone
(tag v2026.5 — alpasim-base-v0.96.0 は上流に存在しません。下記参照) → NGC login(オプション)+イメージアクセス確認 → `source setup_local_env.sh`
→ mount ディレクトリ作成 → `deploy/local_m7.yaml`(driver HF-offline) + `topology/m7_4gpu.yaml`
(driver 単独 GPU0) 作成 → `uv run alpasim_wizard ...` 実行 → 結果検証 → `s3://.../m10-reference/`
アップロード。**初回ビルドは時間がかかります (protos コンパイル + イメージ pull + NuRec シーンのダウンロード)。**
再実行時は clone/ビルド/hf-cache/NuRec シーンが残っているので wizard ステップからになり、はるかに速い。

### ログで成功/失敗を判定する
`tail -f` がそれ以上更新されなくなったら **成功 (終了) または失敗 (中断)** のどちらかです — ログの
**最後の部分**を見て判別します (`tail -n 40 /var/log/alpasim_m7.log`)。

- **✅ 成功**: ログの末尾にスクリプトの完了マーカーがあります。
  ```
  runtime-0-1 exited with code 0            # eval コンテナが 0 で正常終了
  [verify] core outputs present.
  [upload] -> s3://.../m10-reference/ ...
  === DONE — genuine AlpaSim results uploaded to s3://.../m10-reference/ ===
  ```
  成功時に `tail -f` が止まるのは **正常**です (スクリプトが終わってバックグラウンドプロセスが終了 —
  死んだのではない)。最終確定は A4 の S3 確認 (今日の日付)。
  > 参考: 完了直後に `renderer/physics/controller` コンテナが `exited with code 143`(SIGTERM)/
  > `137`(SIGKILL) と表示されるのは **正常**です — 主コンテナ (runtime) が 0 で終わった後に docker
  > compose が残りのサービスを落とすため。`runtime-0-1 exited with code 0` + `=== DONE ===`
  > があれば成功です。

- **❌ 失敗/中断**: ログの末尾に `=== DONE ===` が **なく**、代わりに次のいずれかなら失敗です。
  - `ERROR: ...` で終わる (preflight 失敗、必須出力の欠落など — スクリプトが exit)。
  - `Error executing job` / `RuntimeError: ...` (wizard 実行失敗、例: GPU 不足)。
  - ログが **途中でぷつりと切れる** + プロセスもない → セッション切断などで中断された
    (`ps aux | grep -E "[a]lpasim|[w]izard"` でプロセス生存を確認; docker `docker ps`)。
  → 原因を直した後、上の「中断してから再実行」recipe で再開。

素早く成功可否だけ確認:
```bash
grep -q "=== DONE" /var/log/alpasim_m7.log && echo "M10 成功 (S3 アップロード完了)" \
  || echo "M10 未完 — ログ末尾(tail -n 40)で ERROR/RuntimeError/中断地点を確認"
```

## A4. 成功確認 → **即座に terminate** (課金停止)
```bash
# ⟸ 先に §0 の UN() ラッパー + SHARED_BUCKET/REGION 変数を定義しておくこと。
# ローカル(資格情報)で:
UN aws s3 ls s3://$SHARED_BUCKET/m10-reference/ --recursive --region $REGION
# aggregate/results-summary.json + metrics_results.{txt,png,parquet} + rollouts/**/metrics.parquet
# + eval/eval.mp4 + run.json が見えれば成功。

# !!! 必ず整理 (しないと時間あたり ~$10.5 が課金され続ける) !!!
UN aws ec2 terminate-instances --region $REGION --instance-ids $IID
UN aws ec2 wait instance-terminated --region $REGION --instance-ids $IID
# IAM/SG も整理 (次回実行時の名前衝突を防ぐ):
UN aws iam remove-role-from-instance-profile --instance-profile-name av30-alpasim-m7-$REGION --role-name av30-alpasim-m7-$REGION
UN aws iam delete-instance-profile --instance-profile-name av30-alpasim-m7-$REGION
UN aws iam delete-role-policy --role-name av30-alpasim-m7-$REGION --policy-name s3-hfcache-m7ref
UN aws iam detach-role-policy --role-name av30-alpasim-m7-$REGION --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
UN aws iam delete-role --role-name av30-alpasim-m7-$REGION
UN aws ec2 delete-security-group --region $REGION --group-id $SG
```

**⚠️ 最大のリスク = terminate 忘れ。** 確認したら即座に終了すること。(ホスト上で `shutdown -h +180` を
バックアップガードとして仕掛けておくこともできる。)

---

# Part C — admin: 参加者ごとのセルフラン用プロビジョニング (参加者が自分で AlpaSim を回すとき)

Part A は admin が **共有参照結果 1 式** (`m10-reference/`) を作るものです。以下の Part C は
**参加者ごとに自分の GPU ホストで直接 AlpaSim を回させる**とき (参加者実行ガイド =
[M10_PARTICIPANT_SSM_RUNBOOK.md](M10_PARTICIPANT_SSM_RUNBOOK.md)) に admin が行う事前配線です。

> **コスト/上限の警告**: g6e.12xlarge = **48 vCPU/台**、~**$10.5/hr/台**。G-vCPU quota 768 →
> **同時最大 16 台 (=16 名)**。launch 前に必ず quota を確認:
> `UN aws service-quotas get-service-quota --region $REGION --service-code ec2 --quota-code L-DB2E81BA`

## C1. instance-profile ポリシーの拡張 (参加者は user-workspace に書く)
Part A の `av30-alpasim-m7` インスタンスロールは `m10-reference/` にのみ write します。参加者のセルフランは
`users/<id>/m10/` に書く必要があるのでポリシーを拡張します (prefix 制限で複数参加者の共有が可能):
```bash
# ⟸ 先に §0 の UN() ラッパー + SHARED_BUCKET/USER_BUCKET 変数を定義しておくこと。
UN aws iam put-role-policy --role-name av30-alpasim-m7-$REGION --policy-name s3-participant-m7 \
  --policy-document "$(cat <<JSON
{"Version":"2012-10-17","Statement":[
  {"Effect":"Allow","Action":["s3:GetObject","s3:ListBucket"],"Resource":["arn:aws:s3:::${SHARED_BUCKET}","arn:aws:s3:::${SHARED_BUCKET}/*"]},
  {"Effect":"Allow","Action":["s3:PutObject"],"Resource":"arn:aws:s3:::${USER_BUCKET}/users/*/m10/*"},
  {"Effect":"Allow","Action":["kms:Decrypt","kms:GenerateDataKey"],"Resource":"*"}]}
JSON
)"
```

## C2. 参加者ごとの GPU インスタンス launch (Part A2 再利用 + Participant タグ)
Part A2 の (e) `run-instances` に参加者タグを追加します (共有 SG/instance-profile を再利用):
```bash
# ⟸ 先に §0 の UN() ラッパーを定義 + 資格情報を更新しておくこと (しないと 'command not found: UN')。
PID=m10-test01     # 参加者 id
IID=$(UN aws ec2 run-instances --region $REGION \
  --image-id $AMI --instance-type g6e.12xlarge \
  --subnet-id $SUBNET --security-group-ids $SG --associate-public-ip-address \
  --iam-instance-profile Name=av30-alpasim-m7-$REGION \
  --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=300,VolumeType=gp3}' \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=av30-alpasim-$PID},{Key=Participant,Value=$PID}]" \
  --query 'Instances[0].InstanceId' --output text)
echo "$PID -> $IID"     # このマッピングを参加者に伝える
UN aws ec2 wait instance-status-ok --region $REGION --instance-ids $IID
```

## C3. 参加者 SSM 資格情報 — 2 つの方式

### オプション 1 — 参加者ごとの IAM user + exact-ARN (事前テスト / 小規模、推奨)
参加者ごとに IAM user を作り、**そのインスタンス ID をポリシーに直接埋め込んで**自分のインスタンスにだけ接続を許可。
`ssm:TerminateSession` は **自分のセッション終了のみ** — インスタンスの terminate は不可 (コスト事故を防止)。
```bash
# ⟸ 先に §0 の UN() ラッパーを定義 + 資格情報を更新しておくこと (しないと 'command not found: UN')。
UN aws iam create-user --user-name $PID
# heredoc で $REGION/$ACCOUNT/$IID は展開し、IAM ポリシー変数 ${aws:...} は \$ で保存。
UN aws iam put-user-policy --user-name $PID --policy-name m10-ssm --policy-document "$(cat <<JSON
{
  "Version":"2012-10-17","Statement":[
   {"Sid":"StartOwnInstance","Effect":"Allow","Action":["ssm:StartSession"],
    "Resource":["arn:aws:ec2:${REGION}:${ACCOUNT}:instance/${IID}",
                "arn:aws:ssm:${REGION}:${ACCOUNT}:document/SSM-SessionManagerRunShell"]},
   {"Sid":"Describe","Effect":"Allow","Action":["ssm:DescribeSessions","ssm:GetConnectionStatus","ssm:DescribeInstanceProperties","ec2:DescribeInstances"],"Resource":"*"},
   {"Sid":"TerminateOwnSessionOnly","Effect":"Allow","Action":["ssm:TerminateSession","ssm:ResumeSession"],"Resource":["arn:aws:ssm:*:*:session/\${aws:userid}-*"]},
   {"Sid":"OpenChannel","Effect":"Allow","Action":["ssmmessages:OpenDataChannel","ssmmessages:CreateControlChannel","ssmmessages:CreateDataChannel","ssmmessages:OpenControlChannel"],"Resource":"*"}]}
JSON
)"
UN aws iam create-access-key --user-name $PID   # → 参加者に out-of-band で伝える
```

### オプション 2 — ABAC タグマッチング (実際のワークショップ / N 名)
ポリシー 1 式だけ作り、**タグ一致**で隔離 (インスタンス ID は埋め込まない)。user の principal tag
`Participant=<id>` とインスタンスの `Tag Participant=<id>` が同じでないと接続できません。C2 で既にインスタンスタグを
付けたので user 側だけ:
```bash
# ⟸ 先に §0 の UN() ラッパーを定義 + 資格情報を更新しておくこと (しないと 'command not found: UN')。
UN aws iam create-user --user-name $PID --tags Key=Participant,Value=$PID
# heredoc で $REGION/$ACCOUNT は展開、IAM ポリシー変数 ${aws:...} は \$ で保存。
UN aws iam put-user-policy --user-name $PID --policy-name m10-ssm-abac --policy-document "$(cat <<JSON
{
  "Version":"2012-10-17","Statement":[
   {"Sid":"StartTaggedInstance","Effect":"Allow","Action":["ssm:StartSession"],
    "Resource":"arn:aws:ec2:${REGION}:${ACCOUNT}:instance/*",
    "Condition":{"StringEquals":{"ssm:resourceTag/Participant":"\${aws:PrincipalTag/Participant}"}}},
   {"Sid":"StartDoc","Effect":"Allow","Action":["ssm:StartSession"],"Resource":"arn:aws:ssm:${REGION}:${ACCOUNT}:document/SSM-SessionManagerRunShell"},
   {"Sid":"Describe","Effect":"Allow","Action":["ssm:DescribeSessions","ssm:GetConnectionStatus","ssm:DescribeInstanceProperties","ec2:DescribeInstances"],"Resource":"*"},
   {"Sid":"TerminateOwnSessionOnly","Effect":"Allow","Action":["ssm:TerminateSession","ssm:ResumeSession"],"Resource":["arn:aws:ssm:*:*:session/\${aws:userid}-*"]},
   {"Sid":"OpenChannel","Effect":"Allow","Action":["ssmmessages:OpenDataChannel","ssmmessages:CreateControlChannel","ssmmessages:CreateDataChannel","ssmmessages:OpenControlChannel"],"Resource":"*"}]}
JSON
)"
UN aws iam create-access-key --user-name $PID
```
> (代替オプション 3 — 長期 access key なし) 上のポリシーをセッションポリシーで包んだ `sts get-federation-token`
> (≤36h) の一時資格情報。漏洩リスクは最小だが発行手順がより複雑 — セキュリティが厳格な環境で。

## C4. スモークテスト (配線検証、必須)
発行した参加者キーで (admin キーではない) 隔離が実際に効くか確認:
```bash
# 参加者キーを export したシェルで:
REGION=us-west-2   # (参加者シェルには §0 の変数がないのでここで定義; 配備リージョンに)
aws ssm start-session --target $IID --region $REGION          # ✓ 成功するはず
aws ssm start-session --target <別のインスタンス> --region $REGION # ✗ AccessDenied のはず
aws ec2 terminate-instances --instance-ids $IID --region $REGION # ✗ 拒否のはず (参加者は終了不可)
```

## C5. 参加者実行 → 完了通知 → admin 整理
- 参加者は [M10_PARTICIPANT_SSM_RUNBOOK.md](M10_PARTICIPANT_SSM_RUNBOOK.md) に従って実行し、
  結果を `users/<id>/m10/` にアップロードした後 **完了を通知**します。
- admin は通知を受けたら即座に整理 (タグで一括照会が可能):
```bash
# ⟸ 先に §0 の UN() ラッパーを定義 + 資格情報を更新しておくこと (しないと 'command not found: UN')。
# 特定の参加者を終了
UN aws ec2 terminate-instances --region $REGION --instance-ids $IID
# 残りの参加者インスタンスを一括照会
UN aws ec2 describe-instances --region $REGION \
  --filters "Name=tag:Participant,Values=*" "Name=instance-state-name,Values=running,pending" \
  --query 'Reservations[].Instances[].[InstanceId,Tags[?Key==`Participant`]|[0].Value]' --output text
# IAM user 整理 (キーを先に削除)
UN aws iam list-access-keys --user-name $PID --query 'AccessKeyMetadata[].AccessKeyId' --output text \
  | tr '\t' '\n' | while read k; do UN aws iam delete-access-key --user-name $PID --access-key-id "$k"; done
UN aws iam delete-user-policy --user-name $PID --policy-name m10-ssm 2>/dev/null || \
  UN aws iam delete-user-policy --user-name $PID --policy-name m10-ssm-abac 2>/dev/null
UN aws iam delete-user --user-name $PID
```

**⚠️ 最大のリスク = 参加者インスタンスの終了忘れ。** 参加者は消せないので admin が専任で担当。Part A4 の
共有 SG/instance-profile は、すべての参加者インスタンスが終了した後に最後に整理。

---

# Part B — 参加者: Studio CPU ノートブックで M10 を可視化 (~$0、5 分)

これが参加者が実際に体験する内容で、ゲート 3 の「実際の Studio 環境」ギャップを埋めます。

## B1. 参加者ダッシュボードを開く
1. admin ダッシュボードでテスト用ユーザーの **participant dashboard link** を取得
   (`https://<user-dashboard>.cloudfront.net/?userId=<id>&token=<token>`)。
   なければ admin ダッシュボード → Users → Provision で新しいユーザーを 1 人作るとリンクが出ます。
2. ブラウザでそのリンクを開く → Pipeline Map が表示される。

## B2. インスタンス = CPU の確認 (M10 は GPU 不要)
- M10 ノートは **`ml.t3.medium`(CPU)** で回ります。ワークスペースのデフォルトが t3.medium なので
  **インスタンス変更は不要**。(M9 で GPU に上げた場合は、M10 の前に Instance Options → t3.medium に
  戻すのがコスト上望ましい — GPU でも回りはするが無駄。)

## B3. ワークスペースを開いてノートブックを実行
1. ダッシュボード右上の **Open Workspace** → JupyterLab タブ。
2. ファイルブラウザで **`M10_AlpaSim_ClosedLoop.ipynb`** を開く。
3. **Run ▸ Run All Cells** (または Shift+Enter で上→下)。

## B4. 合格基準 (各セルがこう出るはず)
| セル | 期待される出力 |
|---|---|
| cell-2 config | Profile/Reference eval/M9 provenance のパスを出力 |
| cell-3 provenance | M9 manifest があれば open-loop minADE を表示、なければ "stand alone" (どちらも正常) |
| cell-4 download | `aws s3 sync m10-reference/` → アーティファクト一覧 (aggregate/、rollouts/、eval/、run.json) |
| cell-5 parse | AlpaSim 集計表 verbatim + 11 個の driving score (collision 0.00、dist_to_gt 4.37m、progress 0.92) + "Per-rollout time-series: N rows" |
| cell-6 viz | metrics_results.png インライン + safety-rate バー + dist_to_gt_trajectory 時系列 |
| cell-7 video | eval.mp4 (~0.5MB, H.264 1280px) インライン再生 |
| cell-8 cost | CPU の正直なフレーミング + reference run メタ (g6e.12xlarge/m7_4gpu) |
| cell-9 validation | 4 個のチェック OK → **PASS** + headline "no at-fault collisions, no off-road, route progress 0.92" + PIPELINE COMPLETE |

## B5. よくある失敗 → 原因
| 症状 | 原因/解決 |
|---|---|
| cell-4 `M10 reference eval not found in S3` | m10-reference/ 未アップロード → Part A を先に (または既存バンドルを確認) |
| cell-4 download failed / AccessDenied | 実行ロールが shared バケットの read 権限なし → 既に付与済み (正常)。なければ IAM を確認 |
| cell-7 video 空白/未表示 | **ファイル欠落ではなくコーデックの問題。** AlpaSim レンダラーが MPEG-4 Part 2 (`mpeg4`) で書き出し、Chrome/Firefox/Edge はこれをデコードできない — ブラウザは静かに失敗し、これは Python 例外ではないので try/except では捕まえられない。`ffprobe -show_entries stream=codec_name eval/eval.mp4` で確認。根本修正済み: `alpasim_ec2_setup.sh` がアップロード前に H.264 へ変換 (ホストに動作する ffmpeg がなければその事実を出力)、cell-7 は死んだプレイヤーの代わりにコーデックを出力する。必須ではない — メトリクスだけでも PASS |
| STS/import エラー | CPU カーネルに pandas/matplotlib はデフォルト同梱 — ダメなら最初のセルで `%pip install pandas matplotlib` |

---

## 参考: ローカル事前検証は完了済み
ゲート 3 でノートブックのセル 4-9 の **実際のソース**をローカル venv (pandas 2.3.3) でライブ S3 バンドルに対して
実行 → すべて PASS を確認しました。Part B はそれを実際の Studio 環境で再確認するステップです (データパスは
同一ソースなので既に検証済み; 残るはカーネル/ネットワーク/UI レンダリングの差だけ)。
