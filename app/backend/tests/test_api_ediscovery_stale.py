#!/usr/bin/env python3
"""[Flow: Step 1 (필요한 helper import) -> Step 2 (_is_ediscovery_stale 단위 테스트)
      -> Step 3 (다양한 stale 시나리오 검증 — 빈 job_id / Celery 종료 상태 / 타임아웃)]

ediscovery API의 stale "processing" 감지 헬퍼(_is_ediscovery_stale)를 검증한다.
Celery 결과 백엔드와 DB를 mock하여 순수 로직만 테스트한다.
"""
import sys
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

# [Flow: backend 패키지 루트를 sys.path에 추가]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

from backend.api.ediscovery import _is_ediscovery_stale, EDISCOVERY_STALE_TIMEOUT_SECONDS


def _make_job(status="processing", job_id="", task_id="", started_at=None):
    """테스트용 Job mock 객체를 생성한다.

    매개변수:
        status: ediscovery_status 값
        job_id: Job.id 값
        task_id: ediscovery_job_id 값 (빈값이면 stale)
        started_at: ediscovery_params.started_at ISO 문자열
    반환값: MagicMock Job 객체
    """
    job = MagicMock()
    job.id = job_id or "test-job-123"
    job.ediscovery_status = status
    job.ediscovery_job_id = task_id
    params = {}
    if started_at:
        params["started_at"] = started_at
    job.ediscovery_params = params
    return job


def test_stale_not_processing_returns_false():
    """ediscovery_status가 'processing'이 아니면 항상 False를 반환한다."""
    job = _make_job(status="done", task_id="task-abc")
    assert _is_ediscovery_stale(job, db=MagicMock()) is False

    job_err = _make_job(status="error", task_id="task-abc")
    assert _is_ediscovery_stale(job_err, db=MagicMock()) is False

    job_empty = _make_job(status="", task_id="task-abc")
    assert _is_ediscovery_stale(job_empty, db=MagicMock()) is False


def test_stale_empty_task_id_returns_true():
    """processing 상태지만 ediscovery_job_id가 비어있으면 stale로 판정한다."""
    job = _make_job(status="processing", task_id="")
    assert _is_ediscovery_stale(job, db=MagicMock()) is True

    job_none = _make_job(status="processing", task_id=None)
    assert _is_ediscovery_stale(job_none, db=MagicMock()) is True


def test_stale_celery_failure_state_returns_true():
    """Celery 태스크 상태가 FAILURE/REVOKED/SUCCESS면 stale로 판정한다."""
    db = MagicMock()
    for terminal_state in ("SUCCESS", "FAILURE", "REVOKED"):
        job = _make_job(status="processing", task_id=f"task-{terminal_state}")
        with patch("backend.celery_app.celery.AsyncResult") as mock_ar:
            mock_result = MagicMock()
            mock_result.state = terminal_state
            mock_ar.return_value = mock_result
            assert _is_ediscovery_stale(job, db) is True, f"state={terminal_state} should be stale"


def test_stale_celery_running_state_returns_false():
    """Celery 태스크 상태가 PENDING/STARTED/RETRY면 stale이 아니다 (실행 중)."""
    db = MagicMock()
    for active_state in ("PENDING", "STARTED", "RETRY"):
        job = _make_job(status="processing", task_id=f"task-{active_state}")
        with patch("backend.celery_app.celery.AsyncResult") as mock_ar:
            mock_result = MagicMock()
            mock_result.state = active_state
            mock_ar.return_value = mock_result
            assert _is_ediscovery_stale(job, db) is False, f"state={active_state} should not be stale"


def test_stale_celery_exception_returns_true():
    """Celery 결과 백엔드 조회 중 예외 발생 시 안전하게 stale로 간주한다."""
    job = _make_job(status="processing", task_id="task-xyz")
    db = MagicMock()
    with patch("backend.celery_app.celery.AsyncResult", side_effect=ConnectionError("Redis down")):
        assert _is_ediscovery_stale(job, db) is True


def test_stale_timeout_exceeded_returns_true():
    """started_at 기준 EDISCOVERY_STALE_TIMEOUT_SECONDS 초과 시 stale로 판정한다."""
    old_time = (datetime.now(timezone.utc) - timedelta(seconds=EDISCOVERY_STALE_TIMEOUT_SECONDS + 60))
    job = _make_job(
        status="processing",
        task_id="task-timeout",
        started_at=old_time.isoformat(),
    )
    db = MagicMock()
    with patch("backend.celery_app.celery.AsyncResult") as mock_ar:
        mock_result = MagicMock()
        mock_result.state = "STARTED"  # Celery는 실행 중이지만 타임아웃 초과
        mock_ar.return_value = mock_result
        assert _is_ediscovery_stale(job, db) is True


def test_stale_within_timeout_returns_false():
    """started_at 기준 타임아웃 이내이고 Celery도 실행 중이면 stale이 아니다."""
    recent_time = datetime.now(timezone.utc)
    job = _make_job(
        status="processing",
        task_id="task-recent",
        started_at=recent_time.isoformat(),
    )
    db = MagicMock()
    with patch("backend.celery_app.celery.AsyncResult") as mock_ar:
        mock_result = MagicMock()
        mock_result.state = "STARTED"
        mock_ar.return_value = mock_result
        assert _is_ediscovery_stale(job, db) is False


def test_stale_invalid_started_at_ignored():
    """started_at이 파싱 불가능한 값이면 타임아웃 판정을 스킵하고 Celery 상태만 확인한다."""
    job = _make_job(
        status="processing",
        task_id="task-bad-ts",
        started_at="not-a-date",
    )
    db = MagicMock()
    with patch("backend.celery_app.celery.AsyncResult") as mock_ar:
        mock_result = MagicMock()
        mock_result.state = "STARTED"
        mock_ar.return_value = mock_result
        assert _is_ediscovery_stale(job, db) is False
