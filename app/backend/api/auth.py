#!/usr/bin/env python3
# [Flow: Step 1 (현재 사용자 인증) -> Step 2 (DB에서 잔액/관리자 여부 조회) -> Step 3 (프론트에 반환)]
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth.supabase_auth import CurrentUser, get_current_user
from ..db.models import User
from ..db.session import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    db_user = db.get(User, uuid.UUID(user.user_id))
    balance = db_user.points_balance if db_user else 0
    is_admin = db_user.is_admin if db_user else False
    return {
        "user_id": user.user_id,
        "email": user.email,
        "points_balance": balance,
        "is_admin": is_admin,
    }
