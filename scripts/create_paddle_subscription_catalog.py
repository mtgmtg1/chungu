#!/usr/bin/env python3
# [Flow: Step 1 (Paddle API 인증) -> Step 2 (Free/Pro/Max 상품 생성) -> Step 3 (월간/연간 가격 생성) -> Step 4 (DB에 price_id 저장) -> Step 5 (결과 출력)]
"""Paddle Billing에 PROOF 구독 요금제 상품과 가격을 자동 생성한다.

Usage:
    PADDLE_API_KEY=xxx DATABASE_URL=xxx python scripts/create_paddle_subscription_catalog.py
    python scripts/create_paddle_subscription_catalog.py --api-key xxx --db-url xxx

환경변수:
    PADDLE_API_KEY: Paddle live API key (필수)
    DATABASE_URL: PostgreSQL 연결 문자열 (필수)
    PADDLE_ENV: sandbox 또는 live (기본 live)
"""
import argparse
import os
import sys
from decimal import Decimal

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# app/ 경로를 import path에 추가 (backend 패키지로 상대 import 가능하도록)
script_dir = os.path.dirname(os.path.abspath(__file__))
DEFAULT_APP_DIR = os.path.join(script_dir, "..", "app")

PADDLE_BASE_URL = "https://api.paddle.com"

# backend.settings_store는 실행 시 --app-dir로 지정된 경로에서 지연 import 한다.
settings_store = None

PLANS = {
    "free": {
        "name": "PROOF Free",
        "description": "Free monthly plan for PROOF: 1,000 basic pages + 500 premium pages + 150 minutes of media.",
        "monthly": {"amount": "0"},
        "yearly": {"amount": "0"},
    },
    "pro": {
        "name": "PROOF Pro",
        "description": "Pro monthly plan for PROOF: 10,000 basic pages + 5,000 premium pages + 1,500 minutes of media.",
        "monthly": {"amount": "2000"},  # $20.00
        "yearly": {"amount": "20000"},  # $200.00
    },
    "max": {
        "name": "PROOF Max",
        "description": "Max monthly plan for PROOF: 60,000 basic pages + 30,000 premium pages + 9,000 minutes of media.",
        "monthly": {"amount": "10000"},  # $100.00
        "yearly": {"amount": "100000"},  # $1,000.00
    },
}


def _paddle_headers(api_key: str) -> dict:
    """Paddle API 요청 헤더를 반환한다."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def create_product(api_key: str, name: str, description: str) -> dict:
    """Paddle에 상품을 생성하고 생성된 상품 정보를 반환한다."""
    url = f"{PADDLE_BASE_URL}/products"
    payload = {
        "name": name,
        "description": description,
        "tax_category": "saas",
        "type": "standard",
    }
    resp = requests.post(url, headers=_paddle_headers(api_key), json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["data"]


def create_price(
    api_key: str,
    product_id: str,
    description: str,
    amount: str,
    interval: str,
    frequency: int,
) -> dict:
    """Paddle에 recurring 가격을 생성하고 생성된 가격 정보를 반환한다."""
    url = f"{PADDLE_BASE_URL}/prices"
    payload = {
        "description": description,
        "product_id": product_id,
        "type": "standard",
        "billing_cycle": {
            "interval": interval,
            "frequency": frequency,
        },
        "unit_price": {
            "amount": amount,
            "currency_code": "USD",
        },
    }
    resp = requests.post(url, headers=_paddle_headers(api_key), json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["data"]


def save_price_ids(db, price_ids: dict[str, str]) -> None:
    """생성된 가격 ID들을 app_settings 테이블에 저장한다."""
    for key, value in price_ids.items():
        settings_store.set_setting(db, key, value)
    print("Saved price IDs to app_settings")


def main():
    parser = argparse.ArgumentParser(description="Create PROOF subscription plans in Paddle.")
    parser.add_argument("--api-key", default=os.environ.get("PADDLE_API_KEY"), help="Paddle API key")
    parser.add_argument("--db-url", default=os.environ.get("DATABASE_URL"), help="PostgreSQL URL")
    parser.add_argument("--env", default=os.environ.get("PADDLE_ENV", "live"), help="Paddle environment")
    parser.add_argument("--save-db", action="store_true", default=True, help="Save price IDs to DB")
    parser.add_argument("--dry-run", action="store_true", help="Print only, do not call Paddle API")
    parser.add_argument("--app-dir", default=os.environ.get("APP_DIR", DEFAULT_APP_DIR), help="Path to app directory containing backend package")
    args = parser.parse_args()

    # backend 패키지를 지정된 app 디렉토리에서 import
    app_dir = os.path.abspath(args.app_dir)
    sys.path.insert(0, app_dir)
    global settings_store
    from backend import settings_store as _settings_store  # noqa: E402
    settings_store = _settings_store

    if args.dry_run:
        args.save_db = False

    if not args.api_key:
        print("Error: PADDLE_API_KEY or --api-key is required", file=sys.stderr)
        sys.exit(1)
    if not args.db_url and args.save_db:
        print("Error: DATABASE_URL or --db-url is required when saving to DB", file=sys.stderr)
        sys.exit(1)

    db = None
    if args.save_db:
        engine = create_engine(args.db_url)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()

    price_ids: dict[str, str] = {}

    try:
        for plan_key, plan in PLANS.items():
            print(f"\nCreating plan: {plan['name']}")
            if args.dry_run:
                product_id = f"dry_run_pro_{plan_key}"
                print(f"  [dry-run] product: {product_id}")
            else:
                product = create_product(args.api_key, plan["name"], plan["description"])
                product_id = product["id"]
                print(f"  product: {product_id}")

            for cycle, price_info in [("monthly", plan["monthly"]), ("yearly", plan["yearly"])]:
                interval = "month" if cycle == "monthly" else "year"
                frequency = 1
                description = f"{plan['name']} - {cycle}"
                amount = price_info["amount"]
                usd = Decimal(amount) / 100

                if args.dry_run:
                    price_id = f"dry_run_pri_{plan_key}_{cycle}"
                    print(f"  [dry-run] price ({cycle} ${usd}): {price_id}")
                else:
                    price = create_price(
                        args.api_key,
                        product_id,
                        description,
                        amount,
                        interval,
                        frequency,
                    )
                    price_id = price["id"]
                    print(f"  price ({cycle} ${usd}): {price_id}")

                setting_key = f"paddle_subscription_price_id_{plan_key}_{cycle}"
                price_ids[setting_key] = price_id

        if args.save_db:
            save_price_ids(db, price_ids)

        print("\nAll price IDs:")
        for key, value in price_ids.items():
            print(f"  {key}: {value}")
    finally:
        if db:
            db.close()


if __name__ == "__main__":
    main()
