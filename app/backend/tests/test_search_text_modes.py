#!/usr/bin/env python3
# [Flow: Step 1 (가상 Job 및 PDF 모킹) -> Step 2 (search_job_text 직접 호출) -> Step 3 (mode="text"와 mode="line"의 bbox 및 텍스트 매칭 결과 검증)]
"""jobs.py의 search_job_text API에 대해 mode 파라미터(text vs line)와 선형 보간, 라인 매칭이 바르게 작동하는지 검증한다."""

import sys
import os
import io
import json
from unittest.mock import MagicMock, patch

# sys.path 설정
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import fitz
import pytest
from sqlalchemy.orm import Session

from backend.api.jobs import search_job_text
from backend.db.models import Job, User


def _make_pdf_with_text(text: str, bbox: tuple[float, float, float, float]) -> bytes:
    """테스트용으로 지정한 텍스트와 좌표(bbox)가 삽입된 PDF 문서 바이너리를 생성한다.

    [Flow: PyMuPDF 문서 생성 -> 지정 텍스트 및 좌표로 삽입 -> PDF 바이너리 반환]

    Args:
        text: 삽입할 텍스트 문자열
        bbox: (x0, y0, x1, y1) 형식의 PDF 포인트 좌표

    Returns:
        생성된 PDF 파일의 bytes 데이터
    """
    doc = fitz.open()
    page = doc.new_page(width=595.0, height=842.0)
    x0, y0, x1, y1 = bbox
    font_size = y1 - y0
    page.insert_text(fitz.Point(x0, y1), text, fontsize=font_size, overlay=True)
    stream = io.BytesIO()
    doc.save(stream)
    doc.close()
    return stream.getvalue()


