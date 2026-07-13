#!/usr/bin/env python3
# [Flow: Step 1 (플랜별 월간 크레딧 정의) -> Step 2 (월간 크레딧 지급 여부 확인) -> Step 3 (사용량을 포인트로 환산) -> Step 4 (points_balance 차감/환불) -> Step 5 (구독 상태 및 잔여 포인트 반환)]
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import points_service
from ..db.models import AdminUser, SubscriptionUsage, User

logger = logging.getLogger(__name__)


# 플랜별 월간 지급 크레딧 (points, milli-USD)
PLAN_MONTHLY_CREDITS: dict[str, int] = {
    "free": 1000,
    "pro": 20000,
    "max": 100000,
}


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
    """특정 기간의 사용량 레코드를 조회하거나 생성한다. (통계용, 내부용)"""
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


def _next_grant_at(granted_at: datetime) -> datetime:
    """마지막 지급 시점으로부터 다음 달 동일 일자를 반환한다."""
    granted_at = granted_at.astimezone(timezone.utc)
    year = granted_at.year
    month = granted_at.month + 1
    if month > 12:
        month -= 12
        year += 1
    # 동일 일자가 해당 월에 없을 수 있으므로, 최대 일수로 clamp
    try:
        return granted_at.replace(year=year, month=month)
    except ValueError:
        from calendar import monthrange
        last_day = monthrange(year, month)[1]
        return granted_at.replace(year=year, month=month, day=last_day)


def _should_grant_monthly_credits(user: User) -> bool:
    """현재 시점에 월간 크레딧을 지급해야 하는지 판단한다.

    유료 플랜은 구독이 활성 상태일 때만 지급한다."""
    plan = user.subscription_plan or "free"
    if plan not in PLAN_MONTHLY_CREDITS:
        return False
    if plan != "free" and not is_subscription_active(user):
        return False
    if user.subscription_credits_granted_at is None:
        return True
    now = datetime.now(timezone.utc)
    return now >= _next_grant_at(user.subscription_credits_granted_at)


def grant_monthly_credits(db: Session, user: User) -> bool:
    """조건에 맞으면 플랜에 해당하는 월간 크레딧을 points_balance에 지급한다.

    반환값: 지급 여부 (True=지급, False=스킵)
    """
    plan = user.subscription_plan or "free"
    if plan not in PLAN_MONTHLY_CREDITS:
        return False
    if not _should_grant_monthly_credits(user):
        return False

    amount = PLAN_MONTHLY_CREDITS[plan]
    points_service.charge_points(
        db, user, amount, f"{plan.upper()} 월간 구독 크레딧 지급"
    )
    user.subscription_credits_granted_at = datetime.now(timezone.utc)
    db.commit()
    logger.info(f"[subscription] user={user.id} plan={plan} 월간 크레딧 {amount}pt 지급")
    return True


def _calculate_credit_cost(
    db: Session,
    basic_pages: int = 0,
    premium_pages: int = 0,
    audio_seconds: int = 0,
    video_seconds: int = 0,
    docling_refinement_pages: int = 0,
    agent_steps: int = 0,
) -> int:
    """주어진 사용량을 포인트 단가로 환산한다."""
    rate = points_service._get_rate(db)
    refinement_rate = int(points_service.settings_store.get_setting(db, "cost_per_docling_refinement_page_krw") or "3")
    return (
        basic_pages * rate["basic_page"]
        + premium_pages * rate["premium_page"]
        + audio_seconds * rate["premium_audio_sec"]
        + video_seconds * rate["premium_video_sec"]
        + docling_refinement_pages * refinement_rate
        + agent_steps * rate["agent_step"]
    )


def get_subscription_status(db: Session, user: User) -> dict[str, Any]:
    """사용자의 구독 플랜, 상태, 월간 크레딧, 현재 포인트 잔액을 반환한다.

    관리자는 플랜 한도와 무관하게 무제한으로 표시한다."""
    plan = user.subscription_plan or "free"
    monthly_credits = PLAN_MONTHLY_CREDITS.get(plan, 0)
    period_start = _get_period_start(user)

    # 관리자 우회: 한도를 무제한(-1)으로 표시한다.
    if _is_admin_user(db, user):
        return {
            "plan": plan,
            "status": user.subscription_status or "inactive",
            "active": True,
            "period_start": period_start.isoformat(),
            "period_end": user.subscription_period_end.isoformat() if user.subscription_period_end else None,
            "points_balance": user.points_balance,
            "monthly_credits": -1,
            "remaining": -1,  # 무제한
            "limits": {"monthly_credits": -1},
            "used": {"points": 0},
        }

    return {
        "plan": plan,
        "status": user.subscription_status or "inactive",
        "active": is_subscription_active(user),
        "period_start": period_start.isoformat(),
        "period_end": user.subscription_period_end.isoformat() if user.subscription_period_end else None,
        "points_balance": user.points_balance,
        "monthly_credits": monthly_credits,
        "remaining": user.points_balance,
        "limits": {"monthly_credits": monthly_credits},
        "used": {"points": 0},
    }


