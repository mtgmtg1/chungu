#!/usr/bin/env python3
# [Flow: Step 1 (요청 도착) -> Step 2 (회로 차단기 상태 확인) -> Step 3 (폴백 가능 여부 판단)]
# PaddleOCR 폴백 제어 모듈 — 회로 차단기(Circuit Breaker) only
# Redis 기반 상태 관리, Redis 불가 시 in-memory fallback
import logging
import threading
import time

from ..config import settings

logger = logging.getLogger(__name__)

# 회로 차단기 상태
CB_CLOSED = "CLOSED"
CB_OPEN = "OPEN"
CB_HALF_OPEN = "HALF_OPEN"


def _now_epoch() -> float:
    """현재 Unix 시간을 반환한다."""
    return time.time()


def _minute_bucket(epoch: float | None = None) -> str:
    """분 단위 버킷 키를 반환한다 (회로 차단기 실패 카운트용)."""
    if epoch is None:
        epoch = _now_epoch()
    return str(int(epoch // 60))


class _InMemoryState:
    """Redis 불가 시 단일 worker 내에서 동작하는 in-memory 상태 저장소."""

    def __init__(self) -> None:
        self.cb_state: str = CB_CLOSED
        self.cb_opened_at: float = 0.0
        self.cb_fail_buckets: dict[str, int] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            if key == "paddleocr:cb:state":
                return self.cb_state
            if key == "paddleocr:cb:opened_at":
                return str(self.cb_opened_at) if self.cb_opened_at else None
            if key.startswith("paddleocr:cb:fail:"):
                return str(self.cb_fail_buckets.get(key, 0))
            return None

    def set(self, key: str, value: str) -> None:
        with self._lock:
            if key == "paddleocr:cb:state":
                self.cb_state = value
            elif key == "paddleocr:cb:opened_at":
                self.cb_opened_at = float(value) if value else 0.0

    def incr(self, key: str, amount: int = 1) -> int:
        with self._lock:
            if key.startswith("paddleocr:cb:fail:"):
                self.cb_fail_buckets[key] = self.cb_fail_buckets.get(key, 0) + amount
                return self.cb_fail_buckets[key]
            return 0

    def expire(self, key: str, seconds: int) -> None:
        pass


class FallbackController:
    """회로 차단기를 관리하는 싱글톤 컨트롤러.

    [Flow: record_failure() -> 1분 윈도우 실패 카운트 -> 3회 이상 시 OPEN 전환]
    [Flow: can_use_fallback() -> fallback_enabled AND 회로 차단기 CLOSED/HALF_OPEN]
    """

    _instance: "FallbackController | None" = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "FallbackController":
        if cls._instance is not None:
            return cls._instance
        with cls._instance_lock:
            if cls._instance is not None:
                return cls._instance
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._redis = None
        self._memory = _InMemoryState()
        self._init_redis()

    def _init_redis(self) -> None:
        """Redis 연결을 시도하고, 실패 시 in-memory fallback을 사용한다."""
        try:
            import redis
            self._redis = redis.from_url(settings.redis_url, decode_responses=True)
            self._redis.ping()
            logger.info("[paddleocr-fallback] Redis 연결 성공")
        except Exception as e:
            logger.warning(f"[paddleocr-fallback] Redis 연결 실패, in-memory fallback 사용: {e}")
            self._redis = None

    def _get(self, key: str) -> str | None:
        """Redis 또는 in-memory에서 키 값을 조회한다."""
        if self._redis:
            return self._redis.get(key)
        return self._memory.get(key)

    def _set(self, key: str, value: str) -> None:
        """Redis 또는 in-memory에 키 값을 저장한다."""
        if self._redis:
            self._redis.set(key, value)
        else:
            self._memory.set(key, value)

    def _incr(self, key: str, amount: int = 1) -> int:
        """Redis 또는 in-memory에서 키 값을 증가시킨다."""
        if self._redis:
            return self._redis.incrby(key, amount)
        return self._memory.incr(key, amount)

    def _expire(self, key: str, seconds: int) -> None:
        """Redis 또는 in-memory에서 키에 TTL을 설정한다."""
        if self._redis:
            self._redis.expire(key, seconds)
        else:
            self._memory.expire(key, seconds)

    # ─── 회로 차단기 (Circuit Breaker) ───

    def record_failure(self) -> None:
        """기본 요청 실패를 기록하고, 1분 내 3회 이상 실패 시 회로를 OPEN으로 전환한다.

        [Flow: Step 1 (분 버킷 실패 카운트 +1) -> Step 2 (1분 내 총 실패 수 계산) -> Step 3 (임계값 초과 시 OPEN 전환)]
        """
        now = _now_epoch()
        bucket = _minute_bucket(now)
        fail_key = f"paddleocr:cb:fail:{bucket}"
        count = self._incr(fail_key)
        self._expire(fail_key, 120)  # 2분 TTL

        # 최근 1분 윈도우의 실패 수 합산
        prev_bucket = _minute_bucket(now - 60)
        prev_key = f"paddleocr:cb:fail:{prev_bucket}"
        prev_val = self._get(prev_key)
        prev_count = int(prev_val) if prev_val else 0
        total_failures = count + prev_count

        threshold = settings.paddleocr_fallback_failure_threshold
        if total_failures >= threshold:
            current_state = self._get("paddleocr:cb:state") or CB_CLOSED
            if current_state != CB_OPEN:
                self._set("paddleocr:cb:state", CB_OPEN)
                self._set("paddleocr:cb:opened_at", str(now))
                logger.warning(
                    f"[paddleocr-fallback] 회로 차단기 OPEN 전환: "
                    f"failures={total_failures} >= threshold={threshold}"
                )

    def record_success(self) -> None:
        """기본 요청 성공을 기록하고, HALF_OPEN 상태에서 CLOSED로 복귀한다."""
        current_state = self._get("paddleocr:cb:state")
        if current_state == CB_HALF_OPEN:
            self._set("paddleocr:cb:state", CB_CLOSED)
            self._set("paddleocr:cb:opened_at", "0")
            logger.info("[paddleocr-fallback] 회로 차단기 CLOSED 복귀 (HALF_OPEN → 성공)")

    def _check_and_transition(self) -> str:
        """현재 회로 차단기 상태를 확인하고, 필요 시 상태 전환을 수행한다.

        [Flow: Step 1 (현재 상태 조회) -> Step 2 (OPEN + 경과 시간 확인 -> HALF_OPEN) -> Step 3 (상태 반환)]
        """
        state = self._get("paddleocr:cb:state") or CB_CLOSED

        if state == CB_OPEN:
            opened_at = float(self._get("paddleocr:cb:opened_at") or "0")
            elapsed = _now_epoch() - opened_at
            if elapsed >= settings.paddleocr_fallback_open_seconds:
                self._set("paddleocr:cb:state", CB_HALF_OPEN)
                logger.info(
                    f"[paddleocr-fallback] 회로 차단기 HALF_OPEN 전환: "
                    f"elapsed={elapsed:.0f}s >= open_seconds={settings.paddleocr_fallback_open_seconds}"
                )
                return CB_HALF_OPEN

        return state

    def is_fallback_preferred(self) -> bool:
        """폴백을 우선시할지 여부를 반환한다.

        임시: vLLM/Docling 서버 개선 전까지 항상 True를 반환하여 PaddleOCR을 우선 사용.

        Returns:
            True (항상 — 임시 정책)
        """
        if not settings.paddleocr_fallback_enabled:
            return False

        return True

    def can_use_fallback(self) -> bool:
        """폴백 사용 가능 여부를 반환한다.

        Returns:
            True if fallback_enabled AND 회로 차단기가 OPEN이 아님
        """
        if not settings.paddleocr_fallback_enabled:
            return False

        state = self._check_and_transition()
        if state == CB_OPEN:
            return False

        return True

    def consume_fallback(self) -> None:
        """폴백 사용을 기록한다 (현재 no-op — 한도 은행 제거됨)."""
        pass

    # ─── 통합 인터페이스 ───

    def get_status(self) -> dict:
        """현재 폴백 시스템 상태를 반환한다 (모니터링용).

        Returns:
            회로 차단기 상태를 포함한 dict
        """
        state = self._check_and_transition()

        return {
            "circuit_breaker_state": state,
            "fallback_enabled": settings.paddleocr_fallback_enabled,
        }


# 싱글톤 인스턴스
fallback_controller = FallbackController()
