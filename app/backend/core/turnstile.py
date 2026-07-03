#!/usr/bin/env python3
# [Flow: Step 1 (Turnstile 토큰 + IP 수신) -> Step 2 (Spin Worker 경유 siteverify) -> Step 3 (검증 결과 반환)]
"""Cloudflare Turnstile CAPTCHA 토큰 검증 (Spin Worker 경유)."""

import logging

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


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
        logger.warning("[turnstile] token empty")
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
        logger.info(
            "[turnstile] token=%s... ip=%s status=%s result=%s",
            token[:20],
            remote_ip,
            resp.status_code,
            result,
        )
        return result.get("success", False)
    except Exception as exc:
        logger.exception("[turnstile] verification failed: token=%s... ip=%s", token[:20], remote_ip)
        return False
