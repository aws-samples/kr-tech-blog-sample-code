# SageMaker Pipelines (M11) — 実際のオーケストレーションデモ、設計上 CPU

**ステータス:** M11 は **実際の SageMaker Pipeline を定義して実行します** — 3 ステップの
依存関係 DAG (Caption → Curate → Augment) を `upsert()` + `start()` し、完了までポーリングし、
実行を S3 に記録します。定義のみのデモではありません。ステップスクリプトは M1 のシーン
メタデータに対する純粋な Python なので、ステップは **CPU** (`ml.m5.xlarge`) で実行されます;
教育上のポイントは **オーケストレーションのパターン** であり、計算ではありません。

## M11 が何だったか、そして今何であるか

M12 と同様に、M11 は **ハルシネーション API の失敗ではありませんでした** — すべてのインポートと
クラス (`Pipeline`、`ProcessingStep`、`PipelineSession`、`ScriptProcessor`) は実在の
SageMaker Python SDK **v2** です。その問題は M12 が当たったのと同じ系統に加えて、いくつか
独自のものがありました:

| 出荷された M11 | 修正された M11 |
|---|---|
| `from sagemaker import Session` (v2 トップレベル) → SDK-v3 カーネルで失敗 | cell-1 で v2 をピン留め (`>=2.257.2,<3`) + カーネル自動再起動 (M12 から) |
| Step1 は `INPUT_DIR/*.jpg` を glob したが、M1 は JSON のみを `m1/` に書く → 0 キャプション | Step1 は M1 の `selected_scenes.json` (実際のシーン名 + 説明) を読む → 根拠のあるキャプション |
| 3 ステップが `ml.g5.12xlarge`/`g5.xlarge` (GPU) を要求 — 処理クォータはここで 0 | CPU `ml.m5.xlarge` (処理クォータが利用可能); スクリプトは純粋な Python なので GPU は何も追加しない |
| GPU `pytorch-training` イメージ | `image_uris.retrieve("sklearn", …)` 経由の CPU sklearn コンテナ — **`image_scope` なし** (sklearn には `processing` スコープがなく、渡すと `ValueError: Unsupported image scope` を出す) |
| exec ロールに `CreatePipeline`/`StartPipelineExecution`/`CreateProcessingJob` が欠けていた | CDK exec ロールに `SageMakerPipelines` (pipeline/av30-*) + `SageMakerProcessingJobs` (processing-job/*) を追加 |
| SDK のアップロード (ステップコード、パイプライン定義) はデフォルトで `sagemaker-<region>-<account>` ルート — ロールの `users/*` 書き込みスコープ外 → AccessDenied | `Session`/`PipelineSession(default_bucket=USER_BUCKET, default_bucket_prefix=users/<profile>/m11)` |
| コストセルは GPU レートをハードコード | `execution.list_steps()` + CPU レートからの実際のステップごとの時間; GPU は概念的な本番として表示 |

## なぜ CPU なのか (そしてなぜそれが正しい選択なのか)

3 つのステップスクリプトは **モデル推論を行いません** — Step1 は M1 のシーン `description`
文字列からキャプションを構築し、Step2 はキーワードスコアフィルター + md5 重複排除、Step3 は
テンプレート文字列の拡張です。そのどれも GPU を使いません。したがって、ステップを GPU で
実行するのは純粋な無駄です (そして g5 の *処理* クォータはこのアカウントでいずれにせよ 0 です)。
**M11 が教える価値はオーケストレーション** です — 再現可能な依存関係 DAG、自動的に開始/停止する
ステップごとのインスタンス、そして完全なリネージ — そしてそれは、ステップが CPU で実行されようと
GPU で実行されようとバイト単位で同一です。本番では、キャプショニングステップは実際の VLM
(例: Cosmos Reason) を実行する GPU イメージに切り替わるでしょう; 変わるのはステップごとの
計算のみで、パイプラインではありません。

## M1 → M11 のデータリンク (実際)

Step1 は `s3://<user-workspace>/users/<profile>/m1/` をマウントし、`selected_scenes.json`
を読み取ります — M1 が選択した実際の nuScenes シーンで、それぞれ `name` (例: `scene-0061`) と
人間による `description` (例: "Parked truck, construction, intersection, turn left,
following...") を持ちます。キャプションはそれらの実際の説明に根拠を持つため、パイプラインは
カウントを作り上げるのではなく本物の上流出力を消費します。(M1 は画像ファイルを `m1/` に
コピーしません; シーンメタデータを記録し、共有 nuScenes データセットを指し示します — なので
メタデータが消費すべき正しいものです。)

## M11 のために追加された IAM (CDK、最小権限)

`infra/av30_constructs/sagemaker.py` で、SageMaker 実行ロールに追加:
- `SageMakerPipelines` — `CreatePipeline`/`UpdatePipeline`/`StartPipelineExecution`/
  `Describe*`/`ListPipelineExecutionSteps`/…、`pipeline/av30-*` にスコープ。
- `SageMakerProcessingJobs` — `processing-job/*` 上の `CreateProcessingJob`/`DescribeProcessingJob`/
  `StopProcessingJob`/`AddTags` (SDK は処理ジョブを自動命名するため、リソースをプレフィックスで
  スコープできない)。
- `iam:PassRole` — M12 のために追加された、自分自身のみの `PassedToService=sagemaker.amazonaws.com`
  ステートメントを再利用; ProcessingSteps がこのロールをコンテナに渡す。

## 浮上したバグ (M12 の反映 + パイプライン固有)

M12 と同じ v2/v3 SDK チェーン (#1 v3 カーネル、#2 メモリ内混在 / カーネル再起動)、に加えて:
- **パイプライン/処理 IAM** — M12 はトレーニングジョブの権限のみを追加した; M11 には上記の
  Pipeline + Processing セットが必要 (ライブ exec ロール `av30lab-sagemaker-execution-role`
  でデプロイ & 検証済み)。
- **アップロードスコープ** — `default_bucket_prefix` により、すべての SDK アップロードが
  `users/<profile>/m11/` (exec ロールが書き込める唯一のパス) の下に着地する。ピン留めされた
  SDK 2.257.3 で `Session` と `PipelineSession` の両方に存在することを検証済み。
- **GPU クォータ 0** — ステップを CPU に移動 (M12 が CPU を使うのと同じ理由)。
- **空の入力** — 存在しない `*.jpg` ではなく、M1 の `selected_scenes.json` を消費する。
- **`image_scope="processing"` ブロッカー (事前実行監査で発見)** — cell-3 は
  `image_uris.retrieve(framework="sklearn", …, image_scope="processing")` でステップイメージを
  構築していたが、これは `ValueError: Unsupported image scope: processing` を出す (sklearn の
  レジストリには `inference`/`training`/`inference_graviton` しかない)。これは *あらゆる* 実行で
  cell-3 の最初の行で失敗した — パイプラインが定義される前なので課金はないが、ハードな
  デッドストップだった。修正: `image_scope` を省略する; 返される
  `…/sagemaker-scikit-learn:1.2-1-cpu-py3` が正しい CPU イメージ (これが `SKLearnProcessor` が
  内部でそれを解決する方法)。ピン留めされた SDK を隔離された venv にインストールし、正確な
  呼び出しを再現することで捕捉したので、課金されるステップが決して当たることはなかった。
- **実際の M2/M3 モジュールとの出力名前空間の衝突 (事前実行監査で発見)** — ステップは元々
  `users/<profile>/m2/captions.json` と `…/m3/curated_captions.json` に書いていた — 実際の
  M2/M3 モジュールが生成する *まさにそのキーとファイル名* だが、互換性のないデモスキーマ
  (キャプションごとの `filename` なし、トップレベルの `model` なし) だった。M11 を実行すると
  参加者の本物の M2/M3 出力を静かに上書きし、その後の **M4** (`m2_output["model"]`、
  `cap["filename"]`) または **M3** (`captions[0]["filename"]`) の再実行が `KeyError` で
  クラッシュしていただろう。M2/M3/M4 のノートブックソースに対して検証済み。修正: 3 つの
  ステップ出力すべてを **M11 専用の名前空間** `users/<profile>/m11/pipeline/stepN_*/` に
  ルーティングする (Step 1 は依然として実際の `m1/` を読み取り専用で読む)。DAG/依存関係/
  リネージは変更なし; M11 は今や自己完結し、他のモジュールのデータを汚染できない。(実際の M1
  データに対して完全な 3 ステップ DAG をローカルで再実行して確認: 3→3→3→9、そして m2/m3/m4 には
  何も書かれない。)

## 検証済みの実行

**マネージド実行の検証済み (2026-07-14、Studio Run-All、参加者プロファイル `ky-5-34x1bx`)。**
実際の SageMaker Pipeline が upsert され、CPU 上でエンドツーエンドで実行されました:

```
execution: av30-data-pipeline-ky-5-34x1bx/execution/3p1jfdpcp0ga  → Succeeded
  AV-Captioning       Succeeded  154s   (read real m1/selected_scenes.json)
  Data-Curation       Succeeded  153s
  Data-Augmentation   Succeeded  303s
  step compute total: 610s → ~$0.039 @ ml.m5.xlarge; wall time 634s
```

実行後にライブ S3 に対して確認:
- **実際の M1 → M11 リンク:** 9 個の最終キャプションは M1 の実際の nuScenes シーン説明
  (トラック / 建設 / サイクリスト / 横断歩道) に根拠を持つ、9/9 — 合成ではない。
- **出力の隔離:** ステップ出力は `users/ky-5-34x1bx/m11/pipeline/step{1,2,3}_*/` の下にのみ
  着地した; 実行記録は `m11/pipeline_execution.json` (ステータス Succeeded、3/3 ステップ) +
  `m11/pipeline_definition.json`。SDK のコードアップロードは `users/…/m11/` の内側に留まった
  (AccessDenied なし — `default_bucket_prefix` が機能)。
- **衝突なし:** 実際の `m2/captions.json` (22649 B) と `m3/curated_captions.json` (24767 B) は
  **手つかず** のまま残った — 専用名前空間の修正 (バグ #4) が実際の環境で検証された。

両方の事前実行監査ブロッカー (`image_scope="processing"` ValueError; m2/m3 出力衝突) は、
この実行の *前に* 修正されたため、防止可能な失敗に課金ステップを 1 つも浪費することなく、
最初のマネージド実行で成功しました。
