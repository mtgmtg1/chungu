#!/usr/bin/env python3
# [Flow: Step 1 (dev_bypass_auth 설정 확인) -> Step 2 (설정된 dev 계정으로 Supabase Auth 로그인) -> Step 3 (Supabase 세션 반환)]
"""로컬 개발 전용 인증 bypass.

이 모듈은 프로덕션이 아닌 로컬 개발 환경에서만 사용합니다.
`DEV_BYPASS_AUTH=true`로 설정된 경우에만 `/api/dev/login` 엔드포인트가 활성화되며,
설정된 이메일/비밀번호로 실제 Supabase Auth에 로그인해 유효한 세션을 발급합니다.
"""
import logging

import httpx
from fastapi import APIRouter, HTTPException, status

from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dev", tags=["dev-auth"])


def _sign_in_with_password(email: str, password: str) -> dict:
    """[Flow: Step 1 (Supabase token endpoint 조립) -> Step 2 (email/password로 로그인 요청)
          -> Step 3 (access_token/refresh_token/user 추출) -> Step 4 (결과 반환)]

    Supabase Auth의 signInWithPassword API를 직접 호출하여 실제 세션을 얻는다.
    """
    base_url = settings.supabase_url.rstrip("/")
    url = f"{base_url}/auth/v1/token?grant_type=password"
    headers = {
        "apikey": settings.supabase_key,
        "Authorization": f"Bearer {settings.supabase_key}",
        "Content-Type": "application/json",
    }
    payload = {"email": email, "password": password}
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=headers, json=payload)
    if resp.status_code != 200:
        logger.error(f"[dev_auth] Supabase login failed: {resp.status_code} {resp.text}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Supabase login failed: {resp.status_code} {resp.text}",
        )
    return resp.json()


@router.post("/login")
def dev_login():
    """로컬 개발 전용: 설정된 계정으로 실제 Supabase Auth에 로그인해 세션을 반환합니다."""
    if not settings.dev_bypass_auth:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dev auth bypass is not enabled.",
        )

    if not settings.dev_bypass_email or not settings.dev_bypass_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DEV_BYPASS_AUTH_EMAIL and DEV_BYPASS_AUTH_PASSWORD are not configured.",
        )

    session = _sign_in_with_password(settings.dev_bypass_email, settings.dev_bypass_password)
    return {
        "access_token": session["access_token"],
        "refresh_token": session["refresh_token"],
        "token_type": session.get("token_type", "bearer"),
        "expires_in": session.get("expires_in", 3600),
        "user": session["user"],
    }
