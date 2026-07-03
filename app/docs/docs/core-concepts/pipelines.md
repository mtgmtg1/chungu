---
sidebar_position: 4
---

# Models & Pipelines

PROOF offers two processing models for different input types, accuracy requirements, and budgets.

## Basic model (`ocr_model=basic`)

The basic model uses Docling for PDFs with a text layer, and Tesseract OCR for scanned documents and images. It is cost-effective and fast.

- **Best for**: Clean digital PDFs with embedded text
- **Speed**: Fast — text extraction without LLM calls
- **Cost**: $0.001/page (1 milli-USD), **100 free pages per day**
- **Limitations**: No audio/video support, lower accuracy for complex layouts

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "ocr_model=basic"
```

## Premium model (`ocr_model=premium`)

The premium model uses high performance AI vision model for all pages, providing superior accuracy for complex documents, scanned images, handwritten text, rotated pages, and tables.

- **Best for**: Scanned documents, handwritten text, complex tables, images, audio/video
- **Speed**: Moderate — one LLM call per page
- **Cost**: $0.005/page (5 milli-USD), no free quota
- **Features**: Audio ($0.001/sec), video ($0.005/sec), Docling refinement option

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "ocr_model=premium"
```

## OCR engine selection

For the premium model, you can specify the OCR engine used for text extraction:

| Engine | Flag | Notes |
|--------|------|-------|
| `easyocr` | Default | Good balance of speed and accuracy |
| `tesseract` | `ocr_engine=tesseract` | Fast, widely supported |
| `rapidocr` | `ocr_engine=rapidocr` | Optimized for CJK text |

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "ocr_model=premium" \
  -F "ocr_engine=rapidocr"
```

## Choosing a model

| Scenario | Recommended model |
|----------|-------------------|
| Clean digital PDF with text layer | `basic` |
| Scanned document | `premium` |
| Handwritten text | `premium` |
| Image with table | `premium` |
| Audio/video | `premium` (required) |
| Budget-conscious, high volume | `basic` (100 free pages/day) |
