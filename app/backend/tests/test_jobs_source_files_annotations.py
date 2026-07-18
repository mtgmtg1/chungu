#!/usr/bin/env python3
"""[Flow: Step 1 (_source_files 의존성 모킹) -> Step 2 (Job 상태 설정)
      -> Step 3 (_source_files 호출) -> Step 4 (첫 번째 원본 문서 항목의 annotations_json_url 검증)]

api/jobs.py의 _source_files 함수가 AI 주석 완료 후 각 원본 문서 항목에
annotations_json_url을 정확히 부착하는지 테스트한다.
파일별 user_annotations 병합 경로를 커버한다.
"""
import sys
import os
import json
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from backend.api.jobs import _source_files
from backend.db.models import Job


def _make_job(job_id: str = "test-job-001") -> Job:
    """[Flow: Job 인스턴스 생성 -> 필수 필드 기본값 설정 -> 반환]"""
    job = Job()
    job.id = job_id
    job.original_filename = "test.pdf"
    job.extracted_files = [
        {
            "filename": "test.pdf",
            "path": "test.pdf",
            "storage_path": "pdfs/test.pdf",
            "bucket": "pdfs",
            "type": "pdf",
            "source_kind": "original",
            "source_index": 0,
        }
    ]
    job.annotated_pdf_files = []
    job.annotate_status = ""
    job.searchable_pdf_storage_path = ""
    return job


class TestSourceFilesAnnotationsJsonUrl:
    """_source_files가 annotations_json_url을 올바르게 생성하는지 검증한다."""

    @pytest.fixture
    def mock_deps(self, monkeypatch):
        """[Flow: pdf_preview_converter / supabase_client / get_service_client 모킹 -> fixture 반환]"""
        # pdf_preview_converter: pdf 원본 미리보기 URL 생성
        mock_pdf = MagicMock()
        mock_pdf.get_preview_pdf_url.return_value = "https://preview.example.com/preview.pdf"
        monkeypatch.setattr("backend.api.jobs.pdf_preview_converter", mock_pdf)

        # signed URL 생성기: 경로에 따라 다르게 반환하여 어떤 파일을 요청했는지 확인
        signed_urls = {}

        def _signed_url(path: str, bucket: str = "results", expires_in: int = 3600) -> str:
            key = f"{bucket}:{path}"
            if key in signed_urls:
                return signed_urls[key]
            raise FileNotFoundError(f"signed url not found for {key}")

        monkeypatch.setattr("backend.api.jobs.supabase_client.get_signed_download_url", _signed_url)

        # get_service_client는 _ensure_clean_source_pdf / _merge_annotation_jsons에서 사용
        class FakeBucket:
            def __init__(self):
                self.files = {}

            def download(self, path: str) -> bytes:
                if path not in self.files:
                    raise FileNotFoundError(f"not found: {path}")
                return self.files[path]

            def upload(self, path: str, data: bytes, options: dict | None = None):
                self.files[path] = data if isinstance(data, bytes) else data

        class FakeStorage:
            def __init__(self):
                self.bucket = FakeBucket()

            def from_(self, bucket: str):
                return self.bucket

        class FakeClient:
            def __init__(self):
                self.storage = FakeStorage()

        monkeypatch.setattr(
            "backend.api.jobs.supabase_client.get_service_client", lambda: FakeClient()
        )

        return {"signed_urls": signed_urls, "pdf": mock_pdf}

    def test_done_annotated_entry_creates_annotations_json_url(self, mock_deps, monkeypatch):
        # [Flow: annotated_pdf_files에 done entry + annotations_json_storage_path 설정 -> source_files 호출 -> URL 부착 확인]
        job_id = "test-job-001"
        job = _make_job(job_id)
        job.annotated_pdf_files = [
            {
                "index": 1,
                "status": "done",
                "storage_path": f"{job_id}/searchable.pdf",
                "annotations_json_storage_path": f"{job_id}/annotated.annotations.json",
                "filename": "test_searchable.pdf",
            }
        ]
        job.annotate_status = "done"
        # 원본 PDF URL + AI annotations JSON URL 모두 제공
        mock_deps["signed_urls"][f"pdfs:pdfs/test.pdf"] = "https://signed.example.com/original.pdf"
        mock_deps["signed_urls"][f"results:{job_id}/annotated.annotations.json"] = "https://signed.example.com/annotated.json"

        result = _source_files(job)

        assert len(result) == 1
        assert result[0]["annotations_json_url"] == "https://signed.example.com/annotated.json"

    def test_no_annotations_does_not_set_url(self, mock_deps, monkeypatch):
        # [Flow: annotate_status가 done이 아님 -> annotations_json_url 미설정 확인]
        job_id = "test-job-003"
        job = _make_job(job_id)
        job.annotated_pdf_files = []
        job.annotate_status = ""
        mock_deps["signed_urls"][f"pdfs:pdfs/test.pdf"] = "https://signed.example.com/original.pdf"

        result = _source_files(job)

        assert len(result) == 1
        assert result[0].get("annotations_json_url") is None

    def test_missing_annotations_json_file_returns_none(self, mock_deps, monkeypatch):
        # [Flow: annotated annotations.json 파일이 storage에 없음 -> get_signed_download_url 실패 -> None]
        job_id = "test-job-004"
        job = _make_job(job_id)
        job.annotated_pdf_files = [
            {
                "index": 1,
                "status": "done",
                "storage_path": f"{job_id}/searchable.pdf",
                "annotations_json_storage_path": f"{job_id}/annotated.annotations.json",
                "filename": "test_searchable.pdf",
            }
        ]
        job.annotate_status = "done"
        mock_deps["signed_urls"][f"pdfs:pdfs/test.pdf"] = "https://signed.example.com/original.pdf"
        # signed_urls에 annotations JSON 경로 없음 -> FileNotFoundError -> annotations_json_url None

        result = _source_files(job)

        assert len(result) == 1
        assert result[0].get("annotations_json_url") is None
