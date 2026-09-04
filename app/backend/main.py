#!/usr/bin/env python3
# [Flow: Step 1 (DB 테이블 생성) -> Step 2 (관리자/설정 시드) -> Step 3 (라우터 등록) -> Step 4 (정적 프론트 서빙)]
import re
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import Response
from sqlalchemy import select, text

from . import settings_store
from .api import admin, auth, jobs, on_premise, payments, subscriptions
from .api.chat_conversations import router as chat_conversations_router
from .api.dev_auth import router as dev_auth_router
from .api.ediscovery import router as ediscovery_router
from .api.flow_drawings import router as flow_drawings_router
from .api.gdpr import router as gdpr_router
from .api.sandboxes import router as sandboxes_router
from .api.supabase_proxy import router as supabase_proxy_router
from .api.v1 import router as v1_router
from .auth.security import hash_password
from .config import settings
from .db.models import AdminUser
from .db.session import Base, SessionLocal, engine

STATIC_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def _make_idempotent(stmt: str) -> str:
    """[Flow: Step 1 (CREATE TABLE/INDEX 및 ALTER TABLE ADD COLUMN 문 감지) -> Step 2 (IF NOT EXISTS 추가) -> Step 3 (변환된 SQL 반환)]

    마이그레이션 SQL을 idempotent하게 변환하여 이미 적용된 스키마 변경에서 실패하지 않도록 한다.
    """
    # CREATE TABLE ... -> CREATE TABLE IF NOT EXISTS ...
    stmt = re.sub(r"CREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS\s+)(?!\s*IF\s+NOT\s+EXISTS\s+)", "CREATE TABLE IF NOT EXISTS ", stmt, flags=re.IGNORECASE)
    # CREATE INDEX ... -> CREATE INDEX IF NOT EXISTS ...
    stmt = re.sub(r"CREATE\s+INDEX\s+(?!IF\s+NOT\s+EXISTS\s+)", "CREATE INDEX IF NOT EXISTS ", stmt, flags=re.IGNORECASE)
    # ALTER TABLE ... ADD COLUMN ... -> ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...
    stmt = re.sub(r"ALTER\s+TABLE\s+(\S+)\s+ADD\s+COLUMN\s+(?!IF\s+NOT\s+EXISTS\s+)", r"ALTER TABLE \1 ADD COLUMN IF NOT EXISTS ", stmt, flags=re.IGNORECASE)
    return stmt


def _apply_migrations():
    """db/migrations/ 아래 SQL 파일을 실행하여 스키마를 최신 상태로 유지한다."""
    migrations_dir = Path(__file__).resolve().parent / "db" / "migrations"
    if not migrations_dir.exists():
        return
    files = sorted(migrations_dir.glob("*.sql"))
    if not files:
        return
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS _migration_versions (filename TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT NOW())"))
        applied = {row[0] for row in conn.execute(text("SELECT filename FROM _migration_versions")).fetchall()}
        for path in files:
            name = path.name
            if name in applied:
                continue
            sql = path.read_text(encoding="utf-8")
            for statement in sql.split(";"):
                stmt = statement.strip()
                if not stmt:
                    continue
                stmt = _make_idempotent(stmt)
                conn.execute(text(stmt))
            conn.execute(text("INSERT INTO _migration_versions (filename) VALUES (:name)"), {"name": name})


