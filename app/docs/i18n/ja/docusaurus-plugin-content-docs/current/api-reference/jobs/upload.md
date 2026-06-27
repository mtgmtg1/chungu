---
sidebar_position: 1
---

# POST /jobs/upload

Upload files and get a cost preview. Points are **not** deducted at this step.

## Form fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `files` | File[] | Yes | — | One or more files (multipart/form-data) |
| `pipeline` | string | No | `vision` | `vision` or `hybrid` |
| `columns` | string | No | defaults | Comma-separated or JSON array of column names |
| `prompt` | string | No | `""` | Extra instructions for the model |
| `dpi` | int | No | 300 | PDF rendering DPI |
| `relative_paths` | string | No | `""` | JSON array of relative paths for archive files |

## Request

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "pipeline=vision" \
  -F "columns=날짜,계정과목,적요,입금액,출금액,잔액" \
  -F "dpi=300"
```

## Response

```json
{
  "job_id": "job-abc123",
  "status": "pending",
  "file_type": "pdf",
  "total_pages": 10,
  "total_files": 1,
  "media_duration_seconds": 0,
  "cost": {
    "pages": 10,
    "points": 30,
    "krw": 30,
    "usd": "0.02"
  },
  "balance": 10000
}
```

## Fields

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | string | Job identifier — use for confirm/status/download |
| `status` | string | Always `pending` at this stage |
| `file_type` | string | `pdf`, `image`, `audio`, `video`, `archive`, `mixed` |
| `total_pages` | int | Total PDF pages detected |
| `total_files` | int | Total files (after archive extraction) |
| `media_duration_seconds` | int | Total audio/video duration |
| `cost.points` | int | Points that will be deducted on confirm |
| `balance` | int | Current point balance (before deduction) |

## Multiple files

Upload multiple files at once:

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@doc1.pdf" \
  -F "files=@doc2.pdf" \
  -F "pipeline=vision"
```

## Errors

| Status | Meaning |
|--------|---------|
| 400 | No files, unsupported format, or missing filename |
| 413 | Total file size exceeds limit (default 200MB) or pages exceed limit (default 2000) |
| 502 | File processing failed |
