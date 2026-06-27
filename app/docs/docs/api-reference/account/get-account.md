---
sidebar_position: 1
---

# GET /account

Returns account info, point balance, today's usage, and current API key metadata.

## Request

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account
```

## Response

```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "points_balance": 10000,
  "api_key": {
    "id": "key-id",
    "name": "production",
    "prefix": "chu_live",
    "scopes": ["jobs:read", "jobs:write"],
    "rate_limit_rpm": 60,
    "daily_quota": null,
    "daily_spent_points": 150
  },
  "today_usage": {
    "points_spent": 150,
    "requests": 12
  }
}
```

## Fields

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | string (uuid) | User identifier |
| `email` | string | User email |
| `points_balance` | int | Current point balance |
| `api_key` | object | Current API key metadata |
| `api_key.scopes` | string[] | Key permissions |
| `api_key.rate_limit_rpm` | int | Requests per minute limit |
| `api_key.daily_quota` | int\|null | Daily point cap (null = unlimited) |
| `api_key.daily_spent_points` | int | Points spent today |
| `today_usage.points_spent` | int | Points spent today |
| `today_usage.requests` | int | Number of API calls today |