def _seed():
    """최초 부팅: 테이블 생성 + 마이그레이션 적용 + 관리자 계정 + 기본 설정 시드."""
    Base.metadata.create_all(bind=engine)
    _apply_migrations()
    db = SessionLocal()
    try:
        existing = db.execute(select(AdminUser).where(AdminUser.email == settings.admin_email)).scalar_one_or_none()
        if existing is None:
            db.add(AdminUser(email=settings.admin_email, password_hash=hash_password(settings.admin_initial_password)))
            db.commit()
        settings_store.seed_defaults(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _seed()
    yield


app = FastAPI(title="PROOF API", lifespan=lifespan, docs_url="/api/v1/docs", openapi_url="/api/v1/openapi.json")


# [Flow: Step 1 (요청 scope 로 압축 제외 여부 판단) -> Step 2 (제외 대상은 원본 앱으로 우회)
#       -> Step 3 (나머지는 starlette GZipMiddleware 에 위임)]
#
# 이 서비스는 리버스 프록시 없이 uvicorn 이 SPA 번들과 API JSON 을 직접 서빙한다.
# 압축이 없으면 첫 진입 그래프(JS+CSS)를 원본 839KB 그대로 내려보낸다 — gzip 시 232KB(3.62배).
#
# 전역 GZipMiddleware 를 그냥 붙이면 안 된다. starlette 의 GZipResponder 는 스트리밍
# 응답에서 청크를 deflate 윈도우에 write 만 하고 flush 하지 않는다(starlette/middleware/gzip.py).
# 따라서 SSE 처럼 작은 청크를 즉시 흘려보내야 하는 응답은 버퍼가 찰 때까지 클라이언트에
# 아무것도 도달하지 않는다 — /api/ai/* AI 채팅 스트리밍이 눈에 띄게 멈춘다.
#
# compresslevel 은 6 을 쓴다. 실측(839KB 진입 번들)에서 level 9 대비 압축률은 99.7% 를
# 유지하면서 CPU 는 27ms -> 22ms 로 줄어, 요청당 압축 비용이 더 유리하다.
GZIP_MINIMUM_SIZE = 1024
GZIP_COMPRESS_LEVEL = 6

# 압축을 건너뛸 경로 접두사 — 전부 업스트림 응답을 그대로 relay 하는 스트리밍 경로다.
# /supabase/* 는 proxy_supabase 가 모든 응답을 StreamingResponse 로 흘려보내는데(supabase_proxy.py),
# 그 안에 Storage 바이너리 다운로드(PDF/이미지)가 섞여 있다. 압축 이득이 없는 바이트를
# 버퍼링만 하게 되므로 접두사 단위로 통째로 제외한다.
STREAMING_PATH_PREFIXES = ("/api/ai/", "/api/v1/ai/", "/supabase/")

# 이미 압축된 포맷 — gzip 을 걸어도 크기가 줄지 않고 CPU 와 메모리만 쓴다.
# 주의: .wasm 은 여기 넣지 않는다. 압축되지 않은 바이트코드라 실측 2.17배
# (pdfium 4.6MB -> 2.1MB) 로 줄어드는, 이 앱에서 가장 큰 단일 절감 대상이다.
# 같은 이유로 .svg / .map / .json 도 텍스트이므로 제외 목록에 넣지 않는다.
PRECOMPRESSED_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".ico",
    ".woff", ".woff2",
    ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac",
    ".mp4", ".m4v", ".webm", ".mov", ".avi", ".mkv",
    ".zip", ".gz", ".br", ".7z", ".rar", ".bz2", ".tgz",
    ".pdf", ".xlsx", ".docx", ".pptx", ".hwpx",
)


def _should_skip_compression(scope) -> bool:
    """이 요청의 응답을 gzip 하지 않고 그대로 흘려보내야 하는지 판단한다.

    scope 는 요청 측 정보만 담고 있어 응답 content-type 을 볼 수 없다.
    따라서 경로 접두사와 확장자로 근사한다.

    Args:
        scope: ASGI HTTP scope. `scope["path"]` 로 요청 경로를 읽을 수 있다.

    Returns:
        압축을 건너뛰어야 하면 True, gzip 해도 되면 False.
    """
    path = scope.get("path", "")
    if path.startswith(STREAMING_PATH_PREFIXES):
        return True
    # 쿼리스트링은 scope["query_string"] 에 따로 담기므로 path 끝이 곧 확장자다.
    return path.lower().endswith(PRECOMPRESSED_EXTENSIONS)


class SelectiveGZipMiddleware:
    """스트리밍 경로를 제외하고 응답을 gzip 압축하는 ASGI 미들웨어."""

    def __init__(self, app, minimum_size: int = GZIP_MINIMUM_SIZE, compresslevel: int = GZIP_COMPRESS_LEVEL):
        self.app = app
        self.gzip_app = GZipMiddleware(app, minimum_size=minimum_size, compresslevel=compresslevel)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or _should_skip_compression(scope):
            await self.app(scope, receive, send)
            return
        await self.gzip_app(scope, receive, send)


app.add_middleware(SelectiveGZipMiddleware)
app.include_router(jobs.router)
app.include_router(admin.router)
app.include_router(payments.router)
app.include_router(subscriptions.router)
app.include_router(auth.router)
app.include_router(on_premise.router)
app.include_router(supabase_proxy_router)
app.include_router(gdpr_router)
app.include_router(v1_router)
app.include_router(sandboxes_router)
app.include_router(flow_drawings_router)
app.include_router(ediscovery_router)
app.include_router(chat_conversations_router)
if settings.dev_bypass_auth:
    app.include_router(dev_auth_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# [Flow: Step 1 (클라이언트의 /api/ai/* 요청 수신) -> Step 2 (Node.js AI 백엔드로 전달)
#       -> Step 3 (스트리밍 응답을 그대로 클라이언트에 relay)]
# Vercel AI SDK 5.x useChat이 POST /api/ai/chat으로 스트리밍 요청을 보낸다.
# Vite dev server의 proxy가 로컬 개발에서 이 경로를 Node 백엔드로 전달하지만,
# 프로덕션/단일 오리진 환경에서는 FastAPI가 빌드된 SPA를 서빙하므로
# FastAPI 자체가 /api/ai/*를 Node AI 백엔드로 리버스 프록시해야 한다.
# 그렇지 않으면 SPA catch-all GET 라우트가 POST 요청에 405를 반환한다.
AI_BACKEND_URL = settings.ai_backend_url.rstrip("/")

# 프록시 전달에서 제외할 hop-by-hop 헤더 (RFC 7230 6.1)
_HOP_BY_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}


