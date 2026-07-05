# AGENTS.md — PROOF Project Guide

## Project Overview

PROOF is a PDF/media → structured table (CSV/MD/XLSX) conversion service. It exposes core functionality both as a web application and as a monetized API (`/api/v1/*`) for external developers.

## Tech Stack

- **Backend**: FastAPI + SQLAlchemy + Celery + Redis
- **Frontend**: React + Vite + Tailwind CSS + react-i18next (en/ko/ja)
- **Storage**: Supabase Storage (PDFs, inputs, results)
- **Database**: PostgreSQL via Supabase (`supabase-chungu-db`)
- **LLM Inference (Images/PDF)**: vLLM proxy (`192.168.1.69:18080`) — round-robin load balancer to two Gemma-4 26B A4B AWQ 4bit instances (`18000` on GPU 1/2, `18001` on GPU 0/3); proxy auto-rewrites the request `model` name to the actual model loaded on the chosen backend
- **LLM Inference (Audio/Video/Images)**: llama.cpp (`192.168.1.82:18080`) — Gemma-4 12B GGUF Q4_K_M, 4 parallel slots
- **Deployment**: Docker Compose on `a1` (local server), exposed via Cloudflare Tunnel at `proof.teamcat.app`

## Directory Structure

```
app/
  backend/          FastAPI app, workers, DB models, API endpoints
    api/v1/         Public API v1 (jobs, account, keys)
    auth/           JWT auth, API key auth
    core/           OCR pipeline, media loader, rate limit
      docling_client.py           Docling 서비스 클라이언트
      paddleocr_client.py         PaddleOCR 클라이언트
      paddleocr_fallback.py       PaddleOCR 폴백 제어 (회로 차단기)
      paddleocr_parameter_recommender.py  Vision LLM 샘플 기반 파라미터 추천
      pdf_annotate_converter.py   PDF 하이라이트/여백 주석 오케스트레이터
      pdf_annotator.py            PDF 주석 적용
      pdf_coords.py               좌표 변환
      ocr_layout.py               OCR 레이아웃 파싱
      xlsx_advanced_converter.py  마크다운에서 고급 XLSX 변환
      pipeline_docling.py         Docling 파이프라인
      pipeline_vision.py          Vision 파이프라인
      pipeline_media.py           Media 파이프라인
      pipeline_hybrid.py          Hybrid 파이프라인 (사용하지 않음)
    db/             SQLAlchemy models and migrations
    workers/        Celery tasks
    docling_service/ Docling 서비스 (별도 Docker 컨테이너)
  frontend/         React SPA
    src/locales/   i18n translation files (en/ko/ja × common/page)
    src/i18n.js     i18next configuration
    src/LanguageContext.jsx  Language provider with Supabase persistence
  docs/              Docusaurus documentation site (API docs, AI prompts)
    docs/            Markdown content (en: source of truth)
    i18n/ko/         Korean translations
    i18n/ja/         Japanese translations
    static/img/      PROOF logo & favicon SVGs
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
- Turnstile: `TURNSTILE_SITE_KEY`, `TURNSTILE_WORKER_URL`, `VITE_TURNSTILE_SITE_KEY`, `VITE_TURNSTILE_WORKER_URL`
- Toss/Paddle keys for payments
- PaddleOCR: `PADDLEOCR_SERVICE_URL`, `PADDLEOCR_API_TOKEN`, `PADDLEOCR_API_URL`, `PADDLEOCR_FALLBACK_ENABLED`
- Docling: `DOCLING_ENABLED`, `DOCLING_SERVICE_URL`, `DOCLING_REFINEMENT_ENABLED`

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

- **Audio/Video**: E4B (llama.cpp, `192.168.1.82:18080`) — **현재 서버 다운, 비활성화**
- **PDF routing** (임시 정책 — vLLM/Docling 서버 개선 전까지):
  - **기본변환** (`ocr_model == "basic"`): `has_pdf_text_layer()` → True면 Docling, False면 `run_vision`(PaddleOCR 우선)
  - **고급변환** (`ocr_model == "premium"`): 무조건 `run_vision` — 모든 페이지 PaddleOCR 우선, 실패 시 vLLM fallback
  - **이미지 파일**: `run_media` → PaddleOCR 우선 (`is_fallback_preferred() == True`)
  - 라우팅 분기 순서: `tasks.py`에서 `ocr_model == "basic" and has_pdf_text_layer()` → True면 Docling, 그 외 PDF는 `run_vision`
  - `run_vision` 내에서 개별 페이지 텍스트 레이어 검사 없음 — 모든 페이지 동일하게 PaddleOCR 우선 처리
- **PDF pages (pipeline=vision)**: rendered to PNG by PyMuPDF and sent page-by-page to the vLLM proxy (`192.168.1.69:18080`). The proxy round-robins between two Gemma-4 26B A4B AWQ 4bit instances (`18000` on GPU 1/2, `18001` on GPU 0/3). `run_vision`은 항상 vLLM endpoint로 라우팅 (E4B media endpoint 라우팅 제거됨).
- **Mixed media batches** (images/audio/video): `pipeline_media.py:_resolve()`에서 동적 라우팅 — E4B 서버 다운 시 media_endpoint 없이 vLLM만 사용
- Routing logic in `pipeline_media.py:_resolve()` and `pipeline_vision.py:resolve_endpoint()`
- E4B has 4 parallel slots (`--parallel 4`) — **현재 다운, 비활성화**
- vLLM is optimized for high-batch throughput
- Celery worker concurrency: 8 (prefork)
- Thread limits per job: `llm_max_workers=64` (vLLM), `media_max_workers=8` (E4B), `ocr_max_workers=8` (Tesseract), `docling_max_workers=16` (Docling)
- `max_pages=10000` per file (configurable via settings_store)

## PaddleOCR Fallback System

- **회로 차단기 (Circuit Breaker) 패턴**: `paddleocr_fallback.py`에서 Redis 기반 상태 관리, Redis 불가 시 in-memory fallback
- **상태 전환**: 1분 내 3회 이상 실패 시 OPEN → 600초 후 HALF_OPEN → 성공 시 CLOSED 복귀
- **임시 정책**: `is_fallback_preferred()`가 항상 `True`를 반환하여 PaddleOCR을 우선 사용 (vLLM/Docling 서버 개선 전까지)
- **폴백 제어**: `fallback_controller.can_use_fallback()`로 폴백 가능 여부 판단, `consume_fallback()`로 사용 기록
- **설정 옵션**:
  - `paddleocr_fallback_enabled`: 폴백 시스템 활성화/비활성화
  - `paddleocr_fallback_failure_threshold`: 회로 차단기 임계값 (기본값 3)
  - `paddleocr_fallback_open_seconds`: OPEN 상태 지속 시간 (기본값 600초)
- **Key files**: `app/backend/core/paddleocr_fallback.py`, `app/backend/core/paddleocr_client.py`, `app/backend/core/paddleocr_parameter_recommender.py`

## XLSX Advanced Converter

- **기능 개요**: 마크다운 결과에서 고급 XLSX 변환 — 페이지별 표 정리/재구성 후 통합 XLSX 저장
- **처리 흐름**:
  1. 원본 job 마크다운 로드 (편집된 마크다운 우선)
  2. `<!-- 페이지 N -->` 마커 기준 페이지 분할
  3. 첫 페이지에서 컬럼 구조 추출 (Vision LLM 또는 텍스트 LLM)
  4. 페이지별 표 정리/재구성 (컬럼 구조 기반)
  5. openpyxl로 XLSX 통합 저장 (스타일 적용)
  6. 원래 job 업데이트 (결과 파일 경로, 상태)
- **컬럼 추출**: Vision LLM (`call_vision`) 우선, 실패 시 텍스트 LLM (`call_text`) 폴백
- **스타일링**: openpyxl로 헤더 폰트, 정렬, 배경색 적용
- **오류 처리**: 실패 시 job 상태를 `error`로 변경하고 `refundable=True` 설정
- **Key files**: `app/backend/core/xlsx_advanced_converter.py`

## Large Image Tiling (Whiteboard/Planner)

- PDF pages for the vision pipeline are rendered to PNG by PyMuPDF (`ocr_client.render_pdf()`) using multi-threaded page rendering (16 workers), replacing the previous single-threaded `pdftoppm` path.
- High-resolution images (whiteboards, planners, posters) that exceed Gemma 4's vision encoder pixel limit (~2.58M pixels, ~1606x1606) are automatically split into overlapping tiles.
- Tiling logic in `ocr_client.py:tile_large_image()` — 15% overlap between tiles to avoid cutting text/tables at boundaries.
- `pipeline_media.py:_process_file()` calls `tile_large_image()` for each image; if tiling is needed, each tile is sent to the LLM separately and results are concatenated with `\n\n`.
- Images within the pixel limit are processed as-is (no tiling overhead).
- Tiles are generated in left-to-right, top-to-bottom reading order.
- No additional billing: tiling is an internal processing detail; the user is charged per original image, not per tile.
- Key files: `app/backend/core/ocr_client.py` (`tile_large_image`, `fit_image_to_gemma4_resolution`), `app/backend/core/pipeline_media.py` (`_process_file`).

## Docling Service

- **기능 개요**: Docling 전처리 서비스 (a1 CPU 서버) — PDF/이미지/HWP를 마크다운으로 변환, 선택적 LLM 후처리
- **서비스 URL**: `http://docling:28182` (Docker compose 내부 서비스 이름)
- **동적 타임아웃**: 파일 크기(MB) 기반 최소 24시간, `max(86400, file_size_mb * 60)` 초
- **Health check**: `/health` 엔드포인트로 서비스 상태 확인
- **폴링**: 30초 간격으로 `/convert/async` 결과 폴링, `processing` + health OK 시 타임아웃 연장
- **LLM Refinement**: Docling 마크다운를 LLM에 전송해 후처리 (선택적)
  - 최대 20개 이미지를 LLM에 전송 (`docling_max_images_per_doc`)
  - 이미지 최대 긴 변 1920px (`docling_image_max_size`)
  - `build_docling_refinement_prompt`로 프롬프트 생성
- **OCR 백엔드 선택**: `ocr_backend` 설정으로 `docling` 또는 `paddleocr` 선택
- **설정 옵션**:
  - `docling_enabled`: Docling 서비스 활성화/비활성화
  - `docling_service_url`: Docling 서비스 URL
  - `docling_refinement_enabled`: LLM 후처리 기본 활성화
  - `docling_max_images_per_doc`: 문서당 LLM 전송 이미지 상한
  - `docling_image_max_size`: 추출 이미지 최대 긴 변 (px)
