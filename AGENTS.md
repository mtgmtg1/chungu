# AGENTS.md — PROOF Project Guide

## Project Overview

PROOF is a PDF/media → structured table (CSV/MD/XLSX) conversion service. It exposes core functionality both as a web application and as a monetized API (`/api/v1/*`) for external developers.

## Recent Changes

최근 주요 변경사항입니다. 상세한 코드 이력은 `git log`를 참조하세요.

### 프론트엔드 초기 로드 최적화 + 빌드/배포 인프라 정리 — 2026-09-04

> 이 항목은 성능 작업과 별개 세션에서 이루어진 변경을 뒤늦게 정리한 것이다. 수치는 작업자가 코드 주석에 남긴 실측값을 옮겼다.

- **`vite.config.js` — `manualChunks` 를 객체 형태에서 함수 형태로 교체**: 객체 형태는 나열한 패키지의 **전이 의존까지** 같은 청크로 빨아들인다. 그 결과 `react/jsx-runtime` 이 `tiptap-vendor` 로, Vite 의 `__vite_preload` 헬퍼가 `pdf-viewer` 로 끌려갔고, 진입 청크가 헬퍼 하나 때문에 brotli 347KB(pdf-viewer + tiptap-vendor)를 정적 import 하게 됐다. 함수 형태는 매칭되지 않은 모듈에 `undefined` 를 반환해 Rollup 기본 배치를 따르므로 이 오염이 없다.
  - `vite/preload-helper` 는 가상 모듈이라 패키지명이 없다. 배치를 지정하지 않으면 Rollup 이 임의의 async 벤더 청크에 넣어 같은 문제가 재발하므로, 항상 초기 로드되는 `react-vendor` 에 고정한다.
  - `@embedpdf/pdfjs-dist` 는 **수동 그룹으로 묶지 않는다**. 자체 dynamic import 로 `worker-engine`/`direct-engine` 을 쪼개는데, 강제로 한 청크에 모으면 그 분할이 무너진다.
- **`main.jsx` — 랜딩을 제외한 전 라우트 `React.lazy`**: 정적 import 로 두면 `JobResultPage` 가 끌어오는 pdf-viewer / tiptap / flow / ai 벤더 청크가 전부 진입 그래프에 포함되어, 랜딩 진입만으로 brotli 1.28MB 를 내려받는다. 랜딩(`UploadPage`)과 `AuthPage`(ProtectedRoute 의 비로그인 fallback)는 진입 청크에 남긴다.
- **`i18n.js` — 로케일 코드 분할**: 세 언어를 모두 정적 import 하면 로케일 JSON 312KB(brotli 77KB)가 통째로 진입 청크에 들어간다. `fallbackLng` 인 `en` 만 번들에 남기고 ko/ja 는 최소 backend 플러그인으로 동적 import 한다. `partialBundledLanguages: true` 가 있어야 번들된 en 과 backend 로 읽어온 ko/ja 를 함께 쓴다.
- **`UploadPage.jsx` — `GridScan` lazy 화**: 배경 장식용 WebGL(three + postprocessing, brotli 141KB)이 랜딩 첫 페인트를 막고 있었다. 콘텐츠와 무관한 장식이므로 `Suspense fallback={null}` 로 분리.
- **DB 커넥션 풀 설정** (`config.py`, `db/session.py`): `pool_size=20` / `max_overflow=20` / `pool_recycle=1800`. SQLAlchemy 기본값(5 + 10)은 동시 요청 15개에서 포화한다.
- **`038_add_jobs_user_created_index.sql`**: `/api/jobs` 는 `WHERE user_id = ? ORDER BY created_at DESC LIMIT ?` 형태라, `user_id` 단일 인덱스만으로는 필터 후 Sort 노드가 필요했다. `(user_id, created_at DESC)` 복합 인덱스와 전역 최신순용 `(created_at DESC)` 를 추가.
- **빌드 재현성**: `Dockerfile.backend` 의 frontend/docs 스테이지가 `npm install` → **`npm ci`**. 이를 위해 `app/frontend/package-lock.json` 과 `app/docs/package-lock.json` 을 `.gitignore` 의 전역 `package-lock.json` 무시 규칙에서 예외 처리해 추적 대상으로 되돌렸다.
- **빌드 컨텍스트 축소**: `app/.dockerignore` 에 `docs/node_modules`, `docs/build`, `docs/.docusaurus`, `backend/venv`, `backend/.venv` 추가 — 컨텍스트 약 880MB → 약 35MB.
- **배포 스크립트**: `deploy_a1.sh` / `deploy_develop.sh` rsync 에 `--exclude='venv'` 추가 (기존에는 `.venv` 만 제외해 `backend/venv` 가 통째로 전송됐다).
- **⚠️ 회귀 방지 경고**:
  1. **`manualChunks` 를 객체 형태로 되돌리지 말 것.** 전이 의존이 딸려 들어와 진입 청크가 다시 부풀고, 원인이 눈에 잘 띄지 않는다.
  2. **`main.jsx` 에서 라우트를 정적 import 로 되돌리지 말 것.** 한 줄만 되돌려도 그 라우트가 끌어오는 벤더 청크 전체가 진입 그래프에 합류한다.
  3. **`package-lock.json` 두 개는 반드시 커밋 상태를 유지해야 한다.** `.gitignore` 의 예외(`!app/frontend/package-lock.json`, `!app/docs/package-lock.json`)를 지우면 fresh clone 에서 `npm ci` 가 실패해 이미지 빌드가 깨진다.
  4. **`db_pool_size + db_max_overflow` 는 anyio 스레드풀 상한과 짝이다.** 한쪽만 올리면 병목이 옮겨가거나 `QueuePool limit` 오류가 난다.
- **핵심 파일**: `app/frontend/vite.config.js`, `app/frontend/src/main.jsx`, `app/frontend/src/i18n.js`, `app/frontend/src/pages/UploadPage.jsx`, `app/backend/config.py`, `app/backend/db/session.py`, `app/backend/db/migrations/038_add_jobs_user_created_index.sql`(신규), `app/Dockerfile.backend`, `app/.dockerignore`, `.gitignore`, `deploy_a1.sh`, `deploy_develop.sh`.

### 성능 개선 — 이벤트 루프 블로킹 async 엔드포인트 21개 제거 — 2026-09-04

- **배경**: FastAPI 는 `def` 핸들러를 스레드풀(anyio, 기본 40스레드)에서 실행하지만 `async def` 핸들러는 이벤트 루프에서 그대로 실행한다. 동기 SQLAlchemy 세션만 쓰면서 `async def` 로 선언된 핸들러가 21개 있었고, 그 요청이 끝날 때까지 프로세스 전체가 다른 요청을 하나도 처리하지 못했다. uvicorn 워커는 1개다.
- **특히 심각했던 지점**: `api/sandboxes.py` 의 12개 핸들러. `SandboxManager` 의 모든 메서드가 `subprocess.run` 으로 nerdctl 을 호출하며 타임아웃이 최대 60초다(`core/sandbox/manager.py:182,274,296,325`). `execute_command` 는 사용자가 준 명령을 그대로 실행한다. 즉 샌드박스 명령 하나가 백엔드 전체를 최대 60초 동결시켰다 — 다른 모든 요청, 헬스체크, `/api/ai` 스트리밍 프록시까지.
- **변경 내용**:
  - `async def` → `def` 전환 21개: `api/sandboxes.py`(12), `api/chat_conversations.py`(4), `api/flow_drawings.py`(3), `api/jobs/uploads.py`(2 — `init_job`, `init_add_files`).
  - 전환 대상은 AST 로 선별했다: 라우트 데코레이터가 붙은 `async def` 중 본문에 동기 DB 호출이 있고 `await` 가 **하나도 없는** 것. `await` 가 없으면 async 로 둘 이유가 없고 손해만 본다.
  - `await` 가 실제로 필요한 6개(`admin.login`, `jobs/download.save_edited_xlsx`, `jobs/uploads.upload_job`/`create_job`/`confirm_add_files`, `v1/jobs.upload_job`)는 async 를 유지했다.
  - 각 파일에 회귀 방지 주석 추가. 신규 테스트 `test_no_blocking_async_endpoints.py` 는 "동기 DB 를 쓰면서 async 인 핸들러" 집합을 허용 목록으로 고정한다.
  - 핸들러를 직접 호출하던 테스트에서 `asyncio.run(...)` 12건과 `await` 1건 제거.
- **검증**: 백엔드 382 tests pass(기존 380 + 신규 2). 실제 FastAPI 앱에 `httpx.ASGITransport` 로 3초 블로킹 핸들러와 `/api/health` 를 동시 호출해 실측: 전환 전 health 응답이 gather 시작 +3,013ms(블로킹이 끝날 때까지 대기), 전환 후 +206ms(자기 지연분만). 회귀 테스트가 실제로 실패하는지도 `execute_command` 를 일시 되돌려 확인했다.
- **⚠️ 회귀 방지 경고**:
  1. **이 핸들러들을 `async def` 로 되돌리지 말 것.** 동기 DB 세션과 subprocess 호출이 그대로 이벤트 루프로 돌아온다. `test_no_blocking_async_endpoints.py` 가 잡지만, 경고 자체를 이해하고 있어야 한다.
  2. **`await` 가 필요한 작업을 추가할 때** 함수를 통째로 `async def` 로 바꾸지 말 것. 같은 함수의 동기 DB 호출이 다시 루프를 막는다. 블로킹 부분을 `asyncio.to_thread` 로 감싸거나 핸들러를 분리하라.
  3. **커넥션 풀 여유가 없다.** `db_pool_size=20 + db_max_overflow=20 = 40` 이고 anyio 기본 스레드풀도 40이다. 정확히 맞아떨어져 현재는 풀 고갈이 없지만, 스레드풀 상한(`anyio.to_thread.current_default_thread_limiter()`)을 올리면 `QueuePool limit` 오류가 난다. 둘은 함께 조정해야 한다.
  4. **핸들러를 직접 호출하는 테스트는 이제 `await`/`asyncio.run` 없이 호출한다.** 다시 async 로 감싸면 `ValueError: a coroutine was expected` 가 아니라 조용히 코루틴 객체를 반환받아 단언이 무의미해질 수 있다.
  5. `ALLOWED_ASYNC_WITH_SYNC_DB` 에 항목을 추가하기 전에, 정말 `await` 가 필요한지 / 블로킹 부분을 분리할 수 없는지 먼저 확인할 것.
- **핵심 파일**: `app/backend/api/sandboxes.py`, `app/backend/api/chat_conversations.py`, `app/backend/api/flow_drawings.py`, `app/backend/api/jobs/uploads.py`, `app/backend/tests/test_no_blocking_async_endpoints.py`(신규), `app/backend/tests/test_chat_conversations.py`, `app/backend/tests/test_api_sandboxes.py`.

### 성능 개선 — 응답 압축 / Storage 왕복 제거 / Paddle 온디맨드 — 2026-09-04

- **배경**: 리버스 프록시 없이 uvicorn 이 SPA 번들과 API JSON 을 직접 서빙하는데 압축이 전혀 없었고, `_source_files` 는 파일 존재 확인을 위해 Supabase 왕복을 파일 수만큼 순차로 돌리고 있었다.
- **변경 내용**:
  - **`SelectiveGZipMiddleware`** (`backend/main.py`): 스트리밍 경로(`/api/ai/`, `/api/v1/ai/`, `/supabase/`)와 이미 압축된 포맷(`PRECOMPRESSED_EXTENSIONS`)을 제외하고 gzip 압축. `compresslevel=6`, `minimum_size=1024`. 실측: 진입 그래프 684,563 → 190,812 bytes(3.59배), pdfium wasm 4.6MB → 2.1MB, luckysheet 3MB → 622KB.
  - **`list_jobs` 컬럼 지연 로딩** (`api/jobs/lifecycle.py`): `_job_summary` 가 읽지 않는 `extracted_files` / `prompt` / `columns` / `ediscovery_params` / `element_mappings` / `issue_tree` 를 `defer()`. JobsPage 가 5초마다 최대 100건을 폴링하므로 폴링당 페이로드가 줄어든다.
  - **`_list_bucket_files` 도입** (`api/jobs/_shared.py`): "signed URL 생성 성공 = 파일 존재" 탐색과 "download() 성공 = 파일 존재" 탐색을 폴더 목록 1회 조회로 대체. 목록 조회 실패 시 기존 탐색으로 폴백한다.
  - **`_ensure_clean_source_pdf` 판정 캐시**: "내장 주석 없음" / "clean PDF 존재" 판정을 `preview:{job_id}:cleanpdf:{hash}` 에 캐싱(TTL 3600초). 예전에는 판정을 남기지 않아 preview 캐시가 만료될 때마다 원본 PDF 전체를 다시 내려받고 PyMuPDF 파싱을 다시 돌렸다.
  - **주석 병합 병렬화 + 경로 분리**: `_merge_annotation_jsons` 가 `merged_annotations_{source_index}.json` 에 쓰도록 변경하고, 파일별 병합을 `ThreadPoolExecutor(max_workers=3)` 으로 병렬화.
  - **Paddle SDK 온디맨드 로드** (`frontend/src/utils/loadPaddle.js` 신규): `index.html` 의 동기 `<script src="cdn.paddle.com/...">` 제거. `PaymentPage`/`PricePage` 가 `initPaddle(token)` 으로 필요 시점에 로드한다.
- **검증**: 백엔드 380 tests pass(기존 371 + 신규 9), 프론트엔드 113 tests pass(기존 106 + 신규 7), vite build 성공. 실제 FastAPI 앱에 ASGI 를 직접 구동해 와이어 바이트와 압축 해제 후 내용 일치를 확인했다.
- **⚠️ 회귀 방지 경고**:
  1. **`GZipMiddleware` 를 전역으로 붙이지 말 것.** starlette 의 `GZipResponder` 는 스트리밍 응답에서 청크를 deflate 윈도우에 write 만 하고 flush 하지 않는다. SSE 는 버퍼가 찰 때까지 클라이언트에 아무것도 도달하지 않아 AI 채팅 스트리밍이 멈춘다. 새 스트리밍 경로를 추가하면 `STREAMING_PATH_PREFIXES` 에도 추가해야 한다.
  2. **`.wasm` 을 `PRECOMPRESSED_EXTENSIONS` 에 넣지 말 것.** 압축되지 않은 바이트코드라 2.17배(4.6MB → 2.1MB)로 줄어드는, 이 앱에서 가장 큰 단일 절감 대상이다. `.svg` / `.map` / `.json` 도 텍스트이므로 마찬가지다.
  3. **`merged_annotations.json` → `merged_annotations_{source_index}.json` 경로가 바뀌었다.** 이전 단일 공유 경로는 파일이 여러 개인 job 에서 마지막 병합이 앞선 파일 결과를 덮어써, 모든 원본 탭이 같은 주석을 가리켰다(회귀 테스트: `test_merged_path_is_per_source_index`). 경로를 되돌리면 병렬 병합이 서로를 침범하므로 절대 단일 경로로 합치지 말 것. 배포 후 기존 `merged_annotations.json` 은 참조되지 않는 잔여 파일이 된다.
  4. **clean PDF 판정 캐시는 `preview:{job_id}:` 네임스페이스에 있어야 한다.** 열 군데에서 호출하는 `cache.invalidate_pattern(f"preview:{job_id}:*")` 이 이 판정까지 함께 쓸어가는 구조에 의존한다. 다른 접두사로 옮기면 원본 PDF 가 교체돼도 낡은 판정이 남는다.
  5. **`list_jobs` 의 `defer` 대상 컬럼을 `_job_summary` 에서 읽기 시작하면** SQLAlchemy 가 행마다 추가 쿼리를 날려 오히려 느려진다. `_job_summary` 에 필드를 추가할 때 `_JOB_LIST_DEFERRED_COLUMNS` 를 함께 확인할 것.
  6. **테스트 fake 의 파라미터명은 프로덕션 시그니처와 일치해야 한다.** 호출부가 `bucket=` 키워드를 쓰므로 이름이 다르면 `TypeError` 가 나고 호출부 `except` 에 삼켜져 "파일 없음"으로 조용히 오해석된다.
- **핵심 파일**: `app/backend/main.py`, `app/backend/api/jobs/_shared.py`, `app/backend/api/jobs/lifecycle.py`, `app/backend/tests/test_selective_gzip.py`(신규), `app/backend/tests/test_source_files_batch_listing.py`(신규), `app/backend/tests/test_clean_pdf_verdict_cache.py`(신규), `app/frontend/src/utils/loadPaddle.js`(신규), `app/frontend/src/utils/loadPaddle.test.js`(신규), `app/frontend/index.html`, `app/frontend/src/pages/PaymentPage.jsx`, `app/frontend/src/pages/PricePage.jsx`.

### 에이전트 샌드박스 결과 파일 수집 실패 수정 — 2026-08-03

- **증상**: 결과 페이지의 AI 에이전트가 샌드박스에서 파일을 생성하거나 외부 파일을 다운로드해도 왼쪽 파일탭에 표시되지 않았고, 사용자가 미리보기/다운로드할 수 없었다.
- **근본 원인**: `app/backend/api/sandboxes.py`와 만료 샌드박스 정리 태스크가 존재하지 않는 `get_supabase_client()`를 import하고 있었다. 예외를 `supabase = None`으로 조용히 바꾸면서 `ResultCollector`가 Storage 업로드를 건너뛰었고, 따라서 `job.extracted_files`가 갱신되지 않았다.
- **수정 내용**:
  - `app/backend/api/sandboxes.py`: 실제 제공되는 `get_service_client()`를 사용하도록 수정. 서비스 클라이언트 생성 실패는 업로드 0개 성공으로 위장하지 않고 HTTP 503으로 명시한다.
  - `app/backend/workers/tasks/maintenance.py`: 만료된 샌드박스 결과 수집도 `get_service_client()`를 사용하도록 수정하여 자동 정리 시 생성 파일이 유실되지 않게 했다.
  - 수집 성공 시 기존 파이프라인(`Storage 업로드 → job.extracted_files 추가 → preview 캐시 무효화 → 결과 페이지 재조회 → 왼쪽 파일탭 표시`)을 정상 동작시켰다.
  - `app/backend/tests/test_api_sandboxes.py`: 수집기가 실제 서비스 클라이언트를 전달받는지 회귀 검증을 추가했다. 기존 FakeCollector 테스트가 잘못된 import를 감지하지 못하던 공백을 보완한다.
- **검증**: Python 문법 검사 및 `git diff --check` 성공, 프론트엔드 106 tests 통과, Vite build 성공. 백엔드 pytest는 현재 로컬 환경에 `fastapi` 패키지가 없어 실행하지 못했다.
- **⚠️ 회귀 방지 경고**:
  1. 샌드박스 결과 업로드는 백엔드 전용 Supabase service-role 클라이언트를 사용해야 한다. 프론트엔드의 anon 클라이언트나 존재하지 않는 `get_supabase_client()`를 사용하지 말 것.
  2. 업로드 실패를 `supabase=None`으로 바꿔 성공 응답처럼 반환하면 파일이 Storage와 `job.extracted_files` 양쪽에서 사라진다. API 경로에서는 명시적인 오류를 반환해야 한다.
  3. `ResultCollector`는 Storage 업로드 후에만 `job.extracted_files`를 갱신해야 한다. preview 캐시는 DB 갱신 직후 무효화해야 다음 `source_files` 조회에 새 파일이 포함된다.
  4. `ResultCollector.scan_workspace()`는 `agent_output`만이 아니라 workspace 전체의 허용 확장자를 스캔하며 `original`, `.git`, `.agent_log`, `node_modules`, 메타데이터 파일은 제외한다. 이 범위를 축소하지 말 것.
- **핵심 파일**: `app/backend/api/sandboxes.py`, `app/backend/workers/tasks/maintenance.py`, `app/backend/core/sandbox/collector.py`, `app/backend/tests/test_api_sandboxes.py`, `app/backend/api/jobs/_shared.py`, `app/backend/api/jobs/preview.py`.

### EmbedPDF 주석 삭제 자동저장(removals 전송) — 2026-07-25

- **배경**: EmbedPDF 뷰어에서 주석 생성은 자동 저장되었으나, 삭제는 새로고침 시 부활했다. 백엔드 `save_user_annotations`(`app/backend/api/jobs/annotations.py`)가 ID 기반 **누적 병합(accumulative merge)** 을 사용하기 때문이다 — 전송된 `annotations` 목록에 없는 ID라고 해서 삭제하지 않고, 오직 `removals` 배열에 명시된 ID만 삭제한다. 프론트엔드는 `exportAnnotations()` 결과(삭제된 주석이 빠진 전체 목록)만 보내고 `removals`를 보내지 않아서 삭제가 백엔드에 반영되지 않았다.
- **변경 내용**:
  - **신규 유틸**: `app/frontend/src/utils/annotationDiffUtils.js` — `extractAnnotationId(item)`와 `computeRemovedAnnotationIds(previousItems, currentItems)` 순수 함수. 백엔드 `_annotation_id`(`api/jobs/_shared.py`)와 동일한 ID 추출 규칙(`annotation.id` → 최상위 `id` fallback)을 사용한다. `previousItems`에 있고 `currentItems`에 없는 ID를 차집합으로 계산해 반환.
  - **SourcePanel**: `handleSaveAnnotations`가 `exportAnnotations()` 결과를 파싱한 뒤 `computeRemovedAnnotationIds(selectedAnnotationsJson, annotations)`로 삭제된 ID를 계산해 `onSaveAnnotations(annotations, removals)`로 전달. `selectedAnnotationsJson`(이전 로드본)을 의존성에 추가.
  - **JobResultPage**: `handleSaveAnnotations(annotations, removals=[])` 시그니처로 `removals`를 받아 `api.saveUserAnnotations`에 전달.
  - **api.js**: `saveUserAnnotations`가 `removals`를 payload에 포함해 전송 (`removals: removals ?? []`).
  - **테스트**: `annotationDiffUtils.test.js` 신규 12개 테스트 — ID 추출(annotation 래퍼/최상위/빈 값/비-dict), removals 계산(Happy Path, 삭제 없음, 신규 추가 무시, previous/current null, ID 없는 항목 무시, 최상위 id 형식).
- **검증**: 프론트엔드 106 tests pass (기존 94 + 신규 12), vite build 성공.
- **⚠️ 회귀 방지 경고**:
  1. `computeRemovedAnnotationIds`는 `selectedAnnotationsJson`(마지막으로 fetch한 병합본)을 기준으로 삼는다. 저장 후 백엔드가 반환한 `merged_annotations_url`로 `sourceFiles[idx].annotations_json_url`이 갱신되면 SourcePanel이 재 fetch하므로 다음 저장 시 기준이 최신화된다 — 재 fetch 완료 전에 연속 삭제하면 이미 삭제된 ID가 removals에 중복 포함될 수 있으나 백엔드가 `if rid in existing_by_id` 로 가드하므로 무해.
  2. ID 추출 규칙이 백엔드 `_annotation_id`와 다르면 삭제가 누락된다. 백엔드는 `item["annotation"]["id"]` → `item["id"]` 순서이고, 프론트 `extractAnnotationId`도 동일 순서를 사용한다. 한쪽만 바꾸면 불일치.
  3. `removals`는 문자열 ID 배열이어야 한다. 백엔드가 `isinstance(rid, str)` 로 필터하므로, 숫자 ID가 오면 무시된다. EmbedPDF 주석 ID는 문자열이므로 정상 동작.
  4. `handleSaveAnnotations`의 `useCallback` 의존성에 `selectedAnnotationsJson`이 추가되었다. 재 fetch 마다 콜백이 재생성되지만 debounce 타이머는 `autoSaveRef`로 유지되므로 타이머 누수 없음.
  5. `DebugPanelTogglePage`의 `onSaveAnnotations={() => {}}` no-op는 새 시그니처에도 호환된다(인수 무시). `PagedResultViewer`는 prop을 그대로 전달하므로 추가 변경 불필요.
- **핵심 파일**: `app/frontend/src/utils/annotationDiffUtils.js`(신규), `app/frontend/src/utils/annotationDiffUtils.test.js`(신규), `app/frontend/src/components/SourcePanel.jsx`, `app/frontend/src/pages/JobResultPage.jsx`, `app/frontend/src/api.js`.

### EmbedPDF sticky note 클릭 시 확장 코멘트 위젯 오버레이 — 2026-07-25

- **배경**: sticky note 주석을 클릭하면 snippet의 기본 선택 메뉴만 열리고 코멘트 텍스트를 바로 볼 수 없었다. 사용자 요청으로 sticky note 클릭 시 확장된 위젯이 페이지에 직접 보이고, 그 아래에 기존 선택 메뉴도 유지되는 UX가 필요했다.
- **변경 내용**:
  - **접근 방식**: snippet `PDFViewer`를 유지하면서 snippet 공식 API(`mergeSchema`/`registerCommand`/`getRectPositionForPage`/`onScroll`)만 사용하는 DOM 오버레이 하이브리드 방식 채택. headless 마이그레이션은 비용이 크고, snippet은 커스텀 React 컴포넌트 등록 API를 노출하지 않으므로 제외.
  - **"코멘트 보기" 명령 등록**: `PdfViewer.jsx`의 `handleReady`에서 `commands.registerCommand`로 `sticky-note-comment` 명령 등록. action에서 `getSelectedAnnotations()`(복수형, fallback `getSelectedAnnotation()`)로 선택된 주석을 가져와 `type=1`(TEXT sticky note)이면 확장 위젯 표시.
  - **selectionMenu schema 병합**: `uiApi.mergeSchema()`로 `selectionMenus`에 새 메뉴 `sticky-note-comment-menu` 추가. 기존 선택 메뉴(삭제/색상/속성 등)는 그대로 유지 — "그 아래에는 기존의 선택메뉴도 떠야한다" 요구사항 충족. `categories: ["annotation-text"]`로 sticky note에만 버튼 표시.
  - **StickyNoteOverlay 컴포넌트 신규**: `app/frontend/src/components/StickyNoteOverlay.jsx`. 주석 `contents`를 큰 카드(280px 너비, 최대 320px 높이)로 표시. 상단 헤더에 sticky note 아이콘 + 주석 색상 띠 + 닫기 버튼. 본문은 `whitespace-pre-wrap`으로 줄바꿈 보존, 스크롤 가능. 닫기 버튼/외부 클릭/Escape 키로 닫기.
  - **오버레이 위치 계산**: `scrollApi.getRectPositionForPage(pageIndex+1, rect)`로 주석 rect(페이지 내 device-space)를 viewport 내 절대 좌표로 변환. 위젯 높이(200px 추정)만큼 위로 오프셋해 주석 위에 배치, 페이지 상단을 벗어나면 아래로 배치.
  - **스크롤/줌 동기화**: `scrollApi.onScroll` + `viewportApi.onViewportChange` 이벤트 구독, throttle 16ms(60fps)로 오버레이 위치 재계산. `expandedAnnotationRef`로 최신 주석을 추적해 이벤트 클로저 문제 회피.
  - **cleanup**: 컴포넌트 언마운트 시 scroll/viewport/annotation 이벤트 구독 해제 + throttle 타이머 정리.
  - **i18n**: `page:annotation.viewComment`/`comment`/`close`/`emptyComment` 키를 ko/en/ja에 추가.
  - **테스트**: `StickyNoteOverlay.test.jsx` 신규 10개 테스트 — 코멘트 표시, 빈 코멘트 placeholder, 닫기 버튼, Escape, 외부 클릭, 카드 내부 클릭, position null/비숫자, 색상 fallback, 여러 줄 줄바꿈 보존.
- **검증**: 프론트엔드 94 tests pass (기존 84 + 신규 10), vite build 성공.
- **⚠️ 회귀 방지 경고**:
  1. `getRectPositionForPage`의 첫 인자는 **1-based 페이지 번호**(`pageIndex + 1`)이다. 0-based로 전달하면 잘못된 페이지의 좌표가 반환되어 오버레이가 어긋난다.
  2. `mergeSchema`는 기존 selectionMenus를 **덮어쓰지 않고 병합**한다. 새 메뉴를 추가할 때 기존 메뉴 ID를 재사용하면 덮어쓰기되므로, 새 메뉴는 고유 ID(`sticky-note-comment-menu`)를 사용한다.
  3. `commands.registerCommand`는 동일 ID 재등록 시 에러를 발생시킬 수 있다. `handleReady`는 snippet 초기화 시 한 번만 호출되므로 중복 등록 위험은 없으나, hot-reload 시 주의.
  4. `expandedAnnotationRef`는 `expandedAnnotation` state를 ref로 미러링한다. 이벤트 핸들러 클로저에서 최신 주석을 참조하려면 ref를 사용해야 한다 — state를 직접 참조하면 stale closure 문제 발생.
  5. 오버레이 위젯에만 `pointer-events: auto`를 설정하고 위젯 외부는 `pointer-events: none`이어야 snippet의 주석 조작(드래그/리사이즈)이 막히지 않는다. 현재 구현은 위젯 자체에만 `pointer-events: auto`를 설정했으나, 외부 클릭 감지는 document-level `pointerdown` listener로 처리하므로 별도 백드롭 요소를 두지 않는다.
  6. `categories: ["annotation-text"]`가 snippet의 카테고리 필터링으로 버튼이 sticky note에만 표시되는 것을 보장하지 않을 수 있다. 미지원 시 `visible` 동적 함수로 주석 타입을 체크하는 fallback이 필요할 수 있음 — 실제 동작 확인 필요.
- **핵심 파일**: `app/frontend/src/components/PdfViewer.jsx`, `app/frontend/src/components/StickyNoteOverlay.jsx`(신규), `app/frontend/src/components/StickyNoteOverlay.test.jsx`(신규), `app/frontend/src/locales/{ko,en,ja}/page.json`.

### 에이전트/비전 주석 callout → sticky note 전환 — 2026-07-25

- **배경**: 에이전트 도구와 백엔드 비전 주석 흐름이 PDF 코멘트 생성 시 FreeTextCallout(텍스트 박스 + 화살표 리더 라인)을 사용했었다. callout은 빈 영역 탐색/충돌 회피 로직이 복잡하고 텍스트 박스가 페이지 여백에 떠서 가독성이 떨어지는 문제가 있었다. 사용자 요청으로 sticky note(메모 아이콘 + 클릭 시 팝업)로 전환.
- **변경 내용**:
  - **AI 에이전트 도구**: `app/ai-backend/src/tools/annotations.ts`에서 `add_text_callout` 도구를 `add_sticky_note`로 변경. `PendingAnnotation.type`을 `'highlight' | 'callout'` → `'highlight' | 'sticky'`로 변경. `_buildAnnotationItem`의 callout 분기를 sticky note 분기로 교체 — `type: 1`(embedpdf `T.TEXT`), 대상 텍스트 시작 위치(x0, y0)에 고정 크기 18pt 아이콘을 겹쳐 배치. `calloutLine`/`rectangleDifferences`/`intent`/`fontFamily` 등 callout 전용 필드 제거. `DEFAULT_CALLOUT_COLOR` → `DEFAULT_STICKY_NOTE_COLOR`로 변경(값은 동일 보라색 유지).
  - **시스템 프롬프트**: `app/ai-backend/src/chat/route.ts`에서 `add_text_callout` 참조를 `add_sticky_note`로 변경. USER INTENT & ANNOTATION TYPE MAPPING에서 "주석/메모/콜아웃/설명" → `add_sticky_note` 사용하도록 수정. 예시 문구 callout → sticky note로 변경.
  - **백엔드 비전 주석**: `app/backend/core/pdf_annotator.py`의 `build_embedpdf_annotations`에서 `needs_callout` → `needs_sticky_note`로 변경. `_build_callout_annotation` 호출을 `_build_sticky_note_annotation` 호출로 교체. 새 함수는 대상 텍스트 시작 위치에 고정 크기 18pt 아이콘을 배치(빈 영역 탐색/충돌 회피 없음). `TEXT_TYPE = 1` 상수 추가. 레거시 `_build_callout_annotation`/`_find_free_callout_slot`/`_compute_callout_line` 등은 기존 주석 호환성을 위해 유지(현재 dead code).
  - **프롬프트**: `app/backend/core/prompts.py`에서 `margin_note` 설명을 "callout with leader arrow" → "sticky note — memo icon placed on the target text with a comment popup"로 변경. 편집 프롬프트의 `type=highlight|callout` → `type=highlight|sticky`로 변경.
  - **변환기**: `app/backend/core/pdf_annotate_converter.py`의 `is_callout` 분기를 `is_note`로 변경 — sticky note(TEXT=1)와 레거시 callout(FREETEXT/FreeTextCallout) 모두 코멘트 주석으로 취급. 기존 callout 주석도 여전히 편집 가능.
  - **PDF 추출**: `app/backend/core/pdf_user_annotator.py`에 `TEXT = 1` 상수 추가, `EMBEDPDF_TYPE_MAP`에 `PDF_ANNOT_TEXT` → `TEXT` 매핑 추가. `extract_pdf_annotations`에 TEXT 분기 추가(strokeColor/color 설정).
- **검증**: 백엔드 305 tests pass, ai-backend 68 tests pass, tsc 빌드 성공.
- **⚠️ 회귀 방지 경고**:
  1. sticky note는 `type: 1`(embedpdf `T.TEXT`)로 생성된다. 기존 callout 주석(`type: 3` FREETEXT + `intent: FreeTextCallout`)은 더 이상 새로 생성되지 않지만, 기존 주석은 그대로 표시/편집된다. `pdf_annotate_converter.py`의 `is_note` 분기가 두 타입 모두 처리한다.
  2. sticky note 아이콘 크기는 `STICKY_NOTE_ICON_SIZE_PT = 18.0`(pdf_annotator.py)과 `STICKY_NOTE_ICON_SIZE_PT = 18`(annotations.ts)로 고정이다. 두 상수가 다르면 AI 에이전트 주석과 비전 주석의 아이콘 크기가不一致해진다 — 변경 시 양쪽 모두 수정.
  3. sticky note는 대상 텍스트 시작 위치에 **직접 겹쳐 배치**된다. callout처럼 빈 영역을 찾지 않으므로, 텍스트 위에 아이콘이 덮이는 것이 정상 동작이다. 충돌 회피 로직이 필요하면 `_build_sticky_note_annotation`에 별도 추가해야 한다.
  4. `pdf_annotator.py`의 레거시 callout 함수들(`_build_callout_annotation`, `_find_free_callout_slot`, `_compute_callout_line` 등)은 현재 dead code이지만 기존 주석 호환성/테스트 참조를 위해 유지. 제거하려면 `CALLOUT_*` 상수 import하는 테스트도 함께 수정해야 한다.
  5. `AnnotationTarget.callout_color` 필드명은 레거시 이름 그대로 유지(기존 호출 코드 호환성). sticky note 아이콘 색으로 사용된다.
  6. `prompts.py` 편집 프롬프트의 `atype`은 이제 `"sticky"`를 반환한다. LLM이 `type=sticky`로 인식하므로, 편집 프롬프트 형식을 변경하면 LLM이 혼동할 수 있다.
