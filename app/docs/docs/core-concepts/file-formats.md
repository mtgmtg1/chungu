---
sidebar_position: 2
---

# Supported File Formats

PROOF accepts a wide variety of input formats for table extraction.

## PDF

| Format | Notes |
|--------|-------|
| `.pdf` | Single or multi-page. Pages are rendered to images at the specified DPI. |

## Images

| Format | Notes |
|--------|-------|
| `.png` | Recommended for scanned documents |
| `.jpg` / `.jpeg` | |
| `.gif` | First frame is processed |
| `.bmp` | |
| `.webp` | |
| `.tiff` / `.tif` | |

## Audio

| Format | Notes |
|--------|-------|
| `.mp3` | |
| `.wav` | |
| `.flac` | |
| `.aac` | |
| `.ogg` | |
| `.m4a` | |
| `.wma` | |

Cost: **$0.001 per second** (1 milli-USD/sec) of audio. Premium model only.

## Video

| Format | Notes |
|--------|-------|
| `.mp4` | |
| `.avi` | |
| `.mov` | |
| `.mkv` | |
| `.flv` | |
| `.wmv` | |
| `.webm` | |
| `.m4v` | |

Cost: **$0.005 per second** (5 milli-USD/sec) of video. Audio is extracted and transcribed. Premium model only.

## Archives

Upload multiple files at once by compressing them:

| Format | Notes |
|--------|-------|
| `.zip` | Most common |
| `.rar` | |
| `.7z` | |
| `.tar` / `.gz` / `.tgz` / `.bz2` | |

All supported file types inside the archive are extracted and processed.

## Markdown

| Format | Notes |
|--------|-------|
| `.md` | Text content is used directly as the result — no OCR/LLM processing. **Free** (0 credits). |

Markdown files are ideal when you already have structured Markdown content and want to convert it to CSV/XLSX/DOCX/PPTX via the download/convert endpoints.

## Office formats

Office and HWP formats are supported via both the web app and the v1 API. They are routed through the Docling preprocessing pipeline (Office) or pyhwp (HWP).

| Format | Notes |
|--------|-------|
| `.docx` / `.doc` | Word documents — Docling preprocessing |
| `.pptx` / `.ppt` | PowerPoint — Docling preprocessing |
| `.xlsx` / `.xls` | Excel — Docling preprocessing |
| `.hwp` / `.hwpx` | Korean word processor — pyhwp conversion |

:::info
Office/HWP page counts are estimated via Docling/pyhwp. If estimation fails, the file is treated as 1 page.
:::

## Limitations

- Maximum file size: **200 MB** total per upload (admin-configurable)
- Maximum pages: **10,000** per job (admin-configurable)
- Unsupported formats will return `400 Bad Request`
