#!/usr/bin/env python3
# [Flow: Step 1 (플랜 한도 정의) -> Step 2 (현재 구독 기간 계산) -> Step 3 (기간 사용량 조회/생성) -> Step 4 (사용량 예약/차감) -> Step 5 (구독 상태 및 잔여 한도 반환)]
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import AdminUser, SubscriptionUsage, User

logger = logging.getLogger(__name__)


def _is_admin_user(db: Session, user: User) -> bool:
    """관리자 여부를 판별한다.
    User.is_admin 플래그 또는 admin_users 테이블 등록 여부를 기준으로 한다.
    (points_service.spend_points 의 관리자 판별 로직과 동일하게 유지)"""
    if getattr(user, "is_admin", False):
        return True
    return (
        db.execute(select(AdminUser).where(AdminUser.email == user.email)).scalar_one_or_none()
        is not None
    )

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


def _normalize_period_start(value: datetime | None) -> datetime:
    """period_start를 UTC timezone-aware datetime으로 정규화한다."""
    if value is None:
        now = datetime.now(timezone.utc)
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _get_period_start(user: User) -> datetime:
    """사용자의 현재 구독 기간 시작일을 반환한다.
    Paddle에서 받은 구독 기간이 없으면 달력월 시작일을 기본으로 사용한다."""
    return _normalize_period_start(user.subscription_period_start)


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


def _get_usage_for_period(db: Session, user_id: uuid.UUID, period_start: datetime) -> SubscriptionUsage:
    """특정 기간의 사용량 레코드를 조회하거나 생성한다. (내부용)"""
    period_start = _normalize_period_start(period_start)
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


def get_subscription_status(db: Session, user: User) -> dict[str, Any]:
    """사용자의 구독 플랜, 상태, 현재 기간 사용량 및 잔여 한도를 반환한다.

    관리자는 플랜 한도와 무관하게 무제한으로 표시한다.
    사용량(used)은 통계를 위해 계속 누적 기록한다."""
    plan = user.subscription_plan or "free"
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    period_start = _get_period_start(user)
    usage = _get_usage_for_period(db, user.id, period_start)

    # 관리자 우회: 한도를 무제한(-1)으로 표시한다.
    if _is_admin_user(db, user):
        unlimited_limits = {"basic_pages": -1, "premium_pages": -1, "media_seconds": -1}
        return {
            "plan": plan,
            "status": user.subscription_status or "inactive",
            "active": True,
            "period_start": period_start.isoformat(),
            "period_end": user.subscription_period_end.isoformat() if user.subscription_period_end else None,
            "limits": unlimited_limits,
            "used": {
                "basic_pages": usage.basic_pages,
                "premium_pages": usage.premium_pages,
                "media_seconds": usage.media_seconds,
            },
            "remaining": {
                "basic_pages": -1,  # 무제한
                "premium_pages": -1,
                "media_seconds": -1,
            },
        }

    return {
        "plan": plan,
        "status": user.subscription_status or "inactive",
        "active": is_subscription_active(user),
        "period_start": period_start.isoformat(),
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


def check_enough(
    db: Session,
    user: User,
    basic_pages: int = 0,
    premium_pages: int = 0,
    media_seconds: int = 0,
) -> dict[str, Any]:
    """주어진 사용량이 현재 구독 한도 내에서 가능한지 확인한다. (차감하지 않음)

    반환값: {"ok": bool, "reason": str|None, "remaining": dict, "limits": dict}

    관리자는 구독 플랜 한도와 무관하게 무제한 사용 가능하다.
    """
    # 관리자 우회: 월간 페이지/미디어 한도를 무제한으로 취급한다.
    if _is_admin_user(db, user):
        return {
            "ok": True,
            "reason": None,
            "remaining": {
                "basic_pages": -1,  # 무제한을 나타내는 센티넬값
                "premium_pages": -1,
                "media_seconds": -1,
            },
            "limits": {"basic_pages": -1, "premium_pages": -1, "media_seconds": -1},
        }

    if not is_subscription_active(user):
        return {"ok": False, "reason": "구독이 활성 상태가 아닙니다.", "remaining": {}, "limits": {}}

    plan = user.subscription_plan or "free"
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    period_start = _get_period_start(user)
    usage = _get_usage_for_period(db, user.id, period_start)

    remaining_basic = max(0, limits["basic_pages"] - usage.basic_pages)
    remaining_premium = max(0, limits["premium_pages"] - usage.premium_pages)
    remaining_media = max(0, limits["media_seconds"] - usage.media_seconds)

    if basic_pages > remaining_basic:
        return {
            "ok": False,
            "reason": f"기본 모델 월간 한도 초과 (잔여: {remaining_basic}페이지)",
            "remaining": {
                "basic_pages": remaining_basic,
                "premium_pages": remaining_premium,
                "media_seconds": remaining_media,
            },
            "limits": limits,
        }
    if premium_pages > remaining_premium:
        return {
            "ok": False,
            "reason": f"고급 모델 월간 한도 초과 (잔여: {remaining_premium}페이지)",
            "remaining": {
                "basic_pages": remaining_basic,
                "premium_pages": remaining_premium,
                "media_seconds": remaining_media,
            },
            "limits": limits,
        }
    if media_seconds > remaining_media:
        return {
            "ok": False,
            "reason": f"미디어 월간 한도 초과 (잔여: {remaining_media // 60}분)",
            "remaining": {
                "basic_pages": remaining_basic,
                "premium_pages": remaining_premium,
                "media_seconds": remaining_media,
            },
            "limits": limits,
        }

    return {
        "ok": True,
        "reason": None,
        "remaining": {
            "basic_pages": remaining_basic,
            "premium_pages": remaining_premium,
            "media_seconds": remaining_media,
        },
        "limits": limits,
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
    반환값: 현재 사용량과 잔여 한도를 포함한 상태.

    관리자는 구독 플랜 한도와 무관하게 무제한 사용 가능하다.
    사용량 레코드는 통계/가시성을 위해 계속 누적 기록하되, 한도 초과 검사는 건너뛴다."""
    # 관리자 우회: 한도 초과 검사 없이 사용량만 누적 기록한다.
    if _is_admin_user(db, user):
        period_start = _get_period_start(user)
        usage = _get_usage_for_period(db, user.id, period_start)
        usage.basic_pages += basic_pages
        usage.premium_pages += premium_pages
        usage.media_seconds += media_seconds
        db.commit()
        db.refresh(usage)
        return {
            "plan": user.subscription_plan or "free",
            "period_start": period_start.isoformat(),
            "used": {
                "basic_pages": usage.basic_pages,
                "premium_pages": usage.premium_pages,
                "media_seconds": usage.media_seconds,
            },
            "remaining": {
                "basic_pages": -1,  # 무제한
                "premium_pages": -1,
                "media_seconds": -1,
            },
        }

    if not is_subscription_active(user):
        raise ValueError("구독이 활성 상태가 아닙니다. 요금제를 선택해주세요.")

    plan = user.subscription_plan or "free"
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    period_start = _get_period_start(user)
    usage = _get_usage_for_period(db, user.id, period_start)

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
        "period_start": period_start.isoformat(),
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
    period_start: datetime | None = None,
) -> None:
    """작업 실패/취소 등으로 예약된 사용량을 되돌린다.

    period_start를 지정하면 해당 구독 기간의 사용량만 환불한다.
    미지정 시 현재 구독 기간 시작일을 사용한다."""
    period_start = _normalize_period_start(period_start) if period_start else _get_period_start(user)
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
