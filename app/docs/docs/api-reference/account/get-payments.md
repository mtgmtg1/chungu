---
sidebar_position: 5
---

# GET /account/payments

Returns payment history.

:::note
This endpoint accepts both API key (`X-API-Key` header) and JWT session token (`Authorization: Bearer` header).
:::

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
    "provider": "paddle",
    "currency": "USD",
    "amount": "10.00",
    "points_added": 10000,
    "status": "done",
    "external_id": "txn_abc123",
    "paid_at": "2026-07-14T15:00:00",
    "created_at": "2026-07-14T14:59:00"
  }
]
```
