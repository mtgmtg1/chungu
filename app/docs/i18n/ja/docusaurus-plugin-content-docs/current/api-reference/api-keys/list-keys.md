---
sidebar_position: 2
---

# GET /keys

List all your API keys (without full key values).

## Request

:::note
This endpoint uses JWT authentication (your login token), not an API key.
:::

```bash
curl -H "Authorization: Bearer <your-jwt-token>" \
  https://your-domain.com/api/v1/keys
```

## Response

```json
[
  {
    "id": "key-abc123",
    "name": "production",
    "prefix": "chu_live",
    "scopes": ["jobs:read", "jobs:write"],
    "rate_limit_rpm": 60,
    "daily_quota": null,
    "is_active": true,
    "last_used_at": "2026-06-27T11:30:00",
    "expires_at": null,
    "created_at": "2026-06-20T10:00:00"
  }
]
```
