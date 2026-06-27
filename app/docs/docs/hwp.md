# HWP/HWPX Support (Phase 2)

## Overview

Chungu supports Hangul Word Processor (`.hwp`) and its XML-based variant (`.hwpx`) files through a dedicated pyhwp-based converter on the a1 backend. This is part of the Docling preprocessing pipeline Phase 2.

- **Markdown extraction**: `pyhwp2md` converts text, paragraphs, headings, lists, and tables into Markdown.
- **Image extraction**: `pyhwp` reads the `BinData` OLE storage to extract embedded images.
- **Page estimation**: `hwp_converter.get_page_count()` reads the document summary info to estimate the number of pages.

## Pipeline Flow

1. **Upload**: `jobs.py` detects `.hwp` / `.hwpx` files via `media_loader.HWP_TYPES`.
2. **Page count**: `hwp_converter.get_page_count()` is called on the uploaded file.
3. **Worker routing**: `tasks.py` calls `run_hwp()` for single files or for files found inside archives.
4. **Processing**: `run_hwp()` in `pipeline_docling.py`:
   - Extracts Markdown with `pyhwp2md`.
   - Extracts `BinData` images with `pyhwp`.
   - Optionally runs LLM layout refinement using the same settings as the Docling path.
5. **Result**: the extracted Markdown is merged into CSV/MD/XLSX output like any other Docling-supported document.

## File Routing

- `media_loader.HWP_TYPES = {"hwp"}`
- Single file: `job.file_type in media_loader.HWP_TYPES` branch in `tasks.py`.
- Multi-file: `ftype in media_loader.HWP_TYPES` branch inside the archive extraction loop.
- Extracted files are uploaded to Supabase Storage with the same path logic as PDF/Office documents.

## Refinement

- The `use_docling_refinement` / `docling_refinement` flag controls whether LLM post-processing is applied to HWP/HWPX results as well.
- Charges are configured via `cost_per_docling_refinement_page_krw` / `cost_per_docling_refinement_page_usd` in `settings_store`.

## API and Frontend

- `POST /api/jobs/upload` accepts the `docling_refinement` form field.
- `UploadPage.jsx` shows a checkbox labeled "Use Docling layout refinement" for Docling-compatible documents, including HWP/HWPX.
- Supported file extensions include `.hwp` and `.hwpx`.

## Key Files

- `app/backend/core/hwp_converter.py` — HWP/HWPX text, image, and page extraction.
- `app/backend/core/pipeline_docling.py` — `run_hwp()` function that reuses the same refinement path as Docling.
- `app/backend/workers/tasks.py` — routes HWP/HWPX files to `run_hwp()`.
- `app/backend/api/jobs.py` — page counting and cost calculation for HWP/HWPX uploads.
- `app/backend/core/media_loader.py` — `HWP_TYPES` and file type detection.
