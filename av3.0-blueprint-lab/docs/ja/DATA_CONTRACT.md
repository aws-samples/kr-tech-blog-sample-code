# AV 3.0 Blueprint Lab — モジュール間データコントラクト

12 個のパイプラインモジュール（M1–M12）は、互いに **S3 経由でのみ**データを受け渡します —
インメモリやノートブック間の状態はありません。このドキュメントは、各モジュールがどの S3 キーを
読み書きするか、そして関与する JSON の形状についての正式な記録であり、あるノートブックの変更が
下流の読み手を黙って壊さないようにするためのものです。

> 2026-07 時点のノートブックに対して検証済み（run-and-improve ハードニング後）。
> モジュールの出力キーを変更する場合は、このファイル**と**下流の読み手を同じ変更の中で
> 更新してください。

## 1. スコープ & バケット

| Env 変数 | デフォルト | 保持するもの |
|---|---|---|
| `USER_BUCKET` | `av30lab-user-workspace-{account_id}-{region}` | `users/{profile}/mN/` 配下のユーザーごとの出力 |
| `SHARED_BUCKET` | `av30lab-shared-data-{account_id}-{region}` | nuScenes ソース、Cosmos/Alpamayo HF キャッシュ、M9 デモ `.pt`、M10 管理者リファレンスバンドル、`notebook-templates/` |
| `USER_PROFILE` | （SageMaker プロファイル名から JupyterLab LCC が注入） | ユーザーごとのプレフィックス `{profile}`。**M4 は未設定だとハードフェイル**します。他のすべてのモジュールは `"default"` にフォールバックします。 |

## 2. モジュールのエッジグラフ（reads → writes）

| モジュール | Reads | Writes | Notes |
|---|---|---|---|
| **M1** データ探索 | 共有 nuScenes-mini | `m1/manifest.json`, `m1/selected_scenes.json` | `selected_scenes.json` = nuScenes シーンレコード全体（name + description）。`cam_front_scenes` は**常に**書き込まれる |
| **M2** Cosmos Reason キャプション | `m1/manifest.json` + 共有 CAM_FRONT jpg | `m2/captions.json` | 各キャプション項目は `scene` + `inference_time_s` を持つ（M3 は `scene` で結合する） |
| **M3** Cosmos Curator | `m1/manifest.json` **と** `m2/captions.json` | `m3/curated_captions.json`, `m3/curation_report.json`, `m3/clips/` | M12 トレーニングコントラクトは `curated_captions` 配下のフラットリスト |
| **M4** OpenSearch 検索 | `m2/captions.json`（**m3 ではない**） | `m4/index_metadata.json`, `m4/embeddings.npy` | `"default"` プロファイルを拒否する唯一のモジュール |
| **M5** Cosmos Transfer | `m1/manifest.json` cam_front + 共有 jpg | `m5/*.mp4`, `m5/source/nuscenes_cam_front.mp4`, `m5/manifest.json` | `m5/source/` クリップは M6 にとって不可欠 |
| **M6** Cosmos Predict | **PRIMARY** `m5/source/` クリップ; **FALLBACK** `m1/manifest.json` | `m6/*.mp4`, `m6/source/`, `m6/manifest.json` | 2 つの入力エッジ — M5 のクリップを優先し、M1 にフォールバック |
| **M7** Nerfstudio | 共有 nuScenes CAM_FRONT を**直接** | `m7/reconstruction_metadata.json`, レンダー | 合成サインウェーブポーズ（スモークテスト）。`splatfacto` セルは gsplat ビルド（`scripts/setup_gsplat_env.sh`）が必要 |
| **M8** Cosmos Reason LoRA SFT | `m1/manifest.json` + 共有 nuScenes **アノテーションテーブル** | `m8/lora_adapter/`, `m8/training_log.json`, `m8/dataset.json`, `m8/loss_curve.png`, `m8/eval_samples.json` | 学習ターゲットは nuScenes の**人手**ラベル（`scene.description`、`sample_annotation`→`instance`→`category`）で、`m2/captions.json` は意図的に**使いません** — Cosmos Reason を自身の出力で学習させると損失が自己参照になります |
| **M9** Alpamayo VLA | 共有 `hf-cache/alpamayo-demo/*.pt` | `m9/manifest.json`, クリップごとの `_pred.npy`/`_gt.npy`/`_cot.txt`, `metrics.json` | `model` + `modes_run` キーは M10 のプロベナンス |
| **M10** AlpaSim クローズドループ | `m9/manifest.json`（**プロベナンスのみ**）+ ユーザー自身の `m10/aggregate/` を**優先**、なければ共有 `m10-reference/` | （S3 出力なし — インラインで可視化） | CPU ノートブック。実際の評価は別個の GPU EC2 で実行される |
| **M11** パイプライン自動化 | `m1/` のみ（`selected_scenes.json` → `manifest.json` → 合成フォールバック） | `m11/pipeline/`（**プライベートスタブ名前空間**）, `m11/pipeline_execution.json`, `m11/pipeline_definition.json` | リーフ。自身の `captions.json`/`curated_captions.json` を `m11/` に**のみ**書き込み、意図的に `m2/`/`m3/` には書き込まない。これにより M3/M4/M12 が依存する本物のものを上書きできない |
| **M12** HyperPod トレーニング | `m3/curated_captions.json` | `m12/input/…`, モデル tarball, `m12/training_metadata.json` | M3 がない場合は合成データセットにフォールバック |