@app.api_route("/api/ai/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_ai_backend(path: str, request: Request):
    """[Flow: Node.js AI 백엔드로 /api/ai/* 요청을 리버스 프록시한다]

    Args:
        path: /api/ai/ 이후의 하위 경로 (예: "chat").
        request: 원본 FastAPI 요청 (메서드/헤더/본문 그대로 전달).

    Returns:
        Node AI 백엔드의 응답을 스트리밍으로 relay한 StreamingResponse.
    """
    target_url = f"{AI_BACKEND_URL}/api/ai/{path}"

    # hop-by-hop 헤더를 제외한 요청 헤더를 그대로 전달한다.
    forward_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP_HEADERS
    }

    # 요청 본문을 비동기로 읽어 Node 백엔드로 전달한다.
    body = await request.body()

    client = httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0))
    upstream_req = client.build_request(
        request.method,
        target_url,
        headers=forward_headers,
        params=request.query_params,
        content=body,
    )
    upstream_resp = await client.send(upstream_req, stream=True)

    # 응답 헤더 중 hop-by-hop을 제외하고 그대로 전달한다.
    response_headers = {
        k: v for k, v in upstream_resp.headers.items()
        if k.lower() not in _HOP_BY_HOP_HEADERS
    }

    async def relay_stream():
        """Node AI 백엔드의 스트리밍 응답을 클라이언트로 relay하고 커넥션을 정리한다."""
        try:
            async for chunk in upstream_resp.aiter_raw():
                yield chunk
        finally:
            await upstream_resp.aclose()
            await client.aclose()

    return StreamingResponse(
        relay_stream(),
        status_code=upstream_resp.status_code,
        headers=response_headers,
        media_type=upstream_resp.headers.get("content-type"),
    )


# [Flow: Step 1 (해시된 정적 자산 요청) -> Step 2 (1년 immutable 캐시 헤더 부착) -> Step 3 (재방문 시 재검증 왕복 제거)]
# Vite/Docusaurus 산출물은 파일명에 콘텐츠 해시가 들어가므로 내용이 바뀌면 URL 이 바뀐다.
# 따라서 만료 없이 캐시해도 안전하며, immutable 이 있어야 브라우저가 새로고침에서도
# 조건부 요청(304 왕복)을 생략한다. 이 헤더가 없으면 초기 로드의 청크 수만큼 왕복이 발생한다.
IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"


class ImmutableStaticFiles(StaticFiles):
    """콘텐츠 해시가 붙은 정적 자산에 장기 immutable 캐시 헤더를 부착하는 StaticFiles."""

    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        # 200 과 304 양쪽에 부착한다. Starlette 의 file_response 는 조건부 요청에서
        # NotModifiedResponse(304) 를 직접 반환하며, 304 의 헤더는 저장된 캐시 항목의
        # 신선도를 갱신하므로(RFC 9111) cache-control 이 함께 실려야 한다.
        response.headers["cache-control"] = IMMUTABLE_CACHE_CONTROL
        return response


def _html_response(path: Path) -> FileResponse:
    """SPA/문서 진입 HTML 은 항상 재검증한다 — 해시된 자산 URL 을 담고 있으므로 오래 캐시하면 안 된다."""
    return FileResponse(path, headers={"cache-control": "no-cache"})


# Docusaurus 문서 사이트 서빙 (빌드 산출물이 있을 때만)
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "build"
if DOCS_DIR.exists():
    app.mount("/docs/assets", ImmutableStaticFiles(directory=DOCS_DIR / "assets"), name="docs-assets")

    @app.get("/docs")
    def docs_index():
        return _html_response(DOCS_DIR / "index.html")

    @app.get("/docs/{full_path:path}")
    def docs_catch_all(full_path: str):
        target = DOCS_DIR / full_path
        if target.is_file():
            return FileResponse(target)
        if target.is_dir() and (target / "index.html").exists():
            return _html_response(target / "index.html")
        return _html_response(DOCS_DIR / "index.html")

# 정적 프론트엔드 서빙 (빌드 산출물이 있을 때만)
if STATIC_DIR.exists():
    app.mount("/assets", ImmutableStaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/")
    @app.get("/admin")
    def spa_index():
        return _html_response(STATIC_DIR / "index.html")

    @app.get("/{full_path:path}")
    def spa_catch_all(full_path: str):
        # API 경로가 아니면 SPA index 반환 (클라이언트 라우팅)
        target = STATIC_DIR / full_path
        if target.exists() and target.is_file():
            return FileResponse(target)
        return _html_response(STATIC_DIR / "index.html")