- **핵심 파일**: `app/ai-backend/src/tools/annotations.ts`, `app/ai-backend/src/chat/route.ts`, `app/backend/core/pdf_annotator.py`, `app/backend/core/prompts.py`, `app/backend/core/pdf_annotate_converter.py`, `app/backend/core/pdf_user_annotator.py`, `app/backend/tests/test_pdf_annotator_build.py`.

### 링크 미리보기(OG) 메타 태그 추가 — 2026-07-24

- **배경**: 카카오톡/슬랙/라인 등 메신저 링크 미리보기 카드에서 텍스트만 표시되고 썸네일 이미지가 나오지 않았음. `app/frontend/index.html`에 OpenGraph / Twitter Card 메타 태그가 전혀 없어, 크롤러가 `og:image`를 찾지 못해 썸네일이 비었음.
- **변경 내용**:
  - `app/frontend/index.html`: `<head>`에 OG/Twitter 메타 태그 12개 추가. `og:type=website`, `og:url=https://proof.teamcat.app/`, `og:title`, `og:description`, `og:image=https://proof.teamcat.app/proof-logo.png` (절대 URL, 400×225px), `og:image:width/height`, `og:site_name=PROOF`, `twitter:card=summary_large_image`, `twitter:title/description/image`.
  - `app/frontend/dist/index.html`: `npm run build`로 재빌드하여 동일 태그 반영.
- **검증**: vite build 성공, dist/index.html에 OG 태그 5개 확인.
- **⚠️ 회귀 방지 경고**:
  1. `og:image`는 **절대 URL**이어야 함. 상대경로 `/proof-logo.png`로 변경하면 카카오톡 크롤러가 이미지를 못 불러옴.
  2. 도메인이 `proof.teamcat.app`에서 변경되면 `og:url`, `og:image`, `twitter:image`의 절대 URL을 모두 함께 수정해야 함.
  3. 카카오톡은 링크 미리보기를 캐싱함. 배포 후 기존 공유 링크는 캐시가 갱신될 때까지 옛날 상태로 표시될 수 있음 — 새 링크를 보내거나 크롤러 재방문을 기다려야 함.
  4. `proof-logo.png`는 400×225px(16:9). 카카오톡 최소 조건(200×200)은 만족하지만, 더 선명한 썸네일이 필요하면 1200×630px 전용 OG 이미지를 별도 제작해 교체.
- **핵심 파일**: `app/frontend/index.html`, `app/frontend/dist/index.html`.

### e-Discovery 타임라인 뷰 "Job expired" 조기 만료 수정 — 2026-07-23

- **배경**: 타임라인 뷰와 재분석 버튼이 완료 후 7일이 지나면 "Job expired" 404를 반환했다. `api/ediscovery.py`의 로컬 `_require_job_not_expired`가 `job.expires_at`(완료 후 `download_expire_days=7`일)를 확인한 반면, 나머지 모든 job 엔드포인트는 `api/jobs/_shared.py`의 공유 함수로 `created_at + RETENTION_DAYS(30일)`를 확인했다. 완료 후 7~30일 사이 job은 결과 페이지는 열리지만 타임라인/재분석은 차단되는 불일치가 발생.
- **변경 내용**:
  - `api/ediscovery.py`: 로컬 `_require_job_not_expired`를 공유 `_shared_require_job_not_expired`(`api.jobs._shared._require_job_not_expired`)의 얇은 래퍼로 변경. `created_at + 30일` 기준으로 통일.
  - 테스트 픽스처(`test_api_ediscovery_graph.py`, `test_api_ediscovery_profile.py`): `_make_job`에 `created_at = datetime.now(timezone.utc)` 추가 (공유 만료 판정이 MagicMock 대신 실제 datetime으로 비교하도록).
- **검증**: 백엔드 305 tests pass.
- **⚠️ 회귀 방지 경고**:
  1. `api/ediscovery.py`의 `_require_job_not_expired`는 이제 `created_at + 30일`을 사용한다. `expires_at`(다운로드 링크 만료, 7일)는 더 이상 e-Discovery 접근 제한에 사용되지 않는다. 다운로드 엔드포인드는 여전히 공유 함수를 사용하므로 30일 기준이 일관됨.
  2. ediscovery 테스트에서 `job.created_at`을 반드시 실제 datetime으로 설정해야 한다. MagicMock을 그대로 두면 `datetime.now() >= MagicMock` 비교에서 TypeError 발생.
- **핵심 파일**: `app/backend/api/ediscovery.py`, `app/backend/tests/test_api_ediscovery_graph.py`, `app/backend/tests/test_api_ediscovery_profile.py`.

### v1 개발자 API Office/HWP + docling_refinement 백포트 — 2026-07-23

- **배경**: v1 API가 Office/HWP 형식과 docling_refinement를 지원하지 않아 개발자가 웹 앱 전용 기능에 의존해야 했음. v2의 Office 처리 로직을 v1 결제 모델(points_service)에 맞춰 백포트.
- **변경 내용**:
  - **v1 MEDIA_EXTENSIONS 확장**: `.docx`, `.doc`, `.dotx`, `.docm`, `.pptx`, `.ppt`, `.potx`, `.ppsx`, `.pptm`, `.potm`, `.ppsm`, `.xlsx`, `.xls`, `.xlsm`, `.hwp`, `.hwpx` 추가.
  - **v1 upload_job Office/HWP 처리**: 단일 파일 시 `media_loader.detect_file_type`으로 파일 유형 파악. `DOCLING_TYPES`(PDF/Office)는 `_count_pages_with_docling`으로 페이지 추정 (Docling 비활성화 시 1페이지). `HWP_TYPES`는 `hwp_converter.get_page_count`로 페이지 추정. 멀티파일/아카이브 시에도 DOCLING_TYPES/HWP_TYPES 분기 추가.
  - **v1 `_count_pages_with_docling` 헬퍼 추가**: v2의 동명 헬퍼를 v1에 백포트. Docling 서비스로 페이지 수 추정, 실패 시 1 반환.
  - **v1 `docling_refinement` Form 파라미터 추가**: `upload_job` 시그니처에 `docling_refinement: bool = Form(False)` 추가. `Job.use_docling_refinement` 필드에 저장. `docling_refinement_pages = pages if docling_refinement else 0`로 비용 계산.
  - **v1 confirm_job 비용 계산 수정**: `docling_refinement_pages`를 `calculate_cost`에 전달. `job.file_type in DOCLING_TYPES or HWP_TYPES` 조건으로 단일 문서 시 image/media 카운트 초기화 (v2 `_calculate_media_info`와 동일 로직).
  - **imports 추가**: `asyncio`, `logging`, `docling_client`, `hwp_converter`를 v1 jobs.py에 추가.
  - **문서 갱신**: API.md/API.ko.md/API.ja.md에서 Office/HWP 지원으로 변경, docling_refinement 지원 명시, 가격표에 Office/HWP 페이지 및 Docling refinement 행 추가. file-formats.md, extraction-options.md, pricing.md, upload.md, changelog.md 갱신.
  - **테스트**: `test_v1_jobs_markdown_title_subscription.py`에 4개 테스트 추가 (Office 확장자 포함 확인, .docx 업로드, .hwp 업로드, docling_refinement=true 비용 계산). 총 10개 테스트.
- **검증**: 백엔드 305 tests pass (기존 301 + 신규 4), docs 빌드 3개 언어(en/ko/ja) 모두 성공.
- **⚠️ 회귀 방지 경고**:
  1. v1 `_count_pages_with_docling`은 Docling 서비스가 비활성화되어 있으면 항상 1을 반환한다. 프로덕션에서 Docling 서비스가 활성화되어 있지 않으면 Office 파일이 모두 1페이지로 청구되므로, 실제 페이지 수와 다를 수 있음. v2도 동일한 동작이므로 일관성 유지.
  2. v1 `docling_refinement`는 `Job.use_docling_refinement` 필드에 저장된다. 이 필드는 v2와 공유되므로 v1에서 업로드한 job을 v2 웹 앱에서 확인할 때 docling_refinement 상태가 올바르게 표시됨.
  3. v1 confirm_job의 비용 계산은 v2의 `_subscription_units_from_job` 대신 `points_service.calculate_cost`를 직접 호출한다. v1은 points 기반, v2는 subscription 기반이므로 의도적으로 다른 구현 유지.
  4. v1 upload_job의 `is_single_pdf` 변수명이 `is_single_file` + `single_file_type` 분류로 변경되었다. 단일 PDF뿐 아니라 단일 Office/HWP도 직접 처리 경로로 진입함.
- **핵심 파일**: `app/backend/api/v1/jobs.py`, `app/backend/tests/test_v1_jobs_markdown_title_subscription.py`, `app/API.md`, `app/API.ko.md`, `app/API.ja.md`, `app/docs/docs/core-concepts/file-formats.md`, `app/docs/docs/core-concepts/extraction-options.md`, `app/docs/docs/pricing.md`, `app/docs/docs/api-reference/jobs/upload.md`, `app/docs/docs/changelog.md`.

### v1 개발자 API 동기화 — Markdown 지원 + title rename + subscription 조회 + 문서 정합성 — 2026-07-23

- **배경**: 앱 기능 변화(markdown 업로드, 구독 시스템, title 수정 등)가 v1 개발자 API와 docs에 반영되지 않아 문서-코드 불일치로 개발자가 에러를 만남. API.md가 stale(구식 "P" 단위, 잘못된 가격, Office/HTML 지원 명시하나 v1은 거부, DPI 기본값 150이나 코드는 300).
- **변경 내용**:
  - **v1 Markdown 업로드 지원**: `api/v1/jobs.py`의 `MEDIA_EXTENSIONS`에 `.md` 추가. `upload_job` 파일 분류 루프에 markdown 분기 추가 (페이지/미디어 비용 없이 `total_files`에만 카운트). `run_job`은 이미 markdown 분기가 있으므로 worker 측 변경 불필요. 비용 0.
  - **v1 `PATCH /jobs/{job_id}/title` 추가**: 모든 상태에서 job 표시 이름 수정 가능 (1~200자). `_normalize_display_name` 헬퍼 로컬 추가 (NFC 정규화). `_job_summary` 응답 반환.
  - **v1 `GET /account/subscription` 추가**: `account.py`에 subscription status 조회 엔드포인트 추가. `subscription_service.get_subscription_status` 호출.
  - **문서 정합성 보정**: `API.md`/`API.ko.md`/`API.ja.md` 전면 갱신 — 가격을 milli-USD로 통일, Office/HTML 미지원 명시, Markdown 지원 추가, DPI 기본값 300, `docling_refinement` 미지원 명시, 신규 엔드포인트(title/subscription/convert/action) 문서화, 응답 예시를 v1 실제 필드에 맞춤.
  - **docs 사이트 갱신**: `file-formats.md`에 Markdown 섹션 + Office 미지원 경고 추가. `extraction-options.md` DPI 300 + docling_refinement 미지원 명시. `pricing.md` Markdown 무료 + docling_refinement web-only 표시. `upload.md` 응답 예시 정정 + Markdown 섹션. `changelog.md` 2026-07-23 항목 추가.
  - **신규 docs 페이지**: `api-reference/account/get-subscription.md`, `api-reference/jobs/rename-job.md`. `sidebars.js`에 추가.
  - **테스트**: `tests/test_v1_jobs_markdown_title_subscription.py` 신규 (6개 테스트 — markdown 업로드, MEDIA_EXTENSIONS .md 포함, title rename 성공/빈값/200자초과, subscription 조회). SQLite UUID 호환성을 위해 `UUIDString` TypeDecorator 사용.
- **검증**: 백엔드 301 tests pass (기존 295 + 신규 6), docs 빌드 3개 언어(en/ko/ja) 모두 성공.
- **⚠️ 회귀 방지 경고**:
  1. v1 `PATCH /jobs/{job_id}/title`은 preview 캐시 무효화를 하지 **않음** — v1에는 preview 엔드포인트가 없으므로 불필요. v2의 `rename_job`은 `cache.invalidate_pattern`을 호출하지만 v1은 호출 안 함.
  2. `API.md`/`API.ko.md`/`API.ja.md`는 이제 v1 실제 동작에 맞춤. v1에 새 기능을 추가할 때는 세 파일 모두 업데이트할 것. (참고: Office/HWP/docling_refinement는 후속 백포트로 추가됨 — 위 항목 참조)
- **핵심 파일**: `app/backend/api/v1/jobs.py`, `app/backend/api/v1/account.py`, `app/backend/tests/test_v1_jobs_markdown_title_subscription.py`, `app/API.md`, `app/API.ko.md`, `app/API.ja.md`, `app/docs/docs/core-concepts/file-formats.md`, `app/docs/docs/core-concepts/extraction-options.md`, `app/docs/docs/pricing.md`, `app/docs/docs/api-reference/jobs/upload.md`, `app/docs/docs/api-reference/account/get-subscription.md`, `app/docs/docs/api-reference/jobs/rename-job.md`, `app/docs/docs/changelog.md`, `app/docs/sidebars.js`.

### 마크다운 프리뷰 패널 표시 + 파일 탭 파일명 표시 수정 — 2026-07-23

- **배경**: 마크다운 파일 업로드 시 좌측 프리뷰 패널을 숨겼으나, 원본 마크다운 렌더링을 좌측 패널에서 보여주는 것이 더 유용함. 또한 마크다운 파일의 파일 탭에 원래 파일명이 무시되고 "file"이라고만 표시되는 문제가 있었음.
- **변경 내용**:
  - **마크다운 프리뷰 패널 표시**: `JobResultPage.jsx`에서 `isMarkdownOnly` 변수와 "마크다운 전용 job은 에디터만 전체 너비" 분기를 제거. 마크다운 전용 job도 항상 `PagedResultViewer`를 사용. 패널 토글 버튼에서 `!isMarkdownOnly` 조건 제거.
  - **SourcePanel markdown 타입 처리**: `SourcePanel.jsx`의 `SourceIcon`에 `markdown` 타입 아이콘 추가. `selectedFile.type === "markdown"`일 때 `FilePreview`로 렌더링 (marked → prose HTML).
  - **파일 탭 파일명 표시 수정**: `preview.py`의 병합 로직에서 source_files 항목에 `name` 필드 추가 (`_normalize_display_name` 적용). `SourcePanel.jsx`의 `getDisplayName`에 `file?.filename` fallback 추가.
- **검증**: 백엔드 305 tests pass, 프론트엔드 84 tests pass, vite build 성공.
- **⚠️ 회귀 방지 경고**:
  1. 마크다운 전용 job은 이제 `PagedResultViewer`를 사용하므로, 좌측 패널에서 원본 마크다운이 `FilePreview`로 렌더링되고 우측 패널에서 `SimpleEditor`로 편집 가능. 패널 토글로 각각 숨기기/보이기 가능.
  2. `preview.py`의 병합 로직이 source_files 항목에 `name`과 `filename` 모두 설정한다. 프론트엔드 `getDisplayName`은 `name` → `filename` → `storage_path` → "file" 순서로 fallback.
  3. 백엔드 `_build_source_file_item`에서 markdown 타입을 원본 type("markdown") 그대로 유지한다. `preview.py`에서 extracted_files를 source_files에 병합할 때도 `info.get("type", "")`를 포함한다.
- **핵심 파일**: `app/frontend/src/pages/JobResultPage.jsx`, `app/frontend/src/components/SourcePanel.jsx`, `app/backend/api/jobs/preview.py`.

### HTML/코드 파일 업로드 금지 + 다중 파일 표시 + job title 인라인 수정 — 2026-07-23

- **배경**: HTML/코드 파일은 변환 대상이 아니지만 업로드가 허용되어 있었음. 다중 파일 업로드 시 "N_files.zip"이라는 의미 없는 이름이 표시됨. job 이름을 수정할 수 없었음.
- **변경 내용**:
  - **HTML/코드 파일 업로드 금지**: `UploadWidget.jsx`의 `ACCEPT_TYPES`에서 `.html`, `.htm` 제거. `REJECTED_EXTENSIONS` 세트 추가 (.html, .js, .ts, .py, .css, .json 등 50+ 확장자). `addFiles`에서 거부된 파일을 분리하여 커스텀 모달로 표시 (앱 디자인 시스템 사용 — AlertTriangle 아이콘, surface-container 배경). 백엔드 `_shared.py`의 `MEDIA_EXTENSIONS`에서도 `.html`, `.htm`, `.xhtml` 제거.
  - **다중 파일 "대표파일명 등 N개" 표시**: `uploads.py`의 `upload_job`과 `init_job`에서 다중 파일 시 `original_filename`을 `f"{len(files)}_files.zip"` → `f"{files[0].filename} 등 {len(files)}개의 파일"` 형식으로 변경.
  - **job title 인라인 수정**: 백엔드 `uploads.py`에 `PATCH /api/jobs/{job_id}/title` 엔드포인트 추가 (모든 상태에서 수정 가능, 200자 제한, preview 캐시 무효화). 프론트엔드 `api.js`에 `renameJob` 메서드 추가. `JobResultPage.jsx` 헤더의 h1 title을 클릭하면 input으로 전환, Enter/체크 버튼으로 저장, Escape/X 버튼으로 취소.
  - **i18n**: `page:upload.rejectedTitle`, `page:upload.rejectedDesc`, `page:result.clickToEdit` 키를 ko/en/ja에 추가.
- **검증**: 백엔드 295 tests pass, 프론트엔드 84 tests pass, vite build 성공.
- **⚠️ 회귀 방지 경고**:
  1. `REJECTED_EXTENSIONS`에 새 확장자를 추가하면 해당 파일이 업로드 거부 모달에 표시된다. `.csv`는 거부 목록에 있지만 백엔드 `MEDIA_EXTENSIONS`에는 없으므로 백엔드에서도 거부됨 — 일관성 유지 필요.
  2. `PATCH /api/jobs/{job_id}/title`은 모든 상태에서 호출 가능하다. job이 processing 중일 때 title을 변경해도 처리에는 영향 없음.
- **핵심 파일**: `app/frontend/src/components/UploadWidget.jsx`, `app/frontend/src/api.js`, `app/backend/api/jobs/uploads.py`, `app/backend/api/jobs/_shared.py`, `app/frontend/src/locales/{ko,en,ja}/page.json`.

### 디버그 전용 패널 토글 페이지 라우트 추가 — 2026-07-23

- **배경**: 마크다운 결과 페이지에서 좌·우 패널이 완전히 숨겨지는 문제를 진단하기 위해, 로그인을 우회하고 패널 보이기/숨기기를 독립적으로 테스트할 수 있는 디버그 페이지가 필요함.
- **변경 내용**:
  - `app/frontend/src/main.jsx`: `DebugPanelTogglePage` import 및 `/dev/debug-panel-toggle` 라우트 추가.
  - `app/frontend/src/pages/DebugPanelTogglePage.jsx` (신규): 패널 토글 상태를 독립적으로 제어·시각화하는 디버그 페이지.
- **핵심 파일**: `app/frontend/src/main.jsx`, `app/frontend/src/pages/DebugPanelTogglePage.jsx`.

### 드로잉 도구 키보드 단축키 언어 무관 처리 + 형광펜 설정 분리 + 패널 상태 localStorage 저장 — 2026-07-23

- **배경**: 드로잉 도구 단축키가 한글 입력 모드에서 동작하지 않았고, 펜과 형광펜 색상/굵기가 공유 상태라 전환 시 설정이 초기화됨. 패널 토글 상태도 새로고침 후 유지되지 않았음.
- **변경 내용**:
  - `FlowViewer.jsx`: `e.key` → `e.code`로 변경하여 한/영 입력 언어와 무관하게 단축키 동작 (KeyZ/KeyX/KeyV/KeyP/KeyH/KeyS/KeyT/KeyE/KeyN/KeyL/KeyF).
  - `useFlowDrawing.js`: 펜/형광펜 색상·굵기를 독립 상태로 분리, localStorage 저장하여 새로고침 후에도 유지. 형광펜 기본값 `#eab308`/16px, 펜 `#6366f1`/4px.
  - `DrawingToolbar.jsx` / `DrawingOverlay.jsx`: 형광펜 굵기 컨트롤 분리, 도구 전환 시 해당 도구의 저장된 설정 로드.
  - `JobResultPage.jsx` / `PagedResultViewer.jsx`: 패널 토글 상태를 localStorage에 저장하여 새로고침 후에도 유지.
  - `index.css`: 형광펜 관련 스타일 추가.
- **테스트**: `PagedResultViewer.test.jsx`에 패널 토글 상태 영속성 테스트 추가.
- **핵심 파일**: `app/frontend/src/components/FlowViewer.jsx`, `app/frontend/src/hooks/useFlowDrawing.js`, `app/frontend/src/components/flow/DrawingToolbar.jsx`, `app/frontend/src/components/flow/DrawingOverlay.jsx`, `app/frontend/src/pages/JobResultPage.jsx`, `app/frontend/src/components/PagedResultViewer.jsx`.

### .md 파일 업로드 및 파싱 허용 — markdown 타입 전체 파이프라인 지원 — 2026-07-23

- **배경**: 파일 업로드 시 `.md` 확장자가 `MEDIA_EXTENSIONS`와 프론트엔드 `ACCEPT_TYPES`에 없어 업로드가 차단됨. 마크다운은 텍스트가 그대로 결과이므로 OCR/LLM 처리 없이 파싱 가능.
- **변경 내용**:
  - `app/backend/core/media_loader.py`: `MEDIA_TYPES`에 `"markdown": (".md",)` 추가. `detect_file_type`이 `.md` 파일을 `"markdown"` 타입으로 감지.
  - `app/backend/api/jobs/_shared.py`: `MEDIA_EXTENSIONS`에 `.md` 추가 (업로드 허용). `_build_source_file_item`의 허용 타입 목록에 `"markdown"` 추가, `"file"`과 동일하게 다운로드 URL만 생성. `_analyze_extracted_files`에 markdown 분기 추가 (페이지/미디어 비용 없이 `total_files`에만 카운트).
  - `app/frontend/src/components/UploadWidget.jsx`: `ACCEPT_TYPES`에 `.md` 추가.
  - `app/backend/workers/tasks/job_tasks.py` (`run_job`): 파일 분류 루프에 `markdown_files` 리스트 추가. md 파일은 텍스트를 `read_text(encoding="utf-8")`로 직접 읽어 `file_markdowns_by_name`에 저장 → `result_markdown`으로 사용. `total_to_process`에 markdown 파일 포함. `extracted_info` 구축 시 md 파일을 Storage에 업로드.
  - `app/backend/workers/tasks/job_tasks.py` (`run_job_added_files`): 파일 분류 루프에 markdown 분기 추가. md 파일 텍스트를 직접 `result_markdown`으로 설정, 상태 `done`으로 표시.
  - `app/backend/api/jobs/uploads.py` (`confirm_add_files`): Storage 업로드 섹션에 markdown 분기 추가.
- **비용 모델**: md 파일은 페이지/이미지/오디오/비디오가 0이므로 `_calculate_work_units`가 0을 반환 — 사용자 비용 발생 없음.
- **검증**: `cd app/backend && venv/bin/python -m pytest tests/ -q` → 295 passed. `detect_file_type(Path("test.md"))` → `"markdown"` 확인.
- **⚠️ 회귀 방지 경고**:
  1. `media_loader.detect_file_type`이 `"markdown"`을 반환하므로, 파일 타입 분기에서 `"markdown"`을 명시적으로 처리하지 않으면 "지원하지 않는 파일 타입" 에러가 발생한다. `run_job`과 `run_job_added_files` 모두 markdown 분기를 포함해야 함.
  2. md 파일은 비용이 0이지만 `total_files`에는 카운트되어야 한다. `_analyze_extracted_files`의 markdown 분기를 제거하면 단일 md 업로드 시 `job.total_files = 0`이 될 수 있음.
- **핵심 파일**: `app/backend/core/media_loader.py`, `app/backend/api/jobs/_shared.py`, `app/frontend/src/components/UploadWidget.jsx`, `app/backend/workers/tasks/job_tasks.py`, `app/backend/api/jobs/uploads.py`.

### 결과 페이지 파일탭 업로드 500 오류 수정 — confirm_add_files settings 미임포트 — 2026-07-23

- **증상**: 결과 표시 페이지의 파일 탭 업로드 버튼으로 파일 추가 시 `POST /api/jobs/{id}/confirm-add-files` 가 500 반환. `NameError: name 'settings' is not defined` at `uploads.py:671`.
- **근본 원인**: `app/backend/api/jobs/uploads.py` 의 `confirm_add_files` 가 `settings.data_dir` 을 참조하지만, 해당 모듈은 `from ... import settings_store` 만 임포트하고 `from ...config import settings` 를 임포트하지 않음. `api/jobs.py` 단일 파일에서 패키지로 분할(`api/jobs/`) 시 누락된 임포트. `_shared.py` 에는 `from ...config import settings` 가 있으나 `uploads.py` 로 전파되지 않음.
- **수정 내용**: `app/backend/api/jobs/uploads.py` 에 `from ...config import settings` 추가.
- **검증**: `cd app/backend && venv/bin/python -m pytest tests/ -q -k "uploads or add_files or confirm"` → 3 passed. a1 dev 재배포 후 200 확인 예정.
- **⚠️ 회귀 방지 경고**:
  1. `api/jobs/` 패키지의 각 서브모듈은 자신이 사용하는 심볼을 직접 임포트해야 한다. `_shared.py` 에서 임포트한 심볼이 서브모듈로 전파되지 않는다. 새 서브모듈에서 `settings`, `cache`, `supabase_client` 등을 사용할 때는 반드시 해당 모듈 상단에서 임포트할 것.
- **핵심 파일**: `app/backend/api/jobs/uploads.py`.

### 로컬 데브 모드 마크다운 에디터 AI "Invalid API key" 해결 — VITE_DEV_API_KEY envDir 불일치 수정 — 2026-07-23

- **증상**: 로컬 데브 모드(`npm run dev`)에서 마크다운 에디터의 AI 기능(AiMenu `useCompletion` → `/api/v1/ai/generate`, 에이전트 채팅 `useChat` → `/api/ai/chat`) 사용 시 백엔드가 401 "Invalid API key" 반환.
- **근본 원인**: `vite.config.js`의 `envDir: '..'` 설정으로 인해 Vite는 `app/` 디렉토리의 `.env*` 파일만 로드. 그러나 `VITE_DEV_API_KEY`가 `app/frontend/.env.local`에만 있어 Vite가 로드하지 못함. 결과적으로 `import.meta.env.VITE_DEV_API_KEY`가 `undefined`가 되고, `api.js`·`useAgentChat.ts`·`AiMenu.jsx`의 폴백값 `chu_live_testkey12345` (유효하지 않은 더미 키)가 사용되어 백엔드 `api_key_auth.get_current_api_key`가 401 반환.
- **수정 내용**:
  - `app/.env.development.local`: `VITE_DEV_API_KEY=chu_live_ff9VN9qmUQajrID2FudLB-sYAYwzGs9_rAwy6mUcKxM` 추가. 다른 `VITE_DEV_*` 변수들과 같은 파일에 배치하여 `envDir: '..'` 로 Vite가 정상 로드.
  - `app/frontend/.env.local`: 더 이상 로드되지 않음을 안내하는 주석으로 대체. 혼란 방지.
- **검증**: 잘못된 키 `chu_live_testkey12345` → 401 재현, 올바른 키 → 200 확인. Vite 재시작 후 `import.meta.env.VITE_DEV_API_KEY`에 실제 키 주입 확인.
- **⚠️ 회귀 방지 경고**:
  1. **`vite.config.js`의 `envDir`가 `'..'`(= `app/`)이므로, 모든 `VITE_` 변수는 `app/` 디렉토리의 `.env*` 파일에 있어야 한다.** `app/frontend/.env*`는 Vite에 의해 로드되지 않으므로 `VITE_` 변수를 거기에 두지 말 것.
  2. **`VITE_DEV_API_KEY` 폴백값 `chu_live_testkey12345`는 유효하지 않은 더미 키다.** env 파일에 실제 키가 없으면 마크다운 에디터 AI 및 에이전트 채팅이 401로 실패한다. env 파일 로딩 문제를 의심할 것.
- **핵심 파일**: `app/.env.development.local`, `app/frontend/.env.local`, `app/frontend/vite.config.js` (참조용, 변경 없음).

### 마크다운 에디터 AI 편집 diff 승인 패널 + 에이전트 채팅 UI 개선 — 2026-07-23

- **배경**: 마크다운 에디터의 AI 메뉴(AiMenu)가 AI 생성 결과를 에디터에 즉시 삽입하여 사용자가 변경사항을 사전 검토할 수 없었음. 에이전트 채팅 메시지/도구 UI도 개선 필요.
- **변경 내용**:
  - **`MarkdownDiffApproval.jsx` 신규** (`app/frontend/src/components/ai-chat/`): `diff` 라이브러리의 `diffLines`로 원본·편집본 라인 단위 diff 렌더링 (추가=녹색, 삭제=적색). 수락 시 `api.saveResultPage` 직접 호출 후 승인 콜백, 거부 시 취소. `MarkdownDiffApproval.test.jsx`로 테스트.
  - **`AiMenu.jsx`**: `useCompletion`의 `onFinish`에서 즉시 `applyResultToEditor` 호출 대신 `pendingDiff` 상태로 diff 승인 패널 표시. 사용자 수락 시에만 에디터에 삽입. `continue` 옵션은 빈 원본 사용.
  - **`AgentChatModal.jsx`**: 에이전트 채팅 모달 개선 (컨텍스트 표시, 배경 클릭 닫기 등).
  - **`Message.jsx` / `Messages.jsx` / `Tool.jsx`**: 에이전트 채팅 메시지 렌더링 및 도구 카드 UI 개선. `Messages.test.jsx` 테스트 추가.
  - **`ai-backend/src/tools/markdown.ts`**: 마크다운 도구 로직 개선, `markdown.test.ts` 테스트 확장.
  - **`chat/route.ts`**: AI 백엔드 채팅 라우트 minor 수정.
- **핵심 파일**: `app/frontend/src/components/ai-chat/MarkdownDiffApproval.jsx` (신규), `app/frontend/src/components/AiMenu.jsx`, `app/frontend/src/components/AgentChatModal.jsx`, `app/frontend/src/components/ai-chat/Message.jsx`, `app/frontend/src/components/ai-chat/Messages.jsx`, `app/frontend/src/components/ai-chat/Tool.jsx`, `app/ai-backend/src/tools/markdown.ts`, `app/ai-backend/src/chat/route.ts`.

### PagedResultViewer 패널 토글 — 좌·우 패널 expand/collapse imperative 제어 — 2026-07-23

- **배경**: 마크다운 모드에서 헤더의 좌·우 탭 토글이 내부 `react-resizable-panels` Panel에 전달되지 않아 패널이 열리지/닫히지 않았음.
- **변경 내용**:
  - `app/frontend/src/components/PagedResultViewer.jsx`: `leftPanelOpen` / `rightPanelOpen` prop 추가. Panel에 `ref` + `collapsible` + `collapsedSize={0}` 설정. `useEffect`로 prop 변경 시 `panelRef.expand()` / `panelRef.collapse()` 호출.
  - `app/frontend/src/pages/JobResultPage.jsx`: 패널 토글 상태를 PagedResultViewer에 전달.
- **핵심 파일**: `app/frontend/src/components/PagedResultViewer.jsx`, `app/frontend/src/pages/JobResultPage.jsx`.

### 코드베이스 리팩토링 및 청소 — 대형 파일 분할 + 프론트엔드 번들 최적화 — 2026-07-23

- **배경**: `api/jobs.py` (5005줄)와 `workers/tasks.py` (1632줄)가 단일 파일로 유지보수 어려움. 루트에 산재한 일회성 스크립트/산물 파일들. 프론트엔드 메인 번들 3,350kB로 초기 로드 지연.
- **7단계 리팩토링 (브랜치 `refactor/cleanup-and-split` → develop 머지)**:
  1. **저장소 청소**: 루트 스크립트/산물 20개 삭제, 구 플랜 문서 삭제, `.playwright-mcp/`·`local_dev.db` 추적 해제, `app/backend/` 수동 스크립트를 `scripts/manual/`로 이동. (-7,741줄)
  2. **공통 헬퍼 추출**: `_parse_columns`, `_convert_format_alias`, `_upload_ocr_layout` 3개 중복 함수를 `core/job_helpers.py`로 통합. Test-First로 검증.
  3. **`api/jobs.py` 분할**: 5005줄 단일 파일 → `api/jobs/` 패키지 (9개 모듈). 모든 라우터 경로와 응답 스키마 100% 유지.
  4. **`workers/tasks.py` 분할**: 1632줄 → `workers/tasks/` 패키지 (7개 모듈). Celery `name=` 문자열 100% 유지로 브로커 호환성 보장.
  5. **PDF 좌표 변환 통합 확인**: `core/pdf_coordinate_transform.py` 기반 통합이 이전 커밋에서 완료됨을 확인. 회귀 테스트 17개 통과.
  6. **`api/v1/jobs.py` 중복 분석**: v1 API는 v2와 다른 결제 모델(`points_service` vs `subscription_service`)을 사용하므로 의도적으로 다른 구현. 안전한 통합 대상 아님.
  7. **프론트엔드 청크 최적화**: `vite.config.js`에 `manualChunks` 추가. 메인 청크 3,350kB → 1,361kB (**59% 감소**). PDF 뷰어·3D·TipTap·Supabase 등을 별도 청크로 분리. — ⚠️ 이때 쓴 **객체 형태** `manualChunks` 는 2026-09-04 에 함수 형태로 교체되었다(전이 의존 오염 문제). 아래 "프론트엔드 초기 로드 최적화" 항목이 현재 구조다.
- **패키지 구조**:
  - `api/jobs/`: `__init__.py` (router 조립 + 테스트 호환성 re-export), `_shared.py` (46개 공유 헬퍼), `uploads.py`, `lifecycle.py`, `download.py`, `result.py`, `preview.py`, `annotations.py`, `admin.py`
  - `workers/tasks/`: `__init__.py` (태스크 re-export), `_helpers.py` (7개 비-태스크 헬퍼), `job_tasks.py`, `maintenance.py`, `conversion.py`, `annotation_tasks.py`, `ediscovery_tasks.py`
