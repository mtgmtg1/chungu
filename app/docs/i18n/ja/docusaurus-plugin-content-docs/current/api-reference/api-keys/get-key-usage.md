---
sidebar_position: 5
---

# GET /keys/`{key_id}`/usage

Returns usage history for a specific API key.

## Request

:::note
This endpoint uses JWT authentication (your login token), not an API key.
:::

```bash
curl -H "Authorization: Bearer <your-jwt-token>" \
  "https://your-domain.com/api/v1/keys/key-abc123/usage?limit=50"
```

## Query parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 100 | Max records to return |

## Response

```json
[
  {
    "id": "usage-001",
    "endpoint": "/api/v1/jobs/upload",
    "job_id": "job-abc123",
    "points_spent": 0,
    "http_status": 200,
    "client_ip": "203.0.113.50",
    "created_at": "2026-06-27T12:00:00"
  }
]
```
