#!/usr/bin/env python3
# [Flow: Step 1 (현재 사용자 인증) -> Step 2 (DB에서 잔액/관리자 여부 조회) -> Step 3 (활성 API key 기준 rate limit 조회) -> Step 4 (프론트에 반환)]
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth.supabase_auth import CurrentUser, get_current_user, SUPPORTED_LANGUAGES
from ..core.rate_limit import get_daily_spent_points
from ..db.models import ApiKey, User
from ..db.session import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LanguageUpdate(BaseModel):
    language: str = Field(..., min_length=2, max_length=10)


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
        "language": user.language or "en",
        **rate_limit,
    }


@router.patch("/language")
def update_language(
    payload: LanguageUpdate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="지원하지 않는 언어입니다")
    db_user = db.get(User, uuid.UUID(user.user_id))
    if db_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="사용자를 찾을 수 없습니다")
    db_user.language = payload.language
    db.commit()
    return {"language": db_user.language}
