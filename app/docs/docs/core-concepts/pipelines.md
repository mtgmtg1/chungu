---
sidebar_position: 4
---

# Pipelines

Chungu offers two processing pipelines for different input types and accuracy requirements.

## Vision pipeline (default)

The `vision` pipeline renders each PDF page to an image and sends it to a vision-language model (VLM) for direct table extraction.

- **Best for**: Clean PDFs, scanned documents, images
- **Speed**: Fast — one model call per page
- **Accuracy**: High for structured tables

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "pipeline=vision"
```

## Hybrid pipeline

The `hybrid` pipeline combines OCR text extraction with vision model analysis. It first extracts text via Tesseract OCR, then sends both the image and OCR text to the model.

- **Best for**: Documents with mixed text and tables, low-quality scans
- **Speed**: Slower — OCR + model call per page
- **Accuracy**: Higher for text-heavy documents with complex layouts

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "pipeline=hybrid"
```

## Choosing a pipeline

| Scenario | Recommended pipeline |
|----------|---------------------|
| Clean digital PDF | `vision` |
| Scanned document | `vision` |
| Low-quality scan with text | `hybrid` |
| Image with table | `vision` |
| Audio/video | Either (pipeline is ignored for media) |