- **테스트 호환성**: `__init__.py`에서 모든 test-imported 심볼을 re-export. 테스트의 `patch("backend.api.jobs.supabase_client")` 등은 `backend.api.jobs._shared.supabase_client`로 업데이트.
- **검증**: 295 backend tests pass (리팩토링 전후 제로 회귀). develop의 4개 jobs.py 커밋(line-width expansion, paragraph line assignment, Check 5/6/7 validation, search_job_text line mode)이 분할된 모듈에 정상 포팅됨.
- **⚠️ 주의사항**:
  1. `api/jobs.py`와 `workers/tasks.py`는 더 이상 단일 파일이 아님. 새 코드는 적절한 서브모듈에 추가할 것.
  2. `api/jobs/_shared.py`의 헬퍼를 수정할 때는 여러 서브모듈에 영향이 가는지 확인할 것.
  3. 테스트에서 `backend.api.jobs.X`를 patch할 때, X가 `_shared.py`에 있으면 `backend.api.jobs._shared.X`로, `annotations.py`에 있으면 `backend.api.jobs.annotations.X`로 patch 경로를 지정할 것.
  4. Celery 태스크 이름은 `backend.workers.tasks.run_job` 형식을 유지. `@celery.task(name="backend.workers.tasks.xxx")` 데코레이터의 name= 문자열을 변경하지 말 것.
- **핵심 파일**: `app/backend/api/jobs/` (패키지), `app/backend/workers/tasks/` (패키지), `app/backend/core/job_helpers.py`, `app/frontend/vite.config.js`.

### 스캔 PDF 하이라이트 y좌표 어긋남 근본 원인 해결 — OCR layout 좌표계 반전 + 교차 검증 로직 추가 — 2026-07-23

- **증상**: 스캔 PDF를 searchable PDF로 변환 후 하이라이트가 텍스트와 어긋남. 특히 표 행에서 y좌표가 반전되어 아래쪽 행에 달려야 할 주석이 위쪽에 표시됨.
- **근본 원인 (2가지)**:
  1. **`_split_bbox_into_rows` 행 배정 방향 반전** (`app/backend/core/ocr_layout.py`): 표 block_bbox를 행으로 분할할 때 `y0 + i*row_height` (첫 행이 y0에 가깝게)로 배정했으나, 이 bbox는 `_normalize_bbox`에서 y축이 한 번 뒤집힌 "normalized bottom-left" 좌표계이므로, 첫 HTML 행이 y1(큰 값)에 가깝게 배정되어야 변환 후 표의 맨 위에 표시됨. 기존 로직은 표 내부 행 순서가 뒤집히는 버그를 유발.
  2. **`search_job_text` OCR 폴백 불필요한 y반전** (`app/backend/api/jobs.py`): OCR 폴백 요소의 `bbox_pdf`가 `_normalize_bbox`(1차 y반전) + `_normalized_bbox_to_pdf_user`(2차 y반전)를 거쳐 device-space와 동일한 좌표계가 됨에도 불구하고, 추가로 `pdf_user_to_device`(3차 y반전)를 적용하여 y가 반전됨. 총 3번 뒤집혀 홀수 → 반전.
- **수정 내용**:
  - `app/backend/core/ocr_layout.py`: `_split_bbox_into_rows`의 행 배정 공식을 `y0 + i*row_height` → `y1 - (i+1)*row_height` (역순)로 변경. 첫 HTML 행이 raw bbox의 y1(변환 후 표의 맨 위)에 가깝게 배정. `_extract_table_row_items`(`pdf_text_layer.py`)와 동일한 패턴.
  - `app/backend/api/jobs.py`: `search_job_text`의 OCR 폴백 경로에서 `pdf_user_to_device` 변환 제거. `bbox_pdf`는 이미 device-space이므로 추가 변환 없이 그대로 사용. 교차 검증 로직(`_cross_validate_matches_with_ocr_layout`)에서도 동일하게 변환 제거.
  - `app/backend/api/jobs.py`: `_cross_validate_matches_with_ocr_layout` 함수 추가 — `search_for` 결과와 OCR layout 좌표를 교차 검증하여 y 차이가 페이지 높이의 10%를 초과하면 OCR layout y로 보정. 수정 전 코드로 생성된 기존 searchable PDF의 반전된 텍스트 레이어 문제를 런타임에 보정.
- **테스트**:
  - `app/backend/tests/test_split_bbox_into_rows.py`: 6개 테스트 (첫 행이 y1에 가깝게, 마지막이 y0에 가깝게, y 단조 감소, x 보존, 0행, 1행).
  - `app/backend/tests/test_search_job_text_cross_validate.py`: 2개 테스트 (y 보정 적용, y 보정 미적용).
  - `app/backend/tests/test_search_job_text_ocr_fallback_coords.py`: 기존 2개 테스트를 새 좌표계 이해(device-space 직접 반환)에 맞게 업데이트.
- **검증**: `cd app/backend && venv/bin/python -m pytest tests/ -q` → 268 passed. 기존 job(`8c8bef99...`)의 searchable PDF 재생성 후 `search_for` 좌표 확인 — 표 행0(수용기관) y0=178(표 상단), 표 행9(예약일시) y0=562(표 하단)로 HTML 순서와 시각적 위치가 일치. 디버그 페이지(`/dev/debug-highlight-coords`)로 pixel 좌표 시각적 확인.
- **핵심 파일**: `app/backend/core/ocr_layout.py`, `app/backend/api/jobs.py`, `app/backend/tests/test_split_bbox_into_rows.py`, `app/backend/tests/test_search_job_text_cross_validate.py`, `app/backend/tests/test_search_job_text_ocr_fallback_coords.py`.
- **⚠️ 회귀 방지 경고**:
  1. **OCR layout의 `bbox_pdf`는 device-space(y=0 상단)이다.** `_normalize_bbox` + `_normalized_bbox_to_pdf_user`의 이중 y반전 결과이므로, 추가 `pdf_user_to_device` 변환을 적용하면 y가 반전된다. 절대 추가 변환을 적용하지 말 것.
  2. **`_split_bbox_into_rows`의 행 배정은 역순이어야 한다.** raw bbox가 "normalized bottom-left" 좌표계이므로 첫 HTML 행이 y1(큰 값)에 가깝게 배정되어야 변환 후 표의 맨 위에 표시된다. `y0 + i*row_height`가 아니라 `y1 - (i+1)*row_height`를 사용할 것.
  3. **교차 검증 로직은 OCR layout이 device-space라는 전제하에 작동한다.** OCR layout 좌표계가 변경되면 교차 검증 로직도 함께 업데이트해야 함.

### 에이전트 마크다운 편집 미반영 근본 원인 해결 — _get_markdown_content 후보 선택 + JobResultPage loadPreview 수정 — 2026-07-23

- **증상**: 에이전트 도구(`insert_text`/`replace_text` + `apply_edits`)로 마크다운을 편집해도 UI(에디터)에 반영되지 않음. `apply_edits`는 `{"saved":true}`를 반환하지만, 이후 `get_markdown` 및 preview에서 변경사항이 보이지 않음.
- **근본 원인 (2가지)**:
  1. **백엔드 `_get_markdown_content` 후보 선택 로직 버그** (`app/backend/api/jobs.py`): `_marker_count`가 파일 마커(`<!-- 파일 N -->`) 수가 같을 때 page 마커(`<!-- Page N -->`) 수를 tie-breaker로 사용. `save_result_page`는 저장 시 `_PAGE_MARKER_RE.sub`로 page 마커를 제거하므로, 편집본(edited_md)은 파일 마커만 가지고 원본(md)은 파일+page 마커를 가져 원본이 더 높은 점수를 받아 선택됨 → 편집 내용 무시.
  2. **프론트엔드 `JobResultPage.loadPreview`가 원본 마크다운 사용** (`app/frontend/src/pages/JobResultPage.jsx`): `fileMarkdowns`를 `preview.source_files[].result_markdown`(변환 시점 원본)에서 가져왔으나, 이 값은 edited_md가 아님. 백엔드 수정만으로는 preview 응답의 `markdown` 필드는 수정되지만, 프론트엔드가 `source_files[].result_markdown`을 우선 사용하므로 여전히 원본 표시.
- **수정 내용**:
  - `app/backend/api/jobs.py`: `_marker_count`를 `_file_marker_count`로 단순화 — 파일 마커 수만 비교, 같으면 `candidates` 순서상 먼저 추가된 edited_md 우선. page 마커는 tie-breaker에서 제외.
  - `app/frontend/src/pages/JobResultPage.jsx`: `loadPreview`에서 `preview.markdown`(=edited_md 포함)을 `<!-- Page N -->` 마커로 분할하여 `fileMarkdowns`로 사용. `source_files[].result_markdown`은 폴백으로만 사용.
  - `app/backend/tests/test_get_markdown_content_edited_priority.py`: 3개 회귀 테스트 (편집본 우선, 테스트 제목 반영, 원본 우선 조건).
- **디버그 페이지**: `/dev/debug-markdown-agent?jobId={id}` — dev bypass 자동 로그인, 마크다운 에디터 + 에이전트 채팅, 각 단계별 상세 로그 패널 (API 호출/응답, Tiptap 내용, 상태 변화). `app/frontend/src/pages/DebugMarkdownAgentPage.jsx`.
- **검증**: `cd app/backend && venv/bin/python -m pytest tests/ -q` → 260 passed. `cd app/frontend && npx vitest run` → 66 passed. a1 서버 재배포 후 실제 `JobResultPage`에서 에이전트가 추가한 `# 테스트 제목`이 표시됨을 브라우저로 확인.
- **⚠️ 회귀 방지 경고**:
  1. `_get_markdown_content`의 후보 선택 기준을 변경할 때, `save_result_page`가 page 마커를 제거한다는 점을 반드시 고려할 것. page 마커 수를 tie-breaker로 사용하면 편집본이 원본에 우선하지 못함.
  2. 프론트엔드에서 `source_files[].result_markdown`은 변환 시점 원본이지 edited_md가 아님. 에이전트 편집 반영 여부를 확인하려면 `preview.markdown`(=`_get_markdown_content` 결과)을 사용할 것.
- **핵심 파일**: `app/backend/api/jobs.py`, `app/frontend/src/pages/JobResultPage.jsx`, `app/backend/tests/test_get_markdown_content_edited_priority.py`, `app/frontend/src/pages/DebugMarkdownAgentPage.jsx`.

### 스캔 PDF 표 내부 행 순서 반전 근본 원인 해결 — _extract_table_row_items 행 배정 방향 수정 — 2026-07-22

- **진짜 근본 원인 (이전 "search_job_text 좌표계 통일" 수정으로도 해결되지 않았던 문제)**:
  - 사용자 재현: 표에서 아래쪽 행(예: "예약일시")에 달려야 할 주석이 위쪽 행(예: "수용기관") 위치에 표시되고, 그 반대도 발생. 표가 아닌 제목/문단은 정상 표시됨.
  - PyMuPDF `insert_text`/`search_for`는 실제로 **device-space(y=0 상단, y↓)**를 사용함 (공식 문서로 재확인: `page.rect`, `get_text`, `insert_text` 모두 MuPDF 네이티브 top-left 좌표계). 이전 조사에서 `insert_text`로 삽입 후 `search_for`로 재검색하는 방식은 두 함수가 같은 내부 좌표계를 공유한다는 것만 증명하는 순환 검증이었음 — `get_pixmap()` 렌더링으로 직접 확인하여 이를 정정함.
  - `pdf_text_layer._convert_bbox_to_pdf_user`(`normalized_top_left_to_pdf_user`)는 "top-left normalized(y=0 상단)" 입력을 "PDF user-space(y=0 하단)"로 뒤집는 변환을 적용하는데, 이 결과값이 `_insert_invisible_text`를 거쳐 그대로 `page.insert_text()`의 device-space y로 사용됨. **단일 블록(제목, 문단, 푸터)은 "잘못된 가정으로 한 번 뒤집고, 그 결과를 다시 device-space로 잘못 해석"하는 두 번의 오류가 우연히 상쇄되어 절대 위치가 정상으로 보임.**
  - 그러나 `_extract_table_row_items`는 표 bbox를 HTML 행 순서대로 `row_y0 = y0 + i*row_height` (raw y가 작은 쪽부터 첫 행 배정)로 분할하는데, 이 값이 이후 파이프라인을 거치면 **첫 행이 표의 "아래쪽 끝"에, 마지막 행이 표의 "위쪽 끝"에 배치**되어 표 내부에서만 행 순서가 뒤집히는 버그가 발생. 실제 job 데이터로 검증: 표 전체 device-space 범위(165.9~588.6)에서 HTML 첫 행("수용기관")이 546.3(아래쪽 끝)에, 마지막 행이 위쪽에 배치됨을 확인.
  - 이전 커밋(같은 날)에서 시도한 "search_job_text OCR 폴백 좌표계를 device-space로 통일" 수정은 여전히 유효하지만, 이 특정 "표 내부 행 뒤바뀜" 증상의 근본 원인은 아니었음(그 수정은 search_for가 0건일 때만 발동하는 별개의 OCR 폴백 경로에 대한 것이고, 이번 문제는 searchable PDF 생성 자체에서 발생).
- **수정 내용**:
  - `app/backend/core/pdf_text_layer.py`: `_extract_table_row_items`의 행 배정 공식을 `row_y0 = y0 + i*row_height` → `row_y0 = y1 - (i+1)*row_height` (역순)로 변경. 첫 HTML 행이 raw bbox의 `y1`(변환 후 표의 맨 위)에 가깝게 배정되도록 수정.
  - `app/backend/tests/test_extract_table_row_items_order.py`: 표 전체 device-space 범위 대비 첫/마지막 행의 위치, 10행 표에서 y가 HTML 순서대로 단조 증가하는지 검증하는 회귀 테스트 추가.
- **검증**: 실제 job(`8c8bef99...`, "변호인 접견예약 확인증") 데이터로 searchable PDF 재생성 후 `search_for` 좌표 확인 — 표 행0(수용기관) y0=178(표 상단), 표 행9(예약일시) y0=562(표 하단)로 HTML 순서와 시각적 위치가 일치함을 확인. `cd app/backend && venv/bin/python -m pytest tests/ -q` → 249 passed. **사용자가 실제 스캔 PDF에서 표 내부 행 뒤바뀜이 해결되었음을 확인함 (2026-07-22).**
- **핵심 파일**: `app/backend/core/pdf_text_layer.py`, `app/backend/tests/test_extract_table_row_items_order.py`.
- **⚠️ 회귀 방지 경고 (이 좌표계 버그는 2026-07-20~22 사이 여러 차례 재발한 이력이 있음)**:
  1. **`insert_text`/`search_for`가 어느 좌표계인지 검증할 때, 같은 함수 쌍으로 삽입 후 재검색하는 방식은 순환 논리다.** 반드시 `page.get_pixmap()`으로 렌더링한 이미지를 육안/자동으로 확인해 절대 위치를 검증할 것.
  2. **PyMuPDF는 항상 device-space(MuPDF 네이티브, 원점 좌상단, y↓)를 사용한다.** `page.rect`, `get_text()`, `insert_text()`, `search_for()` 전부 동일. "PDF user-space(원점 좌하단, y↑)"로 변환이 필요한 것은 원본 PDF 파일의 `/MediaBox` 등 PDF 스펙 좌표를 직접 다룰 때뿐이다.
  3. **단일 블록(제목/문단/푸터)의 절대 위치가 정상으로 "보인다"고 해서 좌표 변환 체인이 올바르다고 단정하지 말 것.** 두 번의 독립적인 뒤집힘 오류가 우연히 상쇄되어 절대 위치는 맞아도, 행 분할처럼 "상대적 순서"를 다루는 로직에서는 오류가 그대로 드러난다. 반드시 **다중 행/다중 요소의 순서**까지 함께 검증해야 한다.
  4. `_extract_table_row_items`를 다시 수정할 경우, `app/backend/tests/test_extract_table_row_items_order.py`의 두 회귀 테스트(첫 행이 표 상단에, 마지막 행이 표 하단에 위치 / 10행 표에서 y가 단조 증가)를 반드시 통과시킬 것.

### 스캔 PDF 표 내부 y좌표 반전 근본 원인 해결 — search_job_text OCR 폴백 좌표계 통일 — 2026-07-22

- **근본 원인**:
  - `search_job_text` 엔드포인트가 두 경로에서 서로 다른 좌표계를 반환하고 있었음.
    - `search_for` 경로 (PyMuPDF): **device-space(y=0 상단)** 반환. 비표 텍스트는 대부분 이 경로.
    - OCR 폴백 경로 (`build_agent_elements_from_ocr_layout`): **PDF user-space(y=0 하단)** 반환. 스캔 PDF에서 `search_for`가 0건일 때(특히 표 텍스트) 이 경로로 빠짐.
  - 에이전트(`annotations.ts`)는 항상 `input_space='device'`로 저장하므로, OCR 폴백의 PDF user-space 좌표가 device-space로 잘못 해석되어 **y 반전(상하 거울)** 발생.
  - "표에서만 반전" 현상: 표 텍스트가 `search_for`에서 실패하여 OCR 폴백으로 빠지는 빈도가 비표보다 높기 때문 (파이프 구분자, 단어 분할, 텍스트 레이어 누락 등).
- **수정 내용**:
  - `app/backend/api/jobs.py`: `search_job_text`의 OCR 폴백 경로에서 `bbox_pdf`를 `pdf_user_to_device`로 변환하여 device-space로 통일. 응답에 `coordinate_space: "device"` 필드 추가.
  - `app/ai-backend/src/tools/annotations.ts`: 주석/로그를 "PDF user-space"에서 "device-space"로 정정 (실제 코드는 이미 `'device'` 전송).
- **검증**: `cd app/backend && venv/bin/python -m pytest tests/ -q` → 247 passed. `cd app/ai-backend && npm run build` → 성공. `cd app/ai-backend && npm test` → 64 passed. `cd app/frontend && npm run build` → 성공.
- **핵심 파일**: `app/backend/api/jobs.py`, `app/ai-backend/src/tools/annotations.ts`, `app/backend/tests/test_search_job_text_ocr_fallback_coords.py`.

### AI 주석 도구 texts 축약 배치 형식 도입 — 토큰 절약 최적화 — 2026-07-22

- **기능 변경**:
  - `app/ai-backend/src/tools/annotations.ts`: `add_text_highlight` 및 `add_text_callout` 도구에 `texts` (문자열 배열) 파라미터를 추가. 공통 `page_no`/`comment`/`color`/`opacity`를 공유하는 여러 텍스트를 하이라이트할 때 `items` 배열 대신 `texts` 배열 + 공유 파라미터로 호출하여 토큰을 대폭 절약.
    - 이전: `{ items: [{text:"A", page_no:1, color:"yellow", comment:""}, {text:"B", page_no:1, color:"yellow", comment:""}, ...] }` (반복되는 파라미터로 토큰 낭비)
    - 이후: `{ texts: ["A", "B", "C"], page_no: 1, color: "yellow", comment: "" }` (공통 파라미터 1회만 전달)
  - `parseBatchInputs()` 함수의 입력 우선순위를 `texts > items > text[] > text` 순으로 재정의.
  - `app/ai-backend/src/chat/route.ts`: 시스템 프롬프트의 배치 모드 가이드를 `texts` 축약 형식 우선으로 업데이트. `items`는 각 항목마다 다른 설정이 필요할 때만 사용하도록 가이드.
- **하위 호환성**: 기존 `items` 배열, `text` 단일/배열 입력은 모두 그대로 작동.
- **검증**: `cd app/ai-backend && npm run build` → tsc 성공.
- **핵심 파일**: `app/ai-backend/src/tools/annotations.ts`, `app/ai-backend/src/chat/route.ts`.

### 서처블 PDF 라인/단어 BBox 우선 적용 및 단어 분할 텍스트 레이어 배치 — 2026-07-22

- **기능 및 좌표계 밀착 개선**:
  - `app/backend/core/pdf_text_layer.py`:
    1. **[Device-Space 좌표계 100% 보존]**: 검증된 Device-Space(y=0 상단) 좌표계를 전면 보존하여 Y축 반전 회귀 발생 차단.
    2. **[라인/단어 BBox (`overall_ocr_res`) 우선 파싱 강제]**: 표(`table`) 블록 균등 분할 폴백 대신 PaddleOCR의 정밀 라인/단어 BBox(`rec_boxes`)를 최우선 100% 파싱하여 각 셀("형사", "01035172214" 등) 항목 위치에 핀포인트 1:1 배치.
    3. **[띄어쓰기 단어 분할 배치]**: 문장의 단어(`words = text.split(" ")`) 단위로 가로 X좌표를 비례 분할 배치하여 자간 누적 이탈(Kerning Drift)을 완벽 차단.
    4. **[PyMuPDF 글리프 높이 정밀화]**: `fitz.TOOLS.set_small_glyph_heights(True)` 설정 적용.
  - `app/backend/tests/test_pdf_text_layer_baseline.py`: `TestWordSegmentationAndLinePriority` 유닛 테스트 추가 및 통과.
- **검증**: `cd app/backend && venv/bin/python -m pytest tests/ -q` → 245 passed.
- **핵심 파일**: `app/backend/core/pdf_text_layer.py`, `app/backend/tests/test_pdf_text_layer_baseline.py`.

### FreeTextCallout 화살표 리더 라인 연동 및 주석/형광펜 발화 의도 규칙 반영 — 2026-07-22

- **기능 변경**:
  - `app/ai-backend/src/tools/annotations.ts`: `add_text_callout`으로 생성되는 주석 항목에 EmbedPDF 뷰어용 `calloutLine` (3점 꺾은선 `[tip, knee, boxConnection]`) 및 `rectangleDifferences` 좌표와 `lineEnding: 4` (`OpenArrow`) 속성을 완벽하게 보강하여 뷰어에서 본문 텍스트를 가리키는 화살표 주석이 정확히 렌더링되도록 구현함.
  - `app/ai-backend/src/chat/route.ts` & `app/backend/core/prompts.py`: 사용자 요청 발화 의도(Intent) 구분 규칙을 강화함.
    1. 사용자가 **"주석", "메모", "콜아웃", "설명"**으로 요청하는 경우 → **화살표 코멘트 주석 (`add_text_callout`)**을 생성하여 본문 텍스트에 글자가 겹치지 않고 외곽 텍스트 박스로 지시선이 그려지도록 지시.
    2. 사용자가 **"형광펜", "하이라이트", "강조", "색칠"**로 명시하는 경우 → **순수 형광펜 하이라이트 (`add_text_highlight` + `comment: ""`)**를 생성하여 코멘트 오버레이 글자 없이 칠만 적용하도록 규칙 명시.
  - `app/backend/api/jobs.py`: 주석 생성 엔드포인트의 기본 `mode` 디폴트값을 `"highlight"`에서 `"both"`(하이라이트 + 외곽 여백 화살표 콜아웃)로 상향 조정함.
- **검증**: `cd app/ai-backend && npm run build` → tsc 성공, `cd app/backend && venv/bin/python -m pytest tests/ -q` → 241 passed.


### AI 주석 도구 배치(목록) 요청 지원 및 시스템 프롬프트 가이드 갱신 — 2026-07-22

- **기능 변경**:
  - `app/ai-backend/src/tools/annotations.ts`: `add_text_highlight` 및 `add_text_callout` 도구가 `items: [{ text, page_no, comment, color, opacity }]` 목록 배열을 받아 **단 1회의 도구 호출로 N개의 주석을 일괄(Batch) 생성**할 수 있도록 확장함. (단일 `string` 및 `text: [...]` 평탄화 배열 입력과의 하위 호환성 유지)
  - `app/ai-backend/src/chat/route.ts`: LLM 시스템 프롬프트에 `items` 목록 배치를 사용해 한 번에 여러 주석을 일괄 처리하도록 강제 가이드 및 예시 명시.
- **검증**: `cd app/ai-backend && npm run build` → tsc 성공, `cd app/backend && venv/bin/python -m pytest tests/ -q` → 241 passed.

### Supabase Storage PDF 업로드 Content-Type 명시 및 뷰어 바로 다운로드 증상 해결 — 2026-07-22

- **원인 분석**:
  - `app/backend/core/supabase_client.py`의 `upload_input` 함수가 PDF 파일을 Supabase Storage(`pdfs` 버킷)에 업로드할 때 Content-Type을 `"application/octet-stream"`으로 하드코딩하고 있었음.
  - 이로 인해 프론트엔드 PDF 뷰어(`PdfViewer.jsx`)가 서명된 Signed URL을 통해 PDF를 불러올 때, 응답 헤더가 `Content-Type: application/octet-stream`으로 내려와 브라우저가 PDF 문서로 파싱하지 못하고 바로 파일을 다운로드받거나 뷰어 파싱 에러(`"데이터를 불러오지 못했습니다"`)를 일으키던 증상이 유발됨.
- **수정 내용**:
  - `app/backend/core/supabase_client.py`: `_get_content_type` 함수를 확장하여 `.pdf`일 때 `"application/pdf"`, `.json`일 때 `"application/json"` 등 동적 Content-Type을 반환하도록 수정하고 `upload_input`에서 이를 적용함.
- **검증**: `cd app/backend && venv/bin/python -m pytest tests/ -q` → 241 passed.

### AI 주석 y좌표 근본 원인 해결 (PyMuPDF search_for Top-Left 좌표 정규화) — 2026-07-22

- **근본 원인 발견**:
  - PyMuPDF의 `fitz.Page.search_for(text)`가 반환하는 `Rect(x0, y0, x1, y1)`는 표준 PDF User-Space(원점 좌하단, y=0 하단)가 아니라 **이미 Top-Left(Device-Space, y=0 상단)** 좌표계였음.
  - 백엔드의 `pdf_annotate_converter.py` 및 AI 백엔드 도구가 이 `search_for` 결과를 "PDF User-Space"라고 착각하여 `_rect_to_embedpdf_rect` 또는 `save_user_annotations(input_space="pdf_user")`를 거쳐 `y_device = page_height - y` (y-flip)를 한 번 더 적용했음.
  - 그로 인해 상단(예: y=100) 텍스트에 칠해져야 할 주석이 하단(y=742) 거울 반전 위치로 튕겨서 찍히던 증상의 100% 근본 원인이었음.
- **수정 내용**:
  - `app/backend/core/pdf_annotate_converter.py`: `_collect_targets_for_search_phrase` 및 `_collect_targets_with_vision_llm`에서 PyMuPDF `search_for()` 결과를 `AnnotationTarget`에 담을 때 `(x0, page_height - y1, x1, page_height - y0)`로 PDF User-Space 좌표계로 정확하게 정규화하여 `build_embedpdf_annotations`에 전달.
  - `app/ai-backend/src/tools/annotations.ts`: `apply_annotations` 도구가 백엔드로 `saveAnnotations` 호출 시 `input_space='device'`로 전달하도록 정돈.
- **검증**: PyMuPDF `search_for` 반환 좌표 수식적 검증 완료, `cd app/backend && venv/bin/python -m pytest tests/ -q` → 241 passed, `cd app/ai-backend && npm run build` → 성공.

### AI 주석 y좌표 반전 원인 해결 및 뷰어 device-space 좌표계 보장 — 2026-07-22

- **원인 분석**:
  - `get_job_result_json(kind="annotations")` 및 `get_job_annotations` API가 Storage에 저장된 device-space(y=0 상단) 주석 JSON을 프론트엔드/뷰어로 반환할 때, `pdf_user_annotator._convert_annotations_to_pdf_user`를 불필요하게 실행하여 PDF user-space(y=0 하단) 좌표계로 다시 반전시켜 보내고 있던 문제가 원인이었음.
  - 프론트엔드 뷰어(`PdfViewer.jsx`)는 device-space(y=0 상단) 좌표를 기대하므로, 이 반환값(`origin.y = 800`)을 그대로 렌더링하면서 주석이 최하단(상하 거울 반전 위치)에 찍히던 증상이 발생했음.
  - `pdf_annotator.py` 및 `pdf_user_annotator.py`의 `fitz.Rect` 생성 시 `page_x0 + page_height` 오타로 인해 비정방형 페이지에서 좌표 왜곡이 유발되던 2차 버그도 함께 수정.
- **수정 내용**:
  - `app/backend/api/jobs.py`: `get_job_result_json`에서 `_convert_annotations_to_pdf_user` 호출 제거하여 뷰어용 device-space 주석을 있는 그대로 반환. `/jobs/{job_id}/annotations` API에 `space` 파라미터(기본값 `"device"`)를 추가하여 `space="pdf_user"` 일 때만 PDF user-space로 변환.
  - `app/backend/core/pdf_annotator.py` 및 `app/backend/core/pdf_user_annotator.py`: `fitz.Rect(page_x0, page_y0, page_x0 + page_height, page_y0 + page_height)` 오타를 `page_x0 + page_width`로 정정 및 `page_width` 선택적 수신 지원.
  - `app/ai-backend/src/lib/proof-api.ts`: Node.js AI 에이전트 도구가 기존 주석을 조회할 때 `space=pdf_user`를 요청하도록 업데이트.
- **검증**: `cd app/backend && venv/bin/python -m pytest tests/ -q` → 241 passed, `cd app/ai-backend && npm run build` → 성공, `cd app/frontend && npm run build` → 성공.
- **핵심 파일**: `app/backend/api/jobs.py`, `app/backend/core/pdf_annotator.py`, `app/backend/core/pdf_user_annotator.py`, `app/ai-backend/src/lib/proof-api.ts`, `app/backend/tests/test_pdf_text_layer_baseline.py`, `app/backend/tests/test_jobs_result_json_annotations.py`.


### 프로 요금제 크레딧 혜택 상향 및 충전 크레딧 일치화 — 2026-07-21

- **프로 요금제 월간 혜택 크레딧 인상**:
  - `app/backend/core/subscription_service.py` 및 `app/frontend/src/pages/PricePage.jsx`에서 프로 요금제의 제공 크레딧을 기존 20,000pt에서 30,000pt(1.5배)로 인상.
  - `app/backend/tests/test_subscription_credits.py` 테스트 코드를 30,000pt에 맞도록 수정 및 검증 완료.
- **프로 요금제 사용 가이드 추가 및 UI 단위 통일**:
  - `app/frontend/src/components/PlanCard.jsx` 카드 하단에 30,000 크레딧에 대한 대략적 예상 사용 가이드(예: 일반 분석 최대 30,000페이지, 고급 비전 분석 최대 6,000페이지)를 다국어로 노출.
  - 기존에 하드코딩 노출되던 `pt` 단위 접미사를 다국어 리소스 `t("common:points.point")`를 사용하여 `크레딧`(Ko), `credits`(En), `クレジット`(Ja)으로 일괄 대응 및 통일.
- **충전 금액 및 크레딧 비율 일치**:
  - `app/frontend/src/pages/PaymentPage.jsx`의 충전 입력창 및 예상 획득 크레딧 정보를 1달러 = 1,000크레딧(1milli-USD = 1크레딧)과 일치하게 수정하여 "20,000 크레딧 충전하기" 와 같이 표시되도록 변경.
- **핵심 파일**: `app/backend/core/subscription_service.py`, `app/backend/tests/test_subscription_credits.py`, `app/frontend/src/pages/PricePage.jsx`, `app/frontend/src/components/PlanCard.jsx`, `app/frontend/src/pages/PaymentPage.jsx`, `app/frontend/src/locales/{ko,en,ja}/page.json`.

### Develop branch fixes — 2026-07-20

- **검색 가능 PDF 텍스트 레이어 y축 반전 수정** (`app/backend/core/pdf_text_layer.py`):
  - `add_text_layer_from_ocr()`이 OCR bbox를 PDF user-space로 변환할 때 points/pixel top-left 좌표계를 지원하지 않아 발생하던 y축 반전 버그를 수정.
  - `_convert_bbox_to_pdf_user()`를 추가해 `normalized`/`points`/`pixel`/`pdf_user_space` 좌표계를 자동 감지하고, `layout`의 `width`/`height` 또는 `dpi`를 이용해 PDF user-space로 변환.
  - `app/backend/tests/test_pdf_text_layer_baseline.py`에 points top-left 회귀 테스트를 추가.
- **사용자 주석 저장 fallback 보강** (`app/backend/api/jobs.py`):
  - `save_user_annotations()`에서 `annotated_pdf_files` entry가 없어도 404를 반환하지 않고 `user_annotations_{source_index}.json` 경로로 fallback, AI/사용자 주석 병합 조건도 entry 존재 여부로 판단.
- **개발 환경 TUS 업로드/프록시 수정** (`app/frontend/src/tusUpload.js`, `app/frontend/vite.config.js`):
  - `tusUpload.js`에서 Supabase 세션 대신 `getToken()`을 사용해 개발 환경 dev bypass 토큰을 우선 사용.
  - `vite.config.js`에서 `/supabase` 프록시 대상을 `VITE_DEV_SUPABASE_URL` 환경변수 기반으로 설정, `VITE_DEV_SUPABASE_URL`이 없으면 백엔드 서버로 fallback.
- **검증**:
  - `cd app/backend && .venv/bin/python -m pytest tests/ -q` → 232 passed.
  - `cd app/frontend && npm run build` → 성공.
- **배포 시 주의**: 백엔드 Docker 컨테이너 재배포 필요. 기존 `searchable.pdf`는 반전된 채 남아 있을 수 있으므로 필요시 재생성.

### AI Annotation Agent Tool Audit — text-only workflow 및 좌표 redaction

- **목표**: AI 채팅 에이전트가 여전히 `get_elements`/`search_text`의 `bbox_pdf`나 `add_highlight`/`save_annotations` 같은 구식 tool로 rect를 조립하려는 문제를 완전히 차단. LLM은 "강조할 텍스트 내용"만 식별하고, 모든 bbox/segmentRects 결정은 백엔드가 검색해서 수행.
- **Phase 1: AI tool 출력에서 좌표 제거** (`app/ai-backend/src/tools/annotations.ts`):
  - `search_text`, `get_elements`, `compare_elements`는 `page_no`, `text`, `kind`만 반환. `bbox_pdf` 및 위치 정보를 모델에 노출하지 않음.
  - `get_annotations`, `read_job_json(kind="annotations")`는 `rect`, `segmentRects`, `calloutLine`, `bbox_pdf`를 REDACTION하여 반환. `id`, `type`, `pageIndex`, `color`, `contents`만 남김.
  - `view_page`는 텍스트 분석만 반환하며 좌표/위치가 포함되지 않음을 명시.
- **Phase 2: text-only annotation tool 교체** (`app/ai-backend/src/tools/annotations.ts`):
  - `add_highlight`/`add_callout` 제거, `add_text_highlight`/`add_text_callout` 추가.
  - 입력은 `text`, `page_no`(선택), `comment`, `color`, `opacity`(선택)뿐. 내부에서 `searchText`로 텍스트 레이어를 검색해 `bbox`를 자동 결정.
  - `add_text_highlight`는 동일 텍스트의 모든 발생 위치를 `segmentRects`로 highlight. `add_text_callout`은 첫 매치를 가리킴.
  - `save_annotations` tool 제거. `apply_annotations`가 pending을 저장.
