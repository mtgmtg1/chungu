#!/usr/bin/env python3
# [Flow: Step 1 (플랜 한도 정의) -> Step 2 (현재 구독 기간 계산) -> Step 3 (기간 사용량 조회/생성) -> Step 4 (사용량 예약/차감) -> Step 5 (구독 상태 및 잔여 한도 반환)]
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..db.models import SubscriptionUsage, User

logger = logging.getLogger(__name__)

# 플랜별 월간 한도
PLAN_LIMITS: dict[str, dict[str, int]] = {
    "free": {
        "basic_pages": 1000,
        "premium_pages": 500,
        "media_seconds": 150 * 60,  # 150분
    },
    "pro": {
        "basic_pages": 10000,
        "premium_pages": 5000,
        "media_seconds": 1500 * 60,  # 1500분
    },
    "max": {
        "basic_pages": 60000,
        "premium_pages": 30000,
        "media_seconds": 9000 * 60,  # 9000분
    },
}


def _get_period_start(user: User) -> datetime:
    """사용자의 현재 구독 기간 시작일을 반환한다.
    Paddle에서 받은 구독 기간이 없으면 달력월 시작일을 기본으로 사용한다."""
    if user.subscription_period_start:
        return user.subscription_period_start
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _get_or_create_usage(db: Session, user_id: uuid.UUID, period_start: datetime) -> SubscriptionUsage:
    """특정 구독 기간의 사용량 레코드를 조회하거나 생성한다."""
    usage = (
        db.query(SubscriptionUsage)
        .filter(
            SubscriptionUsage.user_id == user_id,
            SubscriptionUsage.period_start == period_start,
        )
        .first()
    )
    if usage is None:
        usage = SubscriptionUsage(
            user_id=user_id,
            period_start=period_start,
            basic_pages=0,
            premium_pages=0,
            media_seconds=0,
        )
        db.add(usage)
        db.commit()
        db.refresh(usage)
    return usage


def is_subscription_active(user: User) -> bool:
    """사용자의 구독이 현재 활성 상태인지 확인한다.
    Free 플랜은 Paddle 구독 없이도 항상 활성으로 간주한다."""
    if user.subscription_plan == "free":
        return True
    if user.subscription_status not in ("active", "trialing"):
        return False
    if user.subscription_period_end and datetime.now(timezone.utc) > user.subscription_period_end:
        return False
    return True


def get_subscription_status(db: Session, user: User) -> dict[str, Any]:
    """사용자의 구독 플랜, 상태, 현재 기간 사용량 및 잔여 한도를 반환한다."""
    plan = user.subscription_plan or "free"
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    period_start = _get_period_start(user)
    usage = _get_or_create_usage(db, user.id, period_start)

    return {
        "plan": plan,
        "status": user.subscription_status or "inactive",
        "active": is_subscription_active(user),
        "period_start": period_start.isoformat() if period_start else None,
        "period_end": user.subscription_period_end.isoformat() if user.subscription_period_end else None,
        "limits": limits,
        "used": {
            "basic_pages": usage.basic_pages,
            "premium_pages": usage.premium_pages,
            "media_seconds": usage.media_seconds,
        },
        "remaining": {
            "basic_pages": max(0, limits["basic_pages"] - usage.basic_pages),
            "premium_pages": max(0, limits["premium_pages"] - usage.premium_pages),
            "media_seconds": max(0, limits["media_seconds"] - usage.media_seconds),
        },
    }


def reserve_usage(
    db: Session,
    user: User,
    basic_pages: int = 0,
    premium_pages: int = 0,
    media_seconds: int = 0,
) -> dict[str, Any]:
    """작업 승인 시점에 월간 구독 한도 내 사용량을 예약(차감)한다.
    한도 초과 시 ValueError를 발생시킨다.
    반환값: 현재 사용량과 잔여 한도를 포함한 상태."""
    if not is_subscription_active(user):
        raise ValueError("구독이 활성 상태가 아닙니다. 요금제를 선택해주세요.")

    plan = user.subscription_plan or "free"
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    period_start = _get_period_start(user)
    usage = _get_or_create_usage(db, user.id, period_start)

    if usage.basic_pages + basic_pages > limits["basic_pages"]:
        raise ValueError(
            f"기본 모델 월간 한도 초과 (잔여: {limits['basic_pages'] - usage.basic_pages}페이지)"
        )
    if usage.premium_pages + premium_pages > limits["premium_pages"]:
        raise ValueError(
            f"고급 모델 월간 한도 초과 (잔여: {limits['premium_pages'] - usage.premium_pages}페이지)"
        )
    if usage.media_seconds + media_seconds > limits["media_seconds"]:
        raise ValueError(
            f"미디어 월간 한도 초과 (잔여: {(limits['media_seconds'] - usage.media_seconds) // 60}분)"
        )

    usage.basic_pages += basic_pages
    usage.premium_pages += premium_pages
    usage.media_seconds += media_seconds
    db.commit()
    db.refresh(usage)

    return {
        "plan": plan,
        "period_start": period_start.isoformat() if period_start else None,
        "used": {
            "basic_pages": usage.basic_pages,
            "premium_pages": usage.premium_pages,
            "media_seconds": usage.media_seconds,
        },
        "remaining": {
            "basic_pages": max(0, limits["basic_pages"] - usage.basic_pages),
            "premium_pages": max(0, limits["premium_pages"] - usage.premium_pages),
            "media_seconds": max(0, limits["media_seconds"] - usage.media_seconds),
        },
    }


def release_usage(
    db: Session,
    user: User,
    basic_pages: int = 0,
    premium_pages: int = 0,
    media_seconds: int = 0,
) -> None:
    """작업 실패/취소 등으로 예약된 사용량을 되돌린다."""
    period_start = _get_period_start(user)
    usage = (
        db.query(SubscriptionUsage)
        .filter(
            SubscriptionUsage.user_id == user.id,
            SubscriptionUsage.period_start == period_start,
        )
        .first()
    )
    if usage is None:
        return
    usage.basic_pages = max(0, usage.basic_pages - basic_pages)
    usage.premium_pages = max(0, usage.premium_pages - premium_pages)
    usage.media_seconds = max(0, usage.media_seconds - media_seconds)
    db.commit()


def sync_subscription_from_paddle(
    db: Session,
    user: User,
    plan: str,
    status: str,
    period_start: datetime,
    period_end: datetime,
    price_id: str,
    paddle_subscription_id: str,
) -> None:
    """Paddle webhook으로 받은 구독 정보를 사용자 레코드에 동기화한다."""
    user.subscription_plan = plan
    user.subscription_status = status
    user.subscription_period_start = period_start
    user.subscription_period_end = period_end
    user.subscription_price_id = price_id
    user.paddle_subscription_id = paddle_subscription_id
    db.commit()
