#!/usr/bin/env python3
# [Flow: Step 1 (API key CRUD) -> Step 2 (생성 시 평문 한 번 반환) -> Step 3 (활성/비활성 관리)]
import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...auth.api_key_auth import create_api_key_record, require_api_key_with_key
from ...auth.supabase_auth import CurrentUser, get_current_user
from ...db.models import ApiKey, User
from ...db.session import get_db

router = APIRouter(prefix="/keys", tags=["api-keys"])


@router.post("")
def create_key(
    request: Request,
    name: Annotated[str, Body()] = "",
    scopes: Annotated[list[str] | None, Body()] = None,
    rate_limit_rpm: Annotated[int, Body()] = 60,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """새 API key를 생성합니다. 평문 key는 이 응답에서만 노출됩니다."""
    db_user = db.get(User, uuid.UUID(user.user_id))
    if db_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="사용자를 찾을 수 없습니다")
    if not db_user.is_developer:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key를 발급할 권한이 없습니다")

    api_key, plain = create_api_key_record(db_user, name, scopes or ["jobs:read", "jobs:write"], rate_limit_rpm)
    return {
        "id": api_key.id,
        "name": api_key.name,
        "prefix": api_key.prefix,
        "key": plain,
        "scopes": api_key.scopes,
        "rate_limit_rpm": api_key.rate_limit_rpm,
        "daily_quota": api_key.daily_quota,
        "is_active": api_key.is_active,
        "created_at": api_key.created_at.isoformat() if api_key.created_at else None,
    }


@router.get("")
def list_keys(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """사용자의 API key 목록을 반환합니다 (평문은 미포함)."""
    rows = db.execute(
        select(ApiKey).where(ApiKey.user_id == uuid.UUID(user.user_id)).order_by(ApiKey.created_at.desc())
    ).scalars().all()
    return [
        {
            "id": k.id,
            "name": k.name,
            "prefix": k.prefix,
            "scopes": k.scopes,
            "rate_limit_rpm": k.rate_limit_rpm,
            "daily_quota": k.daily_quota,
            "is_active": k.is_active,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "expires_at": k.expires_at.isoformat() if k.expires_at else None,
            "created_at": k.created_at.isoformat() if k.created_at else None,
        }
        for k in rows
    ]


@router.delete("/{key_id}")
def delete_key(
    key_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """API key를 삭제합니다."""
    key = db.get(ApiKey, key_id)
    if key is None or str(key.user_id) != user.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="key를 찾을 수 없습니다")
    db.delete(key)
    db.commit()
    return {"ok": True}


@router.post("/{key_id}/rotate")
def rotate_key(
    key_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """기존 key를 비활성화하고 새 평문 key를 발급합니다."""
    old_key = db.get(ApiKey, key_id)
    if old_key is None or str(old_key.user_id) != user.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="key를 찾을 수 없습니다")

    db_user = db.get(User, uuid.UUID(user.user_id))
    new_key, plain = create_api_key_record(
        db_user, old_key.name, old_key.scopes or ["jobs:read", "jobs:write"], old_key.rate_limit_rpm
    )
    old_key.is_active = False
    db.commit()
    return {
        "id": new_key.id,
        "name": new_key.name,
        "prefix": new_key.prefix,
        "key": plain,
        "scopes": new_key.scopes,
        "rate_limit_rpm": new_key.rate_limit_rpm,
    }


@router.get("/{key_id}/usage")
def key_usage(
    key_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 100,
):
    """특정 API key의 사용 내역을 반환합니다."""
    from ...db.models import ApiUsage

    key = db.get(ApiKey, key_id)
    if key is None or str(key.user_id) != user.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="key를 찾을 수 없습니다")

    rows = db.execute(
        select(ApiUsage).where(ApiUsage.api_key_id == key_id).order_by(ApiUsage.created_at.desc()).limit(limit)
    ).scalars().all()
    return [
        {
            "id": u.id,
            "endpoint": u.endpoint,
            "job_id": u.job_id,
            "points_spent": u.points_spent,
            "http_status": u.http_status,
            "client_ip": u.client_ip,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in rows
    ]
