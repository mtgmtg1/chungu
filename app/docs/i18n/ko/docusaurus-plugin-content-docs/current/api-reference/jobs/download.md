---
sidebar_position: 5
---

# GET /jobs/`{job_id}`/download

Returns a signed Supabase Storage URL for downloading the result file.

## Query parameters

| Parameter | Type | Default | Options |
|-----------|------|---------|---------|
| `type` | string | `xlsx_basic` | `csv_basic`, `md`, `xlsx_basic`, `xlsx_advanced`, `docx`, `pptx` |

## Request

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  "https://your-domain.com/api/v1/jobs/job-abc123/download?type=xlsx_basic"
```

## Response

```json
{
  "download_url": "https://supabase-storage.example.com/results/job-abc123/result.xlsx?token=..."
}
```

:::info
The signed URL is valid for **1 hour**. Request a new URL if it expires.
:::

## XLSX auto-conversion

For `xlsx_basic` and `xlsx_advanced` types, if the file hasn't been generated yet, it will be auto-converted on the first download request.

| Format | Cost (first conversion only) |
|--------|------|
| `xlsx_basic` | $0.001 per unit (1 milli-USD) |
| `xlsx_advanced` | $0.003 per unit (3 milli-USD) |

Subsequent downloads of the same format are free.

## Errors

| Status | Meaning |
|--------|---------|
| 400 | Job is not `done` yet |
| 402 | Insufficient credits for XLSX conversion |
| 404 | Result file not found for the requested type |
