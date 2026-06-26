#!/usr/bin/env python3
# [Flow: Step 1 (X-API-Key 헤더 읽기) -> Step 2 (hash 일치 및 활성화/만료/scope 검증) -> Step 3 (CurrentUser 형태로 반환)]
import hashlib
import secrets
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from sqlalchemy import select

from ..db.models import AdminUser, ApiKey, User
from ..db.session import get_db
from .supabase_auth import CurrentUser


def _constant_time_compare(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode(), b.encode())


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _get_key_prefix(key: str) -> str:
    return key[:8] if len(key) >= 8 else key


def get_current_api_key(
    request: Request,
    x_api_key: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> tuple[CurrentUser, ApiKey]:
    """API key를 검증하고 (CurrentUser, ApiKey) 튜플을 반환합니다."""
    raw_key = ""
    if x_api_key:
        raw_key = x_api_key.strip()
    elif authorization and authorization.lower().startswith("bearer "):
        raw_key = authorization[7:].strip()

    if not raw_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key가 필요합니다")

    key_hash = _hash_key(raw_key)
    prefix = _get_key_prefix(raw_key)

    api_key = (
        db.query(ApiKey)
        .filter(ApiKey.key_hash == key_hash, ApiKey.prefix == prefix, ApiKey.is_active.is_(True))
        .first()
    )
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="유효하지 않은 API key입니다")

    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="만료된 API key입니다")

    user = db.get(User, api_key.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key에 연결된 사용자가 없습니다")

    # admin_users 테이블에 등록된 계정은 관리자로 간주
    is_admin = user.is_admin or (
        db.execute(select(AdminUser).where(AdminUser.email == user.email)).scalar_one_or_none() is not None
    )

    api_key.last_used_at = datetime.now(timezone.utc)
    db.commit()

    return CurrentUser(str(user.id), user.email, is_admin, user.points_balance), api_key


def require_api_key(
    auth: tuple[CurrentUser, ApiKey] = Depends(get_current_api_key),
) -> CurrentUser:
    return auth[0]


def require_api_key_with_key(
    auth: tuple[CurrentUser, ApiKey] = Depends(get_current_api_key),
) -> tuple[CurrentUser, ApiKey]:
    return auth


def require_scope(scope: str):
    def _check(
        auth: tuple[CurrentUser, ApiKey] = Depends(get_current_api_key),
    ) -> CurrentUser:
        _, api_key = auth
        scopes = api_key.scopes or []
        if scope not in scopes and "admin" not in scopes:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"필요한 scope: {scope}")
        return auth[0]

    return _check


def create_api_key_record(user: User, name: str, scopes: list[str] | None = None, rate_limit_rpm: int = 60) -> tuple[ApiKey, str]:
    """새 API key를 생성하고 (ApiKey, 평문 key)를 반환합니다."""
    plain = f"chu_live_{secrets.token_urlsafe(32)}"
    key_hash = _hash_key(plain)
    prefix = _get_key_prefix(plain)
    api_key = ApiKey(
        user_id=user.id,
        name=name or "default",
        key_hash=key_hash,
        prefix=prefix,
        scopes=scopes or ["jobs:read", "jobs:write"],
        rate_limit_rpm=rate_limit_rpm,
    )
    db = Session.object_session(user)
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return api_key, plain
