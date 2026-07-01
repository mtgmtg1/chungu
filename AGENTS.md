# AGENTS.md — Chungu Project Guide

## Project Overview

Chungu is a PDF/media → structured table (CSV/MD/XLSX) conversion service. It exposes core functionality both as a web application and as a monetized API (`/api/v1/*`) for external developers.

## Tech Stack

- **Backend**: FastAPI + SQLAlchemy + Celery + Redis
- **Frontend**: React + Vite + Tailwind CSS + react-i18next (en/ko/ja)
- **Storage**: Supabase Storage (PDFs, inputs, results)
- **Database**: PostgreSQL via Supabase (`supabase-chungu-db`)
- **LLM Inference (Images/PDF)**: vLLM proxy (`192.168.1.69:18080`) — round-robin load balancer to two Gemma-4 26B A4B AWQ 4bit instances (`18000` on GPU 1/2, `18001` on GPU 0/3); proxy auto-rewrites the request `model` name to the actual model loaded on the chosen backend
- **LLM Inference (Audio/Video/Images)**: llama.cpp (`192.168.1.82:18080`) — Gemma-4 12B GGUF Q4_K_M, 4 parallel slots
- **Deployment**: Docker Compose on `a1` (local server), exposed via Cloudflare Tunnel at `chungu.teamcat.app`

## Directory Structure

```
app/
  backend/          FastAPI app, workers, DB models, API endpoints
    api/v1/         Public API v1 (jobs, account, keys)
    auth/           JWT auth, API key auth
    core/           OCR pipeline, media loader, rate limit
    db/             SQLAlchemy models and migrations
    workers/        Celery tasks
  frontend/         React SPA
    src/locales/   i18n translation files (en/ko/ja × common/page)
    src/i18n.js     i18next configuration
    src/LanguageContext.jsx  Language provider with Supabase persistence
  docs/              Docusaurus documentation site (API docs, AI prompts)
    docs/            Markdown content (en: source of truth)
    i18n/ko/         Korean translations
    i18n/ja/         Japanese translations
    static/img/      Chungu logo & favicon SVGs
    docusaurus.config.js
    build/           Generated static site (gitignored)
  Dockerfile.backend
  docker-compose.yml
  .env.example
infra/
  mailu/            Mailu mail server deployment
ocr_output/         OCR output artifacts (ignored in git)
*.py                Standalone scripts and test helpers
```

## Environment Setup

Copy `app/.env.example` to `app/.env` and fill in:

- `DATABASE_URL`
- `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
- `REDIS_URL`
- `DEFAULT_LLM_ENDPOINT`, `DEFAULT_LLM_MODEL` (vLLM for images/PDF)
- `MEDIA_LLM_ENDPOINT`, `MEDIA_LLM_MODEL` (llama.cpp for audio/video + image share)
- `PUBLIC_BASE_URL` (external URL for download links)
- `SUPABASE_URL` (internal), `SUPABASE_PUBLIC_URL` (external proxied URL)
- `JWT_SECRET_KEY` (for Supabase token verification)
- `ADMIN_EMAIL`, `ADMIN_PASSWORD_HASH`
- Toss/Paddle keys for payments

## Local Development

```bash
cd app
# Backend
cd backend
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 28181

# Frontend
cd ../frontend
npm install
npm run dev

# Worker
cd ../backend
celery -A backend.celery_app.celery worker --loglevel=info

