#!/usr/bin/env python3
# [Flow: Step 1 (Turnstile 토큰 + IP 수신) -> Step 2 (Spin Worker 경유 siteverify) -> Step 3 (검증 결과 반환)]
"""Cloudflare Turnstile CAPTCHA 토큰 검증 (Spin Worker 경유)."""

import httpx

from ..config import settings


async def verify_turnstile_token(token: str, remote_ip: str = "") -> bool:
    """
    Spin Worker 경유로 Turnstile 토큰 검증.
    반환: True = 검증 통과, False = 검증 실패 또는 설정 미구성.
    site key가 설정되지 않은 경우 (개발 환경 등) True 반환 (CAPTCHA 미사용).
    """
    site_key = getattr(settings, "turnstile_site_key", "")
    worker_url = getattr(settings, "turnstile_worker_url", "")

    if not site_key or not worker_url:
        return True

    if not token:
        return False

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                worker_url,
                json={
                    "token": token,
                    "remoteip": remote_ip,
                },
            )
        result = resp.json()
        return result.get("success", False)
    except Exception:
        return False
