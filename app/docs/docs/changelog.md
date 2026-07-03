---
sidebar_position: 100
---

# Changelog

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
