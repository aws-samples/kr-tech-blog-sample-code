# M10 参加者実行ガイド — 自分の GPU ホストで本物の AlpaSim を回す (SSM)

> ## ⚠️ 先に読んでください — コストと時間
> - この実行は **admin があなたのために立ち上げておいた GPU サーバー (g6e.12xlarge)** 上で回ります。
>   そのサーバーは **時間あたり約 $10.5** が課金されます。
> - **初回ビルドは時間がかかります** — 数十分から最大 2〜3 時間 (コードのコンパイル + コンテナイメージの
>   ダウンロード + NuRec シーンのダウンロード)。ノートブックのように 5 分では終わりません。
> - **あなたはサーバーを消せません。** 終わったら **必ず admin に「完了」を知らせて** admin に
>   サーバーを終了 (terminate) させてください。知らせないと料金が積み上がり続けます。
> - これは M10 の **任意の上級パス**です。結果だけを見たいなら admin の共有参照
>   結果をノートブックで可視化すればよいです (この文書なし、CPU、$0) — [ALPASIM_M10.md](ALPASIM_M10.md)。

M10 は 2 層構造です。**(1) 本物の AlpaSim 実行**は GPU サーバーで (この文書)、**(2) 結果の可視化**は
SageMaker CPU ノートブックで行います。AlpaSim は Docker-Compose で立ち上がる gRPC マイクロサービスの fleet で
ドライバーが ≥40GB GPU を使うため、Docker デーモンのない SageMaker Studio ノートブックでは実行が
不可能です。そのため実行は別の GPU EC2 ホストで行い、ノートブックはその結果をダウンロードして見ます。

---

## 準備物
admin から受け取るもの:
1. **AWS access key** (Access Key ID + Secret) — あなた専用の IAM ユーザー。
2. **あなたの GPU インスタンス ID** (`i-0abc...` 形式)。