- **Key files**: `app/backend/core/docling_client.py`, `app/backend/core/pipeline_docling.py`

## Supabase Proxy

- FastAPI reverse proxy at `/supabase/*` routes to internal Supabase (`192.168.1.50:28000`)
- Frontend uses `window.location.origin + '/supabase'` as Supabase URL (no hardcoded IPs)
- Signed download URLs are rewritten from internal to external proxied URLs in `supabase_client.py`
- Proxy implementation: `app/backend/api/supabase_proxy.py`

## Public URL & Email Confirmation

- All externally visible URLs must use the public domain (`https://proof.teamcat.app`), never internal IPs.
- `app/backend/config.py` defaults `public_base_url` to `https://proof.teamcat.app` and `supabase_public_url` to `https://proof.teamcat.app/supabase` so that missing `.env` values do not leak internal addresses.
- In `app/.env` (and on the server):
  - `PUBLIC_BASE_URL=https://proof.teamcat.app` (used by `email_sender.py` for download links)
  - `SUPABASE_PUBLIC_URL=https://proof.teamcat.app/supabase` (used by `supabase_client.py` to rewrite signed Storage URLs)
- For self-hosted Supabase (`/opt/supabase-chungu/.env` on `a1`):
  - `SITE_URL=https://proof.teamcat.app`
  - `ADDITIONAL_REDIRECT_URLS=https://proof.teamcat.app/**`
  - `MAILER_URLPATHS_CONFIRMATION="/supabase/auth/v1/verify"`
  - `MAILER_URLPATHS_INVITE="/supabase/auth/v1/verify"`
  - `MAILER_URLPATHS_RECOVERY="/supabase/auth/v1/verify"`
  - `MAILER_URLPATHS_EMAIL_CHANGE="/supabase/auth/v1/verify"`
- With this setup, Supabase Auth emails generate links like `https://proof.teamcat.app/supabase/auth/v1/verify?token=...&type=signup`, which are proxied by FastAPI's `/supabase/*` route to the internal Supabase Auth service (`192.168.1.50:28000`).
- Internal IPs (`192.168.1.x`, `localhost`, `127.0.0.1`) are reserved for backend-only services: LLM endpoints, Docling service, and the internal `SUPABASE_URL`.

## Email System

### Supabase Auth Emails (English Fixed)

- GoTrue는 단일 템플릿만 지원하므로 인증 메일은 **영어 고정**.
- 템플릿 파일: `/opt/supabase-chungu/volumes/templates/confirmation.html` (서버)
- docker-compose.yml에 `GOTRUE_MAILER_TEMPLATES_CONFIRMATION`, `GOTRUE_MAILER_SUBJECTS_CONFIRMATION` 환경변수 및 volume 마운트 추가.
- 회원가입 시 프론트엔드(`AuthPage.jsx`)에서 스팸 폴더 확인 안내 표시 (`signupSuccessTitle`, `signupSuccessBody`, `signupSpamNotice` i18n 키).

### App Emails (Multi-language: ko/en/ja)

- **완료 메일** (`build_done_email`): 사용자 프로필 언어에 따라 DOCX 다운로드 버튼 + 결과 페이지 링크(`/jobs/{jobId}`) 포함. 결과 페이지에서 엑셀 다운로드 및 고급변환 가능 안내.
- **실패 메일** (`build_error_email`): 사용자 프로필 언어에 따라 에러 내용 통지.
- 언어 조회: `tasks.py`에서 `job.user_id` → `User.language` 조회 후 `lang` 파라미터로 전달. 비회원(`user_id == None`)은 기본값 `"en"`.
- 다운로드 링크: `/api/dl/{token}?type=docx` — auth 없이 `download_token`으로 302 redirect (이메일 버튼용). DOCX 파일이 아직 생성되지 않은 경우 on-demand 변환(`_generate_office_on_demand`) 후 redirect.
- XLSX 다운로드는 이메일에서 제외: 결과 페이지(`/jobs/{jobId}`)에서 인증 후 다운로드 가능.
- Key files:
  - `app/backend/email_sender.py` — `_DONE_T`, `_ERROR_T` 다국어 딕셔너리, `build_done_email`, `build_error_email`
  - `app/backend/workers/tasks.py` — `_handle_job_failure`, `run_job` Step 7에서 언어 조회 후 이메일 발송
  - `app/backend/api/jobs.py` — `/api/dl/{token}` redirect 엔드포인트

## Model Selection UI

- `JobConfirmPage.jsx`에서 OCR 엔진 선택 및 고급 옵션 UI 제거 — "기본 모델"과 "고급 모델" 두 가지 선택지만 제공.
- 기본 모델: 대량의 스캔된 PDF에 최적화된 빠른 OCR 및 데이터 변환 (1P/페이지, 매일 100페이지 무료).
- 고급 모델: high performance AI 비전 모델 (모든 페이지 정밀 분석, 비전 AI 에이전트 교차 검증 복원, 오디오/비디오/이미지 변환 지원, 5P/페이지).
- 오디오/비디오 파일이 포함된 경우 기본 모델 비활성화, 고급 모델 강제.
- i18n 키: `basicFeature1-3`, `premiumFeature1-3` (ko/en/ja).

## Price & Payment Page

- **PricePage** (`app/frontend/src/pages/PricePage.jsx`): 카드형 디자인으로 파일 형식(MD, CSV, XLSX, DOCX)과 모델(기본/고급)을 아이콘과 함께 표시.
  - 파일 형식 카드: 고정 너비, `flex-wrap` 배치, PowerPoint 제외.
  - 모델 카드: 기능 목록 중앙 정렬, 고급 모델에 "추천" 배지.
  - 크레딧 구매 카드: 단가($1.00/credit), 최소 충전액($5.00), 예시 금액 표시.
  - i18n 키: `creditTitle`, `creditDesc`, `creditProduct`, `creditUnitPrice`, `creditMinimum`, `creditExamples`, `mostPopular` (ko/en/ja).
- **PaymentPage** (`app/frontend/src/pages/PaymentPage.jsx`): 충전 금액 입력 위에 단가/최소 금액 안내 추가. 결제 동의 안내는 크레딧 충전 카드 내부 오른쪽에 배치. 환불 안내 문구에 `/refund-policy` 링크 추가.
- **세금 안내**: `taxNotice` i18n 키를 "세금은 결제 시 별도로 계산되어 추가될 수 있습니다"로 변경 (ko/en/ja).

## Global Footer

- **GlobalFooter** (`app/frontend/src/components/GlobalFooter.jsx`): 모든 페이지에서 공통으로 사용하는 글로벌 푸터 컴포넌트. 저작권, 서비스 이용약관, 개인정보처리방침, 환불 정책, API 문서, 관리자 링크 포함.
- 푸터가 있는 페이지: UploadPage, PricePage, PaymentPage, OnPremisePage, LegalTermsPage, LegalPrivacyPage, LegalRefundPage, SidebarLayout 사용 페이지 (Dashboard, Developer, Jobs, Settings).
- 푸터가 없는 페이지 (의도적): AuthPage, AdminLogin, AdminDashboard, JobConfirmPage, JobResultPage.
- UploadPage는 기존 인라인 푸터를 `GlobalFooter` 컴포넌트로 교체.

## Logout Fix

- `SidebarLayout.jsx`: `signOut()` 후 `navigate("/")`로 랜딩 페이지 이동. (기존 `signOut()`만 호출하면 `onAuthStateChange`로 인한 재렌더링이 `DashboardPage`의 `!user && !error` 로딩 조건을 만족시켜 무한 스피너가 표시됨)
- `DashboardPage.jsx`: 로딩 조건을 `if (authLoading)`로 단순화 — 로그아웃 후 `user == null`일 때 무한 로딩 스피너 방지.

## Cloudflare Turnstile CAPTCHA

- 백엔드에서 Worker를 통해 Turnstile 토큰을 검증. secret key는 Cloudflare Worker secret(`TURNSTILE_SECRET_KEY`)으로만 보관하고, 애플리케이션 서버에는 저장하지 않음.
- Worker URL: `https://turnstile-siteverify-proof.mtgmtg.workers.dev`
- Widget site key: `0x4AAAAAADux9LO13vEhA4F7`
- 프론트엔드는 Turnstile 위젯으로 토큰만 수집하고, Worker 직접 검증은 하지 않음. **Turnstile 토큰은 1회용**이므로 프론트엔드와 백엔드에서 이중 검증하면 두 번째 검증이 실패함.
- Supabase JS 클라이언트는 `turnstile_token` 대신 `options.captchaToken`을 받아 요청 본문의 `gotrue_meta_security.captcha_token`으로 전송. 백엔드 `supabase_proxy.py`는 이 필드를 추출하여 Worker로 검증.
- 로그인/회원가입/관리자 로그인 시 백엔드가 토큰을 검증. 실패 시 `403` 응답과 `"bot 확인에 실패했습니다. 다시 시도하세요."` 메시지 반환.
- Widget 도메인: `localhost`, `127.0.0.1`, `proof.teamcat.app`
- Key files:
  - `app/backend/core/turnstile.py` — Worker 경유 토큰 검증
  - `app/backend/api/supabase_proxy.py` — `/supabase/auth/v1/token` 요청 시 Turnstile 검증
  - `app/backend/api/admin.py` — 관리자 로그인 Turnstile 검증
  - `app/frontend/src/pages/AuthPage.jsx` — Turnstile 위젯, 토큰 수집
  - `app/frontend/src/pages/AdminLogin.jsx` — Turnstile 위젯, 토큰 수집
  - `app/backend/config.py` — `turnstile_site_key`, `turnstile_worker_url` 설정
  - `app/.env.example` — 환경변수 예시
  - `app/Dockerfile.backend` — `VITE_TURNSTILE_SITE_KEY`, `VITE_TURNSTILE_WORKER_URL` build args
  - `app/docker-compose.yml` — build args 전달

## PDF Viewer & Markdown Editor Optimization

- **PdfViewer** (`app/frontend/src/components/PdfViewer.jsx`):
  - 브라우저 네이티브 PDF 뷰어를 `<iframe src="{pdf_url}#page={page}" />`로 표시한다. Chrome PDFium, Safari PDFKit 등 브라우저의 네이티브 엔진이 렌더링하므로 100페이지 이상 대용량 PDF도 빠르게 표시된다.
  - 툴바에서 이전/다음 페이지, 페이지 번호 직접 입력으로 이동할 수 있다. 입력한 페이지 번호는 `#page` URL 프래그먼트로 iframe에 전달된다.
  - Markdown 미리보기와의 동기화는 **툴바로 페이지 이동할 때만** `onPageChange` 콜백을 통해 이루어진다. iframe 내부에서 사용자가 스크롤하거나 네이티브 뷰어의 페이지 컨트롤을 사용하면 부모에게 이벤트가 전달되지 않아 양방향 동기화는 불가능하다.
  - PDF.js, 캔버스 렌더링, 썸네일 패널은 사용하지 않는다.
