#!/usr/bin/env python3
# [Flow: Step 1 (자유 금액 입력) -> Step 2 (Paddle Customer 생성/조회) -> Step 3 (Checkout URL 생성) -> Step 4 (웹훅 수신) -> Step 5 (크레딧 충전) -> Step 6 (자동 충전 트리거/재시도)]
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import settings_store
from ..auth.supabase_auth import CurrentUser, get_current_admin, get_current_user
from ..core import points_service
from ..db.models import Payment, User
from ..db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/payments", tags=["payments"])


def _paddle_api_headers(db: Session) -> dict:
    """Paddle API 인증 헤더를 반환한다."""
    api_key = settings_store.get_setting(db, "paddle_api_key")
    if not api_key:
        raise HTTPException(status_code=503, detail="Paddle API key not configured")
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


@router.get("/packages")
def list_packages(db: Session = Depends(get_db)):
    """충전 한도를 반환한다 (자유 금액 방식)."""
    limits = points_service.get_charge_limits()
    return {
        "min_amount": limits["min_amount"],
        "max_amount": limits["max_amount"],
        "currency": "USD",
    }


def _get_or_create_paddle_customer(db: Session, db_user: User, api_headers: dict) -> str:
    """Paddle Customer를 조회하거나 생성하고 customer_id를 반환한다.
    생성된 customer_id는 db_user.paddle_customer_id에 저장한다."""
    # [Flow: Step 1 (기존 customer_id 확인) -> Step 2 (없으면 Paddle에서 생성) -> Step 3 (DB에 저장)]
    if db_user.paddle_customer_id:
        return db_user.paddle_customer_id

    try:
        resp = requests.post(
            "https://api.paddle.com/customers",
            headers=api_headers,
            json={"email": db_user.email},
            timeout=20,
        )
        resp.raise_for_status()
        customer_id = resp.json()["data"]["id"]
        db_user.paddle_customer_id = customer_id
        db.commit()
        return customer_id
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Failed to create Paddle customer: {e}") from e


