# AV 3.0 Blueprint Lab — 参加者向け事前学習ガイド

**ワークショップの前にお読みください。** このガイドは、ハンズオンの各モジュールを理解できるよう、
ラボの背後にある*概念*を教えます。クリック単位の実行手順書では**ありません** — それは
当日使用する [PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md) です。

- ⏱️ **必須の読み物（これは実施してください）：約45〜60分。** セクション 1〜4 ＋ 最初に着手するモジュール。
- 📚 **オプションのより深い掘り下げ：好きなだけ。** セクション 6 に論文、リポジトリ、ドキュメントへのリンクがあります。
- 準備のために何かをインストールしたり、AWS/Hugging Face アカウントを持ったりする必要は**ありません**。
  必須の読み物は概念的なものです。（管理者がすべてを事前キャッシュします。）

---

## 1. 全体像 — 「AV 3.0 / Physical AI」とは何か？

自動運転車の開発は、大きく分けて 3 つの時代を経てきました：

- **AV 1.0** — 手書きのルール ＋ 古典的なロボティクス。ロングテールでは脆い。
- **AV 2.0** — 大規模なラベル付きデータセットによるディープラーニング。より優れているが、
  データを大量に必要とし、依然としてモジュール型（知覚 → 予測 → 計画の各スタックが分離）。
- **AV 3.0** — **エンドツーエンドで、基盤モデル駆動**。大規模なマルチモーダルモデル
  （視覚言語モデル、ワールドモデル、視覚言語**行動**ポリシー）を、膨大な量の実世界の
  データ*および合成*運転データで学習させ、路上に出す前にシミュレーションで評価する。
  「**Physical AI**」は、物理世界（ロボット、AV）で知覚し行動する AI を指す NVIDIA の総称です。

**このラボが扱う中核的な課題：データ。** 現代の AV モデルは、膨大で、*多様*で、*適切にラベル
付けされた*運転データを必要とします — 実際の路上では安全に収集できない、まれで危険な状況
（飛び出してくる子供、ホワイトアウト、逆走車）も含めて。AV 3.0 の答えは、次のような
**データパイプライン**です：
1. 実際のセンサーデータから始め、
2. AI で**キャプションを付けてキュレーションし**（検索可能かつ高品質にする）、
3. 生成的な「ワールドモデル」で、より多くのデータ — 新しい天候、新しいシナリオ — を**合成し**、
4. 運転**ポリシー**を学習させ、
5. 車に触れる前に**クローズドループシミュレーションで評価する**。

このラボは、まさにそのパイプラインを、AWS 上で NVIDIA のオープンモデルを使って、
最初から最後までハンズオンで体験するものです。**あなたは実際のパイプラインを実行します**
（おもちゃではありません）— 小さなデータセットで。

