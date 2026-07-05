#!/usr/bin/env python3
# [Flow: Step 1 (내 구독 상태 조회) -> Step 2 (Paddle Checkout 생성) -> Step 3 (구독 취소/업데이트)]
import logging
import uuid

import requests
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import settings_store
from ..auth.supabase_auth import CurrentUser, get_current_user
from ..core import subscription_service
from ..db.models import User
from ..db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])

def _paddle_api_headers(db: Session) -> dict:
    """Paddle API 인증 헤더를 반환한다."""
    api_key = settings_store.get_setting(db, "paddle_api_key")
    if not api_key:
        raise HTTPException(status_code=503, detail="Paddle API key not configured")
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _get_or_create_paddle_customer(db: Session, db_user: User, api_headers: dict) -> str:
    """Paddle Customer를 조회하거나 생성하고 customer_id를 반환한다."""
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


@router.get("/me")
def my_subscription(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """현재 로그인 사용자의 구독 상태와 잔여 한도를 반환한다."""
    db_user = db.get(User, uuid.UUID(user.user_id))
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return subscription_service.get_subscription_status(db, db_user)


@router.post("/checkout")
def create_subscription_checkout(
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Paddle 구독 Checkout URL을 생성한다.
    요청: { "plan": "pro", "cycle": "monthly" }"""
    plan = str(payload.get("plan") or "").lower()
    cycle = str(payload.get("cycle") or "").lower()
    if plan not in ("free", "pro", "max"):
        raise HTTPException(status_code=400, detail="Invalid plan")
    if cycle not in ("monthly", "yearly"):
        raise HTTPException(status_code=400, detail="Invalid cycle")

    price_key = f"paddle_subscription_price_id_{plan}_{cycle}"
    price_id = settings_store.get_setting(db, price_key)
    if not price_id:
        raise HTTPException(status_code=503, detail=f"Price not configured: {price_key}")

    db_user = db.get(User, uuid.UUID(user.user_id))
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    api_headers = _paddle_api_headers(db)
    customer_id = _get_or_create_paddle_customer(db, db_user, api_headers)

    try:
        resp = requests.post(
            "https://api.paddle.com/transactions",
            headers=api_headers,
            json={
                "items": [
                    {
                        "price_id": price_id,
                        "quantity": 1,
                    }
                ],
                "customer_id": customer_id,
                "checkout": {"url": "https://proof.teamcat.app/price"},
                "custom_data": {
                    "user_id": user.user_id,
                    "plan": plan,
                    "cycle": cycle,
                },
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        return {"checkout_url": data["data"]["checkout"]["url"], "transaction_id": data["data"]["id"]}
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Failed to create Paddle checkout: {e}") from e


@router.post("/cancel")
def cancel_subscription(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """현재 사용자의 Paddle 구독을 다음 갱신일에 취소한다."""
    db_user = db.get(User, uuid.UUID(user.user_id))
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not db_user.paddle_subscription_id:
        raise HTTPException(status_code=400, detail="No active subscription")

    api_headers = _paddle_api_headers(db)
    try:
        resp = requests.post(
            f"https://api.paddle.com/subscriptions/{db_user.paddle_subscription_id}/cancel",
            headers=api_headers,
            json={"effective_from": "next_billing_period"},
            timeout=20,
        )
        resp.raise_for_status()
        return {"ok": True, "subscription_id": db_user.paddle_subscription_id}
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Failed to cancel subscription: {e}") from e
