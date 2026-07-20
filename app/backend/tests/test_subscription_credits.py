#!/usr/bin/env python3
# [Flow: Step 1 (backend 패키지 경로 설정) -> Step 2 (SQLite 테스트 DB) -> Step 3 (구독 크레딧 지급/차감/환불/상태 검증)]
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

import pytest
from sqlalchemy import String, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.types import UUID as SQLUUID

from backend.db.models import Base, PointTransaction, User


def _setup_test_db() -> Session:
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


def _make_user(
    db: Session,
    plan: str = "free",
    points: int = 0,
    granted_at: datetime | None = None,
) -> User:
    user = User(
        id=str(uuid.uuid4()),
        email=f"{uuid.uuid4().hex}@example.com",
        points_balance=points,
        subscription_plan=plan,
        subscription_status="active" if plan != "free" else "inactive",
        subscription_credits_granted_at=granted_at,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _seed_rates(mocker):
    mocker.patch(
        "backend.core.subscription_service.points_service._get_rate",
        return_value={
            "basic_page": 1,
            "premium_page": 5,
            "premium_audio_sec": 1,
            "premium_video_sec": 10,
            "agent_step": 1,
        },
    )


class TestGrantMonthlyCredits:
    def test_first_grant_free(self, db_session, mocker):
        _seed_rates(mocker)
        from backend.core.subscription_service import grant_monthly_credits

        user = _make_user(db_session, plan="free", points=0)
        granted = grant_monthly_credits(db_session, user)
        assert granted is True
        assert user.points_balance == 1000
        assert user.subscription_credits_granted_at is not None

    def test_first_grant_pro(self, db_session, mocker):
        _seed_rates(mocker)
        from backend.core.subscription_service import grant_monthly_credits

        user = _make_user(db_session, plan="pro", points=100)
        granted = grant_monthly_credits(db_session, user)
        assert granted is True
        assert user.points_balance == 100 + 30000

    def test_skip_duplicate_same_month(self, db_session, mocker):
        _seed_rates(mocker)
        from backend.core.subscription_service import grant_monthly_credits

        now = datetime.now(timezone.utc)
        user = _make_user(db_session, plan="pro", points=0, granted_at=now)
        granted = grant_monthly_credits(db_session, user)
        assert granted is False
        assert user.points_balance == 0

    def test_grant_next_month(self, db_session, mocker):
        _seed_rates(mocker)
        from backend.core.subscription_service import grant_monthly_credits

        # 작년 12월 15일에 지급받았으면 올해 1월 15일에 재지급 대상
        granted_at = datetime(2025, 12, 15, 0, 0, 0, tzinfo=timezone.utc)
        user = _make_user(db_session, plan="pro", points=0, granted_at=granted_at)
        granted = grant_monthly_credits(db_session, user)
        assert granted is True
        assert user.points_balance == 30000


class TestCheckEnough:
    def test_ok(self, db_session, mocker):
        _seed_rates(mocker)
        from backend.core.subscription_service import check_enough

        user = _make_user(db_session, points=100)
        result = check_enough(
            db_session, user, basic_pages=10, premium_pages=0, audio_seconds=0, video_seconds=0
        )
        assert result["ok"] is True
        assert result["remaining"] == 100

    def test_insufficient(self, db_session, mocker):
        _seed_rates(mocker)
        from backend.core.subscription_service import check_enough

        user = _make_user(db_session, points=5)
        result = check_enough(
            db_session, user, basic_pages=0, premium_pages=10, audio_seconds=0, video_seconds=0
        )
        assert result["ok"] is False
        assert "잔액" in result["reason"]

    def test_admin_always_ok(self, db_session, mocker):
        _seed_rates(mocker)
        from backend.core.subscription_service import check_enough

        user = _make_user(db_session, points=0)
        user.is_admin = True
        db_session.commit()
        result = check_enough(
            db_session, user, basic_pages=1000, premium_pages=1000, audio_seconds=1000, video_seconds=1000
        )
        assert result["ok"] is True
        assert result["remaining"] == -1


class TestReserveAndRelease:
    def test_reserve_spend_points(self, db_session, mocker):
        _seed_rates(mocker)
        from backend.core.subscription_service import reserve_usage

        user = _make_user(db_session, points=100)
        result = reserve_usage(
            db_session, user, basic_pages=10, premium_pages=0, audio_seconds=0, video_seconds=0
        )
        assert user.points_balance == 90
        assert result["remaining"] == 90
        assert result["cost_points"] == 10

    def test_reserve_insufficient(self, db_session, mocker):
        _seed_rates(mocker)
        from backend.core.subscription_service import reserve_usage

        user = _make_user(db_session, points=5)
        with pytest.raises(ValueError):
            reserve_usage(
                db_session, user, basic_pages=0, premium_pages=10, audio_seconds=0, video_seconds=0
            )

    def test_release_refunds_points(self, db_session, mocker):
        _seed_rates(mocker)
        from backend.core.subscription_service import reserve_usage, release_usage

        user = _make_user(db_session, points=100)
        reserve_usage(
            db_session, user, basic_pages=0, premium_pages=10, audio_seconds=0, video_seconds=0
        )
        release_usage(
            db_session, user, basic_pages=0, premium_pages=10, audio_seconds=0, video_seconds=0
        )
        assert user.points_balance == 100


class TestGetSubscriptionStatus:
    def test_returns_points_balance(self, db_session, mocker):
        _seed_rates(mocker)
        from backend.core.subscription_service import get_subscription_status

        user = _make_user(db_session, plan="pro", points=1234)
        status = get_subscription_status(db_session, user)
        assert status["plan"] == "pro"
        assert status["points_balance"] == 1234
        assert status["monthly_credits"] == 30000
        assert status["remaining"] == 1234
