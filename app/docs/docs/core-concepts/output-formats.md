---
sidebar_position: 3
---

# Output Formats

PROOF can deliver results in multiple formats. The primary output is always Markdown, which is then converted to other formats on demand.

## Available formats

| Format | Endpoint parameter | Notes |
|--------|-------------------|-------|
| Markdown | `type=md` | Default output, raw structured table |
| CSV Basic | `type=csv_basic` | Comma-separated values |
| XLSX Basic | `type=xlsx_basic` | Excel spreadsheet (first conversion costs extra credits) |
| XLSX Advanced | `type=xlsx_advanced` | Enhanced Excel with formatting (first conversion costs extra credits) |
| DOCX | `type=docx` | Word document (via `/convert` endpoint) |
| PPTX | `type=pptx` | PowerPoint (via `/convert` endpoint) |

## Download vs Convert

- **Download** (`GET /jobs/{id}/download?type=`) — returns a signed URL for an already-generated result
- **Convert** (`POST /jobs/{id}/convert`) — generates a new format from the Markdown result

### When to use which

- Use **download** for `md` and `csv_basic` (always available after job completion)
- Use **download** for `xlsx_basic` (auto-converts on first request, then caches)
- Use **download** for `xlsx_advanced` (auto-converts on first request, then caches)
- Use **convert** for `docx` and `pptx` (not available via download endpoint)

## Example: Download XLSX Basic

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  "https://your-domain.com/api/v1/jobs/job-abc123/download?type=xlsx_basic"
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