- **Phase 3: 시스템 프롬프트 강화** (`app/ai-backend/src/chat/route.ts`):
  - tool 목록에서 `add_highlight`/`add_callout`/`save_annotations` 제거.
  - "OLD TOOLS REMOVED" 문구 추가: `add_highlight`, `add_callout`, `save_annotations`는 더 이상 존재하지 않으며, `rect/bbox`를 수동으로 계산/전달하면 안 된다고 강조.
  - `search_text`/`get_elements`/`compare_elements`/`view_page`는 좌표 없이 텍스트/분석만 제공함을 명시.
- **검증**: `cd app/ai-backend && npm run build` → tsc 성공. a1 서버 배포 완료 및 `ai-backend` 컨테이너 `Up` 확인.
- **배포 시 주의**: `ai-backend` 재배포 필요. 프론트엔드/DB 변경 없음.
- **핵심 파일**: `app/ai-backend/src/tools/annotations.ts`, `app/ai-backend/src/chat/route.ts`.


### AI Annotation Text-Only + Searchable PDF Guarantee — 모든 PDF를 PaddleOCR로 searchable 변환 및 LLM 위치값 제거

- **목표**: 텍스트 레이어가 없는 스캔 PDF를 포함한 **모든 PDF**가 PaddleOCR을 거쳐 searchable PDF가 되도록 보장하고, AI 주석 생성 시 LLM이 위치/좌표/`element_index`/bbox를 전혀 고려하지 않고 "강조할 텍스트 내용"만 반환하도록 한다. 백엔드가 `TextLayerSearcher`로 해당 텍스트를 검색해 모든 발생 위치를 `segmentRects`로 highlight.
- **Phase 1: 프롬프트 정리** (`app/backend/core/prompts.py`):
  - `build_element_highlight_prompt`, `build_row_highlight_prompt` 삭제.
  - `build_vision_bbox_highlight_prompt`를 `build_vision_text_highlight_prompt`로 변경: 이미지를 보고 `text`만 반환.
  - `build_text_search_highlight_prompt`를 범용 text-only prompt로 유지/강화.
- **Phase 2: `pdf_annotate_converter.py` 통합**:
  - `_ensure_searchable_pdf()` 추가: `job.searchable_pdf_storage_path`가 없으면 `_collect_page_elements()`로 PaddleOCR 수행 → corrected images → `add_text_layer_from_ocr()` → searchable PDF 업로드.
  - `run()`의 `advanced` 여부와 상관없이 searchable PDF를 먼저 확보하고, `advanced=True`는 Vision LLM이 `text`만 반환, `advanced=False`는 페이지 텍스트에서 `text`를 반환.
  - `_collect_targets_with_vision_llm()` 수정: Vision LLM이 `text`만 반환하면 `TextLayerSearcher.search()`로 해당 페이지에서 bbox 검색.
  - `_select_elements_with_llm`, `_matches_to_targets`, `_narrow_bbox_by_scope` 등 위치 기반 선택 로직 제거.
- **Phase 3: `pipeline_vision.py` PaddleOCR 강제**:
  - `fallback_controller` 의존 제거, LLM vision fallback 제거.
  - 10페이지 이하 PDF는 `convert_pdf_with_layout` 직접, 11페이지 이상은 렌더링 후 `convert_images_batch_with_layout` 또는 `convert_image_with_layout` per-page.
- **Phase 4: `workers/tasks.py` searchable PDF 복구 강화**:
  - `_build_and_upload_searchable_pdf()`에서 `layout_by_page`가 비어 있을 경우 `paddleocr_client.convert_pdf_with_layout()`로 직접 layout을 복구하는 방어 로직 추가.
- **Phase 5: `paddleocr_client.py` 중복 함수 정리**:
  - `convert_pdf_with_layout`이 두 번 정의되어 있던 문제 수정 (shadowing 제거). 모든 호출자가 per-page `(markdown, layout, angle_code)` tuple list를 반환하는 단일 함수를 사용하도록 정리.
- **Phase 6: 테스트 및 디버그 스크립트**:
  - `app/backend/tests/test_pdf_annotate_converter_run.py`:
    - `TestAnnotationPromptsAreTextOnly`: 모든 annotation prompt가 text 기반이고 위치값을 요구하지 않음을 검증.
    - `TestScannedPdfTextSearchPipeline`: searchable PDF가 없는 스캔 PDF에서 LLM이 `text`만 반환하면 backend가 검색해 highlight.
    - `test_run_advanced_vision_returns_text_only`: `advanced=True` Vision LLM이 `text`만 반환하면 backend가 검색.
  - `app/backend/test_annotate_compare.py`: text-only prompt와 OCR bbox 검색 방식으로 갱신.
- **Phase 7: searchable PDF 텍스트 레이어 y축 반전 버그 수정** (`app/backend/core/pdf_text_layer.py`):
  - `add_text_layer_from_ocr()`에서 OCR bbox 좌표계를 PDF user-space로 변환할 때 normalized 외 points/pixel top-left 좌표계를 지원하지 않아, 텍스트 레이어가 페이지 상하로 반전되어 삽입되던 문제 수정.
  - `_convert_bbox_to_pdf_user()` 헬퍼 추가: `_coordinate_system` 메타데이터와 `layout`의 `width`/`height`를 이용해 normalized, points, pixel, pdf_user_space 좌표계를 자동 감지/변환. `dpi` 파라미터도 `_insert_text_layer_into_doc()`에 전달.
  - `app/backend/tests/test_pdf_text_layer_baseline.py`에 points top-left 회귀 테스트 추가.
- **검증**: `cd app/backend && .venv/bin/python -m pytest tests/ -q` → 232 passed.
- **배포 시 주의**: 백엔드 Docker 재배포 필요. 이전 코드로 생성된 `searchable.pdf`는 여전히 상하 반전된 채 남아 있으므로, 새로 생성하거나 `searchable_pdf_storage_path`를 삭제 후 재생성해야 화면에서 바르게 보임. 프론트엔드/DB 변경 없음. `advanced` 모드는 여전히 Vision LLM을 호출하지만 위치값 대신 텍스트 내용만 반환. PaddleOCR 장애 시 `run_vision` 및 searchable PDF 생성이 실패할 수 있음.
- **핵심 파일**: `app/backend/core/prompts.py`, `app/backend/core/pdf_annotate_converter.py`, `app/backend/core/pdf_text_layer.py`, `app/backend/core/pipeline_vision.py`, `app/backend/core/paddleocr_client.py`, `app/backend/workers/tasks.py`, `app/backend/tests/test_pdf_annotate_converter_run.py`, `app/backend/test_annotate_compare.py`, `app/backend/tests/test_pdf_text_layer_baseline.py`.

### IRAC Argument Map — 쟁점/주장/근거 3단계 행렬 + 원문 스크롤 연동 뷰 모드

- **목표**: `JobResultPage`에 신규 "IRAC 공방 맵" 뷰 모드를 추가. Issue-Claim Tree API(`/legal-issue-tree`, `/legal-issue-tree/mappings`) 데이터를 좌우 분할 행렬(쟁점 ↔ 주장 ↔ 근거)로 시각화하고, 증거 클릭 시 `SourcePanel.scrollToPage`로 원본 PDF 해당 페이지로 스크롤 연동.
- **Phase 1: 신규 컴포넌트** (`app/frontend/src/components/irac/IracArgumentMap.jsx`):
  - `getIssueTreeMappings`로 저장된 트리 로드 → 없으면 청구 원인 입력 후 `getLegalIssueTree`로 추출.
  - 쟁점(Issue) → 주장(Claim) → 근거(Evidence) 3열 행렬 렌더링. 원고/피고 주장을 `party` 키워드로 분류.
  - 증거/주장/쟁점 클릭 시 우측 슬라이드인 상세 패널 + "원본 PDF 보기" 버튼 → `onNodeClick` 콜백으로 `SourcePanel` 해당 파일/페이지 스크롤.
  - Proven/Contested/Weak 상태 뱃지는 `mapped_evidence` 개수 기반 휴리스틱 표시.
- **Phase 2: JobResultPage 통합** (`app/frontend/src/pages/JobResultPage.jsx`):
  - `previewMode`에 `"irac"` 추가. 뷰 모드 드롭다운에 IRAC 메뉴(`Scale` 아이콘) 추가.
  - `renderRightContent`에 `irac` 분기 추가 — `onNodeClick`에서 `node.data.original_page`/`source_file`로 `sourcePanelApiRef.current.scrollToPage({ fileIndex, pageNum })` 호출.
- **Phase 3: i18n** (`app/frontend/src/locales/{ko,en,ja}/page.json`): `irac`, `iracTitle`, `iracExtract`, `iracPlaintiff`, `iracDefendant`, `iracContention`, `iracEvidence`, `iracStatusProven`, `iracStatusContested`, `iracStatusWeak`, `iracDetailTitle` 등 23개 키 추가.
- **검증**: 프론트엔드 `npm run build` 성공, `npm run test` 14 passed.
- **배포 시 주의**: 백엔드 변경 없이 기존 `/legal-issue-tree` API 재사용. DB 마이그레이션 불필요.
- **핵심 파일**: `app/frontend/src/components/irac/IracArgumentMap.jsx`, `app/frontend/src/pages/JobResultPage.jsx`, `app/frontend/src/locales/{ko,en,ja}/page.json`.

### e-Discovery Timeline 단일화 — React Chrono 3.x alternating + 상세 카드 통합

- **목표**: 기존 "상단 재분석 버튼 + 중앙 양측 주장/증거 카드 + 하단 수평 타임라인 스트립" 3단 구조를 단일 React Chrono 3.x 수직 alternating 타임라인으로 단순화. 코드 중복 제거 및 인지 과부하 감소.
- **의존성 업그레이드**: `app/frontend/package.json` — `react-chrono` 2.6.1 → `^3.3.0`.
- **Phase 1: 삭제 컴포넌트** (`app/frontend/src/components/timeline/`):
  - `CourtroomColumn.jsx`/`.test.jsx`, `EdiscoveryTimelineStrip.jsx`/`.test.jsx`, `ResizableCourtroomCards.jsx`/`.test.jsx` 제거 — 양측 카드/수평 스트립/리사이즈 래퍼 기능이 Chrono 기본 UI로 흡수.
  - `app/frontend/src/utils/ediscoveryTimelineUtils.js`(`classifyNodesBySide`), `app/frontend/src/utils/ediscoveryToTimeline.js` 제거 — 변환 로직이 `EdiscoveryTimelinePanel` 내부로 인라인.
- **Phase 2: EdiscoveryTimelinePanel 재작성** (`app/frontend/src/components/timeline/EdiscoveryTimelinePanel.jsx`):
  - `<Chrono mode="VERTICAL_ALTERNATING">`로 전체 영역 렌더링. `media` prop으로 썸네일/이미지 표시.
  - 카드/타이틀/포인트 클릭 시 상위 `onItemClick(node)` 콜백 → 미리보기 패널 + SourcePanel 연동.
  - `applyIssueDimmingToNodes`/`sortByDateOrPage` 헬퍼 제거, `getNodePage`/`findSourceFile` 헬퍼 추가.
  - 폴링 로직(재분석)은 `EDiscoveryViewer`로 이동.
- **Phase 3: 신규 컴포넌트** (`app/frontend/src/components/timeline/`):
  - `EdiscoveryDetailCard.jsx` — 선택 노드 + 미리보기 메타데이터 + 원문 텍스트를 좌우 분할 카드로 표시. 드래그 핸들로 좌우 비율 조절. `marked`로 원문 렌더링, 페이지 마커 제거.
  - `TimelinePreviewCard.jsx` — 노드 미리보기 썸네일 카드.
- **Phase 4: EDiscoveryViewer 고도화** (`app/frontend/src/components/EDiscoveryViewer.jsx`):
  - 헤더 재분석 버튼 + 컨텍스트 입력 팝업 + 폴링(`POLL_TIMEOUT_MS=600000`, `POLL_INTERVAL_MS=2000`) 추가.
  - `preview API`로 `source_files` 로드하여 자식 컴포넌트에 전달.
  - `previewNode` 상태로 상세 카드 표시, 원문 `result_markdown` 렌더링.
  - `onJobRefresh` prop 추가 — 재분석 완료 시 상위 `loadJob` 호출.
- **Phase 5: DevEdiscoveryTimelinePage 단순화** (`app/frontend/src/pages/DevEdiscoveryTimelinePage.jsx`):
  - `EdiscoveryTimelineStrip` 직접 렌더링 제거 → `EdiscoveryTimelinePanel`에 `SAMPLE_JOB` 전달.
- **Phase 6: DevEdiscoveryPage** (`app/frontend/src/pages/DevEdiscoveryPage.jsx`): `onJobRefresh={() => Promise.resolve()}` prop 추가.
- **Phase 7: index.css 정리** (`app/frontend/src/index.css`): `ediscovery-chrono` 관련 커스텀 CSS(가로 스크롤, 카드 높이 제한, React Chrono 기본 여백 오버라이드) 제거.
- **검증**: 프론트엔드 `npm run build` 성공, `npm run test` 14 passed.
- **배포 시 주의**: 프론트엔드 전용 변경. 백엔드/DB 변경 없음.
- **핵심 파일**: `app/frontend/src/components/timeline/EdiscoveryTimelinePanel.jsx`, `app/frontend/src/components/timeline/EdiscoveryDetailCard.jsx`, `app/frontend/src/components/timeline/TimelinePreviewCard.jsx`, `app/frontend/src/components/EDiscoveryViewer.jsx`, `app/frontend/src/pages/DevEdiscoveryTimelinePage.jsx`, `app/frontend/src/pages/DevEdiscoveryPage.jsx`, `app/frontend/src/index.css`, `app/frontend/package.json`.

### SimpleEditor 고도화 — TOC 미니맵 사이드바 (토글 헤딩은 미구현)

- **목표**: TipTap 에디터에 우측 TOC(목차) 미니맵 사이드바를 추가. 긴 문서 작성 시 탐색성 개선. (원래 노션 스타일 "제목 토글로 아래 본문 숨기기/보이기" 기능도 계획했으나 **현재 미구현** — `CollapsibleHeading.jsx`가 생성되지 않았고 `expandAllHeadings`/`collapseAllHeadings` 헬퍼, `ChevronsDownUp`/`ChevronsUpDown` 툴바 버튼, `.collapsible-heading-wrapper` CSS도 없음.)
- **의존성 추가** (`app/frontend/package.json`):
  - `@tiptap/extension-heading@^3.27.1` — 커스텀 헤딩 확장 베이스.
  - `@tiptap/extension-table-of-contents@^3.27.1` — TOC anchor 수집.
  - `@tiptap/extension-unique-id@^3.27.1` — 헤딩에 고유 id 부여(TOC 스크롤 대상).
- **구현됨 — TocSidebar 컴포넌트** (`app/frontend/src/components/editor/TocSidebar.jsx`):
  - `TableOfContents` 확장의 `onUpdate`에서 anchors 배열 수신.
  - heading depth별 들여쓰기 + 활성 heading 하이라이트. 클릭 시 해당 heading id로 `scrollIntoView`.
  - 펼침/접힘 토글 버튼.
- **구현됨 — SimpleEditor 통합** (`app/frontend/src/components/SimpleEditor.jsx`):
  - `TableOfContents.configure({...})` + `UniqueID` 확장 추가.
  - 레이아웃을 `flex`로 변경 — 좌측 에디터 콘텐츠 + 우측 `TocSidebar`.
- **미구현 — CollapsibleHeading**: `app/frontend/src/components/editor/CollapsibleHeading.jsx`가 생성되지 않았음. `heading` 노드의 `collapsed` attribute, ProseMirror plugin 형제 블록 숨김, `expandAllHeadings`/`collapseAllHeadings` 헬퍼, 토글 버튼, `.collapsible-heading-wrapper` CSS 모두 미구현.
- **Phase 6: 신규 에셋** (`app/frontend/public/assets/`): `audio-thumbnail.svg`, `pdf-thumbnail.svg` — 미디어 타입 썸네일.
- **검증**: 프론트엔드 `npm run build` 성공, `npm run test` 14 passed.
- **배포 시 주의**: 프론트엔드 전용 변경. 백엔드/DB 변경 없음.
- **핵심 파일**: `app/frontend/src/components/editor/TocSidebar.jsx`, `app/frontend/src/components/SimpleEditor.jsx`, `app/frontend/src/index.css`, `app/frontend/package.json`, `app/frontend/public/assets/audio-thumbnail.svg`, `app/frontend/public/assets/pdf-thumbnail.svg`.

### 통합 크레딧(포인트) 시스템 마이그레이션 — 페이지/오디오/비디오/에이전트 스텝 통합 과금

- **목표**: 기존 개별 사용량 제한(기본/프리미엄 페이지, 오디오/비디오 초)을 하나의 `points_balance` 크레딧 잔액으로 통합. 페이지/오디오/비디오/AI 에이전트 스텝 모두 포인트에서 차감되며, 월간 구독으로 크레딧을 지급한다.
- **크레딧 비율**: 기본 모델 페이지 1pt, 프리미엄 모델 페이지 5pt, 오디오 1pt/초, 비디오 10pt/초, Docling 후처리 페이지 3pt, AI 에이전트 스텝 1pt/스텝.
- **월간 구독 크레딧**: Free 1,000pt, Pro 30,000pt, Max 100,000pt.
- **Phase 1: DB 마이그레이션 & 백엔드 코어** (`app/backend/db/migrations/036_credit_system_subscription.sql` 신규):
  - `users` 테이블에 `subscription_credits_granted_at` 컬럼 추가 (중복 지급 방지).
  - `jobs` 테이블에 `cost_points`, `xlsx_advanced_cost_points`, `annotate_cost_points`, `ediscovery_cost_points` 컬럼 추가.
  - `app_settings`에 `cost_premium_video_sec_krw=10`, `cost_agent_step_krw=1` 반영.
  - `app/backend/core/points_service.py`: 비디오 10pt, 에이전트 스텝 1pt, Docling 후처리 3pt 비용 계산. 일일 무료 기본 페이지 로직 제거.
  - `app/backend/core/subscription_service.py`: `points_balance` 기반 `check_enough`, `reserve_usage`, `release_usage`, 월간 크레딧 지급, 구독 상태 조회.
  - `app/backend/workers/tasks.py` + `celery_app.py`: `grant_monthly_subscription_credits` Celery beat 태스크 추가.
- **Phase 2: API/Job 통합**:
  - `app/backend/api/v1/agent.py` (신규): `POST /api/v1/agent/steps` — AI 백엔드가 총 스텝 수를 보고하면 `X-AI-Backend-Secret` 검증 후 포인트 차감.
  - `app/backend/api/jobs.py`: `reserve_usage`/`release_usage`를 포인트 기반으로 변경, `GET /api/jobs/{job_id}` 응답에 `cost_basic`/`cost_premium`/`cost` 및 `subscription` 잔액/예상 비용 포함.
  - `app/backend/api/v1/jobs.py`: API 업로드/확인/환불 시 포인트 기반으로 변경, `calculate_cost`에서 `user_id` 인자 제거.
  - `app/backend/api/auth.py`: 사용하지 않는 `POST /api/auth/agent/spend-step` 제거.
- **Phase 3: AI 백엔드** (`app/ai-backend/src/lib/proof-api.ts`, `app/ai-backend/src/chat/route.ts`):
  - `spendAgentSteps(userId, steps, description)` 메서드 추가. `AI_BACKEND_SECRET` 환경변수로 `POST /api/v1/agent/steps` 호출.
  - `chat/route.ts`에서 `onStepFinish`당 1pt씩 차감하던 로직을 제거하고, `streamText` `onFinish`에서 `steps.length`로 총 스텝을 집계해 비동기 차감.
- **Phase 4: 프론트엔드 UI/UX**:
  - `PricePage.jsx` + `PlanCard.jsx`: 요금제 카드를 월간 크레딧 기준으로 표시.
  - `JobConfirmPage.jsx`: 잔여 포인트, 예상 비용, 차감 후 잔액 표시. 기존 페이지/미디어 잔여량 UI 제거.
  - `DashboardPage.jsx` + `SettingsPage.jsx`: 포인트 잔액 표시.
  - `ko/en/ja/page.json` 및 `common.json`: 포인트 단위 `$` → `pt` 변경 후 최종 크레딧(credits/クレジット)으로 통일.
- **검증**: `pytest tests/` 134 passed, AI 백엔드 `npm run build` 성공, 프론트엔드 `npm run test` + `npm run build` 성공. `test_points_service.py`, `test_subscription_credits.py`, `test_agent_steps.py` 추가.
- **배포 시 주의**: DB 마이그레이션 `036_credit_system_subscription.sql`을 `supabase-chungu-db` 컨테이너에 수동 적용. AI 백엔드(`.env`)에 `AI_BACKEND_SECRET` 추가, 백엔드 `config`에 동일값 설정. `deploy_a1.sh`로 a1 서버 배포.
- **핵심 파일**: `app/backend/db/migrations/036_credit_system_subscription.sql`, `app/backend/core/points_service.py`, `app/backend/core/subscription_service.py`, `app/backend/api/v1/agent.py`, `app/backend/api/jobs.py`, `app/backend/api/v1/jobs.py`, `app/ai-backend/src/chat/route.ts`, `app/ai-backend/src/lib/proof-api.ts`, `app/frontend/src/pages/JobConfirmPage.jsx`, `app/frontend/src/pages/PricePage.jsx`, `app/frontend/src/components/PlanCard.jsx`.

### Evidence-to-Element Mapper — 요건 사실 기반 증거 퍼즐 매퍼 (DnD + 입증 달성도 시각화)

- **목표**: 변호사가 사건 기획을 직관적으로 할 수 있도록 돕는 '요건 사실 기반 증거 퍼즐 매퍼' 추가. 청구 원인(예: 사기죄)에 따른 법적 요건 빈 슬롯을 제공하고, e-Discovery 그래프에서 추출된 증거(evidence) 노드를 @dnd-kit 드래그 앤 드롭으로 슬롯에 채우면 입증 달성도(%)를 시각화. 기존 EDiscoveryViewer 내 'Graph'/'Mapper' 탭 전환으로 통합.
- **의존성 추가**: `app/frontend/package.json`에 `@dnd-kit/core@^6.1.0`, `@dnd-kit/utilities@^3.2.2` 추가 — DnD 인프라 (deprecated된 react-beautiful-dnd 대체).
- **Phase 1: DB 마이그레이션 & 모델** (`app/backend/db/migrations/032_add_element_mappings.sql` 신규):
  - `jobs` 테이블에 `element_mappings JSONB NOT NULL DEFAULT '{}'::jsonb` 컬럼 추가.
  - `app/backend/db/models.py`: `Job` 클래스에 `element_mappings: Mapped[dict] = mapped_column(JSON, default=dict)` 추가 (ediscovery_* 필드 그룹 뒤).
- **Phase 2: 요건사실 추출 모듈** (`app/backend/core/legal_elements.py` 신규):
  - `extract_legal_elements(claim_type, endpoint, model, api_key)`: vLLM `call_text`로 청구명 → 법적 요건사실 3~5개 JSON 추출. `_build_legal_elements_prompt` — 한국 법률 체계 기준, 데이터 계약 스키마 준수. `_parse_legal_elements` — JSON 펜스 제거 + 스키마 검증 + 빈 슬롯 `mapped_evidence:[]` 주입.
  - `compute_overall_progress(mappings)`: 1개 이상 증거가 매핑된 요건의 비율(%) 계산.
- **Phase 3: FastAPI 엔드포인트** (`app/backend/api/ediscovery.py`에 추가, 기존 라우터 재사용):
  - `GET /api/jobs/{job_id}/legal-elements?claim_type={범죄명}`: vLLM으로 요건사실 추출. 같은 claim_type 재요청 시 캐시(저장된 element_mappings) 반환.
  - `PUT /api/jobs/{job_id}/legal-elements/mappings`: 퍼즐 상태를 `element_mappings` JSONB에 영속화. `overall_progress_percent` 서버 재계산.
  - `GET /api/jobs/{job_id}/legal-elements/mappings`: 저장된 매핑 조회 (페이지 새로고침 후 복원용).
  - `_resolve_llm_settings`: job.endpoint → settings_store → settings 기본값 순서로 LLM 설정 해석 (pipeline_ediscovery.run 패턴 준수).
- **Phase 4: 프론트엔드 DnD 인프라** (`app/frontend/src/components/mapper/` 신규 디렉토리):
  - `EvidenceMapperPanel.jsx`: 최상단 `<DndContext collisionDetection={closestCenter}>` 래퍼. 좌측 증거 카드 리스트(e-Discovery graph의 evidence 노드) + 우측 ElementDroppableSlots + 상단 ProgressBadge. claim_type 자유 텍스트 입력 + '요건사실 추출' 버튼. 드롭 시 요건 슬롯에 증거 append + `overall_progress_percent` 재계산 + PUT /mappings 자동 영속화. 페이지 로드 시 저장된 매핑 복원.
  - `EvidenceDraggableCard.jsx`: `useDraggable` 훅으로 증거 카드 감싸기. drag 시 `CSS.Transform.toString(transform)` 적용, 투명도/스케일 피드백. 이미 매핑된 증거는 disabled.
  - `ElementDroppableSlots.jsx`: 각 요건별 `useDroppable` 슬롯. 점선 테두리(`border-dashed border-2 border-gray-300 rounded-lg p-4`). 드래그 오버 시 `border-blue-500 bg-blue-50` 하이라이트. 매핑된 증거 카드 + 제거 버튼.
  - `ProgressBadge.jsx`: 상단 프로그레스 바(`bg-blue-600 transition-all duration-500`) + 도넛 차트 뱃지(SVG circle stroke-dasharray). shadcn/ui 없이 Tailwind + SVG로만 구현.
- **Phase 5: EDiscoveryViewer 통합** (`app/frontend/src/components/EDiscoveryViewer.jsx`):
  - 헤더에 'Graph'/'Mapper' 탭 전환 UI 추가 (`activeTab` state). Network/Puzzle 아이콘.
  - Mapper 탭에 `<EvidenceMapperPanel jobId job />` 렌더링. job.ediscovery_graphs에서 evidence 노드 추출해 mapper로 전달.
- **Phase 6: 프론트엔드 API 클라이언트** (`app/frontend/src/api.js`):
  - `getLegalElements(jobId, claimType)`, `saveElementMappings(jobId, data)`, `getElementMappings(jobId)` 메서드 추가.
- **Phase 7: AI 백엔드 도구** (`app/ai-backend/src/tools/mapper.ts` 신규):
  - `buildMapperTools(context)`: `get_legal_elements`(요건사실 추출), `save_element_mappings`(퍼즐 상태 저장), `get_element_mappings`(저장된 매핑 조회). ediscovery.ts 패턴 준수.
  - `app/ai-backend/src/lib/proof-api.ts`: `ElementMappings`/`LegalElement`/`MappedEvidence` 타입 정의 + `getLegalElements`/`saveElementMappings`/`getElementMappings` 클라이언트 메서드 추가.
  - `app/ai-backend/src/chat/route.ts`: `buildMapperTools` import + toolContext 등록 + 시스템 프롬프트 "9. Evidence-to-Element Mapper" 카테고리 추가.
- **Phase 8: i18n**: `app/frontend/src/locales/{ko,en,ja}/page.json`에 매퍼 키 14개 추가 (`mapperTabGraph` ~ `mapperRemoveEvidence`).
- **검증**: 백엔드 Job.element_mappings 필드 import 성공, legal_elements 모듈 import 성공, FastAPI 라우터 3개 등록 확인, compute_overall_progress 단위 테스트(50% 계산) 통과, 프론트엔드 Vite 빌드 성공 (2327 모듈 변환), AI 백엔드 TypeScript 빌드 성공 (에러 0).
- **배포 시 주의**: DB 마이그레이션 `032_add_element_mappings.sql`을 서버 `supabase-chungu-db` 컨테이너에 수동 적용 필요 (AGENTS.md "Deployment" 섹션 참조).
- **핵심 파일**: `app/backend/db/migrations/032_add_element_mappings.sql`, `app/backend/db/models.py`, `app/backend/core/legal_elements.py`, `app/backend/api/ediscovery.py`, `app/frontend/src/components/mapper/EvidenceMapperPanel.jsx`, `app/frontend/src/components/mapper/EvidenceDraggableCard.jsx`, `app/frontend/src/components/mapper/ElementDroppableSlots.jsx`, `app/frontend/src/components/mapper/ProgressBadge.jsx`, `app/frontend/src/components/EDiscoveryViewer.jsx`, `app/frontend/src/api.js`, `app/ai-backend/src/tools/mapper.ts`, `app/ai-backend/src/lib/proof-api.ts`, `app/ai-backend/src/chat/route.ts`, `app/frontend/src/locales/{ko,en,ja}/page.json`.

### e-Discovery 타임라인 시각화 고도화 — 스윔레인 + 모순점(Anomaly) 탐지 + 점진적 탐색 패널

- **목표**: 기존 평면 노드 그래프를 법률 전문가용 'e-Discovery 타임라인 시각화 뷰'로 고도화. 주체별 스윔레인 배치, 진술-증거 모순 자동 탐지(2차 LLM 패스), 점진적 탐색 오버레이, 쟁점 필터 디밍을 구현. 인지 과부하 최소화 및 모순점 직관적 파악이 핵심.
- **데이터 계약 변경**: `ediscovery_graphs` JSONB에 신규 스키마 도입 — `type: "swimlane"` 최상위 노드(원고/피고/제3자/쟁점 4레인), 자식 노드의 `parentId` 매핑, `type: "anomaly"` 엣지 + `data.conflict_reason`. 기존 평면 스키마 job은 그대로 유지되며 EDiscoveryViewer가 두 스키마를 모두 렌더링(폴백 포함).
- **Phase 1: 백엔드 추출 프롬프트/파싱 확장** (`app/backend/core/pipeline_ediscovery.py`):
  - `EdiscoveryNode` 데이터클래스에 `entity`, `date_text`, `date_iso`, `summary`, `parent_id` 필드 추가.
  - `_build_extraction_prompt` 확장 — entity(행위 주체), date(시간 표현), summary(1~2문 요약) 필드 추가 추출.
  - `_normalize_date(text)` 헬퍼 — 한국식(년/월/일)/일본식(年/月/日)/서양식(. - /) 날짜를 ISO YYYY-MM-DD로 정규화. 시간순 정렬용.
  - `_classify_entity(node_type, item_entity)` 헬퍼 — LLM 명시 entity 우선, 누락 시 node_type에서 추론.
  - `_parse_nodes` 확장 — 새 필드 파싱 + 날짜 정규화 + entity 분류.
- **Phase 2: 2차 LLM 모순(Anomaly) 탐지** (`pipeline_ediscovery.py`):
  - `AnomalyPair` 데이터클래스 — source_id, target_id, conflict_reason.
  - `_build_anomaly_prompt(nodes_batch)` — 추출된 노드 목록에서 진술(plaintiff/defendant) vs 객관적 증거(evidence) 충돌 쌍 탐지 프롬프트.
  - `_parse_anomalies(content, valid_ids)` — 응답 파싱 + 존재하지 않는 id 필터링.
  - `detect_anomalies_concurrent(nodes, endpoint, model, api_key)` — MAX_ANOMALY_NODES(200) 상한 적용 → 배치(40개) 분할 → ThreadPoolExecutor 병렬 2차 LLM 호출 → 중복 제거.
- **Phase 3: 스윔레인 구성 + 그래프 조립 재작성** (`pipeline_ediscovery.py`):
  - `SWIMLANE_IDS`/`SWIMLANE_LABELS` 상수 — 4개 swimlane 고정 ID + 표시 라벨.
  - `_build_swimlanes(nodes)` — 등장한 entity별 swimlane 노드 생성 + 각 노드에 parentId 주입. 미등장 주체는 swimlane 미생성.
  - `assemble_graph(nodes, anomalies)` 재작성 — 중복 제거 → 노드 수 상한 → swimlane 생성 → 시간순 정렬(date_iso → page → id) → 같은 swimlane 내 인접 노드 간 smoothstep 엣지 + 모순 쌍 간 anomaly 엣지 조립. 데이터 계약 스키마 준수.
- **Phase 4: run 오케스트레이션 갱신** (`pipeline_ediscovery.py`):
  - `run`에 2차 LLM 패스 삽입 — 노드 추출 → 임계값 필터 → `detect_anomalies_concurrent` → `assemble_graph(filtered, anomalies)`.
  - metrics에 `anomalies_detected` 키 추가.
- **Phase 5: ELK 스윔레인 레이아웃** (`app/frontend/src/utils/elkLayout.js`):
  - `calculateElkSwimlaneLayout(nodes, edges)` 신규 — `elk.algorithm: 'layered'` + `elk.partitioning.activate: 'true'`. 부모(swimlane) 내부에 자식을 중첩한 ELK JSON 구성. React Flow v12 규칙에 따라 `node.measured?.width` 우선 참조, 폴백 `node.data?.width`. 부모가 없으면 `calculateElkLayout` 평면 레이아웃으로 폴백. 기존 `calculateElkLayout`은 FlowViewer 호환성을 위해 유지.
- **Phase 6: AnomalyEdge 컴포넌트** (`app/frontend/src/components/flow/AnomalyEdge.jsx` 신규):
  - `BaseEdge` + `getBezierPath`로 빨간 점선 패스 렌더링. `animate-dash` 클래스로 stroke-dashoffset 흐름 애니메이션.
  - `EdgeLabelRenderer` 포털로 중앙에 "모순 발생" 경고 뱛지(빨간 배경 + AlertTriangle 아이콘). 호버 시 `data.conflict_reason` 툴팁 표시.
- **Phase 7: index.css 애니메이션** (`app/frontend/src/index.css`):
  - `@keyframes dash` + `.animate-dash` 클래스 추가 — stroke-dasharray: 6 4, 1s linear infinite.
- **Phase 8: EDiscoveryViewer 고도화** (`app/frontend/src/components/EDiscoveryViewer.jsx`):
  - `SwimlaneNode` 컴포넌트 — entity별 색상 코딩(원고=파랑/피고=주황/제3자=보라/쟁점=빨강) + 점선 테두리.
  - `dimClass(data)` 헬퍼 — `data.dimmed` 시 `opacity-20 grayscale transition-opacity duration-300` 적용. 모든 노드 컴포넌트에 디밍 적용.
  - `nodeTypes`에 `eDiscovery-swimlane` 등록, `edgeTypes`에 `anomaly: AnomalyEdge` 등록.
  - `buildGraph` 신/구 스키마 분기 — `parentId` 보유 노드가 있으면 `calculateElkSwimlaneLayout`, 없으면 `calculateElkLayout` 폴백. 엣지 type 보존(anomaly 엣지가 AnomalyEdge로 렌더링되도록).
  - `IssueFilterBar` 컴포넌트 — 그래프에서 고유 issue 라벨 추출 → 토글 칩 렌더링. 미선택 쟁점 노드는 hidden 대신 디밍.
  - `DetailOverlayPanel` 컴포넌트 — 노드 클릭 시 우측 슬라이드인 패널(`animate-stagger-enter`). label/summary/page/confidence/date 표시 + "원본 PDF 보기" 버튼 → `onNodeClick` 콜백으로 SourcePanel scrollToPage 연동.
  - `applyIssueFilter` — 선택된 쟁점 집합 기반 노드 data.dimmed 플래그 갱신. swimlane은 필터 제외.
  - `handleNodeClick` — swimlane 클릭 시 오버레이 미표시, 일반 노드 클릭 시 오버레이 + 외부 onNodeClick 호출.
  - `useRef` import 누락 버그 수정 (pollRef용).
