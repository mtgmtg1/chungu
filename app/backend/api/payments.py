#!/usr/bin/env python3
# [Flow: Step 1 (포인트 패키지 조회) -> Step 2 (Toss/Paddle 결제 시작) -> Step 3 (결제 검증/웹훅) -> Step 4 (포인트 충전)]
import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import requests
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .. import settings_store
from ..auth.supabase_auth import CurrentUser, get_current_admin, get_current_user
from ..core import points_service
from ..db.models import Payment, User
from ..db.session import get_db

router = APIRouter(prefix="/api/payments", tags=["payments"])


def _toss_headers(secret_key: str) -> dict:
    token = base64.b64encode(f"{secret_key}:".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


@router.get("/packages")
def list_packages(db: Session = Depends(get_db)):
    """판매 중인 포인트 패키지 목록."""
    return {
        "packages": points_service.get_point_packages(db),
        "rates": {
            "krw_per_page": int(settings_store.get_setting(db, "cost_per_page_krw") or "3"),
            "krw_per_image": int(settings_store.get_setting(db, "cost_per_image_krw") or "3"),
            "krw_per_audio_second": int(settings_store.get_setting(db, "cost_per_audio_sec_krw") or "1"),
            "krw_per_video_second": int(settings_store.get_setting(db, "cost_per_video_sec_krw") or "3"),
            "usd_per_point": settings_store.get_setting(db, "cost_per_page_usd") or "0.002",
        },
    }


@router.post("/toss/order")
def create_toss_order(
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Toss 결제용 orderId를 생성하고 DB에 pending Payment를 기록합니다."""
    package_id = payload.get("package_id")
    packages = points_service.get_point_packages(db)
    selected = next((p for p in packages if p.get("id") == package_id or p.get("name") == package_id), None)
    if not selected:
        # custom point amount
        points = int(payload.get("points") or 0)
        krw = int(payload.get("krw") or 0)
        if points <= 0 or krw <= 0:
            raise HTTPException(status_code=400, detail="유효한 포인트/금액을 입력하세요")
    else:
        points = selected["points"]
        krw = selected["krw"]

    order_id = f"chungu-{user.user_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hashlib.sha256((str(user.user_id) + str(krw)).encode()).hexdigest()[:8]}"
    payment = Payment(
        user_id=uuid.UUID(user.user_id),
        provider="toss",
        currency="KRW",
        amount=krw,
        points_added=points,
        status="pending",
        external_id=order_id,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return {"order_id": order_id, "amount": krw, "points": points, "payment_id": payment.id}


@router.post("/toss/success")
def verify_toss_payment(
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Toss 결제 승인 후 포인트를 충전합니다."""
    payment_key = payload.get("paymentKey")
    order_id = payload.get("orderId")
    amount = int(payload.get("amount") or 0)
    if not payment_key or not order_id:
        raise HTTPException(status_code=400, detail="paymentKey와 orderId가 필요합니다")

    secret_key = settings_store.get_setting(db, "toss_secret_key")
    if not secret_key:
        raise HTTPException(status_code=503, detail="Toss 시크릿 키가 설정되지 않았습니다")

    # Toss 결제 승인 API 호출
    try:
        resp = requests.post(
            "https://api.tosspayments.com/v1/payments/confirm",
            headers=_toss_headers(secret_key),
            json={"paymentKey": payment_key, "orderId": order_id, "amount": amount},
            timeout=20,
        )
        resp.raise_for_status()
        result = resp.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Toss 검증 실패: {e}") from e

    payment = db.query(Payment).filter(Payment.external_id == order_id).first()
    if payment is None or str(payment.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다")
    if payment.status == "paid":
        return {"ok": True, "points": payment.points_added, "balance": user.points_balance}

    if result.get("status") != "DONE":
        payment.status = "failed"
        db.commit()
        raise HTTPException(status_code=400, detail=f"결제가 완료되지 않았습니다: {result.get('status')}")

    db_user = db.get(User, uuid.UUID(user.user_id))
    if db_user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    payment.status = "paid"
    payment.paid_at = datetime.now(timezone.utc)
    db.commit()

    points_service.charge_points(db, db_user, payment.points_added, f"Toss 결제 {amount}원")
    return {"ok": True, "points": payment.points_added, "balance": db_user.points_balance}


@router.post("/paddle/checkout")
def create_paddle_checkout(
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Paddle Checkout URL을 생성합니다."""
    api_key = settings_store.get_setting(db, "paddle_api_key")
    vendor_id = settings_store.get_setting(db, "paddle_vendor_id")
    if not api_key or not vendor_id:
        raise HTTPException(status_code=503, detail="Paddle API 키/판매자 ID가 설정되지 않았습니다")

    package_id = payload.get("package_id")
    packages = points_service.get_point_packages(db)
    selected = next((p for p in packages if p.get("id") == package_id or p.get("name") == package_id), None)
    if not selected:
        raise HTTPException(status_code=400, detail="패키지를 찾을 수 없습니다")

    # Paddle v2 API: transaction 생성
    try:
        resp = requests.post(
            "https://api.paddle.com/transactions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "items": [
                    {
                        "price": {"description": f"{selected['points']} Points", "unit_price": {"amount": str(selected["usd"]), "currency_code": "USD"}},
                        "quantity": 1,
                    }
                ],
                "customer_id": user.user_id,
                "custom_data": {"user_id": user.user_id, "points": selected["points"], "package_name": selected["name"]},
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        return {"checkout_url": data["data"]["checkout"]["url"], "transaction_id": data["data"]["id"]}
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Paddle checkout 생성 실패: {e}") from e


@router.post("/paddle/webhook")
def paddle_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """Paddle 웹훅을 검증하고 포인트를 충전합니다."""
    body = (request.body() or b"").decode()
    signature = request.headers.get("paddle-signature") or ""
    secret = settings_store.get_setting(db, "paddle_webhook_secret")
    if not secret:
        raise HTTPException(status_code=503, detail="Paddle webhook secret이 설정되지 않았습니다")

    if not _verify_paddle_signature(body, signature, secret):
        raise HTTPException(status_code=401, detail="서명이 유효하지 않습니다")

    data = json.loads(body)
    event_type = data.get("event_type")
    if event_type not in ("payment.succeeded", "transaction.completed"):
        return {"ok": True, "ignored": event_type}

    custom = data.get("data", {}).get("custom_data", {})
    user_id = custom.get("user_id")
    points = int(custom.get("points") or 0)
    if not user_id or points <= 0:
        return {"ok": False, "detail": "custom_data에 user_id/points가 없습니다"}

    db_user = db.get(User, uuid.UUID(user_id))
    if db_user is None:
        return {"ok": False, "detail": "사용자를 찾을 수 없습니다"}

    # 중복 처리 방지
    external_id = data.get("data", {}).get("id", "")
    existing = db.query(Payment).filter(Payment.external_id == external_id).first()
    if existing:
        return {"ok": True, "duplicate": True}

    payment = Payment(
        user_id=uuid.UUID(user_id),
        provider="paddle",
        currency="USD",
        amount=data.get("data", {}).get("details", {}).get("totals", {}).get("total", "0"),
        points_added=points,
        status="paid",
        external_id=external_id,
        paid_at=datetime.now(timezone.utc),
    )
    db.add(payment)
    db.commit()

    points_service.charge_points(db, db_user, points, f"Paddle 결제 ${payment.amount}")
    return {"ok": True, "points": points, "balance": db_user.points_balance}


def _verify_paddle_signature(body: str, signature: str, secret: str) -> bool:
    try:
        expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception:  # noqa: BLE001
        return False


@router.get("/history")
def payment_history(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 100,
):
    rows = db.query(Payment).filter(Payment.user_id == uuid.UUID(user.user_id)).order_by(Payment.created_at.desc()).limit(limit).all()
    return [
        {
            "id": p.id,
            "provider": p.provider,
            "currency": p.currency,
            "amount": str(p.amount),
            "points_added": p.points_added,
            "status": p.status,
            "external_id": p.external_id,
            "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in rows
    ]


@router.get("/admin/history")
def admin_payment_history(
    admin: CurrentUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
    limit: int = 100,
):
    rows = db.query(Payment).order_by(Payment.created_at.desc()).limit(limit).all()
    return [
        {
            "id": p.id,
            "user_id": str(p.user_id),
            "provider": p.provider,
            "currency": p.currency,
            "amount": str(p.amount),
            "points_added": p.points_added,
            "status": p.status,
            "external_id": p.external_id,
            "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in rows
    ]
