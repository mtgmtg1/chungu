---
sidebar_position: 3
---

# GET /account/usage

Returns daily aggregated API usage for the last N days.

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
  { "day": "2026-06-20", "requests": 15, "points_spent": 450 },
  { "day": "2026-06-21", "requests": 8, "points_spent": 240 },
  { "day": "2026-06-22", "requests": 0, "points_spent": 0 }
]
```