- **Phase 9: AI 백엔드 인터페이스 갱신** (`app/ai-backend/src/tools/ediscovery.ts`):
  - `GraphNode` 인터페이스에 `parentId?`, `entity?`, `date?`, `summary?`, `issue?` 추가.
  - `GraphEdge` 인터페이스에 `data?: { conflict_reason? }` 추가.
- **Phase 10: i18n** (`app/frontend/src/locales/{ko,en,ja}/page.json`):
  - 신규 키 12개 추가 — `ediscoveryAnomalyBadge`, `ediscoveryIssueFilter`, `ediscoveryDetailTitle`, `ediscoveryViewSource`, `ediscoveryClose`, `ediscoverySummary`, `ediscoveryPage`, `ediscoveryConfidence`, `ediscoverySwimlanePlaintiff`/`Defendant`/`ThirdParty`/`Issue`.
- **검증**: 백엔드 import 성공 + 단위 테스트(날짜 정규화/주체 분류/swimlane 조립/anomaly 파싱) 통과, 기존 43개 테스트 회귀 없음, 프론트엔드 Vite 빌드 성공(2320 모듈), AI 백엔드 TypeScript 빌드 성공(에러 0).
- **배포 시 주의**: DB 마이그레이션 불필요 (`ediscovery_graphs`는 JSONB라 스키마 변경에 컬럼 추가 없음). 다만 `ediscovery_metrics`에 `anomalies_detected` 키가 추가되어 기존 job은 해당 키가 0/없음으로 표시됨.
- **핵심 파일**: `app/backend/core/pipeline_ediscovery.py`, `app/frontend/src/utils/elkLayout.js`, `app/frontend/src/components/flow/AnomalyEdge.jsx`, `app/frontend/src/components/EDiscoveryViewer.jsx`, `app/frontend/src/index.css`, `app/ai-backend/src/tools/ediscovery.ts`, `app/frontend/src/locales/{ko,en,ja}/page.json`.

### e-Discovery GraphRAG 백엔드 파이프라인 — 법률 문서 쟁점/증거 그래프 추출

- **목표**: 수천 장 단위의 법률 문서에서 쟁점(issue)/원고(plaintiff)/피고(defendant)/증거(evidence) 노드를 추출해 React Flow 시각화용 그래프 JSON으로 조립하는 e-Discovery 파이프라인을 백엔드(Python/FastAPI/Celery)에 추가. 기존 `annotate`/`xlsx_advanced`의 과금·상태 추적·Celery 큐잉 패턴을 재사용.
- **Phase 1: DB 마이그레이션** (`app/backend/db/migrations/031_add_ediscovery_fields.sql` 신규):
  - `jobs` 테이블에 8개 컬럼 추가: `ediscovery_status`, `ediscovery_job_id`, `ediscovery_graphs`(JSONB), `ediscovery_metrics`(JSONB), `ediscovery_params`(JSONB), `ediscovery_refundable`, `ediscovery_reserved_pages`, `ediscovery_reserved_period_start`.
  - `ediscovery_status` 부분 인덱스 생성 (`WHERE ediscovery_status <> ''`).
  - 번호 030은 기존 `030_add_chat_conversations.sql`이 사용 중이므로 031 사용.
- **Phase 2: 모델 업데이트** (`app/backend/db/models.py`):
  - `Job` 클래스에 8개 `ediscovery_*` 필드 매핑 추가 (기존 `annotate_*` 필드 그룹 패턴 준수).
- **Phase 3: 추출 파이프라인** (`app/backend/core/pipeline_ediscovery.py` 신규):
  - `extract_page_texts(job)`: `searchable_pdf_storage_path` → `pdf_storage_path` → `result_md_storage_path` 순서 폴백. PyMuPDF `page.get_text("blocks")`로 페이지별 텍스트 추출 (pdf_annotate_converter 패턴 재사용).
  - `build_parent_child_chunks(page_texts, chunk_size, overlap, page_range)`: 부모=페이지 전체, 자식=슬라이딩 윈도우(단어 단위, 기본 512단어 + 64 overlap). 페이지 메타데이터 보존.
  - `extract_nodes_from_chunk(chunk, endpoint, model, api_key)`: vLLM Proxy(`call_text`) 호출 → 쟁점/원고/피고/증거 노드 JSON 추출. 데이터 계약 스키마 준수.
  - `extract_nodes_concurrent(chunks, ...)`: ThreadPoolExecutor로 청크별 vLLM 호출 병렬화 (MAX_LLM_WORKERS=16 상한).
  - `filter_nodes_by_threshold(nodes, threshold)`: confidence 임계값 필터링 (파이프라인 방식).
  - `assemble_graph(nodes)`: 중복 제거(label+type 기준) + 같은 페이지 내 smoothstep 엣지 생성. 노드 수 상한 5000.
  - `run(job_id, chunk_size, threshold, page_range, max_chunks, query, max_docs)`: 전체 오케스트레이션. 상태 갱신(done/error), 환불 플래그, `ediscovery_graphs`/`ediscovery_metrics` JSONB 저장. `max_docs`는 `max_chunks`의 별칭(api/ediscovery.py 호환용).
- **Phase 4: Celery 태스크** (`app/backend/workers/tasks.py`):
  - `@celery.task run_ediscovery(job_id, chunk_size, threshold, page_range, max_chunks, query)` 등록 → `pipeline_ediscovery.run` 호출.
- **Phase 5: FastAPI 엔드포인트** (`app/backend/api/jobs.py`):
  - `POST /api/jobs/{job_id}/ediscovery/extract`: Celery 백그라운드 큐잉. 파라미터: chunk_size, threshold, max_chunks, query, page_range. 관리자 무료 / 일반 사용자 포인트(`ediscovery_cost_points`) 차감 + 환불 가능. 같은 파라미터 재사용 시 캐시 반환.
  - `GET /api/jobs/{job_id}/ediscovery`: 상태/그래프/메트릭 반환 (폴링용).
  - `POST /api/jobs/{job_id}/ediscovery/threshold`: 저장된 그래프에서 confidence 기준 재필터링 (재추출 없이 엣지/노드만 재구성).
  - `_job_summary()`에 `ediscovery_status`, `ediscovery_graphs`, `ediscovery_metrics`, `ediscovery_refundable` 필드 추가.
- **Phase 6: 병렬 에이전트 충돌 조정**:
  - `app/backend/api/ediscovery.py`에 동일 경로의 동기 처리 엔드포인트가 별도 존재했으나, `jobs.py`의 Celery 기반 엔드포인트와 중복되어 `main.py`에서 `ediscovery_router` 등록을 제거. `jobs.router`가 정식 제공자.
  - `pipeline_ediscovery.run`에 `max_docs` 별칭 파라미터 추가 — `api/ediscovery.py`의 `extract`/`threshold` 엔드포인트가 `max_docs=` 키워드로 호출하므로 호환성 유지.
- **검증**: Job 모델 필드 8개 import 성공, pipeline_ediscovery import 성공, run_ediscovery Celery 태스크 import 성공, run 시그니처 호환(max_docs/max_chunks/query 포함), FastAPI 라우터 3개 등록 확인(중복 없음), 청킹/필터/그래프 조립 단위 테스트 통과, 데이터 계약 스키마 준수 확인, 기존 43개 테스트 회귀 없음.
- **배포 시 주의**: DB 마이그레이션 `031_add_ediscovery_fields.sql`을 서버 `supabase-chungu-db` 컨테이너에 수동 적용 필요 (AGENTS.md "Deployment" 섹션 참조).
- **핵심 파일**: `app/backend/db/migrations/031_add_ediscovery_fields.sql`, `app/backend/db/models.py`, `app/backend/core/pipeline_ediscovery.py`, `app/backend/workers/tasks.py`, `app/backend/api/jobs.py`, `app/backend/main.py`.

### Flow Panel 에이전트 조작 도구 확장 — 드로잉/주석/노트/엣지/헤딩 노드 CRUD

- **목표**: 플로우뷰(React Flow)의 드로잉, 텍스트 주석, 노트 노드, 커스텀 엣지, 헤딩 노드 구조를 에이전트가 조작할 수 있도록 AI 백엔드 도구를 확장. 기존 `flow.ts`에는 읽기/분석 전용 도구 2개만 있었고, 드로잉/주석 CRUD, 노트/엣지 영속화, 헤딩 노드 조작 도구가 전무했음. 백엔드 `flow_drawings` API와 프론트엔드 저장 로직은 사용자 수동 조작용으로만 구현되어 있었음.
- **의존성 추가**: `app/ai-backend/package.json`에 `elkjs@^0.9.3` 추가 — 서버 사이드 레이아웃 계산용 (에이전트가 드로잉/주석을 노드 근처에 배치할 때 좌표 참조).
- **Phase 1: 백엔드 DB 마이그레이션 & API 확장**:
  - `app/backend/db/migrations/029_add_flow_notes_edges.sql` (신규): `flow_drawings` 테이블에 `note_nodes JSONB`, `custom_edges JSONB` 컬럼 추가.
  - `app/backend/db/models.py`: `FlowDrawing` 모델에 `note_nodes`, `custom_edges` 컬럼 추가.
  - `app/backend/api/flow_drawings.py`: `FlowDrawingData` Pydantic 모델 + GET/PUT 응답에 `note_nodes`, `custom_edges` 필드 포함.
- **Phase 2: AI 백엔드 proof-api.ts 클라이언트 확장**:
  - `app/ai-backend/src/lib/proof-api.ts`: `getFlowDrawings`/`saveFlowDrawings`/`deleteFlowDrawings` 클라이언트 메서드 추가 (GET/PUT/DELETE `/api/jobs/{jobId}/flow-drawings`).
- **Phase 3: 드로잉/주석 도구** (`app/ai-backend/src/tools/flow.ts`):
  - `createShapePath` 포팅: `drawingUtils.js`의 선/화살표/사각형/원 SVG path 생성 로직을 TypeScript로 이식.
  - `get_flow_layout`: elkjs로 마크다운 헤딩 노드 위치 계산 → 에이전트가 드로잉/주석 배치 시 좌표 참조.
  - `get_flow_drawings`: 서버에서 현재 paths, text_annotations, note_nodes, custom_edges 조회.
  - `add_flow_shape`: 도형(선/화살표/사각형/원) SVG path 생성 추가. 입력: shapeType, 좌표(x1,y1,x2,y2), strokeColor, strokeWidth.
  - `add_flow_text_annotation`: 텍스트 주석 추가. 입력: text, x/y, color, fontSize.
  - `delete_flow_drawing`: ID로 특정 path 또는 text annotation 삭제.
  - `clear_flow_drawings`: 모든 드로잉/주석/노트/엣지 초기화.
  - `save_flow_drawings`: 보류 중인 변경사항을 서버에 PUT 저장. 변경된 전체 상태 반환 (프론트엔드 동기화용).
  - read-modify-write 패턴: `ensureLoaded()`로 서버에서 로드 → 보류 버퍼에서 조작 → `save_flow_drawings`로 영속화 (markdown.ts의 edits 버퍼 패턴과 동일).
- **Phase 4: 노트 노드 & 커스텀 엣지 도구** (`flow.ts`):
  - `add_flow_note`: 스티키 노트 추가. 입력: text, x/y, width, height.
  - `update_flow_note`: 노트 텍스트/크기 수정. 입력: noteId, text?, width?, height?.
  - `delete_flow_note`: ID로 노트 삭제.
  - `add_flow_edge`: 두 노드 간 커스텀 엣지 추가. 입력: sourceNodeId, targetNodeId, label?.
  - `delete_flow_edge`: ID로 엣지 삭제.
- **Phase 5: 헤딩 노드 조작 도구** (`flow.ts` — 내부적으로 마크다운 편집):
  - `add_flow_heading`: 마크다운에 새 헤딩 추가 → 플로우뷰에 새 노드 생성. parentHeading 지정 시 해당 섹션 끝에, 생략 시 문서 끝에 추가.
  - `delete_flow_heading`: 헤딩 섹션 전체 삭제 → 플로우뷰에서 노드 제거.
  - `rename_flow_heading`: 헤딩 텍스트 변경 → 플로우뷰 노드 제목 수정.
  - `move_flow_heading`: 헤딩 레벨 변경 → 플로우뷰 노드 계층 이동.
  - `_findHeadingLineRange` 헬퍼: 마크다운에서 헤딩 라인 인덱스 범위 검색.
  - 헤딩 도구는 마크다운을 직접 수정하므로 `apply_edits`와 혼용 금지 (시스템 프롬프트에 명시).
- **Phase 6: route.ts 시스템 프롬프트 업데이트**:
  - `app/ai-backend/src/chat/route.ts`: `buildSystemPrompt()`에 "7. Flow view manipulation" 도구 카테고리 추가. 레이아웃/드로잉/주석/노트/엣지/헤딩 도구 사용 규칙 명시. "항상 `get_flow_layout` 먼저 호출", "조작 후 반드시 `save_flow_drawings` 호출", "헤딩 도구는 `apply_edits`와 혼용 금지" 지시.
- **Phase 7: 프론트엔드 동기화**:
  - `app/frontend/src/hooks/useFlowDrawing.js`: `noteNodes`/`customEdges` state 추가. 서버 GET/localStorage/자동 저장 PUT에 새 필드 포함. `updateFromAgent(data)` 메서드 추가 — 에이전트 도구 결과로 받은 전체 상태를 로컬에 즉시 반영.
  - `app/frontend/src/components/FlowViewer.jsx`: `forwardRef` + `useImperativeHandle`로 `updateFromAgent` 외부 노출. `drawingApiRef`로 FlowCanvas에 전달. `noteNodes`를 React Flow `noteNode` 타입 노드로 변환하여 `nodes` state에 통합. `customEdges`를 `custom` 타입 엣지로 변환하여 `edges` state에 통합.
  - `app/frontend/src/components/AgentChatModal.jsx`: `onFlowDrawingsUpdate` prop 추가. ChatSession에서 `messages`의 `save_flow_drawings` 도구 결과(`state === "output-available"`)를 감지하여 콜백 호출.
  - `app/frontend/src/pages/JobResultPage.jsx`: `flowViewerApiRef` 생성 → FlowViewer에 ref 연결. AgentChatModal에 `onFlowDrawingsUpdate` 콜백 전달 → `flowViewerApiRef.current.updateFromAgent(data)` 호출로 즉시 동기화.
- **Phase 8: i18n**: `app/frontend/src/locales/{ko,en,ja}/page.json`에 신규 도구 라벨 18개 추가 (`extract_flow_structure` ~ `move_flow_heading`).
- **검증**: AI 백엔드 TypeScript 빌드 성공 (에러 0), 프론트엔드 Vite 빌드 성공 (2337 모듈 변환), 백엔드 모델/API에 note_nodes/custom_edges 컬럼 정상 추가 확인.
- **배포 시 주의**: DB 마이그레이션 `029_add_flow_notes_edges.sql`을 서버 `supabase-chungu-db` 컨테이너에 수동 적용 필요 (AGENTS.md "Deployment" 섹션 참조).
- **핵심 파일**: `app/ai-backend/src/tools/flow.ts`, `app/ai-backend/src/lib/proof-api.ts`, `app/ai-backend/src/chat/route.ts`, `app/backend/db/migrations/029_add_flow_notes_edges.sql`, `app/backend/db/models.py`, `app/backend/api/flow_drawings.py`, `app/frontend/src/hooks/useFlowDrawing.js`, `app/frontend/src/components/FlowViewer.jsx`, `app/frontend/src/components/AgentChatModal.jsx`, `app/frontend/src/pages/JobResultPage.jsx`, `app/frontend/src/locales/{ko,en,ja}/page.json`.

### Flow Panel 기능 확장 — 드로깅/주석, 노드 리사이즈, 원문 PDF 스크롤 연동

- **목표**: React Flow 기반 Flow Panel 에 3가지 기능 추가: (1) 풍부한 드로잉/주석 도구, (2) 드래그앤드롭 노드 리사이즈, (3) 플로우 노드 클릭 시 왼쪽 SourcePanel 원문 PDF의 해당 페이지로 자동 스크롤. koda-learn 프로젝트의 `perfect-freehand` + SVG path 드로잉 엔진을 이식하고 React Flow의 `NodeResizer`/`ViewportPortal`로 통합.
- **의존성 추가**: `app/frontend/package.json`에 `perfect-freehand@^1.2.2` 추가 — 부드러운 곡선 생성.
- **Phase 1: 노드 리사이즈** (`app/frontend/src/components/FlowViewer.jsx`):
  - `HeadingNode`/`NoteNode`에 `@xyflow/react`의 `NodeResizer` 추가.
  - 선택 시에만 핸들 노출 (`isVisible={selected}`), 최소/최대 크기 제한 (`minWidth/maxWidth/minHeight`).
  - 고정 너비 CSS(`w-[280px]`, `w-[200px]`) 제거하고 `style={{ width: data.width }}`로 동적 적용. `elkLayout.js`는 이미 `data.width`/`data.height`를 존중.
- **Phase 2: 노드 클릭 → 원문 PDF 스크롤 연동**:
  - `app/frontend/src/utils/markdownToFlow.js`: `<!-- 페이지 N -->` HTML 주석을 정규식으로 추적, 각 heading 노드의 `data.page`에 페이지 번호 할당 (마커 없는 문서는 `1` 폴백).
  - `app/frontend/src/components/SourcePanel.jsx`: `forwardRef` + `useImperativeHandle`로 `scrollToPage(pageNum)` 메서드 외부 노출.
  - `app/frontend/src/pages/JobResultPage.jsx`: `sourcePanelApiRef` 생성 → `FlowViewer`의 `onNodeClick`에서 `sourcePanelApiRef.current.scrollToPage(node.data.page)` 호출.
- **Phase 3: 드로잉/주석 도구**:
  - `app/frontend/src/utils/drawingUtils.js` (신규): `getFreehandPath` (perfect-freehand), `createShapePath` (선/화살표/사각형/원), `eraseAtPoint`/`eraseTextAtPoint`.
  - `app/frontend/src/hooks/useFlowDrawing.js` (신규): 펜/형광펜/지우개/텍스트/도형 모드, 색상/굵기, Undo/Clear, localStorage 자동 저장 + 서버 자동 저장 (2초 debounce). 드로잉 중 동기 상태 추적을 위해 `isDrawingRef`/`currentPointsRef` 사용 (stale closure 방지).
  - `app/frontend/src/components/flow/DrawingOverlay.jsx` (신규): React Flow `ViewportPortal` 내부에 SVG 렌더링 → pan/zoom 자동 따라감. 드로잉 모드에서만 `pointerEvents: auto`.
  - `app/frontend/src/components/flow/DrawingToolbar.jsx` (신규): 하단 중앙 툴바 — 모드 전환, 색상 팝오버(8색), 굵기 슬라이더(1~20px), 도형 서브메뉴, Undo/Clear.
  - `FlowViewer.jsx` 통합: `useFlowDrawing` 훅 사용, 드로잉 모드 시 `panOnDrag={false}` + `nodesDraggable={false}`로 React Flow 상호작용 차단.
- **Phase 4: 서버 저장 (Supabase)**:
  - `app/backend/db/migrations/028_add_flow_drawings.sql` (신규): `flow_drawings` 테이블 — `job_id` + `user_id` UNIQUE, `paths JSONB`, `text_annotations JSONB`.
  - `app/backend/db/models.py`: `FlowDrawing` SQLAlchemy 모델 추가.
  - `app/backend/api/flow_drawings.py` (신규): GET/PUT/DELETE `/api/jobs/{job_id}/flow-drawings` CRUD API. `response_model=None`로 `CurrentUser` Pydantic 변환 회피.
  - `app/backend/main.py`: `flow_drawings_router` 등록.
  - `app/frontend/src/api.js`: `getFlowDrawings`/`saveFlowDrawings`/`deleteFlowDrawings` 클라이언트 메서드 추가.
- **Phase 5: i18n**: `app/frontend/src/locales/{ko,en,ja}/page.json`에 14개 드로잉 키 추가 (`flowSelectMode`, `flowDraw`, `flowHighlight`, `flowEraser`, `flowText`, `flowShape`, `flowShapeLine`, `flowShapeArrow`, `flowShapeRectangle`, `flowShapeCircle`, `flowStrokeColor`, `flowStrokeWidth`, `flowUndo`, `flowClear`).
- **디버깅/검증**: 로컬 Vite dev server + Playwright 브라우저에서 Flow 뷰 전환, 드로잉 툴바, 펜 드로잉 저장, 노드 클릭 → `scrollToPage` 호출, NodeResizer 핸들 노출, 프론트엔드 빌드, 백엔드 import 확인.
- **배포 시 주의**: DB 마이그레이션 `028_add_flow_drawings.sql`을 서버 `supabase-chungu-db` 컨테이너에 수동 적용 필요 (AGENTS.md "Deployment" 섹션 참조).
- **핵심 파일**: `app/frontend/src/components/FlowViewer.jsx`, `app/frontend/src/hooks/useFlowDrawing.js`, `app/frontend/src/utils/drawingUtils.js`, `app/frontend/src/components/flow/DrawingOverlay.jsx`, `app/frontend/src/components/flow/DrawingToolbar.jsx`, `app/frontend/src/pages/JobResultPage.jsx`, `app/frontend/src/components/SourcePanel.jsx`, `app/frontend/src/utils/markdownToFlow.js`, `app/backend/api/flow_drawings.py`, `app/backend/db/migrations/028_add_flow_drawings.sql`.

### Flow Panel — 마크다운 헤딩 구조를 React Flow 그래프로 시각화 + 드롭다운 뷰 전환

- **목표**: 결과페이지(JobResultPage)에 마크다운 문서의 헤딩(H1~H6) 구조를 React Flow 캔버스에 논리 흐름 그래프로 시각화하는 플로우 패널 추가. 기존 가로형 탭 버튼(Markdown/Excel/Excel Advanced)을 드롭다운 메뉴로 교체하여 Markdown/Excel/Flow 뷰를 전환. 상세 계획은 `FLOW_PANEL_PLAN.md` 참조.
- **MCP 조사 기반 구현**: context7 + deepwiki MCP로 React Flow v12, elkjs, marked의 최신 API 시그니처를 사전 조사하여 정확한 API 사용.
- **Phase 1: 의존성 설치 + 인프라**:
  - `@xyflow/react` (React Flow v12, 구 `reactflow`에서 패키지명 변경), `elkjs` (Eclipse Layout Kernel), `uuid` npm 설치.
  - `app/frontend/src/index.css`: `@import "@xyflow/react/dist/style.css"` 추가 (PostCSS `@import` 우선 순위 준수).
  - `app/frontend/src/locales/{ko,en,ja}/page.json`: flow 관련 i18n 키 11개 추가 (flow, flowView, flowLoading, flowEmpty, flowResetLayout, flowFitView, flowAnalyzeDeps, flowAnalyzing, flowDepEdges, flowHierarchyEdges, viewMode).
- **Phase 2: 마크다운 → Flow 파서 (순방향 파이프라인)**:
  - `app/frontend/src/utils/markdownToFlow.js`: `marked.lexer()`로 토큰화 → heading 토큰(`{ type, depth, text }`)을 React Flow 노드로 변환 → 스택 기반 부모-자식 계층 에지 생성 → 하위 콘텐츠를 `content`/`contentPreview`(200자)에 축적. 토큰 소모 0, 순수 파싱.
  - `app/frontend/src/utils/elkLayout.js`: `elkjs/lib/elk.bundled.js` import → ELK JSON 그래프 형식(`{ id, layoutOptions, children, edges }`) 구성 → `elk.layout()` 호출 → 계산된 x/y 좌표를 노드에 매핑. 레이아웃 옵션: `elk.algorithm: 'layered'`, `elk.direction: 'DOWN'`, `elk.spacing.nodeNode: '80'`, `elk.layered.spacing.nodeNodeBetweenLayers: '100'`.
- **Phase 3: FlowViewer 컴포넌트** (`app/frontend/src/components/FlowViewer.jsx`):
  - `HeadingNode` 커스텀 노드: 제목 + H레벨 배지 + 내용 미리보기 (line-clamp-3). `<Handle>` 컴포넌트로 연결점 표시.
  - `HierarchyEdge` 커스텀 엣지: 실선 (부모-자식 heading 관계). `BaseEdge` + `getBezierPath` 사용.
  - `DependencyEdge` 커스텀 엣지: 점선 + 호버 시 `EdgeLabelRenderer` 포털로 `reason` 툴팁 렌더링 (AI 의존성 분석 결과 표시용).
  - `ReactFlowProvider` + `useNodesState`/`useEdgesState` + `useReactFlow().fitView()`. `<Background>`, `<Controls>`, `<MiniMap>` 내장 컴포넌트. `proOptions={{ hideAttribution: true }}`.
- **Phase 4: 드롭다운 뷰 전환기** (`app/frontend/src/pages/JobResultPage.jsx`):
  - 기존 가로형 탭 버튼 3개(Markdown/Excel/Excel Advanced)를 드롭다운 메뉴로 교체. 기존 `openDropdown`/`closeDropdown` hover timer 패턴 재사용.
  - `previewMode` state에 `"flow"` 추가 (`"markdown" | "xlsxBasic" | "xlsxAdvanced" | "flow"`).
  - `renderRightContent()`에 flow 분기 추가: `FlowViewer` 컴포넌트 렌더링.
  - `Workflow`, `ChevronDown` 아이콘 import 추가. `FlowViewer` import 추가.
- **Phase 5: AI 의존성 추론 파이프라인 (백엔드)**:
  - `app/ai-backend/src/tools/flow.ts`: `buildFlowTools` 팩토리 — 2개 도구:
    - `extract_flow_structure`: 마크다운에서 헤딩 트리 추출 (토큰 소모 0, `marked.lexer()` 순수 파싱). 노드 배열 + 계층 에지 배열 반환.
    - `infer_flow_dependencies`: 압축 메타데이터를 LLM에 전달하여 크로스 섹션 논리적 의존성 에지 추론. 참고 자료의 시스템 프롬프트 템플릿 적용.
  - `app/ai-backend/src/chat/route.ts`: `buildFlowTools` import + `tools` 객체에 스프레드 등록. `buildSystemPrompt()`에 "6. Flow analysis" 도구 카테고리 설명 추가.
  - `app/ai-backend/package.json`: `marked` 의존성 추가.
- **Phase 6: 양방향 동기화 (향후 확장)**: 순환 참조 탐지(DFS), 다중 부모 검증, 위상 정렬 트리 복원, 드래그 앤 드롭 리팩토링, 실시간 동기화(Flow → 마크다운 에디터 `editor.commands.setContent()`). 별도 스프린트 예정.
- **핵심 파일**: `FLOW_PANEL_PLAN.md`, `app/frontend/src/utils/markdownToFlow.js`, `app/frontend/src/utils/elkLayout.js`, `app/frontend/src/components/FlowViewer.jsx`, `app/frontend/src/pages/JobResultPage.jsx`, `app/frontend/src/locales/{ko,en,ja}/page.json`, `app/frontend/src/index.css`, `app/ai-backend/src/tools/flow.ts`, `app/ai-backend/src/chat/route.ts`.

### AI 에이전트 툴콜 응답 처리 개선 — LLMLingua-2 동적 프롬프트 압축 + maxOutputTokens + 도구 출력 제한

- **목표**: 에이전트가 툴콜 결과를 읽고 다음 툴콜을 호출하지 못하는 문제를 5가지 방향으로 수정. Gemma 4-26B 모델의 토큰 예산 부족, 도구 출력 과다, 시스템 프롬프트 모호성, 디버깅 로그 부족을 해결.
- **maxOutputTokens 8192 설정** (`app/ai-backend/src/chat/route.ts`): vLLM 기본값(128~256)은 툴콜 결과 분석에 부족하므로 `streamText()`에 `maxOutputTokens: 8192` 추가.
- **LLMLingua-2 동적 프롬프트 압축 마이크로서비스** (`app/llmlingua-service/` — 3파일):
  - `main.py`: FastAPI 서버 — POST `/compress` 엔드포인트. LLMLingua-2 `PromptCompressor(model_name="microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank", use_llmlingua2=True)` 사용.
  - **동적 rate 선택** (`_selectDynamicRate`): 도구 결과 크기(문자 수)에 따라 3단계 자동 선택 — 4000~8000자→0.5(2x), 8000~20000자→0.3(3x), 20000자+→0.2(5x). 논문 Appendix L Sample-Wise Dynamic Compression Ratio 방식 적용.
  - **`dynamic_context_compression_ratio=0.4`**: 각 문맥(청크)마다 40% 가변 허용하여 정보 밀도에 맞춤.
  - **`force_tokens`**: 8개 핵심 JSON 키(`error`, `id`, `page`, `bbox`, `rect`, `color`, `contents`, `type`) 보존하여 좌표/ID/페이지/색상 손실 방지.
  - `Dockerfile`: Python 3.11-slim + llmlingua 패키지 + 모델 사전 다운로드 (런타임 지연 방지). builder/runtime 2단계 이미지.
  - `requirements.txt`: llmlingua>=0.2.0, fastapi, uvicorn, pydantic.
- **Node.js 클라이언트** (`app/ai-backend/src/lib/llmlingua.ts`):
  - `shouldCompress(text, threshold=4000)`: 임계값 초과 시만 압축.
  - `compressToolResults(text, dynamic=true)`: Python 서비스에 POST `/compress` 요청, 실패 시 원본 폴백 (30초 타임아웃).
- **prepareStep 통합** (`app/ai-backend/src/chat/route.ts`): `prepareStep` 콜백에서 이전 스텝의 tool 결과 JSON이 4000자 초과 시 LLMLingua-2 압축 적용. 압축된 데이터를 시스템 메시지로 주입.
- **도구 출력 크기 제한**:
  - `annotations.ts`: `get_elements` 50→20개, `read_job_json` 80→30개, `get_annotations` 80→30개.
  - `sandbox.ts`: `execute_in_sandbox` stdout 2000자/stderr 1000자 제한, `read_sandbox_file` content 4000자 제한 (`_truncate` 헬퍼 함수).
  - `spreadsheet.ts`: `get_sheet` rows 50→20행.
  - `browserless.ts`: `extract_web_text` text 3000자 제한.
- **시스템 프롬프트 개선** (`route.ts`): "CRITICAL: Always read and analyze tool results before making the next tool call" 지시 추가. "After calling a tool, summarize what you learned from its output before deciding the next step" 추가.
- **onStepFinish 로깅** (`route.ts`): 각 스텝 종료 시 `finishReason`, `toolCalls`, `toolResults`, `usage`(input/output tokens) 로그 출력.
- **docker-compose.yml + .env.example**: `llmlingua` 서비스 추가 (포트 8001), `ai-backend`에 `LLMLINGUA_URL=http://llmlingua:8000` 환경변수 추가. `.env.example`에 `LLMLINGUA_URL`/`LLMLINGUA_RATE`/`LLMLINGUA_MODEL` 3개 환경변수 추가.
- **리서치 근거**: LLMLingua-2 논문(arxiv 2403.12968) Table 5/6/12, Appendix L. 동적 압축(DCR)이 고정 비율(FR) 대비 5x/7x에서 +17.5% 성능 개선. 5x(rate=0.2)에서도 원본 대비 89% 성능 유지, 2.9x 지연 가속.
- **핵심 파일**: `app/llmlingua-service/`(3파일), `app/ai-backend/src/lib/llmlingua.ts`, `app/ai-backend/src/chat/route.ts`, `app/ai-backend/src/tools/annotations.ts`, `app/ai-backend/src/tools/sandbox.ts`, `app/ai-backend/src/tools/spreadsheet.ts`, `app/ai-backend/src/tools/browserless.ts`, `app/docker-compose.yml`, `app/.env.example`.

### Kata Containers + Cloud Hypervisor 기반 에이전트 샌드박스 (격리 실행 환경)

- **목표**: PROOF 결과 페이지의 문서/이미지/오디오/비디오 파일들을 격리된 Kata Containers microVM 내부의 `/workspace`로 마운트하여, 에이전트가 자유롭게 코드 작성/실행할 수 있도록 함. 300+ 동시 VM 목표 (고밀도 모드). 상세 계획은 `KATA_SANDBOX_PLAN.md` 참조.
- **rootfs 부팅 성공 (디버그 완료)**: 커스텀 `proof-agent.img` 가 Kata 런타임으로 부팅되도록 4가지 근본 원인 수정:
  1. **ext4 저널 유지**: Kata 런타임이 `rootflags=data=ordered` 를 자동 추가하는데, 저널 없는 ext4 는 `data=ordered` 모드를 지원하지 않아 `can't mount with data=, fs mounted w/o journal` 커널 패닉 발생. 저널 제거하지 않고 유지.
  2. **`kernel_params` 에 `rw` 제거**: Kata 가 디스크를 `readonly: true` 로 설정하는데 `rw` 파라미터가 충돌. `ro` (Kata 기본값) 사용. `kernel_params = "cgroup_no_v1=all systemd.unified_cgroup_hierarchy=1"` 만 지정.
  3. **`tmp.mount` 추가**: `kata-containers.target` 이 `Requires=tmp.mount` 로 의존하지만 Debian 12 slim 에는 tmp.mount 유닛이 기본 설치되지 않음. tmpfs /tmp 가 없으면 kata-agent 가 `/tmp/policy.jsonl` 에 쓰지 못해 `Failed to initialize agent policy: Read-only file system` 로 종료. `Dockerfile.rootfs` 에서 tmp.mount 유닛 파일 수동 생성.
  4. **`dbus` 패키지 설치**: kata-agent 가 cgroup 관리를 위해 D-Bus 시스템 버스에 연결해야 함. dbus 없으면 `Establishing a D-Bus connection: No such file or directory` 로 shim 실패. `Dockerfile.rootfs` 에서 `dbus` 패키지 설치 + `dbus.socket` 을 `kata-containers.target.wants` 에 등록.
