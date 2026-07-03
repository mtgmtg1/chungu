---
sidebar_position: 7
---

# POST /jobs/`{job_id}`/action

Retry or refund a failed document parsing job. Only available when the job status is `error` and `refundable` is `true`.

## Request

```bash
curl -X POST https://your-domain.com/api/v1/jobs/job-abc123/action \
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
| `retry` | Resets job status to `queued`, re-dispatches to worker at no extra cost |
| `refund` | Refunds all credits deducted for this job back to your balance |

## Response (retry)

```json
{
  "job_id": "job-abc123",
  "status": "queued"
}
```

## Response (refund)

```json
{
  "refunded": true,
  "points": 50
}
```

:::info
`points` is the refunded amount in milli-USD. A value of `50` means $0.05 USD.
:::

## Errors

| Status | Meaning |
|--------|---------|
| 400 | Job is not in a refundable/retryable state, or invalid action |
| 404 | Job not found or doesn't belong to you |
