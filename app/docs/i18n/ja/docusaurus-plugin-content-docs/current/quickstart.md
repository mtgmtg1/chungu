---
sidebar_position: 2
---

# クイックスタート

5分で最初のAPI呼び出しを行いましょう。

## 前提条件

- Chunguアカウント（ウェブアプリで登録）
- APIキー（[開発者ポータル](../../developer)で作成）
- `curl`またはHTTPクライアント

## ステップ1：APIキーを取得

1. Chunguウェブアプリにログインします
2. **開発者ポータル**（`/developer`）に移動します
3. **キー作成**をクリックします
4. 完全なキーをコピーします — 一度のみ表示されます

## ステップ2：アカウントを確認

キーが機能することを確認し、ポイント残高を確認します:

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account
```

**レスポンス:**
```json
{
  "user_id": "uuid",
  "email": "user@example.com",
  "points_balance": 10000,
  "today_usage": { "points_spent": 0, "requests": 0 }
}
```

## ステップ3：ファイルをアップロード

PDFをアップロードし、コストプレビューを取得します（まだポイントは消費されません）:

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "pipeline=vision"
```

**レスポンス:**
```json
{
  "job_id": "job-abc123",
  "status": "pending",
  "file_type": "pdf",
  "total_pages": 10,
  "cost": { "pages": 10, "points": 30, "krw": 30, "usd": "0.02" },
  "balance": 10000
}
```

## ステップ4：ジョブを確認

確認するとポイントが差し引かれ、処理が開始されます:

```bash
curl -X POST https://your-domain.com/api/v1/jobs/job-abc123/confirm \
  -H "X-API-Key: chu_live_xxxxxxxx"
```

**レスポンス:**
```json
{
  "job_id": "job-abc123",
  "status": "queued",
  "remaining_points": 9970
}
```

## ステップ5：完了をポーリング

ステータスが`done`になるまで確認します:

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/jobs/job-abc123
```

**レスポンス（完了時）:**
```json
{
  "job_id": "job-abc123",
  "status": "done",
  "total_pages": 10,
  "done_pages": 10,
  "cost_points": 30,
  "downloadable": true
}
```

## ステップ6：結果をダウンロード

結果ファイルをダウンロードするための署名付きURLを取得します:

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  "https://your-domain.com/api/v1/jobs/job-abc123/download?type=xlsx"
```

**レスポンス:**
```json
{
  "download_url": "https://supabase-storage.example.com/results/job-abc123/result.xlsx?token=..."
}
```

## Python例

```python
import requests

API_KEY = "chu_live_xxxxxxxx"
BASE = "https://your-domain.com/api/v1"
HEADERS = {"X-API-Key": API_KEY}

# アップロード
with open("document.pdf", "rb") as f:
    resp = requests.post(f"{BASE}/jobs/upload", headers=HEADERS,
                         files={"files": f}, data={"pipeline": "vision"})
job_id = resp.json()["job_id"]

# 確認
requests.post(f"{BASE}/jobs/{job_id}/confirm", headers=HEADERS)

# ポーリング
import time
while True:
    status = requests.get(f"{BASE}/jobs/{job_id}", headers=HEADERS).json()
    if status["status"] in ("done", "error"):
        break
    time.sleep(5)

# ダウンロード
url = requests.get(f"{BASE}/jobs/{job_id}/download?type=csv",
                   headers=HEADERS).json()["download_url"]
print(f"ダウンロード: {url}")
```

## 次のステップ

- [認証](./authentication) — APIキー管理の詳細
- [コア概念](./core-concepts/job-lifecycle) — ジョブライフサイクルを理解
- [AIプロンプト](./ai-prompts/full-pipeline-prompt) — AIにAPIを自動呼び出させる
