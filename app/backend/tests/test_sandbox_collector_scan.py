#!/usr/bin/env python3
# [Flow: Step 1 (workspace 디렉토리 구조 생성) -> Step 2 (파일 생성 + mtime 제어)
#       -> Step 3 (scan_workspace 호출) -> Step 4 (수집 대상/제외 대상 검증)]
"""ResultCollector의 전체 workspace 스캔 및 mtime 기반 필터링을 검증한다.

핵심 시나리오:
  - agent_output/, extracted/, annotations/ 외의 경로(예: /workspace 루트)에
    생성된 파일도 스캔 대상에 포함되어야 한다.
  - original/ (입력 파일), .git/, .agent_log/ 등은 제외되어야 한다.
  - since_timestamp 이후에 수정된 파일만 업로드 대상이 되어야 한다.
  - Supabase upload 시 기존 파일이 있으면 upsert로 덮어쓰기해야 한다.
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

from backend.core.sandbox.collector import ResultCollector


# ========================================
# 헬퍼: 파일 생성 후 mtime을 지정된 시각으로 설정
# ========================================
def _create_file(path: Path, content: str = "test", mtime_offset: float = 0) -> Path:
    """파일을 생성하고 mtime을 현재 시각 + offset(초)로 설정한다.

    매개변수:
        path: 생성할 파일 경로
        content: 파일 내용
        mtime_offset: mtime 오프셋 (양수=미래, 음수=과거)

    반환값:
        생성된 파일 경로
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    target_mtime = time.time() + mtime_offset
    os.utime(path, (target_mtime, target_mtime))
    return path


