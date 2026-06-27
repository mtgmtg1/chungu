---
sidebar_position: 4
---

# GET /account/transactions

Returns point charge and spend history.

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
    "amount": -30,
    "balance_after": 9970,
    "description": "API 작업: document.pdf",
    "created_at": "2026-06-27T10:30:00"
  },
  {
    "id": "tx-002",
    "type": "charge",
    "amount": 10000,
    "balance_after": 10000,
    "description": "Toss 결제: Starter 패키지",
    "created_at": "2026-06-26T15:00:00"
  }
]
```
