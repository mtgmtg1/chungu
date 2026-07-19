# Subagent B Status
- Branch: feature/annotation-coordinate-context
- Worktree: /Users/jun16/repo/chungu-worktree-b
- Status: completed
- Started: 2026-01-12T02:00:00Z
- Last update: 2026-01-12T02:35:00Z - All verification passed

## Summary
Implemented `_coordinate_context` metadata in annotation JSON to prevent y-flip and coordinate mismatches when the original PDF and searchable PDF have different page sizes.

## Files changed
- `app/backend/api/jobs.py`
  - `save_user_annotations` now selects the coordinate source PDF based on `source_index` (annotated_pdf_files entry -> `job.searchable_pdf_storage_path` -> `job.pdf_storage_path`), converts `pdf_user` inputs to device-space using that PDF, and attaches `_coordinate_context` to each annotation item.
  - `get_job_annotations` and `get_job_result_json` now convert device-space back to PDF user-space using per-annotation `_coordinate_context`, falling back to `job.pdf_storage_path` for legacy JSON.
- `app/backend/core/pdf_user_annotator.py`
  - Added `_coordinate_context` helpers: `_build_coordinate_context`, `_attach_coordinate_context`, `_get_page_rect_from_context`, `_extract_page_dimensions_from_pdf_bytes`, `_get_pdf_bytes_for_context`.
  - `_convert_annotations_to_pdf_user` / `_convert_annotations_to_device_space` now use per-annotation context page dimensions when available.
  - Fixed `fitz.Rect(page_x0, page_y0, page_x0 + page_height, page_y0 + page_height)` width=height bug by adding `page_width` parameters and using `page_x0 + page_width`.
- `app/backend/core/pdf_annotator.py`
  - Added `page_width` to all coordinate-conversion helpers and `build_embedpdf_annotations` to fix the same width bug.
  - `build_embedpdf_annotations` accepts optional `coordinate_context` and attaches it to generated annotation items.
- `app/backend/core/pdf_annotate_converter.py`
  - `run()` now builds `_coordinate_context` from the searchable PDF used for annotation generation and passes it to `build_embedpdf_annotations`.
- `app/backend/tests/test_coord_transform.py`
  - Updated calls to coordinate helpers to pass `page_width=595.0` for A4.
- `app/backend/tests/test_jobs_result_json_annotations.py`
  - Extended with tests verifying `_coordinate_context` preservation and that `get_job_result_json` uses the context PDF for conversion.
- `app/backend/tests/test_save_user_annotations_metadata.py` (new)
  - Tests `save_user_annotations` attaches `_coordinate_context` and round-trips correctly when original and searchable PDF heights differ, plus fallback to `job.pdf_storage_path` for legacy JSON without context.

## Verification results
- `cd app/backend && .venv/bin/python -m pytest tests/ -q` → 235 passed
- `cd app/ai-backend && npm run build` → tsc success
- `cd app/frontend && npm run build` → vite production build success

## Notes
- No AI-backend or frontend source code was modified; both builds pass unchanged.
- `node_modules` and `.venv` are shared symlinks from the main repo and remain untracked.
- No push/merge performed per instructions.
