# Cosmos Transfer / Predict (M5, M6) — SMD イメージ上での実際の推論

**ステータス:** M5 (Cosmos Transfer 2.5、edge → weather) と M6 (Cosmos Predict 2.5、
video2world) は、いずれも SageMaker Distribution (SMD) GPU イメージ上で **エンドツーエンドで
検証済み** です — M5 はリポジトリの例 + 実際の nuScenes CAM_FRONT クリップで、M6 は完全な
JupyterLab の "Restart & Run All" で検証しました。両方とも、オフライン S3 チェックポイント
キャッシュを介して **参加者の HF トークンなし** で動作するようになりました (下記の
「オフラインチェックポイントキャッシュ」を参照)。

## これらのモジュールが抱えていた中核的な問題

出荷されたノートブックは、**存在しない** **ハルシネーションによる `cosmos1` パッケージ**
(`from cosmos1.models.diffusion.inference... import load_model_by_config`、
`WorldGenerationPipeline`、`cosmos1.utils.video_utils`) をインポートしていました。
`pip install cosmos-transfer2` は存在しません。実際のワークフローは:

1. 公式リポジトリ `github.com/nvidia-cosmos/cosmos-transfer2.5` をクローンする。
2. `uv sync --extra=cu128 --python 3.10` (torch 2.7 + cu128、transformer-engine、
   megatron — すべて **プリビルド** ホイールで、ソースコンパイルなし)。
3. `examples/inference.py -i <spec.json> -o <outdir> control:edge` を実行する。

M7 (gsplat は SMD イメージができないソース CUDA コンパイルを必要とする) とは異なり、
**M5 はすべてプリビルド** です — そのため、いったん環境が配線されれば、そのまま動作し、
スクリプトで再現可能です。

## `scripts/setup_cosmos_env.sh`

1 つの冪等なスクリプトが、インスタンスの NVMe (`/mnt/sagemaker-nvme`、p4d/p5 上では 28 TB)
に対してインストール全体を行い、ノートブックが source する `cosmos_env.sh` を書き出します。
我々が発見しなければならなかったすべての環境修正がエンコードされています:

| # | 症状 | 根本原因 | スクリプト内の修正 |
|---|---------|-----------|---------------|
| 1 | `ImportError: libGL.so.1` に続いて `libgthread-2.0.so.0` | `opencv-python` (GUI ビルド) は SMD イメージに欠けているシステム GL ライブラリを必要とする | `opencv-python-headless` のみを残す |
| 2 | `CalledProcessError: ldconfig -p \| grep libnvrtc` | transformer-engine の `_load_nvrtc()` が `ldconfig` を実行する; pip の CUDA ライブラリはリンカーキャッシュにないため、grep が 1 で終了し、フォールバックの前にクラッシュする | pip の `nvidia/` ツリーに `CUDA_HOME` を設定し、TE の再帰的な glob が最初に `libnvrtc` を見つけられるようにする |
| 3 | `OSError: libcublas.so.12: cannot open shared object file` | TE がバージョン付き SONAME を `dlopen` する; pip の CUDA ディレクトリがローダーパスにない | すべての `nvidia/*/lib` を `LD_LIBRARY_PATH` に置く |
| 4 | `RuntimeError: Unable to dlopen libcudart.so` | TE が **バージョンなし** の名前を `dlopen` する; pip ホイールは `libcudart.so.12` のみを同梱する | `libX.so → libX.so.NN` シンボリックリンクを作成する |
| 5 | `Access denied. This repository requires approval` | Cosmos チェックポイントは HuggingFace でゲートされている | ライセンスに同意したアカウントの `HF_TOKEN` (下記) |
| 6 | `RuntimeError: Unable to parse string as hex hash value` | hf-xet のチャンク化ダウンロードバックエンドのバグ | `HF_HUB_DISABLE_XET=1` |

`ldconfig` (ステップ 3 に隣接) も念のため `/etc/ld.so.conf.d/pip-nvidia-cuda.conf` 経由で
登録されますが、`cosmos_env.sh` 内の `LD_LIBRARY_PATH` が本当の保証です (一部の SMD アプリ
シェルは conf.d ファイルを拾いませんでした)。

### ゲート付き HuggingFace リポジトリ (HF アカウントごとに一度ライセンスに同意)

- https://huggingface.co/nvidia/Cosmos-Guardrail1
- https://huggingface.co/nvidia/Cosmos-Transfer2.5-2B
- https://huggingface.co/nvidia/Cosmos-Reason1-7B  (プロンプト/ガードレールの推論器として使用)
- (M6) https://huggingface.co/nvidia/Cosmos-Predict2.5-2B

