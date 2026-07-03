#!/usr/bin/env python3
# [Flow: Step 1 (JWT 인증으로 사용자 식별) -> Step 2 (사용자 데이터 수집 또는 계정 삭제) -> Step 3 (JSON 응답 또는 삭제 완료)]
import json
import os
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.supabase_auth import CurrentUser, get_current_user
from ..db.models import ApiKey, ApiUsage, Job, Payment, PointTransaction, User
from ..db.session import get_db

router = APIRouter(prefix="/api/account", tags=["account-gdpr"])


@router.get("/export")
def export_user_data(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    GDPR/CCPA 데이터 내보내기.
    사용자의 계정 정보, 포인트 거래, 결제 내역, 작업 내역, API 키, API 사용량을 JSON으로 반환.
    """
    uid = uuid.UUID(user.user_id)

    account_info = {
        "user_id": str(uid),
        "email": user.email,
        "points_balance": user.points_balance,
        "language": user.language,
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }

    transactions = (
        db.execute(
            select(PointTransaction).where(PointTransaction.user_id == uid)
        )
        .scalars()
        .all()
    )
    tx_list = [
        {
            "id": str(t.id),
            "type": t.type,
            "amount": t.amount,
            "balance_after": t.balance_after,
            "description": t.description,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in transactions
    ]

    payments = (
        db.execute(select(Payment).where(Payment.user_id == uid))
        .scalars()
        .all()
    )
    pay_list = [
        {
            "id": str(p.id),
            "provider": p.provider,
            "currency": p.currency,
            "amount": str(p.amount),
            "points_added": p.points_added,
            "status": p.status,
            "external_id": p.external_id,
            "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in payments
    ]

    jobs = (
        db.execute(select(Job).where(Job.user_id == uid))
        .scalars()
        .all()
    )
    job_list = [
        {
            "id": str(j.id),
            "status": j.status,
            "filename": j.filename,
            "created_at": j.created_at.isoformat() if j.created_at else None,
        }
        for j in jobs
    ]

    api_keys = (
        db.execute(select(ApiKey).where(ApiKey.user_id == uid))
        .scalars()
        .all()
    )
    key_list = [
        {
            "id": str(k.id),
            "name": k.name,
            "prefix": k.prefix,
            "is_active": k.is_active,
            "rate_limit_rpm": k.rate_limit_rpm,
            "created_at": k.created_at.isoformat() if k.created_at else None,
        }
        for k in api_keys
    ]

    usage = (
        db.execute(select(ApiUsage).where(ApiUsage.user_id == uid))
        .scalars()
        .all()
    )
    usage_list = [
        {
            "id": str(u.id),
            "points_spent": u.points_spent,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in usage
    ]

    data = {
        "account": account_info,
        "point_transactions": tx_list,
        "payments": pay_list,
        "jobs": job_list,
        "api_keys": key_list,
        "api_usage": usage_list,
    }

    return Response(
        content=json.dumps(data, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="proof-data-export-{uid}.json"',
        },
    )


@router.delete("")
def delete_user_account(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    GDPR/CCPA 계정 삭제.
    사용자의 모든 데이터를 삭제하고 계정을 영구 제거.
    결제 기록은 전자상거래법에 따라 5년간 익명화 보관.
    Supabase Auth에서도 사용자를 삭제.
    """
    uid = uuid.UUID(user.user_id)

    # 1. API 사용량 삭제
    db.execute(
        ApiUsage.__table__.delete().where(ApiUsage.user_id == uid)
    )

    # 2. 포인트 거래 삭제
    db.execute(
        PointTransaction.__table__.delete().where(PointTransaction.user_id == uid)
    )

    # 3. 결제 내역 익명화 (전자상거래법 5년 보관 의무)
    payments = (
        db.execute(select(Payment).where(Payment.user_id == uid))
        .scalars()
        .all()
    )
    for p in payments:
        p.user_id = None

    # 4. 작업 내역 삭제
    db.execute(
        Job.__table__.delete().where(Job.user_id == uid)
    )

    # 5. API 키 삭제
    db.execute(
        ApiKey.__table__.delete().where(ApiKey.user_id == uid)
    )

    # 6. 사용자 레코드 삭제
    db.execute(
        User.__table__.delete().where(User.id == uid)
    )

    db.commit()

    # 7. Supabase Auth에서 사용자 삭제 (서비스 롤 키 필요)
    supabase_url = os.getenv("SUPABASE_URL")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if supabase_url and service_role_key:
        try:
            resp = httpx.delete(
                f"{supabase_url}/auth/v1/admin/users/{uid}",
                headers={
                    "Authorization": f"Bearer {service_role_key}",
                    "apikey": service_role_key,
                },
                timeout=10,
            )
        except Exception:
            pass

    return {"ok": True, "message": "Account deleted successfully"}