## 3. キースキーマ（正式なキーリスト）

- **`m1/manifest.json`**: `scenes`, `num_samples`, `num_cam_front_frames`,
  `cam_front_files`（nuScenes ルート相対パス）, `cam_front_scenes`,
  `source_bucket`, `source_prefix`
- **`m1/selected_scenes.json`**: `{name, description, ...}` のリスト（M11 が読む）
- **`m2/captions.json`**: `module`, `model`, `generated_at`, `num_captions`,
  `total_inference_time_s`, `avg_inference_time_s`, `prompt_template`,
  `captions[{frame_idx, scene, filename, caption, inference_time_s, timestamp}]`
- **`m3/curated_captions.json`**: `module`, `generated_at`, `curator`,
  `source_modules[]`, `curation_stats{...}`,
  `curated_captions[ <M2 item> + curation_verdict ]`
- **`m9/manifest.json`**: `module`, `profile`, `timestamp`, `model`, `license`,
  `modes_run`, `clips`, `results`（M10 がプロベナンスのために読む）

## 4. 正規の進捗モジュール ID マップ

ダッシュボードの進捗機能（B2）は `moduleProgress` をこれらの ID でキー付けします。信頼できる
情報源は `scripts/av30_progress.py` であり、`web/user/src/data/pipeline-config.ts` と正確に
一致しなければなりません。

| ノートブック | `mark_complete()` id |
|---|---|
| M1_Data_Exploration | `m01-data-exploration` |
| M2_Cosmos_Reason_Captioning | `m02-cosmos-reason` |
| M3_Cosmos_Curator | `m03-cosmos-curator` |
| M4_OpenSearch_Semantic_Search | `m04-opensearch` |
| M5_Cosmos_Transfer_Augmentation | `m05-cosmos-transfer` |
| M6_Cosmos_Predict_Synthesis | `m06-cosmos-predict` |
| M7_Nerfstudio_3D_Reconstruction | `m07-nerfstudio` |
| M8_Cosmos_Reason_SFT | `m08-cosmos-sft` |
| M9_Alpamayo_VLA_Inference | `m09-alpamayo-vla` |
| M10_AlpaSim_ClosedLoop | `m10-alpasim` |
| M11_Pipeline_Automation | `m11-orchestration` |
| M12_HyperPod_Distributed_Training | `m12-hyperpod` |

各ノートブックの最終セルは `mark_complete("<id>")` を呼び出し、これは `X-Api-Key` ヘッダー付きで
`{moduleId, status:"completed"}` を `{AV30_API_URL}/sessions/{profile}/progress` に POST します。
これはベストエフォートかつ非致命的です — ping の失敗がモジュールを失敗させることは決してありません。
バックエンド（`update_progress`）は、短い後方互換 ID `m0`–`m12` も引き続き受け付けます。

## 5. 明記すべきニュアンス

- **M6 の主入力は M5 のクリップ**であり、M1 ではありません — M6 が M1 にフォールバックするのは、
  M5 のソースクリップが欠けているときだけです。
- **M10 は参加者自身の AlpaSim ラン**（`users/{profile}/m10/aggregate/`）を優先し、共有の管理者
  リファレンス（`m10-reference/`）にフォールバックします。
- **M4 は M2 を読み、M3 は読みません** — これは生キャプションから分岐した並列の検索ブランチであり、
  キュレーション済みセットの消費者ではありません。
- **M11 はプライベートな `m11/pipeline/` 名前空間に分岐したスタブスキーマを書き込み**、
  `m2/`/`m3/`（M3/M4/M12 が依存）の上書きを避けます。
- **M1 の `cam_front_scenes` は常に書き込まれます**。一部の下流セルにある `?`/`.get()` ガードは、
  古いマニフェスト向けのものにすぎません。
