---
sidebar_position: 4
---

# GET /account/transactions

クレジットチャージおよび消費履歴を返します。

:::note
このエンドポイントはAPIキー以外にウェブアプリログインのJWTセッショントークンもサポートしています。
:::

## クエリパラメータ

| パラメータ | タイプ | デフォルト | 範囲 |
|-----------|------|---------|-------|
| `limit` | int | 100 | 1–500 |

## リクエスト

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  "https://your-domain.com/api/v1/account/transactions?limit=20"
```

## レスポンス

```json
[
  {
    "id": "tx-001",
    "type": "spend",
    "amount": -30,
    "balance_after": 9970,
    "description": "APIジョブ: document.pdf",
    "created_at": "2026-06-27T10:30:00"
  },
  {
    "id": "tx-002",
    "type": "charge",
    "amount": 10000,
    "balance_after": 10000,
    "description": "Paddle決済: $10.00 USD",
    "created_at": "2026-07-15T15:00:00"
  }
]
```
