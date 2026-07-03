#!/usr/bin/env python3
# [Flow: Step 1 (dev_bypass_auth 설정 확인) -> Step 2 (고정 dev 사용자 조회/생성) -> Step 3 (Supabase JWT 발급) -> Step 4 (세션 정보 반환)]
"""로컬 개발 전용 인증 bypass.

이 모듈은 프로덕션이 아닌 로컬 개발 환경에서만 사용됩니다.
`DEV_BYPASS_AUTH=true`로 설정된 경우에만 `/api/dev-login` 엔드포인트가 활성화되며,
실제 Supabase Auth를 거치지 않고 유효한 access token을 발급합니다.
"""
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import User
from ..db.session import SessionLocal

router = APIRouter(prefix="/api/dev", tags=["dev-auth"])

ALGO = "HS256"


def _ensure_dev_user() -> User:
    """고정 dev 사용자를 local DB에 생성/조회합니다."""
    db = SessionLocal()
    try:
        uid = settings.dev_bypass_user_id
        user = db.execute(select(User).where(User.id == uid)).scalar_one_or_none()
        if user is None:
            user = User(
                id=uid,
                email=settings.dev_bypass_email,
                points_balance=10000,  # 개발 테스트용 잔액 (10 USD)
                language="ko",
                is_admin=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return user
    finally:
        db.close()


def _mint_dev_token(user: User) -> str:
    """Supabase JWT secret으로 개발용 access token을 생성합니다."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": "authenticated",
        "aud": "authenticated",
        "iat": now,
        "exp": now + timedelta(days=365),
    }
    return jwt.encode(payload, settings.supabase_jwt_secret, algorithm=ALGO)


@router.post("/login")
def dev_login():
    """로컬 개발 전용: 설정이 활성화된 경우 유효한 access token을 반환합니다."""
    if not settings.dev_bypass_auth:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dev auth bypass is not enabled.",
        )

    if not settings.supabase_jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SUPABASE_JWT_SECRET is not configured.",
        )

    user = _ensure_dev_user()
    access_token = _mint_dev_token(user)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": 365 * 24 * 60 * 60,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "role": "authenticated",
        },
    }
