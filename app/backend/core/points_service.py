#!/usr/bin/env python3
# [Flow: Step 1 (포인트 단가 조회) -> Step 2 (페이지별 비용 계산) -> Step 3 (포인트 충전/차감) -> Step 4 (트랜잭션 기록)]
import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy.orm import Session

from sqlalchemy import select

from .. import settings_store
from ..db.models import AdminUser, PointTransaction, User


def _get_rate(db: Session) -> dict:
    krw_page = int(settings_store.get_setting(db, "cost_per_page_krw") or "3")
    krw_image = int(settings_store.get_setting(db, "cost_per_image_krw") or "3")
    krw_audio_sec = int(settings_store.get_setting(db, "cost_per_audio_sec_krw") or "1")
    krw_video_sec = int(settings_store.get_setting(db, "cost_per_video_sec_krw") or "3")
    usd = Decimal(settings_store.get_setting(db, "cost_per_page_usd") or "0.002")
    rate = Decimal(settings_store.get_setting(db, "usd_to_krw_rate") or "1500")
    return {
        "krw_page": krw_page,
        "krw_image": krw_image,
        "krw_audio_sec": krw_audio_sec,
        "krw_video_sec": krw_video_sec,
        "usd": usd,
        "rate": rate,
    }


def calculate_cost(
    db: Session,
    pages: int = 0,
    image_count: int = 0,
    audio_seconds: int = 0,
    video_seconds: int = 0,
    docling_refinement_pages: int = 0,
) -> dict:
    """페이지/이미지/오디오/비디오/Docling 후처리 조합에 따른 포인트 비용을 계산합니다."""
    rate = _get_rate(db)
    krw_refinement_page = int(settings_store.get_setting(db, "cost_per_docling_refinement_page_krw") or "3")
    krw_cost = (
        pages * rate["krw_page"]
        + image_count * rate["krw_image"]
        + audio_seconds * rate["krw_audio_sec"]
        + video_seconds * rate["krw_video_sec"]
        + docling_refinement_pages * krw_refinement_page
    )
    total_media = pages + image_count + audio_seconds + video_seconds + docling_refinement_pages
    usd_cost = (total_media * rate["usd"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "pages": pages,
        "image_count": image_count,
        "audio_seconds": audio_seconds,
        "video_seconds": video_seconds,
        "docling_refinement_pages": docling_refinement_pages,
        "points": krw_cost,
        "krw": krw_cost,
        "usd": usd_cost,
    }


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