セットアップセルを実行する前に `export HF_TOKEN=hf_xxx` を設定してください。**トークンを
コミットしないでください。** トークンが露出した場合は、
https://huggingface.co/settings/tokens で失効させてください。

## M5 ノートブックのフロー (書き直し済み)

`notebooks/M5_Cosmos_Transfer_Augmentation.ipynb` は現在:

1. **設定** — プロファイル/バケット、NVMe 作業ディレクトリ、天候プロンプト、`HF_TOKEN`。
2. **GPU チェック** — 任意の ≥ 24 GB GPU ボックス (`total_memory`、`total_mem` ではない)。
3. **インストール** — `scripts/setup_cosmos_env.sh` を実行 (冪等; 新しいアプリの初回実行では
   ~15-25 分、以降はほぼ瞬時)。
4. **入力の構築** — `m1/manifest.json` を読み取り、共有バケットから記載された nuScenes
   CAM_FRONT フレームをダウンロードし、そのうち ≤57 個をつなぎ合わせて
   1280×704 @ 10 fps の mp4 にする。
5. **spec の構築** — 天候条件ごとに 1 つの JSON; `control_path` を **省略** して Cosmos が
   Canny エッジコントロールをオンザフライで計算するようにする (`--video-path` のみ)。
6. **推論** — spec ごとに `examples/inference.py ... control:edge` (35 拡散ステップ;
   p4d/p5 上でクリップあたり ~3-5 分)。
7. **アップロード** — 生成された + エッジコントロールの mp4 + ソースクリップ + マニフェスト → `m5/`。
8. **コスト + 検証 + インラインプレビュー。**

ワークショップの実行を安価に保つため、デフォルトは `CONDITIONS = ["rain"]` です;
すべてのバリアントには `["rain","fog","night"]` に拡張してください。

### 検証済みの実行 (2026-07-07、リファレンスデプロイ例 account <aws-account-id>)

- リポジトリの例: `robot_edge_spec.json` → `robot_edge.mp4` (3.8 MB、35/35 ステップ)。
- nuScenes: 57 CAM_FRONT フレーム → 自動エッジ → `nuscenes_rain.mp4`
  (ログ内の `{'edge': None}` がオンザフライのエッジを確認; 35/35 ステップ、実行中の
  GPU ボックスで ~4m38s)。

## M6 (Cosmos Predict 2.5) — 検証済み

M6 は同じハルシネーションによる API (`WorldGenerationPipeline`) を出荷していました。実際の
パスは兄弟リポジトリ **`github.com/nvidia-cosmos/cosmos-predict2.5`** です — Transfer と
同じインストール形状 (`cosmos-oss[cu128_torch27]`、`uv sync --extra=cu128`、同じ
CUDA/opencv 修正) ですが、**独自の `.venv`** 内に **別個の** トップレベルパッケージ
(`cosmos_predict2`) を持ちます。2026-07-09 にエンドツーエンドで検証済み (KY-5、p5.48xlarge、
H100×8)。

- `scripts/setup_cosmos_env.sh` は引数を取るようになりました: `transfer` | `predict` | `both`
  (デフォルト)。`prepare_repo()` は各リポジトリをクローン + `uv sync` して独自の venv に入れ、
  共有の修正を適用し、スタックごとの env ファイルを書き出します: **`cosmos_env.sh`**
  (Transfer/M5) と **`cosmos_predict_env.sh`** (Predict/M6)。M6 は後者を source します。
- M6 ノートブック (`notebooks/M6_Cosmos_Predict_Synthesis.ipynb`) は実際のフローに書き直されました:
  セットアップを実行 (`predict`) → M5 の nuScenes クリップを再利用 (`m5/source/`、なければ
  M1 から再構築) → Video2World の spec を構築 → `examples/inference.py -i spec
  -o out --inference-type=video2world` → `m6/` にアップロード。
- **入力 spec** (Predict 2.5): `{"inference_type":"video2world", "name":..,
  "prompt":.., "input_path":<mp4>}`。`input_path` に注意 (Transfer の `video_path` ではない)。
  ベース 2B には `--experiment`/`--checkpoint-path` は **不要** です; モードは自動検出されます
  (2 以上のビデオフレーム → video2world)。チェックポイント
  (Cosmos-Predict2.5-2B/base/post-trained、Reason1.1-7B、Guardrail1) は HF から `HF_HOME`
  へ自動ダウンロードされます。
