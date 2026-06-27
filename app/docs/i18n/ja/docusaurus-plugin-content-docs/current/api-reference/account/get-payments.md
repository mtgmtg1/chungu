---
sidebar_position: 5
---

# GET /account/payments

支払い履歴を返します。

## クエリパラメータ

| パラメータ | タイプ | デフォルト | 範囲 |
|-----------|------|---------|-------|
| `limit` | int | 100 | 1–500 |

## リクエスト

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  "https://your-domain.com/api/v1/account/payments"
```

## レスポンス

```json
[
  {
    "id": "pay-001",
    "provider": "toss",
    "currency": "KRW",
    "amount": "33000",
    "points_added": 10000,
    "status": "done",
    "external_id": "toss_payment_abc123",
    "paid_at": "2026-06-26T15:00:00",
    "created_at": "2026-06-26T14:59:00"
  }
]
```
