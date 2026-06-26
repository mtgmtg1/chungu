# Chungu API v1 ドキュメント

Chungu API v1 は、外部開発者が PDF/画像/音声/動画をアップロードし、前払いポイント制で構造化テーブル（CSV/MD/XLSX）を抽出できるようにします。

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
- 日次ポイントクォータ: キーごとに任意。

超過時、API は `Retry-After` ヘッダー付きで `429 Too Many Requests` を返します。

## 価格

入力タイプに基づいてポイントが差し引かれます。

| 入力 | コスト |
|-------|------|
| PDF ページ | 3P |
| 画像 | 3P |
| 音声 1 秒 | 1P |
| 動画 1 秒 | 3P |

現在の価格とパッケージは `GET /api/v1/account/pricing` で確認できます。

## コアフロー

1. **ファイルアップロード** → `POST /jobs/upload` は `job_id` とコストプレビューを返します。
2. **ジョブ確認** → `POST /jobs/{job_id}/confirm` はポイントを差し引いて処理をキューに入れます。
3. **状態ポーリング** → `GET /jobs/{job_id}` で `status` が `done` または `error` になるまで確認します。
4. **結果ダウンロード** → `GET /jobs/{job_id}/download?type=csv|md|xlsx` は署名付き URL を返します。

## エンドポイント

### アカウント

#### `GET /account`

アカウント情報、ポイント残高、今日の使用量、現在の API キーのメタデータを返します。

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

ポイントパッケージと単位あたりのレートを返します。

#### `GET /account/transactions`

ポイントのチャージ/使用履歴を返します。

#### `GET /account/usage?days=30`

日次の集計使用状況を返します。

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

### ジョブ

#### `POST /jobs/upload`

ファイルをアップロードし、コストプレビューを取得します。

**フォームフィールド:**
- `files`: 1 つ以上のファイル（multipart/form-data）
- `pipeline`: `"vision"`（デフォルト）または `"hybrid"`
- `columns`: カンマ区切りの列名または JSON 配列（任意）
- `prompt`: モデルへの追加指示（任意）
- `dpi`: PDF レンダリング DPI、デフォルト 150

**レスポンス:**
```json
{
  "job_id": "job-id",
  "status": "pending",
  "file_type": "pdf",
  "total_pages": 10,
  "total_files": 1,
  "media_duration_seconds": 0,
  "cost": { "pages": 10, "points": 30, "krw": 30, "usd": "0.02" },
  "balance": 9970
}
```

#### `POST /jobs/{job_id}/confirm`

ジョブを確認し、ポイントを差し引いて処理を開始します。

**レスポンス:**
```json
{
  "job_id": "job-id",
  "status": "queued",
  "remaining_points": 9940
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
  "cost_points": 30,
  "downloadable": true,
  "created_at": "2026-06-26T00:00:00",
  "finished_at": "2026-06-26T00:01:00"
}
```

#### `GET /jobs`

ジョブの一覧を取得します。`limit` クエリパラメータをサポートします。

#### `GET /jobs/{job_id}/download?type=xlsx`

結果ファイルの署名付き Supabase Storage URL を返します。

**サポートされるタイプ:** `csv`、`md`、`xlsx`。

**レスポンス:**
```json
{ "download_url": "https://..." }
```

## エラーコード

| ステータス | 意味 |
|--------|---------|
| 400 | 不正なリクエスト（無効なファイルタイプ、不足フィールド） |
| 401 | 無効または未設定の API キー |
| 402 | ポイント不足 |
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
  -d '{"url":"https://your-app.com/webhooks/chungu","events":["job.done","job.error"]}'
```

## OpenAPI / Swagger

対話型ドキュメントは以下で確認できます。

```
/api/v1/docs
```
