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
| `format` | string | `xlsx_basic`, `xlsx_advanced`, `docx`, or `pptx` |

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
| `xlsx_basic` | $0.001 per unit (1 milli-USD), first conversion only |
| `xlsx_advanced` | $0.003 per unit (3 milli-USD), first conversion only |
| `docx` | Free |
| `pptx` | Free |

If the file was already converted (e.g., you request `xlsx_basic` again), the existing file is returned at no cost.

## Errors

| Status | Meaning |
|--------|---------|
| 400 | Job is not `done`, or unsupported format |
| 402 | Insufficient credits for XLSX conversion |
| 502 | Conversion or upload failed |
