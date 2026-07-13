#!/usr/bin/env python3
# [Flow: Step 1 (SQLite 테스트 DB 생성) -> Step 2 (FastAPI 앱에서 agent 라우터만 분리) -> Step 3 (AI 시크릿으로 POST /steps) -> Step 4 (차감/잔액 검증)]
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import String, create_engine, StaticPool
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.types import UUID as SQLUUID

from backend.api.v1 import agent
from backend.db.models import Base, PointTransaction, User
from backend.db.session import get_db


def _setup_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, SQLUUID):
                column.type = String(36)
    Base.metadata.create_all(bind=engine)
    return engine


def _make_user(db: Session, points: int = 100) -> User:
    user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4().hex}@example.com", points_balance=points)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


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
def app(mocker, engine):
    mocker.patch("backend.core.points_service.settings_store.get_setting", side_effect=lambda _db, key: {
        "cost_basic_page_krw": "1",
        "cost_premium_page_krw": "5",
        "cost_premium_audio_sec_krw": "1",
        "cost_premium_video_sec_krw": "10",
        "cost_agent_step_krw": "1",
        "cost_per_docling_refinement_page_krw": "3",
    }.get(key, ""))
    mocker.patch("backend.config.settings.ai_backend_secret", "test-secret")

    test_app = FastAPI()
    test_app.include_router(agent.router)

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    test_app.dependency_overrides[get_db] = lambda: SessionLocal()
    yield test_app


def test_spend_agent_steps_success(app, db_session):
    with TestClient(app) as client:
        user = _make_user(db_session)
        response = client.post(
            "/agent/steps",
            json={"user_id": str(user.id), "steps": 7},
            headers={"X-AI-Backend-Secret": "test-secret"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["steps"] == 7
        assert data["cost_points"] == 7
        assert data["points_balance"] == 93


def test_spend_agent_steps_invalid_secret(app, db_session):
    with TestClient(app) as client:
        user = _make_user(db_session)
        response = client.post(
            "/agent/steps",
            json={"user_id": str(user.id), "steps": 1},
            headers={"X-AI-Backend-Secret": "wrong"},
        )
        assert response.status_code == 401


def test_spend_agent_steps_insufficient_balance(app, db_session):
    with TestClient(app) as client:
        user = _make_user(db_session, points=3)
        response = client.post(
            "/agent/steps",
            json={"user_id": str(user.id), "steps": 5},
            headers={"X-AI-Backend-Secret": "test-secret"},
        )
        assert response.status_code == 402
