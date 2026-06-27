---
sidebar_position: 1
---

# ジョブライフサイクル

すべてのChunguジョブは、アップロードからダウンロードまで明確なライフサイクルに従います。

## ステータス

| ステータス | 説明 |
|--------|-------------|
| `pending` | ファイルがアップロード済み、確認待ち |
| `queued` | 確認済み、ワーカーの取得待ち |
| `processing` | ワーカーがアクティブに処理中 |
| `done` | 処理完了、結果ダウンロード可能 |
| `error` | 処理失敗、`error_log`を確認 |
| `cancelled` | 完了前にキャンセルされた |

## フロー

```
アップロード → pending → 確認 → queued → processing → done
                                              ↘ error
```

1. **アップロード** (`POST /jobs/upload`) — `pending`状態でジョブ作成、コストプレビュー返却
2. **確認** (`POST /jobs/{id}/confirm`) — ポイント差し引き、`queued`に移行、Celeryワーカーにディスパッチ
3. **処理** — ワーカーがページ/ファイルを処理、リアルタイムで`done_pages` / `done_files`を更新
4. **完了** — 結果がSupabase Storageに保存、ダウンロード準備完了
5. **ダウンロード** (`GET /jobs/{id}/download`) — 1時間有効な署名付きURL返却

## ポーリング戦略

`GET /jobs/{id}`を3〜5秒間隔でポーリングします。レスポンスに`done_pages`と`total_pages`が含まれているため、進捗を表示できます。

```python
import time

while True:
    job = get_job(job_id)
    if job["status"] in ("done", "error"):
        break
    print(f"進捗: {job['done_pages']}/{job['total_pages']}")
    time.sleep(3)
```

## エラー処理

`status`が`error`の場合、`error_log`フィールドに詳細が含まれます。一般的な原因:

- サポートされていないファイル形式
- 破損したPDFまたはメディアファイル
- LLM推論タイムアウト
- ポイント不足（確認ステップで検出）
