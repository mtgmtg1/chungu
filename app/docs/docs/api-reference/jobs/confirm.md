---
sidebar_position: 2
---

# POST /jobs/`{job_id}`/confirm

Confirm a pending job, deduct points, and queue it for processing.

## Request

```bash
curl -X POST https://your-domain.com/api/v1/jobs/job-abc123/confirm \
  -H "X-API-Key: chu_live_xxxxxxxx"
```

## Response

```json
{
  "job_id": "job-abc123",
  "status": "queued",
  "remaining_points": 9970
}
```

## Errors

| Status | Meaning |
|--------|---------|
| 402 | Insufficient points — purchase more at `/payment` |
| 404 | Job not found or doesn't belong to you |
| 400 | Job is not in `pending` state (already confirmed or cancelled) |