- **sandbox e2e 테스트 완료**: nerdctl + Kata 런타임으로 VM 생성/명령실행/파일읽기/파일쓰기/Python실행/Node.js실행/git diff/종료 전 단계 검증. `--read-only` 플래그 정상 동작. `--security-opt seccomp=...` 는 Kata shim 의 capget 시스콜을 차단하여 사용 불가 (seccomp 는 Kata 레벨에서 `disable_guest_seccomp=false` 로 적용).
- **Phase 1: 호스트 환경 구성** (`infra/kata-host/` — 7파일):
  - `install-kata.sh`: Kata 3.31 + Cloud Hypervisor 설치, THP 비활성화 (KSM 4KB 페이지 병합률 확보), KSM 극대화 (pages_to_scan=5000), zRAM 128GB 압축 스왑, /dev/shm 160GB (기본 모드) / 75GB (고밀도 모드), disable-thp systemd 서비스.
  - `configuration-clh.toml`: 기본 모드 (150 VM, default_memory=2048MB, DAX 1GB 윈도우, virtio-mem 동적 확장 최대 8GB, cache=auto, reclaim_guest_freed_memory=true).
  - `configuration-clh-dense.toml`: 고밀도 모드 (300+ VM, default_memory=512MB, DAX 256MB 윈도우, virtio-mem 최대 4GB).
  - `containerd-config.toml`: RuntimeClass 등록 (kata-clh, kata-clh-dense).
  - `seccomp-proof-agent.json`: 시스템 파괴 시스콜 차단 (mount, init_module, pivot_root, reboot, bpf, perf_event_open 등).
  - `apparmor-proof-agent`: 위험 경로 접근 차단 (/dev/sda, /proc/kcore, /sys/firmware 등), /workspace·/tmp·/home/agent만 read-write.
  - `kata-opa-policy.rego`: Kata Agent Policy (OPA/Rego) — CreateContainer 이미지 화이트리스트, ExecProcess 명령어 블랙리스트, CLONE_NEWUSER 제한 (Layer 5 심화 보안).
- **Phase 2: 게스트 rootfs 빌드** (`infra/kata-guest/` — 5파일):
  - `Dockerfile.rootfs`: Debian 12 slim + systemd + dbus (kata-agent cgroup 관리용) + tmp.mount 유닛 (tmpfs /tmp, kata-agent 정책 초기화용) + LibreOffice/Pandoc/Poppler/Tesseract(kor/eng/jpn/chi-sim/chi-tra)/MarkItDown/PyMuPDF + FFmpeg/faster-whisper(small 모델 사전 다운로드)/pydub/librosa + ImageMagick/Ghostscript/Pillow/OpenCV/@napi-rs/canvas + Noto CJK/Nanum/Unfonts/Liberation 폰트 + Python 3.11/Node.js 20/git + 비특권 사용자 agent(UID 1000, sudo 불가). Chrome/Puppeteer 제외 (browserless 서버 공유로 ~500MB/VM 절약).
  - `build-rootfs.sh`: Docker 빌드 → rootfs 추출 → ext4 5GB 이미지 생성 → `/opt/kata/share/kata-containers/proof-agent.img` 배포.
  - `entrypoint.sh`: VM 진입점 — workspace 확인, git init, vsock 명령 수신 루프, 명령어 블랙리스트 필터링, 환경 변수 주입 제거.
  - `browserless-helper.py` / `browserless-helper.js`: a1 browserless 서버(`http://192.168.1.50:20047`) 원격 연결 헬퍼 (Python pyppeteer / Node.js puppeteer-core).
- **Phase 3: SandboxManager 코어** (`app/backend/core/sandbox/` — 6파일):
  - `manager.py`: SandboxManager — VM 생명주기 (create/execute/status/destroy), containerd CLI 호출, dense_mode 지원, 리소스 제한 (CPU/memory/timeout).
  - `workspace.py`: WorkspaceManager — 결과 파일 준비 (original/extracted/annotations/agent_output 디렉토리), Supabase Storage 다운로드, git init + .gitignore.
  - `communicator.py`: VsockCommunicator — Kata VM 과 AF_VSOCK 통신, HTTP 폴백 지원.
  - `collector.py`: ResultCollector — workspace 전체의 허용 확장자 파일을 스캔하고 입력 원본/메타데이터를 제외한 결과 파일을 Supabase Storage에 업로드. `agent_output` 외의 workspace 경로도 수집 대상이다.
  - `security.py`: 명령어 블랙리스트 (30+ 정규식 패턴: rm -rf /, dd of=/dev/, mkfs, mount, sysctl, insmod, reboot, fork bomb, curl|sh 등), 환경 변수 주입 제거.
- **Phase 4: FastAPI API + DB 마이그레이션**:
  - `app/backend/api/sandboxes.py`: REST API — POST/GET/DELETE /api/sandboxes, /execute, /files, /files/read, /files/write, /commit, /diff, /collect, /stats (관리자용 통계). 기존 `get_current_user` 인증 재사용, sandbox 소유자 검증.
  - `app/backend/db/migrations/026_add_sandboxes.sql`: sandboxes 테이블 생성 (id, job_id, user_id, status, vm_id, workspace_path, resource_limits JSONB, result JSONB, error, created_at, updated_at, expires_at).
  - `app/backend/db/models.py`: Sandbox SQLAlchemy 모델 추가.
  - `app/backend/main.py`: sandboxes_router 등록.
  - `app/backend/config.py`: sandbox_* 설정 10개 추가 (sandbox_enabled, sandbox_data_dir, sandbox_runtime, sandbox_runtime_dense, sandbox_image, sandbox_default_timeout, sandbox_max_concurrent, sandbox_max_concurrent_dense, sandbox_browserless_url).
- **Phase 5: Node.js AI 도구** (`app/ai-backend/src/`):
  - `tools/sandbox.ts`: 14개 도구 — create_sandbox, execute_in_sandbox, read/write/list_sandbox_files, commit_sandbox_changes, get_sandbox_diff, collect_sandbox_results, destroy_sandbox, download_file, convert_document (LibreOffice/Pandoc 자동 선택), transcribe_audio (faster-whisper), process_image (ImageMagick/Pillow — resize/convert/rotate/crop/grayscale/thumbnail), get_workspace_status.
  - `tools/browserless.ts`: 3개 도구 — browse_web (스크린샷), convert_web_to_pdf, extract_web_text. a1 browserless 서버 REST API 사용.
  - `lib/proof-api.ts`: sandbox API 메서드 10개 추가 (createSandbox, executeInSandbox, getSandboxStatus, listSandboxFiles, readSandboxFile, writeSandboxFile, commitSandboxChanges, getSandboxDiff, collectSandboxResults, destroySandbox).
  - `chat/route.ts`: sandbox + browserless 도구 통합, system prompt에 sandbox/web browsing 도구 사용 규칙 추가.
- **Phase 6: 5계층 보안 방어**:
  - Layer 1: read-only rootfs (시스템 바이너리 변경 차단).
  - Layer 2: capabilities drop (CAP_SYS_ADMIN/SYS_RAWIO/SYS_MODULE/SYS_BOOT 등 전면 제거).
  - Layer 3: seccomp 프로필 (mount, mkfs, init_module, reboot 등 시스콜 차단).
  - Layer 4: AppArmor 프로필 (/dev/sda, /proc/kcore, /sys/firmware 등 위험 경로 차단).
  - Layer 5: Kata Agent Policy OPA (이미지 화이트리스트, 명령어 블랙리스트, CLONE_NEWUSER 제한).
  - Sandbox Manager 레벨 명령어 블랙리스트 (30+ 정규식 패턴).
- **Phase 7: 프론트엔드 통합**:
  - `app/frontend/src/components/SandboxBrowser.jsx`: 신규 — workspace 파일 브라우저 (트리 뷰, 디렉토리 펼침/접힘, 파일 내용 미리보기, 새로고침).
  - `app/frontend/src/pages/JobResultPage.jsx`: sandboxId state, SandboxBrowser 패널 + 토글 버튼, AgentChatModal context에 sandboxId 전달.
  - `app/frontend/src/api.js`: sandbox API 메서드 12개 추가 (createSandbox, getSandbox, executeInSandbox, listSandboxFiles, readSandboxFile, writeSandboxFile, commitSandboxChanges, getSandboxDiff, collectSandboxResults, destroySandbox, getSandboxStats).
  - `app/frontend/src/locales/{ko,en,ja}/page.json`: sandbox i18n 키 22개 추가 (runInSandbox, sandboxStatus, fileBrowser, collectResults, stats 등).
  - `app/frontend/src/components/UploadWidget.jsx`: 파일/폴더 입력을 `<label>` + `<input ref>` 패턴으로 리팩터링 (버튼 클릭 → 숨겨진 input click 간접 트리거 제거). `jobId`/`onProgress` props 추가로 기존 Job에 파일 추가 모드 지원.
  - `app/frontend/src/api.js`: `initAddFiles`/`confirmAddFiles` 메서드 추가 (기존 Job 파일 추가 — 백엔드 엔드포인트 구현 필요).
- **Phase 8: 운영 (자동 정리 + 통계)**:
  - `app/backend/workers/tasks/maintenance.py`: `cleanup_expired_sandboxes` Celery task — 만료된 sandbox 자동 종료 + 결과 수집 (sandbox_default_timeout 초과 시). 결과 수집에는 Supabase service-role 클라이언트를 사용한다.
  - `app/backend/celery_app.py`: beat_schedule에 10분 간격 cleanup-expired-sandboxes 등록.
  - `app/backend/api/sandboxes.py`: `/api/sandboxes/stats` 엔드포인트 — 상태별 카운트, 디스크 사용량, 사용자별 활성 sandbox 수 (관리자용).
- **인프라 통합**:
  - `app/docker-compose.yml`: backend 서비스에 SANDBOX_* 환경변수 6개, ai-backend 서비스에 BROWSERLESS_URL/BROWSERLESS_TOKEN 추가. backend 서비스 `privileged: true` + 호스트 containerd socket/Kata 설정/nerdctl 볼륨 마운트 (Kata VM 생성/관리용). appdata volume 의 호스트 경로를 직접 마운트 (nerdctl bind mount 경로 일치).
  - `app/Dockerfile.backend`: nerdctl 바이너리 설치 (호스트 containerd socket 통해 Kata VM 생성), git/curl 추가.
  - `app/.env.example`: sandbox 환경변수 10개 + browserless 환경변수 2개 추가.
- **메모리 최적화 전략** (300+ VM 달성):
  - browserless 서버 공유 (a1, ~500MB/VM 절약).
  - virtio-mem 동적 메모리 (기본 512MB, 필요 시 4GB 확장, idle 시 회수).
  - KSM 페이지 병합 (THP 비활성화 후 4KB 단위, ~40% 절약).
  - zRAM 압축 스왑 (128GB, zstd 압축, 3:1 압축률).
  - virtio-fs DAX (host buffer cache를 guest에 직접 매핑, guest page cache 중복 제거).
  - reclaim_guest_freed_memory (게스트 해제 메모리 호스트 회수).
- **핵심 파일**: `KATA_SANDBOX_PLAN.md`, `infra/kata-host/`(7파일), `infra/kata-guest/`(5파일), `app/backend/core/sandbox/`(6파일), `app/backend/api/sandboxes.py`, `app/backend/db/migrations/026_add_sandboxes.sql`, `app/backend/workers/tasks.py`, `app/backend/celery_app.py`, `app/backend/config.py`, `app/backend/main.py`, `app/ai-backend/src/tools/sandbox.ts`, `app/ai-backend/src/tools/browserless.ts`, `app/ai-backend/src/lib/proof-api.ts`, `app/ai-backend/src/chat/route.ts`, `app/frontend/src/components/SandboxBrowser.jsx`, `app/frontend/src/pages/JobResultPage.jsx`, `app/frontend/src/api.js`, `app/frontend/src/locales/*/page.json`, `app/docker-compose.yml`, `app/.env.example`.

### AI agent 채팅 — Vercel ai-chatbot 템플릿 기반 UI 재작성 + FastAPI 리버스 프록시

- **FastAPI `/api/ai/*` 리버스 프록시** (`app/backend/main.py`, `app/backend/config.py`): Vercel AI SDK 5.x `useChat`가 `POST /api/ai/chat`으로 스트리밍 요청을 보내는데, Vite dev server proxy는 로컬 개발에서만 동작하고 프로덕션/단일 오리진 환경에서는 FastAPI가 빌드된 SPA를 서빙하므로 `POST /api/ai/chat`이 SPA catch-all GET 라우트에 걸려 **405 Method Not Allowed**를 반환하던 버그 수정. FastAPI에 `/api/ai/{path:path}` 리버스 프록시 라우트를 SPA catch-all 앞에 추가해 Node.js AI 백엔드(`ai_backend_url`, 기본값 `http://localhost:3001`)로 httpx 스트리밍 relay. hop-by-hop 헤더 제외, 모든 HTTP 메서드 지원.
- **`vite.config.js` `loadEnv` 버그 수정**: 기존 코드가 `process.env.VITE_DEV_BACKEND_URL`을 읽었으나 이는 쉘 환경변수이지 Vite env 파일의 변수가 아니어서 `.env.development`의 `VITE_DEV_BACKEND_URL`/`VITE_DEV_AI_BACKEND_URL`을 무시하고 항상 fallback 값(`192.168.1.50:28181`)을 사용하던 버그 수정. `loadEnv(mode, cwd/.., '')`로 envDir에서 env 파일을 로드.
- **Vercel ai-chatbot 템플릿 구조 포팅** (`app/frontend/src/components/ai-chat/`): shadcn/ui 의존성 없이 Tailwind + MD3 토큰으로 자체 구현. 템플릿의 컴포넌트 구조(`messages.tsx`, `message.tsx`, `ai-elements/tool.tsx`, `ai-elements/prompt-input.tsx`, `greeting.tsx`, `suggested-actions.tsx`)를 그대로 재구현.
  - **`Shimmer.jsx`**: "Thinking..." 그라데이션 스윕 애니메이션 (CSS `ai-chat-shimmer`).
  - **`Greeting.jsx`**: 빈 상태 중앙 환영 메시지 ("도와드릴까요?").
  - **`Tool.jsx`**: collapsible 도구 카드 + 상태 배지 (실행 중/완료/오류/거부). `Wrench` 아이콘 + 상태별 아이콘 + input/output JSON 토글.
  - **`Message.jsx`**: `PreviewMessage` + `ThinkingMessage`. 어시스턴트=좌측 Sparkles 아바타 + 전체 폭 콘텐츠(풍선 없음), 사용자=우측 정렬 풍선(`rounded-2xl rounded-br-md` + 그라데이션). `marked`로 마크다운 렌더링 (GFM + breaks).
  - **`Messages.jsx`**: 메시지 목록 + `useMessages` 훅(자동 스크롤, 맨 아래 감지) + scroll-to-bottom 버튼. 빈 상태면 `Greeting` 오버레이.
  - **`PromptInput.jsx`**: textarea composer (자동 높이 조정, Enter=전송/Shift+Enter=줄바꿈, 중지 버튼). `rounded-2xl` + focus shadow.
  - **`SuggestedActions.jsx`**: 컨텍스트별 제안 칩 (PDF=하이라이트/코멘트, 마크다운=글 다듬기/표 정리, 엑셀=셀 업데이트/행 추가).
- **`AgentChatModal.jsx` 재작성**: 새 `ai-chat/` 컴포넌트 조합. 헤더에 컨텍스트 표시(sourceType · activeEditor), 배경 클릭으로 닫기, system 메시지 필터링, 빈 상태 시 `SuggestedActions` 표시.
- **`AgentInputBar.jsx` 재작성**: 템플릿 composer 스타일 차용 (Sparkles 아이콘 + `rounded-2xl` + ArrowUp 버튼 + backdrop-blur).
- **`index.css` 애니메이션/스타일 추가**: `ai-chat-shimmer`, `ai-chat-fade-up`, `ai-chat-greeting`, `ai-chat-tool-open` 애니메이션 + `.ai-chat-markdown` 마크다운 렌더링 스타일 (코드 블록, 표, 인용구 등).
- **`AgentToolRenderer.jsx` deprecated**: 새 `Tool.jsx`로 대체. 더 이상 import되지 않음.
- **핵심 파일**: `app/backend/main.py`, `app/backend/config.py`, `app/frontend/vite.config.js`, `app/frontend/src/components/ai-chat/`(신규 7파일), `app/frontend/src/components/AgentChatModal.jsx`, `app/frontend/src/components/AgentInputBar.jsx`, `app/frontend/src/index.css`.

### AI agent — LangGraph → Vercel AI SDK 5.x 마이그레이션 + 채팅 버그 4종 수정

- **백엔드 마이그레이션** (`7cc6bf5`): LangGraph 기반 에이전트 런타임을 Vercel AI SDK 5.x (`ai@5.0.210`, `@ai-sdk/openai`) 기반 Node.js 백엔드(`app/ai-backend/`)로 교체. `streamText` + `tools` + `stopWhen: stepCountIs(N)` 로 단일 스트림 내 도구 루프를 처리하고, `toUIMessageStreamResponse()`로 프론트엔드에 스트리밍 응답을 전송. 도구 구현체(`tools/annotations.ts`, `tools/markdown.ts`, `tools/spreadsheet.ts`)는 Python FastAPI(`/api/v1/*`)를 호출해 기존 비즈니스 로직을 그대로 재사용.
- **ISSUE-001 — 인증 헤더 누락** (`75cffc7`): `useCompletion`/`useChat`가 `Authorization`/`X-Api-Key` 헤더를 전송하지 않아 AI 백엔드가 401을 반환하며 즉시 실패. `headers` 옵션으로 토큰/API key를 주입.
- **ISSUE-002 — `useCompletion` body 구조 오류** (`87f743a`): Novel의 `useCompletion` 패턴을 참고해 `body`에 `prompt`만 보내던 것을, Vercel AI SDK가 기대하는 `{ messages, ...options }` 형태로 수정.
- **ISSUE-003 — AgentInputBar focus로 인한 채팅 메시지 손실** (`f839280`): `AgentInputBar`가 input focus 시점에 채팅 모달을 열어 typed text가 유실되고 `AgentChatModal`이 빈 메시지를 전송하던 버그. submit 시점에 모달을 열고 `initialText`를 전달하도록 변경, `AgentChatModal`은 이미 열려 있어도 `initialText` 변경을 반영.
- **ISSUE-004 — `@ai-sdk/react` 버전 불일치** (`54f96ba`, `e449fd1`): `package.json`에 `@ai-sdk/react: ^1.0.0`(v1 API)이 고정되어 `ai@5.0.210`(v5 API)와 짝이 맞지 않아 `chat.sendMessage is not a function` 런타임 에러로 전송 버튼이 무반응. `@ai-sdk/react`를 `2.0.212`(ai-v5 dist-tag)로 업그레이드.
  - **`useAgentChat.ts` v5 API 재작성**: `sendMessage({ text })`, `parts` 기반 메시지 포맷, `transport`/`messages` 초기값 키 사용.
  - **무한 루프/브라우저 프리징 수정**: 매 렌더마다 `new DefaultChatTransport(...)`가 재생성되고 `useChat` 반환 객체가 `useCallback` deps에 들어가 스트리밍 토큰 도착 시마다 `sendContextualMessage`가 재실행 → 렌더러 CPU 100%+ 무한 루프. `transport`를 `useMemo`로 안정화하고 `sendMessage` 호출을 `ref` 기반으로 변경, 불필요한 `sendAutomaticallyWhen` 제거.
  - **`AgentToolRenderer.jsx` v5 tool part 포맷**: v1 형식(`part.toolInvocation`)을 기대하던 것을 v5 tool part(`type: "tool-${name}"`, `state`/`input`/`output`이 part에 직접 존재)로 수정.
- **핵심 파일**: `app/ai-backend/`(신규), `app/frontend/src/hooks/useAgentChat.ts`, `app/frontend/src/components/AgentChatModal.jsx`, `app/frontend/src/components/AgentInputBar.jsx`, `app/frontend/src/components/AgentToolRenderer.jsx`, `app/frontend/src/components/AiMenu.jsx`, `app/frontend/package.json`.

### AI agent 개발/검증 및 프론트엔드 연동

- **개발 환경 mock 모드 해제**: 로컬 백엔드의 `/api/dev/login` bypass가 405로 실패하면 프론트엔드가 mock 사용자로 전환되었는데, 이제는 API key 인증으로 백엔드와 직접 통신한다. `AuthContext.jsx`가 dev 모드에서 세션 대신 mock 사용자를 유지하면서 `api.js`가 `X-Api-Key` 헤더를 전송, `backend/api/auth.py`의 `get_current_user`가 `x-api-key` 헤더를 수락한다. `DevBypassBanner.jsx`도 API key 상태를 반영하도록 갱신.
- **API key 인증을 job 엔드포인트로 확장**: 기존 `/api/v1/agent/*`와 `/api/auth/me`만 API key를 지원했으나, `/api/jobs/*` 엔드포인트에도 `get_current_user_or_api_key` dependency를 추가해 웹 포털 세션과 API key를 모두 허용. 이로 인해 dev API key로 결과 페이지(`JobResultPage`)와 PDF 주석 UI를 확인할 수 있다.
- **HITL editor agent 검증**: `/api/v1/agent/run`으로 `editor` 그래프를 실행, `ask_user` 호출 시 `AgentRun`이 `interrupted` 상태로 전환되고 `AgentApprovalModal`이 표시됨을 확인. `/api/v1/agent/resume/{run_id}`로 사용자 승인 값을 전달하면 실행이 재개되어 `final_markdown`이 에디터에 반영된다.
- **Annotator agent end-to-end API 테스트**: `test_annotator.py` 스크립트로 테스트 PDF를 업로드하고 `AgentRun`을 직접 실행, `search_text` → `add_highlight` → `finish` 도구 체인이 동작하고 `final_annotations`에 highlight 항목이 생성되는 것을 확인.
- **PDF 주석 UI 버그 수정**:
  - `AnnotationListPanel.jsx`: EmbedPDF가 반환하는 numeric annotation type(예: `9` = highlight)에서 `(ann.type || "").toLowerCase()`가 `TypeError`를 내는 문제를 수정. 숫자형 type을 highlight/freetext로 매핑하고 `intent`도 함께 확인.
  - `JobResultPage.jsx`: AI 주석 생성(`startAnnotate` / `startAnnotateEdit`) 시 `i18n.language`를 참조했지만 `useTranslation()`에서 `i18n`을 destructuring 하지 않아 `i18n is not defined` 오류가 발생했던 버그를 수정.
- **개발 환경 UX 개선**: `api.js`의 `previewJob`이 dev 모드에서 브라우저/프록시 캐시로 인해 오래된 400 응답이 재사용되는 것을 방지하기 위해 `_t` 캐시 버스팅 파라미터를 추가. 임시 `/editor-test` 라우트는 제거.
- **핵심 파일**: `app/backend/api/auth.py`, `app/backend/api/jobs.py`, `app/frontend/src/AuthContext.jsx`, `app/frontend/src/api.js`, `app/frontend/src/components/DevBypassBanner.jsx`, `app/frontend/src/components/AnnotationListPanel.jsx`, `app/frontend/src/pages/JobResultPage.jsx`, `app/frontend/src/components/SourcePanel.jsx`, `app/backend/tests/test_agent_graph.py`, `test_annotator.py`.

### AI 주석 — 페이지 범위 지정 + 주석 편집 패널

- **페이지 범위 지정**: AI 주석 생성 시 처리할 페이지를 지정할 수 있다. FAB 다이얼로그의 "고급 옵션" 토글을 펼치면 페이지 범위 입력 필드가 표시되며, `"1-5,7,10-12"` 형태로 입력한다. 빈 값이면 **현재 보고 있는 페이지만** 처리 (기본값). 이전에는 항상 전체 페이지를 처리해 LLM 프롬프트가 `MAX_ELEMENTS_FOR_LLM=400`으로 잘려 뒷부분 페이지의 요소가 무시되는 문제가 있었다.
- **`_parse_page_range()` 헬퍼** (`api/jobs.py`): `"1-5,7,10-12"` 문자열을 1-based 페이지 번호 리스트로 변환. 역순 범위(`5-3`) 허용, `total_pages` 초과 시 클램프, 빈 입력 → None(전체 페이지 의미).
- **과금 변경**: 지정한 페이지 수만큼만 과금 (`units = page_range_count`). 관리자는 무제한. `annotated_pdf_files` entry에 `page_range` 저장하여 재시도/중복 검사에 사용.
- **백엔드 필터링** (`pdf_annotate_converter.py:run()`): `page_range`가 None이 아니면 `image_paths`와 `elements`를 지정 페이지로 필터링. Vision LLM 경로와 텍스트 LLM 경로 모두에 적용. `tasks.py:annotate_pdf_job()` 시그니처에 `page_range` 파라미터 추가.
- **사용자 편집 AI 주석 보존**: 같은 `annotation_index`로 AI 주석을 재생성해도 사용자가 편집한 주석을 덮어쓰지 않도록 보존. `_merge_annotations_for_run()`이 `_userEdited: true` 플래그가 있는 주석은 제거하지 않고 유지. `save_user_annotations()`가 export된 주석과 기존 JSON을 비교해 사용자가 AI 주석의 색상/코멘트/위치/투명도를 변경했는지 감지 (`_is_annotation_edited()`), 변경 시 `_mark_user_edited()`로 플래그 설정. 사용자가 삭제한 AI 주석은 export에 없으므로 자동 제외.
- **주석 편집 패널** (`AnnotationListPanel.jsx`): PDF 뷰어 우측 상단 List 아이콘 버튼으로 토글. 주석을 페이지별로 그룹화해 리스트 표시. 항목 클릭 시 해당 페이지로 스크롤 + 주석 선택. 확장 시 색상(8색 컬러피커)/코멘트(textarea)/투명도(range slider) 편집 UI + 삭제 버튼. 변경 시 기존 `onAnnotationChanged` debounce 자동 저장 경로 재사용.
- **PdfViewer ref API 확장**: `getAnnotations()`, `selectAnnotation(pageIndex, id)`, `updateAnnotation(pageIndex, id, patch)`, `deleteAnnotation(pageIndex, id)`, `scrollToPage(pageNumber)` 노출. embedpdf annotation plugin의 메서드를 래핑.
- **i18n 키 추가** (ko/en/ja `page.json`): `annotateAdvancedOptions`, `annotatePageRangeLabel`, `annotatePageRangePlaceholder`, `annotatePageRangeHint`, `annotationListTitle`, `annotationListEmpty`, `annotationPage`, `annotationTypeHighlight`, `annotationTypeCallout`, `annotationNoText`, `annotationEditColor`, `annotationEditComment`, `annotationEditOpacity`, `annotationDelete`.
- **핵심 파일**: `api/jobs.py`, `workers/tasks.py`, `core/pdf_annotate_converter.py`, `api.js`, `PdfViewer.jsx`, `SourcePanel.jsx`, `AnnotationListPanel.jsx`, `JobResultPage.jsx`.

### AI 주석 — Callout (FreeTextCallout)

- **여백 주석 → callout 전환**: 기존 `margin_note`/`both` 모드는 페이지 우측에 mediabox를 확장해 FREETEXT 박스를 배치했으나, JSON 오버레이 방식 전환 후 mediabox 확장이 빠져 여백 박스가 페이지 밖에 떠 있어 보이지 않는 버그가 있었다. 이를 embedpdf의 `FreeTextCallout`(텍스트 박스 + 화살표 리더 라인)로 대체 — 페이지 내 빈 모서리/외곽 여백에 텍스트 박스를 배치하고 화살표로 원본 요소를 가리킨다.
- **`build_embedpdf_annotations()` 시그니처 변경**: 새 파라미터 `page_elements_bboxes: dict[int, list[tuple]]` 추가 (1-based page_no → PDF user-space bbox 목록). callout 텍스트 박스 배치 시 기존 OCR 요소와의 충돌 회피에 사용.
- **callout 배치 알고리즘** (`pdf_annotator.py:_find_free_callout_slot()`): 페이지 4모서리 + 4외곽 여백 중심 후보 영역 중 기존 요소/대상/같은 페이지 선행 callout 박스와 충돌하지 않는 가장 가까운 빈 영역 선택. 전부 충돌하면 최소 겹침 후보로 폴백.
- **calloutLine 계산** (`_compute_callout_line()`): `[arrowTip, knee, connectionPoint]` 3점으로 L자 리더 라인 생성. arrowTip은 대상 가장자리 중점, knee는 꺾임점, connectionPoint는 텍스트 박스 가장자리 중점(embedpdf `computeCalloutConnectionPoint` 로직과 동일). knee가 텍스트 박스 내부에 있으면 2점 직선 callout으로 폴백.
- **EmbedPDF 호환 필드**: callout 주석에 `intent: "FreeTextCallout"`, `calloutLine`, `rectangleDifferences`(PDF /RD), `lineEnding: 4`(OpenArrow), `strokeColor`, `strokeWidth` 추가. `importAnnotations()`/`exportAnnotations()` round-trip 지원.
- **코드 정리**: `annotate_pdf()`, `_extend_mediabox_for_visual_margins()`, `_layout_margin_notes()`, `_apply_target()` 및 관련 상수(`MARGIN_WIDTH_PT` 등) 제거 — 더 이상 PDF에 주석을 구워 넣거나 mediabox를 확장하지 않음.
- **converter 연동**: `pdf_annotate_converter.py`에서 `elements`의 `bbox_px`를 PDF user-space로 변환해 `page_elements_bboxes`를 빌드하고 `build_embedpdf_annotations()`에 전달. 고급주석(Vision LLM) 경로에서는 `elements`가 비어 충돌 검사 없이 모서리에 배치.
- **테스트 파일**: `test_annotate_compare.py`를 `build_embedpdf_annotations` 기반으로 업데이트 — PDF + annotations JSON을 분리 저장.
- **핵심 파일**: `pdf_annotator.py`, `pdf_annotate_converter.py`, `test_annotate_compare.py`.

### Searchable PDF (텍스트 레이어)

- **업로드 시점 텍스트 레이어 생성**: PaddleOCR이 반환한 `overall_ocr_res`의 `rec_texts`/`rec_boxes`를 사용해 원본 PDF/이미지에 투명 텍스트 레이어를 추가. `app/backend/core/pdf_text_layer.py`의 `add_text_layer_from_ocr()`가 핵심.
- **원본 미리보기 대체**: `app/backend/api/jobs.py:_source_files()`와 `_build_source_file_item()`에서 원본 PDF/이미지의 `preview_url`을 `searchable_pdf_storage_path`로 대체. 다운로드용 `url`은 원본 유지.
- **DB 메타데이터**: `Job` 테이블에 `searchable_pdf_storage_path` 컬럼 추가. 단일 PDF 업로드는 Job 컬럼 사용, 멀티파일 이미지는 `extracted_files` JSONB에 `searchable_pdf_storage_path` 필드 추가.
- **AI 주석 최적화**: `app/backend/core/pdf_annotate_converter.py`에서 `job.searchable_pdf_storage_path`가 있으면 OCR을 생략하고, `_collect_page_elements_from_searchable_pdf()`로 텍스트 레이어에서 `elements`를 추출. `TextLayerSearcher`로 직접 bbox 검색.
- **좌표 보정**: `pdf_annotator.py`와 `pdf_user_annotator.py`의 `_rect_to_embedpdf_rect()`/`_fitz_rect_to_embedpdf_rect()`에 `page.rect.x0`을 고려해 CropBox/MediaBox가 있는 PDF에서도 정확히 정렬.
- **핵심 파일**: `pdf_text_layer.py`, `pipeline_vision.py`, `workers/tasks.py`, `api/jobs.py`, `pdf_annotate_converter.py`, `db/models.py`.

### AI 주석 (PDF Annotation)

- **비동기/원자적 인덱스**: 주석 생성 요청마다 고유 인덱스를 원자적으로 할당해 파일 덮어쓰기 및 동시 생성 충돌 방지.
- **JSON 오버레이 단일 진실원**: 주석을 PDF에 구워 넣지 않고 embedpdf `AnnotationTransferItem[]` JSON 오버레이로만 표시. `pdf_annotate_converter.run()`은 깨끗한 보정 이미지 PDF를 표시 기반으로 업로드하고 `build_embedpdf_annotations()`로 JSON을 생성. 하이라이트는 `HIGHLIGHT`, 코멘트는 `FreeTextCallout`(텍스트 박스 + 화살표 리더 라인)로 생성 — 페이지 내 빈 모서리/외곽 여백에 배치. flatten 다운로드는 embedpdf snippet 자체의 다운로드 UI가 처리.
- **원본 내장 주석 중복 방지**: 원본 PDF에 이미 내장된 하이라이트/코멘트 주석이 있으면, embedpdf가 이를 자동으로 렌더링하고 `exportAnnotations()`에 포함해 `user_annotations.json`이 반복 저장되면서 중복 증식하는 문제를 방지. `api/jobs.py:_source_files()`에서 원본 PDF의 내장 주석을 PyMuPDF로 추출하여 `user_annotations.json` 초기값으로 저장하고, 주석이 제거된 `clean.pdf`를 별도 Storage 경로(`{job_id}/clean.pdf`)에 업로드해 원본 대신 표시. `pdf_user_annotator.py`에 `extract_pdf_annotations()`와 `remove_pdf_annotations()` 추가.
- **좌표 변환**: `_rect_to_embedpdf_rect()`가 PDF user-space(원점 좌하단, y↑)를 embedpdf device-space(원점 좌상단, y↓)로 변환할 때 `origin.y = page_height - y1`로 y축 flip. embedpdf가 annotation `rect.origin.y`를 CSS `top`으로 직접 렌더링하므로 flip이 필수.
- **JSONB 변경 감지**: `annotated_pdf_files`는 SQLAlchemy JSONB 컬럼이며, dict/list를 직접 변경한 뒤 재할당해도 SQLAlchemy가 변경을 감지하지 못하는 경우가 있으므로, 해당 컬럼을 수정하는 모든 경로(`pdf_annotate_converter.py`, `api/jobs.py`)에서 `flag_modified(job, "annotated_pdf_files")`를 호출해야 한다. 이를 누락하면 주석 생성이 완료되어도 DB entry 상태가 `processing`으로 남는다.
- **자동 저장**: 원본 패널에서 사용자가 그린 주석을 자동 저장하며, 무한 파일 증식 및 404 깜빡임 문제를 방지.
- **AI 주석 생성**: PDF 패널 하단 중앙 플로팅 FAB으로 AI 주석 생성 트리거 이동; Vision LLM이 mode/comment_mode를 동적으로 결정.
- **실패 처리**: AI 주석 생성이 실패(`status === "error"`)하거나 처리 중(`status === "processing"`)인 파일의 파일탭(좌측 다중 파일 목록)에 재시도/취소 버튼 표시; `SourcePanel.jsx`에서 `onRetryAnnotation` / `onDeleteFile` 콜백으로 `JobResultPage`와 연결.
- **버그 수정**: 병렬 AI 주석 생성 중에도 `converting` 상태로 FAB이 비활성화되지 않던 문제 수정.

