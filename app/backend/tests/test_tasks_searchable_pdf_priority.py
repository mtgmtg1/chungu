#!/usr/bin/env python3
"""[Flow: Step 1 (원본 PDF에 텍스트 레이어가 있을 때 job.searchable_pdf_storage_path 설정)
      -> Step 2 (_build_and_upload_searchable_pdf 호출)
      -> Step 3 (기존 searchable 경로를 덮어쓰지 않는지 검증)]

text-layer PDF는 원본 PDF를 searchable PDF로 우선 사용해야 하므로,
_build_and_upload_searchable_pdf가 이미 등록된 경로를 덮어쓰면 안 됩니다.
"""
import sys
import os
from io import BytesIO
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import fitz
import pytest
from unittest.mock import MagicMock

from backend.db.models import Job
from backend.workers import tasks


def _make_a4_pdf(path: Path) -> None:
    """[Flow: Step 1 (A4 PDF 생성) -> Step 2 (지정 경로 저장)]"""
    doc = fitz.open()
    doc.new_page(width=595.0, height=842.0)
    doc.save(str(path))
    doc.close()


class TestSearchablePdfPriority:
    """텍스트 레이어 원본 PDF가 OCR searchable PDF로 덮어쓰이지 않는지 검증한다."""

    def test_build_and_upload_does_not_overwrite_existing_searchable_path(
        self, monkeypatch, tmp_path
    ):
        """[Flow: Step 1 (원본 searchable 경로가 이미 설정된 Job 준비)
              -> Step 2 (입력 PDF 생성)
              -> Step 3 (render_pdf/deskew_image 등 무거운 의존성 모킹)
              -> Step 4 (_build_and_upload_searchable_pdf 호출)
              -> Step 5 (upload_input이 호출되지 않고 경로가 유지되는지 assert)]"""
        input_path = tmp_path / "input.pdf"
        _make_a4_pdf(input_path)

        job = Job()
        job.id = "test-job"
        original_path = "original/searchable.pdf"
        job.searchable_pdf_storage_path = original_path

        db = MagicMock()

        # OCR layout 업로드는 테스트 대상이 아니미 무시
        monkeypatch.setattr(tasks, "upload_ocr_layout", lambda *a, **k: None)

        # PaddleOCR에서 추출할 더미 결과
        monkeypatch.setattr(
            tasks.pdf_text_layer,
            "extract_page_ocr_results_from_layout",
            lambda layout: {1: [("hello", (0.1, 0.1, 0.9, 0.9))]},
        )
        monkeypatch.setattr(
            tasks.pdf_text_layer,
            "add_text_layer_from_ocr",
            lambda *a, **k: b"fake searchable pdf bytes",
        )

        # 이미지 렌더링/Deskew 비활성화
        monkeypatch.setattr(
            "backend.core.image_deskew.deskew_image",
            lambda img_path, output_dir=None: (img_path, 0.0),
        )
        monkeypatch.setattr(
            "backend.core.ocr_client.render_pdf",
            lambda *args, **kwargs: None,
        )

        uploads = []

        def fake_upload(data, filename, job_id):
            uploads.append((filename, job_id))
            return "ocr/searchable.pdf"

        monkeypatch.setattr(tasks.supabase_client, "upload_input", fake_upload)

        layout_by_page = {1: {"_coordinate_system": "normalized"}}

        # Act
        tasks._build_and_upload_searchable_pdf(db, job, input_path, layout_by_page, 300)

        # Assert
        assert not uploads, (
            "searchable_pdf_storage_path가 이미 설정된 경우 "
            "_build_and_upload_searchable_pdf는 upload_input을 호출하면 안 됩니다."
        )
        assert job.searchable_pdf_storage_path == original_path, (
            "기존 searchable_pdf_storage_path가 OCR 생성물로 덮어쓰여졌습니다."
        )
