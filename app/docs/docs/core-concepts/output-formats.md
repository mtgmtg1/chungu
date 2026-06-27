---
sidebar_position: 3
---

# Output Formats

Chungu can deliver results in multiple formats. The primary output is always Markdown, which is then converted to other formats on demand.

## Available formats

| Format | Endpoint parameter | Notes |
|--------|-------------------|-------|
| Markdown | `type=md` | Default output, raw structured table |
| CSV | `type=csv` | Comma-separated values |
| XLSX | `type=xlsx` | Excel spreadsheet (first conversion costs extra points) |
| DOCX | `type=docx` | Word document (via `/convert` endpoint) |
| PPTX | `type=pptx` | PowerPoint (via `/convert` endpoint) |

## Download vs Convert

- **Download** (`GET /jobs/{id}/download?type=`) — returns a signed URL for an already-generated result
- **Convert** (`POST /jobs/{id}/convert`) — generates a new format from the Markdown result

### When to use which

- Use **download** for `md` and `csv` (always available after job completion)
- Use **download** for `xlsx` (auto-converts on first request, then caches)
- Use **convert** for `docx` and `pptx` (not available via download endpoint)

## Example: Download XLSX

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  "https://your-domain.com/api/v1/jobs/job-abc123/download?type=xlsx"
```

## Example: Convert to DOCX

```bash
curl -X POST https://your-domain.com/api/v1/jobs/job-abc123/convert \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{"format": "docx"}'
```

## Signed URL expiry

Download URLs are valid for **1 hour**. Request a new URL if it expires.
