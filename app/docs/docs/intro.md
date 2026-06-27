---
sidebar_position: 1
---

# Introduction

Chungu is a PDF/media → structured table conversion service. Upload PDFs, images, audio, or video, and get back structured tables in CSV, Markdown, or XLSX format.

## What can you do with Chungu API?

- **Extract tables** from PDF documents, scanned images, and screenshots
- **Transcribe and structure** audio recordings and video files
- **Convert** results to CSV, Markdown, XLSX, DOCX, or PPTX
- **Automate** document processing with AI-powered pipelines

## How it works

```mermaid
flowchart LR
    A[Upload files] --> B[Get cost preview]
    B --> C[Confirm job]
    C --> D[Processing]
    D --> E[Poll status]
    E --> F[Download results]
```

1. **Upload** your files via `POST /api/v1/jobs/upload` — get a cost preview without spending points
2. **Confirm** the job via `POST /api/v1/jobs/{job_id}/confirm` — points are deducted, processing begins
3. **Poll** the job status via `GET /api/v1/jobs/{job_id}` until `status` is `done` or `error`
4. **Download** the result via `GET /api/v1/jobs/{job_id}/download?type=csv|md|xlsx`

## Get started

- New to Chungu? Read the [Quick Start](./quickstart) guide
- Need an API key? Visit the [Developer Portal](../../developer)
- Want AI to call the API for you? Check [AI Prompts](./ai-prompts/full-pipeline-prompt)
