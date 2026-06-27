---
sidebar_position: 5
---

# GET /jobs/`{job_id}`/download

Returns a signed Supabase Storage URL for downloading the result file.

## Query parameters

| Parameter | Type | Default | Options |
|-----------|------|---------|---------|
| `type` | string | `xlsx` | `csv`, `md`, `xlsx`, `docx`, `pptx` |

## Request

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  "https://your-domain.com/api/v1/jobs/job-abc123/download?type=xlsx"
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

For `csv` and `xlsx` types, if the XLSX file hasn't been generated yet, it will be auto-converted on the first download request. This costs an additional **3 points per unit** (page or file). Subsequent downloads of the same format are free.

## Errors

| Status | Meaning |
|--------|---------|
| 400 | Job is not `done` yet |
| 402 | Insufficient points for XLSX conversion |
| 404 | Result file not found for the requested type |
