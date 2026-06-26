#!/usr/bin/env python3
# [Flow: Step 1 (현재 사용자 인증) -> Step 2 (DB에서 잔액/관리자 여부 조회) -> Step 3 (활성 API key 기준 rate limit 조회) -> Step 4 (프론트에 반환)]
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth.supabase_auth import CurrentUser, get_current_user
from ..core.rate_limit import get_daily_spent_points
from ..db.models import ApiKey
from ..db.session import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    active_key = (
        db.query(ApiKey)
        .filter(ApiKey.user_id == uuid.UUID(user.user_id), ApiKey.is_active.is_(True))
        .order_by(ApiKey.created_at.asc())
        .first()
    )
    rate_limit = {
        "rate_limit_rpm": active_key.rate_limit_rpm if active_key else 60,
        "daily_quota": active_key.daily_quota if active_key else None,
        "daily_spent_points": get_daily_spent_points(active_key.id) if active_key else 0,
    }
    return {
        "user_id": user.user_id,
        "email": user.email,
        "points_balance": user.points_balance,
        "is_admin": user.is_admin,
        **rate_limit,
    }
