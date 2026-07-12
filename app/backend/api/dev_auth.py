#!/usr/bin/env python3
# [Flow: Step 1 (dev_bypass_auth 설정 확인) -> Step 2 (설정된 dev 계정 정보로 로컬 JWT 발급) -> Step 3 (Supabase 호환 세션 반환)]
"""로컬 개발 전용 인증 bypass.

이 모듈은 프로덕션이 아닌 로컬 개발 환경에서만 사용합니다.
`DEV_BYPASS_AUTH=true`로 설정된 경우에만 `/api/dev/login` 엔드포인트가 활성화되며,
실제 Supabase Auth가 없을 때도 `SUPABASE_JWT_SECRET`으로 서명된 JWT 세션을 발급합니다.
"""
import logging
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, HTTPException, status

from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dev", tags=["dev-auth"])

ALGO = "HS256"


def _build_token_payload(audience: str = "authenticated") -> dict:
    """[Flow: Step 1 (현재 시간 + 만료 시간 계산) -> Step 2 (Supabase 호환 JWT payload 구성)]

    Supabase JWT와 호환되는 payload를 생성한다. `get_current_user`가 검증하는
    `sub`, `email`, `aud`, `role` 클레임을 포함한다.
    """
    now = datetime.now(timezone.utc)
    return {
        "iss": "supabase-chungu",
        "sub": settings.dev_bypass_user_id,
        "aud": audience,
        "email": settings.dev_bypass_email,
        "role": "authenticated",
        "iat": now,
        "exp": now + timedelta(hours=24),
    }


@router.post("/login")
def dev_login():
    """로컬 개발 전용: Supabase Auth 없이 `SUPABASE_JWT_SECRET`으로 세션을 발급합니다."""
    if not settings.dev_bypass_auth:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dev auth bypass is not enabled.",
        )

    if not settings.dev_bypass_email or not settings.dev_bypass_user_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DEV_BYPASS_EMAIL and DEV_BYPASS_USER_ID are not configured.",
        )

    logger.info("[dev_auth] 로컬 dev bypass 세션 발급: user_id=%s", settings.dev_bypass_user_id)
    access_payload = _build_token_payload("authenticated")
    refresh_payload = _build_token_payload("refresh")
    access_token = jwt.encode(access_payload, settings.supabase_jwt_secret, algorithm=ALGO)
    refresh_token = jwt.encode(refresh_payload, settings.supabase_jwt_secret, algorithm=ALGO)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 86400,
        "user": {
            "id": settings.dev_bypass_user_id,
            "email": settings.dev_bypass_email,
            "role": "authenticated",
        },
    }
