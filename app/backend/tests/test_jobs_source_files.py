#!/usr/bin/env python3
# [Flow: Step 1 (Job/파일 메타데이터 모의 생성) -> Step 2 (_build_source_file_item/_detect_source_type/_source_files 검증) -> Step 3 (pptx/docx/hwp 미리보기 URL 생성 확인)]
"""api/jobs.py의 source_files 생성 로직에서 pptx/docx/hwp 미리보기 처리를 검증한다."""
import sys
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

import pytest

from backend.api.jobs import (
    _build_source_file_item,
    _detect_source_type,
)


@pytest.fixture
def mock_jobs_dependencies(monkeypatch):
    """jobs.py에서 참조하는 외부 모듈 함수를 모킹한다."""
    mock_pdf = MagicMock()
    mock_pdf.get_preview_pdf_url.return_value = "https://preview.example.com/preview.pdf"
    monkeypatch.setattr("backend.api.jobs._shared.pdf_preview_converter", mock_pdf)

    mock_supabase = MagicMock()
    mock_supabase.get_signed_download_url.return_value = "https://original.example.com/file.pptx"
    monkeypatch.setattr("backend.api.jobs._shared.supabase_client", mock_supabase)

    return {"pdf": mock_pdf, "supabase": mock_supabase}


# ---------------------------------------------------------------------------
# _build_source_file_item: 문서 미리보기 URL 생성
# ---------------------------------------------------------------------------
class TestBuildSourceFileItem:
    """_build_source_file_item이 pptx/docx/hwp에 대해 PDF 미리보기 URL을 생성한다."""

    def test_pptx_generates_preview_pdf_url(self, mock_jobs_dependencies):
        # [Flow: pptx 원본 -> get_preview_pdf_url -> preview_url, get_signed_download_url -> url]
        info = {
            "storage_path": "jobs/output.pptx",
            "type": "pptx",
            "bucket": "jobs",
        }

        item = _build_source_file_item(info, 0)

        assert item is not None
        assert item["type"] == "pptx"
        assert item["url"] == "https://original.example.com/file.pptx"
        assert item["preview_url"] == "https://preview.example.com/preview.pdf"
        assert item["bucket"] == "jobs"

        pdf = mock_jobs_dependencies["pdf"]
        pdf.get_preview_pdf_url.assert_called_once_with(
            "jobs/output.pptx",
            source_bucket="jobs",
            expires_in=3600,
        )

    def test_docx_generates_preview_pdf_url(self, mock_jobs_dependencies):
        info = {
            "storage_path": "pdfs/doc.docx",
            "type": "docx",
            "bucket": "pdfs",
        }

        item = _build_source_file_item(info, 1)

        assert item["type"] == "docx"
        assert item["preview_url"] == "https://preview.example.com/preview.pdf"
        mock_jobs_dependencies["pdf"].get_preview_pdf_url.assert_called_once_with(
            "pdfs/doc.docx",
            source_bucket="pdfs",
            expires_in=3600,
        )

    def test_hwp_generates_preview_pdf_url(self, mock_jobs_dependencies):
        info = {
            "storage_path": "pdfs/doc.hwp",
            "type": "hwp",
            "bucket": "pdfs",
        }

        item = _build_source_file_item(info, 2)

        assert item["type"] == "hwp"
        assert item["preview_url"] == "https://preview.example.com/preview.pdf"

    def test_pptx_preview_failure_falls_back_to_file_type(self, mock_jobs_dependencies, monkeypatch):
        # [Flow: PDF 변환 실패 -> file 타입으로 폴백 (다운로드 링크만 제공)]
        mock_jobs_dependencies["pdf"].get_preview_pdf_url.return_value = None

        info = {
            "storage_path": "jobs/output.pptx",
            "type": "pptx",
            "bucket": "jobs",
        }

        item = _build_source_file_item(info, 0)

        assert item is not None
        assert item["type"] == "file"
        assert item["url"] == "https://original.example.com/file.pptx"

    def test_pdf_does_not_call_pdf_preview_converter(self, mock_jobs_dependencies):
        # [Flow: pdf는 원본/검색가능 PDF URL을 직접 사용, pdf_preview_converter 미호출]
        info = {
            "storage_path": "pdfs/doc.pdf",
            "type": "pdf",
            "bucket": "pdfs",
            "searchable_pdf_storage_path": "pdfs/searchable.pdf",
        }

        item = _build_source_file_item(info, 0)

        assert item["type"] == "pdf"
        mock_jobs_dependencies["pdf"].get_preview_pdf_url.assert_not_called()


# ---------------------------------------------------------------------------
# _detect_source_type: pptx 확장자 인식
# ---------------------------------------------------------------------------
class TestDetectSourceType:
    """_detect_source_type이 pptx 확장자와 extracted_files type을 올바르게 반환한다."""

    def test_pptx_by_extension(self):
        job = SimpleNamespace(
            pdf_storage_path="pdfs/slides.pptx",
            extracted_files=[],
        )

        assert _detect_source_type(job) == "pptx"

    def test_ppt_by_extension(self):
        job = SimpleNamespace(
            pdf_storage_path="pdfs/slides.ppt",
            extracted_files=[],
        )

        assert _detect_source_type(job) == "pptx"

    def test_pptx_from_single_extracted_file(self):
        # [Flow: 확장자로 pptx를 알 수 없는 경우에도 extracted_files의 단일 항목 기준으로 식별]
        job = SimpleNamespace(
            pdf_storage_path="dummy",
            extracted_files=[{"type": "pptx", "storage_path": "x.pptx"}],
        )

        assert _detect_source_type(job) == "pptx"
