---
sidebar_position: 7
---

# POST /jobs/`{job_id}`/action

失敗したドキュメント解析ジョブをリトライまたは返金します。ジョブステータスが`error`で`refundable`が`true`の場合のみ利用可能です。

## リクエスト

```bash
curl -X POST https://your-domain.com/api/v1/jobs/job-abc123/action \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{"action": "retry"}'
```

## Body

| Field | Type | Description |
|-------|------|-------------|
| `action` | string | `retry` or `refund` |

## Actions

| Action | 動作 |
|--------|---------|
| `retry` | ジョブステータスを`queued`にリセットし、追加コストなしでワーカーに再ディスパッチ |
| `refund` | このジョブで差し引かれた全クレジットを残高に返金 |

## レスポンス (retry)

```json
{
  "job_id": "job-abc123",
  "status": "queued"
}
```

## レスポンス (refund)

```json
{
  "refunded": true,
  "points": 50
}
```

:::info
`points`は返金されたクレジット額（milli-USD）です。`50`は$0.05 USDを意味します。
:::

## エラー

| Status | Meaning |
|--------|---------|
| 400 | 返金/リトライ可能な状態でない、または無効なaction |
| 404 | ジョブが見つからない、または所有者でない |
