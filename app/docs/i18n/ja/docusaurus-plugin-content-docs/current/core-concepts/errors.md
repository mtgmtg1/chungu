---
sidebar_position: 6
---

# エラー処理

Chungu APIは標準HTTPステータスコードを使用します。エラーレスポンスには人が読めるメッセージを含む`detail`フィールドが含まれます。

## エラーコード

| ステータス | 意味 | アクション |
|--------|---------|--------|
| 400 | 不正なリクエスト — 無効なファイル形式、欠落フィールド | リクエスト形式を確認 |
| 401 | 無効または欠落APIキー | APIキーを確認 |
| 402 | ポイント不足 | `/payment`でポイントを追加購入 |
| 403 | 禁止 — スコープ欠落または開発者でない | キースコープを確認 |
| 404 | ジョブまたはリソースが見つからない | ジョブIDを確認 |
| 413 | ファイルが大きすぎるまたはページが多すぎる | ファイルサイズを減らすまたはPDFを分割 |
| 429 | レート制限超過 | `Retry-After`ヘッダー後に待機して再試行 |
| 502 | ダウンストリーム処理エラー | 指数バックオフで再試行 |

## エラーレスポンス形式

```json
{
  "detail": "포인트가 부족합니다"
}
```

:::note
エラーメッセージは韓国語の場合があります。プログラムによる処理にはHTTPステータスコードを使用してください。
:::

## 再試行戦略

`429`および`502`エラーの場合、指数バックオフを使用してください:

```python
import time
import requests

def retry_request(url, max_retries=3):
    for attempt in range(max_retries):
        resp = requests.get(url, headers=HEADERS)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 5))
            time.sleep(wait)
            continue
        if resp.status_code == 502 and attempt < max_retries - 1:
            time.sleep(2 ** attempt)
            continue
        return resp
    return resp
```

## ジョブエラー

ジョブが失敗した場合、`GET /jobs/{id}`は以下を返します:

```json
{
  "job_id": "job-abc123",
  "status": "error",
  "error_log": "LLM inference timeout after 120s"
}
```

一般的なジョブエラー:
- **LLM推論タイムアウト** — モデルが長時間かかった、再試行またはページ数を減らす
- **サポートされていないファイル形式** — [サポート形式](../file-formats)を確認
- **Storageアップロード失敗** — 一時的インフラエラー、再試行
