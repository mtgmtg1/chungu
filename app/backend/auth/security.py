#!/usr/bin/env python3
# [Flow: Step 1 (비밀번호 해시/검증) -> Step 2 (JWT 발급/검증) -> Step 3 (관리자 가드 의존성)]
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Cookie, HTTPException, status
from passlib.context import CryptContext

from ..config import settings

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGO = "HS256"
SESSION_HOURS = 12
COOKIE_NAME = "chungu_admin"


def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)


def create_token(email: str) -> str:
    payload = {
        "sub": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGO)


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGO])
        return payload.get("sub")
    except Exception:  # noqa: BLE001
        return None


def require_admin(chungu_admin: str | None = Cookie(default=None)) -> str:
    """관리자 전용 라우트 가드: 유효 세션 쿠키가 없으면 401."""
    if not chungu_admin:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인이 필요합니다")
    email = decode_token(chungu_admin)
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="세션이 만료되었습니다")
    return email
