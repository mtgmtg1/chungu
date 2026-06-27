---
sidebar_position: 2
---

# Supported File Formats

Chungu accepts a wide variety of input formats for table extraction.

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

Cost: **1 point per second** of audio.

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

Cost: **3 points per second** of video. Audio is extracted and transcribed.

## Archives

Upload multiple files at once by compressing them:

| Format | Notes |
|--------|-------|
| `.zip` | Most common |
| `.rar` | |
| `.7z` | |
| `.tar` / `.gz` / `.tgz` / `.bz2` | |

All supported file types inside the archive are extracted and processed.

## Limitations

- Maximum file size: **200 MB** total per upload (admin-configurable)
- Maximum pages: **2,000** per job (admin-configurable)
- Unsupported formats will return `400 Bad Request`
