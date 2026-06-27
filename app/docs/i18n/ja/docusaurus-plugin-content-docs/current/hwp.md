# HWP/HWPX サポート (Phase 2)

## 概要

Chungu は、a1 バックエンドで pyhwp ベースの専用コンバータを使用して、Hangul Word Processor (`.hwp`) とその XML ベースの形式 (`.hwpx`) をサポートしています。これは Docling 前処理パイプラインの Phase 2 の一部です。

- **マークダウン抽出**: `pyhwp2md` がテキスト、段落、見出し、リスト、表をマークダウンに変換します。
- **画像抽出**: `pyhwp` が `BinData` OLE ストレージを読み込み、埋め込み画像を抽出します。
- **ページ数推定**: `hwp_converter.get_page_count()` が文書の要約情報を読み込み、ページ数を推定します。

## パイプラインの流れ

1. **アップロード**: `jobs.py` が `media_loader.HWP_TYPES` を通じて `.hwp` / `.hwpx` ファイルを検出します。
2. **ページ数**: アップロードされたファイルに対して `hwp_converter.get_page_count()` を呼び出します。
3. **ワーカールーティング**: `tasks.py` が単一ファイルまたはアーカイブ内のファイルに対して `run_hwp()` を呼び出します。
4. **処理**: `pipeline_docling.py` の `run_hwp()` が:
   - `pyhwp2md` でマークダウンを抽出します。
   - `pyhwp` で `BinData` 画像を抽出します。
   - 同じ Docling 設定を使用して、必要に応じて LLM レイアウト精製を実行します。
5. **結果**: 抽出されたマークダウンは、他の Docling 対応文書と同様に CSV/MD/XLSX 出力にマージされます。

## ファイルルーティング

- `media_loader.HWP_TYPES = {"hwp"}`
- 単一ファイル: `tasks.py` の `job.file_type in media_loader.HWP_TYPES` 分岐。
- 複数ファイル: アーカイブ展開ループ内の `ftype in media_loader.HWP_TYPES` 分岐。
- 抽出されたファイルは、PDF/Office 文書と同じパスロジックで Supabase Storage にアップロードされます。

## 精製（Refinement）

- `use_docling_refinement` / `docling_refinement` フラグは、HWP/HWPX 結果にも同様に適用されます。
- 料金は `settings_store` の `cost_per_docling_refinement_page_krw` / `cost_per_docling_refinement_page_usd` で設定します。

## API とフロントエンド

- `POST /api/jobs/upload` は `docling_refinement` フォームフィールドを受け入れます。
- `UploadPage.jsx` は Docling 互換文書（HWP/HWPX を含む）に対して「Docling レイアウト精製を使用」チェックボックスを表示します。
- サポートされるファイル拡張子には `.hwp` と `.hwpx` が含まれます。

## 主なファイル

- `app/backend/core/hwp_converter.py` — HWP/HWPX テキスト、画像、ページ抽出。
- `app/backend/core/pipeline_docling.py` — Docling と同じ精製パスを再利用する `run_hwp()` 関数。
- `app/backend/workers/tasks.py` — HWP/HWPX ファイルを `run_hwp()` にルーティング。
- `app/backend/api/jobs.py` — HWP/HWPX アップロードのページ数計算とコスト計算。
- `app/backend/core/media_loader.py` — `HWP_TYPES` とファイルタイプ検出。