- **Preview Backend Optimization** (`app/backend/core/pdf_preview_converter.py`, `app/backend/api/jobs.py`, `app/backend/core/supabase_client.py`):
  - DOCX/HWP 미리보기 PDF를 생성할 때 PyMuPDF로 `linear=True` 선형화를 적용하여 브라우저가 첫 페이지 바이트만 받아도 렌더링할 수 있게 한다.
  - 10MB 이상 또는 50페이지 이상인 PDF/DOCX/HWP에 대해 `preview_pdfs_lowres/` 아래에 100 DPI 저해상도 미리보기 PDF를 별도 생성한다. 용량은 줄지만 텍스트 레이어는 사라진다.
  - 저화질/선형화 생성 중 오류가 발생하면 원본 PDF의 서명 URL로 폴백하여 프리뷰 패널이 blank 되지 않도록 한다.
  - `/api/jobs/{id}/preview` 응답을 Redis에 `preview:{job_id}:{start_page}:{end_page}` 키로 5분 TTL 캐싱한다. `save_result_markdown` / `save_result_page`에서 `preview:{job_id}:*` 패턴으로 캐시를 무효화한다.
  - `_source_files()`에서 `concurrent.futures.ThreadPoolExecutor(max_workers=3)`로 여러 파일의 signed URL 생성을 병렬화한다. 스레드당 `create_fresh_service_client()`로 새로운 Supabase 클라이언트를 생성하여 스레드 안전을 확보한다.
- **MarkdownPreview** (`app/frontend/src/components/MarkdownPreview.jsx`):
  - 읽기 전용 마크다운 뷰어. `marked.parse`로 HTML 렌더링 후 `dangerouslySetInnerHTML` 사용 (백엔드 신뢰 출력, DOMPurify 미사용).
  - `<!-- 페이지 N -->` 마커 기준으로 마크다운을 페이지 섹션으로 분할.
  - `content-visibility: auto` + `containIntrinsicHeight`로 화면 외 섹션 렌더링 스킵 (가상화).
  - `IntersectionObserver`로 가시 페이지 추적.
  - `scrollToPage(pageNum)` imperative API로 PDF 페이지 이동 시 해당 섹션으로 스무스 스크롤.
  - `React.memo` 적용.
  - **방어 로직**: 첫 페이지는 초기부터 `visible`로 설정, `markdown` 변경 시 `visiblePages` 초기화. 페이지 수가 10개 이하일 때는 `content-visibility` 가상화를 비활성화하여 브라우저별 렌더링 차이/blank 현상을 방지.
- **SimpleEditor** (`app/frontend/src/components/SimpleEditor.jsx`):
  - Tiptap 기반 편집 가능 마크다운 에디터.
  - `PageMarkerNode` 커스텀 Tiptap 노드: `<!-- 페이지 N -->` 마커를 `div[data-page-marker]`로 변환하여 ProseMirror 스키마에 등록. 기본 스키마에 없는 div가 `setContent` 시 제거되는 문제 해결.
  - `turndown` 규칙: 저장 시 `div[data-page-marker]`를 다시 `<!-- 페이지 N -->` 마커로 역변환 (round-trip 보존).
  - `scrollToPage(pageNum)` imperative API로 PDF 페이지 이동 시 해당 마커로 스크롤.
  - `React.memo` 적용.
- **PagedResultViewer** (`app/frontend/src/components/PagedResultViewer.jsx`):
  - 100페이지 초과 작업용 페이지별 뷰어. `api.previewJob(jobId, pageNum, pageNum)`으로 단일 페이지 로드.
  - 보기 모드(`MarkdownPreview`)와 편집 모드(`SimpleEditor`) 토글 지원. **기본 모드는 편집 모드**.
  - `React.memo` 적용.
- **JobResultPage** (`app/frontend/src/pages/JobResultPage.jsx`):
  - `editMode` state로 보기/편집 모드 전환. **초기값은 `true`로 편집 모드로 진입**. 보기 모드: `MarkdownPreview`, 편집 모드: `SimpleEditor`.
  - `currentPdfPage` 변경 시 에디터/프리뷰에 `scrollToPage` 호출하여 원본-결과 동기 스크롤.
  - `loadPreview()`에서 `preview.last_page > PAGE_THRESHOLD` 폴백 체크: DB의 `total_pages`가 잘못되어도 마크다운의 실제 페이지 수로 페이징 모드 전환.
  - `loadPreview()` **대형 작업 최적화**: `needsPagedMode(job)`(100페이지 초과)로 미리 판단된 작업은 전체 마크다운을 받아오지 않고 `api.previewJob(jobId, 1, 1)`로 첫 페이지 메타/소스 정보만 획득. 이후 `PagedResultViewer`가 페이지별로 개별 로드하여 300페이지 이상 문서에서 스켈레톤 화면이 멈추는 문제를 방지.
  - `saveMarkdown()`는 `pages.length > 0`으로 페이징 모드 판단 (DB 값 의존 제거).
  - `MarkdownViewToolbar`로 보기/편집 토글 UI 제공.
  - i18n 키: `editMode`, `viewMode`, `edit`, `view` (ko/en/ja).
  - **방어 로직**: 다중 파일 작업에서 `source_files[i].result_markdown`이 비어 있을 경우 전체 결합 마크다운로 폴백하여 빈 화면 방지.
- **total_pages 보정** (`app/backend/workers/tasks.py`):
  - 워커 처리 후 `total_pages`를 `len(page_tables)`로 덮어쓰지 않고 `max(job.total_pages, len(page_tables))`로 업로드 시점 페이지 수 보존. 빈 페이지로 인해 `total_pages`가 감소하는 것 방지.
  - 멀티미디어/이미지 작업 완료 후 `total_pages`/`done_pages` 설정 추가 (기존에는 0으로 유지됨).
- **CSS** (`app/frontend/src/index.css`):
  - `.markdown-page-section`: 페이지 섹션 구분선 스타일.
  - `.page-marker`: Tiptap 페이지 마커 div (`pointer-events: none`).
- 페이지 마커 형식: `<!-- 페이지 N -->` (백엔드 `converter.build_layout_markdown_string()`에서 생성).

## Deployment

Docker 이미지 빌드는 **a1 서버에서 수행**한다. 로컬에서 Docker 빌드를 하지 않는다.

```bash
bash deploy_a1.sh
```

이 스크립트는 다음을 수행한다:

1. LAN(a1) 또는 WAN(wan-1)으로 SSH 연결
2. `rsync`로 로컬 `app/` 디렉토리를 서버 `~/chungu-app/`에 동기화 (`.env` 제외)
3. 서버에서 `docker compose down && docker compose up --build -d` 실행 (이미지 빌드 + 컨테이너 재시작)
4. 컨테이너 상태 확인

서버 `.env`는 rsync로 덮어쓰지 않으므로 수동으로 관리해야 한다.
DB 마이그레이션 SQL 파일은 배포 후 서버에서 수동으로 적용한다 (실제 DB 컨테이너명은 `supabase-chungu-db`, DB명은 `postgres`):

```bash
cat app/backend/db/migrations/020_add_pdf_annotate_fields.sql | ssh a1 'docker exec -i supabase-chungu-db psql -U postgres -d postgres'
```

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

## Docling Service Details

- **서버 환경**: Xeon Scalable CPU 서버 (a1 GPU 아님), CPU PyTorch + Intel Extension for PyTorch (IPEX) for VNNI/OneDNN acceleration
- **OCR 엔진 선택**: `OCR_ENGINE=tesseract` (기본값) 또는 `OCR_ENGINE=easyocr` 설정. `OCR_LANG=ko+en+ja`로 Tesseract 언어 팩 제어
- **Tesseract 5.5.1**: Xeon 6230 듀얼 소켓 속도 최적화. `ppa:alex-p/tesseract-ocr5` PPA 사용. 컨테이너 내 `tesseract -v`로 `Found AVX512VNNI`, `Found AVX512F`, `Found AVX2`, `Found OpenMP` 확인
- **EasyOCR**: 회전/노이즈 스캔에 더 좋지만 느림. Tesseract는 깨끗한 deskewed 스캔에 최적
- **HWP/HWPX 지원**: `run_hwp`가 pyhwp의 `hwp5odt`로 ODT 변환 → LibreOffice headless로 DOCX 변환 → Docling 서비스 전송. pyhwp2md/hwp5odt가 일부 다중 페이지 HWP 파일의 첫 페이지만 추출하는 문제 회피. LibreOffice 또는 Docling 실패 시 기존 pyhwp 기반 변환기로 폴백
- **Threading**: `torch.set_num_threads(2)` (요청당 2 스레드), `AcceleratorOptions(num_threads=80)` (총 80 스레드 = Xeon 6230 듀얼 소켓에서 40 동시 요청). OpenVINO `INFERENCE_NUM_THREADS=2`
- **Celery worker concurrency**: 16 (prefork)
- **Backend `docling_max_workers`**: 16 동시 Docling 요청
- **NUMA binding**: 컨테이너 시작 시 `numactl --cpunodebind=0 --membind=0` 사용. 듀얼 소켓 6230의 경우 최대 처리량을 위해 각 NUMA 노드에 바인딩된 두 개의 독립 worker 실행
- **Model quantization** (`_apply_ipex` warm-up 후 적용):
  - **RTDetrV2 (layout)**: OpenVINO NNCF INT8 quantization with `torch.jit.trace` → `ov.convert_model` → `nncf.quantize`. 디스크 캐시 `/data/ov_cache/`. `INFERENCE_NUM_THREADS=2`로 컴파일
