#!/usr/bin/env python3
# [Flow: Step 1 (로그인 -> 세션 쿠키) -> Step 2 (설정 조회/수정) -> Step 3 (LLM/SMTP 연결 테스트) -> Step 4 (job 모니터)]
import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from .. import email_sender, settings_store
from ..auth.security import (
    COOKIE_NAME,
    SESSION_HOURS,
    create_token,
    hash_password,
    require_admin,
    verify_password,
)
from ..core import ocr_client
from ..core.password_security import validate_password_strength
from ..core.rate_limit import (
    LOGIN_IP_MAX_FAILS,
    LOGIN_WARNING_THRESHOLD,
    _client_ip,
    check_login_attempts,
    get_remaining_attempts,
    record_login_failure,
    reset_login_attempts,
)
from ..core.turnstile import verify_turnstile_token
from ..db.models import AdminUser, Job
from ..db.session import get_db

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/login")
async def login(request: Request, response: Response, payload: dict = Body(...), db: Session = Depends(get_db)):
    # [Flow: Step 1 (Turnstile 검증) -> Step 2 (로그인 시도 제한 확인) -> Step 3 (비밀번호 검증) -> Step 4 (세션 쿠키 발급)]
    email = (payload.get("email") or "").strip()
    password = payload.get("password") or ""
    ip = _client_ip(request)

    # Turnstile CAPTCHA 검증 (설정 시에만 활성화)
    turnstile_token = payload.get("turnstile_token") or ""
    logger.info("[admin_login] email=%s token=%s... ip=%s", email, turnstile_token[:20], ip)
    if not await verify_turnstile_token(turnstile_token, ip):
        logger.warning("[admin_login] captcha failed for %s", email)
        raise HTTPException(status_code=403, detail="Bot verification failed. Please try again.")

    # 로그인 시도 제한 확인
    attempt_state = check_login_attempts(ip, email)
    if not attempt_state["allowed"]:
        retry_minutes = max(1, attempt_state["retry_after"] // 60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many login attempts. Please try again in {retry_minutes} minutes.",
            headers={"Retry-After": str(attempt_state["retry_after"])},
        )

    user = db.execute(select(AdminUser).where(AdminUser.email == email)).scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        record_login_failure(ip, email)
        remaining = get_remaining_attempts(ip, email)
        if remaining["locked"]:
            retry_minutes = max(1, remaining["retry_after"] // 60)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many login attempts. Please try again in {retry_minutes} minutes.",
                headers={"Retry-After": str(remaining["retry_after"])},
            )
        detail = "Invalid email or password"
        if remaining["remaining"] <= LOGIN_IP_MAX_FAILS - LOGIN_WARNING_THRESHOLD:
            detail += f" (remaining attempts: {remaining['remaining']})"
        raise HTTPException(status_code=401, detail=detail)

    reset_login_attempts(ip, email)
    token = create_token(email)
    response.set_cookie(
        key=COOKIE_NAME, value=token, httponly=True, samesite="lax", path="/",
        max_age=SESSION_HOURS * 3600,
    )
    return {"ok": True, "email": email}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(admin: str = Depends(require_admin)):
    return {"email": admin}


@router.post("/password")
def change_password(payload: dict = Body(...), admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    current = payload.get("current_password") or ""
    new = payload.get("new_password") or ""
    strength = validate_password_strength(new)
    if not strength["valid"]:
        if "too_short" in strength["issues"]:
            raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
        raise HTTPException(status_code=400, detail="Password must include at least 3 of: uppercase, lowercase, numbers, special characters")
    user = db.execute(select(AdminUser).where(AdminUser.email == admin)).scalar_one_or_none()
    if user is None or not verify_password(current, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    user.password_hash = hash_password(new)
    db.commit()
    return {"ok": True}


@router.get("/settings")
def get_settings(admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    return settings_store.get_all(db, mask_secrets=True)


@router.put("/settings")
def update_settings(payload: dict = Body(...), admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    settings_store.update_many(db, payload)
    return settings_store.get_all(db, mask_secrets=True)


@router.post("/settings/test-llm")
def test_llm(admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    endpoint = settings_store.get_setting(db, "llm_endpoint")
    model = settings_store.get_setting(db, "llm_model")
    api_key = settings_store.get_setting(db, "llm_api_key")
    try:
        content, _ = ocr_client.call_text("'OK'만 출력하세요.", endpoint, model, api_key, max_tokens=10)
        return {"ok": True, "reply": content[:100]}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM connection failed: {e}")


@router.post("/settings/test-smtp")
def test_smtp(payload: dict = Body(default={}), admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    to = (payload.get("to") or admin).strip()
    try:
        email_sender.send_test_email(db, to)
        return {"ok": True, "to": to}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"SMTP send failed: {e}")


@router.get("/jobs")
def list_jobs(admin: str = Depends(require_admin), limit: int = 100, db: Session = Depends(get_db)):
    rows = db.execute(select(Job).order_by(Job.created_at.desc()).limit(limit)).scalars().all()
    return [
        {
            "job_id": j.id,
            "email": j.email,
            "status": j.status,
            "pipeline": j.pipeline,
            "file_type": j.file_type,
            "filename": j.original_filename,
            "total_pages": j.total_pages,
            "done_pages": j.done_pages,
            "total_files": j.total_files,
            "done_files": j.done_files,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        }
        for j in rows
    ]
