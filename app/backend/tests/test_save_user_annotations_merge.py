#!/usr/bin/env python3
"""[Flow: Step 1 (의존성 모킹) -> Step 2 (save_user_annotations 호출)
      -> Step 3 (_merge_annotation_jsons 호출 여부 검증)
      -> Step 4 (응답에 merged_annotations_url 포함 여부 검증)]

api/jobs.py의 save_user_annotations가 사용자 주석 저장 후
merged_annotations.json을 재생성(_merge_annotation_jsons 호출)하고,
응답에 merged_annotations_url을 포함하는지 검증한다.

이 회귀 테스트는 "주석 추가 시 이전 주석이 지워지는" 버그를 방지한다.
근본 원인: 자동 저장 후 merged_annotations.json이 재생성되지 않아,
파일 전환/복귀 시 이전 병합본을 로드하고, 그 상태에서 새 주석 추가 시
기존 사용자 주석이 빠진 채로 user_annotations_{source_index}.json이 덮어쓰기됨.
"""
import os
import sys
import json
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from backend.api import jobs as jobs_module
from backend.db.models import Job


def _make_job(job_id: str = "test-job-save-001") -> Job:
    """[Flow: Job 인스턴스 생성 -> annotated_pdf_files에 AI entry 설정 -> 반환]"""
    job = Job()
    job.id = job_id
    job.original_filename = "test.pdf"
    job.pdf_storage_path = f"{job_id}/original.pdf"
    job.searchable_pdf_storage_path = f"{job_id}/searchable.pdf"
    job.annotated_pdf_files = [
        {
            "index": 1,
            "status": "done",
            "storage_path": f"{job_id}/searchable.pdf",
            "annotations_json_storage_path": f"{job_id}/annotated.annotations.json",
            "filename": "test_searchable.pdf",
        }
    ]
    return job


class FakeBucket:
    """[Flow: Storage 버킷 모킹 -> download/upload 지원]"""

    def __init__(self):
        self.files: dict[str, bytes] = {}

    def download(self, path: str) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(f"not found: {path}")
        return self.files[path]

    def upload(self, path: str, data: bytes, options: dict | None = None):
        self.files[path] = data if isinstance(data, bytes) else data


class FakeStorage:
    def __init__(self):
        self._bucket = FakeBucket()

    def from_(self, bucket: str):
        return self._bucket


class FakeClient:
    def __init__(self):
        self.storage = FakeStorage()


@pytest.fixture
def mock_env(monkeypatch):
    """[Flow: 모든 외부 의존성 모킹 -> save_user_annotations 단독 실행 환경 구성]"""
    job = _make_job()
    job_id = job.id

    # DB 세션 모킹: db.get(Job, id) -> job, db.execute(select...) -> locked job
    db = MagicMock()
    db.get.return_value = job

    locked_job = MagicMock()
    locked_job.annotated_pdf_files = job.annotated_pdf_files
    locked_execute_result = MagicMock()
    locked_execute_result.scalar_one.return_value = locked_job
    db.execute.return_value = locked_execute_result

    # 권한 검사 통과
    monkeypatch.setattr(jobs_module, "_require_job_access", lambda _job, _user: None)
    monkeypatch.setattr(jobs_module, "_require_job_not_expired", lambda _job: None)

    # supabase_client: FakeClient 반환
    fake_client = FakeClient()
    # AI 주석 JSON이 이미 존재한다고 가정 (canonical document 형식)
    fake_client.storage._bucket.files[f"{job_id}/annotated.annotations.json"] = json.dumps({
        "coordinate_system": "canonical",
        "source_pdf_storage_path": f"{job_id}/searchable.pdf",
        "source_pdf_bucket": "pdfs",
        "page_dimensions": {},
        "annotations": [],
    }).encode("utf-8")
    monkeypatch.setattr(jobs_module.supabase_client, "get_service_client", lambda: fake_client)

    # pdf_user_annotator: canonical 변환 통과 (입력 그대로 반환)
    monkeypatch.setattr(
        jobs_module.pdf_user_annotator,
        "_convert_annotations_to_canonical",
        lambda annotations, _pdf_bytes, input_space="device": annotations,
    )

    # pdf_annotate_converter: page_dimensions / extract / build 모킹
    monkeypatch.setattr(jobs_module.pdf_annotate_converter, "_page_dimensions", lambda _pdf_bytes: {})
    monkeypatch.setattr(
        jobs_module.pdf_annotate_converter,
        "_extract_annotations_from_document",
        lambda _doc: ([], {}, []),
    )

    def _build_doc(annotations, source_pdf_storage_path=None, source_pdf_bucket="pdfs", page_dimensions=None):
        return {
            "coordinate_system": "canonical",
            "source_pdf_storage_path": source_pdf_storage_path,
            "source_pdf_bucket": source_pdf_bucket,
            "page_dimensions": page_dimensions or {},
            "annotations": annotations,
        }
    monkeypatch.setattr(
        jobs_module.pdf_annotate_converter,
        "_build_canonical_annotations_document",
        _build_doc,
    )

    # cache 무효화 통과
    monkeypatch.setattr(jobs_module.cache, "invalidate_pattern", lambda _pattern: None)

    # _merge_annotation_jsons 호출 추적 (핵심 검증 대상)
    merge_calls: list[tuple[str, str | None, str]] = []
    merged_url = f"https://signed.example.com/{job_id}/merged_annotations.json"

    def _fake_merge(jid: str, ai_path: str | None, user_path: str) -> str | None:
        merge_calls.append((jid, ai_path, user_path))
        return merged_url

    monkeypatch.setattr(jobs_module, "_merge_annotation_jsons", _fake_merge)

    return {
        "job": job,
        "job_id": job_id,
        "db": db,
        "fake_client": fake_client,
        "merge_calls": merge_calls,
        "merged_url": merged_url,
    }


