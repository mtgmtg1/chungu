---
sidebar_position: 1
---

# POST /keys

Create a new API key. The full key value is only returned in this response.

## Request

:::note
This endpoint uses JWT authentication (your login token), not an API key.
:::

```bash
curl -X POST https://your-domain.com/api/v1/keys \
  -H "Authorization: Bearer <your-jwt-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "production",
    "scopes": ["jobs:read", "jobs:write"],
    "rate_limit_rpm": 60
  }'
```

## Body

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | `""` | Display name for the key |
| `scopes` | string[] | `["jobs:read", "jobs:write"]` | Key permissions |
| `rate_limit_rpm` | int | 60 | Requests per minute limit |

## Response

```json
{
  "id": "key-abc123",
  "name": "production",
  "prefix": "chu_live",
  "key": "chu_live_xxxxxxxxxxxxxxxxxxxxxxxx",
  "scopes": ["jobs:read", "jobs:write"],
  "rate_limit_rpm": 60,
  "daily_quota": null,
  "is_active": true,
  "created_at": "2026-06-27T12:00:00"
}
```

:::warning
The `key` field is only shown once. Store it securely — there is no way to retrieve it later.
:::
