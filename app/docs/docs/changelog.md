---
sidebar_position: 100
---

# Changelog

## 2026-07-23

- Added **Office formats** (`.docx`, `.doc`, `.pptx`, `.ppt`, `.xlsx`, `.xls`) upload support — routed through Docling preprocessing pipeline
- Added **HWP formats** (`.hwp`, `.hwpx`) upload support — converted via pyhwp
- Added `docling_refinement` form parameter to `POST /jobs/upload` — enables LLM layout refinement for PDF/Office/HWP at 3 md/page
- Added **Markdown (`.md`)** file upload support — text content is used directly as the result at no cost (0 credits)
- Added `PATCH /jobs/{id}/title` endpoint to rename a job's display title in any state
- Added `GET /account/subscription` endpoint to query subscription plan, status, and monthly usage
- Corrected DPI default to **300** (was incorrectly documented as 150)
- Corrected pricing table to milli-USD (was stale "P" unit)

## 2026-07

- Migrated billing system from KRW points to **USD credits (milli-USD)**
- Removed Toss payment integration — **Paddle** is now the sole payment provider
- Added free-amount credit purchasing ($5–$500 USD) with auto-recharge support
- Added `ocr_model` parameter (`basic` / `premium`) to upload endpoint
- Added `ocr_engine` parameter (`tesseract` / `easyocr` / `rapidocr`) to upload endpoint
- Split XLSX output into `xlsx_basic` and `xlsx_advanced` formats
- Added `POST /jobs/{id}/action` endpoint for document parse retry/refund
- Added `POST /jobs/{id}/xlsx-advanced-action` endpoint for XLSX advanced retry/refund
- Basic model: 100 free pages per day
- Increased max pages to 10,000 per file
- Account endpoints now accept session tokens in addition to API keys

## 2026-06-27

- Launched PROOF API v1 documentation site
- Added support for audio and video file processing
- Added XLSX, DOCX, PPTX conversion endpoints
- Added API key rotation endpoint

## 2026-01-15

- Initial API v1 release
- Endpoints: account, keys, jobs (upload, confirm, status, download)
- Point-based billing system
- Vision and hybrid pipelines
