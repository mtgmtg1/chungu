#!/usr/bin/env python3
# [Flow: Step 1 (milli-USD 단가 조회) -> Step 2 (모델별 비용 계산) -> Step 3 (무료 한도 적용) -> Step 4 (크레딧 충전/차감) -> Step 5 (자동 충전 트리거) -> Step 6 (트랜잭션 기록)]
import logging
from datetime import date

from sqlalchemy.orm import Session

from sqlalchemy import select

from .. import settings_store
from ..db.models import AdminUser, DailyUsage, PointTransaction, User

logger = logging.getLogger(__name__)


def _get_rate(db: Session) -> dict:
    """milli-USD 단가를 설정에서 조회한다. 기존 KRW 설정 키를 재사용하되 값은 milli-USD."""
    basic_page = int(settings_store.get_setting(db, "cost_basic_page_krw") or "1")
    premium_page = int(settings_store.get_setting(db, "cost_premium_page_krw") or "5")
    premium_audio_sec = int(settings_store.get_setting(db, "cost_premium_audio_sec_krw") or "1")
    premium_video_sec = int(settings_store.get_setting(db, "cost_premium_video_sec_krw") or "5")
    free_daily = int(settings_store.get_setting(db, "free_daily_pages_basic") or "100")
    return {
        "basic_page": basic_page,
        "premium_page": premium_page,
        "premium_audio_sec": premium_audio_sec,
        "premium_video_sec": premium_video_sec,
        "free_daily": free_daily,
    }


def get_daily_free_remaining(db: Session, user_id) -> int:
    """오늘 기본모델로 사용한 페이지 수를 조회하고 잔여 무료 한도를 반환한다."""
    rate = _get_rate(db)
    today = date.today()
    row = db.execute(
        select(DailyUsage).where(DailyUsage.user_id == user_id, DailyUsage.date == today)
    ).scalar_one_or_none()
    used = row.pages_used if row else 0
    return max(0, rate["free_daily"] - used)


def calculate_cost(
    db: Session,
    pages: int = 0,
    image_count: int = 0,
    audio_seconds: int = 0,
    video_seconds: int = 0,
    docling_refinement_pages: int = 0,
    ocr_model: str = "premium",
    user_id=None,
) -> dict:
    """모델별 차등 과금을 적용하여 milli-USD 비용을 계산합니다.

    - basic: 이미지/문서 1md/페이지, 하루 100페이지 무료 (user_id 필요)
    - premium: 이미지/문서 5md/페이지, 오디오 1md/초, 비디오 5md/초
    """
    rate = _get_rate(db)
    total_pages = pages + image_count

    if ocr_model == "basic":
        free_remaining = 0
        if user_id is not None:
            free_remaining = get_daily_free_remaining(db, user_id)
        free_pages = min(total_pages, free_remaining)
        chargeable_pages = total_pages - free_pages
        milli_usd_cost = chargeable_pages * rate["basic_page"]
        free_pages_used = free_pages
    else:
        refinement_rate = int(settings_store.get_setting(db, "cost_per_docling_refinement_page_krw") or "3")
        milli_usd_cost = (
            total_pages * rate["premium_page"]
            + audio_seconds * rate["premium_audio_sec"]
            + video_seconds * rate["premium_video_sec"]
            + docling_refinement_pages * refinement_rate
        )
        free_pages_used = 0

    usd_str = f"${milli_usd_cost / 1000:.2f}"
    return {
        "pages": pages,
        "image_count": image_count,
        "audio_seconds": audio_seconds,
        "video_seconds": video_seconds,
        "docling_refinement_pages": docling_refinement_pages,
        "ocr_model": ocr_model,
        "free_pages_used": free_pages_used,
        "points": milli_usd_cost,
        "usd": usd_str,
    }


def record_daily_usage(db: Session, user_id, pages: int) -> None:
    """기본모델 사용 페이지 수를 DailyUsage 테이블에 누적한다."""
    if pages <= 0:
        return
    today = date.today()
    row = db.execute(
        select(DailyUsage).where(DailyUsage.user_id == user_id, DailyUsage.date == today)
    ).scalar_one_or_none()
    if row:
        row.pages_used += pages
    else:
        db.add(DailyUsage(user_id=user_id, date=today, pages_used=pages))
    db.commit()


def get_charge_limits() -> dict:
    """충전 한도를 반환한다 (자유 금액 방식)."""
    return {"min_amount": 5, "max_amount": 500}


def charge_points(db: Session, user: User, points: int, description: str) -> PointTransaction:
    """포인트를 충전하고 트랜잭션을 기록합니다."""
    user.points_balance += points
    tx = PointTransaction(
        user_id=user.id,
        type="charge",
        amount=points,
        balance_after=user.points_balance,
        description=description,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx


def spend_points(db: Session, user: User, points: int, description: str) -> PointTransaction:
    """milli-USD 크레딧을 차감하고 트랜잭션을 기록합니다. 잔액 부족 시 ValueError.
    관리자는 잔액 체크/차감 없이 사용 가능합니다.
    차감 후 잔액이 자동 충전 임계값 이하이고 자동 충전이 활성화된 경우 트리거한다."""
    # [Flow: Step 1 (관리자 확인) -> Step 2 (잔액 차감) -> Step 3 (자동 충전 트리거)]
    is_admin = user.is_admin or (
        db.execute(select(AdminUser).where(AdminUser.email == user.email)).scalar_one_or_none() is not None
    )
    if is_admin:
        tx = PointTransaction(
            user_id=user.id,
            type="spend",
            amount=0,
            balance_after=user.points_balance,
            description=f"[관리자 무료] {description}",
        )
        db.add(tx)
        db.commit()
        db.refresh(tx)
        return tx

    if user.points_balance < points:
        raise ValueError(f"크레딧이 부족합니다 (잔액: {user.points_balance}md, 필요: {points}md)")
    user.points_balance -= points
    tx = PointTransaction(
        user_id=user.id,
        type="spend",
        amount=-points,
        balance_after=user.points_balance,
        description=description,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)

    _maybe_trigger_auto_recharge(db, user)
    return tx


def refund_points(db: Session, user: User, points: int, description: str) -> PointTransaction:
    user.points_balance += points
    tx = PointTransaction(
        user_id=user.id,
        type="refund",
        amount=points,
        balance_after=user.points_balance,
        description=description,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx


def _maybe_trigger_auto_recharge(db: Session, user: User) -> None:
    """잔액이 자동 충전 임계값 이하이고 자동 충전이 활성화된 경우 트리거한다.
    순환 import 방지를 위해 payments 모듈을 지연 import한다."""
    # [Flow: Step 1 (자동 충전 활성화 확인) -> Step 2 (잔액 ≤ 임계값 확인) -> Step 3 (trigger_auto_recharge 호출)]
    if not getattr(user, "auto_recharge_enabled", False):
        return
    if not getattr(user, "paddle_customer_id", None):
        return
    if user.points_balance > getattr(user, "auto_recharge_threshold", 2000):
        return
    if user.auto_recharge_retries >= 3:
        return

    try:
        from ..api import payments as payments_api
        payments_api.trigger_auto_recharge(db, user)
    except Exception as e:
        logger.warning(f"자동 충전 트리거 실패 (user={user.id}): {e}")
