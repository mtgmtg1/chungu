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