class TestSaveUserAnnotationsMergedRegeneration:
    """save_user_annotations가 merged_annotations.json을 재생성하는지 검증한다."""

    def test_merge_called_and_url_returned_for_user_annotation(self, mock_env):
        """[Flow: 사용자 주석 1개 저장 -> _merge_annotation_jsons 호출 -> 응답에 merged_annotations_url 포함]"""
        user_annotation = {
            "type": "highlight",
            "pageIndex": 0,
            "rect": [10, 20, 100, 40],
            "contents": "사용자가 추가한 주석",
            "id": "user-annotation-1",
        }

        result = jobs_module.save_user_annotations(
            job_id=mock_env["job_id"],
            payload={
                "source_index": 0,
                "annotations": [user_annotation],
                "input_space": "device",
            },
            user=MagicMock(),
            db=mock_env["db"],
        )

        # _merge_annotation_jsons가 호출되었는지 검증
        assert len(mock_env["merge_calls"]) == 1, (
            f"_merge_annotation_jsons가 호출되어야 하지만 {len(mock_env['merge_calls'])}회 호출됨"
        )
        called_job_id, called_ai_path, called_user_path = mock_env["merge_calls"][0]
        assert called_job_id == mock_env["job_id"]
        assert called_ai_path == f"{mock_env['job_id']}/annotated.annotations.json"
        assert called_user_path == f"{mock_env['job_id']}/user_annotations_0.json"

        # 응답에 merged_annotations_url이 포함되어야 함
        assert isinstance(result, dict)
        assert result.get("ok") is True
        assert result.get("merged_annotations_url") == mock_env["merged_url"], (
            "응답에 merged_annotations_url이 포함되어야 함"
        )

    def test_merge_called_even_when_no_ai_entry(self, mock_env, monkeypatch):
        """[Flow: AI entry가 없는 경우(source_index >= 0, entry is None)에도 병합 재생성 검증]"""
        # AI entry 제거
        mock_env["job"].annotated_pdf_files = []
        locked_job = MagicMock()
        locked_job.annotated_pdf_files = []
        locked_execute_result = MagicMock()
        locked_execute_result.scalar_one.return_value = locked_job
        mock_env["db"].execute.return_value = locked_execute_result

        user_annotation = {
            "type": "highlight",
            "pageIndex": 0,
            "rect": [10, 20, 100, 40],
            "contents": "사용자 주석",
            "id": "user-annotation-2",
        }

        result = jobs_module.save_user_annotations(
            job_id=mock_env["job_id"],
            payload={
                "source_index": 0,
                "annotations": [user_annotation],
                "input_space": "device",
            },
            user=MagicMock(),
            db=mock_env["db"],
        )

        # entry가 없어도 병합이 호출되어야 함
        assert len(mock_env["merge_calls"]) == 1, (
            f"AI entry가 없어도 _merge_annotation_jsons가 호출되어야 함 (현재 {len(mock_env['merge_calls'])}회)"
        )
        assert result.get("merged_annotations_url") == mock_env["merged_url"]