- **Key files**:
  - `app/backend/docling_service/main.py` — CPU accelerator, model quantization, IPEX warm-up이 있는 FastAPI 서비스
  - `app/backend/docling_service/Dockerfile` — Ubuntu 22.04 + CPU PyTorch + IPEX + Tesseract language packs
  - `app/backend/docling_service/requirements.txt` — Docling/FastAPI deps (torch GPU 없음). `openvino>=2024.0` 및 `nncf>=3.0` 포함
  - `app/backend/docling_service/benchmark_ocr.py` — EasyOCR vs Tesseract A/B benchmark 도구
  - `app/docker-compose.docling.yml` — GPU 예약 없는 Compose
  - `app/backend/core/docling_client.py` — Docling 서비스용 a1 backend 클라이언트
  - `app/backend/core/pipeline_docling.py` — Docling markdown + 선택적 LLM refinement
  - `app/backend/core/hwp_converter.py` — pyhwp 기반 HWP/HWPX text/image/page extraction
  - **EfficientViT (detection)**: `torch.quantization.quantize_dynamic` (Linear INT8). OpenVINO conversion hangs due to dynamic control flow in forward.
  - **TableModel04_rs (table structure)**: `torch.quantization.quantize_dynamic` (Linear INT8). Discovered via `table_model.tf_predictor._model`.
  - **OCR model**: kept in FP32 to preserve recognition quality.
- `torch.autocast` patched to CPU float32 to avoid slow bfloat16 emulation on CPU.
- Batch sizes: Docling defaults (no custom env vars).
- Refinement costs: `cost_per_docling_refinement_page_krw` / `cost_per_docling_refinement_page_usd` in `settings_store`.
- Docs: `app/docs/docs/docling.md` and `app/docs/docs/hwp.md` (HWP Phase 2).

## PaddleOCR Fallback (AI Studio API)

- PaddleOCR AI Studio API (`https://paddleocr.aistudio-app.com/api/v2/ocr/jobs`)를 폴백 OCR 백엔드로 사용한다.
- AI Studio API는 **이미지 파일만** 지원한다 (png/jpg/bmp/tiff/webp). PDF, 오피스 문서, HWP/HWPX는 직접 전송하지 않는다.
- 폴백 대상:
  - **Vision 파이프라인** (`pipeline_vision.py`): PDF 페이지를 PNG로 렌더링 후, 모든 페이지를 PaddleOCR 우선 처리. 개별 페이지 텍스트 레이어 검사 없음.
  - **Media 파이프라인** (`pipeline_media.py`): 이미지 파일만 폴백 (비디오/오디오 제외).
  - **Docling 파이프라인** (`pipeline_docling.py`): 폴백 안 함 (이미지가 아닌 문서).
- 폴백 우선 조건 (`paddleocr_fallback.py:is_fallback_preferred()`):
  - `paddleocr_fallback_enabled == True`이면 항상 `True` 반환 — 모든 변환 요청이 PaddleOCR을 우선 사용 (임시 정책)
- 회로 차단기 (Circuit Breaker):
  - 60초 내 3회 실패 → OPEN (600초)
  - OPEN 경과 후 → HALF_OPEN → 성공 시 CLOSED 복귀
  - `can_use_fallback()`: fallback_enabled AND 회로 차단기가 OPEN이 아님
  - 한도 은행(Limit Bank) 시스템은 제거됨 — 사용량 제한 없음
- `paddleocr_service/main.py`의 `/api/convert` 엔드포인트는 이미지 확장자만 허용하며, AI Studio API에 비동기 job을 제출하고 폴링으로 결과를 수신한다.
- PaddleOCR 결과에 포함된 이미지는 **base64 data URI**로 markdown에 직접 삽입된다 (컨테이너 내부 경로 의존성 제거, 프론트엔드에서 직접 표시 가능).
- `paddleocr_client.py`는 `convert_file()` (docling_client 호환 시그니처) 및 `convert_image()` (경량 이미지 전용) 함수를 제공한다.
- Key files:
  - `app/backend/core/paddleocr_fallback.py` — 회로 차단기 + `is_fallback_preferred()`
  - `app/backend/core/paddleocr_client.py` — AI Studio API 클라이언트 (이미지 확장자 체크)
  - `app/backend/paddleocr_service/main.py` — AI Studio API 프록시 서비스 (`/api/convert`)
  - `app/backend/paddleocr_service/Dockerfile` — AI Studio API 프록시용 컨테이너
  - `app/backend/core/pipeline_vision.py` — PaddleOCR 우선 + vLLM fallback
  - `app/backend/core/pipeline_media.py` — 이미지 전용 폴백
  - `app/backend/core/ocr_client.py` — `has_pdf_text_layer()` PDF 텍스트 레이어 검사
  - `app/backend/workers/tasks.py` — PDF 라우팅 분기 (기본변환: 텍스트 레이어 → Docling / 스캔 → run_vision / 고급변환: 무조건 run_vision)
- Docker Compose: `paddleocr_service` 서비스 정의, worker/beat에 `PADDLEOCR_SERVICE_URL` 환경변수 전달.
- 환경변수: `PADDLEOCR_API_TOKEN`, `PADDLEOCR_API_URL`, `PADDLEOCR_SERVICE_URL`, `PADDLEOCR_FALLBACK_ENABLED`, `PADDLEOCR_FALLBACK_FAILURE_THRESHOLD`, `PADDLEOCR_FALLBACK_OPEN_SECONDS` 등.

## PaddleOCR Auto Parameter Recommendation

- 사용자가 기술 용어를 몰라도, 업로드된 문서의 샘플 페이지를 Vision LLM이 보고 PaddleOCR-VL 최적 파라미터를 자동으로 결정한다.
- 샘플링: PDF/오피스 문서의 전체 페이지 수 기준 `ceil(total_pages × 0.01)` 장, **최소 1장, 최대 3장**.
  - 1장일 때는 중간 페이지, 2장일 때는 첫/마지막 페이지, 3장일 때는 첫/중간/마지막 페이지를 선택하여 문서 전체 구조를 대표한다.
- Vision LLM은 문서 유형(receipt/invoice/form/paper/table_heavy/image_heavy/business_card/report/mixed)을 판단하고, 아래 파라미터를 JSON으로 추천한다:
  - `layout_threshold`, `layout_merge_bboxes_mode` (`large`/`small`/`union`), `layout_unclip_ratio`, `layout_nms`
  - `use_doc_orientation_classify`, `use_doc_unwarping`, `use_layout_detection`, `use_ocr_for_image_block`, `format_block_content`
  - `use_chart_recognition`, `use_seal_recognition`
- 추천값은 범위를 벗어나면 clamping되고, JSON 파싱/추천 실패 시 `mixed` 문서 유형 프리셋으로 안전하게 fallback한다.
- 적용 범위:
  - `paddleocr_service/main.py`의 로컬 PaddleOCRVL 파이프라인 (`predict()`에 동적 파라미터 전달)
  - AI Studio API 폴백 (`/api/convert`)의 `optionalPayload`에 동일 파라미터를 camelCase로 변환하여 전달
- 설정 옵션:
  - `paddleocr_auto_parameter_enabled`: 자동 파라미터 추천 활성화/비활성화
  - `paddleocr_sample_dpi`: 샘플링 DPI (기본값 150)
  - `paddleocr_sample_max_tokens`: 샘플링 최대 토큰 (기본값 2000)
- Key files: `app/backend/core/paddleocr_parameter_recommender.py`
- 환경변수:
  - `PADDLEOCR_AUTO_PARAMETER_ENABLED=true` — 자동 추천 On/Off
  - `PADDLEOCR_SAMPLE_DPI=150` — 샘플 페이지 렌더링 해상도 (비용 절감)
  - `PADDLEOCR_SAMPLE_MAX_TOKENS=2000` — 추천 LLM 응답 길이 제한
- Key files:
  - `app/backend/core/paddleocr_parameter_recommender.py` — 샘플 추출, LLM 추천, 파라미터 검증/프리셋
  - `app/backend/core/prompts.py` — `build_paddleocr_parameter_recommendation_prompt()`
  - `app/backend/paddleocr_service/main.py` — `_get_paddleocr_params()`, `_run_paddleocr()`, AI Studio API payload 변환
  - `app/backend/paddleocr_service/Dockerfile`, `Dockerfile.pipeline` — `Pillow`/`ImageMagick` 및 `backend/core/*` 복사

## PDF Highlight & Margin Annotation (하이라이트/여백 주석)

- **기능 개요**: 원본 스캔 PDF의 표에서 자연어 조건(예: "80만원 이상 이체된 줄")에 맞는 행을 찾아 **형광펜 하이라이트**와/또는 **여백 코멘트 주석**을 추가해 다운로드할 수 있는 기능. 변호사 등 법률 실무에서 스캔 문서를 그대로 제출용으로 표시해야 하는 요구에서 시작됨.
- **처리 흐름**:
  1. 원본 PDF를 DPI 200으로 재렌더링
  2. PaddleOCR-VL(AI Studio 유료 API, 현재 사용 중)로 페이지별 bbox 원본(layout) 확보
  3. 표의 행을 텍스트로만 LLM(vLLM Gemma-4)에 전달해 조건에 맞는 행 선택 (좌표 추론은 LLM에 절대 맡기지 않음 — grounding 신뢰도가 낮다는 리서치 결과 반영)
  4. 선택된 행의 bbox를 PDF 좌표로 변환
  5. PyMuPDF로 원본 PDF에 주석 적용
  6. Storage 업로드
- **사용자 인터페이스**: 결과 페이지(JobResultPage)의 "PDF 하이라이트/주석" 버튼 → 지시문 입력(예: "출금금액이 1000만원 이상인 거래 행") + 표시방식(`highlight`/`margin_note`/`both`) + 여백 코멘트 방식(`user_text`/`llm_summary`) 선택 → Celery 비동기 처리 (xlsx_advanced와 동일한 구독 사용량 예약/환불/재시도 패턴)
- **PaddleOCR-VL 1.6 실제 원본 스키마** (a1 프로덕션에서 실측, 사전 조사했던 PP-StructureV3 계열 `table_res_list`/`cell_box_list` 스키마와는 다름에 주의):
  - `{"width": px, "height": px, "layout_det_res": {...}, "parsing_res_list": [{"block_label": "table"|"text"|"title"|"seal"|..., "block_content": "<table>...</table>" (표는 HTML 문자열), "block_bbox": [xmin,ymin,xmax,ymax], ...}]}`
  - 표는 **블록 전체 bbox만 있고 행/셀 단위 bbox가 없다** — `core/ocr_layout.py`가 `block_content`의 HTML을 `lxml`로 파싱하고, `block_bbox`를 `<tr>` 개수만큼 세로로 균등 분할해 각 행의 근사 bbox를 만든다.
  - AI Studio API(`layoutParsingResults[].prunedResult`)와 로컬 PaddleOCR-VL 파이프라인(`res.json`)은 `input_path`/`page_index` 차이만 있고 스키마가 동일하므로, 로컬 서버로 전환해도 `core/ocr_layout.py`는 수정할 필요가 없다 — `core/paddleocr_client.py`의 `convert_image_with_layout()` 내부 호출 엔드포인트만 교체하면 됨.
