---
sidebar_position: 3
---

# DELETE /keys/`{key_id}`

Delete an API key permanently.

## Request

:::note
This endpoint uses JWT authentication (your login token), not an API key.
:::

```bash
curl -X DELETE https://your-domain.com/api/v1/keys/key-abc123 \
  -H "Authorization: Bearer <your-jwt-token>"
```

## Response

```json
{ "ok": true }
```

## Errors

| Status | Meaning |
|--------|---------|
| 404 | Key not found or doesn't belong to you |
