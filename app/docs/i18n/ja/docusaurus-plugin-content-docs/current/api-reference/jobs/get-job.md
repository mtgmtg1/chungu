---
sidebar_position: 3
---

# GET /jobs/`{job_id}`

Get the current status and metadata of a job.

## Request

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/jobs/job-abc123
```

## Response

```json
{
  "job_id": "job-abc123",
  "status": "done",
  "pipeline": "vision",
  "file_type": "pdf",
  "filename": "document.pdf",
  "total_pages": 10,
  "done_pages": 10,
  "total_files": 1,
  "done_files": 1,
  "media_duration_seconds": 0,
  "cost_points": 30,
  "error_log": null,
  "created_at": "2026-06-27T12:00:00",
  "finished_at": "2026-06-27T12:01:30",
  "downloadable": true,
  "xlsx_converted": false
}
```

## Fields

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `pending`, `queued`, `processing`, `done`, `error`, `cancelled` |
| `done_pages` | int | Pages processed so far (for progress tracking) |
| `cost_points` | int | Points actually deducted |
| `downloadable` | bool | `true` when status is `done` |
| `xlsx_converted` | bool | Whether XLSX has been generated yet |
| `error_log` | string\|null | Error details if status is `error` |
