#!/usr/bin/env python3
# [Flow: Step 1 (API key로 사용자 식별) -> Step 2 (잔액/사용량/단가 조회) -> Step 3 (거래 내역 반환)]
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...auth.api_key_auth import require_api_key_with_key
from ...auth.supabase_auth import CurrentUser
from ...core import points_service
from ...core.rate_limit import enforce_rate_limit, get_daily_spent_points
from ...db.models import ApiKey, ApiUsage, Payment, PointTransaction
from ...db.session import get_db
from ... import settings_store

router = APIRouter(prefix="/account", tags=["account"])


@router.get("")
def get_account(
    request: Request,
    auth: tuple[CurrentUser, ApiKey] = Depends(require_api_key_with_key),
    db: Session = Depends(get_db),
):
    """개발자 계정 정보, 잔액, 오늘 사용량을 반환합니다."""
    user, api_key = auth
    enforce_rate_limit(request, api_key.id, api_key.rate_limit_rpm)
    db_user_id = uuid.UUID(user.user_id)

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_spent = (
        db.query(func.sum(ApiUsage.points_spent))
        .filter(ApiUsage.user_id == db_user_id, ApiUsage.created_at >= today_start)
        .scalar()
        or 0
    )

    return {
        "user_id": user.user_id,
        "email": user.email,
        "points_balance": user.points_balance,
        "api_key": {
            "id": api_key.id,
            "name": api_key.name,
            "prefix": api_key.prefix,
            "scopes": api_key.scopes,
            "rate_limit_rpm": api_key.rate_limit_rpm,
            "daily_quota": api_key.daily_quota,
            "daily_spent_points": get_daily_spent_points(api_key.id),
        },
        "today_usage": {
            "points_spent": int(today_spent),
            "requests": db.query(ApiUsage).filter(ApiUsage.user_id == db_user_id, ApiUsage.created_at >= today_start).count(),
        },
    }


@router.get("/pricing")
def get_pricing(
    request: Request,
    auth: tuple[CurrentUser, ApiKey] = Depends(require_api_key_with_key),
    db: Session = Depends(get_db),
):
    user, api_key = auth
    enforce_rate_limit(request, api_key.id, api_key.rate_limit_rpm)
    """현재 판매 중인 포인트 패키지 및 단가를 반환합니다."""
    return {
        "packages": points_service.get_point_packages(db),
        "rates": {
            "krw_per_page": int(settings_store.get_setting(db, "cost_per_page_krw") or "3"),
            "krw_per_image": int(settings_store.get_setting(db, "cost_per_image_krw") or "3"),
            "krw_per_audio_second": int(settings_store.get_setting(db, "cost_per_audio_sec_krw") or "1"),
            "krw_per_video_second": int(settings_store.get_setting(db, "cost_per_video_sec_krw") or "3"),
            "usd_per_point": settings_store.get_setting(db, "cost_per_page_usd") or "0.002",
        },
    }


@router.get("/transactions")
def list_transactions(
    request: Request,
    auth: tuple[CurrentUser, ApiKey] = Depends(require_api_key_with_key),
    db: Session = Depends(get_db),
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    """포인트 충전/차감 내역을 반환합니다."""
    user, api_key = auth
    enforce_rate_limit(request, api_key.id, api_key.rate_limit_rpm)
    rows = (
        db.query(PointTransaction)
        .filter(PointTransaction.user_id == uuid.UUID(user.user_id))
        .order_by(PointTransaction.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": t.id,
            "type": t.type,
            "amount": t.amount,
            "balance_after": t.balance_after,
            "description": t.description,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in rows
    ]


@router.get("/usage")
def usage_summary(
    request: Request,
    auth: tuple[CurrentUser, ApiKey] = Depends(require_api_key_with_key),
    db: Session = Depends(get_db),
    days: Annotated[int, Query(ge=1, le=90)] = 30,
):
    """최근 N일간 일별 API 사용량을 집계합니다."""
    user, api_key = auth
    enforce_rate_limit(request, api_key.id, api_key.rate_limit_rpm)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(
            func.date_trunc("day", ApiUsage.created_at).label("day"),
            func.count().label("requests"),
            func.sum(ApiUsage.points_spent).label("points"),
        )
        .filter(ApiUsage.user_id == uuid.UUID(user.user_id), ApiUsage.created_at >= since)
        .group_by("day")
        .order_by("day")
        .all()
    )
    return [
        {
            "day": r.day.isoformat() if r.day else None,
            "requests": r.requests,
            "points_spent": int(r.points or 0),
        }
        for r in rows
    ]


@router.get("/payments")
def list_payments(
    request: Request,
    auth: tuple[CurrentUser, ApiKey] = Depends(require_api_key_with_key),
    db: Session = Depends(get_db),
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    """결제 내역을 반환합니다."""
    user, api_key = auth
    enforce_rate_limit(request, api_key.id, api_key.rate_limit_rpm)
    rows = (
        db.query(Payment)
        .filter(Payment.user_id == uuid.UUID(user.user_id))
        .order_by(Payment.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": p.id,
            "provider": p.provider,
            "currency": p.currency,
            "amount": str(p.amount),
            "points_added": p.points_added,
            "status": p.status,
            "external_id": p.external_id,
            "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in rows
    ]