- **検証済みの実行**: nuScenes CAM_FRONT クリップ → `near_collision` プロンプト →
  `Generating video with standard mode... 36/36 [~4m07s]` → `nuscenes_near_collision.mp4`。

### M6 の配線中に見つかった 2 つのバグ (setup_cosmos_env.sh で修正済み)
- **uv venv には `pip` がない。** リファクタリングで一時的に opencv クリーンアップに
  `"$venv/bin/python" -m pip` を使用 → `No module named pip`。そのため GUI の `opencv-python`
  がそのまま残り、`import cv2` が `libgthread-2.0.so.0` に当たった (M5 と同じ libGL ファミリー)。
  修正: **`VIRTUAL_ENV=$venv uv pip ...`** を使う (uv venv には常に `uv pip` があり、`pip` は
  決してない)。
- **git-lfs が素の SMD シェルの PATH にない** → `git clone` のチェックアウトが失敗する
  (`git-lfs filter-process: git-lfs: not found`)。修正:
  `-c filter.lfs.smudge= -c filter.lfs.process= -c filter.lfs.required=false` でクローンする
  (コードファイルは取得され; LFS の例示アセットはポインターのまま残るが、それは不要)。

## オフラインチェックポイントキャッシュ — 参加者の HF トークン不要

M5/M6 の `examples/inference.py` は、ランタイムに Hugging Face 自身のキャッシュ
(`checkpoint_db` → `uvx hf download`) を通じてゲート付き Cosmos チェックポイントを取得します。
すべての参加者に HF アカウント + トークン + ライセンス承認を強いることを避けるため、一度
キャッシュしてオフラインで実行します:

- **管理者 (一度):** 管理者の HF トークン (ライセンス承認済み) を持つ GPU アプリ上で M5 + M6 を
  実行し、その後 `aws s3 sync /mnt/sagemaker-nvme/hf/hub s3://<shared>/hf-cache/hub/`。
  モジュールを実行すること (素の `hf download` ではなく) が、cosmos が必要とするすべての
  リビジョン + サイドファイル (Wan2.1 VAE、Reason1.1、Guardrail1、…) がツリーにあることを保証します。
- **参加者のセットアップ:** `setup_cosmos_env.sh` が `hf-cache/hub/` を `$HF_HOME/hub` へ
  `aws s3 sync` で戻し、生成された `cosmos_env.sh` / `cosmos_predict_env.sh` が **そのキャッシュが
  存在する場合にのみ** **`HF_HUB_OFFLINE=1`** (+ `TRANSFORMERS_OFFLINE=1`) を export します。
  すると cosmos はトークンなし、ネットワークなしでキャッシュからロードします。
- **検証済み (2026-07-09):** `HF_TOKEN=""` および `HF_HUB_OFFLINE=1` で、M6 の video2world が
  36/36 ステップを完了しました — `uvx hf download` がオフラインモードを尊重し、ローカル
  キャッシュにヒットしました。同じメカニズムが M5 をカバーします。
- **フォールバック:** `hf-cache/hub/` が S3 に存在しない場合、セットアップはオンラインモードを
  有効なままにし、呼び出し元が提供する `HF_TOKEN` で依然ダウンロードします (ライセンス承認が
  必要)。ノートブックはトークンが欠けていても、もはやハードに失敗しません — オフライン
  キャッシュを想定し、どちらも利用できない場合にのみ、実際のダウンロード時にエラーになります。

## インスタンス / コストに関する注記

- **どの GPU インスタンスでも動くわけではありません** — 両モデルとも 1 GPU に載せるには
  約 65 GB が必要です。24 GB カードでは **GPU 2 枚以上**が必要で、シャーディングして実行
  されます。1 枚の場合はノートブックが `RuntimeError` で停止し、マルチ GPU インスタンスを
  選ぶよう案内します（M5 cell 2 / M6 cell 2）。p5.48xlarge（H100×8）と p クラスで検証済みです。
  ブロッカーは決してインスタンスではありませんでした — 環境の配線であり、それは今やスクリプト化
  されています。
- env + チェックポイントは NVMe 上に存在し、**アプリ再起動時にリセットされます**;
  セットアップセルは冪等なので、再起動後の再実行が意図されたフローです。オフライン S3
  キャッシュがあれば、新しいアプリの初回実行は HF から再ダウンロードする代わりに S3 (高速、
  同一リージョン) からチェックポイントを復元します。
- 一度きりの初回実行コストは `uv sync` + キャッシュ復元 (~15-25 分) です。
