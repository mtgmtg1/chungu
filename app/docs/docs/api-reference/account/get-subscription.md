---
sidebar_position: 6
---

# GET /account/subscription

Returns the current user's subscription status, plan, monthly limit, and usage.

:::note
This endpoint accepts both API key (`X-API-Key` header) and JWT session token (`Authorization: Bearer` header).
:::

## Request

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account/subscription
```

## Response

```json
{
  "plan": "pro",
  "status": "active",
  "monthly_limit": 100000,
  "used": 5000
}
```

## Fields

| Field | Type | Description |
|-------|------|-------------|
| `plan` | string | Subscription plan: `free`, `pro`, or `max` |
| `status` | string | Subscription status (e.g. `active`, `canceled`, `past_due`) |
| `monthly_limit` | int | Monthly credit limit in milli-USD |
| `used` | int | Credits used this billing period in milli-USD |

## Errors

| Status | Meaning |
|--------|---------|
| 401 | Invalid or missing API key |
| 404 | User not found |
