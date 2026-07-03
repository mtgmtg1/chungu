#!/usr/bin/env python3
# [Flow: Step 1 (Redis 연결) -> Step 2 (sliding window 카운트) -> Step 3 (limit 초과 여부 반환)]
import time
from functools import lru_cache

import redis
from fastapi import HTTPException, Request, status

from ..config import settings


@lru_cache
def get_redis() -> redis.Redis | None:
    try:
        return redis.from_url(settings.redis_url, decode_responses=True)
    except Exception:  # noqa: BLE001
        return None


def _key(api_key_id: str, window_seconds: int) -> str:
    now = int(time.time())
    bucket = now // window_seconds
    return f"rate_limit:{api_key_id}:{bucket}"


def check_rate_limit(api_key_id: str, limit: int, window_seconds: int = 60) -> dict:
    """Sliding window rate limit. 남은 횟수와 reset 시각을 반환."""
    r = get_redis()
    if r is None:
        return {"allowed": True, "remaining": limit, "reset_at": int(time.time()) + window_seconds}

    key = _key(api_key_id, window_seconds)
    current = r.incr(key)
    if current == 1:
        r.expire(key, window_seconds)

    remaining = max(0, limit - current)
    ttl = r.ttl(key)
    reset_at = int(time.time()) + (ttl if ttl > 0 else window_seconds)

    if current > limit:
        return {"allowed": False, "remaining": 0, "reset_at": reset_at}
    return {"allowed": True, "remaining": remaining, "reset_at": reset_at}


def enforce_rate_limit(request: Request, api_key_id: str, limit: int) -> None:
    result = check_rate_limit(api_key_id, limit)
    if not result["allowed"]:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="요청 제한을 초과했습니다. 잠시 후 다시 시도하세요.",
            headers={"Retry-After": str(result["reset_at"] - int(time.time()))},
        )
    request.state.rate_limit_remaining = result["remaining"]
    request.state.rate_limit_reset = result["reset_at"]


def get_daily_spent_points(api_key_id: str) -> int:
    """당일 API key로 차감된 포인트 합계."""
    r = get_redis()
    if r is None:
        return 0
    key = f"api_daily_points:{api_key_id}:{int(time.time()) // 86400}"
    val = r.get(key)
    return int(val or 0)


def add_daily_spent_points(api_key_id: str, points: int) -> None:
    r = get_redis()
    if r is None:
        return
    key = f"api_daily_points:{api_key_id}:{int(time.time()) // 86400}"
    pipe = r.pipeline()
    pipe.incrby(key, points)
    pipe.expire(key, 86400)
    pipe.execute()


# ── 로그인 시도 제한 (무차별 대입 방어) ──────────────────────────────
LOGIN_LOCK_MINUTES = 15
LOGIN_LOCK_SECONDS = LOGIN_LOCK_MINUTES * 60
LOGIN_IP_MAX_FAILS = 10
LOGIN_EMAIL_MAX_FAILS = 5
LOGIN_WARNING_THRESHOLD = 3
SIGNUP_IP_MAX_HOURLY = 5


def _client_ip(request: Request) -> str:
    """Cloudflare / 프록시 헤더를 고려하여 클라이언트 IP 추출."""
    # [Flow: Step 1 (CF-Connecting-IP 확인) -> Step 2 (X-Forwarded-For 확인) -> Step 3 (client.host)]
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_login_attempts(ip: str, email: str = "") -> dict:
    """로그인 잠금 상태 확인. 잠금 중이면 allowed=False와 남은 시간 반환."""
    r = get_redis()
    if r is None:
        return {"allowed": True, "remaining_ip": LOGIN_IP_MAX_FAILS, "remaining_email": LOGIN_EMAIL_MAX_FAILS, "retry_after": 0}

    ip_key = f"login_fail:{ip}"
    ip_count = int(r.get(ip_key) or 0)
    email_count = 0
    if email:
        email_key = f"login_fail:{email}"
        email_count = int(r.get(email_key) or 0)

    ip_locked = ip_count >= LOGIN_IP_MAX_FAILS
    email_locked = email_count >= LOGIN_EMAIL_MAX_FAILS

    if ip_locked or email_locked:
        ttl = max(r.ttl(ip_key), r.ttl(f"login_fail:{email}") if email else 0)
        retry_after = ttl if ttl > 0 else LOGIN_LOCK_SECONDS
        return {"allowed": False, "remaining_ip": 0, "remaining_email": 0, "retry_after": retry_after}

    return {
        "allowed": True,
        "remaining_ip": LOGIN_IP_MAX_FAILS - ip_count,
        "remaining_email": LOGIN_EMAIL_MAX_FAILS - email_count if email else LOGIN_EMAIL_MAX_FAILS,
        "retry_after": 0,
    }


def record_login_failure(ip: str, email: str = "") -> None:
    """로그인 실패 시 IP 및 이메일 카운터 증가 (TTL 15분)."""
    r = get_redis()
    if r is None:
        return
    pipe = r.pipeline()
    ip_key = f"login_fail:{ip}"
    pipe.incr(ip_key)
    pipe.expire(ip_key, LOGIN_LOCK_SECONDS)
    if email:
        email_key = f"login_fail:{email}"
        pipe.incr(email_key)
        pipe.expire(email_key, LOGIN_LOCK_SECONDS)
    pipe.execute()


def reset_login_attempts(ip: str, email: str = "") -> None:
    """로그인 성공 시 카운터 초기화."""
    r = get_redis()
    if r is None:
        return
    r.delete(f"login_fail:{ip}")
    if email:
        r.delete(f"login_fail:{email}")


def get_remaining_attempts(ip: str, email: str = "") -> dict:
    """
    현재 남은 로그인 시도 횟수 반환 (실패 기록 후 호출).
    반환: {remaining: int, locked: bool, retry_after: int}
    """
    state = check_login_attempts(ip, email)
    if not state["allowed"]:
        return {"remaining": 0, "locked": True, "retry_after": state["retry_after"]}
    remaining = min(state["remaining_ip"], state["remaining_email"])
    return {"remaining": remaining, "locked": False, "retry_after": 0}


def check_signup_rate(ip: str) -> dict:
    """회원가입 IP당 시간당 제한 (5회/시간)."""
    r = get_redis()
    if r is None:
        return {"allowed": True, "remaining": SIGNUP_IP_MAX_HOURLY, "retry_after": 0}

    key = f"signup_count:{ip}:{int(time.time()) // 3600}"
    current = int(r.get(key) or 0)
    if current >= SIGNUP_IP_MAX_HOURLY:
        ttl = r.ttl(key)
        return {"allowed": False, "remaining": 0, "retry_after": ttl if ttl > 0 else 3600}

    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, 3600)
    pipe.execute()

    return {"allowed": True, "remaining": SIGNUP_IP_MAX_HOURLY - current - 1, "retry_after": 0}
