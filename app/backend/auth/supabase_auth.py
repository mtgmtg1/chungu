#!/usr/bin/env python3
# [Flow: Step 1 (Authorization 헤더에서 JWT 추출) -> Step 2 (Supabase JWT 검증) -> Step 3 (User 레코드 조회/생성) -> Step 4 (FastAPI 의존성 반환)]
import uuid
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import User
from ..db.session import get_db


class CurrentUser:
    """인증된 사용자 정보."""

    def __init__(self, user_id: str, email: str, is_admin: bool, points_balance: int):
        self.user_id = user_id
        self.email = email
        self.is_admin = is_admin
        self.points_balance = points_balance

    def __repr__(self) -> str:
        return f"CurrentUser({self.email}, admin={self.is_admin})"


ALGO = "HS256"


def _decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.supabase_jwt_secret, algorithms=[ALGO], audience="authenticated")
    except Exception:  # noqa: BLE001
        return None


def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> CurrentUser:
    """Supabase access_token을 검증하고 public.users 레코드를 반환합니다."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인이 필요합니다")

    token = authorization[7:].strip()
    payload = _decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="세션이 만료되었거나 유효하지 않습니다")

    user_id = payload.get("sub") or payload.get("user_id")
    email = payload.get("email") or ""
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="토큰에 사용자 정보가 없습니다")

    try:
        uid = uuid.UUID(str(user_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="잘못된 사용자 ID입니다") from exc

    user = db.execute(select(User).where(User.id == uid)).scalar_one_or_none()
    if user is None:
        # auth.users 트리거가 아직 실행되지 않았을 수 있음: 보수적으로 생성
        user = User(id=uid, email=email, points_balance=0, is_admin=False)
        db.add(user)
        db.commit()
        db.refresh(user)

    return CurrentUser(str(user.id), user.email, user.is_admin, user.points_balance)


def get_current_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="관리자 권한이 필요합니다")
    return user


def require_user_or_admin(
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> CurrentUser | None:
    """선택적 인증: 토큰이 없으면 None, 있으면 검증."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return get_current_user(authorization, db)
