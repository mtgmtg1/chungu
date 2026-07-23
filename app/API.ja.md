# PROOF API v1 ドキュメント

PROOF API v1 は、外部開発者が PDF/画像/音声/動画/Markdown をアップロードし、前払いクレジット制で構造化テーブル（CSV/MD/XLSX）を抽出できるようにします。クレジットは **milli-USD** 単位です（1,000 milli-USD = $1.00 USD）。

## ベース URL

すべての API エンドポイントには `/api/v1` 接頭辞が付きます。

```
https://your-domain.com/api/v1
```

## 認証

API キーを `X-API-Key` ヘッダー（または `Authorization: Bearer <key>`）で送信して認証します。

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" https://your-domain.com/api/v1/account
```

API キーは、ログイン後の `/developer` の **開発者ポータル**で作成できます。

## レート制限

- デフォルト: API キーあたり分間 60 リクエスト。
- 同時ジョブ: アカウントあたり最大 5 つ（管理者が設定可能）。
- 日次クレジットクォータ: キーごとに任意。

超過時、API は `Retry-After` ヘッダー付きで `429 Too Many Requests` を返します。

## 価格

入力タイプと選択したモデルに基づいてクレジットが差し引かれます。すべての金額は milli-USD 単位です。

| 入力 | Basic モデル | Premium モデル |
|-------|-------------|---------------|
| PDF ページ | 1 md ($0.001) | 5 md ($0.005) |
| Office/HWP ページ | 1 md ($0.001) | 5 md ($0.005) |
| 画像 | 1 md ($0.001) | 5 md ($0.005) |
| 音声（秒あたり） | — | 1 md ($0.001) |
| 動画（秒あたり） | — | 5 md ($0.005) |
| Markdown（`.md`） | 無料 (0 md) | 無料 (0 md) |
| Docling 精製（ページあたり） | — | 3 md ($0.003) |

:::info
**Basic モデル**: 1 日 100 ページ無料。無料枠を超えると 1 md/ページが課金されます。
**Premium モデル**: 無料枠なし。すべてのページに 5 md/ページが課金されます。
:::

Markdown ファイルは無料で処理されます — テキストコンテンツがそのまま結果として使用されます。

現在のレートは `GET /api/v1/account/pricing` で確認できます。

## サポートされる入力形式

- **PDF**: PDF
- **Office**: DOCX, DOC, PPTX, PPT, XLSX, XLS（Docling 前処理パイプライン経由）
- **HWP**: HWP, HWPX（韓国語ワープロ、pyhwp で変換）
- **画像**: PNG, JPG, JPEG, GIF, BMP, WEBP, TIFF
- **音声**: MP3, WAV, FLAC, AAC, OGG, M4A, WMA
- **動画**: MP4, AVI, MOV, MKV, WEBM, FLV, WMV, M4V
- **Markdown**: MD（テキストコンテンツが結果として直接使用され、OCR/LLM 処理なし）
- **圧縮ファイル**: ZIP, RAR, 7Z, TAR, GZ, TGZ, BZ2

PDF、Office、HWP/HWPX ファイルは Docling 前処理パイプラインを経由して処理されます。Office/HWP のページ数は Docling/pyhwp で推定されます（推定失敗時はデフォルト 1 ページ）。

## コアフロー

1. **ファイルアップロード** → `POST /jobs/upload` は `job_id` とコストプレビューを返します。
2. **ジョブ確認** → `POST /jobs/{job_id}/confirm` はクレジットを差し引いて処理をキューに入れます。
3. **状態ポーリング** → `GET /jobs/{job_id}` で `status` が `done` または `error` になるまで確認します。
4. **結果ダウンロード** → `GET /jobs/{job_id}/download?type=csv_basic|md|xlsx_basic` は署名付き URL を返します。

## エンドポイント

### アカウント

#### `GET /account`

アカウント情報、クレジット残高、今日の使用量、現在の API キーのメタデータを返します。

**レスポンス:**
```json
{
  "user_id": "uuid",
  "email": "user@example.com",
  "points_balance": 10000,
  "api_key": { "id": "...", "name": "...", "scopes": ["jobs:read", "jobs:write"] },
  "today_usage": { "points_spent": 150, "requests": 12 }
}
```

#### `GET /account/pricing`

現在のクレジットレート（milli-USD）とチャージ限度を返します。

#### `GET /account/transactions`

クレジットのチャージ/使用履歴を返します。

#### `GET /account/usage?days=30`

日次の集計使用状況を返します。

#### `GET /account/payments`

支払い履歴を返します。

#### `GET /account/subscription`

現在のサブスクリプション状態、プラン、月次限度、使用量を返します。

**レスポンス:**
```json
{
  "plan": "pro",
  "status": "active",
  "monthly_limit": 100000,
  "used": 5000
}
```

### API キー

#### `POST /keys`

新しい API キーを作成します。

**リクエスト:**
```json
{ "name": "production", "scopes": ["jobs:read", "jobs:write"] }
```

**レスポンス:**
```json
{
  "id": "key-id",
  "name": "production",
  "prefix": "chu_live",
  "key": "chu_live_...",
  "scopes": ["jobs:read", "jobs:write"],
  "rate_limit_rpm": 60
}
```

完全な `key` は一度だけ返されます。

#### `GET /keys`

API キーの一覧を取得します（完全なキー値は除く）。

#### `DELETE /keys/{id}`

API キーを無効化します。

#### `POST /keys/{id}/rotate`

API キーをローテーションします（新しいキー値を生成し、古いキーを無効化します）。

#### `GET /keys/{id}/usage`

特定の API キーの使用統計を返します。

### ジョブ

#### `POST /jobs/upload`

ファイルをアップロードし、コストプレビューを取得します。このステップではクレジットは差し引かれ**ません**。

**フォームフィールド:**
- `files`: 1 つ以上のファイル（multipart/form-data）
- `pipeline`: `"vision"`（デフォルト）または `"hybrid"`
- `columns`: カンマ区切りの列名または JSON 配列（任意）
- `prompt`: モデルへの追加指示（任意）
- `dpi`: PDF レンダリング DPI、デフォルト **300**
- `ocr_model`: `"basic"` または `"premium"`（デフォルト `"premium"`）
- `ocr_engine`: `"tesseract"`、`"easyocr"`（デフォルト）、または `"rapidocr"`（premium のみ）
- `relative_paths`: アーカイブ内の相対パス JSON 配列（任意）
- `docling_refinement`: `true` または `false`（デフォルト）。PDF/Office/HWP 文書に対して LLM レイアウト精製を有効にします（3 md/ページ）。

**レスポンス:**
```json
{
  "job_id": "job-id",
  "status": "pending",
  "file_type": "pdf",
  "total_pages": 10,
  "total_files": 1,
  "media_duration_seconds": 0,
  "docling_refinement": false,
  "docling_refinement_pages": 0,
  "ocr_model": "premium",
  "ocr_engine": "easyocr",
  "has_media": false,
  "cost": { "pages": 10, "points": 50, "usd": "$0.05" },
  "balance": 10000
}
```

#### `POST /jobs/{job_id}/confirm`

ジョブを確認し、クレジットを差し引いて処理を開始します。

**レスポンス:**
```json
{
  "job_id": "job-id",
  "status": "queued",
  "remaining_points": 9950
}
```

#### `GET /jobs/{job_id}`

ジョブの状態とメタデータを取得します。

**レスポンス:**
```json
{
  "job_id": "job-id",
  "status": "done",
  "pipeline": "vision",
  "file_type": "pdf",
  "filename": "document.pdf",
  "total_pages": 10,
  "done_pages": 10,
  "total_files": 1,
  "done_files": 1,
  "media_duration_seconds": 0,
  "ocr_model": "premium",
  "ocr_engine": "easyocr",
  "cost_points": 50,
  "error_log": null,
  "downloadable": true,
  "xlsx_converted": false,
  "xlsx_basic_converted": false,
  "xlsx_advanced_converted": false,
  "xlsx_advanced_status": null,
  "xlsx_advanced_job_id": null,
  "xlsx_advanced_refundable": false,
  "xlsx_advanced_recovery_notes": null,
  "refundable": false,
  "retry_count": 0,
  "created_at": "2026-07-23T00:00:00",
  "finished_at": "2026-07-23T00:01:00"
}
```

#### `GET /jobs`

ジョブの一覧を取得します。`limit` クエリパラメータをサポートします（デフォルト 100）。

#### `PATCH /jobs/{job_id}/title`

ジョブの表示タイトルを変更します。どの状態でも利用可能です。

**リクエスト:**
```json
{ "title": "新しいタイトル" }
```

**レスポンス:** `GET /jobs/{job_id}` と同じ形式。`filename` フィールドに新しいタイトルが反映されます。

**エラー:**

| ステータス | 意味 |
|--------|---------|
| 400 | タイトルが空または 200 文字を超えている |
| 404 | ジョブが見つからない、または所有者でない |

#### `GET /jobs/{job_id}/download?type=xlsx_basic`

結果ファイルの署名付き Supabase Storage URL を返します。

**サポートされるタイプ:** `csv_basic`、`md`、`xlsx_basic`、`xlsx_advanced`、`docx`、`pptx`。

**レスポンス:**
```json
{ "download_url": "https://..." }
```

:::info
署名付き URL は **1 時間**有効です。`xlsx_basic`/`csv_basic` の場合、初回ダウンロード時に自動変換されます（1 md/単位、初回のみ）。
:::

#### `POST /jobs/{job_id}/convert`

完了したジョブの Markdown 結果を Office 形式に変換します。

**リクエスト:**
```json
{ "format": "xlsx_basic" }
```

**サポートされる形式:** `xlsx_basic`、`csv_basic`、`xlsx_advanced`、`docx`、`pptx`。

| 形式 | コスト |
|--------|------|
| `xlsx_basic` / `csv_basic` | 1 md/単位、初回のみ |
| `xlsx_advanced` | 3 md/単位、初回のみ |
| `docx` / `pptx` | 無料 |

#### `POST /jobs/{job_id}/action`

失敗した文書解析ジョブをリトライまたは返金します。`status` が `error` で `refundable` が `true` の場合のみ利用可能です。

**リクエスト:**
```json
{ "action": "retry" }
```

**アクション:** `retry`（追加コストなしで再実行）または `refund`（全クレジット返金）。

#### `POST /jobs/{job_id}/xlsx-advanced-action`

失敗した XLSX Advanced 変換をリトライまたは返金します。`xlsx_advanced_status` が `error` で `xlsx_advanced_refundable` が `true` の場合のみ利用可能です。

**リクエスト:**
```json
{ "action": "retry" }
```

## エラーコード

| ステータス | 意味 |
|--------|---------|
| 400 | 不正なリクエスト（無効なファイルタイプ、不足フィールド） |
| 401 | 無効または未設定の API キー |
| 402 | クレジット不足 |
| 403 | 禁止（不足しているスコープ） |
| 413 | ファイルが大きすぎるかページが多すぎる |
| 429 | レート制限超過 |
| 502 | ダウンストリーム処理エラー |

## Webhooks（予定）

ジョブ完了イベントを受け取るコールバック URL を登録します。

```bash
curl -X POST /api/v1/webhooks \
  -H "X-API-Key: <key>" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://your-app.com/webhooks/proof","events":["job.done","job.error"]}'
```

## OpenAPI / Swagger

対話型ドキュメントは以下で確認できます。

```
/api/v1/docs
```
