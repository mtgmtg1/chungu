#!/usr/bin/env python3
# [Flow: Step 1 (API key로 사용자 식별) -> Step 2 (잔액/사용량/단가 조회) -> Step 3 (거래 내역 반환)]
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...auth.api_key_auth import require_api_key_or_session
from ...auth.supabase_auth import CurrentUser
from ...core import points_service, subscription_service
from ...core.rate_limit import enforce_rate_limit, get_daily_spent_points
from ...db.models import ApiKey, ApiUsage, Payment, PointTransaction, User
from ...db.session import get_db
from ... import settings_store

router = APIRouter(prefix="/account", tags=["account"])


@router.get("")
def get_account(
    request: Request,
    auth: tuple[CurrentUser, ApiKey | None] = Depends(require_api_key_or_session),
    db: Session = Depends(get_db),
):
    """개발자 계정 정보, 잔액, 오늘 사용량을 반환합니다."""
    user, api_key = auth
    if api_key:
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
        } if api_key else {},
        "today_usage": {
            "points_spent": int(today_spent),
            "requests": db.query(ApiUsage).filter(ApiUsage.user_id == db_user_id, ApiUsage.created_at >= today_start).count(),
        },
    }


@router.get("/pricing")
def get_pricing(
    request: Request,
    auth: tuple[CurrentUser, ApiKey | None] = Depends(require_api_key_or_session),
    db: Session = Depends(get_db),
):
    user, api_key = auth
    if api_key:
        enforce_rate_limit(request, api_key.id, api_key.rate_limit_rpm)
    """현재 크레딧 단가를 반환한다 (milli-USD)."""
    limits = points_service.get_charge_limits()
    return {
        "currency": "USD",
        "charge_limits": {
            "min_amount": limits["min_amount"],
            "max_amount": limits["max_amount"],
        },
        "rates": {
            "basic_page_milli_usd": int(settings_store.get_setting(db, "cost_basic_page_krw") or "1"),
            "premium_page_milli_usd": int(settings_store.get_setting(db, "cost_premium_page_krw") or "5"),
            "premium_audio_sec_milli_usd": int(settings_store.get_setting(db, "cost_premium_audio_sec_krw") or "1"),
            "premium_video_sec_milli_usd": int(settings_store.get_setting(db, "cost_premium_video_sec_krw") or "10"),
            "agent_step_milli_usd": int(settings_store.get_setting(db, "cost_agent_step_krw") or "1"),
            "docling_refinement_page_milli_usd": int(settings_store.get_setting(db, "cost_per_docling_refinement_page_krw") or "3"),
        },
    }


@router.get("/transactions")
def list_transactions(
    request: Request,
    auth: tuple[CurrentUser, ApiKey | None] = Depends(require_api_key_or_session),
    db: Session = Depends(get_db),
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    """포인트 충전/차감 내역을 반환합니다."""
    user, api_key = auth
    if api_key:
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
    auth: tuple[CurrentUser, ApiKey | None] = Depends(require_api_key_or_session),
    db: Session = Depends(get_db),
    days: Annotated[int, Query(ge=1, le=90)] = 30,
):
    """최근 N일간 일별 API 사용량을 집계합니다."""
    user, api_key = auth
    if api_key:
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
    auth: tuple[CurrentUser, ApiKey | None] = Depends(require_api_key_or_session),
    db: Session = Depends(get_db),
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    """결제 내역을 반환합니다."""
    user, api_key = auth
    if api_key:
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


@router.get("/subscription")
def get_subscription(
    request: Request,
    auth: tuple[CurrentUser, ApiKey | None] = Depends(require_api_key_or_session),
    db: Session = Depends(get_db),
):
    """현재 사용자의 구독 상태와 잔여 한도를 반환한다.

    [Flow: Step 1 (API key/세션 인증) -> Step 2 (사용자 조회) -> Step 3 (subscription_service에서 상태 집계)]

    구독 플랜(free/pro/max), 월간 한도, 사용량, 갱신일 등을 반환한다.
    """
    user, api_key = auth
    if api_key:
        enforce_rate_limit(request, api_key.id, api_key.rate_limit_rpm)

    db_user = db.get(User, uuid.UUID(user.user_id))
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return subscription_service.get_subscription_status(db, db_user)
