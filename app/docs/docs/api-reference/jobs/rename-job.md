---
sidebar_position: 9
---

# PATCH /jobs/`{job_id}`/title

Rename a job's display title. Available in any job state (`pending`, `processing`, `done`, `error`).

## Request

```bash
curl -X PATCH https://your-domain.com/api/v1/jobs/job-abc123/title \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{"title": "Q3 Financial Report"}'
```

## Body

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | New display title (1–200 characters) |

## Response

Same shape as [`GET /jobs/{job_id}`](./get-job). The `filename` field reflects the new title.

```json
{
  "job_id": "job-abc123",
  "status": "done",
  "filename": "Q3 Financial Report",
  "..."
}
```

## Errors

| Status | Meaning |
|--------|---------|
| 400 | Title is empty or exceeds 200 characters |
| 404 | Job not found or doesn't belong to you |
