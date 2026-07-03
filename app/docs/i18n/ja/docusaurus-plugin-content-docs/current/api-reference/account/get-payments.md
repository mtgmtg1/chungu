---
sidebar_position: 5
---

# GET /account/payments

支払い履歴を返します。

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
  "https://your-domain.com/api/v1/account/payments"
```

## レスポンス

```json
[
  {
    "id": "pay-001",
    "provider": "paddle",
    "currency": "USD",
    "amount": "10.00",
    "points_added": 10000,
    "status": "done",
    "external_id": "paddle_pay_abc123",
    "paid_at": "2026-07-15T15:00:00",
    "created_at": "2026-07-15T14:59:00"
  }
]
```
