---
sidebar_position: 5
---

# Extraction Options

Customize how Chungu extracts tables from your files.

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
  -F "prompt=Extract only rows where the amount is greater than 1,000,000 KRW"
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
