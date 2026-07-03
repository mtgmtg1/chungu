---
sidebar_position: 5
---

# Extraction Options

Customize how PROOF extracts tables from your files.

## Model selection

Choose between basic and premium processing models:

| Model | Flag | Default | Notes |
|-------|------|---------|-------|
| Basic | `ocr_model=basic` | — | $0.001/page, 100 free pages/day, no audio/video |
| Premium | `ocr_model=premium` | ✓ | $0.005/page, supports all file types |

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "ocr_model=basic"
```

## OCR engine

For the premium model, select the OCR engine for text extraction:

| Engine | Flag | Default | Notes |
|--------|------|---------|-------|
| EasyOCR | `ocr_engine=easyocr` | ✓ | Balanced speed and accuracy |
| Tesseract | `ocr_engine=tesseract` | — | Fast, widely supported |
| RapidOCR | `ocr_engine=rapidocr` | — | Optimized for CJK text |

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "ocr_model=premium" \
  -F "ocr_engine=rapidocr"
```

## Columns

Specify column names to guide the model's extraction. If omitted, default columns are used.

### Comma-separated

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "columns=날짜,계정과목,적요,입금액,출금액,잔액"
```

### JSON array

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F 'columns=["date","account","description","debit","credit","balance"]'
```

## Prompt

Add extra instructions for the model to customize extraction behavior.

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "prompt=Extract only rows where the amount is greater than 1,000,000"
```

Common prompt examples:

- `"Merge multi-line cells into single cells"`
- `"Ignore header rows and only extract data rows"`
- `"Use YYYY-MM-DD date format"`
- `"Include a row number column"`

## DPI

Control the rendering resolution for PDF pages. Higher DPI improves accuracy for small text but increases processing time.

| DPI | Use case |
|-----|----------|
| 150 | Default, good for most documents |
| 300 | High detail, small fonts |
| 600 | Very fine print, receipts |

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "dpi=300"
```

## Relative paths (for archives)

When uploading archives, you can specify relative paths to preserve directory structure:

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@archive.zip" \
  -F 'relative_paths=["folder/doc1.pdf","folder/doc2.pdf"]'
```
