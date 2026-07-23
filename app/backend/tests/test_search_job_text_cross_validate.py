#!/usr/bin/env python3
"""[Flow: Step 1 (잘못된 위치의 텍스트 레이어 PDF 생성 + 올바른 OCR layout 모킹)
      -> Step 2 (search_job_text 호출)
      -> Step 3 (search_for 결과가 OCR layout 좌표로 보정되었는지 검증)]

search_for가 텍스트를 찾았지만 그 위치가 OCR layout의 실제 시각적 위치와
큰 차이가 나는 경우(예: 수정 전 코드로 생성된 searchable PDF의 반전된 표 행),
search_job_text는 OCR layout 좌표로 y 위치를 보정해야 한다.
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


def _make_pdf_with_text_at(
    text: str,
    x: float,
    y: float,
    width: float = 595.0,
    height: float = 842.0,
) -> bytes:
    """[Flow: Step 1 (빈 페이지 생성) -> Step 2 (지정한 위치에 투명 텍스트 삽입) -> Step 3 (PDF 바이트 반환)]

    지정한 (x, y) 위치에 텍스트를 삽입한 PDF를 생성한다.
    search_for가 이 텍스트를 해당 위치에서 찾도록 한다.
    """
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    # 투명 텍스트 삽입 (render_mode=3)
    page.insert_text(
        fitz.Point(x, y),
        text,
        fontname="helv",
        fontsize=12,
        render_mode=3,
    )
    stream = io.BytesIO()
    doc.save(stream)
    doc.close()
    return stream.getvalue()


class TestSearchJobTextCrossValidation:
    """search_for 결과와 OCR layout 좌표를 교차 검증하여 y 위치를 보정하는지 테스트한다."""

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    @pytest.fixture
    def mock_user(self):
        user = MagicMock(spec=User)
        user.id = "test-user-id"
        return user

    @patch("backend.api.jobs.annotations.supabase_client")
    @patch("backend.core.pdf_annotate_converter.build_agent_elements_from_ocr_layout")
    def test_search_for_y_corrected_by_ocr_layout(
        self, mock_build_elements, mock_supabase, mock_db, mock_user
    ):
        """[Flow: 텍스트가 하단(y=700)에 삽입된 PDF + OCR layout이 상단(y=200)을 가리키는 상황
              -> search_job_text 호출 -> OCR layout y로 보정되었는지 검증]

        search_for가 텍스트를 하단(y≈700)에서 찾았지만, OCR layout이 동일 텍스트를
        상단(y≈200)에 배치하고 있다면, search_job_text는 OCR layout의 y 좌표로 보정해야 한다.
        이는 수정 전 코드로 생성된 searchable PDF의 반전된 표 행 문제를 해결한다.
        """
        job_id = "test-job-cross-validate"
        job = Job(id=job_id, user_id=mock_user.id)
        job.pdf_storage_path = f"{job_id}/original.pdf"
        job.searchable_pdf_storage_path = f"{job_id}/searchable.pdf"
        job.result_ocr_layout_storage_path = f"{job_id}/layout.json"
        mock_db.get.return_value = job

        # 영문 텍스트를 하단(y=700)에 삽입 — search_for가 y≈700에서 찾음
        pdf_bytes = _make_pdf_with_text_at("TARGET_TEXT", 50.0, 700.0)

        mock_storage = MagicMock()
        mock_storage.download.side_effect = lambda path: (
            b'{"1": {}}' if "layout" in path else pdf_bytes
        )
        mock_supabase.get_service_client.return_value.storage.from_.return_value = mock_storage

        # OCR layout: 동일 텍스트 "TARGET_TEXT | extra"를 상단(y=200~250, device-space)에 배치
        # build_agent_elements_from_ocr_layout은 이중 y반전 결과인 device-space를 반환
        mock_build_elements.return_value = [
            {
                "page_no": 1,
                "bbox_pdf": [21.0, 200.0, 572.0, 250.0],  # device-space (상단)
                "text": "TARGET_TEXT | extra info",
                "kind": "table_row",
            }
        ]

        with patch("backend.api.jobs.annotations._require_job_access"), \
             patch("backend.api.jobs.annotations._require_job_not_expired"):
            response = search_job_text(
                job_id=job_id,
                query="TARGET_TEXT",
                page_no=None,
                user=mock_user,
                db=mock_db,
            )

        assert response.status_code == 200
        data = json.loads(response.body.decode("utf-8"))
        # search_for가 찾은 매치가 있어야 함
        assert len(data["matches"]) >= 1

        # search_for 매치의 y가 OCR layout y로 보정되었는지 확인
        # 원본 search_for: y≈700 (하단)
        # OCR layout device-space: y≈200~250 (상단)
        # 보정 후: y가 200~250 부근이어야 함 (임계값 내)
        corrected_match = None
        for m in data["matches"]:
            if "TARGET_TEXT" in m["text"]:
                corrected_match = m
                break

        assert corrected_match is not None, "TARGET_TEXT 매치가 없음"
        match_y0 = corrected_match["bbox_pdf"][1]
        # 보정된 y0가 OCR layout의 device-space y0(≈200)에 가까워야 함
        # 허용 오차: ±60px (보정 로직이 OCR layout 행 높이 내로 정렬하므로)
        assert abs(match_y0 - 200.0) < 60.0, (
            f"y0 should be corrected to ~200 (OCR layout position), got {match_y0}"
        )

    @patch("backend.api.jobs.annotations.supabase_client")
    @patch("backend.core.pdf_annotate_converter.build_agent_elements_from_ocr_layout")
    def test_search_for_kept_when_close_to_ocr_layout(
        self, mock_build_elements, mock_supabase, mock_db, mock_user
    ):
        """[Flow: 텍스트가 올바른 위치(y=200)에 삽입된 PDF + OCR layout도 동일 위치
              -> search_job_text 호출 -> 보정 없이 원래 위치 유지 검증]

        search_for 결과와 OCR layout의 y 차이가 임계값 이내라면,
        search_for 결과를 그대로 유지해야 한다 (불필요한 보정 방지).
        """
        job_id = "test-job-no-correction"
        job = Job(id=job_id, user_id=mock_user.id)
        job.pdf_storage_path = f"{job_id}/original.pdf"
        job.searchable_pdf_storage_path = f"{job_id}/searchable.pdf"
        job.result_ocr_layout_storage_path = f"{job_id}/layout.json"
        mock_db.get.return_value = job

        # 영문 텍스트를 상단(y=200)에 삽입 — search_for가 y≈200에서 찾음
        pdf_bytes = _make_pdf_with_text_at("TITLE_TEXT", 50.0, 200.0)

        mock_storage = MagicMock()
        mock_storage.download.side_effect = lambda path: (
            b'{"1": {}}' if "layout" in path else pdf_bytes
        )
        mock_supabase.get_service_client.return_value.storage.from_.return_value = mock_storage

        # OCR layout: 동일 텍스트를 비슷한 위치(y=195~210, device-space)에 배치
        # build_agent_elements_from_ocr_layout은 이중 y반전 결과인 device-space를 반환
        mock_build_elements.return_value = [
            {
                "page_no": 1,
                "bbox_pdf": [50.0, 195.0, 200.0, 210.0],  # device-space (상단)
                "text": "TITLE_TEXT",
                "kind": "text",
            }
        ]

        with patch("backend.api.jobs.annotations._require_job_access"), \
             patch("backend.api.jobs.annotations._require_job_not_expired"):
            response = search_job_text(
                job_id=job_id,
                query="TITLE_TEXT",
                page_no=None,
                user=mock_user,
                db=mock_db,
            )

        assert response.status_code == 200
        data = json.loads(response.body.decode("utf-8"))
        assert len(data["matches"]) >= 1

        # search_for 결과가 원래 위치(y≈200) 근처에 유지되어야 함
        match = data["matches"][0]
        match_y0 = match["bbox_pdf"][1]
        # 원래 search_for 위치(y≈200)에서 크게 벗어나지 않아야 함
        assert abs(match_y0 - 200.0) < 30.0, (
            f"y0 should stay near original ~200, got {match_y0}"
        )
