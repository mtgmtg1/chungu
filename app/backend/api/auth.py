#!/usr/bin/env python3
# [Flow: Step 1 (현재 사용자 인증) -> Step 2 (DB에서 잔액/관리자 여부 조회) -> Step 3 (프론트에 반환)]
from fastapi import APIRouter, Depends

from ..auth.supabase_auth import CurrentUser, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)):
    return {
        "user_id": user.user_id,
        "email": user.email,
        "points_balance": user.points_balance,
        "is_admin": user.is_admin,
    }
