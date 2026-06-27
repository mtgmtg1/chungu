---
sidebar_position: 2
---

# Quick Start

Make your first API call in 5 minutes.

## Prerequisites

- A Chungu account (sign up at the web app)
- An API key (create one at [Developer Portal](../../developer))
- `curl` or any HTTP client

## Step 1: Get your API key

1. Log in to the Chungu web app
2. Navigate to **Developer Portal** (`/developer`)
3. Click **Create Key**
4. Copy the full key — it's only shown once

## Step 2: Check your account

Verify your key works and check your point balance:

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account
```

**Response:**
```json
{
  "user_id": "uuid",
  "email": "user@example.com",
  "points_balance": 10000,
  "today_usage": { "points_spent": 0, "requests": 0 }
}
```

## Step 3: Upload a file

Upload a PDF and get a cost preview (no points deducted yet):

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "pipeline=vision"
```

**Response:**
```json
{
  "job_id": "job-abc123",
  "status": "pending",
  "file_type": "pdf",
  "total_pages": 10,
  "cost": { "pages": 10, "points": 30, "krw": 30, "usd": "0.02" },
  "balance": 10000
}
```

## Step 4: Confirm the job

Confirm to deduct points and start processing:

```bash
curl -X POST https://your-domain.com/api/v1/jobs/job-abc123/confirm \
  -H "X-API-Key: chu_live_xxxxxxxx"
```

**Response:**
```json
{
  "job_id": "job-abc123",
  "status": "queued",
  "remaining_points": 9970
}
```

## Step 5: Poll for completion

Check the job status until it's `done`:

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/jobs/job-abc123
```

**Response (when done):**
```json
{
  "job_id": "job-abc123",
  "status": "done",
  "total_pages": 10,
  "done_pages": 10,
  "cost_points": 30,
  "downloadable": true
}
```

## Step 6: Download the result

Get a signed URL to download the result file:

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  "https://your-domain.com/api/v1/jobs/job-abc123/download?type=xlsx"
```

**Response:**
```json
{
  "download_url": "https://supabase-storage.example.com/results/job-abc123/result.xlsx?token=..."
}
```

## Python example

```python
import requests

API_KEY = "chu_live_xxxxxxxx"
BASE = "https://your-domain.com/api/v1"
HEADERS = {"X-API-Key": API_KEY}

# Upload
with open("document.pdf", "rb") as f:
    resp = requests.post(f"{BASE}/jobs/upload", headers=HEADERS,
                         files={"files": f}, data={"pipeline": "vision"})
job_id = resp.json()["job_id"]

# Confirm
requests.post(f"{BASE}/jobs/{job_id}/confirm", headers=HEADERS)

# Poll
import time
while True:
    status = requests.get(f"{BASE}/jobs/{job_id}", headers=HEADERS).json()
    if status["status"] in ("done", "error"):
        break
    time.sleep(5)

# Download
url = requests.get(f"{BASE}/jobs/{job_id}/download?type=csv",
                   headers=HEADERS).json()["download_url"]
print(f"Download: {url}")
```

## Next steps

- [Authentication](./authentication) — API key management details
- [Core Concepts](./core-concepts/job-lifecycle) — understand the job lifecycle
- [AI Prompts](./ai-prompts/full-pipeline-prompt) — let AI call the API for you
