#!/usr/bin/env python3
"""[Flow: Step 1 (pdf_text_layer._insert_invisible_text로 투명 텍스트 삽입)
      -> Step 2 (fitz Page.search_for로 검색)
      -> Step 3 (반환된 bbox가 원래 bbox 범위 내에 들어오는지 검증)]

OCR로 추가한 투명 텍스트 레이어의 검색 결과가 원래 bbox를 벗어나지 않도록
baseline 계산이 올바른지 확인하는 회귀 테스트입니다.
"""
import sys
import os
import io
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import fitz
import pytest

from backend.core.pdf_text_layer import add_text_layer_from_ocr


def _make_a4_image_pdf() -> bytes:
    """[Flow: Step 1 (A4 크기 빈 PDF 생성) -> Step 2 (bytes 반환)]"""
    doc = fitz.open()
    doc.new_page(width=595.0, height=842.0)
    stream = io.BytesIO()
    doc.save(stream)
    doc.close()
    return stream.getvalue()


class TestInvisibleTextBaseline:
    """투명 텍스트 삽입 후 search_for 결과가 bbox 안에 들어오는지 검증한다."""

    def test_search_result_fits_inside_source_bbox(self):
        """[Flow: Step 1 (A4 PDF 준비)
              -> Step 2 (페이지 중앙에 normalized bbox 지정)
              -> Step 3 (add_text_layer_from_ocr로 텍스트 레이어 추가)
              -> Step 4 (search_for로 bbox 검색)
              -> Step 5 (검색 결과가 원래 bbox 범위 내인지 assert)]"""
        pdf_bytes = _make_a4_image_pdf()

        # 페이지 중앙에 텍스트 블록 하나. normalized 좌표(y=0 상단, y=1 하단)
        nx0, ny0, nx1, ny1 = 0.3, 0.4, 0.7, 0.45
        page_ocr_results = {
            1: [("hello", (nx0, ny0, nx1, ny1))],
        }
        layout_by_page = {
            1: {
                "_coordinate_system": "normalized",
                "_page_width_px": 1240,
                "_page_height_px": 1754,
            }
        }

        result_bytes = add_text_layer_from_ocr(
            pdf_bytes,
            page_ocr_results,
            dpi=300,
            language="en",
            layout_by_page=layout_by_page,
        )

        doc = fitz.open(stream=result_bytes, filetype="pdf")
        page = doc[0]
        rects = page.search_for("hello")
        assert len(rects) == 1, f"Expected 1 match, got {len(rects)}"

        found = rects[0]
        page_width = 595.0
        page_height = 842.0
        expected_x0 = nx0 * page_width
        expected_x1 = nx1 * page_width
        expected_y0 = (1 - ny1) * page_height
        expected_y1 = (1 - ny0) * page_height

        # 검색 결과가 원래 bbox를 크게 벗어나면 안 됨
        # 허용 오차 5pt (PyMuPDF glyph metrics 차이 허용)
        tol = 5.0
        assert found.x0 >= expected_x0 - tol, f"x0 too small: {found.x0} < {expected_x0 - tol}"
        assert found.x1 <= expected_x1 + tol, f"x1 too large: {found.x1} > {expected_x1 + tol}"

        # 핵심: y축 반전이나 baseline 오류로 인해 위로 삐져나가지 않아야 함
        assert found.y0 >= expected_y0 - tol, (
            f"y0 (bottom) too small: {found.y0} < {expected_y0 - tol}. "
            f"Baseline may be placed too high."
        )
        assert found.y1 <= expected_y1 + tol, (
            f"y1 (top) too large: {found.y1} > {expected_y1 + tol}. "
            f"Text may extend above the intended bbox."
        )

        doc.close()

    def test_search_result_fits_inside_source_bbox_top_left_points(self):
        """[Flow: Step 1 (A4 PDF 준비)
              -> Step 2 (페이지 상단에 points top-left bbox 지정)
              -> Step 3 (add_text_layer_from_ocr로 텍스트 레이어 추가)
              -> Step 4 (search_for로 bbox 검색)
              -> Step 5 (검색 결과가 원래 상단 bbox 범위 내인지 assert)]

        OCR 서비스가 좌표계 메타데이터 없이 points top-left (y=0이 상단) bbox를
        반환할 때도 텍스트 레이어가 PDF user-space로 올바르게 변환되어야 합니다.
        """
        pdf_bytes = _make_a4_image_pdf()

        page_width = 595.0
        page_height = 842.0
        # 페이지 상단, 좌측에 위치한 텍스트 블록 (points, y=0이 상단)
        x0, y0_top, x1, y1_top = 120.0, 100.0, 420.0, 130.0
        page_ocr_results = {
            1: [("hello", (x0, y0_top, x1, y1_top))],
        }
        # layout 자체에 width/height가 points 단위로 들어있다고 가정
        layout_by_page = {
            1: {
                "width": page_width,
                "height": page_height,
            }
        }

        result_bytes = add_text_layer_from_ocr(
            pdf_bytes,
            page_ocr_results,
            dpi=300,
            language="en",
            layout_by_page=layout_by_page,
        )

        doc = fitz.open(stream=result_bytes, filetype="pdf")
        page = doc[0]
        rects = page.search_for("hello")
        assert len(rects) == 1, f"Expected 1 match, got {len(rects)}"

        found = rects[0]
        # points top-left -> PDF user-space (y=0 하단, y↑)
        expected_x0 = x0
        expected_x1 = x1
        expected_y0 = page_height - y1_top
        expected_y1 = page_height - y0_top

        tol = 5.0
        assert found.x0 >= expected_x0 - tol, f"x0 too small: {found.x0} < {expected_x0 - tol}"
        assert found.x1 <= expected_x1 + tol, f"x1 too large: {found.x1} > {expected_x1 + tol}"

        # 핵심: y축이 반전되지 않고 상단에 삽입되어야 함
        assert found.y0 >= expected_y0 - tol, (
            f"y0 (bottom) too small: {found.y0} < {expected_y0 - tol}. "
            f"Text may be flipped vertically."
        )
        assert found.y1 <= expected_y1 + tol, (
            f"y1 (top) too large: {found.y1} > {expected_y1 + tol}. "
            f"Text may be flipped vertically."
        )

        doc.close()
