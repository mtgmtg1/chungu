#!/usr/bin/env python3
# [Flow: Step 1 (SQLite 테스트 DB 생성) -> Step 2 (v1 라우터 로드 + 인증/외부 의존성 mock) -> Step 3 (markdown 업로드/title rename/subscription 조회 검증)]
import io
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import String, create_engine, StaticPool
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.types import TypeDecorator, UUID as SQLUUID

from backend.api.v1 import account, jobs
from backend.api.v1.jobs import require_api_key_with_key
from backend.api.v1.account import require_api_key_or_session
from backend.auth.supabase_auth import CurrentUser
from backend.db.models import ApiKey, Base, Job, User
from backend.db.session import get_db


# ---------- SQLite UUID 호환 타입 ----------

class UUIDString(TypeDecorator):
    """SQLite 테스트에서 UUID 객체를 str로 자동 변환하는 커스텀 타입."""
    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return str(value)
        return value


# ---------- DB 셋업 헬퍼 ----------

def _setup_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    for table in Base.metadata.tables.values():
        for column in table.columns:
            # 다른 테스트가 이미 String(36)으로 변환했을 수 있으므로 UUID와 String 모두 처리
            if isinstance(column.type, SQLUUID) or (isinstance(column.type, String) and getattr(column.type, "length", None) == 36):
                column.type = UUIDString()
    Base.metadata.create_all(bind=engine)
    return engine


