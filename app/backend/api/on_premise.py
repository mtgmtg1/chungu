#!/usr/bin/env python3
# [Flow: Step 1 (문의 데이터 검증) -> Step 2 (DB 저장) -> Step 3 (admin 이메일 발송) -> Step 4 (문의 ID 반환)]
import logging
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import email_sender
from ..auth.supabase_auth import CurrentUser, get_current_admin, require_user_or_admin
from ..db.models import OnPremiseInquiry
from ..db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/on-premise", tags=["on-premise"])

MIN_PAGES = 3000
MAX_PAGES = 12000
STEP_PAGES = 1000
BASE_PRICE = 20000
MAX_PRICE = 80000


def calculate_price(pages_per_hour: int) -> int:
    """시간당 처리량에 따른 예상 가격을 USD로 계산한다 (선형)."""
    if pages_per_hour < MIN_PAGES or pages_per_hour > MAX_PAGES:
        raise ValueError(f"Throughput must be between {MIN_PAGES} and {MAX_PAGES}")
    if pages_per_hour % STEP_PAGES != 0:
        raise ValueError(f"Throughput must be in increments of {STEP_PAGES}")
    ratio = (pages_per_hour - MIN_PAGES) / (MAX_PAGES - MIN_PAGES)
    return int(BASE_PRICE + ratio * (MAX_PRICE - BASE_PRICE))


@router.post("/inquiry")
def submit_inquiry(
    payload: dict = Body(...),
    user: CurrentUser | None = Depends(require_user_or_admin),
    db: Session = Depends(get_db),
):
    """온프레미스 로컬 서버 견적 문의를 접수한다."""
    email = (payload.get("email") or "").strip().lower()
    company = (payload.get("company") or "").strip()
    contact_name = (payload.get("contact_name") or "").strip()
    country = (payload.get("country") or "").strip()
    pages_per_hour = int(payload.get("pages_per_hour") or 0)
    message = (payload.get("message") or "").strip()
    agreed_terms = bool(payload.get("agreed_terms"))

    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    if pages_per_hour < MIN_PAGES or pages_per_hour > MAX_PAGES:
        raise HTTPException(status_code=400, detail=f"Throughput must be between {MIN_PAGES} and {MAX_PAGES} pages/hour")
    if pages_per_hour % STEP_PAGES != 0:
        raise HTTPException(status_code=400, detail=f"Throughput must be in increments of {STEP_PAGES} pages")
    if not agreed_terms:
        raise HTTPException(status_code=400, detail="You must agree to the terms to submit an inquiry")

    try:
        estimated_price = calculate_price(pages_per_hour)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    user_id = uuid.UUID(user.user_id) if user else None

    inquiry = OnPremiseInquiry(
        user_id=user_id,
        email=email,
        company=company or None,
        contact_name=contact_name or None,
        country=country or None,
        pages_per_hour=pages_per_hour,
        estimated_price=estimated_price,
        message=message or None,
        agreed_terms=agreed_terms,
    )
    db.add(inquiry)
    db.commit()
    db.refresh(inquiry)

    try:
        email_sender.send_on_premise_inquiry_email(db, inquiry)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[on-premise] admin 메일 발송 실패: %s", exc)
        # 메일 실패는 문의 접수를 막지 않는다.

    return {
        "id": str(inquiry.id),
        "estimated_price": estimated_price,
        "message": "Your inquiry has been submitted. Our sales team will contact you via email.",
    }


@router.get("/inquiries")
def list_inquiries(
    admin: CurrentUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """관리자용 온프레미스 문의 목록 조회."""
    inquiries = db.query(OnPremiseInquiry).order_by(OnPremiseInquiry.created_at.desc()).all()
    return [
        {
            "id": str(i.id),
            "user_id": str(i.user_id) if i.user_id else None,
            "email": i.email,
            "company": i.company,
            "contact_name": i.contact_name,
            "country": i.country,
            "pages_per_hour": i.pages_per_hour,
            "estimated_price": i.estimated_price,
            "message": i.message,
            "agreed_terms": i.agreed_terms,
            "status": i.status,
            "created_at": i.created_at.isoformat() if i.created_at else None,
        }
        for i in inquiries
    ]