@router.post("/paddle/checkout")
def create_paddle_checkout(
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Paddle Checkout URL을 생성한다 (자유 금액 방식).
    요청: { "amount": 15 } — 사용자가 입력한 달러 금액 (정수, $5~$500)"""
    # [Flow: Step 1 (금액 검증) -> Step 2 (Paddle Customer 조회/생성) -> Step 3 (트랜잭션 생성) -> Step 4 (Checkout URL 반환)]
    amount = int(payload.get("amount") or 0)
    limits = points_service.get_charge_limits()
    if amount < limits["min_amount"] or amount > limits["max_amount"]:
        raise HTTPException(status_code=400, detail=f"Amount must be an integer between ${limits['min_amount']} and ${limits['max_amount']}")

    api_headers = _paddle_api_headers(db)
    price_id = settings_store.get_setting(db, "paddle_price_id")
    if not price_id:
        raise HTTPException(status_code=503, detail="paddle_price_id not configured")

    db_user = db.get(User, uuid.UUID(user.user_id))
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    customer_id = _get_or_create_paddle_customer(db, db_user, api_headers)
    credits = amount * 1000  # milli-USD

    try:
        resp = requests.post(
            "https://api.paddle.com/transactions",
            headers=api_headers,
            json={
                "items": [
                    {
                        "price_id": price_id,
                        "quantity": amount,
                    }
                ],
                "customer_id": customer_id,
                "checkout": {"url": "https://proof.teamcat.app/payment"},
                "custom_data": {"user_id": user.user_id, "credits": str(credits)},
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        return {"checkout_url": data["data"]["checkout"]["url"], "transaction_id": data["data"]["id"]}
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Failed to create Paddle checkout: {e}") from e


@router.post("/paddle/webhook")
def paddle_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """Paddle 웹훅을 검증하고 크레딧을 충전한다."""
    # [Flow: Step 1 (서명 검증) -> Step 2 (이벤트 필터) -> Step 3 (custom_data 추출) -> Step 4 (중복 방지) -> Step 5 (크레딧 충전)]
    body = (request.body() or b"").decode()
    signature = request.headers.get("paddle-signature") or ""
    secret = settings_store.get_setting(db, "paddle_webhook_secret")
    if not secret:
        raise HTTPException(status_code=503, detail="Paddle webhook secret not configured")

    if not _verify_paddle_signature(body, signature, secret):
        raise HTTPException(status_code=401, detail="Invalid signature")

    data = json.loads(body)
    event_type = data.get("event_type")
    if event_type != "transaction.completed":
        return {"ok": True, "ignored": event_type}

    custom = data.get("data", {}).get("custom_data", {})
    user_id = custom.get("user_id")
    credits = int(custom.get("credits") or 0)
    if not user_id or credits <= 0:
        return {"ok": False, "detail": "Missing user_id/credits in custom_data"}

    db_user = db.get(User, uuid.UUID(user_id))
    if db_user is None:
        return {"ok": False, "detail": "User not found"}

    # 중복 처리 방지
    external_id = data.get("data", {}).get("id", "")
    existing = db.query(Payment).filter(Payment.external_id == external_id).first()
    if existing:
        return {"ok": True, "duplicate": True}

    # paddle_customer_id가 없으면 저장 (첫 결제 후)
    if not db_user.paddle_customer_id:
        customer_id = data.get("data", {}).get("customer_id", "")
        if customer_id:
            db_user.paddle_customer_id = customer_id

    amount_str = data.get("data", {}).get("details", {}).get("totals", {}).get("total", "0")
    payment = Payment(
        user_id=uuid.UUID(user_id),
        provider="paddle",
        currency="USD",
        amount=amount_str,
        points_added=credits,
        status="paid",
        external_id=external_id,
        paid_at=datetime.now(timezone.utc),
    )
    db.add(payment)
    db.commit()

    points_service.charge_points(db, db_user, credits, f"Paddle 결제 ${amount_str}")
    return {"ok": True, "credits": credits, "balance": db_user.points_balance}


def _verify_paddle_signature(body: str, signature: str, secret: str) -> bool:
    """Paddle v2 웹훅 서명을 검증한다. 형식: ts=xxx;h1=xxx"""
    # [Flow: Step 1 (ts;h1 파싱) -> Step 2 (HMAC-SHA256 계산) -> Step 3 (비교)]
    try:
        parts = dict(p.split("=", 1) for p in signature.split(";"))
        ts = parts.get("ts", "")
        h1 = parts.get("h1", "")
        if not ts or not h1:
            return False
        signed_payload = f"{ts}:{body}"
        expected = hmac.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, h1)
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


# ============================================================
# 자동 충전 (Auto-Recharge)
# ============================================================


def trigger_auto_recharge(db: Session, db_user: User) -> dict:
    """저장된 결제 수단으로 자동 충전을 시도한다.
    성공 시 트랜잭션 생성, 실패 시 재시도 카운트 증가.
    3회 실패 시 자동 충전 비활성화 + 이메일 알림."""
    # [Flow: Step 1 (Paddle customer_id 확인) -> Step 2 (저장된 결제 수단 조회) -> Step 3 (자동 결제 트랜잭션 생성) -> Step 4 (실패 시 재시도/비활성화)]
    if not db_user.paddle_customer_id:
        logger.warning(f"자동 충전 실패: paddle_customer_id 없음 (user={db_user.id})")
        return {"ok": False, "reason": "no_customer_id"}

    api_headers = _paddle_api_headers(db)
    price_id = settings_store.get_setting(db, "paddle_price_id")
    if not price_id:
        logger.error("자동 충전 실패: paddle_price_id 미설정")
        return {"ok": False, "reason": "no_price_id"}

    # Step 2: 저장된 결제 수단 조회
    try:
        pm_resp = requests.get(
            f"https://api.paddle.com/customers/{db_user.paddle_customer_id}/payment-methods",
            headers=api_headers,
            params={"per_page": 1},
            timeout=20,
        )
        pm_resp.raise_for_status()
        pm_data = pm_resp.json()
        payment_methods = pm_data.get("data", [])
        if not payment_methods:
            logger.warning(f"자동 충전 실패: 저장된 결제 수단 없음 (user={db_user.id})")
            _disable_auto_recharge(db, db_user)
            return {"ok": False, "reason": "no_payment_method"}
    except requests.RequestException as e:
        logger.error(f"자동 충전: 결제 수단 조회 실패 (user={db_user.id}): {e}")
        _handle_auto_recharge_failure(db, db_user)
        return {"ok": False, "reason": "payment_method_lookup_failed"}

    # Step 3: 자동 결제 트랜잭션 생성
    amount = db_user.auto_recharge_amount
    credits = amount * 1000  # milli-USD
    try:
        resp = requests.post(
            "https://api.paddle.com/transactions",
            headers=api_headers,
            json={
                "items": [{"price_id": price_id, "quantity": amount}],
                "customer_id": db_user.paddle_customer_id,
                "collection_mode": "automatic",
                "status": "billed",
                "custom_data": {
                    "user_id": str(db_user.id),
                    "credits": str(credits),
                    "auto_recharge": "true",
                },
            },
            timeout=30,
        )
        resp.raise_for_status()
        tx_data = resp.json()["data"]
        logger.info(f"자동 충전 트랜잭션 생성 성공 (user={db_user.id}, tx={tx_data['id']})")
        # 재시도 카운트 리셋
        db_user.auto_recharge_retries = 0
        db.commit()
        return {"ok": True, "transaction_id": tx_data["id"]}
    except requests.RequestException as e:
        logger.error(f"자동 충전 결제 실패 (user={db_user.id}): {e}")
        _handle_auto_recharge_failure(db, db_user)
        return {"ok": False, "reason": "charge_failed"}


def _handle_auto_recharge_failure(db: Session, db_user: User) -> None:
    """자동 충전 실패 시 재시도 카운트 증가. 3회 실패 시 비활성화 + 이메일 알림."""
    db_user.auto_recharge_retries += 1
    db.commit()

    if db_user.auto_recharge_retries >= 3:
        _disable_auto_recharge(db, db_user)
        _send_auto_recharge_failure_email(db_user)


def _disable_auto_recharge(db: Session, db_user: User) -> None:
    """자동 충전을 비활성화한다."""
    db_user.auto_recharge_enabled = False
    db.commit()
    logger.info(f"자동 충전 비활성화 (user={db_user.id})")


def _send_auto_recharge_failure_email(db_user: User) -> None:
    """자동 충전 실패 알림 이메일을 발송한다."""
    try:
        from ..email_sender import build_error_email, send_email
        from ..db.session import SessionLocal

        lang = getattr(db_user, "language", "en") or "en"
        subject, html = build_error_email(
            job_id="auto-recharge",
            filename="Auto-Recharge",
            error="자동 충전이 3회 연속 실패하여 비활성화되었습니다. 결제 수단을 확인 후 다시 활성화해주세요.",
            lang=lang,
        )
        db_session = SessionLocal()
        try:
            send_email(db_session, db_user.email, subject, html)
        finally:
            db_session.close()
        logger.info(f"자동 충전 실패 이메일 발송 완료 (user={db_user.id}, email={db_user.email})")
    except Exception as e:
        logger.error(f"자동 충전 실패 이메일 발송 중 오류 (user={db_user.id}): {e}")


@router.get("/auto-recharge/settings")
def get_auto_recharge_settings(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """현재 자동 충전 설정과 저장된 결제 수단 여부를 반환한다."""
    db_user = db.get(User, uuid.UUID(user.user_id))
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    has_payment_method = False
    if db_user.paddle_customer_id:
        try:
            api_headers = _paddle_api_headers(db)
            pm_resp = requests.get(
                f"https://api.paddle.com/customers/{db_user.paddle_customer_id}/payment-methods",
                headers=api_headers,
                params={"per_page": 1},
                timeout=20,
            )
            pm_resp.raise_for_status()
            has_payment_method = len(pm_resp.json().get("data", [])) > 0
        except requests.RequestException:
            pass

    return {
        "enabled": db_user.auto_recharge_enabled,
        "threshold": db_user.auto_recharge_threshold,
        "amount": db_user.auto_recharge_amount,
        "has_payment_method": has_payment_method,
        "retries": db_user.auto_recharge_retries,
    }


@router.post("/auto-recharge/settings")
def update_auto_recharge_settings(
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """자동 충전 설정을 업데이트한다."""
    db_user = db.get(User, uuid.UUID(user.user_id))
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    enabled = bool(payload.get("enabled", False))
    threshold = int(payload.get("threshold", 2000))
    amount = int(payload.get("amount", 10))

    min_threshold = int(settings_store.get_setting(db, "auto_recharge_min_threshold") or "500")
    if threshold < min_threshold:
        raise HTTPException(status_code=400, detail=f"Threshold must be at least {min_threshold} milli-USD")
    if amount < 5 or amount > 500:
        raise HTTPException(status_code=400, detail="Charge amount must be between $5 and $500")

    db_user.auto_recharge_enabled = enabled
    db_user.auto_recharge_threshold = threshold
    db_user.auto_recharge_amount = amount
    if enabled:
        db_user.auto_recharge_retries = 0
    db.commit()

    return {
        "enabled": db_user.auto_recharge_enabled,
        "threshold": db_user.auto_recharge_threshold,
        "amount": db_user.auto_recharge_amount,
    }


@router.get("/paddle/payment-methods")
def list_paddle_payment_methods(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """저장된 결제 수단 목록을 반환한다."""
    db_user = db.get(User, uuid.UUID(user.user_id))
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not db_user.paddle_customer_id:
        return {"payment_methods": []}

    try:
        api_headers = _paddle_api_headers(db)
        resp = requests.get(
            f"https://api.paddle.com/customers/{db_user.paddle_customer_id}/payment-methods",
            headers=api_headers,
            timeout=20,
        )
        resp.raise_for_status()
        methods = resp.json().get("data", [])
        return {
            "payment_methods": [
                {
                    "id": m.get("id", ""),
                    "type": m.get("type", ""),
                    "card": {
                        "brand": m.get("card", {}).get("type", "") if m.get("card") else "",
                        "last4": m.get("card", {}).get("last4", "") if m.get("card") else "",
                        "expiry_month": m.get("card", {}).get("expiry_month", "") if m.get("card") else "",
                        "expiry_year": m.get("card", {}).get("expiry_year", "") if m.get("card") else "",
                    } if m.get("card") else None,
                }
                for m in methods
            ]
        }
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Failed to retrieve payment methods: {e}") from e
