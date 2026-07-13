#!/usr/bin/env python3
# [Flow: Step 1 (AI 백엔드 시크릿 검증) -> Step 2 (요청 사용자 조회) -> Step 3 (steps * 단가만큼 포인트 차감) -> Step 4 (트랜잭션 결과 반환)]
# AI 백엔드(Vercel AI SDK 에이전트)에서 에이전트 스텝 사용량을 보고하고 포인트를 차감하는 엔드포인트.
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...config import settings
from ...core import points_service
from ...db.models import User
from ...db.session import get_db

router = APIRouter(prefix="/agent", tags=["agent"])


def _require_ai_backend_secret(
    request: Request,
    x_ai_backend_secret: str | None = Header(None, alias="X-AI-Backend-Secret"),
) -> None:
    """AI 백엔드에서만 호출할 수 있도록 공유 비밀을 검증한다.

    환경변수 AI_BACKEND_SECRET가 비어 있으면 보안상 차단한다."""
    expected = settings.ai_backend_secret
    if not expected:
        raise HTTPException(status_code=500, detail="AI_BACKEND_SECRET is not configured")
    if not x_ai_backend_secret or x_ai_backend_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid AI backend secret")


class SpendAgentStepsRequest(BaseModel):
    """POST /agent/steps 요청 본문."""

    user_id: str = Field(..., description="포인트를 차감할 사용자 UUID 문자열")
    steps: int = Field(..., ge=1, description="사용한 에이전트 스텝 수")
    description: str | None = Field(None, description="트랜잭션 설명 (기본값: 'AI 에이전트 스텝 사용')")


class SpendAgentStepsResponse(BaseModel):
    """POST /agent/steps 응답 본문."""

    user_id: str
    steps: int
    cost_points: int
    points_balance: int


@router.post("/steps", response_model=SpendAgentStepsResponse)
def spend_agent_steps(
    body: SpendAgentStepsRequest,
    db: Session = Depends(get_db),
    _secret: None = Depends(_require_ai_backend_secret),
):
    """AI 에이전트가 사용한 스텝 수만큼 사용자의 포인트를 차감한다.

    AI 백엔드는 대화/에이전트 실행 종료 시 총 스텝 수를 집계해 이 엔드포인트를 한 번 호출한다.
    """
    db_user = db.get(User, body.user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    rate = points_service._get_rate(db)
    cost_points = body.steps * rate["agent_step"]
    description = body.description or "AI 에이전트 스텝 사용"
    try:
        points_service.spend_points(db, db_user, cost_points, description)
    except ValueError as e:
        raise HTTPException(status_code=402, detail=str(e))

    return SpendAgentStepsResponse(
        user_id=str(db_user.id),
        steps=body.steps,
        cost_points=cost_points,
        points_balance=db_user.points_balance,
    )
