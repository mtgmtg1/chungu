# Chungu API v1 Documentation

Chungu API v1 allows external developers to upload PDFs/images/audio/video and extract structured tables (CSV/MD/XLSX) using a prepaid point system.

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
- Daily point quota: optional per key.

When exceeded, the API returns `429 Too Many Requests` with a `Retry-After` header.

## Pricing

Points are deducted based on input type:

| Input | Cost |
|-------|------|
| PDF page | 3P |
| Image | 3P |
| Audio 1 second | 1P |
| Video 1 second | 3P |
| Docling refinement per page | 3P |

Docling refinement applies an optional LLM post-processing step to Docling-preprocessed documents (PDF, Office, HTML, HWP) to improve layout accuracy.

Check current prices and packages at `GET /api/v1/account/pricing`.

## Supported Input Types

- **Documents**: PDF, DOCX, DOC, PPTX, PPT, XLSX, XLS, HTML, HWP, HWPX
- **Images**: PNG, JPG, JPEG, GIF, WEBP, BMP, TIFF
- **Audio**: MP3, WAV, FLAC, AAC, OGG, M4A, WMA
- **Video**: MP4, AVI, MOV, MKV, WEBM, FLV, WMV, M4V
- **Archives**: ZIP, RAR, 7Z, TAR, GZ, TGZ, BZ2

PDF, Office, HTML, and HWP/HWPX files are routed through the Docling preprocessing pipeline.

## Core Flow

1. **Upload files** → `POST /jobs/upload` returns a `job_id` and cost preview.
2. **Confirm job** → `POST /jobs/{job_id}/confirm` deducts points and queues processing.
3. **Poll status** → `GET /jobs/{job_id}` until `status` is `done` or `error`.
4. **Download result** → `GET /jobs/{job_id}/download?type=csv|md|xlsx` returns a signed URL.

## Endpoints

### Account

#### `GET /account`

Returns account info, point balance, today's usage, and current API key metadata.

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

Returns point packages and per-unit rates.

#### `GET /account/transactions`

Returns point charge/spend history.

#### `GET /account/usage?days=30`

Returns daily aggregated usage.

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

### Jobs

#### `POST /jobs/upload`

Upload files and get a cost preview.

**Form fields:**
- `files`: one or more files (multipart/form-data)
- `pipeline`: `"vision"` (default) or `"hybrid"`
- `columns`: comma-separated column names or JSON array (optional)
- `prompt`: extra instruction for the model (optional)
- `dpi`: PDF rendering DPI, default 150
- `docling_refinement`: `true` or `false` (default). Enables LLM layout refinement for Docling-compatible documents.

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
  "cost": { "pages": 10, "points": 30, "krw": 30, "usd": "0.02" },
  "balance": 9970
}
```

#### `POST /jobs/{job_id}/confirm`

Confirm the job, deduct points, and start processing.

**Response:**
```json
{
  "job_id": "job-id",
  "status": "queued",
  "remaining_points": 9940
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
  "cost_points": 30,
  "downloadable": true,
  "created_at": "2026-06-26T00:00:00",
  "finished_at": "2026-06-26T00:01:00"
}
```

#### `GET /jobs`

List your jobs. Supports `limit` query parameter.

#### `GET /jobs/{job_id}/download?type=xlsx`

Returns a signed Supabase Storage URL for the result file.

**Supported types:** `csv`, `md`, `xlsx`.

**Response:**
```json
{ "download_url": "https://..." }
```

## Error Codes

| Status | Meaning |
|--------|---------|
| 400 | Bad request (invalid file type, missing fields) |
| 401 | Invalid or missing API key |
| 402 | Insufficient points |
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