class TestScanWorkspaceFullScan:
    """scan_workspace가 COLLECT_DIRS 외의 경로도 스캔하는지 검증."""

    def test_scan_includes_workspace_root_files(self):
        """[Flow: /workspace 루트에 생성된 파일이 스캔 결과에 포함되는지 검증]"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            collector = ResultCollector(workspace_root=workspace)

            # /workspace 루트에 파일 생성 (agent_output 외부)
            _create_file(workspace / "output.csv", "a,b,c")

            files = collector.scan_workspace(workspace)

            relative_paths = [f["relative_path"] for f in files]
            assert "output.csv" in relative_paths, (
                f"workspace 루트의 파일이 스캔되지 않음: {relative_paths}"
            )

    def test_scan_includes_nested_directories(self):
        """[Flow: /workspace/subdir/deep.csv 같은 중첩 경로도 스캔되는지 검증]"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            collector = ResultCollector(workspace_root=workspace)

            _create_file(workspace / "reports" / "deep.csv", "x,y,z")

            files = collector.scan_workspace(workspace)

            relative_paths = [f["relative_path"] for f in files]
            assert "reports/deep.csv" in relative_paths, (
                f"중첩 디렉토리 파일이 스캔되지 않음: {relative_paths}"
            )

    def test_scan_excludes_original_directory(self):
        """[Flow: original/ 디렉토리(입력 파일)는 스캔에서 제외되는지 검증]"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            collector = ResultCollector(workspace_root=workspace)

            _create_file(workspace / "original" / "input.pdf", "fake pdf")
            _create_file(workspace / "agent_output" / "result.csv", "ok")

            files = collector.scan_workspace(workspace)

            relative_paths = [f["relative_path"] for f in files]
            assert not any("original/" in p for p in relative_paths), (
                f"original/ 이 스캔에 포함됨: {relative_paths}"
            )
            assert "agent_output/result.csv" in relative_paths

    def test_scan_excludes_git_and_agent_log(self):
        """[Flow: .git/, .agent_log/ 디렉토리는 제외되는지 검증]"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            collector = ResultCollector(workspace_root=workspace)

            _create_file(workspace / ".git" / "config", "git config")
            _create_file(workspace / ".agent_log" / "log.txt", "log")
            _create_file(workspace / "agent_output" / "out.csv", "ok")

            files = collector.scan_workspace(workspace)

            relative_paths = [f["relative_path"] for f in files]
            assert not any(".git/" in p for p in relative_paths)
            assert not any(".agent_log/" in p for p in relative_paths)
            assert "agent_output/out.csv" in relative_paths

    def test_scan_excludes_file_mapping_and_gitignore(self):
        """[Flow: _file_mapping.json, .gitignore 등 메타데이터 파일은 제외]"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            collector = ResultCollector(workspace_root=workspace)

            _create_file(workspace / "_file_mapping.json", "{}")
            _create_file(workspace / ".gitignore", "*.tmp")
            _create_file(workspace / "agent_output" / "data.csv", "ok")

            files = collector.scan_workspace(workspace)

            relative_paths = [f["relative_path"] for f in files]
            assert "_file_mapping.json" not in relative_paths
            assert ".gitignore" not in relative_paths
            assert "agent_output/data.csv" in relative_paths


class TestCollectAndUploadMtimeFilter:
    """collect_and_upload의 mtime 기반 필터링을 검증."""

    def test_only_recent_files_uploaded(self):
        """[Flow: since_timestamp 이후에 수정된 파일만 업로드 대상이 되는지 검증]"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            collector = ResultCollector(workspace_root=workspace)

            # 과거 파일 (sandbox 생성 전부터 존재)
            _create_file(workspace / "agent_output" / "old.csv", "old", mtime_offset=-100)
            # 최근 파일 (sandbox 생성 후 생성)
            _create_file(workspace / "agent_output" / "new.csv", "new", mtime_offset=10)

            since_ts = time.time() - 50  # 50초 전 기준

            # supabase mock — upload 호출을 기록
            uploaded_paths = []

            class FakeStorage:
                def from_(self, bucket):
                    class FakeBucket:
                        def upload(self, path, data, options=None):
                            uploaded_paths.append(path)
                            return {"path": path}
                    return FakeBucket()

            result = collector.collect_and_upload(
                workspace_path=workspace,
                job_id="test-job",
                supabase_client=MagicMock(storage=FakeStorage()),
                since_timestamp=since_ts,
            )

            assert result["uploaded"] == 1
            assert any("new.csv" in p for p in uploaded_paths)
            assert not any("old.csv" in p for p in uploaded_paths)

    def test_no_timestamp_uploads_all(self):
        """[Flow: since_timestamp가 None이면 모든 스캔 파일을 업로드]"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            collector = ResultCollector(workspace_root=workspace)

            _create_file(workspace / "agent_output" / "a.csv", "a", mtime_offset=-200)
            _create_file(workspace / "agent_output" / "b.csv", "b", mtime_offset=-100)

            class FakeStorage:
                def from_(self, bucket):
                    class FakeBucket:
                        def upload(self, path, data, options=None):
                            return {"path": path}
                    return FakeBucket()

            result = collector.collect_and_upload(
                workspace_path=workspace,
                job_id="test-job",
                supabase_client=MagicMock(storage=FakeStorage()),
                since_timestamp=None,
            )

            assert result["uploaded"] == 2


class TestUploadUpsert:
    """upload_to_storage가 upsert 옵션을 사용하는지 검증."""

    def test_upload_uses_upsert_option(self):
        """[Flow: Supabase upload 호출 시 upsert=True 옵션이 전달되는지 검증]"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            collector = ResultCollector(workspace_root=workspace)

            file_path = _create_file(workspace / "agent_output" / "result.csv", "data")
            files = [{
                "path": str(file_path),
                "relative_path": "agent_output/result.csv",
                "size": 4,
                "extension": ".csv",
                "modified_at": time.time(),
            }]

            received_options = []

            class FakeStorage:
                def from_(self, bucket):
                    class FakeBucket:
                        def upload(self, path, data, options=None):
                            received_options.append(options)
                            return {"path": path}
                    return FakeBucket()

            collector.upload_to_storage(files, "test-job", MagicMock(storage=FakeStorage()))

            assert len(received_options) == 1
            assert received_options[0] is not None
            # upsert=True 가 포함되어 있어야 함 (딕셔너리 또는 객체 형태)
            opts = received_options[0]
            if isinstance(opts, dict):
                assert opts.get("upsert") is True or opts.get("overwrite") is True
            else:
                assert getattr(opts, "upsert", None) is True or getattr(opts, "overwrite", None) is True
