---
sidebar_position: 4
---

# GET /jobs

List your jobs, most recent first.

## Query parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 100 | Maximum number of jobs to return |

## Request

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  "https://your-domain.com/api/v1/jobs?limit=10"
```

## Response

```json
[
  {
    "job_id": "job-abc123",
    "status": "done",
    "pipeline": "vision",
    "file_type": "pdf",
    "filename": "document.pdf",
    "total_pages": 10,
    "done_pages": 10,
    "cost_points": 30,
    "downloadable": true,
    "created_at": "2026-06-27T12:00:00",
    "finished_at": "2026-06-27T12:01:30"
  }
]
```
