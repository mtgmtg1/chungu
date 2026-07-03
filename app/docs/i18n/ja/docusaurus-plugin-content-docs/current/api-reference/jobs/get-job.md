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
  "ocr_model": "premium",
  "ocr_engine": "easyocr",
  "file_type": "pdf",
  "filename": "document.pdf",
  "total_pages": 10,
  "done_pages": 10,
  "total_files": 1,
  "done_files": 1,
  "media_duration_seconds": 0,
  "cost_points": 50,
  "error_log": null,
  "created_at": "2026-07-15T12:00:00",
  "finished_at": "2026-07-15T12:01:30",
  "downloadable": true,
  "xlsx_basic_converted": false,
  "xlsx_advanced_converted": false,
  "xlsx_advanced_status": null,
  "xlsx_advanced_job_id": null,
  "xlsx_advanced_refundable": false,
  "xlsx_advanced_recovery_notes": null,
  "refundable": false,
  "retry_count": 0
}
```

## Fields

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `pending`, `queued`, `processing`, `done`, `error`, `cancelled` |
| `done_pages` | int | Pages processed so far (for progress tracking) |
| `cost_points` | int | Credits actually deducted (milli-USD) |
| `downloadable` | bool | `true` when status is `done` |
| `xlsx_basic_converted` | bool | Whether XLSX Basic has been generated |
| `xlsx_advanced_converted` | bool | Whether XLSX Advanced has been generated |
| `xlsx_advanced_status` | string\|null | Status of XLSX Advanced conversion |
| `xlsx_advanced_refundable` | bool | Whether XLSX Advanced conversion can be refunded |
| `refundable` | bool | Whether the job can be refunded (via `/action`) |
| `retry_count` | int | Number of times this job has been retried |
| `error_log` | string\|null | Error details if status is `error` |