**ここから始めてください：** このラボ全体が実装する、たった 1 つのブログ記事 —
[Building an end-to-end Physical AI data pipeline for AV 3.0 on AWS with NVIDIA](https://aws.amazon.com/blogs/industries/building-an-end-to-end-physical-ai-data-pipeline-for-autonomous-vehicle-3-0-on-aws-with-nvidia/)。
今すぐ一度読んでください。以下のすべては、その記事の地図です。

---

<a id="the-8-stage-pipeline"></a>
## 2. 8 ステージのパイプライン（とモジュールの対応関係）

このブログは**8 ステージ**のパイプラインを定義しています。このラボは各ステージを 1 つ以上の
ノートブックモジュール（M1〜M12）として実装し、**番号はブログのステージ順に従います**。
さらにそれを拡張するいくつかの**補足**モジュール（M6、M11、M12）を加えています。データはモジュール → モジュールへと **S3** を介して
流れます（各モジュールは前のモジュールの出力フォルダを読み、自分の出力を書き込みます）。

```
 real data          AI labeling            synthetic data          policy + eval
 ─────────          ───────────            ──────────────          ────────────
 nuScenes ─▶ M1 ─▶ M2 caption ─▶ M3 curate ─┬─▶ M5 weather aug   (Stage 5)
 (Stage 1-2 explore) (Stage 3)   (Stage 3)   ├─▶ M6 scenario gen (Stage 5)
                        │                     ├─▶ M9 VLA inference ─▶ M10 closed-loop
                        │                     │      (Stage 7)            eval (Stage 8)
                        │                     └─▶ M12 distributed training (ext)
                        └─▶ M4 semantic search (Stage 4)
 nuScenes annotations ─▶ M8 LoRA SFT (Stage 7)  ← human labels, NOT M2's captions
 nuScenes CAM ────────▶ M7 3D reconstruction (Stage 6)    M1 ─▶ M11 orchestration (ext)
```

| ステージ（ブログ） | モジュール | 一言で表す概念 |
|---|---|---|
| 1–2 データ収集と探索 | **M1** | 生の運転データセット（nuScenes-mini）を読み込んで閲覧する。 |
| 3 キャプション生成 | **M2** | 視覚言語モデルが各クリップのテキスト記述を書く。 |
| 3 キュレーション | **M3** | クリップを分割・トランスコードし、動きの少ないクリップ（信号待ちなど）を落とす。M2 のキャプションは、そのシーンのクリップが残ったものだけが引き継がれる。*重複排除もキャプションの品質スコアリングも行わない — 下の代替表を参照。* |
| 4 検索 | **M4** | クリップを埋め込みに変換して、*意味的に*検索できるようにする（「雨の中の左折を探す」）。 |
| 5 オーグメンテーション | **M5** | 「ワールドモデル」が実際のクリップを、再走行せずに新しい**天候／照明**へとリスタイルする。 |
| 5（拡張）シナリオ生成 | **M6** | ワールドモデルがプロンプト／シードから**新しい合成運転映像を生成する**。 |
| 6 ニューラル再構成 | **M7** | カメラ画像から 3D シーンを再構築する（NeRF / Gaussian Splatting）。*（既知の制限あり — §5 を参照。）* |
| 7 モデル学習 | **M8** | 運転 VLM を nuScenes の**人手ラベル**で LoRA ファインチューニングする（M2 のキャプションでは学習しない — それでは循環になる）。 |
| 7 VLA 推論 | **M9** | 視覚言語**行動**モデルが運転軌跡＋その推論を予測する。 |
| 8 クローズドループ評価 | **M10** | そのポリシーを**シミュレータ**に置いてスコアリングする（衝突、路外逸脱など）。 |
| — オーケストレーション（拡張） | **M11** | M1→M2→M3→M5 を、1 つの自動化された再現可能な **SageMaker Pipeline** に結線する。 |
| — トレーニングのスケールアップ（拡張） | **M12** | 分散マルチノードトレーニングの*パターン*（HyperPod）。 |

> **心に留めておくメンタルモデル：** *実データ → ラベル付け → 検索＆クリーニング →
> 合成生成で増幅 → ポリシーを学習 → シミュレーションで証明。*

### このラボがブログを代替している箇所

パイプラインはエンドツーエンドで本物です — 本物の NVIDIA 重み、本物の nuScenes データ、
本物の AWS サービス。ただし**ワークショップ規模**で動作し、いくつかのステージはブログが
指定するものの代替を使っています。モジュールの途中で気づく形にせず、ここにまとめます。

| ステージ | ブログ | このラボ | 理由 |
|---|---|---|---|
| **1–2** 取り込み + 品質ゲート | 物理メディアを **AWS Data Transfer Terminal** 経由で S3 へ; **AWS Batch** がチャンネル/同期/破損を検証; ROS bag・MCAP・ASAM MDF4 コンテナからセンサーデータを抽出 | **M1** は既に抽出済みの nuScenes-mini ツリーを S3 から読んで閲覧する | 物理メディアも抽出対象のコンテナファイルもありません — nuScenes-mini は jpg + json で配布されます。ここでは取り込みも品質ゲートも**行いません**。 |
| **3** キュレーション | **NVIDIA Cosmos Curator** を **SageMaker HyperPod + SLURM** 上で: 分割 → トランスコード → **キャプション生成** → **埋め込み** の 4 サブステージを 1 つの統合パイプラインとして | **M3** は **NeMo Curator**（名前は似ているが別の NVIDIA プロジェクト）で分割 + トランスコード + モーションフィルタのみを行い、キャプション生成と埋め込みはオフ。キャプション生成は **M2**、埋め込みは **M4** | Cosmos Curator は永続 GPU クラスタ上の Docker + SLURM であり、Studio ノートブック内では実行できません。分割（fixed stride）とトランスコード（H.264）はブログと一致し、残る 2 サブステージは別モジュールに移しています。 |
| **3** キャプション生成 | Curator のサブステージとしての **Cosmos Reason**（ブログは `cosmos-reason2` をリンク） | **M2** が **Cosmos-Reason1-7B** を単独実行 | Reason 1 はゲートなしなので、参加者はライセンス承諾も Hugging Face トークンも不要です。 |
| **3** 埋め込み | **Cosmos Embed** — クリップごとの*ビデオ・テキスト結合*ベクトル | **M4** はキャプションの**テキストのみ**を `all-MiniLM-L6-v2`（384 次元）で埋め込む | テキストのみの埋め込みは CPU で数秒です。代償は実在します: 検索は映像が*示す*ものではなく、キャプションが*述べる*ものに一致します。 |
| **4** 検索 | Path A **OpenSearch Service** + NVIDIA cuVS、テキスト+ベクトルの**ハイブリッド**クエリ · Path B **Cosmos Dataset Search** を **EKS** 上で | **M4** は Path A を採るが、OpenSearch **Serverless** でベクトルのみの k-NN | Serverless は 1 日のワークショップでクラスタのサイジングやパッチ適用が不要です。Path B（EKS、専用 UI、データセット組み立てワークフロー）は対象外です。 |
| **5** オーグメンテーション | **EC2 + Amazon DCV**。Cosmos Transfer は*「約 65 GB の GPU メモリを必要とする」*ため、ブログは **G7e**（RTX PRO 6000 Blackwell、96 GB）を挙げている | **M5** は Studio ノートブックで実行。デフォルトの `ml.g5.12xlarge` は**カードあたり 24 GB** なのでシャーディングし、480p + ガードレール OFF に下げます | 24 GB カードはワークショップで確実にクォータを確保できる線です。**ブログが挙げているまさにそのハードウェア**である `ml.g7e.2xlarge`（96 GB 1 枚）はクォータがあれば選択でき、デフォルトより*安価*です。 |
| **6** 再構成 | **NuRec** | **M7** Nerfstudio / gsplat | M7 のヘッダーで既に開示済み。最終学習セルには既知の制限があります。 |
| **7** 学習 | **Alpamayo** | **M8** が nuScenes の人手ラベルで Cosmos Reason を LoRA SFT; **M9** は NVIDIA 公開チェックポイントで Alpamayo の*推論* | Alpamayo には LoRA 経路がなく、フルファインチューニングは重み+勾配+オプティマイザ状態で約 123 GiB を要します。M8 のヘッダーに詳述。 |
| **8** SiL テスト | **AlpaSim** | **M10** は別の GPU EC2 ホストで実行された本物の AlpaSim 結果を可視化 | AlpaSim は Docker Compose + gRPC で、Studio ノートブックではホストできません。 |
| *全体* | HyperPod、AWS Batch、EKS、EC2 + DCV | 単一の SageMaker Studio インスタンス | 参加者・モジュールごとに 1 インスタンスが、ワークショップがプロビジョニング・課金・撤去できる規模です。 |

**代替*ではない*もの:** モデルの重みは NVIDIA の本物、データは本物の nuScenes、表示される
出力はすべて実際に計算されたものです。結果が*欠けている*のではなく*品質が下がっている*
場合（M5/M6 の解像度、M7 の学習セル）は、各モジュールのヘッダーに明記されています。

---

## 3. 始める前に理解しておくべき主要概念

これらを習得する必要はありません — ノートブックがそれらの言葉を使ったときに認識できれば十分です。

### 3.1 基盤モデルと NVIDIA Cosmos ファミリー
**基盤モデル**とは、広範なデータで事前学習され、多くのタスクに適応させる大規模モデルです。
このラボは NVIDIA の *world foundation model*（ワールド基盤モデル）である **Cosmos** ファミリーと、
**Alpamayo** 運転ポリシーを使用します：

| モデル（使用箇所） | タイプ | ここでの役割 |
|---|---|---|
| **Cosmos Reason 1**（M2） | 視覚言語モデル（VLM） | 動画クリップについて「推論」してキャプションを付ける。 |
| **Cosmos Transfer 2.5**（M5） | ワールドモデル（video→video） | 実際のクリップを新しい天候／条件へとリスタイルする。 |
| **Cosmos Predict 2.5**（M6） | ワールドモデル（生成） | 新しい合成運転映像を生成する。 |
| **Alpamayo 1.5**（M9、M10） | 視覚言語**行動**（VLA） | 自車軌跡＋思考の連鎖を予測する。いわば「ドライバー」。 |
| **Cosmos Reason 2**（隠れて、M9/M10） | VLM バックボーン | Alpamayo の内部視覚バックボーン。 |

- **VLM と VLA の違い：** VLM は*テキスト／理解*を出力し、**VLA** はさらに*行動*
  （ここでは：将来の軌跡）を出力します。VLA は AV 3.0 の「エンドツーエンドドライバー」です。
- **ワールドモデル：** シーンの*将来のフレーム*を予測／生成する生成モデル — 
  合成データの背後にあるエンジン（M5/M6）。
- **ライセンスに関する注記：** Alpamayo（M9/M10）は**非商用**（研究・評価のみ）です。
  ダウンロードはしません。M9/M10 を実行することでそのライセンスに同意したことになります。

### 3.2 データセット — nuScenes
[**nuScenes**](https://www.nuscenes.org/) は、広く使われているオープンな AV データセット
（Motional）です：マルチカメラ ＋ LiDAR ＋ レーダーの運転シーンに、豊富なアノテーションが
付いています。ラボはすべてを安価に実行できるよう **nuScenes-mini**（小さなサブセット）を使います。
**シーン**は約 20 秒のクリップで、**CAM_FRONT** は M5/M7 が使う前方カメラのストリームです。

### 3.3 合成データとそれが重要な理由
実データはロングテールを安全にカバーできません。**オーグメンテーション**（M5：同じシーン、
新しい天候）と**シナリオ生成**（M6：まったく新しい合成クリップ）は、再走行せずに多様性を
増幅します。これが AV 3.0 のデータ戦略の核心です。

### 3.4 埋め込みと意味的検索（M4）
**埋め込み**は、クリップ／キャプションをベクトルに変換し、*意味が似ている → 近いベクトル*
となるようにします。それらをベクトルインデックス（ここでは **Amazon OpenSearch
Serverless**）に格納すれば、ファイル名ではなく意味で検索できます（「夜、歩行者、横断歩道」）—
**k-NN** が最も近いベクトルを見つけます。

### 3.5 クローズドループ評価とオープンループ評価（M9 → M10）
- **オープンループ（M9）：** ログに記録されたデータをポリシーに与え、その予測軌跡を実際に
  起きたことと比較する（メトリクス：minADE — 平均軌跡誤差）。
- **クローズドループ（M10）：** ポリシーを*シミュレータの中*に置き、そこでは自身の行動が
  次に見えるものを変える — より現実的なテスト。メトリクス：衝突、路外逸脱、正解経路への距離。
  ここでのシミュレータは **AlpaSim** です。

### 3.6 分散トレーニング（M12）とオーケストレーション（M11）— 「本番」の概念
- **分散トレーニング（M12）：** 実際のモデルは 1 つの GPU には大きすぎるため、トレーニングは
  勾配を同期する多数のノードに分割されます（**DDP** / `torch.distributed`）。
  **SageMaker HyperPod** は、これを大規模に行うための AWS のマネージドクラスターです。
  *（ラボでは M12 は小さな CPU インスタンス上でマルチノードのパターンを実演します — §5 を参照。）*
- **オーケストレーション（M11）：** ノートブックを手作業で実行する代わりに、各ステップを
  **SageMaker Pipeline** として定義します — 再現可能でパラメータ化された DAG（有向非巡回グラフ）で、
  各ステップが自身の計算リソースを開始／停止し、リネージが追跡されます。

### 3.7 触れることになる AWS プラットフォーム
- **Amazon SageMaker Studio / JupyterLab** — ブラウザ内のノートブック環境。
- **インスタンスと GPU** — 軽い作業には CPU（`ml.t3.medium`）、モデルには GPU（`ml.g5.*`、
  `ml.p4d.*`）。インスタンスはダッシュボードから選び、プラットフォームが対応する GPU
  ソフトウェアイメージを読み込みます。**GPU の時間には実際のお金がかかります** — GPU
  モジュールの間は CPU に戻してください。
- **S3** — すべてのモジュールが入力を読み、出力を書き込む場所（これがモジュール間のデータの
  流れ方であり、インスタンス変更後も結果が残る理由です）。

---

## 4. 実際にできる必要があること（スキルチェック）

このラボは、以下に慣れていれば取り組みやすいものです：
- **基本的な Python と Jupyter** — セルを上から下へ実行し、出力／エラーを読むこと。
  （コードは*実行*しますが、あまり書きません。）
- **ノートブックを読むこと** — コードセルの間の markdown 説明をたどること。
- **ごく基本的な ML 用語** — モデル、推論、トレーニング、データセット、GPU。

以下は**必要ありません**：ディープラーニングの数学、CUDA、AWS の管理、または AV の
事前経験。AWS 固有のこと（インスタンスの選択、ワークスペースを開くこと）はすべて、
実務的な [PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md) にあります。

**Jupyter が初めてですか？** 10 分の
[JupyterLab インターフェースツアー](https://jupyterlab.readthedocs.io/en/stable/user/interface.html)
にざっと目を通してください — 「セルの実行 = Shift+Enter」と「Run ▸ Run All Cells」を
知っておくだけで十分です。

---

## 5. 当日に驚かないために知っておくべき 2 つのこと

- **M10 と M12 のノートブックは CPU です** — GPU スケールのアイデアに関するものであるにも
  かかわらず。M10 は管理者が GPU ホスト上で実行したクローズドループシミュレーションを
  *可視化*します。M12 は別のマネージドインスタンス上で実行される実際の 2 ノードトレーニング
  ジョブを*送信*します。これは設計上のものです — ノートブックがオーケストレーションし、
  重い計算は別の場所で行われます。
- **M7（3D 再構成）は既知の制限があります。** GPU チェックとデータ準備のセルは実行され、
  ステージを示しますが、最終的な 3D トレーニングのセルは現在のワークショップイメージでは
  **実行されません**（CUDA のビルドツールのギャップ）。M7 はオプション／デモモジュールとして
  扱ってください。最後のセルがエラーになっても驚かないでください。

当日の推奨パス：**M0（概要）→ M1 → M2 → M3**、その後、興味のあるもの（M5/M6 合成データ、
M9/M10 ポリシー＋シミュレーション、M4 検索、M12/M11 本番パターン）へと枝分かれしてください。

---

## 6. オプションのより深い掘り下げ（興味に応じて）

もっと深く理解したいものに合う行を選んでください。これらのいずれもワークショップには
必須ではありません。

### パイプラインとプラットフォーム
- 📄 **AWS + NVIDIA AV 3.0 ブログ**（このラボ全体の源） —
  [aws.amazon.com/blogs/industries/…av-3-0…](https://aws.amazon.com/blogs/industries/building-an-end-to-end-physical-ai-data-pipeline-for-autonomous-vehicle-3-0-on-aws-with-nvidia/)
- 📘 **Amazon SageMaker Studio** ドキュメント —
  [docs.aws.amazon.com/sagemaker/latest/dg/studio.html](https://docs.aws.amazon.com/sagemaker/latest/dg/studio.html)
- 📘 **SageMaker Pipelines**（M11） —
  [docs.aws.amazon.com/sagemaker/latest/dg/pipelines.html](https://docs.aws.amazon.com/sagemaker/latest/dg/pipelines.html)
- 📘 **SageMaker HyperPod**（M12） —
  [docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod.html](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod.html)

### モデル（NVIDIA Cosmos と Alpamayo）
- 🧩 **NVIDIA Cosmos** — モデルの本拠地、現在は **Cosmos 3**：
  [github.com/NVIDIA/Cosmos](https://github.com/NVIDIA/Cosmos)
- 🧩 **Cosmos Cookbook** — このラボが参照するポストトレーニングのレシピ集（**別**リポジトリで、
  Cosmos 3 のリリース以降はメンテナンスのみ）：
  [github.com/nvidia-cosmos/cosmos-cookbook](https://github.com/nvidia-cosmos/cosmos-cookbook)
  · ドキュメントサイト：[nvidia-cosmos.github.io/cosmos-cookbook](https://nvidia-cosmos.github.io/cosmos-cookbook/)
- 🧩 **Cosmos Reason 1**（キャプション生成、M2） —
  [huggingface.co/nvidia/Cosmos-Reason1-7B](https://huggingface.co/nvidia/Cosmos-Reason1-7B)
- 🧩 **Cosmos Transfer 2.5**（天候オーグメンテーション、M5） —
  [huggingface.co/nvidia/Cosmos-Transfer2.5-2B](https://huggingface.co/nvidia/Cosmos-Transfer2.5-2B)
- 🧩 **Cosmos Predict 2.5**（シナリオ生成、M6） —
  [huggingface.co/nvidia/Cosmos-Predict2.5-2B](https://huggingface.co/nvidia/Cosmos-Predict2.5-2B)
- 🧩 **Alpamayo 1.5**（VLA ポリシー、M9/M10） —
  [huggingface.co/nvidia/Alpamayo-1.5-10B](https://huggingface.co/nvidia/Alpamayo-1.5-10B)
  （非商用）

### データ、シミュレーション、再構成
- 🚗 **nuScenes** データセット — [nuscenes.org](https://www.nuscenes.org/)
- 🕹️ **AlpaSim** シミュレータ（M10） — [github.com/NVlabs/alpasim](https://github.com/NVlabs/alpasim)
- 🧊 **Nerfstudio**（M7、3D 再構成） — [docs.nerf.studio](https://docs.nerf.studio/)
- 🔎 **Amazon OpenSearch Serverless** ベクトル検索（M4） —
  [docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless.html)

### 用語が初めてだった場合の概念
- **基盤モデル／ワールドモデル**、**VLM**、**VLA** — 上記の Cosmos と Alpamayo の
  モデルカードを参照（それぞれがそのタスクを説明しています）。
- **分散データ並列トレーニング（DDP）** — PyTorch
  [Distributed Overview](https://docs.pytorch.org/tutorials/beginner/dist_overview.html)。
- **ベクトル埋め込みと k-NN 検索** — 上記の OpenSearch ベクトル検索ガイド。

### 最も深い掘り下げ：このリポジトリ内のモジュールドキュメント
難しい各モジュールには、それがどう実行され、なぜそうなるのかを正確に説明する
エンジニアリングの解説があります：
[COSMOS_M5_M6.md](COSMOS_M5_M6.md) · [ALPAMAYO_M9.md](ALPAMAYO_M9.md) ·
[ALPASIM_M10.md](ALPASIM_M10.md) · [HYPERPOD_M12.md](HYPERPOD_M12.md) ·
[PIPELINE_M11.md](PIPELINE_M11.md)。これらは、モジュールを実行して内部の仕組みを知りたく
なった*後で*読んでください。

---

## 7. 「準備できた？」チェックリスト

セクション 1〜3 から次に答えられれば、ワークショップの準備は万全です：

- [ ] 一文で、AV 3.0 データパイプラインは*何のため*のものか？
- [ ] 5 つのフェーズを挙げてください：実データ → ? → ? → ? → ?
- [ ] **VLM**（M2）と **VLA**（M9）の違いは何か？
- [ ] なぜラボは、実際のクリップを使うだけでなく**合成データを生成する**（M5/M6）のか？
- [ ] **オープンループ**（M9）と**クローズドループ**（M10）の評価の違いは何か？
- [ ] なぜモジュールはデータをメモリ内ではなく **S3** を介して受け渡すのか？
- [ ] どのモジュールが**既知の制限あり**で、何を予想すべきか？ *（M7 — トレーニングセルが実行されない。）*

質問が曖昧なら、§3（または §1 のブログ）でその概念をもう一度ざっと見直してください。
それが必要な準備のすべてです — 当日、[PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md) でお会いしましょう。