### 마크다운 에디터

- **자동 저장**: 결과 페이지 마크다운 에디터에 1초 debounce 자동 저장 적용; `lastMarkdownRef` 동기화로 피드백 및 콘텐츠 중복/리셋 문제 해결.
- **AI 텍스트 생성**: Tiptap 에디터에 Novel의 `ai/react` `useCompletion` 패턴을 참고한 AI 텍스트 생성 기능 추가.
  - **백엔드**: `POST /api/v1/ai/generate` 스트리밍 엔드포인트 (`app/backend/api/v1/ai.py`), `app/backend/core/ai_client.py`에서 OpenAI-compatible vLLM/llama.cpp endpoint로 스트리밍 요청.
  - **LLM**: 기존 `default_llm_endpoint` (Gemma-4 26B vLLM) 재사용; `app/backend/core/llm_utils.py`로 `chat_template_kwargs.enable_thinking=true`와 `thinking_token_budget=256` 공통 처리.
  - **프론트**: `app/frontend/src/components/AiMenu.jsx` — Improve, Fix grammar, Make shorter, Make longer, Continue writing, Custom command (zap) 기능 제공.
  - **UX**: 텍스트 선택 시 Tiptap `BubbleMenu`로 AI 메뉴를 표시하고, 툴바에도 AI 버튼을 유지; 선택하지 않은 상태에서도 버튼이 활성화되어 AI 기능을 바로 인지할 수 있도록 수정.
  - **i18n**: `page:components.ai.*` 번역 키를 `ko/page.json`, `en/page.json`, `ja/page.json`에 추가.
- **UX 개선**: AI 버튼이 `editable` prop 누락으로 렌더링되지 않던 문제 수정; 번역 키(namespace) 불일치로 키가 그대로 노출되던 문제 수정.

### 엑셀 베이직

- **자동 저장**: 1초 debounce 자동 저장 추가.
- **UI 정리**: 베이직 탭에서 다운로드/초기화 버튼이 포함된 툴바 제거.
- **안정성**: `handleAutoSave` 사용 순서로 인한 TDZ(Temporal Dead Zone) 에러 수정.

### 개발 환경

- **로컬 프론트엔드 개선**: a1 백엔드/Supabase 연결을 위한 `app/.env.development.example` 및 `scripts/dev-tunnel.sh` 보강.

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
    api/            Internal API routers
      v1/           Public API v1 (jobs, account, keys, agent, ai)
      admin.py, auth.py, chat_conversations.py, dev_auth.py,
      ediscovery.py, flow_drawings.py, gdpr.py,
      on_premise.py, payments.py, sandboxes.py, subscriptions.py,
      supabase_proxy.py
      jobs/           Job 라우터 패키지 (api/jobs.py에서 분할)
        __init__.py     router 조립 + 테스트 호환성 re-export
        _shared.py      46개 공유 헬퍼 + 상수
        uploads.py      업로드/생성 엔드포인트
        lifecycle.py    confirm/list/get/delete 엔드포인트
        download.py     다운로드/XLSX 변환 엔드포인트
        result.py       결과 저장/페이지 수정 엔드포인트
        preview.py      미리보기/페이지 이미지 엔드포인트
        annotations.py  주석/검색/요소 조회 엔드포인트
        admin.py        관리자 Job 목록 엔드포인트
    auth/           JWT auth, API key auth (supabase_auth.py, api_key_auth.py, security.py, crypto.py)
    core/           비즈니스 로직, OCR/변환 파이프라인, 과금, 주석
      ai_client.py                 OpenAI 호환 LLM 스트리밍 클라이언트
      archive_handler.py           아카이브 처리
      cache.py                     Redis 캐시 유틸
      canonical_annotation_coords.py  주석 좌표 정규화
      converter.py                 공통 변환 유틸
      docling_client.py            Docling 서비스 클라이언트
      excel_writer.py              Excel 출력
      hwp_converter.py             HWP 변환
      job_helpers.py               Job 공통 헬퍼 (parse_columns, convert_format_alias, upload_ocr_layout)
      image_deskew.py              이미지 기울기 보정
      legal_case_profile.py        법률 사건 프로파일
      legal_elements.py            요건 사실 정의
      legal_issue_tree.py          쟁점 트리
      llm_utils.py                 LLM 공통 유틸 (chat_template, thinking budget)
      llm_xlsx_converter.py        LLM 기반 XLSX 변환
      markdown_image_rewriter.py   마크다운 이미지 경로 재작성
      markdown_sanitizer.py        마크다운 새니타이저
      media_loader.py              오디오/비디오 로더
      merge.py                     다중 파일 병합
      ocr_client.py                OCR 클라이언트 (has_pdf_text_layer, tile_large_image)
      ocr_layout.py                OCR 레이아웃 파싱
      office_converter.py          DOCX/PPTX 변환
      paddleocr_client.py          PaddleOCR 클라이언트
      paddleocr_fallback.py        PaddleOCR 폴백 제어 (회로 차단기)
      paddleocr_parameter_recommender.py  Vision LLM 샘플 기반 파라미터 추천
      password_security.py         비밀번호 해시
      pdf_annotate_converter.py    PDF 하이라이트/여백 주석 오케스트레이터
      pdf_annotator.py             PDF 주석 적용
      pdf_coordinate_transform.py  좌표계 변환
      pdf_coords.py                좌표 유틸
      pdf_optimizer.py             PDF 최적화
      pdf_preview_converter.py     PDF 미리보기 변환
      pdf_text_layer.py            서처블 PDF 텍스트 레이어 생성
      pdf_user_annotator.py        PDF user-space 주석
      pipeline_docling.py          Docling 파이프라인
      pipeline_ediscovery.py       e-Discovery GraphRAG 파이프라인
      pipeline_hybrid.py           Hybrid 파이프라인 (사용하지 않음)
      pipeline_media.py            Media 파이프라인 (오디오/비디오/이미지 라우팅)
      pipeline_vision.py           Vision 파이프라인 (PaddleOCR 우선 + vLLM fallback)
      points_service.py            포인트 비용 계산
      prompts.py                   LLM 프롬프트
      rate_limit.py                요청 속도 제한
      sandbox/                     Kata Containers 샌드박스 관리
        collector.py, communicator.py, manager.py, security.py, workspace.py
      subscription_service.py      구독/크레딧 관리 (PLAN_MONTHLY_CREDITS)
      supabase_client.py           Supabase Storage 클라이언트
      turnstile.py                 Cloudflare Turnstile 검증
      xlsx_advanced_converter.py   마크다운에서 고급 XLSX 변환
    db/             SQLAlchemy models and migrations (38 SQL files)
    workers/        Celery tasks
      tasks/         태스크 패키지 (tasks.py에서 분할)
        __init__.py     태스크 re-export + 테스트 호환성
        _helpers.py     비-태스크 헬퍼 (상태 설정, 구독 해제 등)
        job_tasks.py    run_job, run_job_added_files, recover_stuck_jobs
        maintenance.py  cleanup, auto_recharge, grant_credits
        conversion.py   convert_xlsx_advanced
        annotation_tasks.py  annotate_pdf_job, annotate_edit_job
        ediscovery_tasks.py  run_ediscovery
    docling_service/ Docling 서비스 (별도 Docker 컨테이너, main.py, Dockerfile, requirements.txt)
    paddleocr_service/ PaddleOCR 서비스 (별도 Docker 컨테이너, main.py, Dockerfile.*)
    unoserver/      LibreOffice headless 서비스 (Dockerfile)
  ai-backend/       Express + TypeScript AI 에이전트 백엔드
    src/chat/route.ts          AI 채팅 라우터 (Vercel AI SDK 5.x)
    src/lib/proof-api.ts       PROOF 백엔드 API 클라이언트
    src/server.ts              Express 서버 진입점
    src/tools/                 AI 에이전트 도구
      annotations.ts           PDF 주석 도구 (highlight, callout, batch)
      browserless.ts           원격 브라우저 도구
      ediscovery.ts            e-Discovery 도구
      flow.ts                  Flow drawing 도구
      mapper.ts                Element mapper 도구
      markdown.ts              마크다운 도구
      sandbox.ts               샌드박스 도구
      spreadsheet.ts           스프레드시트 도구
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
  llmlingua-service/  LLMLingua-2 프롬프트 압축 서비스 (별도 Docker 컨테이너)
  Dockerfile.backend
  docker-compose.yml
  docker-compose.docling.yml
  docker-compose.paddleocr.yml
  .env.example
infra/
  mailu/            Mailu mail server deployment
  kata-guest/       Kata Containers guest 설정
  kata-host/        Kata Containers host 설정
ocr_output/         OCR output artifacts (ignored in git)
*.py                Standalone scripts and test helpers
```

## Environment Setup

Copy `app/.env.example` to `app/.env` and fill in:

- `DATABASE_URL`
- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, `SUPABASE_JWT_SECRET`
- `REDIS_URL`
- `DEFAULT_LLM_ENDPOINT`, `DEFAULT_LLM_MODEL` (vLLM for images/PDF)
- `MEDIA_LLM_ENDPOINT`, `MEDIA_LLM_MODEL` (llama.cpp E4B for audio/video + image share) — **선택값**. `config.py`에 기본값 `http://192.168.1.82:18080/v1`이 하드코딩되어 있으나, E4B 서버가 현재 다운/비활성화 상태이므로 빈 값으로 두면 `pipeline_media.py:_resolve()`가 자동으로 vLLM만 사용하도록 폴백함. E4B를 비활성화하려면 `.env`에서 빈 값으로 설정하거나 관리자 페이지에서 `media_llm_endpoint`를 비우면 됨.
- `PUBLIC_BASE_URL` (external URL for download links)
- `SUPABASE_PUBLIC_URL` (external proxied URL; 빈 값이면 `SUPABASE_URL` 사용)
- `SECRET_KEY` (민감 설정 암호화/세션 서명용)
- `ADMIN_EMAIL`, `ADMIN_INITIAL_PASSWORD`
- Turnstile: `TURNSTILE_SITE_KEY`, `TURNSTILE_WORKER_URL`, `VITE_TURNSTILE_SITE_KEY`, `VITE_TURNSTILE_WORKER_URL`
- Paddle: `PADDLE_API_KEY` (결제)
- PaddleOCR: `PADDLEOCR_SERVICE_URL`, `PADDLEOCR_API_TOKEN`, `PADDLEOCR_API_URL`, `PADDLEOCR_FALLBACK_ENABLED`
- Docling: `DOCLING_ENABLED`, `DOCLING_SERVICE_URL`, `DOCLING_REFINEMENT_ENABLED`

## Local Development

### Full Local Stack (backend + frontend + worker + ai-backend)

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

# AI Backend (Express + TypeScript, Vercel AI SDK)
cd ../ai-backend
npm install
npm run dev          # 개발 모드 (ts-node)
# 또는 npm run build && npm start

# Docs (Docusaurus)
cd ../docs
npm install
npm run build        # outputs to docs/build/
npm run start        # dev server at localhost:3000
```

### Local Frontend with a1 Backend/Supabase

a1 서버에서 백엔드/워커/Supabase가 이미 실행 중일 때, 로컬 머신에서 프론트엔드만 띄워 개발할 수 있습니다. Vite dev server의 `/api`, `/supabase` 프록시를 a1로 전달합니다.

#### 1. 환경변수 설정

`app/.env.development.example`을 `app/.env.development`로 복사하고 값을 채웁니다.

```bash
cp app/.env.development.example app/.env.development
```

핵심 변수 (모두 `app/` 디렉토리의 `.env*` 파일에 작성 — `vite.config.js`의 `envDir: '..'` 설정 때문에 `app/frontend/.env*`는 로드되지 않음):

- `VITE_DEV_BACKEND_URL`: a1 백엔드 주소
  - 내부망 직접 연결: `http://192.168.1.50:28181`
  - SSH 터널링 사용: `http://localhost:28181`
- `VITE_DEV_API_KEY`: 로컬 데브 모드에서 마크다운 에디터 AI 및 에이전트 채팅 인증용 dev API key (a1에서 발급, `chu_live_` 접두사). 없으면 폴백값 `chu_live_testkey12345`가 사용되어 401 "Invalid API key" 발생.
- `VITE_SUPABASE_ANON_KEY`: a1 Supabase anon key
- `VITE_TURNSTILE_SITE_KEY` / `VITE_TURNSTILE_WORKER_URL`: CAPTCHA 사용 시 (비워두면 미사용)

#### 2. 직접 연결 (내부망)

```bash
cd app/frontend
npm install
npm run dev
```

`http://localhost:5173`에서 프론트엔드가 실행되며, API/Supabase 요청은 `VITE_DEV_BACKEND_URL`로 프록시됩니다.

#### 3. SSH 터널링 (내부망에 접근 불가하거나 원격 개발 시)

```bash
# LAN 우선, 실패 시 WAN으로 시도
./scripts/dev-tunnel.sh

# 터미널을 하나 더 열어
VITE_DEV_BACKEND_URL=http://localhost:28181 npm run dev
```

스크립트는 a1의 `28181`(backend)과 `28000`(Supabase) 포트를 로컬로 포워드합니다. SSH 키는 `~/Documents/ssh-key-backup/`에서 자동 감지하며, 필요하면 `SSH_KEY` 환경변수로 직접 지정할 수 있습니다. WAN 주소는 `A1_WAN_HOST` 환경변수로 설정합니다.

#### 4. 인증 방식

- **Dev bypass 자동 로그인** (기본): a1 `.env`에 `DEV_BYPASS_AUTH=true`가 설정되어 있으면, `npm run dev` 실행 시 `/api/dev/login`으로 자동 로그인됩니다. 화면 상단에 파란색 배너가 표시됩니다. **프로덕션 a1에서는 절대 활성화하지 마세요.**
  - `DEV_BYPASS_EMAIL` / `DEV_BYPASS_PASSWORD`로 설정된 계정을 실제 Supabase Auth에 로그인하여 세션을 발급합니다. local DB에도 동일 사용자가 있어야 업로드 및 job 생성 등 모든 기능이 정상 동작합니다.
  - `DEV_BYPASS_AUTH_EMAIL` / `DEV_BYPASS_AUTH_PASSWORD`는 사용하지 않습니다. (config.py의 필드명은 `dev_bypass_email` / `dev_bypass_password`이며, Pydantic은 `DEV_BYPASS_EMAIL` / `DEV_BYPASS_PASSWORD` 환경변수를 매핑합니다.)
- **실제 Supabase Auth**: a1 `.env`에 `DEV_BYPASS_AUTH=false`이면 정상적인 회원가입/로그인을 사용합니다. Turnstile이 활성화되어 있으면 CAPTCHA도 필요합니다.
- **Mock 모드**: a1에 연결할 수 없거나 bypass가 비활성화되면 자동으로 mock 사용자로 전환됩니다. 화면 상단에 노란색 배너가 표시됩니다. 이는 UI 레이아웃 점검용이며 실제 데이터 흐름은 테스트하지 않습니다.

#### 5. TUS 업로드 개발 주의

a1 Supabase의 `SUPABASE_PUBLIC_URL`이 `https://proof.teamcat.app/supabase`로 설정되어 있으면, TUS 업로드 중 Supabase가 반환하는 `Location` 헤더가 외부 도메인을 가리킬 수 있습니다. `app/frontend/src/tusUpload.js`는 개발 모드에서 이 URL을 자동으로 `window.location.origin/supabase`로 재작성하여 로컬 개발이 원활하도록 합니다.

## LLM Routing & Load Balancing

- **Audio/Video**: E4B (llama.cpp, `192.168.1.82:18080`) — **현재 서버 다운, 비활성화**
- **PDF routing** (임시 정책 — vLLM/Docling 서버 개선 전까지):
  - **라우팅 결정 단위 = 전체 PDF(작업 단위)**. `tasks.py`에서 PDF 파일 전체에 대해 `has_pdf_text_layer()`를 1회 호출해 라우팅 경로를 결정. 페이지별 개별 라우팅 분기는 없음.
  - **기본변환** (`ocr_model == "basic"`): `has_pdf_text_layer()` → True면 Docling 파이프라인(`run_docling`) + `_register_searchable_pdf_if_text_layer`로 원본 텍스트 레이어를 searchable PDF로 등록(OCR 재생성 방지). False면 `run_vision`(PaddleOCR 우선).
  - **고급변환** (`ocr_model == "premium"`): 무조건 `run_vision` — 모든 페이지 PaddleOCR 우선, 실패 시 vLLM fallback.
  - **이미지 파일**: `run_media` → PaddleOCR 우선 (`is_fallback_preferred() == True`)
  - 라우팅 분기 순서: `tasks.py`에서 `ocr_model == "basic" and has_pdf_text_layer()` → True면 Docling, 그 외 PDF는 `run_vision`
  - **`run_vision` 내부 동작 (페이지 단위 처리)**: `pipeline_vision.py:run_vision`은 위에서 결정된 단일 경로를 모든 페이지에 동일하게 적용. `run_vision` 자체는 개별 페이지 텍스트 레이어를 재검사하지 않고, 전체 페이지를 PaddleOCR 우선 → (실패 시) vLLM fallback 순으로 처리. 즉 "텍스트 레이어 검사"는 작업 단위 분기에서만 발생하고 `run_vision` 진입 후에는 페이지별 분기가 없음.
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
- **현재 정책**: `is_fallback_preferred()`는 항상 `True`를 반환한다. 이름은 "fallback"이지만 지금은 PaddleOCR 서비스가 **주 OCR 경로**이므로 정상 동작이다 (a1 로컬 PP-OCRv5). 이 값을 내리면 이미지 OCR이 Docling으로 되돌아가 bbox(주석/searchable PDF/에이전트 좌표)를 잃는다 — 함부로 끄지 말 것.
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
- **OCR 엔진 선택은 Docling과 무관**: 스캔/이미지 OCR은 전부 `paddleocr_service`가 담당하며 엔진은 그쪽 `PADDLEOCR_BACKEND`로 고른다. 앱 설정에 있던 `ocr_backend`는 어디서도 읽지 않는 죽은 값이어서 제거했다 (`config.py`).
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

- **완료 메일** (`build_done_email`): 사용자 프로필 언어에 따라 결과 페이지 링크(`/jobs/{jobId}`) 포함.
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
  - `autoSaveMarkdown()`는 `pages.length > 0`으로 페이징 모드 판단하여 PagedResultViewer에 flush를 위임하고, 단일/다중 파일 마크다운은 API로 자동 저장 (DB 값 의존 제거). 수동 저장 버튼은 제거.
  - **Markdown Auto-save**:
    - `SimpleEditor`에서 Tiptap `update` 이벤트를 감지, 1.5초 debounce 후 `onChange` 콜백으로 변경된 마크다운을 상위에 전달. `lastMarkdownRef`로 `setContent`에 의한 중복 저장을 방지.
    - `JobResultPage`는 `SimpleEditor`의 `onChange`를 `autoSaveMarkdown(updated)`에 연결. 저장 완료 시 `autoSaveMessage`로 "자동 저장됨"을 표시.
    - `PagedResultViewer`는 현재 페이지의 `SimpleEditor`에 `onChange`를 연결하여 페이지별로 자동 저장. 언마운트/페이지 전환 시 `pendingMarkdownRef`에 남은 변경분을 flush.
    - 파일 선택 전환, MD 다운로드, Office/Excel 변환, 고급 Excel 변환 시작 전에 `autoSaveMarkdown()`으로 pending 변경분을 먼저 서버에 저장.
    - i18n 키: `autoSaved` (ko: "자동 저장됨", en: "Auto-saved", ja: "自動保存しました").
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
3. 서버에서 `COMPOSE_PROJECT_NAME=chungu-app docker compose down && COMPOSE_PROJECT_NAME=chungu-app docker compose up --build -d` 실행 (이미지 빌드 + 컨테이너 재시작). `COMPOSE_PROJECT_NAME=chungu-app` 환경변수는 컨테이너/네트워크 이름 접두사를 고정하므로 생략하면 안 됨.
4. 컨테이너 상태 확인

서버 `.env`는 rsync로 덮어쓰지 않으므로 수동으로 관리해야 한다.
DB 마이그레이션 SQL 파일은 배포 후 서버에서 수동으로 적용한다 (실제 DB 컨테이너명은 `supabase-chungu-db`, DB명은 `postgres`):

```bash
cat app/backend/db/migrations/020_add_pdf_annotate_fields.sql | ssh a1 'docker exec -i supabase-chungu-db psql -U postgres -d postgres'
```

## Storage Retention & Source Cleanup

- OCR 원본 업로드 파일의 Supabase Storage `pdfs` 버킷 보관 기간은 `RETENTION_DAYS = 30` (30일)로 설정되어 있다 (`app/backend/workers/tasks.py`).
- **현재 실제 삭제는 보류 중** — `cleanup_expired_uploads` Celery 태스크가 30일 이상 경과한 job을 조회하되, 아카이빙 스토리지 구성 전까지 로그만 기록하고 Storage 파일을 삭제하지 않는다. Celery beat의 `cleanup-expired-uploads` 스케줄도 주석 처리되어 비활성화 상태 (`app/backend/celery_app.py`).
- 변환 결과 파일(`results` 버킷)은 별도 보관 정책을 유지하며, 원본 삭제와 무관하게 다운로드 가능하다.
- DB의 `jobs` 레코드는 유지되며, 삭제 후 `pdf_storage_path` 및 `extracted_files` 내 `storage_path` 참조만 제거된다.
- 사용자가 수동으로 작업을 삭제하면 DB 레코드 삭제 전에 `pdfs` 버킷 원본 파일도 함께 삭제된다.
- jobs 리스트에는 `source_expires_at`를 기준으로 남은 시간(일/시간/분)이 표시된다.
- Key files:
  - `app/backend/api/jobs.py` — `_source_expires_at()`, `delete_job` Storage 정리
  - `app/backend/core/supabase_client.py` — `delete_source_files()`, `clear_source_paths()`
  - `app/backend/workers/tasks.py` — `cleanup_expired_uploads` 태스크 (현재 삭제 보류)
  - `app/backend/celery_app.py` — Celery beat schedule (`cleanup-expired-uploads` 비활성화, `cleanup-expired-sandboxes` 10분 간격 활성, `grant-monthly-subscription-credits` 1일 간격 활성)
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

## Unified OCR Service (PaddleOCR v5 on a1 CPU)

- **모든 OCR의 단일 진입점은 `paddleocr_service` 컨테이너의 `/api/convert*` 계약이다.** 상위 파이프라인(`core/paddleocr_client.py` → `pipeline_vision` / `pdf_annotate_converter` / `workers/tasks/_helpers` / `job_tasks`)은 어떤 엔진이 도는지 알지 못한다. 엔진 교체는 환경변수 한 줄(`PADDLEOCR_BACKEND`)이며 상위 코드 수정이 없다.
- **백엔드 3종** (`app/backend/paddleocr_service/main.py`의 `OCR_BACKEND`):
  - `local_v5` (**기본/프로덕션**): PP-OCRv5 검출·인식 + PP-StructureV3 레이아웃/표 파싱을 a1 CPU에서 직접 추론. GPU 불필요, 외부 API 비용 0. 구현은 `app/backend/paddleocr_service/ocr_v5.py`.
  - `aistudio`: PaddleOCR AI Studio 유료 API 프록시 (기존 경로, 롤백/폴백용).
  - `local_vl`: PaddleOCR-VL 1.6 + vLLM (GPU 필요 — b2 복구 후).
