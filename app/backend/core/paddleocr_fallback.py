#!/usr/bin/env python3
# [Flow: Step 1 (요청 도착) -> Step 2 (한도 은행 정산) -> Step 3 (회로 차단기 상태 확인) -> Step 4 (폴백 가능 여부 판단) -> Step 5 (폴백 사용 시 카운터 차감)]
# PaddleOCR 폴백 제어 모듈 — 회로 차단기(Circuit Breaker) + 한도 은행(Limit Bank)
# Redis 기반 상태 관리, Redis 불가 시 in-memory fallback
import logging
import threading
import time
from datetime import datetime, timezone

from ..config import settings

logger = logging.getLogger(__name__)

# 회로 차단기 상태
CB_CLOSED = "CLOSED"
CB_OPEN = "OPEN"
CB_HALF_OPEN = "HALF_OPEN"


def _now_epoch() -> float:
    """현재 Unix 시간을 반환한다."""
    return time.time()


def _hour_key(dt: datetime | None = None) -> str:
    """시간 단위 키를 YYYYMMDDHH 형식으로 반환한다."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%Y%m%d%H")


def _day_key(dt: datetime | None = None) -> str:
    """일일 단위 키를 YYYYMMDD 형식으로 반환한다."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%Y%m%d")


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
        self.bank_balance: int = 0
        self.bank_last_hour: str = _hour_key()
        self.bank_hourly: dict[str, int] = {}
        self.bank_daily: dict[str, int] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            if key == "paddleocr:cb:state":
                return self.cb_state
            if key == "paddleocr:cb:opened_at":
                return str(self.cb_opened_at) if self.cb_opened_at else None
            if key == "paddleocr:bank:balance":
                return str(self.bank_balance)
            if key == "paddleocr:bank:last_hour":
                return self.bank_last_hour
            if key.startswith("paddleocr:cb:fail:"):
                return str(self.cb_fail_buckets.get(key, 0))
            if key.startswith("paddleocr:bank:hour:"):
                return str(self.bank_hourly.get(key, 0))
            if key.startswith("paddleocr:bank:day:"):
                return str(self.bank_daily.get(key, 0))
            return None

    def set(self, key: str, value: str) -> None:
        with self._lock:
            if key == "paddleocr:cb:state":
                self.cb_state = value
            elif key == "paddleocr:cb:opened_at":
                self.cb_opened_at = float(value) if value else 0.0
            elif key == "paddleocr:bank:balance":
                self.bank_balance = int(value)
            elif key == "paddleocr:bank:last_hour":
                self.bank_last_hour = value

    def incr(self, key: str, amount: int = 1) -> int:
        with self._lock:
            if key.startswith("paddleocr:cb:fail:"):
                self.cb_fail_buckets[key] = self.cb_fail_buckets.get(key, 0) + amount
                return self.cb_fail_buckets[key]
            if key.startswith("paddleocr:bank:hour:"):
                self.bank_hourly[key] = self.bank_hourly.get(key, 0) + amount
                return self.bank_hourly[key]
            if key.startswith("paddleocr:bank:day:"):
                self.bank_daily[key] = self.bank_daily.get(key, 0) + amount
                return self.bank_daily[key]
            if key == "paddleocr:bank:balance":
                self.bank_balance += amount
                return self.bank_balance
            return 0

    def expire(self, key: str, seconds: int) -> None:
        # in-memory에서는 TTL 미지원 (lazy cleanup은 호출부에서 처리)
        pass


