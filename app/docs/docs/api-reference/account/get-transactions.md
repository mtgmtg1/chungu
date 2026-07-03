---
sidebar_position: 4
---

# GET /account/transactions

Returns credit charge and spend history.

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
  "https://your-domain.com/api/v1/account/transactions?limit=20"
```

## Response

```json
[
  {
    "id": "tx-001",
    "type": "spend",
    "amount": -50,
    "balance_after": 9950,
    "description": "API job: document.pdf",
    "created_at": "2026-07-15T10:30:00"
  },
  {
    "id": "tx-002",
    "type": "charge",
    "amount": 10000,
    "balance_after": 10000,
    "description": "Paddle payment: $10.00 USD",
    "created_at": "2026-07-14T15:00:00"
  }
]
```
