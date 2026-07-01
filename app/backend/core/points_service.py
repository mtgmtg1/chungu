#!/usr/bin/env python3
# [Flow: Step 1 (포인트 단가 조회) -> Step 2 (모델별 비용 계산) -> Step 3 (무료 한도 적용) -> Step 4 (포인트 충전/차감) -> Step 5 (트랜잭션 기록)]
import json
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy.orm import Session

from sqlalchemy import select

from .. import settings_store
from ..db.models import AdminUser, DailyUsage, PointTransaction, User


def _get_rate(db: Session) -> dict:
    krw_basic_page = int(settings_store.get_setting(db, "cost_basic_page_krw") or "1")
    krw_premium_page = int(settings_store.get_setting(db, "cost_premium_page_krw") or "5")
    krw_premium_audio_sec = int(settings_store.get_setting(db, "cost_premium_audio_sec_krw") or "1")
    krw_premium_video_sec = int(settings_store.get_setting(db, "cost_premium_video_sec_krw") or "5")
    free_daily = int(settings_store.get_setting(db, "free_daily_pages_basic") or "100")
    usd = Decimal(settings_store.get_setting(db, "cost_per_page_usd") or "0.002")
    rate = Decimal(settings_store.get_setting(db, "usd_to_krw_rate") or "1500")
    return {
        "krw_basic_page": krw_basic_page,
        "krw_premium_page": krw_premium_page,
        "krw_premium_audio_sec": krw_premium_audio_sec,
        "krw_premium_video_sec": krw_premium_video_sec,
        "free_daily": free_daily,
        "usd": usd,
        "rate": rate,
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
    """모델별 차등 과금을 적용하여 포인트 비용을 계산합니다.

    - basic: 이미지/문서 1원/페이지, 하루 100페이지 무료 (user_id 필요)
    - premium: 이미지/문서 5원/페이지, 오디오 1원/초, 비디오 5원/초
    """
    rate = _get_rate(db)
    total_pages = pages + image_count

    if ocr_model == "basic":
        free_remaining = 0
        if user_id is not None:
            free_remaining = get_daily_free_remaining(db, user_id)
        free_pages = min(total_pages, free_remaining)
        chargeable_pages = total_pages - free_pages
        krw_cost = chargeable_pages * rate["krw_basic_page"]
        free_pages_used = free_pages
    else:
        krw_refinement_page = int(settings_store.get_setting(db, "cost_per_docling_refinement_page_krw") or "3")
        krw_cost = (
            total_pages * rate["krw_premium_page"]
            + audio_seconds * rate["krw_premium_audio_sec"]
            + video_seconds * rate["krw_premium_video_sec"]
            + docling_refinement_pages * krw_refinement_page
        )
        free_pages_used = 0

    total_media = total_pages + audio_seconds + video_seconds + docling_refinement_pages
    usd_cost = (total_media * rate["usd"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "pages": pages,
        "image_count": image_count,
        "audio_seconds": audio_seconds,
        "video_seconds": video_seconds,
        "docling_refinement_pages": docling_refinement_pages,
        "ocr_model": ocr_model,
        "free_pages_used": free_pages_used,
        "points": krw_cost,
        "krw": krw_cost,
        "usd": usd_cost,
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


def get_point_packages(db: Session) -> list[dict[str, Any]]:
    raw = settings_store.get_setting(db, "point_packages") or "[]"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


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
    """포인트를 차감하고 트랜잭션을 기록합니다. 잔액 부족 시 ValueError.
    관리자는 잔액 체크/차감 없이 사용 가능합니다."""
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
        raise ValueError(f"포인트가 부족합니다 (잔액: {user.points_balance}, 필요: {points})")
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