あなたが事前に準備するもの (**必須**):
3. **あなたの Hugging Face トークン** (`hf_...`)。AlpaSim がランタイムにゲート NuRec シーン
   (`nvidia/PhysicalAI-Autonomous-Vehicles-NuRec`) をダウンロードしますが、このデータセットは admin の
   共有オフラインキャッシュに **なく** (モデルと違って) あなたのトークンが必要です。事前に:
   - HF アカウント + トークンを作成 (`https://huggingface.co/settings/tokens`)
   - [`nvidia/PhysicalAI-Autonomous-Vehicles-NuRec`](https://huggingface.co/datasets/nvidia/PhysicalAI-Autonomous-Vehicles-NuRec)
     でライセンスに同意 ("Agree and access repository")
   - (任意) `nvidia/Alpamayo-1.5-10B`、`nvidia/Cosmos-Reason2-8B` にも同意しておくと安全 — ただし
     この 2 つは admin が hf-cache に入れているので通常オフラインでロードされます。

admin が 1・2 を out-of-band (Slack/メールなど) で伝えます。3 はあなたのものなので他人に共有しないでください。

---

## 1. 資格情報の設定 + 確認
ローカルターミナル (または CloudShell) で:
```bash
export AWS_ACCESS_KEY_ID=<受け取ったキー>
export AWS_SECRET_ACCESS_KEY=<受け取ったシークレット>
export REGION=us-west-2   # リファレンス配備リージョン; admin が配備したリージョンに置き換える
export AWS_DEFAULT_REGION=$REGION
aws sts get-caller-identity
export ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
# → あなたの IAM user ARN (arn:aws:iam::<account>:user/m7-<your-id>) が出れば正常 (リファレンス配備の例: <aws-account-id>)
```
> Session Manager プラグインが必要です (ほとんどの場合インストール済み)。なければ:
> https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html

## 2. GPU ホストに SSM で接続
```bash
aws ssm start-session --target <your-instance-id> --region $AWS_DEFAULT_REGION
```
- 接続されるとシェルプロンプトが出ます。(SSH キー・インバウンドポート不要 — SSM が処理)
- **他人のインスタンス ID** では接続できません (`AccessDenied`) — 正常です。

## 3. セッション内で AlpaSim を実行
> ⚠️ **各 `export` は必ず 1 行ずつ。** `A=1 B=2` のように export なしで書いたり、貼り付け時に行が分割されると
> 変数がスクリプト (子プロセス) に渡されず、preflight が `HF_TOKEN not set` で失敗したり
> 結果が見当違いのパスに行ったりします。下のように `export VAR=値` を 1 行ごとに書いてください。
```bash
sudo su -
export PARTICIPANT_ID=<your-id>
export M10_OUTPUT_PREFIX=users/<your-id>/m10
export OUTPUT_BUCKET=av30lab-user-workspace-$ACCOUNT-$REGION
export SHARED_BUCKET=av30lab-shared-data-$ACCOUNT-$REGION
export HF_TOKEN=hf_xxx          # 必須 — ゲート NuRec シーンのダウンロード用 (準備物 3 番)

# 伝達確認 (スクリプトを回す前に必ず): 5 個がすべて見えて tok_len が 0 でないこと
env | grep -E 'PARTICIPANT_ID|M10_OUTPUT_PREFIX|OUTPUT_BUCKET|SHARED_BUCKET'; echo "tok_len=${#HF_TOKEN}"

# スクリプトを取得してバックグラウンド(detached)で実行 + ログをリアルタイムで見る
aws s3 cp s3://$SHARED_BUCKET/notebook-templates/scripts/alpasim_ec2_setup.sh /root/
setsid bash /root/alpasim_ec2_setup.sh > /var/log/m7.log 2>&1 &
tail -f /var/log/m7.log
```
- ログの序盤に `[s3] participant self-run: id=<your-id> output=s3://…/users/<your-id>/m10/` が
  見えれば per-user パスに行っています。`admin reference run` が見えたら上の env が伝達されていない —
  Ctrl-C 後に export をやり直して再実行してください。
- `setsid ... &` で立ち上げると SSM セッションが切れても続きます。`tail -f` は Ctrl-C で抜けても
  実行には影響しません (ログを見るのをやめるだけ)。
- **時間がかかります。** ログが止まったように見えてもイメージ pull/シーンダウンロード中のことがあります。

## 4. 成功確認
実行は数十分かかる。**`tail -f` がそれ以上更新されなくなったら終わり** — 成功 (完了) か
失敗 (中断) かはログの **最後の部分** (`tail -n 40 /var/log/m7.log`) で判別する。

**✅ 成功**: ログの末尾に完了マーカーがある。
```
runtime-0-1 exited with code 0
[verify] core outputs present.
=== DONE — genuine AlpaSim results uploaded to s3://av30lab-user-workspace-.../users/<id>/m10/ ===
>>> Participant <id>: results are in ...
```
- 成功時に `tail -f` が止まるのは **正常** (スクリプトが終わったこと — 死んだのではない)。
- 完了直後に `renderer/physics/controller` コンテナが `exited with code 143`(または `137`)と
  表示されるのも **正常**だ (主コンテナが 0 で終わった後に残りを整理)。`runtime-0-1 exited
  with code 0` + `=== DONE ===` があれば成功。

**❌ 失敗/中断**: `=== DONE` が **なく**、代わりにログの末尾が `ERROR:` / `RuntimeError` /
`CUDA out of memory` / `HF_TOKEN not set` だったり、途中でぷつりと切れていたら → 下の **問題解決** 表を
参照。(SSM セッションが切れても setsid 実行は死なないので、再接続して `tail -f /var/log/m7.log` で再び追えばよい。)

素早い判定:
```bash
grep -q "=== DONE" /var/log/m7.log && echo "成功 (S3 アップロード完了)" \
  || echo "未完 — tail -n 40 /var/log/m7.log で ERROR/RuntimeError/切れた地点を確認 → 問題解決表"
```

直接確認 (セッション内またはローカルで):
```bash
# 新しいローカルシェルなら ACCOUNT を再導出 (§3 セッション内なら既に export 済み)
ACCOUNT=${ACCOUNT:-$(aws sts get-caller-identity --query Account --output text)}
aws s3 ls s3://av30lab-user-workspace-$ACCOUNT-$REGION/users/<your-id>/m10/ --recursive
# aggregate/results-summary.json, rollouts/**/metrics.parquet, eval/eval.mp4, run.json が見えれば OK
```

## 5. ⚠️ admin に完了通知 → admin がサーバー終了
あなたはインスタンスを消す権限がありません (コスト事故を防止)。**「m7-<id> 完了」** を admin に知らせてください。
admin が確認後 `terminate-instances` で終了し、課金を止めます。

## 6. SageMaker ノートブックで自分の結果を可視化 (CPU)
1. 参加者ダッシュボード → **M10 ノード** (インスタンスは `ml.t3.medium` CPU のまま) → **Open Workspace**
2. `M10_AlpaSim_ClosedLoop.ipynb` を開いて **Run All**
3. ノートブックが `users/<your-id>/m10/` を自動検出して **あなたの** 結果を可視化します
   (cell-2 が `Result source: your own EC2 run` を出力)。なければ admin 共有参照にフォールバック。

**合格基準**: cell-5 に driving score (collision_at_fault など)、cell-9 に **PASS** + headline。

---

## 問題解決
| 症状 | 原因 / 対処 |
|---|---|
| `aws sts get-caller-identity` 失敗 | キーのタイプミス/失効 → admin に再発行を依頼 |
| `start-session` → AccessDenied | インスタンス ID があなたのものでない → admin に正しい ID を確認 |
| `SessionManagerPlugin not found` | 上のリンクでプラグインをインストール |
| ログに `CUDA out of memory` | admin に通知 (トポロジー調整が必要) |
| ログに `HF_TOKEN not set` / preflight 失敗 | 3 番のステップ `export HF_TOKEN=hf_…` をしていないか export されていない → `echo tok_len=${#HF_TOKEN}` で確認後に再実行 (準備物 3 番) |
| ログに `401` / `GatedRepoError` (NuRec) | HF トークンが NuRec データセットのライセンス未同意 → 準備物 3 番のリンクで "Agree and access" 後に再実行 |
| ログが `admin reference run` で始まる | env がスクリプトに伝達されていない (export 漏れ/行分割) → 3 番のステップの env を再度 export 後に再実行 |
| ノートブック cell-4 `not found` | 3〜4 番のステップがまだ成功していない → ログを確認後に再実行 |
| 全部終わったのにサーバーが消えない | admin のみ終了可能 → admin に通知 |

管理者用のプロビジョニング・IAM・整理手順: [M10_MANUAL_TEST_RUNBOOK.md](M10_MANUAL_TEST_RUNBOOK.md)。