- **한국어 인식 모델**: PP-OCRv5의 기본 server/mobile rec 모델은 **한국어를 지원하지 않는다** (PaddleOCR discussion #15371). 다국어 계열인 `korean_PP-OCRv5_mobile_rec`을 기본 rec 모델로 쓴다 (`PADDLEOCR_V5_REC_MODEL`). 검출은 `PP-OCRv5_server_det`.
- **한국어를 세 곳 모두에 적용해야 한다 (`PADDLEOCR_V5_PATCH_ALL_RECOGNIZERS`)**: PP-StructureV3 기본 설정에는 `TextRecognition` 모듈이 **세 곳**에 있다 (a1에서 기본 설정을 덤프해 실측):
  | 설정 경로 | 담당 | `text_recognition_model_name` kwarg로 바뀌나? |
  |---|---|---|
  | `SubPipelines.GeneralOCR.SubModules.TextRecognition` | 본문 텍스트 | ✅ 바뀜 |
  | `SubPipelines.TableRecognition.SubPipelines.GeneralOCR.SubModules.TextRecognition` | **표 셀 텍스트** | ❌ 안 바뀜 |
  | `SubPipelines.SealRecognition.SubPipelines.SealOCR.SubModules.TextRecognition` | **도장 안 글자** | ❌ 안 바뀜 |
  즉 kwarg만 쓰면 거래내역 표의 셀과 도장 글자가 한국어 미지원 모델(`PP-OCRv5_server_rec`)로 인식된다 — 한국어 표가 주력인 본 서비스에서는 치명적이다. `ocr_v5._korean_config_path()`가 paddlex 기본 설정 YAML(`paddlex/configs/pipelines/PP-StructureV3.yaml`)을 읽어 **모든 `TextRecognition`의 `model_name`을 재귀적으로 교체**한 파일을 만들고, `PPStructureV3(paddlex_config=...)`로 넘긴다. 키 이름(`TextRecognition`)으로 찾으므로 버전이 올라가 서브파이프라인이 추가돼도 자동으로 함께 교체된다. 기동 로그의 `[ocr-v5] 인식 모델 교체:` 3줄로 확인할 수 있다.
- **oneDNN(MKLDNN)은 반드시 꺼야 한다**: `enable_mkldnn=True`로 PP-StructureV3를 추론하면 paddlepaddle 3.3.1에서 `NotImplementedError: ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]` (onednn_instruction.cc)로 죽는다 (a1 실측). `PADDLEOCR_V5_ENABLE_MKLDNN` 기본값을 `false`로 두었고, 기본값이 다시 켜지지 않도록 단위 테스트로 고정했다. paddle 업그레이드 후 재시도해볼 만한 성능 레버다.
- **CPU 비용 실측 (a1, 1755×1240 한국어 스캔 표 문서 1페이지, pool 4 / 16 threads)** — `benchmark_v5.py`로 측정. 직관과 반대인 결과가 두 개 있으니 튜닝 전에 반드시 읽을 것:

  | 설정 | sec/page | 기준 대비 | 인식 라인 | 본문 한글 | **표 안 한글** | 표 블록 |
  |---|---|---|---|---|---|---|
  | 기준 (server det, rec batch 8) | 130.1 | — | 239 | 346 | 311 | 2 |
  | `rec_batch_size=1` | **113.4** | **−13%** | 239 | 345 | 311 | 2 |
  | `det=PP-OCRv5_mobile_det` | **86.3** | **−34%** | 234 | 345 | 308 | 2 |
  | `table_recognition=false` | 116.7 | −10% | 239 | 35 | **0** | 2 |
  | `seal_recognition=false` | 131.2 | ±0 (노이즈) | 239 | 346 | 311 | 2 |
  | `layout=PP-DocLayout-S` | 119.5 | −8% | 239 | **0** | **0** | **0** |

  - **인식 배치를 키우면 느려진다**: `batch_size=8`이 `1`보다 13% 느렸다(품질은 동일). 텍스트라인 폭이 제각각이라 배치 패딩 낭비가 이득을 넘어선다. `PADDLEOCR_V5_REC_BATCH_SIZE` 기본값은 **1**이며, 단위 테스트로 고정했다.
  - **`PP-DocLayout-S`로 낮추면 결과가 통째로 빈다**: 레이아웃 블록을 0개 검출해 마크다운·표가 전부 사라졌다(OCR 라인은 239개 정상 검출). 속도 이득도 8%뿐이다. `PADDLEOCR_V5_LAYOUT_MODEL`은 **비워두는 것이 기본값**이고, 다른 문서 유형에서 실측하기 전에는 건드리지 말 것.
  - **표 인식은 싸고 필수다**: 끄면 10%만 빨라지는데 표 안 한글이 311자 → 0자가 된다. 거래내역 표가 주력 문서이므로 항상 ON.
  - **도장 인식은 비용이 없다**: 측정 노이즈 범위. 주석 기능이 도장 블록을 대상으로 하므로 ON 유지.
  - **`mobile_det`은 유일하게 큰 속도 레버(−34%)지만 검출 라인이 2% 줄어든다**(239→234). 법률 문서에서 누락은 결함이므로 기본값은 품질 우선 `PP-OCRv5_server_det`으로 두고, 처리량이 급할 때 내리는 escape hatch로 남긴다.
- **좌표 규약 (가장 중요)**: PP-StructureV3는 bbox를 입력 이미지 픽셀 좌표(top-left origin)로 반환한다. AI Studio에 **이미지**를 제출했을 때와 같은 규약이므로 `_extract_layout_from_result()`를 그대로 통과시켜 `core/ocr_layout.py` / `core/pdf_text_layer.py`의 좌표 계산을 건드리지 않는다. 또한 로컬 백엔드는 **PDF도 항상 300DPI 페이지 이미지로 렌더링한 뒤** 추론하므로, AI Studio PDF 직접 제출(PDF user-space, bottom-left origin)과 이미지 경로가 원점이 달랐던 불일치가 사라진다 — 좌표 규약이 하나로 통일된다.
- **반드시 채워야 하는 필드**: `_extract_layout_from_result()`는 `width`/`height`가 없으면 bbox 정규화를 건너뛰고 원본 좌표를 그대로 반환한다(하위 소비자 전부 오작동). PP-StructureV3 `res.json`에는 페이지 크기가 없으므로 `ocr_v5._inject_page_size()`가 이미지 실제 픽셀 크기를 주입하며, 90°/270° 방향 보정이 적용된 페이지는 가로/세로를 교환한다.
- **numpy 직렬화**: `res.json`의 `rec_boxes`/`rec_polys`는 numpy int16 배열이다. `ocr_v5._to_jsonable()`이 순수 파이썬 타입으로 변환하지 않으면 FastAPI 직렬화와 하위 `float()` 변환이 모두 깨진다.
- **문서 방향**: AI Studio 경로와 동일하게 `use_doc_orientation_classify=True`(90° 단위 대회전 보정, 각도 코드를 `page_angles`로 반환) + `use_doc_unwarping=False`(왜곡 보정은 역매핑 불가하므로 항상 강제 off — `ocr_v5._filtered_params()`가 값을 덮어쓴다).
- **자동 파라미터 추천 필터링**: `core/paddleocr_parameter_recommender.py`는 PaddleOCR-VL 전용 키(`use_ocr_for_image_block`, `format_block_content` 등)도 내보낸다. `ocr_v5.PREDICT_PARAM_WHITELIST`로 걸러내지 않으면 `PPStructureV3.predict()`가 TypeError로 죽는다.
- **CPU 병렬화**: PaddleOCR 파이프라인은 thread-safe가 아니므로 인스턴스 풀(`PADDLEOCR_V5_POOL_SIZE`, 기본 4)로 관리하고 한 인스턴스는 한 스레드만 쓴다. `POOL_SIZE × PADDLEOCR_V5_CPU_THREADS ≈ 물리 코어 수`로 맞춘다(a1: 4 × 16). 페이지 단위 실패는 격리되어 빈 결과로 채워지고 전체 작업을 되돌리지 않는다.
- **페이지 상한 해제**: AI Studio는 job당 10페이지가 상한이었다. 로컬 백엔드는 `PADDLEOCR_LOCAL_BATCH_MAX_PAGES`(기본 200)까지 받는다. 앱 쪽 배치 크기는 `OCR_BATCH_SIZE`(`settings.ocr_batch_size`, 기본 10) — `pipeline_vision`의 배치 크기와 PDF 직접 제출 임계값, `pdf_annotate_converter`/`_helpers`의 페이지 게이트가 모두 이 값을 참조한다(이전에는 10이 세 곳에 하드코딩되어 있었다).
- **로컬 실패 시 폴백**: `PADDLEOCR_LOCAL_FALLBACK_TO_AISTUDIO=true`(기본)이고 `PADDLEOCR_API_TOKEN`이 있으면, 로컬 추론 실패 시 같은 task를 AI Studio 경로로 재시도한다. 안정화 후 `false`로 내릴 것.
- **컨테이너**: `app/backend/paddleocr_service/Dockerfile.v5` (python:3.11-slim + `paddlepaddle==3.3.1` CPU + `paddleocr[doc-parser]==3.7.0` + LibreOffice/CJK 폰트). 모델 가중치는 빌드 시 워밍업으로 이미지에 내려받고, 실패 시 런타임에 `paddleocr_v5_models:/root/.paddlex` 볼륨으로 캐시된다. 롤백은 `.env`에 `PADDLEOCR_DOCKERFILE=backend/paddleocr_service/Dockerfile` + `PADDLEOCR_BACKEND=aistudio`.
- **`[doc-parser]` extra는 필수다**: 순수 `paddleocr`만 설치하면 PP-StructureV3 생성이 `RuntimeError: A dependency error occurred during pipeline creation`으로 실패한다 (a1 x86_64에서 실측). 설치가 성공했다고 안심하면 안 되고, 컨테이너 기동 로그에서 `[ocr-v5] PPStructureV3 초기화 완료`를 확인해야 한다.
- **a1에서 실측 검증한 사실** (paddleocr 3.7.0 / paddlepaddle 3.3.1, `docker run --rm python:3.11-slim`):
  - `paddlepaddle==3.3.1` + `paddleocr[doc-parser]==3.7.0` 설치 성공, `PPStructureV3(...)` 생성 성공
  - 모델명 `korean_PP-OCRv5_mobile_rec`, `PP-OCRv5_server_det` 유효 (다국어 rec: arabic/cyrillic/devanagari/el/en/eslav/korean/latin/ta/te/th)
  - 생성자는 `device` / `cpu_threads` / `enable_mkldnn`을 `**kwargs`로 수용하고, **미지원 키는 `ValueError: Unknown argument: X`로 거부**한다 (TypeError가 아니다 — `_build_pipeline`이 두 예외를 모두 잡는 이유)
  - `PPStructureV3.predict()`에는 `use_layout_detection`이 **없고** `format_block_content`는 **있다** — PaddleOCR-VL 기준으로 짐작하면 틀린다
- **미검증 / 후속 확인 필요**:
  1. **한국어 표 인식 품질**: 생성 로그를 보면 표 인식 서브파이프라인이 한국어를 지원하지 않는 `PP-OCRv5_server_rec`도 함께 올린다. 한국어 표가 많은 실제 문서로 셀 텍스트 품질을 확인해야 하며, 열화가 확인되면 `PADDLEOCR_V5_TABLE_RECOGNITION=false`(표는 레이아웃 블록 HTML로만 처리)가 escape hatch다.
  2. **CPU 처리 시간/페이지**: 실문서 벤치마크 미측정. a1은 495GB RAM / 80스레드에 여유가 크므로(측정 시 load ~3) `PADDLEOCR_V5_POOL_SIZE`를 4보다 올릴 여지가 있다.
  3. **주석/searchable PDF 좌표 정합**: 단위·통합 테스트로 정규화 규약은 고정했으나, 실제 스캔 PDF의 하이라이트 위치는 develop(28190)에서 눈으로 확인해야 한다.
- **`/health`가 백엔드를 노출한다**: `{"status":"ok","backend":"local_v5","rec_model":"korean_PP-OCRv5_mobile_rec"}` — 배포 후 어떤 엔진이 도는지 확인하는 1차 수단.
- **컨테이너 전이 의존성 주의**: `paddleocr_parameter_recommender` → `ocr_client` → `{llm_utils, markdown_sanitizer}`. 기존 `Dockerfile`은 뒤의 두 파일을 복사하지 않아 자동 파라미터 추천이 ImportError로 조용히 죽고 있었다. `Dockerfile.v5`는 전이 의존까지 모두 복사한다.
- **추천기 LLM 엔드포인트**: `local_v5`에는 vLLM 컨테이너가 없으므로 `VLLM_SERVER_URL`을 그대로 쓰면 문서마다 없는 호스트로 붙었다가 타임아웃한다. `PADDLEOCR_RECOMMENDER_ENDPOINT`(비우면 `DEFAULT_LLM_ENDPOINT`)를 사용한다.
- **벤치마크 / 품질 A-B 도구**: `app/backend/paddleocr_service/benchmark_v5.py`. `--compare-korean-patch`로 표/도장 인식기 한국어 교체 ON/OFF를 비교하고(표 안 한글 음절 수를 지표로 사용), `--pool-sizes 1,2,4,8`로 pool size별 처리량(pages/min)을 측정한다. 컨테이너 안에서 샘플 디렉터리를 마운트해 실행한다.
- **테스트**: `app/backend/tests/test_ocr_v5_adapter.py`(어댑터 단위 33개 — 직렬화/회전/페이지 크기/마크다운 인라인/파라미터 화이트리스트/좌표 정규화), `app/backend/tests/test_paddleocr_service_backend_dispatch.py`(엔드포인트 디스패치 통합 9개 — 세 엔드포인트 라우팅, 페이지 상한 해제, 폴백 차단 시 error 전이).
- Key files:
  - `app/backend/paddleocr_service/ocr_v5.py` — PP-StructureV3 파이프라인 풀, `predict_page`/`predict_pages`, 결과 정규화
  - `app/backend/paddleocr_service/main.py` — `OCR_BACKEND` 디스패치, `_do_local_v5_*` 워커, `/health`
  - `app/backend/paddleocr_service/Dockerfile.v5`, `requirements.v5.txt`
  - `app/docker-compose.yml` — `paddleocr_service`(v5 이미지 + 모델 볼륨 + healthcheck)

## PaddleOCR AI Studio API (백업 백엔드)

- PaddleOCR AI Studio API (`https://paddleocr.aistudio-app.com/api/v2/ocr/jobs`)를 백업 OCR 백엔드로 사용한다 (`PADDLEOCR_BACKEND=aistudio`, 또는 로컬 실패 시 자동 폴백).
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

- **기능 개요**: 원본 PDF/이미지에서 자연어 조건(예: "80만원 이상 이체된 줄", "사람 이름이 있는 부분")에 맞는 텍스트 요소를 찾아 **형광펜 하이라이트**와/또는 **여백 코멘트 주석**을 추가해 다운로드할 수 있는 기능. 변호사 등 법률 실무에서 스캔 문서를 그대로 제출용으로 표시해야 하는 요구에서 시작됨.
- **주석 대상**: 표의 행(table_row)뿐 아니라 제목/단락/각주/도장 내 글자 등 모든 텍스트 블록(text)이 주석 대상이 된다. PaddleOCR-VL의 `parsing_res_list`에서 `block_label`이 `table`인 블록은 행 단위로, 그 외 텍스트가 포함된 블록(`text`/`title`/`figure_title`/`seal` 등)은 블록 전체를 하나의 요소로 취급한다. `image`/`figure` 등 텍스트가 없는 블록은 제외.
- **이미지 파일 지원**: 원본 PDF가 없는 경우(zip 속 이미지 파일 등), 이미지들을 PyMuPDF로 PDF로 변환한 후 주석을 적용한다. `_images_to_pdf()`가 각 이미지를 RENDER_DPI 기준 포인트 크기의 페이지로 삽입해 단일 PDF를 생성한다. 이미지 파일은 주석 생성 직전에 `pdfs` 버킷에 개별 업로드되어야 하며, `supabase_client.upload_image()`가 담당한다.
- **이미지 전처리 (보정)**: OCR bbox와 주석 PDF의 좌표를 정확히 맞추기 위해 이미지 페이지를 보정한다.
  1. `image_deskew.deskew_image()`로 미세 기울기(수평에서 몇 도 벗어난 스캔/사진)를 보정한다. `deskew>=1.5.0` 패키지를 사용하며, |각도| < 0.5°면 보정을 생략한다.
  2. PaddleOCR-VL(AI Studio)의 `doc_preprocessor_res.angle` 코드(0/1/2/3)를 기반으로 90°/180°/270° 단위 대회전을 `_rotate_image_90()`로 적용한다. AI Studio의 `useDocOrientationClassify` 결과를 클라이언트 측에서 재현하는 것이다.
  3. 보정이 완료된 이미지를 기준으로 bbox를 수집하고, 동일한 보정 이미지로 주석 PDF를 생성한다. 원본 PDF 벡터 정보는 포기하고 시각적 정확도를 우선한다.
- **처리 흐름**:
  1. `_get_page_image_paths()`로 원본 PDF/이미지에서 페이지 이미지 확보 (PDF는 DPI 200 재렌더링, 이미지는 `pdfs` 버킷에서 다운로드)
  2. `deskew_image()` + `_rotate_image_90()`로 페이지 이미지 보정
  3. PaddleOCR-VL(AI Studio 유료 API, 현재 사용 중)로 페이지별 bbox 원본(layout) 확보
  4. 모든 텍스트 요소(표 행 + 텍스트 블록)를 텍스트로만 LLM(vLLM Gemma-4)에 전달해 조건에 맞는 요소 선택 (좌표 추론은 LLM에 절대 맡기지 않음 — grounding 신뢰도가 낮다는 리서치 결과 반영)
  5. 선택된 요소의 bbox를 PDF 좌표로 변환
  6. 깨끗한 보정 이미지 PDF를 Storage에 업로드 (주석을 PDF에 구워 넣지 않음)
  7. `build_embedpdf_annotations()`로 EmbedPDF `AnnotationTransferItem[]` JSON 생성 후 Storage에 업로드
  8. 프론트 `PdfViewer`가 JSON을 `importAnnotations()`로 오버레이; flatten 다운로드는 embedpdf snippet 자체 다운로드 UI가 처리
- **사용자 인터페이스**: 결과 페이지(JobResultPage)의 "AI 주석" 버튼 → 지시문 입력(예: "출금금액이 1000만원 이상인 거래 행", "사람 이름이 있는 부분") + 표시방식(`highlight`/`margin_note`/`both`) + 여백 코멘트 방식(`user_text`/`llm_summary`) 선택 → Celery 비동기 처리 (xlsx_advanced와 동일한 구독 사용량 예약/재시도 패턴)
- **PaddleOCR-VL 1.6 실제 원본 스키마** (a1 프로덕션에서 실측, 사전 조사했던 PP-StructureV3 계열 `table_res_list`/`cell_box_list` 스키마와는 다름에 주의):
  - `{"width": px, "height": px, "layout_det_res": {...}, "parsing_res_list": [{"block_label": "table"|"text"|"title"|"seal"|..., "block_content": "<table>...</table>" (표는 HTML 문자열), "block_bbox": [xmin,ymin,xmax,ymax], ...}]}`
  - 표는 **블록 전체 bbox만 있고 행/셀 단위 bbox가 없다** — `core/ocr_layout.py`가 `block_content`의 HTML을 `lxml`로 파싱하고, `block_bbox`를 `<tr>` 개수만큼 세로로 균등 분할해 각 행의 근사 bbox를 만든다.
  - 텍스트 블록은 `block_bbox`를 그대로 사용한다 (블록 전체가 하나의 주석 대상).
  - AI Studio API(`layoutParsingResults[].prunedResult`)와 로컬 PaddleOCR-VL 파이프라인(`res.json`)은 `input_path`/`page_index` 차이만 있고 스키마가 동일하므로, 로컬 서버로 전환해도 `core/ocr_layout.py`는 수정할 필요가 없다 — `core/paddleocr_client.py`의 `convert_image_with_layout()` 내부 호출 엔드포인트만 교체하면 됨.
- **PDF 좌표 변환 시 주의 (실측으로 발견한 함정들)**:
  - `use_doc_orientation_classify`/`use_doc_unwarping`이 켜지면 bbox가 "보정된 이미지" 기준으로 나와 원본 좌표와 어긋난다 — AI Studio 잡 제출 시(`_aistudio_submit_job`) 항상 `False`로 고정 전송.
  - `/Rotate 90/180/270`이 걸린 PDF는 OCR bbox(시각적/렌더링 좌표)와 PyMuPDF 주석 API가 기대하는 좌표계가 다르다 — `page.derotation_matrix`로 변환 필요.
  - PyMuPDF의 주석/텍스트 삽입 좌표는 **PDF 절대좌표가 아니라 "현재 mediabox의 좌상단(x0,y0)을 원점으로 하는 로컬 좌표"**다. PaddleOCR-VL 1.6의 원점도 좌상단이며, **우측/하단 여백을 늘리면 x0/y0가 이동하지 않아 보정이 불필요**하다. 좌측/상단 여백을 늘리면 x0/y0가 이동해 기존 좌표가 어긋나므로, 본 기능은 우측/하단 여백만 추가한다. 기본적으로는 우측에만 여백을 추가하고, 주석 박스가 페이지 하단을 넘어 겹칠 경우에만 하단을 필요한 만큼 늘린다 (원점 이동 보정 로직은 제거됨).
  - **mediabox 원점 보존 (실측으로 발견한 함정)**: `page.rect`는 PyMuPDF가 **y0를 항상 0으로 정규화**한 시각적 사각형이다. 원본 mediabox가 `(0, 50, 400, 350)`처럼 y0≠0인 페이지에서 `page.rect` 기반으로 새 mediabox를 계산하면 y0가 0으로 덮어씌워져 **페이지 콘텐츠 전체가 위로 밀려 잘못된 위쪽 여백**이 생긴다. 따라서 여백 확장은 `page.rect`가 아닌 **원본 `page.mediabox`를 직접 확장**해야 한다 (`_extend_mediabox_for_visual_margins()`). 회전된 페이지(90/180/270)에서는 시각적 우측/하단이 raw mediabox의 어느 변에 해당하는지 회전 각도에 따라 계산한다.
  - 텍스트 레이어 없는 스캔본에서 `add_highlight_annot()`에 raw bbox를 넣으면 MuPDF가 사각형이 아닌 타원형 브러시로 그린다 — `add_rect_annot()`(Square 주석) + 반투명 채우기로 대체.
  - 여백은 **기본적으로 우측에만** 추가한다. 주석 박스가 많아져 페이지 하단을 넘어 겹치게 되면, 하단도 필요한 만큼 늘린다. PaddleOCR-VL / PDF 시각 좌표계의 원점이 좌상단이므로 우측/하단 확장은 원점을 이동시키지 않는다. 좌측/상단 여백은 건드리지 않는다.
- 여백 코멘트 박스는 서로 겹치지 않도록 세로 위치를 순서대로 밀어내며 배치하고(`_layout_margin_notes`), 원래 요소 위치와 배치된 박스 위치가 달라지면 꺾이는 연결선(callout)으로 이어준다. **박스 높이는 텍스트 양에 따라 가변** (`_estimate_note_height`): 폰트 8pt 기준 약 22문자/줄로 줄 수를 추정해 높이를 계산, 최소 11pt(약 1줄)~최대 120pt(약 10줄) 범위에서 조절된다.
- LLM 요소 선택 프롬프트(`build_element_highlight_prompt`)는 표 행과 텍스트 블록이 혼합된 요소 목록에서 조건에 맞는 요소를 선택한다. 표 행은 헤더 컬럼명을 정확히 매칭하도록 명시하고, 텍스트 블록은 특정 단어/이름/날짜 포함 여부로 판단한다. 완전한 정확도는 보장되지 않으므로 결과 검토가 필요하다. 텍스트 블록은 앞 200자만 LLM에 전달해 토큰 폭증을 방지한다. **주석 코멘트는 사용자가 instruction에 사용한 언어로 작성**된다 — 프롬프트에서 "write the comment in the SAME language as the user's condition text"로 지시하여, 앱 지원 언어(ko/en/ja) 외의 언어(예: 불어, 스페인어)로 조건을 입력한 사용자도 자신의 언어로 주석을 받을 수 있다. 프롬프트 자체는 모두 영어로 작성되어 있다.
- **EmbedPDF AnnotationTransferItem[] 주석 (단일 진실원)**: 백엔드는 주석을 PDF에 구워 넣지 않고, 깨끗한 보정 이미지 PDF + EmbedPDF `importAnnotations()`가 기대하는 `AnnotationTransferItem[]` JSON만 저장한다. JSON이 있으면 프론트 `PdfViewer`가 초기 로드 시 `importAnnotations()`로 주석을 복원하고, 사용자는 뷰어 내에서 주석을 추가/편집/삭제할 수 있다. flatten 다운로드(주석이 포함된 PDF)는 embedpdf snippet 자체의 다운로드 UI가 `saveAsCopy()`로 처리한다. JSON 좌표는 PDF user-space(원점 좌하단, y↑)에서 embedpdf device-space(원점 좌상단, y↓)로 y축 flip한 포인트 좌표를 사용하며 (`origin.y = page_height - y1`), `PdfAnnotationSubtype`은 숫자 enum 값(`HIGHLIGHT=9`, `FREETEXT=3`)으로 기록한다.
- **사용자 주석 편집/저장**: 프론트에서 편집이 발생하면 "주석 저장" 버튼이 활성화된다. `SourcePanel`이 `exportAnnotations()`로 현재 JSON을 받아 `POST /api/jobs/{id}/user-annotations`로 전송하면, 백엔드는 `pdf_user_annotator.py`로 PyMuPDF 주석을 다시 렌더링하여 주석 PDF를 덮어쓰고, JSON 파일도 함께 갱신한다. Storage 경로는 `annotated_pdf_files[].annotations_json_storage_path`에 기록된다. `annotated_pdf_files` JSONB 배열의 각 객체는 이제 `storage_path`, `filename`, `annotations_json_storage_path`를 포함할 수 있다.
- **DB 필드**: `Job.annotate_instruction/annotate_mode/annotate_comment_mode/annotate_status/annotate_job_id/annotate_recovery_notes/annotate_refundable/annotate_reserved_pages/annotate_reserved_period_start`, `result_ocr_layout_storage_path`, `result_annotated_pdf_storage_path` (`020_add_pdf_annotate_fields.sql`). `annotate_job_id`/`result_xlsx_advanced_job_id`는 VARCHAR(64) (`021_widen_job_id_columns.sql`). 주석 결과 파일 목록은 `annotated_pdf_files` JSONB (`022_add_annotated_pdf_files.sql`). 고급주석(Vision LLM) 여부는 `annotate_advanced` BOOLEAN (`023_add_annotate_advanced.sql`).
- Key files:
  - `app/backend/core/ocr_layout.py` — PaddleOCR-VL `parsing_res_list` → `PageLayout`/`OcrTable`/`OcrRow`/`OcrTextBlock` 정규화 (HTML 표 파싱 + 행 bbox 균등분할 추정, 텍스트 블록 추출)
  - `app/backend/core/pdf_coords.py` — 픽셀 bbox ↔ PDF 포인트 변환, 페이지 경계 clamp
  - `app/backend/core/pdf_annotator.py` — `AnnotationTarget` 기반 하이라이트/여백 주석 렌더링 (회전 보정, 원본 mediabox 직접 확장으로 원점 이동 방지, 텍스트 양에 따른 가변 박스 높이, 겹침 방지 배치). `build_embedpdf_annotations()`로 EmbedPDF `AnnotationTransferItem[]` 형식 변환 (PDF user-space → device-space y축 flip). `annotate_pdf()`는 테스트용으로만 사용 (프로덕션은 JSON 오버레이 방식).
  - `app/backend/core/pdf_annotate_converter.py` — 오케스트레이터 (`run()`): 페이지 이미지 확보 → 보정(deskew + 90° 회전) → OCR bbox 확보 → 요소 수집(표 행+텍스트 블록) → LLM 요소 선택 → 좌표 변환 → 깨끗한 보정 이미지 PDF 업로드 + `.annotations.json` 업로드 (주석을 PDF에 구워 넣지 않음). `_images_to_pdf()`로 이미지→PDF 변환 지원.
  - `app/backend/core/pdf_user_annotator.py` — 사용자/백엔드 생성 JSON을 PyMuPDF로 렌더링 (highlight/underline/strikeout/free-text/rectangle/circle/line/arrow/ink 지원). `apply_user_annotations(pdf_bytes, annotations)`로 새 PDF 생성.
  - `app/backend/core/image_deskew.py` — 이미지 미세 기울기 보정 (`deskew` 라이브러리). 0.5° 미만은 생략, 흰색 배경으로 채움.
  - `app/backend/core/prompts.py` — `build_element_highlight_prompt()` (표 행+텍스트 블록 혼합, 사용자 조건 문구 언어로 코멘트 작성 지시), `build_row_highlight_prompt()` (레거시, 표 전용). 모든 프롬프트는 영어로 작성.
  - `app/backend/core/paddleocr_client.py` — `convert_image_with_layout()` (bbox 포함 변환, angle_code 반환), `_convert_and_poll()` 공통 폴링
  - `app/backend/paddleocr_service/main.py` — `_extract_layout_from_result()`, `ConvertResponse.layout` 필드, AI Studio `prunedResult` 전달
  - `app/backend/core/supabase_client.py` — `upload_image()` (원본 이미지를 `pdfs` 버킷에 개별 업로드). `_get_page_image_paths()`가 이 경로를 다운로드할 수 있도록 동일 버킷을 사용해야 한다.
  - `app/backend/workers/tasks.py` — `annotate_pdf_job` Celery task; 이미지 파일 처리 후 `extracted_files[i].storage_path`를 `upload_image()`로 설정
  - `app/backend/api/jobs.py` — `POST /jobs/{id}/annotate`, `POST /jobs/{id}/annotate-action` (xlsx_advanced와 동일 패턴), `POST /jobs/{id}/user-annotations` (사용자 주석 저장). preview/삭제 시 JSON 파일 동시 처리.
  - `app/frontend/src/components/PdfViewer.jsx` — `@embedpdf/react-pdf-viewer`의 `PDFViewer` 래퍼. `forwardRef`로 `exportAnnotations()` 노출, `importAnnotations()`로 초기 주석 로드, `onAnnotationChanged` 이벤트 상위 전달.
  - `app/frontend/src/components/SourcePanel.jsx` — `annotations_json_url` fetch, "주석 저장" 버튼, `onSaveAnnotations` 콜백.
  - `app/frontend/src/components/PagedResultViewer.jsx` — `SourcePanel`에 `onSaveAnnotations` 전달.
  - `app/frontend/src/pages/JobResultPage.jsx` — 하이라이트/주석 생성 버튼 + 모달 + 상태 폴링. `saveUserAnnotations()` API 호출.
  - `app/frontend/src/api.js` — `annotateJob()`, `annotateAction()`, `saveUserAnnotations()`.
  - `app/frontend/src/locales/{ko,en,ja}/page.json` — `saveAnnotations` i18n 키.

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

- **Status**: b2 GPU server (RTX 3080 / 2080 Ti) is still down and will not be repaired soon. All GPU OCR backend work stays suspended. b1(192.168.1.69, LLM)과 b3(192.168.1.49)도 함께 내려가 있어, 현재 살아 있는 노드는 a1(80 스레드 Xeon, GPU 없음)과 a2뿐이다.
- **PaddleOCR-VL 1.6**: dual-container architecture (vLLM + PaddleOCR Pipeline) was in progress on b2. Files remain in `app/backend/paddleocr_service/` (`Dockerfile.pipeline`, `Dockerfile.vllm`, `PADDLEOCR_BACKEND=local_vl`) and `app/docker-compose.paddleocr.yml` for resumption after repair.
- **Nemotron-OCR-v2**: Docker-based evaluation was attempted but could not complete due to the b2 outage. The model is Turing/CC-7.5 unsupported by NVIDIA's official docs; evaluation will resume on a compatible GPU if available.
- **현재 프로덕션 OCR**: GPU를 기다리지 않고 **a1 CPU에서 PaddleOCR v5(PP-OCRv5 + PP-StructureV3)** 로 전환했다 — 위 "Unified OCR Service (PaddleOCR v5 on a1 CPU)" 절 참조.

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

- **기능 개요**: 구독 기반 사용량 관리 — 통합 크레딧(`points_balance`) 잔액 기반 과금, 월간 크레딧 지급, 예약/차감/환불. 페이지/오디오/비디오/AI 에이전트 스텝이 모두 포인트에서 차감됨.
- **플랜별 월간 크레딧** (`PLAN_MONTHLY_CREDITS` in `subscription_service.py`):
  - `free`: 1,000pt
  - `pro`: 30,000pt
  - `max`: 100,000pt
- **크레딧 비율** (`points_service.py`): 기본 모델 페이지 1pt, 프리미엄 모델 페이지 5pt, 오디오 1pt/초, 비디오 10pt/초, Docling 후처리 페이지 3pt, AI 에이전트 스텝 1pt/스텝.
- **기간 계산**: 사용자의 `subscription_period_start` 기준 월간 기간, 없으면 달력월 시작일 사용. `grant_monthly_credits()`가 Celery beat 태스크로 월간 크레딧을 지급 (중복 지급 방지용 `subscription_credits_granted_at` 컬럼 사용).
- **사용량 관리** (`points_balance` 기반):
  - `check_enough()`: 잔액 충분 여부 확인
  - `reserve_usage()`: 작업 시작 전 포인트 예약
  - `release_usage()`: 작업 실패 시 예약된 포인트 환불
- **구독 상태**: `is_subscription_active()`로 활성 여부 확인
- **레거시 컬럼 참고**: `subscription_usages` 테이블의 `basic_pages`/`premium_pages`/`media_seconds`와 `jobs` 테이블의 `reserved_*` 컬럼은 마이그레이션 036 이전 개별 한도 방식의 잔재로 DB에 남아 있으나, 현재는 통계/사용량 계산 보조용이며 실제 한도 체크는 `points_balance`로만 이루어짐.
- **Key files**: `app/backend/core/subscription_service.py`, `app/backend/core/points_service.py`, `app/backend/db/migrations/036_credit_system_subscription.sql`

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
  - `JobResultPage.jsx`: Single download icon button (`FileDown`) with a hover menu containing Excel Basic, Excel Advanced, Word, and Markdown. The previous separate Excel and Office buttons were merged. Preview tabs for Markdown / Excel Basic / Excel Advanced use `SpreadsheetEditor.jsx` (Luckysheet-based xlsx editor).
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
- `/api/jobs/{id}/preview` returns `source_files` (name, type, url, storage_path, page_num, result_markdown, source_index, source_kind) for each original file. PDF 원본은 signed URL로 브라우저 네이티브 뷰어에 표시된다.
- **원본 파일 삭제**: 결과 페이지의 `SourcePanel` 파일 목록 각 항목에 휴지통 아이콘을 표시한다. 클릭 시 확인 모달을 띄우고, 확인하면 `DELETE /api/jobs/{id}/source-files/{source_kind}/{source_index}`를 호출한다.
  - `source_kind`는 `original` (원본 파일) 또는 `annotation` (주석 PDF)이다.
  - 백엔드는 Supabase Storage에서 실제 파일을 삭제하고, DB의 `extracted_files` 또는 `annotated_pdf_files`에서도 항목을 제거한다.
  - 단일 PDF/DOCX/HWP 업로드의 경우 `pdf_storage_path`를 직접 삭제한다.
  - 이미 생성된 변환 결과물(마크다운, XLSX, DOCX 등)은 재생성하지 않고 그대로 유지한다.
  - i18n 키: `page:result.deleteSourceFileTitle`, `page:result.deleteSourceFileDesc` (ko/en/ja).
  - Key files: `app/backend/api/jobs.py` (`delete_source_file`, `_delete_original_file`, `_delete_annotation_file`), `app/frontend/src/components/SourcePanel.jsx`, `app/frontend/src/pages/JobResultPage.jsx`.
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

- **과금 모델**: UI 사용자(웹 앱)와 API 사용자 모두 동일한 통합 크레딧 시스템(`points_balance`)을 사용. 페이지/오디오/비디오/AI 에이전트 스텝이 포인트에서 차감됨. 이전 개별 한도 방식(basic_pages/premium_pages/media_seconds)은 마이그레이션 036으로 폐지됨.
- **Plans** (월간 지급 크레딧, `PLAN_MONTHLY_CREDITS`):
  - Free: 1,000pt/month
  - Pro: $20/month or $200/year — 30,000pt/month
  - Max: $100/month or $1,000/year — 100,000pt/month
- **크레딧 비율**: 기본 모델 페이지 1pt, 프리미엄 모델 페이지 5pt, 오디오 1pt/초, 비디오 10pt/초, Docling 후처리 페이지 3pt, AI 에이전트 스텝 1pt/스텝. (상세 비용 계산은 `app/backend/core/points_service.py`)
- **Key files**:
  - `app/backend/core/subscription_service.py` — `PLAN_MONTHLY_CREDITS` 정의, 월간 크레딧 지급 및 포인트 기반 예약/환불.
  - `app/backend/core/points_service.py` — 리소스별 포인트 비용 계산.
  - `app/backend/api/subscriptions.py` — public plan listing, checkout, and cancel endpoints.
  - `app/backend/api/payments.py` — Paddle webhook handling for `subscription.*` events.
  - `app/backend/db/migrations/036_credit_system_subscription.sql` — 통합 크레딧 시스템 전환 마이그레이션.
  - `app/frontend/src/pages/PlansPage.jsx` / `app/frontend/src/pages/PricePage.jsx` — subscription plan UI (월간 크레딧 표시).
  - `app/frontend/src/components/PlanCard.jsx` — 플랜 카드 (크레딧 기준 예상 사용 가이드 포함).
  - `scripts/create_paddle_subscription_catalog.py` — automated Paddle product/price creation.
- **Paddle API key**: store in `app/.env` as `PADDLE_API_KEY`. It is seeded into `app_settings` via `settings_store.py` and `config.py`.
- **Creating catalog**: run `PADDLE_API_KEY=... DATABASE_URL=... python scripts/create_paddle_subscription_catalog.py`. This creates products and monthly/yearly prices for Free/Pro/Max and saves the resulting `price_id`s into `app_settings`.
- **Webhooks**: Paddle dashboard must send `subscription.created`, `subscription.updated`, `subscription.canceled`, and `transaction.completed` to `https://proof.teamcat.app/api/payments/paddle/webhook`.
- **Free $0 note**: if Paddle does not allow a $0 recurring checkout, the Free tier can stay internal-only (no Paddle subscription) and only Pro/Max use Paddle checkout. The backend treats `subscription_plan == "free"` as always active.

## Frontend Dropdown Hover UX

- CSS-only `group-hover` dropdowns (e.g. the download icon button in `JobResultPage.jsx`) can disappear when the cursor crosses the small gap between the trigger button and the dropdown panel.
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
- **프론트엔드 처리**:
  - `app/frontend/src/pages/JobResultPage.jsx`의 `startAnnotate(instruction)` 함수가 API를 호출하고, 에러 메시지에 "구독이 필요" 또는 "subscription"이 포함되면 2초 후 price 페이지로 자동 이동합니다.
  - `app/frontend/src/components/SourcePanel.jsx`의 `AiAnnotationFab` 컴포넌트가 PDF 소스 패널 하단 중앙에 작은 FAB으로 표시됩니다. 클릭하면 `scale`/`opacity`/`translate` 트랜지션으로 입력 카드 팝업이 부드럽게 펼쳐지며, instruction을 입력하고 생성할 수 있습니다.
  - i18n 키 `page:errors.subscriptionRequired` 사용 (ko/en/ja 모두 추가)
- **주석 생성 비용**: 포인트(`annotate_cost_points`)로 차감됩니다. 관리자는 차감되지 않습니다.
- **재시도 액션** (`annotate_action` 엔드포인트): 주석 생성이 `error` 상태로 실패한 경우 사용자가 재시도(retry)할 수 있습니다. 구독제이므로 환불(refund) 기능은 제공하지 않습니다. 비회원 사용자는 이 액션 엔드포인트에서도 402 에러를 받습니다.
- **결과 파일 노출**: 주석 생성이 완료되면 `JobResultPage.jsx`의 파일 탭에 `<원본파일명>_annotation1.pdf`, `_annotation2.pdf` … 형식으로 누적 추가됩니다. 별도의 ‘주석 PDF 다운로드’ 버튼은 생성되지 않으며, AI 주석 FAB은 PDF 패널 하단에 계속 떠 있는 작은 트리거로 유지됩니다.
- **결과 저장**: `app/backend/core/pdf_annotate_converter.py`는 각 주석을 `results/{job_id}/annotated_{N}.pdf`로 저장하고, `Job.annotated_pdf_files` JSONB 목록에 `storage_path`, `filename`, `instruction`, `mode`, `comment_mode`, `created_at`을 기록합니다. 동일한 `(instruction, mode, comment_mode)`로 재요청하면 기존 파일을 반환합니다.

## Frontend Variable Naming Conventions

- **JobResultPage.jsx**: XLSX 변환 비용 표시 시 `xlsxBasicCost`/`xlsxAdvancedCost` 대신 `xlsxBasicUnits`/`xlsxAdvancedUnits`를 사용해야 합니다.
- 이 두 변수는 이미 409-410번 라인에서 정의되어 있으며: `job.total_pages || job.total_files || 1` 값으로 계산됩니다.
- 구독제에서는 실제 달러 비용이 아니라 구독 월간 페이지 한도를 차감하므로 "units"라는 명칭이 더 정확합니다.
- i18n 키 `page:result.xlsxBasic`과 `page:result.xlsxAdvanced`는 `cost` 파라미터를 받아 표시합니다.

## Backend 테스트 실행 참고

- `backend` 폴더에서 `pytest`를 실행할 때 `core` 패키지와 `backend` 패키지가 모두 정상적으로 임포트되도록 하려면 작업 디렉터리를 `app/backend`로 설정하고 `PYTHONPATH`에 `app`의 상위 디렉터리(`app`)를 추가해야 한다.
  - 예: `cd /path/to/repo/app/backend && PYTHONPATH=/path/to/repo/app python -m pytest tests/`
  - `PYTHONPATH=/app`를 지정하면 `backend.*` 모듈 임포트가 가능하고, 현재 디렉터리 `app/backend`가 `sys.path`에 포함되어 `core.*` 직접 임포트도 가능하다.
- 프론트엔드: `cd app/frontend && npm run test` / `npm run build`

## Searchable PDF 우선순위 — 텍스트 레이어가 있는 원본 PDF 사용

- `app/backend/workers/tasks.py`에서 `_build_and_upload_searchable_pdf`보다 `_register_searchable_pdf_if_text_layer`를 먼저 호출해야 합니다.
- `_build_and_upload_searchable_pdf` 내부 맨 앞에 `if job.searchable_pdf_storage_path: return` guard를 추가해, 이미 원본이 등록된 경우 OCR 재생성으로 덮어쓰지 않습니다.
- 이렇게 하면 텍스트 레이어가 있는 PDF는 PaddleOCR 재변환 없이 원본의 정확한 텍스트 좌표를 그대로 사용하므로, 에이전트 하이라이트 y축 반전/오차가 해결됩니다.
- `_insert_invisible_text`의 `baseline_y = y0 + font_size` 계산은 실제로 투명 텍스트 검색 bbox가 원래 bbox 안에 들어오므로 수정하지 않습니다.
- 회귀 테스트: `tests/test_tasks_searchable_pdf_priority.py`, `tests/test_pdf_text_layer_baseline.py`

## OCR Layout PDF user-space 감지

- `app/backend/paddleocr_service/main.py`의 `_extract_layout_from_result`는 AI Studio에 원본 PDF를 직접 제출했을 때 반환 bbox가 PDF user-space(y↑)일 수 있으므로 동적으로 감지한다.
- `page_height_px`가 `page_height_pt`와 비슷하고(0.8~1.2배), 상단 블록 샘플의 y 평균이 페이지 상반부에 있으면 PDF user-space로 판단해 y축을 뒤집는다.
- `_normalize_bbox` / `_normalize_points`는 `flip_y` 플래그로 top-left normalized(y=0 상단)를 생성한다.
- 이렇게 하면 OCR로 생성된 searchable PDF 텍스트 레이어 좌표가 원문과 상하 반전되는 문제를 방어할 수 있다.
- 회귀 테스트: `tests/test_paddleocr_layout_pdf_user_space.py`

## OCR searchable PDF y-flip canary 검증 + 좌표계 변환 일원화

- `app/backend/core/pdf_text_layer.py`의 `add_text_layer_from_ocr`는 파일당 1개 canary 페이지로 y-flip을 검증한다.
  - 원본 PDF에서 canary 텍스트를 `page.search_for`로 찾아 ground truth bbox를 확보한다.
  - OCR bbox를 PDF user-space로 변환한 표준/반전 두 rect 중 ground truth와 IoU가 더 높은 쪽을 선택해 파일 전체에 적용한다.
  - `force_flip_y` 파라미터로 외부에서 강제할 수도 있다.
- `app/backend/core/pdf_coordinate_transform.py`를 신설해 모든 y-flip/스케일 변환을 `fitz.Matrix`로 한 곳에서 처리한다.
  - `normalized_top_left_to_pdf_user`, `image_top_left_to_pdf_user`, `pdf_user_to_device`, `device_to_pdf_user`, `embedpdf_rect_from_pdf_user`, `pdf_user_rect_from_embedpdf` 등을 제공한다.
- `pdf_text_layer.py`, `pdf_coords.py`, `pdf_annotator.py`, `pdf_user_annotator.py`의 산발적 `1 - y` 계산을 `pdf_coordinate_transform` 함수로 대체한다.
- 회귀 테스트: `tests/test_pdf_text_layer_canary.py`, `tests/test_pdf_coordinate_transform.py`, `tests/test_coord_transform.py`
