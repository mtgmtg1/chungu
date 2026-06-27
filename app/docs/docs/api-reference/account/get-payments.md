---
sidebar_position: 5
---

# GET /account/payments

Returns payment history.

## Query parameters

| Parameter | Type | Default | Range |
|-----------|------|---------|-------|
| `limit` | int | 100 | 1–500 |

## Request

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  "https://your-domain.com/api/v1/account/payments"
```

## Response

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