- **PDF 좌표 변환 시 주의 (실측으로 발견한 함정들)**:
  - `use_doc_orientation_classify`/`use_doc_unwarping`이 켜지면 bbox가 "보정된 이미지" 기준으로 나와 원본 좌표와 어긋난다 — AI Studio 잡 제출 시(`_aistudio_submit_job`) 항상 `False`로 고정 전송.
  - `/Rotate 90/180/270`이 걸린 PDF는 OCR bbox(시각적/렌더링 좌표)와 PyMuPDF 주석 API가 기대하는 좌표계가 다르다 — `page.derotation_matrix`로 변환 필요.
  - PyMuPDF의 주석/텍스트 삽입 좌표는 **PDF 절대좌표가 아니라 "현재 mediabox의 좌하단(x0,y0)을 원점으로 하는 로컬 좌표"**다. 여백 확보를 위해 mediabox를 리사이즈하면서 원점(x0,y0)이 이동하면(회전 각도에 따라 특정 방향 패딩만으로도 이동할 수 있음) 좌표가 어긋난다 — 원점 이동량을 기록해 모든 배치 좌표에서 보정해야 한다.
  - 텍스트 레이어 없는 스캔본에서 `add_highlight_annot()`에 raw bbox를 넣으면 MuPDF가 사각형이 아닌 타원형 브러시로 그린다 — `add_rect_annot()`(Square 주석) + 반투명 채우기로 대체.
  - 여백은 **오른쪽에만** 추가한다 (상하좌우 전체 확장은 회전된 페이지에서 원점 이동/정렬 붕괴 사례가 실측되어 제외). 필요한 세로 길이는 쌓일 주석 개수에 따라 미리 계산해서 겹치지 않을 만큼만 확장한다.
- 여백 코멘트 박스는 서로 겹치지 않도록 세로 위치를 순서대로 밀어내며 배치하고(`_layout_margin_notes`), 원래 행 위치와 배치된 박스 위치가 달라지면 꺾이는 연결선(callout)으로 이어준다.
- LLM 행 선택 프롬프트(`build_row_highlight_prompt`)는 여러 표/페이지의 헤더 컬럼명을 정확히 매칭하도록 명시 — 실측 중 "출금금액" 조건인데 "입금금액" 컬럼 값을 잘못 매칭하는 오탐이 발견되어 보강함. 완전한 정확도는 보장되지 않으므로 결과 검토가 필요하다.
- DB 필드: `Job.annotate_instruction/annotate_mode/annotate_comment_mode/annotate_status/annotate_job_id/annotate_recovery_notes/annotate_refundable/annotate_reserved_pages/annotate_reserved_period_start`, `result_ocr_layout_storage_path`, `result_annotated_pdf_storage_path` (`020_add_pdf_annotate_fields.sql`).
- Key files:
  - `app/backend/core/ocr_layout.py` — PaddleOCR-VL `parsing_res_list` → `PageLayout`/`OcrTable`/`OcrRow` 정규화 (HTML 표 파싱 + 행 bbox 균등분할 추정)
  - `app/backend/core/pdf_coords.py` — 픽셀 bbox ↔ PDF 포인트 변환, 페이지 경계 clamp
  - `app/backend/core/pdf_annotator.py` — `AnnotationTarget` 기반 하이라이트/여백 주석 렌더링 (회전 보정, 원점 이동 보정, 겹침 방지 배치)
  - `app/backend/core/pdf_annotate_converter.py` — 오케스트레이터 (`run()`): 페이지 렌더링 → OCR bbox 확보 → LLM 행 선택 → 좌표 변환 → 주석 적용 → 업로드
  - `app/backend/core/prompts.py` — `build_row_highlight_prompt()`
  - `app/backend/core/paddleocr_client.py` — `convert_image_with_layout()` (bbox 포함 변환), `_convert_and_poll()` 공통 폴링
  - `app/backend/paddleocr_service/main.py` — `_extract_layout_from_result()`, `ConvertResponse.layout` 필드, AI Studio `prunedResult` 전달
  - `app/backend/workers/tasks.py` — `annotate_pdf_job` Celery task
  - `app/backend/api/jobs.py` — `POST /jobs/{id}/annotate`, `POST /jobs/{id}/annotate-action` (xlsx_advanced와 동일 패턴)
  - `app/frontend/src/pages/JobResultPage.jsx` — 하이라이트/주석 생성 버튼 + 모달 + 상태 폴링
  - `app/frontend/src/api.js` — `annotateJob()`, `annotateAction()`

## OCR Progress Reporting

- `status == "ocr"`일 때 프론트엔드는 `job.done_pages / job.total_pages * 100`으로 퍼센트를 표시한다.
- **시간진행바 (Time Progress Bar)**:

  - 실제 진행률이 늦게 보고될 때 프로그레스 바가 멈춘 것처럼 느껴지는 문제를 해결하기 위해, 경과 시간 기반 추정 진행률을 추가한다.
- **Vision 파이프라인** (`pipeline_vision.py` / `run_vision`):

  - PDF -> PNG 렌더링과 OCR을 겹쳐 실행한다. 페이지가 렌더링되자마자 `ocr_client.render_pdf()`의 `on_page_rendered` 콜백으로 해당 페이지를 OCR executor에 즉시 제출한다.
  - 전체 작업을 2×N 단위로 보고: 각 페이지는 렌더링(1단위) + OCR(1단위). 프로그레스는 `(rendered_count + ocr_done_count) / (2 * total_pages) * 100`으로 계산한다.
  - 렌더링 워커는 `ThreadPoolExecutor`로 최대 64개까지 병렬 처리한다.
- **PagedResultViewer** (`app/frontend/src/components/PagedResultViewer.jsx`):

  - 100페이지 초과 작업의 결과 보기 페이지. 페이지 목록 사이드바와 툴바 페이지네이션을 제거하고, 상단에 저장 버튼만 남긴다.
  - 소스 PDF/문서 뷰어의 내부 페이지 컨트롤만 사용하며, `SourcePanel`과 `SimpleEditor`는 좌우 패널로 유지된다.
- **Docling 파이프라인** (`pipeline_docling.py` / `run_docling`):

  - Docling 서비스는 내부적으로 페이지별 진행률을 제공하지 않으므로, 경과 시간 기반 추정치(0~99%)를 사용하고 완료 시 100%로 설정한다.
- Key files:

  - `app/backend/core/ocr_client.py` — `render_pdf()` 진행률 콜백, `on_page_rendered` 콜백, 64 workers
  - `app/backend/core/pipeline_vision.py` — 렌더링/OCR 스트리밍, 2×N 진행률
  - `app/backend/core/docling_client.py` — Docling 폴링 진행률 추정
  - `app/frontend/src/utils/progress.js` — `getDisplayProgress`, `getTimeProgress`, `getActualProgress`
  - `app/frontend/src/pages/JobsPage.jsx` — 1초 타이머, 데스크톱/모바일 시간진행바 적용
  - `app/frontend/src/pages/JobResultPage.jsx` — `PoetryProgress`에 시간진행바 적용, `PagedResultViewer` 호출
  - `app/frontend/src/components/PagedResultViewer.jsx` — 100페이지 초과 결과 보기 (페이지네이션 제거, 저장 버튼만 유지)
- **PoetryProgress** (`app/frontend/src/components/PoetryProgress.jsx`):

  - 작업 진행 중 로딩 화면에 한국 명시를 표시하며, 30초 간격으로 랜덤하게 시가 교체됩니다.
  - 76편의 시가 수록되어 있으며 (윤동주 21편, 김소월 48편, 기존 7편), 시 데이터는 `ko/page.json`의 `poems` 배열에서 i18n으로 로드됩니다.
  - 같은 시가 연속으로 표시되지 않도록 중복 방지 로직이 포함되어 있습니다.
  - `SLIDE_INTERVAL = 30000` (30초, 기존 10초의 3배).

## GPU OCR Backends (Suspended)

- **Status**: b2 GPU server (RTX 3080) is currently down with boot failures and is scheduled for repair. All GPU OCR backend work is suspended until the server is recovered.
- **PaddleOCR-VL 1.6**: dual-container architecture (vLLM + PaddleOCR Pipeline) was in progress on b2. Files remain in `app/backend/paddleocr_service/` and `app/docker-compose.paddleocr.yml` for resumption after repair.
- **Nemotron-OCR-v2**: Docker-based evaluation was attempted but could not complete due to the b2 outage. The model is Turing/CC-7.5 unsupported by NVIDIA's official docs; evaluation will resume on a compatible GPU if available.
- **Fallback**: production currently uses the CPU-only Docling service with `OCR_ENGINE=easyocr`.

## Internationalization (i18n)

- Frontend uses `react-i18next` with two namespaces: `common` and `page`
- Translation files: `app/frontend/src/locales/{en,ko,ja}/{common,page}.json`
- Language detection: browser language → localStorage (`proof-language`) → Supabase user profile
- Backend persists user language via `PATCH /api/auth/language`
- `LanguageSelector` component in sidebar for manual switching
- `LanguageContext.jsx` provides `useLanguage()` hook for global access
- API docs translated: `app/API.md` (en), `app/API.ko.md` (ko), `app/API.ja.md` (ja)
- Docusaurus docs site supports en/ko/ja via `i18n/{locale}/docusaurus-plugin-content-docs/current/` directories
- Docusaurus docs are served at `/docs/` by FastAPI (`main.py` mounts `docs/build/` as static files)
- Admin pages (`AdminDashboard.jsx`, `AdminLogin.jsx`) are not yet internationalized
- When adding new UI strings, add keys to all three languages and use `t('namespace:key')`

## Subscription Service

- **기능 개요**: 구독 기반 사용량 관리 — 플랜별 월간 한도, 기간별 사용량 추적, 예약/차감/환불
- **플랜별 한도**:
  - `free`: basic_pages=1000, premium_pages=500, media_seconds=150분
  - `pro`: basic_pages=10000, premium_pages=5000, media_seconds=1500분
  - `max`: basic_pages=60000, premium_pages=30000, media_seconds=9000분
- **기간 계산**: 사용자의 `subscription_period_start` 기준 월간 기간, 없으면 달력월 시작일 사용
- **사용량 관리**:
  - `reserve_usage()`: 작업 시작 전 사용량 예약
  - `consume_usage()`: 작업 완료 후 실제 사용량 차감
  - `release_usage()`: 작업 실패 시 예약된 사용량 환불