# Docs (Docusaurus)
cd ../docs
npm install
npm run build        # outputs to docs/build/
npm run start        # dev server at localhost:3000
```

## LLM Routing & Load Balancing

- **Audio/Video**: 100% routed to E4B (llama.cpp, `192.168.1.82:18080`)
- **Images/PDF pages (pipeline=vision)**: rendered to PNG by PyMuPDF and sent page-by-page to the vLLM proxy (`192.168.1.69:18080`). The proxy round-robins between two Gemma-4 26B A4B AWQ 4bit instances (`18000` on GPU 1/2, `18001` on GPU 0/3). If the request's `model` name does not match the loaded model on the selected backend, the proxy rewrites it to the actual backend model name before forwarding.
- **PDF pages (pipeline=docling)**: Docling OCR + optional LLM refinement; no per-page PNG rendering.
- **Mixed media batches** (images/audio/video): dynamically routed based on total count, but E4B image load is minimized to prioritize audio/video:
  - ≤6 items: 1:3 (vLLM:E4B) — E4B 1/3
  - 7~59 items: 1:5 (vLLM:E4B) — E4B 1/5
  - ≥60 items: 1:10 (vLLM:E4B) — E4B 1/10
- Routing logic in `pipeline_media.py:_resolve()` and `pipeline_vision.py:resolve_endpoint()`
- E4B has 4 parallel slots (`--parallel 4`), vLLM is optimized for high-batch throughput
- Celery worker concurrency: 8 (prefork)
- Thread limits per job: `llm_max_workers=64` (vLLM), `media_max_workers=8` (E4B), `ocr_max_workers=8` (Tesseract)
- `max_pages=10000` per file (configurable via settings_store)

## Large Image Tiling (Whiteboard/Planner)

- PDF pages for the vision pipeline are rendered to PNG by PyMuPDF (`ocr_client.render_pdf()`) using multi-threaded page rendering (16 workers), replacing the previous single-threaded `pdftoppm` path.
- High-resolution images (whiteboards, planners, posters) that exceed Gemma 4's vision encoder pixel limit (~2.58M pixels, ~1606x1606) are automatically split into overlapping tiles.
- Tiling logic in `ocr_client.py:tile_large_image()` — 15% overlap between tiles to avoid cutting text/tables at boundaries.
- `pipeline_media.py:_process_file()` calls `tile_large_image()` for each image; if tiling is needed, each tile is sent to the LLM separately and results are concatenated with `\n\n`.
- Images within the pixel limit are processed as-is (no tiling overhead).
- Tiles are generated in left-to-right, top-to-bottom reading order.
- No additional billing: tiling is an internal processing detail; the user is charged per original image, not per tile.
- Key files: `app/backend/core/ocr_client.py` (`tile_large_image`, `fit_image_to_gemma4_resolution`), `app/backend/core/pipeline_media.py` (`_process_file`).

## Supabase Proxy

- FastAPI reverse proxy at `/supabase/*` routes to internal Supabase (`192.168.1.50:28000`)
- Frontend uses `window.location.origin + '/supabase'` as Supabase URL (no hardcoded IPs)
- Signed download URLs are rewritten from internal to external proxied URLs in `supabase_client.py`
- Proxy implementation: `app/backend/api/supabase_proxy.py`

## Public URL & Email Confirmation

- All externally visible URLs must use the public domain (`https://chungu.teamcat.app`), never internal IPs.
- `app/backend/config.py` defaults `public_base_url` to `https://chungu.teamcat.app` and `supabase_public_url` to `https://chungu.teamcat.app/supabase` so that missing `.env` values do not leak internal addresses.
- In `app/.env` (and on the server):
  - `PUBLIC_BASE_URL=https://chungu.teamcat.app` (used by `email_sender.py` for download links)
  - `SUPABASE_PUBLIC_URL=https://chungu.teamcat.app/supabase` (used by `supabase_client.py` to rewrite signed Storage URLs)
- For self-hosted Supabase (`/opt/supabase-chungu/.env` on `a1`):
  - `SITE_URL=https://chungu.teamcat.app`
  - `ADDITIONAL_REDIRECT_URLS=https://chungu.teamcat.app/**`
  - `MAILER_URLPATHS_CONFIRMATION="/supabase/auth/v1/verify"`
  - `MAILER_URLPATHS_INVITE="/supabase/auth/v1/verify"`
  - `MAILER_URLPATHS_RECOVERY="/supabase/auth/v1/verify"`
  - `MAILER_URLPATHS_EMAIL_CHANGE="/supabase/auth/v1/verify"`
- With this setup, Supabase Auth emails generate links like `https://chungu.teamcat.app/supabase/auth/v1/verify?token=...&type=signup`, which are proxied by FastAPI's `/supabase/*` route to the internal Supabase Auth service (`192.168.1.50:28000`).
- Internal IPs (`192.168.1.x`, `localhost`, `127.0.0.1`) are reserved for backend-only services: LLM endpoints, Docling service, and the internal `SUPABASE_URL`.

## Deployment

Use the provided scripts:

```bash
bash build_backend.sh
bash deploy_a1.sh
```

This syncs `app/` to the `a1` server (via WAN host `wan-1`), rebuilds Docker images, and restarts containers.
Server `.env` must be updated manually (not overwritten by rsync).

## Storage Retention & Source Cleanup

- OCR 원본 업로드 파일은 `Job.created_at` 기준 **48시간** 후 Supabase Storage `pdfs` 버킷에서 자동 삭제된다.
- 변환 결과 파일(`results` 버킷)은 별도 보관 정책을 유지하며, 원본 삭제와 무관하게 다운로드 가능하다.
- DB의 `jobs` 레코드는 유지되며, 삭제 후 `pdf_storage_path` 및 `extracted_files` 내 `storage_path` 참조만 제거된다.
- 삭제 스케줄링: Celery beat가 1시간마다 `cleanup_expired_uploads` 태스크를 실행한다.
- 사용자가 수동으로 작업을 삭제하면 DB 레코드 삭제 전에 `pdfs` 버킷 원본 파일도 함께 삭제된다.
- jobs 리스트에는 `source_expires_at`를 기준으로 남은 시간(일/시간/분)이 표시된다.
- Key files:
  - `app/backend/api/jobs.py` — `_source_expires_at()`, `delete_job` Storage 정리
  - `app/backend/core/supabase_client.py` — `delete_source_files()`, `clear_source_paths()`
  - `app/backend/workers/tasks.py` — `cleanup_expired_uploads` periodic task
  - `app/backend/celery_app.py` — Celery beat schedule
  - `app/frontend/src/pages/JobsPage.jsx` — 남은 시간 표시
  - `app/docker-compose.yml` — `beat` 서비스

## Docling Preprocessing Pipeline

- Phase 1 routes PDF/DOCX/PPTX/XLSX/HTML through a dedicated Docling path (`run_docling` in `tasks.py`).
- Phase 2 adds HWP/HWPX support: `run_hwp` first converts the file to ODT via `pyhwp`'s `hwp5odt` (LibreOffice alone cannot read many HWP files), then converts ODT to DOCX via LibreOffice headless, and finally sends the DOCX to the Docling service. This avoids `pyhwp2md`/`hwp5odt` extracting only the first page of some multi-page HWP files. If LibreOffice or Docling fails, it falls back to the original pyhwp-based converter.
- The Docling service runs on a Xeon Scalable CPU server (not a1 GPU), using CPU PyTorch + Intel Extension for PyTorch (IPEX) for VNNI/OneDNN acceleration.
- OCR engine selection: set `OCR_ENGINE=tesseract` (default) or `OCR_ENGINE=easyocr` in `.env`. `OCR_LANG=ko+en+ja` controls Tesseract language packs.
- Tesseract 5.5.1 is the default for speed on Xeon 6230 dual-socket. The container uses the `ppa:alex-p/tesseract-ocr5` PPA; verify with `tesseract -v` inside the container — look for `Found AVX512VNNI`, `Found AVX512F`, `Found AVX2`, and `Found OpenMP`.
- EasyOCR handles rotated/noisy scans better but is slower; Tesseract works best on clean, deskewed scans.
- Key files:
  - `app/backend/docling_service/main.py` — FastAPI service with CPU accelerator, model quantization, and IPEX warm-up.
  - `app/backend/docling_service/Dockerfile` — Ubuntu 22.04 + CPU PyTorch + IPEX + Tesseract language packs.
  - `app/backend/docling_service/requirements.txt` — Docling/FastAPI deps (no torch GPU). Includes `openvino>=2024.0` and `nncf>=3.0`.
  - `app/backend/docling_service/benchmark_ocr.py` — EasyOCR vs Tesseract A/B benchmark tool.
  - `app/docker-compose.docling.yml` — Compose without GPU reservations.
  - `app/backend/core/docling_client.py` — a1 backend client for the Docling service.
  - `app/backend/core/pipeline_docling.py` — Docling markdown + optional LLM refinement.
  - `app/backend/core/hwp_converter.py` — pyhwp-based HWP/HWPX text/image/page extraction.
- Threading: `torch.set_num_threads(2)` (2 threads per request), `AcceleratorOptions(num_threads=80)` (total 80 threads = 40 concurrent requests on Xeon 6230 dual-socket). OpenVINO `INFERENCE_NUM_THREADS=2`.
- Celery worker concurrency: 16 (prefork).
- Backend `docling_max_workers`: 16 concurrent Docling requests.
- NUMA binding: use `numactl --cpunodebind=0 --membind=0` when launching the container. For dual-socket 6230, run two independent workers bound to each NUMA node for maximum throughput.
- Model quantization (applied in `_apply_ipex` after warm-up):
  - **RTDetrV2 (layout)**: OpenVINO NNCF INT8 quantization with `torch.jit.trace` → `ov.convert_model` → `nncf.quantize`. Cached on disk at `/data/ov_cache/`. Compiled with `INFERENCE_NUM_THREADS=2`.
  - **EfficientViT (detection)**: `torch.quantization.quantize_dynamic` (Linear INT8). OpenVINO conversion hangs due to dynamic control flow in forward.
  - **TableModel04_rs (table structure)**: `torch.quantization.quantize_dynamic` (Linear INT8). Discovered via `table_model.tf_predictor._model`.
  - **OCR model**: kept in FP32 to preserve recognition quality.
- `torch.autocast` patched to CPU float32 to avoid slow bfloat16 emulation on CPU.
- Batch sizes: Docling defaults (no custom env vars).
- Refinement costs: `cost_per_docling_refinement_page_krw` / `cost_per_docling_refinement_page_usd` in `settings_store`.
- Docs: `app/docs/docs/docling.md` and `app/docs/docs/hwp.md` (HWP Phase 2).

## GPU OCR Backends (Suspended)

- **Status**: b2 GPU server (RTX 3080) is currently down with boot failures and is scheduled for repair. All GPU OCR backend work is suspended until the server is recovered.
- **PaddleOCR-VL 1.6**: dual-container architecture (vLLM + PaddleOCR Pipeline) was in progress on b2. Files remain in `app/backend/paddleocr_service/` and `app/docker-compose.paddleocr.yml` for resumption after repair.
- **Nemotron-OCR-v2**: Docker-based evaluation was attempted but could not complete due to the b2 outage. The model is Turing/CC-7.5 unsupported by NVIDIA's official docs; evaluation will resume on a compatible GPU if available.
- **Fallback**: production currently uses the CPU-only Docling service with `OCR_ENGINE=easyocr`.

## Internationalization (i18n)

- Frontend uses `react-i18next` with two namespaces: `common` and `page`
- Translation files: `app/frontend/src/locales/{en,ko,ja}/{common,page}.json`
- Language detection: browser language → localStorage (`chungu-language`) → Supabase user profile
- Backend persists user language via `PATCH /api/auth/language`
- `LanguageSelector` component in sidebar for manual switching
- `LanguageContext.jsx` provides `useLanguage()` hook for global access
- API docs translated: `app/API.md` (en), `app/API.ko.md` (ko), `app/API.ja.md` (ja)
- Docusaurus docs site supports en/ko/ja via `i18n/{locale}/docusaurus-plugin-content-docs/current/` directories
- Docusaurus docs are served at `/docs/` by FastAPI (`main.py` mounts `docs/build/` as static files)
- Admin pages (`AdminDashboard.jsx`, `AdminLogin.jsx`) are not yet internationalized
- When adding new UI strings, add keys to all three languages and use `t('namespace:key')`

## API Notes

- Base path: `/api/v1`
- Authentication: `X-API-Key: chu_live_...` or `Authorization: Bearer <key>`
- Billing: points are deducted per page/image/audio/video
- Docs: `/api/v1/docs` (OpenAPI/Swagger)
- Developer portal: `/developer` in the web UI
- Docusaurus docs site: `/docs/` (served by FastAPI from `docs/build/`)

## Office Conversion (DOCX/PPTX/XLSX)

- Conversion is handled by `app/backend/core/office_converter.py`.
- All markdown content is preserved: headings, paragraphs, lists, tables, and code blocks. No data is lost.
- `docx`: renders headings, paragraphs with inline formatting (`**bold**`, `*italic*`, `~~strike~~`), bullet/numbered lists, tables, and code blocks.
- `pptx`: splits content into slides by headings; each slide contains the heading as a title and the following content as body text.
- `xlsx`: creates a `Content` sheet with all text/list/code content and a separate sheet per markdown table.
- Conversion endpoints: `/api/jobs/{id}/convert` (web) and `/api/v1/jobs/{id}/convert` (API). xlsx conversion still deducts points per page/file.

## DOCX/HWP Preview

- `docx` and `hwp` source files are converted to PDF on the backend using LibreOffice headless.
- The converted PDF is stored in Supabase Storage under the `pdfs` bucket (`preview_pdfs/` prefix) and reused across preview requests.
- The frontend renders the converted PDF with `PdfViewer` (PDF.js), just like native PDFs.
- Preview conversion is a server-side operation; no client-side load is added.
- CJK (Korean/Chinese/Japanese) fonts are installed in the Docker image so that non-Latin characters render correctly:
  - `fonts-noto-cjk`, `fonts-nanum`, `fonts-unfonts-core`, `fonts-noto-color-emoji`
  - `libreoffice-l10n-ko`, `libreoffice-help-ko`, `locales` with `LANG=ko_KR.UTF-8`/`LC_ALL=ko_KR.UTF-8`
- For `.hwp` files, the backend first tries `pyhwp`'s `hwp5odt` to produce an ODT and then converts it to PDF with LibreOffice. If `hwp5odt` is unavailable or fails, it falls back to direct LibreOffice conversion.
- Key files: `app/backend/core/pdf_preview_converter.py`, `app/Dockerfile.backend`, `app/backend/api/jobs.py`, `app/frontend/src/components/SourcePanel.jsx`.

## Result Preview & Multi-file Uploads

- Uploading multiple files creates one job; each file's parsing result is stored separately in `extracted_files[].result_markdown`.
- The combined markdown uses file markers (`<!-- 파일 N -->`) via `converter.build_combined_file_markdowns()`.
- `/api/jobs/{id}/preview` returns `source_files` (name, type, url, page_num, result_markdown) for each original file.
- PDF preview uses PDF.js (`PdfViewer`) to render one page at a time on a canvas, auto-fitted to the container. The toolbar with page navigation and zoom controls is at the top of the preview panel. The preview panel scrolls independently and the page is aligned to the top.
- `SourcePanel` renders a single source when only one exists, and a file list + selected preview when multiple sources exist.
- `SourcePanel` supports controlled selection via `selectedFileIndex` / `onFileSelect` props.
- `JobResultPage` manages `fileMarkdowns` state: when multiple files exist, `SimpleEditor` shows only the selected file's markdown.
- Saving in multi-file mode uses `api.saveResultFileMarkdowns()` (PUT `file_markdowns` array); single-file mode uses `api.saveResultMarkdown()`.
- The `save_result_markdown` backend endpoint accepts `file_markdowns` (array) to update `extracted_files` and rebuild the combined markdown.
- When adding new source media types, update `SourcePanel.jsx` and add i18n keys to `page:result` and `page:components`.

## Agent Guidelines

- Prefer minimal, focused edits. Follow existing code style.
- Add DB schema changes to `app/backend/db/migrations/` as SQL files.
- Do not commit media files, PDFs, or `node_modules`.
- Test API changes by creating a temporary API key and running the full upload→confirm→download flow.
- Keep the workflow-linear code style with flow comments at the top of major functions.
- When adding UI text, always use i18n translation keys. Never hardcode user-facing strings.
- Add new translation keys to all three locale files (en/ko/ja) simultaneously.
- When adding new Docusaurus docs pages, create the English source in `app/docs/docs/` and add Korean/Japanese translations under `app/docs/i18n/{ko,ja}/docusaurus-plugin-content-docs/current/`.
