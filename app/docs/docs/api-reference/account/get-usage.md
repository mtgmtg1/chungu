---
sidebar_position: 3
---

# GET /account/usage

Returns daily aggregated API usage for the last N days.

:::note
This endpoint accepts both API key (`X-API-Key` header) and JWT session token (`Authorization: Bearer` header).
:::

## Query parameters

| Parameter | Type | Default | Range |
|-----------|------|---------|-------|
| `days` | int | 30 | 1–90 |

## Request

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  "https://your-domain.com/api/v1/account/usage?days=7"
```

## Response

```json
[
  { "day": "2026-07-10", "requests": 15, "points_spent": 450 },
  { "day": "2026-07-11", "requests": 8, "points_spent": 240 },
  { "day": "2026-07-12", "requests": 0, "points_spent": 0 }
]
```

:::info
`points_spent` is in milli-USD. A value of `450` means $0.45 USD spent that day.
:::
