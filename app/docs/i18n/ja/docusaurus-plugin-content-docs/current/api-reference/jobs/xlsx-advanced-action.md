---
sidebar_position: 8
---

# POST /jobs/`{job_id}`/xlsx-advanced-action

失敗したXLSX高度変換をリトライまたは返金します。`xlsx_advanced_status`が`error`で`xlsx_advanced_refundable`が`true`の場合のみ利用可能です。

## リクエスト

```bash
curl -X POST https://your-domain.com/api/v1/jobs/job-abc123/xlsx-advanced-action \
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
| `retry` | XLSX高度変換ステータスを`processing`にリセットし、追加コストなしで再ディスパッチ |
| `refund` | XLSX高度変換で差し引かれたクレジットを返金（単位あたり3 milli-USD） |

## レスポンス (retry)

```json
{
  "job_id": "task-xyz789",
  "status": "processing"
}
```

## レスポンス (refund)

```json
{
  "refunded": true,
  "points": 30
}
```

:::info
`points`は返金されたクレジット額（milli-USD）です。`30`は$0.03 USDを意味します（10単位 × 3 md/単位）。
:::

## エラー

| Status | Meaning |
|--------|---------|
| 400 | XLSX高度変換が返金/リトライ可能な状態でない、または無効なaction |
| 404 | ジョブが見つからない、または所有者でない |
