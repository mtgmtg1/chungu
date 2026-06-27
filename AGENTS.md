# AGENTS.md — Chungu Project Guide

## Project Overview

Chungu is a PDF/media → structured table (CSV/MD/XLSX) conversion service. It exposes core functionality both as a web application and as a monetized API (`/api/v1/*`) for external developers.

## Tech Stack

- **Backend**: FastAPI + SQLAlchemy + Celery + Redis
- **Frontend**: React + Vite + Tailwind CSS + react-i18next (en/ko/ja)
- **Storage**: Supabase Storage (PDFs, inputs, results)
- **Database**: PostgreSQL via Supabase (`supabase-chungu-db`)
- **LLM Inference (Images/PDF)**: vLLM proxy (`192.168.1.69:18080`) — Qwen3.6-27B-AWQ, high-batch optimized
- **LLM Inference (Audio/Video/Images)**: llama.cpp (`192.168.1.82:18080`) — Gemma-4 E4B GGUF, 4 parallel slots
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
- **Images/PDF pages**: dynamically routed based on total count:
  - ≤20 items: 1:4 (vLLM:E4B) — E4B 80%, small batches benefit from E4B speed
  - 21~200 items: 1:1 — balanced
  - >200 items: 4:1 (vLLM:E4B) — vLLM 80%, high-batch throughput dominates
- Routing logic in `pipeline_media.py:_resolve()` and `pipeline_vision.py:resolve_endpoint()`
- E4B has 4 parallel slots (`--parallel 4`), vLLM is optimized for high-batch throughput
- Celery worker concurrency: 8 (prefork)
- Thread limits per job: `llm_max_workers=64` (vLLM), `media_max_workers=8` (E4B), `ocr_max_workers=8` (Tesseract)
- `max_pages=10000` per file (configurable via settings_store)

## Supabase Proxy

- FastAPI reverse proxy at `/supabase/*` routes to internal Supabase (`192.168.1.50:28000`)
- Frontend uses `window.location.origin + '/supabase'` as Supabase URL (no hardcoded IPs)
- Signed download URLs are rewritten from internal to external proxied URLs in `supabase_client.py`
- Proxy implementation: `app/backend/api/supabase_proxy.py`

## Deployment

Use the provided scripts:

```bash
bash build_backend.sh
bash deploy_a1.sh
```

This syncs `app/` to the `a1` server (via WAN host `wan-1`), rebuilds Docker images, and restarts containers.
Server `.env` must be updated manually (not overwritten by rsync).

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

## Result Preview & Multi-file Uploads

- Uploading multiple files creates one job; each file's parsing result is stored separately in `extracted_files[].result_markdown`.
- The combined markdown uses file markers (`<!-- 파일 N -->`) via `converter.build_combined_file_markdowns()`.
- `/api/jobs/{id}/preview` returns `source_files` (name, type, url, page_num, result_markdown) for each original file.
- PDF preview uses a browser-native iframe viewer (`SourcePanel` / `PdfViewer`), not PDF.js.
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
