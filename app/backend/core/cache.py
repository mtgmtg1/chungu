#!/usr/bin/env python3
# [Flow: Step 1 (Redis 연결 시도) -> Step 2 (get/set/delete/invalidate 연산 제공) -> Step 3 (Redis 사용 불가 시 no-op 폴백)]
import json
import logging
from functools import lru_cache
from typing import Any

import redis

from ..config import settings

logger = logging.getLogger(__name__)


@lru_cache
def get_redis() -> redis.Redis | None:
    """Redis 연결을 반환한다. 연결 실패 시 None을 반환하여 캐시를 비활성화한다."""
    try:
        return redis.from_url(settings.redis_url, decode_responses=True)
    except Exception:  # noqa: BLE001
        logger.warning("[cache] Redis 연결 실패: 캐시가 비활성화됩니다")
        return None


def _serialize(value: Any) -> str:
    """Python 값을 JSON 문자열로 직렬화한다."""
    return json.dumps(value, default=str)


def _deserialize(data: str | bytes | None) -> Any:
    """JSON 문자열을 Python 값으로 역직렬화한다."""
    if data is None:
        return None
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return None


def get(key: str) -> Any:
    """Redis에서 키에 해당하는 값을 조회한다."""
    r = get_redis()
    if r is None:
        return None
    try:
        return _deserialize(r.get(key))
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[cache] get 실패 ({key}): {e}")
        return None


def set(key: str, value: Any, ttl_seconds: int) -> None:
    """Redis에 키-값을 저장하고 TTL을 설정한다."""
    r = get_redis()
    if r is None:
        return
    try:
        r.setex(key, ttl_seconds, _serialize(value))
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[cache] set 실패 ({key}): {e}")


def delete(key: str) -> None:
    """Redis에서 키를 삭제한다."""
    r = get_redis()
    if r is None:
        return
    try:
        r.delete(key)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[cache] delete 실패 ({key}): {e}")


def invalidate_pattern(pattern: str) -> None:
    """Redis에서 패턴과 일치하는 모든 키를 삭제한다."""
    r = get_redis()
    if r is None:
        return
    try:
        keys = r.scan_iter(match=pattern)
        for key in keys:
            r.delete(key)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[cache] invalidate_pattern 실패 ({pattern}): {e}")
