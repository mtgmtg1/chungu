#!/usr/bin/env python3
"""[Flow: Step 1 (빈 스캔 PDF + OCR layout 모킹) -> Step 2 (search_job_text 호출)
      -> Step 3 (OCR 폴백 경로가 device-space 좌표를 반환하는지 검증)]

스캔 PDF에서 search_for가 0건을 반환하면 OCR 폴백으로 빠진다.
build_agent_elements_from_ocr_layout은 PDF user-space(y=0 하단) 좌표를 반환하므로,
search_job_text는 이를 device-space(y=0 상단)로 변환하여 반환해야 한다.
그렇지 않으면 에이전트가 input_space='device'로 저장할 때 y 반전이 발생한다.
"""
import sys
import os
import io
import json
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import fitz
import pytest
from sqlalchemy.orm import Session

from backend.api.jobs import search_job_text
from backend.db.models import Job, User


def _make_empty_pdf(width: float = 595.0, height: float = 842.0) -> bytes:
    """[Flow: Step 1 (빈 페이지 생성) -> Step 2 (PDF 바이트 반환)] 텍스트 레이어가 없는 스캔 PDF 시뮬레이션."""
    doc = fitz.open()
    doc.new_page(width=width, height=height)
    stream = io.BytesIO()
    doc.save(stream)
    doc.close()
    return stream.getvalue()


class TestSearchJobTextOcrFallbackCoords:
    """search_job_text의 OCR 폴백 경로가 device-space 좌표를 반환하는지 검증한다."""

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    @pytest.fixture
    def mock_user(self):
        user = MagicMock(spec=User)
        user.id = "test-user-id"
        return user

    @patch("backend.api.jobs.supabase_client")
    @patch("backend.core.pdf_annotate_converter.build_agent_elements_from_ocr_layout")
    def test_ocr_fallback_returns_device_space_coords(
        self, mock_build_elements, mock_supabase, mock_db, mock_user
    ):
        """[Flow: 빈 PDF + OCR 요소(PDF user-space) 모킹 -> search_job_text 호출 -> device-space 변환 검증]

        OCR 폴백 요소가 PDF user-space bbox(페이지 상단 y≈800)를 반환하면,
        search_job_text는 device-space bbox(페이지 상단 y≈42)로 변환해야 한다.
        """
        job_id = "test-job-ocr-coords"
        job = Job(id=job_id, user_id=mock_user.id)
        job.pdf_storage_path = f"{job_id}/original.pdf"
        job.searchable_pdf_storage_path = None
        job.result_ocr_layout_storage_path = f"{job_id}/layout.json"
        mock_db.get.return_value = job

        # 빈 PDF (search_for 0건 유도)
        pdf_bytes = _make_empty_pdf(595.0, 842.0)

        mock_storage = MagicMock()
        mock_storage.download.side_effect = lambda path: b"{}" if "layout" in path else pdf_bytes
        mock_supabase.get_service_client.return_value.storage.from_.return_value = mock_storage

        # OCR 요소: PDF user-space에서 페이지 상단(y=800~820, y=0 하단 기준 상단)
        mock_build_elements.return_value = [
            {
                "page_no": 1,
                "bbox_pdf": [50.0, 800.0, 200.0, 820.0],  # PDF user-space (상단)
                "text": "표제목",
                "kind": "text",
            }
        ]

        with patch("backend.api.jobs._require_job_access"), \
             patch("backend.api.jobs._require_job_not_expired"):
            response = search_job_text(
                job_id=job_id,
                query="표제목",
                page_no=None,
                user=mock_user,
                db=mock_db,
            )

        assert response.status_code == 200
        data = json.loads(response.body.decode("utf-8"))
        assert len(data["matches"]) == 1
        match = data["matches"][0]
        # PDF user-space (50, 800, 200, 820) → device-space (50, 22, 200, 42)
        # device_y0 = page_height - pdf_user_y1 = 842 - 820 = 22
        # device_y1 = page_height - pdf_user_y0 = 842 - 800 = 42
        assert abs(match["bbox_pdf"][0] - 50.0) < 0.1
        assert abs(match["bbox_pdf"][1] - 22.0) < 0.1, (
            f"device-space y0 should be ~22 (page top), got {match['bbox_pdf'][1]}"
        )
        assert abs(match["bbox_pdf"][2] - 200.0) < 0.1
        assert abs(match["bbox_pdf"][3] - 42.0) < 0.1, (
            f"device-space y1 should be ~42 (page top), got {match['bbox_pdf'][3]}"
        )

    @patch("backend.api.jobs.supabase_client")
    @patch("backend.core.pdf_annotate_converter.build_agent_elements_from_ocr_layout")
    def test_ocr_fallback_table_row_device_space_coords(
        self, mock_build_elements, mock_supabase, mock_db, mock_user
    ):
        """[Flow: 표 행 OCR 요소(PDF user-space) -> search_job_text 호출 -> device-space 변환 검증]

        표 행 요소가 PDF user-space bbox(페이지 중간 y≈400~420)를 반환하면,
        search_job_text는 device-space bbox(페이지 중간 y≈422~442)로 변환해야 한다.
        """
        job_id = "test-job-ocr-table"
        job = Job(id=job_id, user_id=mock_user.id)
        job.pdf_storage_path = f"{job_id}/original.pdf"
        job.searchable_pdf_storage_path = None
        job.result_ocr_layout_storage_path = f"{job_id}/layout.json"
        mock_db.get.return_value = job

        pdf_bytes = _make_empty_pdf(595.0, 842.0)

        mock_storage = MagicMock()
        mock_storage.download.side_effect = lambda path: b"{}" if "layout" in path else pdf_bytes
        mock_supabase.get_service_client.return_value.storage.from_.return_value = mock_storage

        # 표 행: PDF user-space에서 페이지 중간(y=400~420)
        mock_build_elements.return_value = [
            {
                "page_no": 1,
                "bbox_pdf": [21.0, 400.0, 572.0, 420.0],  # PDF user-space (중간)
                "text": "사건구분 | 형사 | 선임구분 | 사선",
                "kind": "table_row",
            }
        ]

        with patch("backend.api.jobs._require_job_access"), \
             patch("backend.api.jobs._require_job_not_expired"):
            response = search_job_text(
                job_id=job_id,
                query="형사",
                page_no=None,
                user=mock_user,
                db=mock_db,
            )

        assert response.status_code == 200
        data = json.loads(response.body.decode("utf-8"))
        assert len(data["matches"]) == 1
        match = data["matches"][0]
        # PDF user-space (21, 400, 572, 420) → device-space (21, 422, 572, 442)
        # device_y0 = 842 - 420 = 422
        # device_y1 = 842 - 400 = 442
        assert abs(match["bbox_pdf"][1] - 422.0) < 0.1, (
            f"device-space y0 should be ~422 (page middle), got {match['bbox_pdf'][1]}"
        )
        assert abs(match["bbox_pdf"][3] - 442.0) < 0.1, (
            f"device-space y1 should be ~442 (page middle), got {match['bbox_pdf'][3]}"
        )
