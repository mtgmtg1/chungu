---
sidebar_position: 1
---

# POST /jobs/upload

Upload files and get a cost preview. Credits are **not** deducted at this step.

## Form fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `files` | File[] | Yes | — | One or more files (multipart/form-data) |
| `ocr_model` | string | No | `premium` | `basic` or `premium` |
| `ocr_engine` | string | No | `easyocr` | `tesseract`, `easyocr`, or `rapidocr` (premium only) |
| `columns` | string | No | defaults | Comma-separated or JSON array of column names |
| `prompt` | string | No | `""` | Extra instructions for the model |
| `dpi` | int | No | 300 | PDF rendering DPI |
| `relative_paths` | string | No | `""` | JSON array of relative paths for archive files |
| `docling_refinement` | bool | No | `false` | Enable LLM layout refinement for PDF/Office/HWP (3 md/page) |

## Request

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "ocr_model=premium" \
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
  "docling_refinement": false,
  "docling_refinement_pages": 0,
  "ocr_model": "premium",
  "ocr_engine": "easyocr",
  "has_media": false,
  "cost": {
    "pages": 10,
    "image_count": 0,
    "audio_seconds": 0,
    "video_seconds": 0,
    "ocr_model": "premium",
    "free_pages_used": 0,
    "points": 50,
    "usd": "$0.05"
  },
  "balance": 10000
}
```

## Fields

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | string | Job identifier — use for confirm/status/download |
| `status` | string | Always `pending` at this stage |
| `file_type` | string | `pdf`, `docx`, `pptx`, `xlsx`, `hwp`, `hwpx`, `image`, `audio`, `video`, `archive`, `mixed` (Markdown files report as `mixed`) |
| `total_pages` | int | Total PDF/Office/HWP pages detected |
| `total_files` | int | Total files (after archive extraction) |
| `media_duration_seconds` | int | Total audio/video duration |
| `docling_refinement` | bool | Whether docling refinement was requested |
| `docling_refinement_pages` | int | Pages subject to docling refinement (0 if disabled) |
| `ocr_model` | string | Model used (`basic` or `premium`) |
| `ocr_engine` | string | OCR engine used (`tesseract`, `easyocr`, or `rapidocr`) |
| `has_media` | bool | Whether audio/video files are included |
| `cost.points` | int | Credits that will be deducted on confirm (milli-USD) |
| `cost.usd` | string | Human-readable USD cost estimate |
| `cost.ocr_model` | string | Model used for cost calculation |
| `cost.free_pages_used` | int | Free pages applied (basic model only) |
| `balance` | int | Current credit balance in milli-USD (before deduction) |

## Office and HWP files

Office (`.docx`, `.pptx`, `.xlsx`) and HWP (`.hwp`, `.hwpx`) files are supported and routed through the Docling preprocessing pipeline (Office) or pyhwp (HWP). Page counts are estimated via Docling/pyhwp (defaults to 1 page if estimation fails).

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.docx" \
  -F "docling_refinement=true"
```

## Markdown files

Markdown (`.md`) files are supported and processed at **no cost** (0 credits). The text content is used directly as the result without OCR/LLM processing. Markdown files are ideal when you already have structured content and want to convert it to CSV/XLSX/DOCX/PPTX via the download/convert endpoints.

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@notes.md"
```

## Multiple files

Upload multiple files at once:

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@doc1.pdf" \
  -F "files=@doc2.pdf" \
  -F "ocr_model=premium"
```

## Errors

| Status | Meaning |
|--------|---------|
| 400 | No files, unsupported format, or missing filename |
| 413 | Total file size exceeds limit (default 200MB) or pages exceed limit (default 10,000) |
| 502 | File processing failed |