class FallbackController:
    """회로 차단기와 한도 은행을 통합 관리하는 싱글톤 컨트롤러.

    [Flow: record_failure() -> 1분 윈도우 실패 카운트 -> 3회 이상 시 OPEN 전환]
    [Flow: _settle_bank() -> 경과 시간 × 시간당 할당량을 잔액에 적립 -> 상한 20000]
    [Flow: can_use_fallback() -> 잔액 > 0 AND 일일 한도 미초과]
    [Flow: consume_fallback() -> 잔액 -1, 시간/일 카운터 +1]
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

    # ─── 한도 은행 (Limit Bank) ───

    def _settle_bank(self) -> None:
        """경과한 시간에 대해 미사용 시간당 할당량을 잔액에 적립한다.

        [Flow: Step 1 (last_hour와 현재 시간 비교) -> Step 2 (경과 시간 × 할당량을 잔액에 적립) -> Step 3 (상한 20000 적용) -> Step 4 (last_hour 업데이트)]
        """
        current_hour = _hour_key()
        last_hour = self._get("paddleocr:bank:last_hour") or current_hour

        if last_hour == current_hour:
            return

        # 경과한 시간 수 계산
        try:
            last_dt = datetime.strptime(last_hour, "%Y%m%d%H").replace(tzinfo=timezone.utc)
            current_dt = datetime.strptime(current_hour, "%Y%m%d%H").replace(tzinfo=timezone.utc)
            hours_elapsed = int((current_dt - last_dt).total_seconds() / 3600)
        except (ValueError, TypeError):
            hours_elapsed = 0

        if hours_elapsed <= 0:
            return

        quota = settings.paddleocr_fallback_hourly_quota
        accrued = hours_elapsed * quota
        current_balance = int(self._get("paddleocr:bank:balance") or "0")
        new_balance = min(current_balance + accrued, settings.paddleocr_fallback_daily_limit)

        self._set("paddleocr:bank:balance", str(new_balance))
        self._set("paddleocr:bank:last_hour", current_hour)

        if accrued > 0:
            logger.info(
                f"[paddleocr-fallback] 한도 은행 적립: +{accrued} "
                f"({hours_elapsed}h × {quota}), 잔액={new_balance}/{settings.paddleocr_fallback_daily_limit}"
            )

    def can_use_fallback(self) -> bool:
        """폴백 사용 가능 여부를 반환한다 (잔액 > 0 AND 일일 한도 미초과).

        Returns:
            True if 잔액 > 0 and 일일 사용량 < 일일 한도
        """
        if not settings.paddleocr_fallback_enabled:
            return False

        self._settle_bank()

        balance = int(self._get("paddleocr:bank:balance") or "0")
        if balance <= 0:
            return False

        day_key = f"paddleocr:bank:day:{_day_key()}"
        daily_used = int(self._get(day_key) or "0")
        if daily_used >= settings.paddleocr_fallback_daily_limit:
            logger.warning(
                f"[paddleocr-fallback] 일일 한도 초과: {daily_used}/{settings.paddleocr_fallback_daily_limit}"
            )
            return False

        return True

    def consume_fallback(self) -> None:
        """폴백 사용을 기록한다: 잔액 -1, 시간/일 카운터 +1.

        [Flow: Step 1 (잔액 차감) -> Step 2 (시간당 카운터 +1) -> Step 3 (일일 카운터 +1)]
        """
        self._incr("paddleocr:bank:balance", -1)

        hour_key = f"paddleocr:bank:hour:{_hour_key()}"
        self._incr(hour_key)
        self._expire(hour_key, 90000)  # 25시간 TTL

        day_key = f"paddleocr:bank:day:{_day_key()}"
        self._incr(day_key)
        self._expire(day_key, 172800)  # 48시간 TTL

        balance = int(self._get("paddleocr:bank:balance") or "0")
        logger.debug(f"[paddleocr-fallback] 폴백 사용 기록: 잔액={balance}")

    # ─── 통합 인터페이스 ───

    def get_status(self) -> dict:
        """현재 폴백 시스템 상태를 반환한다 (모니터링용).

        Returns:
            회로 차단기 상태, 잔액, 시간/일 사용량을 포함한 dict
        """
        self._settle_bank()
        state = self._check_and_transition()
        balance = int(self._get("paddleocr:bank:balance") or "0")
        hour_key = f"paddleocr:bank:hour:{_hour_key()}"
        day_key = f"paddleocr:bank:day:{_day_key()}"
        hourly_used = int(self._get(hour_key) or "0")
        daily_used = int(self._get(day_key) or "0")

        return {
            "circuit_breaker_state": state,
            "bank_balance": balance,
            "hourly_used": hourly_used,
            "hourly_quota": settings.paddleocr_fallback_hourly_quota,
            "daily_used": daily_used,
            "daily_limit": settings.paddleocr_fallback_daily_limit,
            "fallback_enabled": settings.paddleocr_fallback_enabled,
        }


# 싱글톤 인스턴스
fallback_controller = FallbackController()