- **구독 상태**: `is_subscription_active()`로 활성 여부 확인
- **Key files**: `app/backend/core/subscription_service.py`

## API Notes

- Base path: `/api/v1`
- Authentication: `X-API-Key: chu_live_...` or `Authorization: Bearer <key>`
- Billing: points are deducted per page/image/audio/video
- Docs: `/api/v1/docs` (OpenAPI/Swagger)
- Developer portal: `/developer` in the web UI
- Docusaurus docs site: `/docs/` (served by FastAPI from `docs/build/`)

## Office Conversion (DOCX/PPTX) & Excel Basic/Advanced Conversion

- Conversion is handled by `app/backend/core/office_converter.py` (basic) and `app/backend/core/xlsx_advanced_converter.py` (advanced).
- **DOCX**: renders headings, paragraphs with inline formatting (`**bold**`, `*italic*`, `~~strike~~`), bullet/numbered lists, tables, and code blocks. Free of charge.
- **HTML-aware DOCX/PPTX conversion**: PaddleOCR 등 HTML을 반환하는 OCR 엔진의 결과를 DOCX/PPTX로 변환할 때 HTML 태그를 정상적으로 파싱하여 포맷된 문서로 변환한다.
  - `_contains_html()`로 HTML 태그 감지 (`<table>`, `<img>`, `<div>`, `<p>`, `<h1>`~`<h6>` 등).
  - HTML 감지 시 `_html_to_docx()` / `_html_to_pptx()` 경로로 라우팅, 순수 마크다운은 기존 경로 유지.
  - 변환 매핑: `<img src="data:image/...;base64,...">` → 임베디드 이미지, `<table>` → DOCX 표 (Table Grid), `<h1>`~`<h6>` → 제목, `<p>`/`<div>` → 문단, `<ul>`/`<ol>` → 목록, `<b>`/`<i>`/`<strong>` → 인라인 서식, `<!-- 페이지 N -->` → 페이지 브레이크 (DOCX) / 슬라이드 분할 (PPTX).
  - 단독 HTML 요소(`<table>`만 입력 등) 처리를 위해 `<html><body>` 래핑 후 lxml 파싱.
  - 의존성: `lxml.html` (HTML 파싱), `Pillow` (base64 이미지 디코딩), `python-docx` (DOCX 생성), `python-pptx` (PPTX 생성).
  - 단위 테스트: `app/backend/tests/test_office_converter.py` (18개 테스트 — HTML 감지, HTML→DOCX 변환, 순수 마크다운 회귀, HTML→PPTX 변환).
- **PPTX**: removed from the UI. Backend code remains but no button is exposed.
- **Excel Basic** (`xlsx_basic` / `csv_basic`):
  - `_parse_markdown_tables()` extracts markdown tables → `_merge_tables()` merges consecutive tables with identical headers → `_normalize_rows()` pads all rows to the same column count.
  - `markdown_to_csv_basic()` writes a single CSV file with all merged tables.
  - `markdown_to_xlsx_basic()` writes a single-sheet xlsx with bold headers and auto-width columns.
  - **Pricing**: Excel Basic export is free of charge (`page:price.exportExcelBasicPrice` = "Free" / "무료" / "無料"). CSV Basic is also free.
  - Cost: **1 point/page** (deducted once per bundle — csv + xlsx generated together).
  - Already-converted files are reused (no double charging).
- **Excel Advanced** (`xlsx_advanced`):
  - LLM-based multi-pass conversion via `xlsx_advanced_converter.py` + Celery task `convert_xlsx_advanced`.
  - Pipeline: load markdown → split by pages → extract common column structure from first page (LLM text) → per-page: normalize with LLM text → if invalid, reconstruct with vision LLM (up to 3 retries with evaluation) → merge all tables → write xlsx.
  - Cost: **3 points/page**. On failure, user can retry (no extra charge) or refund.
  - Status tracked via `job.xlsx_advanced_status` (`""` → `"processing"` → `"done"` / `"error"`).
  - Recovery notes (`job.xlsx_advanced_recovery_notes`) record pages where vision reconstruction had issues.
  - `job.xlsx_advanced_refundable` indicates whether the user can request a refund.
  - Retry/refund endpoints: `/api/jobs/{id}/xlsx-advanced-action` (web) and `/api/v1/jobs/{id}/xlsx-advanced-action` (API).
- **Frontend**:
  - `JobResultPage.jsx`: Excel dropdown group (CSV Basic, Excel Basic, Excel Advanced) + Office dropdown group (DOCX only). Preview tabs for Markdown / Excel Basic / Excel Advanced using `SpreadsheetEditor.jsx` (Luckysheet-based xlsx editor).
  - `JobsPage.jsx`: `DownloadMenu` shows Markdown (free), CSV Basic, Excel Basic, Excel Advanced, Word (free). Polling includes `xlsx_advanced_status === "processing"` jobs.
  - `ExcelPreview.jsx`: deprecated, replaced by `SpreadsheetEditor.jsx`.
- **DB migration**: `013_add_xlsx_conversion_fields.sql` adds `result_xlsx_basic_storage_path`, `result_xlsx_advanced_storage_path`, `result_xlsx_advanced_job_id`, `xlsx_basic_converted`, `xlsx_advanced_converted`, `xlsx_advanced_status`, `xlsx_advanced_recovery_notes` (JSONB), `xlsx_advanced_refundable` columns.
- **Backward compatibility**: legacy `xlsx`/`csv` format requests are aliased to `xlsx_basic`/`csv_basic` via `_convert_format_alias()`. `result_xlsx_storage_path` is still set for backward compatibility.
- Conversion endpoints: `/api/jobs/{id}/convert` (web) and `/api/v1/jobs/{id}/convert` (API).
- Key files:
  - `app/backend/core/office_converter.py` — `_parse_markdown_tables`, `_merge_tables`, `_normalize_rows`, `markdown_to_csv_basic`, `markdown_to_xlsx_basic`, `_contains_html`, `_html_to_docx`, `_html_to_pptx`
  - `app/backend/tests/test_office_converter.py` — HTML→DOCX/PPTX 변환 및 순수 마크다운 회귀 단위 테스트
  - `app/backend/core/xlsx_advanced_converter.py` — LLM + vision advanced conversion pipeline
  - `app/backend/workers/tasks.py` — `convert_xlsx_advanced` Celery task
  - `app/backend/api/jobs.py` — web convert/download/xlsx-advanced-action endpoints
  - `app/backend/api/v1/jobs.py` — API v1 convert/download/xlsx-advanced-action endpoints
  - `app/frontend/src/pages/JobResultPage.jsx` — Excel/Office button groups, preview tabs
  - `app/frontend/src/pages/JobsPage.jsx` — DownloadMenu with new formats
  - `app/frontend/src/components/SpreadsheetEditor.jsx` — Luckysheet-based xlsx editor (replaces `ExcelPreview.jsx`)
  - `app/frontend/src/components/ExcelPreview.jsx` — deprecated, no longer imported
  - `app/frontend/src/api.js` — `xlsxAdvancedAction`, `saveEditedXlsx`, `editedXlsxUrl` API methods
  - `app/backend/db/migrations/013_add_xlsx_conversion_fields.sql` — DB migration
  - `app/backend/db/migrations/014_add_edited_xlsx_path.sql` — adds `result_edited_xlsx_storage_path` column

## Spreadsheet Editor (Luckysheet)

- Excel Basic / Excel Advanced 미리보기가 읽기 전용 `ExcelPreview.jsx`에서 완전한 스프레드시트 편집기 `SpreadsheetEditor.jsx`로 교체되었다.
- **라이브러리 로드 방식 (UMD 스크립트 태그)**: Vite + ESM 환경에서 CommonJS 기반 Luckysheet를 사용하기 위해, `plugin.js`, `luckysheet.umd.js`, `luckyexcel.umd.js`를 모두 `<script>` 태그로 동적 로드한다. 이는 전역 jQuery를 공유하여 `mousewheel` 플러그인 등이 정상 작동하도록 보장한다.
  - jQuery는 먼저 `import("jquery")`로 로드하여 `window.jQuery` / `window.$`에 노출한다.
  - CSS 3종 (`pluginsCss.css`, `luckysheet.css`, `iconfont.css`)은 `await import()`로 로드한다.
  - `loadScript()` 헬퍼 함수로 Vite `?url` import 경로를 받아 `<script>` 태그를 생성한다.
  - 로드 완료 후 `window.luckysheet`와 `window.LuckyExcel` 전역 객체를 사용한다.
- **Race condition 해결**: `libsLoaded` 상태 플래그로 스크립트 로드 완료 시점과 `downloadUrl` 설정 시점을 동기화한다. 첫 `useEffect`에서 스크립트 로드 완료 시 `setLibsLoaded(true)`, 두 번째 `useEffect`에서 `libsLoaded && downloadUrl` 모두 만족 시 `loadExcel` 호출.
- **컨테이너 스타일**: `position: absolute`, `width: 100%`, `height: 100%` 인라인 스타일로 Luckysheet가 컨테이너 offset을 정상 읽도록 보장한다.
- **툴바 설정**: `showtoolbar: true`만 사용하고 `showtoolbarConfig` 커스텀 설정은 제거한다. 커스텀 설정 시 일부 툴바 버튼이 DOM에 존재하지 않아 `offset().left`가 undefined가 되는 버그(`Cannot read properties of undefined (reading 'left')`)를 방지.
- **luckysheet.create 호출 시점**: `requestAnimationFrame` 2회 중첩으로 DOM 렌더링을 보장한 후 호출한다.
- **LuckyExcel** (`luckyexcel` npm package)로 XLSX 파일을 Luckysheet JSON으로 변환한다. `transformExcelToLucky(file, callback)`에 `File` 객체를 전달한다.
- **SheetJS** (`xlsx` npm package)로 Luckysheet 데이터를 XLSX Blob으로 변환한다. `getAllSheets()` → `luckysheetDataToWorkbook()` → `XLSX.write()` → Blob.
- **편집 기능**: 기본 툴바 (undo/redo, 서식, 글꼴, 정렬, 정렬/필터, 차트, 이미지, 인쇄), 시트 추가/삭제, 줌, 상태 표시줄.
- **서버 저장**: `POST /api/jobs/{job_id}/save-edited-xlsx` — 편집된 XLSX를 Supabase Storage `results` 버킷에 업로드하고 `job.result_edited_xlsx_storage_path`에 경로를 저장한다.
- **편집본 재조회**: `GET /api/jobs/{job_id}/edited-xlsx-url` — 저장된 편집본의 signed URL을 반환한다. `SpreadsheetEditor` 로드 시 편집본이 있으면 원본 대신 편집본을 우선 로드한다. 편집본이 없으면 404가 반환되며 정상 동작이다.
- **로컬 다운로드**: 편집된 데이터를 XLSX Blob으로 생성하여 브라우저에서 직접 다운로드한다.
- **초기화**: 원본(또는 편집본) 데이터로 `luckysheet.create()`를 다시 호출하여 편집 내용을 되돌린다.
- **언마운트/재로드**: `luckysheet.destroy()`를 호출하여 메모리 누수를 방지한다.
- **DB 마이그레이션**: `014_add_edited_xlsx_path.sql`이 `result_edited_xlsx_storage_path` 컬럼을 `jobs` 테이블에 추가한다.
- Key files:
  - `app/frontend/src/components/SpreadsheetEditor.jsx` — Luckysheet 기반 스프레드시트 편집기
  - `app/frontend/src/api.js` — `saveEditedXlsx`, `editedXlsxUrl` API 메서드
  - `app/backend/api/jobs.py` — `save_edited_xlsx`, `get_edited_xlsx_url` 엔드포인트
  - `app/backend/core/supabase_client.py` — `upload_edited_xlsx()` 함수
  - `app/backend/db/models.py` — `result_edited_xlsx_storage_path` 필드
  - `app/backend/db/migrations/014_add_edited_xlsx_path.sql` — DB 마이그레이션
  - `app/frontend/src/pages/JobResultPage.jsx` — Excel Basic/Advanced 탭에서 `SpreadsheetEditor` 렌더링

