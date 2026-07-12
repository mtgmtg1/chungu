#!/usr/bin/env python3
# [Flow: Step 1 (DB 테이블 생성) -> Step 2 (관리자/설정 시드) -> Step 3 (라우터 등록) -> Step 4 (정적 프론트 서빙)]
import re
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
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


# Docusaurus 문서 사이트 서빙 (빌드 산출물이 있을 때만)
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "build"
if DOCS_DIR.exists():
    app.mount("/docs/assets", StaticFiles(directory=DOCS_DIR / "assets"), name="docs-assets")

    @app.get("/docs")
    def docs_index():
        return FileResponse(DOCS_DIR / "index.html")

    @app.get("/docs/{full_path:path}")
    def docs_catch_all(full_path: str):
        target = DOCS_DIR / full_path
        if target.is_file():
            return FileResponse(target)
        if target.is_dir() and (target / "index.html").exists():
            return FileResponse(target / "index.html")
        return FileResponse(DOCS_DIR / "index.html")

# 정적 프론트엔드 서빙 (빌드 산출물이 있을 때만)
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/")
    @app.get("/admin")
    def spa_index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/{full_path:path}")
    def spa_catch_all(full_path: str):
        # API 경로가 아니면 SPA index 반환 (클라이언트 라우팅)
        target = STATIC_DIR / full_path
        if target.exists() and target.is_file():
            return FileResponse(target)
        return FileResponse(STATIC_DIR / "index.html")
