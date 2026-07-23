# Chungu API v1 Documentation

Chungu API v1 allows external developers to upload PDFs/images/audio/video/Markdown and extract structured tables (CSV/MD/XLSX) using a prepaid credit system. Credits are measured in **milli-USD** (1,000 milli-USD = $1.00 USD).

## Base URL

All API endpoints are prefixed with `/api/v1`.

```
https://your-domain.com/api/v1
```

## Authentication

Authenticate with your API key via the `X-API-Key` header (or `Authorization: Bearer <key>`).

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" https://your-domain.com/api/v1/account
```

API keys can be created from the **Developer Portal** at `/developer` after signing in.

## Rate Limits

- Default: 60 requests per minute per API key.
- Concurrent jobs: up to 5 per account (configurable by admin).
- Daily credit quota: optional per key.

When exceeded, the API returns `429 Too Many Requests` with a `Retry-After` header.

## Pricing

Credits are deducted based on input type and model selected. All amounts are in milli-USD.

| Input | Basic model | Premium model |
|-------|-------------|---------------|
| PDF page | 1 md ($0.001) | 5 md ($0.005) |
| Office/HWP page | 1 md ($0.001) | 5 md ($0.005) |
| Image | 1 md ($0.001) | 5 md ($0.005) |
| Audio (per second) | — | 1 md ($0.001) |
| Video (per second) | — | 5 md ($0.005) |
| Markdown (`.md`) | Free (0 md) | Free (0 md) |
| Docling refinement (per page) | — | 3 md ($0.003) |

:::info
**Basic model**: 100 free pages per day. After the free quota, 1 md/page is charged.
**Premium model**: No free quota. All pages are charged at 5 md/page.
:::

Markdown files are processed at no cost — the text content is used as-is for the result.

Check current rates at `GET /api/v1/account/pricing`.

## Supported Input Types

- **PDF**: PDF
- **Office**: DOCX, DOC, PPTX, PPT, XLSX, XLS (routed through Docling preprocessing)
- **HWP**: HWP, HWPX (Korean word processor, converted via pyhwp)
- **Images**: PNG, JPG, JPEG, GIF, BMP, WEBP, TIFF
- **Audio**: MP3, WAV, FLAC, AAC, OGG, M4A, WMA
- **Video**: MP4, AVI, MOV, MKV, WEBM, FLV, WMV, M4V
- **Markdown**: MD (text content used directly as the result, no OCR/LLM processing)
- **Archives**: ZIP, RAR, 7Z, TAR, GZ, TGZ, BZ2

PDF, Office, and HWP/HWPX files are routed through the Docling preprocessing pipeline. Office/HWP page counts are estimated via Docling/pyhwp (defaults to 1 page if estimation fails).

## Core Flow

1. **Upload files** → `POST /jobs/upload` returns a `job_id` and cost preview.
2. **Confirm job** → `POST /jobs/{job_id}/confirm` deducts credits and queues processing.
3. **Poll status** → `GET /jobs/{job_id}` until `status` is `done` or `error`.
4. **Download result** → `GET /jobs/{job_id}/download?type=csv_basic|md|xlsx_basic` returns a signed URL.

## Endpoints

### Account

#### `GET /account`

Returns account info, credit balance, today's usage, and current API key metadata.

**Response:**
```json
{
  "user_id": "uuid",
  "email": "user@example.com",
  "points_balance": 10000,
  "api_key": { "id": "...", "name": "...", "scopes": ["jobs:read", "jobs:write"] },
  "today_usage": { "points_spent": 150, "requests": 12 }
}
```

#### `GET /account/pricing`

Returns current credit rates (milli-USD) and charge limits.

#### `GET /account/transactions`

Returns credit charge/spend history.

#### `GET /account/usage?days=30`

Returns daily aggregated usage.

#### `GET /account/payments`

Returns payment history.

#### `GET /account/subscription`

Returns the current subscription status, plan, monthly limit, and usage.

**Response:**
```json
{
  "plan": "pro",
  "status": "active",
  "monthly_limit": 100000,
  "used": 5000
}
```

### API Keys

#### `POST /keys`

Create a new API key.

**Request:**
```json
{ "name": "production", "scopes": ["jobs:read", "jobs:write"] }
```

**Response:**
```json
{
  "id": "key-id",
  "name": "production",
  "prefix": "chu_live",
  "key": "chu_live_...",
  "scopes": ["jobs:read", "jobs:write"],
  "rate_limit_rpm": 60
}
```

The full `key` is returned only once.

#### `GET /keys`

List your API keys (without full key values).

#### `DELETE /keys/{id}`

Deactivate an API key.

#### `POST /keys/{id}/rotate`

Rotate an API key (generates a new key value, invalidates the old one).

#### `GET /keys/{id}/usage`

Returns usage statistics for a specific API key.

### Jobs

#### `POST /jobs/upload`

Upload files and get a cost preview. Credits are **not** deducted at this step.

**Form fields:**
- `files`: one or more files (multipart/form-data)
- `pipeline`: `"vision"` (default) or `"hybrid"`
- `columns`: comma-separated column names or JSON array (optional)
- `prompt`: extra instruction for the model (optional)
- `dpi`: PDF rendering DPI, default **300**
- `ocr_model`: `"basic"` or `"premium"` (default `"premium"`)
- `ocr_engine`: `"tesseract"`, `"easyocr"` (default), or `"rapidocr"` (premium only)
- `relative_paths`: JSON array of relative paths for archive files (optional)
- `docling_refinement`: `true` or `false` (default). Enables LLM layout refinement for PDF/Office/HWP documents at 3 md/page.

**Response:**
```json
{
  "job_id": "job-id",
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
  "cost": { "pages": 10, "points": 50, "usd": "$0.05" },
  "balance": 10000
}
```

#### `POST /jobs/{job_id}/confirm`

Confirm the job, deduct credits, and start processing.

**Response:**
```json
{
  "job_id": "job-id",
  "status": "queued",
  "remaining_points": 9950
}
```

#### `GET /jobs/{job_id}`

Get job status and metadata.

**Response:**
```json
{
  "job_id": "job-id",
  "status": "done",
  "pipeline": "vision",
  "file_type": "pdf",
  "filename": "document.pdf",
  "total_pages": 10,
  "done_pages": 10,
  "total_files": 1,
  "done_files": 1,
  "media_duration_seconds": 0,
  "ocr_model": "premium",
  "ocr_engine": "easyocr",
  "cost_points": 50,
  "error_log": null,
  "downloadable": true,
  "xlsx_converted": false,
  "xlsx_basic_converted": false,
  "xlsx_advanced_converted": false,
  "xlsx_advanced_status": null,
  "xlsx_advanced_job_id": null,
  "xlsx_advanced_refundable": false,
  "xlsx_advanced_recovery_notes": null,
  "refundable": false,
  "retry_count": 0,
  "created_at": "2026-07-23T00:00:00",
  "finished_at": "2026-07-23T00:01:00"
}
```

#### `GET /jobs`

List your jobs. Supports `limit` query parameter (default 100).

#### `PATCH /jobs/{job_id}/title`

Rename a job's display title. Available in any job state.

**Request:**
```json
{ "title": "New title" }
```

**Response:** same as `GET /jobs/{job_id}`.

**Errors:**

| Status | Meaning |
|--------|---------|
| 400 | Title is empty or exceeds 200 characters |
| 404 | Job not found or doesn't belong to you |

#### `GET /jobs/{job_id}/download?type=xlsx_basic`

Returns a signed Supabase Storage URL for the result file.

**Supported types:** `csv_basic`, `md`, `xlsx_basic`, `xlsx_advanced`, `docx`, `pptx`.

**Response:**
```json
{ "download_url": "https://..." }
```

:::info
The signed URL is valid for **1 hour**. For `xlsx_basic`/`csv_basic`, the file is auto-converted on first download (1 md/unit, first conversion only).
:::

#### `POST /jobs/{job_id}/convert`

Convert a completed job's Markdown result to an Office format.

**Request:**
```json
{ "format": "xlsx_basic" }
```

**Supported formats:** `xlsx_basic`, `csv_basic`, `xlsx_advanced`, `docx`, `pptx`.

| Format | Cost |
|--------|------|
| `xlsx_basic` / `csv_basic` | 1 md/unit, first conversion only |
| `xlsx_advanced` | 3 md/unit, first conversion only |
| `docx` / `pptx` | Free |

#### `POST /jobs/{job_id}/action`

Retry or refund a failed document parsing job. Only available when `status` is `error` and `refundable` is `true`.

**Request:**
```json
{ "action": "retry" }
```

**Actions:** `retry` (re-dispatch at no extra cost) or `refund` (refund all credits).

#### `POST /jobs/{job_id}/xlsx-advanced-action`

Retry or refund a failed XLSX Advanced conversion. Only available when `xlsx_advanced_status` is `error` and `xlsx_advanced_refundable` is `true`.

**Request:**
```json
{ "action": "retry" }
```

## Error Codes

| Status | Meaning |
|--------|---------|
| 400 | Bad request (invalid file type, missing fields) |
| 401 | Invalid or missing API key |
| 402 | Insufficient credits |
| 403 | Forbidden (missing scope) |
| 413 | File too large or too many pages |
| 429 | Rate limit exceeded |
| 502 | Downstream processing error |

## Webhooks (planned)

Register a callback URL to receive job completion events:

```bash
curl -X POST /api/v1/webhooks \
  -H "X-API-Key: <key>" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://your-app.com/webhooks/chungu","events":["job.done","job.error"]}'
```

## OpenAPI / Swagger

Interactive documentation is available at:

```
/api/v1/docs
```
