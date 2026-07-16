#!/usr/bin/env python3
# [Flow: Step 1 (sandbox/Job/DB/User mock 생성) -> Step 2 (ResultCollector/cache monkeypatch)
#       -> Step 3 (collect_results 엔드포인트 직접 호출) -> Step 4 (job.extracted_files 업데이트 및 캐시 무효화 검증)]
"""POST /api/sandboxes/{id}/collect 엔드포인트가 sandbox 결과 파일을 수집하여
job.extracted_files에 반영하고 preview 캐시를 무효화하는지 검증한다."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

from backend.api.sandboxes import collect_results


@pytest.fixture
def mock_sandbox():
    """테스트용 Sandbox mock 객체를 생성한다."""
    sandbox = MagicMock()
    sandbox.id = "sandbox-123"
    sandbox.job_id = "job-123"
    sandbox.user_id = "11111111-1111-1111-1111-111111111111"
    sandbox.workspace_path = ""
    return sandbox


@pytest.fixture
def mock_job():
    """테스트용 Job mock 객체를 생성한다."""
    job = MagicMock()
    job.id = "job-123"
    job.extracted_files = []
    return job


@pytest.fixture
def mock_user():
    """테스트용 CurrentUser mock 객체를 생성한다."""
    user = MagicMock()
    user.user_id = "11111111-1111-1111-1111-111111111111"
    user.is_admin = False
    return user


@pytest.fixture
def mock_db(mock_sandbox, mock_job):
    """테스트용 DB 세션 mock 객체를 생성한다.

    첫 번째 execute는 Sandbox를, 두 번째 execute는 Job을 반환한다.
    """
    db = MagicMock()
    scalar_mock = MagicMock()
    scalar_mock.scalar_one_or_none.side_effect = [mock_sandbox, mock_job]
    db.execute.return_value = scalar_mock
    return db


class FakeCollector:
    """collect_and_upload 호출 시 가짜 수집 결과를 반환하는 Collector mock."""

    def collect_and_upload(self, workspace_path, job_id, supabase_client=None):
        """workspace/agent_output/result.csv가 수집된 것처럼 결과를 반환한다."""
        return {
            "files": [
                {
                    "path": str(Path(workspace_path) / "agent_output" / "result.csv"),
                    "storage_path": "job-123/agent_output/result.csv",
                    "size": 123,
                }
            ],
            "uploaded": 1,
            "failed": 0,
            "total_scanned": 1,
        }


@pytest.mark.anyio
async def test_collect_results_updates_job_extracted_files_and_invalidates_cache(
    mock_sandbox, mock_job, mock_user, mock_db, monkeypatch
):
    """collect_results 호출 시 job.extracted_files가 업데이트되고 preview 캐시가 무효화된다."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        (workspace / "agent_output").mkdir()
        mock_sandbox.workspace_path = str(workspace)

        # [Flow: ResultCollector 싱글톤을 FakeCollector로 교체]
        monkeypatch.setattr("backend.api.sandboxes._get_collector", lambda: FakeCollector())

        # [Flow: 캐시 무효화 패턴을 기록하기 위해 cache.invalidate_pattern 모킹]
        invalidated_patterns = []

        def fake_invalidate_pattern(pattern):
            invalidated_patterns.append(pattern)

        monkeypatch.setattr("backend.api.sandboxes.cache", MagicMock(invalidate_pattern=fake_invalidate_pattern))

        # [Flow: SQLAlchemy flag_modified 모킹 — MagicMock 객체에 적용]
        monkeypatch.setattr("backend.api.sandboxes.flag_modified", lambda obj, attr: None)

        result = await collect_results("sandbox-123", mock_user, mock_db)

        assert result["uploaded"] == 1
        assert result["failed"] == 0
        assert result["total_scanned"] == 1

        # [Flow: job.extracted_files에 수집된 파일이 추가되었는지 검증]
        assert len(mock_job.extracted_files) == 1
        collected = mock_job.extracted_files[0]
        assert collected["storage_path"] == "job-123/agent_output/result.csv"
        assert collected["type"] == "file"
        assert collected["bucket"] == "jobs"
        assert collected["source_kind"] == "agent_output"

        # [Flow: preview 캐시 무효화가 호출되었는지 검증]
        assert any("preview:job-123:*" in pattern for pattern in invalidated_patterns)

        # [Flow: DB commit이 호출되었는지 검증]
        mock_db.commit.assert_called_once()