## DOCX/HWP Preview

- `docx` and `hwp` source files are converted to PDF on the backend using LibreOffice headless.
- The converted PDF is stored in Supabase Storage under the `pdfs` bucket (`preview_pdfs/` prefix) and reused across preview requests.
- The frontend renders the converted PDF with `PdfViewer` (PDF.js), just like native PDFs.
- Preview conversion is a server-side operation; no client-side load is added.
- CJK (Korean/Chinese/Japanese) fonts are installed in the Docker image so that non-Latin characters render correctly:
  - `fonts-noto-cjk`, `fonts-nanum`, `fonts-unfonts-core`, `fonts-noto-color-emoji`
  - `libreoffice-l10n-ko`, `libreoffice-help-ko`, `locales` with `LANG=ko_KR.UTF-8`/`LC_ALL=ko_KR.UTF-8`
- For `.hwp` files, the backend first tries `pyhwp`'s `hwp5odt` to produce an ODT and then converts it to PDF with LibreOffice. If `hwp5odt` is unavailable or fails, it falls back to direct LibreOffice conversion.
- Key files: `app/backend/core/pdf_preview_converter.py`, `app/Dockerfile.backend`, `app/backend/api/jobs.py`, `app/frontend/src/components/SourcePanel.jsx`, `app/frontend/src/components/PdfViewer.jsx`.

## Result Preview & Multi-file Uploads

- Uploading multiple files creates one job; each file's parsing result is stored separately in `extracted_files[].result_markdown`.
- The combined markdown uses file markers (`<!-- 파일 N -->`) via `converter.build_combined_file_markdowns()`.
- `/api/jobs/{id}/preview` returns `source_files` (name, type, url, storage_path, page_num, result_markdown) for each original file. PDF 원본은 signed URL로 브라우저 네이티브 뷰어에 표시된다.
- PDF preview uses an iframe with the browser's native PDF viewer (`PdfViewer`). The toolbar with page navigation is at the top of the preview panel. The preview panel scrolls independently and the page is aligned to the top.
- `SourcePanel` renders a single source when only one exists, and a file list + selected preview when multiple sources exist.
- `SourcePanel` supports controlled selection via `selectedFileIndex` / `onFileSelect` props.
- `JobResultPage` manages `fileMarkdowns` state: when multiple files exist, `SimpleEditor` shows only the selected file's markdown.
- Saving in multi-file mode uses `api.saveResultFileMarkdowns()` (PUT `file_markdowns` array); single-file mode uses `api.saveResultMarkdown()`.
- The `save_result_markdown` backend endpoint accepts `file_markdowns` (array) to update `extracted_files` and rebuild the combined markdown.
- When adding new source media types, update `SourcePanel.jsx` and add i18n keys to `page:result` and `page:components`.

## Upload Page File Management

- Upload page hero title: `page:upload.title` — "수백개 자료도 원클릭 데이터 변환" (ko), "Hundreds of files, one-click data conversion" (en), "数百のファイルもワンクリックでデータ変換" (ja).
- 드래그앤드롭, 파일 선택, 폴더 선택 모두 기존 파일 리스트에 **누적 추가**된다 (이전에는 대체).
- 동일한 이름+크기의 파일은 중복으로 간주하여 **건너뛴다**.
- 파일 입력 `<input>`은 선택 후 `e.target.value = ""`로 초기화하여 같은 파일 재선택이 가능하다.
- 드래그앤드롭 영역이 `<label>`에서 `<div>`로 변경되었으며, `onDragOver`/`onDrop`/`onDragEnter`/`onDragLeave`에 `preventDefault`를 사용해 브라우저 기본 동작을 차단한다.
- `document` capture phase에서 전역 `dragover`/`drop` 기본 동작을 차단하여, drop zone 밖에 떨어뜨려도 브라우저가 파일을 열지 않는다.
- `handleDrop()`에서 파일 아이템은 `item.getAsFile()`로 직접 수집하고, 디렉토리 아이템만 `webkitGetAsEntry()` + `traverseEntry()`로 재귀 처리한다. `dataTransfer.items`가 없으면 `dataTransfer.files`를 fallback로 사용한다.
- `handleDrop()`과 `traverseEntry()`에서 발생하는 예외를 catch하여 전체 페이지가 멈추지 않도록 한다.
- 각 파일 항목에 개별 삭제 버튼(X 아이콘)이 있으며, "취소" 버튼은 전체 리스트 초기화 역할을 유지한다.
- Key file: `app/frontend/src/pages/UploadPage.jsx` — `addFiles()`, `removeFile()`, `handleDrop()`

## GridScan WebGL Fallback

- `GridScan`은 Three.js WebGLRenderer를 사용한 배경 시각 효과 컴포넌트이다.
- WebGL 컨텍스트를 생성할 수 없는 환경(일부 headless 브라우저, WebGL 비활성화 등)에서 전체 페이지가 crash되지 않도록, 렌더러 생성 실패 시 `glFailed` 상태를 설정하고 `null`을 반환한다.
- Key file: `app/frontend/src/components/GridScan.jsx`

## Sidebar Account Navigation

- 사이드바 하단의 "Logged in as" 계정 카드에서 이메일 주소를 클릭하면 `/settings?tab=account`로 이동하여 계정 설정을 열 수 있다.
- 이메일은 `react-router-dom`의 `Link` 컴포넌트로 렌더링되며, 호버 시 primary 색상과 밑줄이 표시된다.
- Key file: `app/frontend/src/components/SidebarLayout.jsx`

## UI/UX Design System

- **Skeleton Loading**: All dynamic data areas use skeleton components (`Skeleton`, `SkeletonCard`, `SkeletonTable`, `SkeletonPageResult`) from `app/frontend/src/components/Skeleton.jsx` instead of spinner loaders. Pages with `dataLoading` state: DashboardPage, JobsPage, JobResultPage, PaymentPage, DeveloperPage, SettingsPage, JobConfirmPage.
- **Staggered List Animation**: All list/table rows use `AnimatedRow` from `app/frontend/src/components/AnimatedList.jsx` for sequential entrance animation. CSS keyframes `stagger-enter` defined in `app/frontend/src/index.css` (240ms ease-out, 30ms stagger per item).
- **Sharp Corners (No Border Radius)**: All `borderRadius` values set to `0` in `app/frontend/tailwind.config.js`. Scrollbar thumb and ProseMirror marks also have `border-radius: 0` in `index.css`.
- **Reduced Font/Element Scale**: Font sizes and spacing reduced ~10-20% via `tailwind.config.js` (`fontSize`, `spacing`). Individual pages have further padding reductions (e.g., `p-8` → `p-5`, `py-3` → `py-2`).
- **Applied Pages**: DashboardPage, JobsPage, JobResultPage, PaymentPage, DeveloperPage, SettingsPage, UploadPage, AuthPage, AdminLogin, AdminDashboard, JobConfirmPage, PoetryProgress, SidebarLayout.
- Key files:
  - `app/frontend/src/components/Skeleton.jsx` — Reusable skeleton components
  - `app/frontend/src/components/AnimatedList.jsx` — `AnimatedRow` / `AnimatedList` wrappers
  - `app/frontend/src/index.css` — `@keyframes stagger-enter`, scrollbar/mark border-radius overrides
  - `app/frontend/tailwind.config.js` — Reduced fontSize, spacing, borderRadius: 0

## API Error Messages (English)

- All backend `HTTPException`, `JSONResponse`, `RuntimeError`, `ValueError`, `FileNotFoundError`, and `TimeoutError` messages are in **English**.
- Korean error messages were fully translated across all backend files: `api/`, `auth/`, `core/`, `workers/`, `docling_service/`, `paddleocr_service/`, `email_sender.py`, `compare_ocr.py`.
- Frontend UI strings remain i18n (ko/en/ja) via `react-i18next`.
- Turnstile verification failure returns `"Bot verification failed. Please try again."` (was Korean).

## On-Premise Inquiry

- On-premise local server quote page at `/on-premise` (`OnPremisePage.jsx`).
- Backend: `app/backend/api/on_premise.py` — `POST /api/on-premise/inquiry` creates an inquiry, sends admin email.
- Pricing: linear from $20,000 (3,000 pages/hr) to $80,000 (12,000 pages/hr), in 1,000-page/hr increments.
- DB: `on_premise_inquiries` table (`016_add_on_premise_inquiry.sql`).
- Key files: `app/backend/api/on_premise.py`, `app/frontend/src/pages/OnPremisePage.jsx`, `app/backend/db/models.py` (`OnPremiseInquiry`).

## Dev Auth (Local Development Only)

