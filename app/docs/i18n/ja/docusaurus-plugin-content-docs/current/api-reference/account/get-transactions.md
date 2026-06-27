---
sidebar_position: 4
---

# GET /account/transactions

ポイントチャージおよび消費履歴を返します。

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
    "description": "Toss決済: Starterパッケージ",
    "created_at": "2026-06-26T15:00:00"
  }
]
```
