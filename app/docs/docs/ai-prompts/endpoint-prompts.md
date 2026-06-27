---
sidebar_position: 2
---

# Endpoint-Specific AI Prompts

Copy-paste these prompts to have an AI agent call individual Chungu API endpoints.

## Upload a file

```
Call the Chungu API to upload a file for table extraction.

POST https://your-domain.com/api/v1/jobs/upload
Headers: X-API-Key: <API_KEY>
Body (multipart/form-data):
  - files: <the file to upload>
  - pipeline: vision
  - columns: <comma-separated column names, or omit for defaults>
  - prompt: <extra instructions, or omit>

Return the job_id from the response.
```

## Confirm a job

```
Call the Chungu API to confirm a job and start processing.

POST https://your-domain.com/api/v1/jobs/<JOB_ID>/confirm
Headers: X-API-Key: <API_KEY>

Return the status and remaining_points.
```

## Check job status

```
Call the Chungu API to check the status of a job.

GET https://your-domain.com/api/v1/jobs/<JOB_ID>
Headers: X-API-Key: <API_KEY>

If status is "processing", report progress as done_pages/total_pages.
If status is "done", the job is complete.
If status is "error", report the error_log.
```

## Download results

```
Call the Chungu API to get the download URL for a completed job.

GET https://your-domain.com/api/v1/jobs/<JOB_ID>/download?type=xlsx
Headers: X-API-Key: <API_KEY>

Return the download_url from the response.
```

## Convert to Office format

```
Call the Chungu API to convert a completed job to DOCX.

POST https://your-domain.com/api/v1/jobs/<JOB_ID>/convert
Headers:
  X-API-Key: <API_KEY>
  Content-Type: application/json
Body: {"format": "docx"}

Return the download_url from the response.
```

## Check account balance

```
Call the Chungu API to check the account info and point balance.

GET https://your-domain.com/api/v1/account
Headers: X-API-Key: <API_KEY>

Report the points_balance and today's usage.
```

## Python automation snippet

```python
import requests
import time

API_KEY = "chu_live_xxxxxxxx"
BASE = "https://your-domain.com/api/v1"
HEADERS = {"X-API-Key": API_KEY}

def process_file(filepath, columns=None, pipeline="vision", output_type="xlsx"):
    """Full pipeline: upload → confirm → poll → download."""
    # Step 1: Upload
    with open(filepath, "rb") as f:
        data = {"pipeline": pipeline}
        if columns:
            data["columns"] = columns
        resp = requests.post(f"{BASE}/jobs/upload", headers=HEADERS,
                             files={"files": f}, data=data)
    resp.raise_for_status()
    job_id = resp.json()["job_id"]

    # Step 2: Confirm
    resp = requests.post(f"{BASE}/jobs/{job_id}/confirm", headers=HEADERS)
    resp.raise_for_status()

    # Step 3: Poll
    while True:
        status = requests.get(f"{BASE}/jobs/{job_id}", headers=HEADERS).json()
        if status["status"] in ("done", "error"):
            break
        time.sleep(3)

    if status["status"] == "error":
        raise RuntimeError(f"Job failed: {status.get('error_log')}")

    # Step 4: Download
    url = requests.get(f"{BASE}/jobs/{job_id}/download",
                       params={"type": output_type}, headers=HEADERS).json()
    return url["download_url"]
```
