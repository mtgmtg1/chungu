#!/usr/bin/env python3
# [Flow: Step 1 (외부 요청 수신) -> Step 2 (auth 경로 보안 검증) -> Step 3 (내부 Supabase로 전달) -> Step 4 (응답 헤더 재작성 + 중계)]
import json
import logging

import httpx
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

logger = logging.getLogger(__name__)

from ..config import settings
from ..core.rate_limit import (
    LOGIN_IP_MAX_FAILS,
    LOGIN_WARNING_THRESHOLD,
    _client_ip,
    check_login_attempts,
    check_signup_rate,
    get_remaining_attempts,
    record_login_failure,
    reset_login_attempts,
)
from ..core.turnstile import verify_turnstile_token

router = APIRouter(prefix="/supabase", tags=["supabase-proxy"])

_TARGET = settings.supabase_url.rstrip("/")
_PUBLIC_URL = (settings.supabase_public_url or "").rstrip("/")

_HOP_HEADERS = frozenset(
    h.lower() for h in (
        "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
        "te", "trailers", "transfer-encoding", "upgrade", "host",
    )
)


def _forward_headers(src: Request) -> dict:
    return {k: v for k, v in src.headers.items() if k.lower() not in _HOP_HEADERS}


def _rewrite_location_header(headers: dict) -> dict:
    """TUS Location 헤더를 내부 URL에서 외부 프록시 URL로 재작성한다."""
    if not _PUBLIC_URL:
        return headers
    for k, v in headers.items():
        if k.lower() == "location" and _TARGET in v:
            headers[k] = v.replace(_TARGET, _PUBLIC_URL)
            break
    return headers


async def _check_auth_security(path: str, request: Request, body: bytes) -> JSONResponse | None:
    """
    Supabase auth 경로에 대한 보안 검증.
    반환: None = 통과, JSONResponse = 차단 응답.
    """
    # [Flow: Step 1 (auth 경로 판별) -> Step 2 (로그인: 시도 제한 + Turnstile) -> Step 3 (회원가입: IP 제한 + Turnstile)]
    is_login = path.startswith("auth/v1/token")
    is_signup = path.startswith("auth/v1/signup")

    if not is_login and not is_signup:
        return None

    ip = _client_ip(request)

    # 요청 바디에서 email / turnstile_token 추출
    # Supabase JS 클라이언트는 gotrue_meta_security.captcha_token으로 전송
    email = ""
    turnstile_token = ""
    try:
        payload = json.loads(body) if body else {}
        email = (payload.get("email") or "").strip()
        turnstile_token = payload.get("turnstile_token") or ""
        if not turnstile_token:
            security = payload.get("gotrue_meta_security") or {}
            turnstile_token = security.get("captcha_token") or ""
    except Exception:
        pass

    logger.info("[supabase_proxy] path=%s email=%s token=%s...", path, email, turnstile_token[:20])

    # Turnstile CAPTCHA 검증 (설정 시에만 활성화)
    if not await verify_turnstile_token(turnstile_token, ip):
        logger.warning("[supabase_proxy] captcha failed for %s", email)
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"error": "bot 확인에 실패했습니다. 다시 시도하세요.", "code": "captcha_failed"},
        )

    if is_login:
        attempt_state = check_login_attempts(ip, email)
        if not attempt_state["allowed"]:
            retry_minutes = max(1, attempt_state["retry_after"] // 60)
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"error": f"로그인 시도가 너무 많습니다. {retry_minutes}분 후 다시 시도하세요.", "code": "too_many_attempts"},
                headers={"Retry-After": str(attempt_state["retry_after"])},
            )

    if is_signup:
        signup_state = check_signup_rate(ip)
        if not signup_state["allowed"]:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"error": "회원가입 시도가 너무 많습니다. 잠시 후 다시 시도하세요.", "code": "too_many_signups"},
                headers={"Retry-After": str(signup_state["retry_after"])},
            )

    return None


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def proxy_supabase(path: str, request: Request):
    # [Flow: Step 1 (auth 경로 보안 검증) -> Step 2 (내부 Supabase로 전달) -> Step 3 (auth 응답 후처리) -> Step 4 (응답 중계)]
    url = f"{_TARGET}/{path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    body = await request.body()

    # auth 경로 보안 검증
    security_response = await _check_auth_security(path, request, body)
    if security_response is not None:
        return security_response

    headers = _forward_headers(request)

    client = httpx.AsyncClient(timeout=300.0, follow_redirects=False)

    req = client.build_request(
        request.method,
        url,
        headers=headers,
        content=body if body else None,
    )
    resp = await client.send(req, stream=True)

    # auth 로그인 응답 후처리: 성공/실패에 따라 카운터 관리
    is_login = path.startswith("auth/v1/token")
    if is_login:
        ip = _client_ip(request)
        email = ""
        try:
            payload = json.loads(body) if body else {}
            email = (payload.get("email") or "").strip()
        except Exception:
            pass

        if resp.status_code == 200:
            reset_login_attempts(ip, email)
        elif resp.status_code == 401:
            record_login_failure(ip, email)
            # 401 응답 바디를 읽고 남은 시도 횟수 주입
            resp_body = await resp.aread()
            await resp.aclose()
            await client.aclose()
            remaining = get_remaining_attempts(ip, email)
            if remaining["locked"]:
                retry_minutes = max(1, remaining["retry_after"] // 60)
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "error": f"로그인 시도가 너무 많습니다. {retry_minutes}분 후 다시 시도하세요.",
                        "code": "too_many_attempts",
                    },
                    headers={"Retry-After": str(remaining["retry_after"])},
                )
            try:
                original = json.loads(resp_body)
            except Exception:
                original = {}
            remaining_attempts = remaining["remaining"]
            if remaining_attempts <= LOGIN_IP_MAX_FAILS - LOGIN_WARNING_THRESHOLD:
                original["remaining_attempts"] = remaining_attempts
            response_headers = {
                k: v for k, v in resp.headers.items()
                if k.lower() not in _HOP_HEADERS
            }
            response_headers = _rewrite_location_header(response_headers)
            response_headers["content-type"] = "application/json"
            return JSONResponse(
                status_code=401,
                content=original,
                headers=response_headers,
            )

    async def stream():
        try:
            async for chunk in resp.aiter_raw():
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    response_headers = {
        k: v for k, v in resp.headers.items() if k.lower() not in _HOP_HEADERS
    }
    response_headers = _rewrite_location_header(response_headers)
    return StreamingResponse(stream(), status_code=resp.status_code, headers=response_headers)
