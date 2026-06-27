---
sidebar_position: 6
---

# Error Handling

Chungu API uses standard HTTP status codes. Error responses include a `detail` field with a human-readable message.

## Error codes

| Status | Meaning | Action |
|--------|---------|--------|
| 400 | Bad request — invalid file type, missing fields | Check request format |
| 401 | Invalid or missing API key | Verify your API key |
| 402 | Insufficient points | Purchase more points at `/payment` |
| 403 | Forbidden — missing scope or not a developer | Check key scopes |
| 404 | Job or resource not found | Verify the job ID |
| 413 | File too large or too many pages | Reduce file size or split PDF |
| 429 | Rate limit exceeded | Wait and retry after `Retry-After` header |
| 502 | Downstream processing error | Retry with exponential backoff |

## Error response format

```json
{
  "detail": "포인트가 부족합니다"
}
```

:::note
Error messages may be in Korean. Use the HTTP status code for programmatic handling.
:::

## Retry strategy

For `429` and `502` errors, use exponential backoff:

```python
import time
import requests

def retry_request(url, max_retries=3):
    for attempt in range(max_retries):
        resp = requests.get(url, headers=HEADERS)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 5))
            time.sleep(wait)
            continue
        if resp.status_code == 502 and attempt < max_retries - 1:
            time.sleep(2 ** attempt)
            continue
        return resp
    return resp
```

## Job errors

When a job fails, `GET /jobs/{id}` returns:

```json
{
  "job_id": "job-abc123",
  "status": "error",
  "error_log": "LLM inference timeout after 120s"
}
```

Common job errors:
- **LLM inference timeout** — model took too long, try again or reduce page count
- **Unsupported file format** — check [supported formats](../file-formats)
- **Storage upload failed** — transient infrastructure error, retry
