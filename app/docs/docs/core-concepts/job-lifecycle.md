---
sidebar_position: 1
---

# Job Lifecycle

Every Chungu job follows a clear lifecycle from upload to download.

## States

| Status | Description |
|--------|-------------|
| `pending` | Files uploaded, awaiting confirmation |
| `queued` | Confirmed, waiting for a worker to pick it up |
| `processing` | Worker is actively processing the files |
| `done` | Processing complete, results available for download |
| `error` | Processing failed, check `error_log` |
| `cancelled` | Job was cancelled before completion |

## Flow

```
upload → pending → confirm → queued → processing → done
                                              ↘ error
```

1. **Upload** (`POST /jobs/upload`) — creates a job in `pending` state, returns cost preview
2. **Confirm** (`POST /jobs/{id}/confirm`) — deducts points, transitions to `queued`, dispatches to Celery worker
3. **Processing** — worker processes pages/files, updates `done_pages` / `done_files` in real time
4. **Done** — results are stored in Supabase Storage, ready for download
5. **Download** (`GET /jobs/{id}/download`) — returns a signed URL valid for 1 hour

## Polling strategy

Poll `GET /jobs/{id}` every 3–5 seconds. The response includes `done_pages` and `total_pages` so you can show progress.

```python
import time

while True:
    job = get_job(job_id)
    if job["status"] in ("done", "error"):
        break
    print(f"Progress: {job['done_pages']}/{job['total_pages']}")
    time.sleep(3)
```

## Error handling

If `status` is `error`, the `error_log` field contains details. Common causes:

- Unsupported file format
- Corrupted PDF or media file
- LLM inference timeout
- Insufficient points (caught at confirm step)
