#!/usr/bin/env python3
# [Flow: Step 1 (DB 테이블 생성) -> Step 2 (관리자/설정 시드) -> Step 3 (라우터 등록) -> Step 4 (정적 프론트 서빙)]
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text

from . import settings_store
from .api import admin, auth, jobs, payments
from .api.v1 import router as v1_router
from .auth.security import hash_password
from .config import settings
from .db.models import AdminUser
from .db.session import Base, SessionLocal, engine

STATIC_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"


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


app = FastAPI(title="Chungu API", lifespan=lifespan, docs_url="/api/v1/docs", openapi_url="/api/v1/openapi.json")
app.include_router(jobs.router)
app.include_router(admin.router)
app.include_router(payments.router)
app.include_router(auth.router)
app.include_router(v1_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


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
