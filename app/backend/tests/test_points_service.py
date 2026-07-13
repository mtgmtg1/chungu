#!/usr/bin/env python3
# [Flow: Step 1 (backend 패키지 경로 설정) -> Step 2 (SQLite 테스트 DB 구성) -> Step 3 (단가 mock) -> Step 4 (비용/차감/환불 검증)]
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

import pytest
from sqlalchemy import String, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.types import UUID as SQLUUID

from backend.db.models import Base, PointTransaction, User


def _setup_test_db() -> Session:
    """SQLite in-memory DB를 생성하고 UUID 컬럼을 String(36)으로 교체한다."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, SQLUUID):
                column.type = String(36)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


@pytest.fixture
def db_session():
    db = _setup_test_db()
    try:
        yield db
    finally:
        db.close()


def _make_user(db: Session, points: int = 0) -> User:
    user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4().hex}@example.com", points_balance=points)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _seed_rates(mocker):
    mocker.patch(
        "backend.core.points_service.settings_store.get_setting",
        side_effect=lambda _db, key: {
            "cost_basic_page_krw": "1",
            "cost_premium_page_krw": "5",
            "cost_premium_audio_sec_krw": "1",
            "cost_premium_video_sec_krw": "10",
            "cost_agent_step_krw": "1",
            "cost_per_docling_refinement_page_krw": "3",
        }.get(key, ""),
    )


class TestCalculateCost:
    def test_basic_pages_cost(self, db_session, mocker):
        _seed_rates(mocker)
        from backend.core.points_service import calculate_cost

        result = calculate_cost(db_session, pages=10, ocr_model="basic")
        assert result["points"] == 10  # 10페이지 * 1pt

    def test_premium_pages_cost(self, db_session, mocker):
        _seed_rates(mocker)
        from backend.core.points_service import calculate_cost

        result = calculate_cost(db_session, pages=10, ocr_model="premium")
        assert result["points"] == 50  # 10페이지 * 5pt

    def test_media_cost(self, db_session, mocker):
        _seed_rates(mocker)
        from backend.core.points_service import calculate_cost

        result = calculate_cost(
            db_session, audio_seconds=60, video_seconds=30, ocr_model="premium"
        )
        assert result["points"] == 60 + 300  # 오디오 60pt + 비디오 30*10=300pt

    def test_agent_steps_cost(self, db_session, mocker):
        _seed_rates(mocker)
        from backend.core.points_service import calculate_cost

        result = calculate_cost(db_session, agent_steps=7, ocr_model="premium")
        assert result["points"] == 7

    def test_combined_cost(self, db_session, mocker):
        _seed_rates(mocker)
        from backend.core.points_service import calculate_cost

        result = calculate_cost(
            db_session,
            pages=5,
            image_count=2,
            audio_seconds=10,
            video_seconds=5,
            agent_steps=3,
            docling_refinement_pages=2,
            ocr_model="premium",
        )
        expected = (5 + 2) * 5 + 10 * 1 + 5 * 10 + 3 * 1 + 2 * 3
        assert result["points"] == expected

    def test_no_daily_free_for_basic(self, db_session, mocker):
        # 사용자가 지정한대로 일일 무료 한도를 더 이상 적용하지 않는다.
        _seed_rates(mocker)
        from backend.core.points_service import calculate_cost

        result = calculate_cost(db_session, pages=200, ocr_model="basic")
        assert result["points"] == 200  # 200 * 1 (무료 적용 없음)


class TestSpendAndRefund:
    def test_spend_points_success(self, db_session, mocker):
        _seed_rates(mocker)
        from backend.core.points_service import spend_points

        user = _make_user(db_session, 1000)
        tx = spend_points(db_session, user, 123, "test usage")
        assert tx.balance_after == 877
        assert tx.amount == -123
        assert user.points_balance == 877

    def test_spend_points_insufficient(self, db_session, mocker):
        _seed_rates(mocker)
        from backend.core.points_service import spend_points

        user = _make_user(db_session, 10)
        with pytest.raises(ValueError):
            spend_points(db_session, user, 11, "test usage")

    def test_refund_points(self, db_session, mocker):
        _seed_rates(mocker)
        from backend.core.points_service import refund_points

        user = _make_user(db_session, 100)
        tx = refund_points(db_session, user, 30, "test refund")
        assert tx.balance_after == 130
        assert user.points_balance == 130

    def test_admin_spend_does_not_deduct(self, db_session, mocker):
        _seed_rates(mocker)
        from backend.core.points_service import spend_points

        user = _make_user(db_session, 100)
        user.is_admin = True
        db_session.commit()
        tx = spend_points(db_session, user, 50, "admin usage")
        assert user.points_balance == 100
        assert tx.amount == 0
