#!/usr/bin/env python3
# [Flow: Step 1 (Paddle API 인증) -> Step 2 (기존 notification-settings 조회) -> Step 3 (webhook URL 설정 POST 또는 PATCH) -> Step 4 (결과 출력)]
"""Paddle Billing에 PROOF 웹훅 알림 설정을 등록하거나 업데이트한다.

Usage:
    PADDLE_API_KEY=xxx python scripts/setup_paddle_webhook.py
    PADDLE_API_KEY=xxx python scripts/setup_paddle_webhook.py --destination https://proof.teamcat.app/api/payments/paddle/webhook
"""
import argparse
import os
import sys

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# backend 패키지는 --app-dir로 지정된 경로에서 import
settings_store = None

PADDLE_BASE_URL = "https://api.paddle.com"

DEFAULT_EVENTS = [
    "subscription.created",
    "subscription.updated",
    "subscription.canceled",
    "subscription.activated",
    "subscription.past_due",
    "subscription.paused",
    "subscription.resumed",
    "subscription.trialing",
    "transaction.completed",
    "transaction.past_due",
    "transaction.updated",
    "transaction.payment_failed",
]

DEFAULT_DESTINATION = "https://proof.teamcat.app/api/payments/paddle/webhook"


def _paddle_headers(api_key: str) -> dict:
    """Paddle API 요청 헤더를 반환한다."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def list_notification_settings(api_key: str) -> list:
    """Paddle에 등록된 notification settings 목록을 조회한다."""
    url = f"{PADDLE_BASE_URL}/notification-settings"
    resp = requests.get(url, headers=_paddle_headers(api_key), timeout=30)
    resp.raise_for_status()
    return resp.json().get("data", [])


def create_notification_setting(api_key: str, destination: str, events: list[str]) -> dict:
    """Paddle에 새 webhook URL notification setting을 생성한다."""
    url = f"{PADDLE_BASE_URL}/notification-settings"
    payload = {
        "description": "PROOF subscription and payment webhooks",
        "type": "url",
        "destination": destination,
        "active": True,
        "api_version": 1,
        "include_sensitive_fields": True,
        "traffic_source": "all",
        "subscribed_events": events,
    }
    resp = requests.post(url, headers=_paddle_headers(api_key), json=payload, timeout=30)
    if resp.status_code >= 400:
        print(f"Paddle API error: {resp.status_code} {resp.text}", file=sys.stderr)
    resp.raise_for_status()
    return resp.json()["data"]


def update_notification_setting(api_key: str, setting_id: str, destination: str, events: list[str]) -> dict:
    """Paddle의 기존 notification setting을 업데이트한다."""
    url = f"{PADDLE_BASE_URL}/notification-settings/{setting_id}"
    payload = {
        "description": "PROOF subscription and payment webhooks",
        "destination": destination,
        "active": True,
        "api_version": 1,
        "include_sensitive_fields": True,
        "traffic_source": "all",
        "subscribed_events": events,
    }
    resp = requests.patch(url, headers=_paddle_headers(api_key), json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["data"]


def main():
    parser = argparse.ArgumentParser(description="Register or update PROOF Paddle webhook.")
    parser.add_argument("--api-key", default=os.environ.get("PADDLE_API_KEY"), help="Paddle API key")
    parser.add_argument("--db-url", default=os.environ.get("DATABASE_URL"), help="PostgreSQL URL for saving webhook secret")
    parser.add_argument("--destination", default=DEFAULT_DESTINATION, help="Webhook destination URL")
    parser.add_argument("--events", default=",".join(DEFAULT_EVENTS), help="Comma-separated event types")
    parser.add_argument("--app-dir", default=os.environ.get("APP_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")), help="Path to app directory containing backend package")
    args = parser.parse_args()

    # backend 패키지를 지정된 app 디렉토리에서 import
    app_dir = os.path.abspath(args.app_dir)
    sys.path.insert(0, app_dir)
    global settings_store
    from backend import settings_store as _settings_store  # noqa: E402
    settings_store = _settings_store

    if not args.api_key:
        print("Error: PADDLE_API_KEY or --api-key is required", file=sys.stderr)
        sys.exit(1)

    events = [e.strip() for e in args.events.split(",") if e.strip()]

    print(f"Listing existing Paddle notification settings...")
    settings = list_notification_settings(args.api_key)

    existing = None
    for s in settings:
        if s.get("type") == "url" and s.get("destination") == args.destination:
            existing = s
            break

    if existing:
        setting_id = existing["id"]
        print(f"Updating existing notification setting: {setting_id}")
        result = update_notification_setting(args.api_key, setting_id, args.destination, events)
        print(f"Updated: {result['id']} -> {result['destination']}")
    else:
        print(f"Creating new notification setting for {args.destination}")
        result = create_notification_setting(args.api_key, args.destination, events)
        print(f"Created: {result['id']} -> {result['destination']}")

    print(f"Subscribed events: {', '.join(events)}")

    secret = result.get("endpoint_secret_key")
    if secret and args.db_url:
        print("Saving webhook secret to app_settings...")
        engine = create_engine(args.db_url)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        try:
            settings_store.set_setting(db, "paddle_webhook_secret", secret)
            print("Saved paddle_webhook_secret to app_settings")
        finally:
            db.close()
    elif secret:
        print(f"Webhook secret (save manually to app_settings paddle_webhook_secret): {secret}")
    else:
        print("Warning: Paddle did not return endpoint_secret_key")


if __name__ == "__main__":
    main()
