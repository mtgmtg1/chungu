---
sidebar_position: 3
---

# Authentication

All API requests require an API key. You can pass it via the `X-API-Key` header or the `Authorization: Bearer` header.

## Using the X-API-Key header

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account
```

## Using Authorization Bearer

```bash
curl -H "Authorization: Bearer chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account
```

## Creating an API key

1. Log in to the Chungu web app
2. Go to **Developer Portal** (`/developer`)
3. Click **Create Key**
4. Enter a name (e.g., "production", "staging")
5. Copy the full key value — **it is only shown once**

You can also create keys via the API:

```bash
curl -X POST https://your-domain.com/api/v1/keys \
  -H "Authorization: Bearer <your-jwt-token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "production", "scopes": ["jobs:read", "jobs:write"]}'
```

:::caution
Store your API key securely. Never commit it to source control or expose it in client-side code.
:::

## API key scopes

| Scope | Description |
|-------|-------------|
| `jobs:read` | Read job status and list jobs |
| `jobs:write` | Upload, confirm, and convert jobs |

## Rate limits

- **Default**: 60 requests per minute per API key
- **Concurrent jobs**: up to 5 per account (admin-configurable)
- **Daily point quota**: optional per key

When exceeded, the API returns `429 Too Many Requests` with a `Retry-After` header.

## Managing API keys

- [List keys](./api-reference/api-keys/list-keys)
- [Delete a key](./api-reference/api-keys/delete-key)
- [Rotate a key](./api-reference/api-keys/rotate-key)
- [View key usage](./api-reference/api-keys/get-key-usage)