class TestSearchJobTextModes:
    """search_job_text API의 검색 모드(text, line)별 검색 좌표 분할 및 라인 처리를 테스트한다."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock(spec=Session)
        return db

    @pytest.fixture
    def mock_user(self):
        user = MagicMock(spec=User)
        user.id = "test-user-id"
        return user

    @patch("backend.api.jobs.supabase_client")
    def test_search_text_mode_text_with_pdf_layer(self, mock_supabase, mock_db, mock_user):
        """텍스트 레이어가 존재하는 PDF에서 mode='text'일 때 정확히 매칭 텍스트의 bbox를 반환하는지 테스트한다.

        [Flow: 모의 PDF 준비 -> search_job_text(mode="text") 호출 -> 정확한 텍스트 바운딩 박스 검증]
        """
        job_id = "test-job-text"
        job = Job(id=job_id, user_id=mock_user.id)
        job.pdf_storage_path = f"{job_id}/original.pdf"
        mock_db.get.return_value = job

        # Hello World가 (100, 100, 200, 120)에 위치한 PDF 생성
        pdf_bytes = _make_pdf_with_text("Hello World", (100, 100, 200, 120))
        
        mock_storage = MagicMock()
        mock_storage.download.return_value = pdf_bytes
        mock_supabase.get_service_client.return_value.storage.from_.return_value = mock_storage

        # 'Hello' 검색 시 텍스트 전체(Hello World)가 아니라 Hello 부분만 반환하는지 검증
        with patch("backend.api.jobs._require_job_access"), \
             patch("backend.api.jobs._require_job_not_expired"):
            response = search_job_text(
                job_id=job_id,
                query="Hello",
                mode="text",
                user=mock_user,
                db=mock_db
            )
            
        assert response.status_code == 200
        data = json.loads(response.body.decode("utf-8"))
        assert len(data["matches"]) > 0
        match = data["matches"][0]
        # x1 좌표가 200보다는 작을 것임 (Hello만 칠했기 때문)
        assert match["bbox_pdf"][2] < 200.0
        assert match["text"] == "Hello"

    @patch("backend.api.jobs.supabase_client")
    def test_search_text_mode_line_with_pdf_layer(self, mock_supabase, mock_db, mock_user):
        """텍스트 레이어가 존재하는 PDF에서 mode='line'일 때 라인 전체의 bbox를 반환하는지 테스트한다.

        [Flow: 모의 PDF 준비 -> search_job_text(mode="line") 호출 -> 텍스트가 속한 라인 영역 검증]
        """
        job_id = "test-job-line"
        job = Job(id=job_id, user_id=mock_user.id)
        job.pdf_storage_path = f"{job_id}/original.pdf"
        mock_db.get.return_value = job

        pdf_bytes = _make_pdf_with_text("Hello World", (100, 100, 200, 120))
        
        mock_storage = MagicMock()
        mock_storage.download.return_value = pdf_bytes
        mock_supabase.get_service_client.return_value.storage.from_.return_value = mock_storage

        with patch("backend.api.jobs._require_job_access"), \
             patch("backend.api.jobs._require_job_not_expired"):
            response = search_job_text(
                job_id=job_id,
                query="Hello",
                mode="line",
                user=mock_user,
                db=mock_db
            )
            
        assert response.status_code == 200
        data = json.loads(response.body.decode("utf-8"))
        assert len(data["matches"]) > 0
        match = data["matches"][0]
        # 'Hello World' 전체 라인 영역이 반환되어야 하므로 x1이 대략 200 근처여야 함
        assert match["bbox_pdf"][2] >= 190.0

    @patch("backend.api.jobs.supabase_client")
    @patch("backend.core.pdf_annotate_converter.build_agent_elements_from_ocr_layout")
    def test_search_text_mode_text_ocr_fallback(self, mock_build_elements, mock_supabase, mock_db, mock_user):
        """텍스트 레이어가 없고 OCR 폴백 시, mode='text'일 때 선형 보간된 정확한 bbox를 반환하는지 테스트한다.

        [Flow: 빈 PDF 및 layout 모킹 -> search_job_text(mode="text") 호출 -> 선형 보간 계산 검증]
        """
        job_id = "test-job-ocr-text"
        job = Job(id=job_id, user_id=mock_user.id)
        job.pdf_storage_path = f"{job_id}/original.pdf"
        job.result_ocr_layout_storage_path = f"{job_id}/layout.json"
        mock_db.get.return_value = job

        # 빈 PDF 생성 (search_for 결과가 없게 만듦)
        doc = fitz.open()
        doc.new_page(width=595.0, height=842.0)
        stream = io.BytesIO()
        doc.save(stream)
        doc.close()
        pdf_bytes = stream.getvalue()

        mock_storage = MagicMock()
        mock_storage.download.side_effect = lambda path: b"{}" if "layout.json" in path else pdf_bytes
        mock_supabase.get_service_client.return_value.storage.from_.return_value = mock_storage
        
        # OCR element 모킹: "Hello World" 라인의 bbox
        mock_build_elements.return_value = [
            {
                "page_no": 1,
                "bbox_pdf": [100.0, 100.0, 200.0, 120.0],
                "text": "Hello World",
                "kind": "text"
            }
        ]

        with patch("backend.api.jobs._require_job_access"), \
             patch("backend.api.jobs._require_job_not_expired"):
            response = search_job_text(
                job_id=job_id,
                query="Hello",
                mode="text",
                user=mock_user,
                db=mock_db
            )

        assert response.status_code == 200
        data = json.loads(response.body.decode("utf-8"))
        assert len(data["matches"]) > 0
        match = data["matches"][0]
        # x0=100.0, x1=200.0 이고 텍스트 "Hello World"(길이 11), 매치 "Hello"(길이 5)이므로
        # 선형 보간 시 x0_new = 100.0, x1_new = 100 + (5/11)*100 = 145.45
        assert abs(match["bbox_pdf"][2] - 145.45) < 1.0
        assert match["text"] == "Hello"

    @patch("backend.api.jobs.supabase_client")
    @patch("backend.core.pdf_annotate_converter.build_agent_elements_from_ocr_layout")
    def test_search_text_mode_line_ocr_fallback(self, mock_build_elements, mock_supabase, mock_db, mock_user):
        """텍스트 레이어가 없고 OCR 폴백 시, mode='line'일 때 원래 라인의 bbox를 그대로 반환하는지 테스트한다.

        [Flow: 빈 PDF 및 layout 모킹 -> search_job_text(mode="line") 호출 -> 원래 라인의 bbox 검증]
        """
        job_id = "test-job-ocr-line"
        job = Job(id=job_id, user_id=mock_user.id)
        job.pdf_storage_path = f"{job_id}/original.pdf"
        job.result_ocr_layout_storage_path = f"{job_id}/layout.json"
        mock_db.get.return_value = job

        doc = fitz.open()
        doc.new_page(width=595.0, height=842.0)
        stream = io.BytesIO()
        doc.save(stream)
        doc.close()
        pdf_bytes = stream.getvalue()

        mock_storage = MagicMock()
        mock_storage.download.side_effect = lambda path: b"{}" if "layout.json" in path else pdf_bytes
        mock_supabase.get_service_client.return_value.storage.from_.return_value = mock_storage
        
        mock_build_elements.return_value = [
            {
                "page_no": 1,
                "bbox_pdf": [100.0, 100.0, 200.0, 120.0],
                "text": "Hello World",
                "kind": "text"
            }
        ]

        with patch("backend.api.jobs._require_job_access"), \
             patch("backend.api.jobs._require_job_not_expired"):
            response = search_job_text(
                job_id=job_id,
                query="Hello",
                mode="line",
                user=mock_user,
                db=mock_db
            )

        assert response.status_code == 200
        data = json.loads(response.body.decode("utf-8"))
        assert len(data["matches"]) > 0
        match = data["matches"][0]
        # mode="line"일 때는 보간 없이 원래 전체 라인 bbox [100, 100, 200, 120] 반환
        assert match["bbox_pdf"] == [100.0, 100.0, 200.0, 120.0]
        assert match["text"] == "Hello World"
