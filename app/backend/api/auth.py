#!/usr/bin/env python3
# [Flow: Step 1 (현재 사용자 인증) -> Step 2 (DB에서 잔액/관리자 여부 조회) -> Step 3 (활성 API key 기준 rate limit 조회) -> Step 4 (프론트에 반환)]
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth.api_key_auth import require_api_key_or_session
from ..auth.supabase_auth import CurrentUser, get_current_user, SUPPORTED_LANGUAGES
from ..core import subscription_service
from ..core.rate_limit import get_daily_spent_points
from ..db.models import ApiKey, User
from ..db.session import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LanguageUpdate(BaseModel):
    language: str = Field(..., min_length=2, max_length=10)


class AISettingsUpdate(BaseModel):
    approval_mode: str | None = Field(default=None, pattern="^(ask|always)$")
    agent_max_steps: int | None = Field(default=None, ge=1, le=1000)


@router.get("/me")
def me(
    auth: tuple[CurrentUser, ApiKey | None] = Depends(require_api_key_or_session),
    db: Session = Depends(get_db),
):
    user, _api_key = auth
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
    # [Flow: Step 1 (CurrentUser에는 subscription_plan/status가 없으므로 DB에서 조회) -> Step 2 (없으면 기본값 폴백)]
    db_user = db.get(User, uuid.UUID(user.user_id))
    return {
        "user_id": user.user_id,
        "email": user.email,
        "points_balance": db_user.points_balance if db_user else user.points_balance,
        "subscription_plan": db_user.subscription_plan if db_user else "free",
        "subscription_status": db_user.subscription_status if db_user else "inactive",
        "is_admin": user.is_admin,
        "language": user.language or "en",
        "ai_tool_approval_mode": db_user.ai_tool_approval_mode if db_user else "ask",
        "agent_max_steps": db_user.agent_max_steps if db_user else 100,
        **rate_limit,
    }


@router.patch("/language")
def update_language(
    payload: LanguageUpdate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported language")
    db_user = db.get(User, uuid.UUID(user.user_id))
    if db_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    db_user.language = payload.language
    db.commit()
    return {"language": db_user.language}


@router.patch("/ai-settings")
def update_ai_settings(
    payload: AISettingsUpdate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI 에이전트 설정(도구 승인 모드, 최대 step 수)을 업데이트한다.

    payload에 포함된 필드만 업데이트한다. 둘 다 생략하면 400 오류를 반환한다.
    """
    db_user = db.get(User, uuid.UUID(user.user_id))
    if db_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if payload.approval_mode is None and payload.agent_max_steps is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="approval_mode or agent_max_steps is required")

    if payload.approval_mode is not None:
        db_user.ai_tool_approval_mode = payload.approval_mode
    if payload.agent_max_steps is not None:
        db_user.agent_max_steps = payload.agent_max_steps

    db.commit()
    return {
        "ai_tool_approval_mode": db_user.ai_tool_approval_mode,
        "agent_max_steps": db_user.agent_max_steps,
    }

