---
sidebar_position: 8
---

# POST /jobs/`{job_id}`/xlsx-advanced-action

Retry or refund a failed XLSX Advanced conversion. Only available when `xlsx_advanced_status` is `error` and `xlsx_advanced_refundable` is `true`.

## Request

```bash
curl -X POST https://your-domain.com/api/v1/jobs/job-abc123/xlsx-advanced-action \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{"action": "retry"}'
```

## Body

| Field | Type | Description |
|-------|------|-------------|
| `action` | string | `retry` or `refund` |

## Actions

| Action | Behavior |
|--------|---------|
| `retry` | Resets XLSX Advanced status to `processing`, re-dispatches conversion at no extra cost |
| `refund` | Refunds credits deducted for the XLSX Advanced conversion (3 milli-USD per unit) |

## Response (retry)

```json
{
  "job_id": "task-xyz789",
  "status": "processing"
}
```

## Response (refund)

```json
{
  "refunded": true,
  "points": 30
}
```

:::info
`points` is the refunded amount in milli-USD. A value of `30` means $0.03 USD (10 units × 3 md/unit).
:::

## Errors

| Status | Meaning |
|--------|---------|
| 400 | XLSX Advanced conversion is not in a refundable/retryable state, or invalid action |
| 404 | Job not found or doesn't belong to you |
