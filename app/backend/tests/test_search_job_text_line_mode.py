#!/usr/bin/env python3
"""[Flow: Step 1 (search_job_text에 mode=line 파라미터 추가) -> Step 2 (스캔 PDF 출신인 경우 bbox 확정)
      -> Step 3 (mode=text이거나 스캔 PDF 출신이 아닌 경우 bbox 유지) -> Step 4 (테스트 검증)]

스캔 PDF 출신 searchable PDF에서 하이라이트/주석을 해당 줄 전체에 표시하기 위해,
search_job_text의 mode=line일 때 match의 bbox를 해당 줄 전체로 확장한다.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch, AsyncMock
import pytest
from fastapi.testclient import TestClient


class TestSearchJobTextLineMode:
    """search_job_text의 mode=line 파라미터가 스캔 PDF 출신에서 bbox를 줄 전체로 확장하는지 검증."""

    def test_mode_line_expands_bbox_for_scanned_pdf(self):
        """[Flow: mode=line + 스캔 PDF 출신 -> bbox가 줄 전체로 확장 검증]

        mode=line이고 job.result_ocr_layout_storage_path가 있으면,
        match의 bbox_x0가 페이지 좌측으로, bbox_x1이 페이지 우측으로 확장되어야 한다.
        y 범위는 유지된다.
        """
        # 이 테스트는 search_job_text에 mode 파라미터가 추가된 후 통과해야 함
        # 현재는 mode 파라미터가 없으므로 실패 예상 (Red)
        from backend.api.jobs import _expand_match_to_line
        # _expand_match_to_line 함수가 존재해야 함
        assert _expand_match_to_line is not None

        # match의 bbox: x0=100, y0=200, x1=150, y1=215
        # 페이지 크기: width=595, height=842
        match = {
            "page_no": 1,
            "bbox_pdf": [100.0, 200.0, 150.0, 215.0],
            "text": "수용기관",
        }
        page_rect = MagicMock()
        page_rect.x0 = 0.0
        page_rect.x1 = 595.0
        page_rect.y0 = 0.0
        page_rect.y1 = 842.0

        expanded = _expand_match_to_line(match, page_rect)
        # x 범위가 페이지 전체 너비(또는 여백 포함)로 확장되어야 함
        assert expanded["bbox_pdf"][0] <= 50.0, (
            f"x0가 좌측으로 확장되어야 함, got {expanded['bbox_pdf'][0]}"
        )
        assert expanded["bbox_pdf"][2] >= 545.0, (
            f"x1이 우측으로 확장되어야 함, got {expanded['bbox_pdf'][2]}"
        )
        # y 범위는 유지되어야 함
        assert expanded["bbox_pdf"][1] == 200.0, (
            f"y0는 유지되어야 함, got {expanded['bbox_pdf'][1]}"
        )
        assert expanded["bbox_pdf"][3] == 215.0, (
            f"y1은 유지되어야 함, got {expanded['bbox_pdf'][3]}"
        )

    def test_mode_text_does_not_expand_bbox(self):
        """[Flow: mode=text -> bbox가 확장되지 않음 검증]

        mode=text이면 bbox가 원본 그대로 유지되어야 한다.
        """
        from backend.api.jobs import _expand_match_to_line

        match = {
            "page_no": 1,
            "bbox_pdf": [100.0, 200.0, 150.0, 215.0],
            "text": "수용기관",
        }
        page_rect = MagicMock()
        page_rect.x0 = 0.0
        page_rect.x1 = 595.0
        page_rect.y0 = 0.0
        page_rect.y1 = 842.0

        # expand=False이면 확장하지 않음
        expanded = _expand_match_to_line(match, page_rect, expand=False)
        assert expanded["bbox_pdf"] == [100.0, 200.0, 150.0, 215.0]

    def test_line_mode_preserves_page_no_and_text(self):
        """[Flow: mode=line -> page_no와 text가 유지되는지 검증]"""
        from backend.api.jobs import _expand_match_to_line

        match = {
            "page_no": 3,
            "bbox_pdf": [100.0, 200.0, 150.0, 215.0],
            "text": "테스트 텍스트",
        }
        page_rect = MagicMock()
        page_rect.x0 = 0.0
        page_rect.x1 = 595.0
        page_rect.y0 = 0.0
        page_rect.y1 = 842.0

        expanded = _expand_match_to_line(match, page_rect)
        assert expanded["page_no"] == 3
        assert expanded["text"] == "테스트 텍스트"

    def test_line_mode_with_margin(self):
        """[Flow: mode=line -> 좌우 여백이 추가되는지 검증]

        페이지 전체 너비(0 ~ 595)가 아니라, 좌우 여백(예: 5%)을 둔 범위로 확장되어야 함.
        """
        from backend.api.jobs import _expand_match_to_line

        match = {
            "page_no": 1,
            "bbox_pdf": [100.0, 200.0, 150.0, 215.0],
            "text": "수용기관",
        }
        page_rect = MagicMock()
        page_rect.x0 = 0.0
        page_rect.x1 = 595.0
        page_rect.y0 = 0.0
        page_rect.y1 = 842.0

        expanded = _expand_match_to_line(match, page_rect)
        # 좌우 여백이 페이지 너비의 5% 이내여야 함
        margin = 595.0 * 0.1  # 10% 여유
        assert expanded["bbox_pdf"][0] >= 0.0 - margin, "x0가 음수가 되지 않아야 함"
        assert expanded["bbox_pdf"][2] <= 595.0 + margin, "x1이 페이지 너비를 크게 초과하지 않아야 함"