def _make_user(db: Session, points: int = 100000) -> User:
    user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4().hex}@example.com", points_balance=points)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_api_key(db: Session, user_id: str) -> ApiKey:
    key = ApiKey(
        id=str(uuid.uuid4()),
        user_id=user_id,
        name="test-key",
        prefix="chu_live",
        key_hash="hash",
        scopes=["jobs:read", "jobs:write"],
        rate_limit_rpm=60,
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    return key


# ---------- 공통 픽스처 ----------

@pytest.fixture
def engine():
    return _setup_engine()


@pytest.fixture
def db_session(engine):
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def app(mocker, engine, db_session):
    """v1 jobs + account 라우터를 로드한 FastAPI 앱. 인증과 외부 의존성을 mock한다."""
    user = _make_user(db_session)
    api_key = _make_api_key(db_session, str(user.id))

    current_user = CurrentUser(user_id=str(user.id), email=user.email, is_admin=False, points_balance=user.points_balance)

    # rate limit 통과
    mocker.patch("backend.api.v1.jobs.enforce_rate_limit", return_value=None)
    mocker.patch("backend.api.v1.account.enforce_rate_limit", return_value=None)
    mocker.patch("backend.api.v1.jobs.add_daily_spent_points", return_value=None)
    # 비용 계산: pages=0, image_count=0, audio=0, video=0 → points=0 (markdown)
    mocker.patch(
        "backend.api.v1.jobs.points_service.calculate_cost",
        return_value={"pages": 0, "image_count": 0, "audio_seconds": 0, "video_seconds": 0,
                       "docling_refinement_pages": 0, "ocr_model": "premium",
                       "free_pages_used": 0, "points": 0, "usd": "$0.00"},
    )
    # supabase 업로드 mock
    mocker.patch("backend.api.v1.jobs.supabase_client.upload_input", return_value=f"input/{uuid.uuid4()}.md")

    test_app = FastAPI()
    test_app.include_router(jobs.router)
    test_app.include_router(account.router)

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    test_app.dependency_overrides[get_db] = lambda: SessionLocal()
    # 인증 의존성을 직접 대체하여 API key 검증을 우회한다
    test_app.dependency_overrides[require_api_key_with_key] = lambda: (current_user, api_key)
    test_app.dependency_overrides[require_api_key_or_session] = lambda: (current_user, api_key)
    yield test_app


# ---------- 테스트: markdown 업로드 ----------

def test_upload_markdown_file_accepted(app):
    """[Flow: .md 파일 업로드 → 200 반환 → total_files=1, cost.points=0 확인]"""
    md_content = b"# Test\n\n| col1 | col2 |\n|------|------|\n| a | b |\n"
    with TestClient(app) as client:
        response = client.post(
            "/jobs/upload",
            files={"files": ("test.md", io.BytesIO(md_content), "text/markdown")},
            data={"ocr_model": "premium"},
        )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total_files"] == 1
    assert data["cost"]["points"] == 0
    assert data["file_type"] in ("mixed", "markdown")


def test_media_extensions_includes_md():
    """[Flow: MEDIA_EXTENSIONS 세트에 .md가 포함되어 있는지 확인]"""
    assert ".md" in jobs.MEDIA_EXTENSIONS


def test_media_extensions_includes_office():
    """[Flow: MEDIA_EXTENSIONS 세트에 Office/HWP 확장자가 포함되어 있는지 확인]"""
    for ext in (".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".hwp", ".hwpx"):
        assert ext in jobs.MEDIA_EXTENSIONS, f"{ext} should be in MEDIA_EXTENSIONS"


# ---------- 테스트: Office 업로드 ----------

@pytest.fixture
def office_app(mocker, engine, db_session):
    """Office 업로드 테스트용 앱. docling_client/hwp_converter를 mock한다."""
    user = _make_user(db_session)
    api_key = _make_api_key(db_session, str(user.id))
    current_user = CurrentUser(user_id=str(user.id), email=user.email, is_admin=False, points_balance=user.points_balance)

    mocker.patch("backend.api.v1.jobs.enforce_rate_limit", return_value=None)
    mocker.patch("backend.api.v1.jobs.add_daily_spent_points", return_value=None)
    # Docling 비활성화 → _count_pages_with_docling이 1 반환
    mocker.patch("backend.api.v1.jobs.docling_client.is_enabled", return_value=False)
    # HWP 페이지 카운트 mock
    mocker.patch("backend.api.v1.jobs.hwp_converter.get_page_count", return_value=3)
    # supabase 업로드 mock
    mocker.patch("backend.api.v1.jobs.supabase_client.upload_input", return_value=f"input/{uuid.uuid4()}")
    # 실제 calculate_cost 사용 (mock하지 않음)

    test_app = FastAPI()
    test_app.include_router(jobs.router)

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    test_app.dependency_overrides[get_db] = lambda: SessionLocal()
    test_app.dependency_overrides[require_api_key_with_key] = lambda: (current_user, api_key)
    yield test_app


def test_upload_docx_accepted(office_app, mocker):
    """[Flow: .docx 파일 업로드 → 200 반환 → file_type=docx, total_files=1 확인]"""
    # Docling 비활성화 시 pages=1
    with TestClient(office_app) as client:
        response = client.post(
            "/jobs/upload",
            files={"files": ("test.docx", io.BytesIO(b"fake docx"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            data={"ocr_model": "premium"},
        )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["file_type"] == "docx"
    assert data["total_files"] == 1
    assert data["total_pages"] == 1  # Docling 비활성화 시 기본 1페이지


def test_upload_hwp_accepted(office_app):
    """[Flow: .hwp 파일 업로드 → 200 반환 → file_type=hwp, total_pages=3 확인]"""
    with TestClient(office_app) as client:
        response = client.post(
            "/jobs/upload",
            files={"files": ("test.hwp", io.BytesIO(b"fake hwp"), "application/octet-stream")},
            data={"ocr_model": "premium"},
        )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["file_type"] == "hwp"
    assert data["total_files"] == 1
    assert data["total_pages"] == 3  # hwp_converter.get_page_count mock = 3


def test_upload_with_docling_refinement(office_app, mocker):
    """[Flow: docling_refinement=true → 응답에 docling_refinement_pages=pages 확인]"""
    # calculate_cost를 spy로 사용하여 docling_refinement_pages 인자 검증
    cost_calls = []
    original_calculate = jobs.points_service.calculate_cost

    def spy_calculate_cost(db, **kwargs):
        cost_calls.append(kwargs)
        return original_calculate(db, **kwargs)

    mocker.patch("backend.api.v1.jobs.points_service.calculate_cost", side_effect=spy_calculate_cost)
    with TestClient(office_app) as client:
        response = client.post(
            "/jobs/upload",
            files={"files": ("test.hwp", io.BytesIO(b"fake hwp"), "application/octet-stream")},
            data={"ocr_model": "premium", "docling_refinement": "true"},
        )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["docling_refinement"] is True
    assert data["docling_refinement_pages"] == 3  # hwp pages=3
    # calculate_cost가 docling_refinement_pages=3으로 호출되었는지 확인
    assert any(c.get("docling_refinement_pages") == 3 for c in cost_calls)


# ---------- 테스트: title rename ----------

def test_rename_job_success(app, db_session):
    """[Flow: job 생성 → PATCH /jobs/{id}/title → 200 + title 변경 확인]"""
    user = db_session.query(User).first()
    job = Job(
        id=str(uuid.uuid4()),
        user_id=str(user.id),
        email=user.email,
        pipeline="vision",
        original_filename="original.pdf",
        status="done",
    )
    db_session.add(job)
    db_session.commit()

    with TestClient(app) as client:
        response = client.patch(
            f"/jobs/{job.id}/title",
            json={"title": "새 제목"},
        )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["filename"] == "새 제목"

    db_session.refresh(job)
    assert job.original_filename == "새 제목"


def test_rename_job_empty_title_rejected(app, db_session):
    """[Flow: 빈 title → 400 반환 확인]"""
    user = db_session.query(User).first()
    job = Job(
        id=str(uuid.uuid4()),
        user_id=str(user.id),
        email=user.email,
        pipeline="vision",
        original_filename="original.pdf",
        status="done",
    )
    db_session.add(job)
    db_session.commit()

    with TestClient(app) as client:
        response = client.patch(f"/jobs/{job.id}/title", json={"title": ""})
    assert response.status_code == 400


def test_rename_job_too_long_rejected(app, db_session):
    """[Flow: 200자 초과 title → 400 반환 확인]"""
    user = db_session.query(User).first()
    job = Job(
        id=str(uuid.uuid4()),
        user_id=str(user.id),
        email=user.email,
        pipeline="vision",
        original_filename="original.pdf",
        status="done",
    )
    db_session.add(job)
    db_session.commit()

    with TestClient(app) as client:
        response = client.patch(f"/jobs/{job.id}/title", json={"title": "x" * 201})
    assert response.status_code == 400


# ---------- 테스트: subscription status ----------

def test_account_subscription_endpoint(app, db_session, mocker):
    """[Flow: GET /account/subscription → 200 + subscription_service 호출 확인]"""
    user = db_session.query(User).first()
    fake_status = {"plan": "pro", "status": "active", "monthly_limit": 100000, "used": 5000}
    mocker.patch("backend.api.v1.account.subscription_service.get_subscription_status", return_value=fake_status)
    # SQLite UUID 호환성 문제로 db.get(User, uuid.UUID(...))를 mock하여 User를 직접 반환
    original_get = Session.get

    def mock_get(self, entity, primary_key, **kw):
        if entity is User:
            return user
        return original_get(self, entity, primary_key, **kw)

    mocker.patch.object(Session, "get", mock_get)
    with TestClient(app) as client:
        response = client.get("/account/subscription")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["plan"] == "pro"
    assert data["monthly_limit"] == 100000