- `app/backend/api/dev_auth.py` — bypasses Supabase Auth for local development.
- Only active when `DEV_BYPASS_AUTH=true` in `.env`.
- `POST /api/dev/login` issues a Supabase-compatible JWT for a fixed dev user (`dev@proof.local`).
- **Never enable in production.**
- **Frontend Dev Mock Mode** (`import.meta.env.DEV`):
  - Vite dev 모드에서 자동 활성화되며, 백엔드 `/api/dev/login` 우선 시도 후 실패 시 mock 사용자로 폴백합니다.
  - `app/frontend/src/dev/mockUser.js` — mock 사용자/세션 객체.
  - `app/frontend/src/dev/mockApi.js` — 모든 API 요청을 가로채 mock 응답 반환 (빈 목록, 기본 프로필, 더미 작업 등).
  - `app/frontend/src/components/DevBypassBanner.jsx` — mock 모드 활성 시 상단에 안내 배너 표시.
  - `app/frontend/src/AuthContext.jsx` — `AuthProvider`가 dev 모드에서 초기 mock 세션 설정, 실제 세션 감지 시 mock 비활성화.
  - `app/frontend/src/api.js` — `devMockEnabled` 플래그로 `mockRequest()` 라우팅.
  - 실제 백엔드 세션이 감지되면 자동으로 mock 모드가 비활성화됩니다.

## GDPR / Account Data

- `app/backend/api/gdpr.py` — GDPR compliance endpoints.
- `GET /api/account/export` — exports all user data as JSON (jobs, payments, API keys, usage).
- `DELETE /api/account/delete` — deletes user account and all associated data.
- Key file: `app/backend/api/gdpr.py`.

## Legal Pages & Cookie Consent

- `/terms` — Terms of Service (`LegalTermsPage.jsx`, i18n).
  - 6장 18조 구조: 제1장 총칙·이용계약(s1–s5), 제2장 서비스 아키텍처·기술적 한계(s6–s7), 제3장 데이터 국지화·개인정보 보호(s8–s9), 제4장 자체 호스팅 AI 지식재산권·환각 면책(s10–s12), 제5장 API 모네타이제이션·B2B 책임 통제(s13–s14), 제6장 책임 제한·수출 통제·분쟁 해결(s15–s18).
  - `renderParagraphs()` 헬퍼로 `\n` 기준 다단락 렌더링, `h2`(장) + `h3`(조) 계층 구조.
  - i18n 키: `legal.terms.ch1Title`~`ch6Title`, `legal.terms.s1Title`~`s18Title`, `legal.terms.s1Body`~`s18Body`, `legal.terms.contactTitle/contactBody`.
  - 시행일: 2026-07-03.
- `/privacy` — Privacy Policy (`LegalPrivacyPage.jsx`, i18n).
- `/refund-policy` — Refund Policy (`LegalRefundPage.jsx`, i18n).
  - Paddle 심사 통과를 위한 별도 페이지. 미사용 크레딧 14일 환불, 사용 후 불가, 청구 방법, 처리 기간 안내.
  - i18n 키: `legal.refund.title`, `legal.refund.lastUpdated`, `legal.refund.effectiveDate`, `legal.refund.body` (ko/en/ja).
- `CookieConsent` component shown on all pages (bottom banner).
- Legal contact email: `admin@proof.teamcat.app`.
- Key files: `app/frontend/src/pages/LegalTermsPage.jsx`, `app/frontend/src/pages/LegalPrivacyPage.jsx`, `app/frontend/src/pages/LegalRefundPage.jsx`, `app/frontend/src/components/CookieConsent.jsx`, `app/frontend/src/components/GlobalFooter.jsx`.
- Locale files: `src/locales/{ko,en,ja}/common.json` — `legal.terms`, `legal.privacy`, `legal.refund` 섹션.

## Docusaurus Docs Site

- Served at `/docs/` by FastAPI (`main.py` mounts `docs/build/` as static files).
- Source: `app/docs/docs/` (English), translations under `app/docs/i18n/{ko,ja}/docusaurus-plugin-content-docs/current/`.
- **External links**: use `pathname:///path` protocol (e.g., `pathname:///developer`, `pathname:///api/v1/docs`) in both `docusaurus.config.js` and markdown files. Relative paths like `../../developer` cause broken links on i18n pages.
- **Doc-internal links**: use doc IDs without `.md` extension (e.g., `[HWP Support](hwp)`, `[file formats](file-formats)`), not file paths like `./hwp.md` or `../file-formats`.
- Sidebars: `app/docs/sidebars.js` — three sidebars: `docsSidebar`, `apiReferenceSidebar`, `aiPromptsSidebar`.
- Build: `cd app/docs && npm run build` (outputs to `docs/build/`).
- When adding new docs pages, create EN source + KO/JA translations and register in `sidebars.js`.

## Agent Guidelines

- Prefer minimal, focused edits. Follow existing code style.
- Add DB schema changes to `app/backend/db/migrations/` as SQL files.
- Do not commit media files, PDFs, or `node_modules`.
- Test API changes by creating a temporary API key and running the full upload→confirm→download flow.
- Keep the workflow-linear code style with flow comments at the top of major functions.
- When adding UI text, always use i18n translation keys. Never hardcode user-facing strings.
- Add new translation keys to all three locale files (en/ko/ja) simultaneously.
- When adding new Docusaurus docs pages, create the English source in `app/docs/docs/` and add Korean/Japanese translations under `app/docs/i18n/{ko,ja}/docusaurus-plugin-content-docs/current/`.

## Subscription Plans (Free / Pro / Max)

- **UI users** (web app) use subscription plans only. API users continue to use the pay-as-you-go credit system (`points_balance`).
- **Plans**:
  - Free: 1,000 basic pages + 500 premium pages + 150 min media/month
  - Pro: $20/month or $200/year — 10,000 basic + 5,000 premium + 1,500 min media/month
  - Max: $100/month or $1,000/year — 60,000 basic + 30,000 premium + 9,000 min media/month
- **Key files**:
  - `app/backend/core/subscription_service.py` — monthly quota tracking and reservation.
  - `app/backend/api/subscriptions.py` — public plan listing, checkout, and cancel endpoints.
  - `app/backend/api/payments.py` — Paddle webhook handling for `subscription.*` events.
  - `app/backend/db/migrations/018_add_subscription_plan.sql` — schema migration.
  - `app/frontend/src/pages/PlansPage.jsx` — subscription plan UI.
  - `scripts/create_paddle_subscription_catalog.py` — automated Paddle product/price creation.
- **Paddle API key**: store in `app/.env` as `PADDLE_API_KEY`. It is seeded into `app_settings` via `settings_store.py` and `config.py`.
- **Creating catalog**: run `PADDLE_API_KEY=... DATABASE_URL=... python scripts/create_paddle_subscription_catalog.py`. This creates products and monthly/yearly prices for Free/Pro/Max and saves the resulting `price_id`s into `app_settings`.
- **Webhooks**: Paddle dashboard must send `subscription.created`, `subscription.updated`, `subscription.canceled`, and `transaction.completed` to `https://proof.teamcat.app/api/payments/paddle/webhook`.
- **Free $0 note**: if Paddle does not allow a $0 recurring checkout, the Free tier can stay internal-only (no Paddle subscription) and only Pro/Max use Paddle checkout. The backend treats `subscription_plan == "free"` as always active.

## Frontend Dropdown Hover UX

- CSS-only `group-hover` dropdowns (e.g. Excel/Office buttons in `JobResultPage.jsx`) can disappear when the cursor crosses the small gap between the trigger button and the dropdown panel.
- Use React state + `useRef` timer instead:
  - `onMouseEnter`: clear any pending close timer and open the dropdown.
  - `onMouseLeave`: start a short timeout (e.g. 150ms) before closing the dropdown.
  - Apply the handlers to both the trigger button wrapper and the dropdown panel itself so moving the mouse between them keeps the dropdown open.
- Replace `hidden group-hover:flex` with conditional classes driven by the open state: `${open ? "flex" : "hidden"}`.
- Key files: `app/frontend/src/pages/JobResultPage.jsx` (Excel/Office dropdowns).

## PDF Annotation (PDF 하이라이트/여백 주석)

- **구독 기능**: PDF 주석 생성은 구독 기반의 프리미엄 기능입니다. 비회원 사용자는 사용할 수 없습니다.
- **비회원 처리**: `job.user_id`가 `None`인 경우 402 에러("구독이 필요한 기능입니다.")를 반환하고, 프론트엔드에서는 price 페이지로 리디렉트합니다.
- **관리자 권한**: `mtgmtg@naver.com` (관리자)는 모든 기능을 무제한으로 사용할 수 있습니다. 구독 체크를 건너뛰고 바로 처리합니다.
- **백엔드 로직** (`app/backend/api/jobs.py`의 `annotate_job` 및 `annotate_action` 엔드포인트):
  - `job.user_id`가 `None`이면 402 에러 반환 (주석 생성뿐 아니라 재시도 action 엔드포인트에서도 동일 체크)
  - `db_user.is_admin`가 `True`이면 구독 체크 없이 바로 처리 (환불 불필요, 예약 페이지 수 0)
  - 일반 사용자는 `subscription_service.reserve_usage()`로 구독 한도 체크 및 차감
- **프론트엔드 처리** (`app/frontend/src/pages/JobResultPage.jsx`의 `startAnnotate` 함수):
  - 에러 메시지에 "구독이 필요" 또는 "subscription"이 포함되면 2초 후 price 페이지로 자동 이동
  - i18n 키 `page:errors.subscriptionRequired` 사용 (ko/en/ja 모두 추가)
- **주석 생성 비용**: 프리미엄 페이지 수(`premium_pages`)로 차감됩니다. 관리자는 차감되지 않습니다.
- **재시도 액션** (`annotate_action` 엔드포인트): 주석 생성이 `error` 상태로 실패한 경우 사용자가 재시도(retry)할 수 있습니다. 구독제이므로 환불(refund) 기능은 제공하지 않습니다. 비회원 사용자는 이 액션 엔드포인트에서도 402 에러를 받습니다.

## Frontend Variable Naming Conventions

- **JobResultPage.jsx**: XLSX 변환 비용 표시 시 `xlsxBasicCost`/`xlsxAdvancedCost` 대신 `xlsxBasicUnits`/`xlsxAdvancedUnits`를 사용해야 합니다.
- 이 두 변수는 이미 409-410번 라인에서 정의되어 있으며: `job.total_pages || job.total_files || 1` 값으로 계산됩니다.
- 구독제에서는 실제 달러 비용이 아니라 구독 월간 페이지 한도를 차감하므로 "units"라는 명칭이 더 정확합니다.
- i18n 키 `page:result.xlsxBasic`과 `page:result.xlsxAdvanced`는 `cost` 파라미터를 받아 표시합니다.
