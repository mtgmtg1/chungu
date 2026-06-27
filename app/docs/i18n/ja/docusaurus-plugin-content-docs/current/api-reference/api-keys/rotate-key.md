---
sidebar_position: 4
---

# POST /keys/`{key_id}`/rotate

Deactivate the old key and issue a new one with the same settings. The new full key value is returned once.

## Request

:::note
This endpoint uses JWT authentication (your login token), not an API key.
:::

```bash
curl -X POST https://your-domain.com/api/v1/keys/key-abc123/rotate \
  -H "Authorization: Bearer <your-jwt-token>"
```

## Response

```json
{
  "id": "key-def456",
  "name": "production",
  "prefix": "chu_live",
  "key": "chu_live_yyyyyyyyyyyyyyyyyyyyyyyy",
  "scopes": ["jobs:read", "jobs:write"],
  "rate_limit_rpm": 60
}
```

:::warning
The old key is immediately deactivated. Update your applications to use the new key right away.
:::