def check_enough(
    db: Session,
    user: User,
    basic_pages: int = 0,
    premium_pages: int = 0,
    audio_seconds: int = 0,
    video_seconds: int = 0,
    docling_refinement_pages: int = 0,
    agent_steps: int = 0,
) -> dict[str, Any]:
    """주어진 사용량을 points_balance에서 차감할 수 있는지 확인한다. (차감하지 않음)

    반환값: {"ok": bool, "reason": str|None, "remaining": int, "cost_points": int}

    관리자는 구독 플랜 한도와 무관하게 무제한 사용 가능하다.
    """
    # 관리자 우회: 월간 페이지/미디어 한도를 무제한으로 취급한다.
    if _is_admin_user(db, user):
        return {
            "ok": True,
            "reason": None,
            "remaining": -1,  # 무제한을 나타내는 센티넬값
            "cost_points": 0,
        }

    if not is_subscription_active(user):
        return {"ok": False, "reason": "구독이 활성 상태가 아닙니다.", "remaining": 0, "cost_points": 0}

    cost = _calculate_credit_cost(
        db, basic_pages, premium_pages, audio_seconds, video_seconds, docling_refinement_pages, agent_steps
    )
    remaining = user.points_balance

    if cost > remaining:
        return {
            "ok": False,
            "reason": f"포인트 잔액 부족 (잔여: {remaining}pt, 필요: {cost}pt)",
            "remaining": remaining,
            "cost_points": cost,
        }

    return {
        "ok": True,
        "reason": None,
        "remaining": remaining,
        "cost_points": cost,
    }


def reserve_usage(
    db: Session,
    user: User,
    basic_pages: int = 0,
    premium_pages: int = 0,
    audio_seconds: int = 0,
    video_seconds: int = 0,
    docling_refinement_pages: int = 0,
    agent_steps: int = 0,
) -> dict[str, Any]:
    """작업 승인 시점에 사용량을 포인트로 환산해 차감한다.
    잔액 부족 시 ValueError를 발생시킨다.
    반환값: 현재 사용량과 잔여 포인트, 차감 포인트를 포함한 상태.

    관리자는 구독 플랜 한도와 무관하게 무제한 사용 가능하다."""
    # 관리자 우회: 한도 초과 검사 없이 통계용 사용량만 누적 기록한다.
    if _is_admin_user(db, user):
        period_start = _get_period_start(user)
        usage = _get_usage_for_period(db, user.id, period_start)
        usage.basic_pages += basic_pages
        usage.premium_pages += premium_pages + docling_refinement_pages
        usage.media_seconds += audio_seconds + video_seconds
        db.commit()
        db.refresh(usage)
        return {
            "plan": user.subscription_plan or "free",
            "period_start": period_start.isoformat(),
            "points_balance": user.points_balance,
            "remaining": -1,  # 무제한
            "cost_points": 0,
            "used": {"basic_pages": usage.basic_pages, "premium_pages": usage.premium_pages, "media_seconds": usage.media_seconds},
        }

    if not is_subscription_active(user):
        raise ValueError("구독이 활성 상태가 아닙니다. 요금제를 선택해주세요.")

    plan = user.subscription_plan or "free"
    period_start = _get_period_start(user)
    cost = _calculate_credit_cost(
        db, basic_pages, premium_pages, audio_seconds, video_seconds, docling_refinement_pages, agent_steps
    )

    points_service.spend_points(db, user, cost, "구독 사용량 예약")

    usage = _get_usage_for_period(db, user.id, period_start)
    usage.basic_pages += basic_pages
    usage.premium_pages += premium_pages + docling_refinement_pages
    usage.media_seconds += audio_seconds + video_seconds
    db.commit()
    db.refresh(usage)

    return {
        "plan": plan,
        "period_start": period_start.isoformat(),
        "points_balance": user.points_balance,
        "remaining": user.points_balance,
        "cost_points": cost,
        "used": {"basic_pages": usage.basic_pages, "premium_pages": usage.premium_pages, "media_seconds": usage.media_seconds},
    }


def release_usage(
    db: Session,
    user: User,
    basic_pages: int = 0,
    premium_pages: int = 0,
    audio_seconds: int = 0,
    video_seconds: int = 0,
    docling_refinement_pages: int = 0,
    agent_steps: int = 0,
    period_start: datetime | None = None,
) -> None:
    """작업 실패/취소 등으로 예약된 사용량을 되돌린다.

    period_start를 지정하면 해당 구독 기간의 통계 사용량만 감소한다.
    미지정 시 현재 구독 기간 시작일을 사용한다."""
    cost = _calculate_credit_cost(
        db, basic_pages, premium_pages, audio_seconds, video_seconds, docling_refinement_pages, agent_steps
    )
    if cost > 0 and not _is_admin_user(db, user):
        points_service.refund_points(db, user, cost, "구독 사용량 환불")

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
    usage.premium_pages = max(0, usage.premium_pages - (premium_pages + docling_refinement_pages))
    usage.media_seconds = max(0, usage.media_seconds - (audio_seconds + video_seconds))
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
    """Paddle webhook으로 받은 구독 정보를 사용자 레코드에 동기화하고, 필요 시 월간 크레딧을 지급한다."""
    user.subscription_plan = plan
    user.subscription_status = status
    user.subscription_period_start = period_start
    user.subscription_period_end = period_end
    user.subscription_price_id = price_id
    user.paddle_subscription_id = paddle_subscription_id

    # 구독 기간이 변경되었거나 처음 동기화되는 경우, 월간 크레딧을 지급한다.
    # 이미 지급된 기간이면 grant_monthly_credits가 내부적으로 스킵한다.
    grant_monthly_credits(db, user)
    db.commit()
