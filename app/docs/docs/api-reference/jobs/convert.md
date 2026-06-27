---
sidebar_position: 6
---

# POST /jobs/`{job_id}`/convert

Convert a completed job's Markdown result to an Office format (XLSX, DOCX, or PPTX).

## Request

```bash
curl -X POST https://your-domain.com/api/v1/jobs/job-abc123/convert \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{"format": "docx"}'
```

## Body

| Field | Type | Description |
|-------|------|-------------|
| `format` | string | `xlsx`, `docx`, or `pptx` |

## Response

```json
{
  "download_url": "https://supabase-storage.example.com/results/job-abc123/result.docx?token=...",
  "format": "docx",
  "storage_path": "results/job-abc123/result.docx"
}
```

## Cost

| Format | Cost |
|--------|------|
| `xlsx` | 3 points per unit (first conversion only) |
| `docx` | Free |
| `pptx` | Free |

If the file was already converted (e.g., you request `xlsx` again), the existing file is returned at no cost.

## Errors

| Status | Meaning |
|--------|---------|
| 400 | Job is not `done`, or unsupported format |
| 402 | Insufficient points for XLSX conversion |
| 502 | Conversion or upload failed |
