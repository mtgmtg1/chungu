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

from backend.core.pdf_text_layer import TextLayerSearcher, add_text_layer_from_ocr


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


class TestInvisibleTextAccuracy:
    """투명 텍스트의 폰트 크기와 위치가 OCR bbox에 최대한 일치하는지 검증한다."""

    def test_font_size_matches_bbox_height_for_short_text(self):
        """[Flow: 짧은 텍스트는 bbox 높이에 맞춰 폰트 크기가 결정되어야 함]
        짧은 텍스트(가로 폭이 충분)의 경우, 폰트 크기가 bbox 높이의 ~80% 이상이어야
        실제 이미지 텍스트와 검색 하이라이트 영역이 일치한다.
        """
        pdf_bytes = _make_a4_image_pdf()
        page_width = 595.0
        page_height = 842.0

        # 짧은 텍스트: bbox 너비가 충분하므로 폰트 축소가 일어나지 않아야 함
        # bbox 높이 30pt, 너비 300pt (충분함)
        x0, y0_top, x1, y1_top = 100.0, 200.0, 400.0, 230.0
        bbox_height = y1_top - y0_top  # 30pt
        page_ocr_results = {1: [("ABC", (x0, y0_top, x1, y1_top))]}
        layout_by_page = {1: {"width": page_width, "height": page_height}}

        result_bytes = add_text_layer_from_ocr(
            pdf_bytes, page_ocr_results, dpi=300, language="en", layout_by_page=layout_by_page,
        )

        doc = fitz.open(stream=result_bytes, filetype="pdf")
        page = doc[0]
        rects = page.search_for("ABC")
        assert len(rects) == 1

        found = rects[0]
        found_height = found.y1 - found.y0
        # 폰트 크기가 bbox 높이의 70% 이상이어야 함 (너무 작으면 안 됨)
        assert found_height >= bbox_height * 0.7, (
            f"Text height {found_height} too small vs bbox height {bbox_height}. "
            f"Font size may be over-shrunk."
        )
        doc.close()

    def test_text_width_does_not_exceed_bbox(self):
        """[Flow: 긴 텍스트도 bbox 가로 폭을 초과하지 않아야 함]
        텍스트가 bbox보다 넓으면 폰트 크기가 축소되어 가로 폭 내에 들어와야 한다.
        """
        pdf_bytes = _make_a4_image_pdf()
        page_width = 595.0
        page_height = 842.0

        # 좁은 bbox에 긴 텍스트
        x0, y0_top, x1, y1_top = 100.0, 200.0, 200.0, 230.0
        bbox_width = x1 - x0  # 100pt
        page_ocr_results = {1: [("ABCDEFGH", (x0, y0_top, x1, y1_top))]}
        layout_by_page = {1: {"width": page_width, "height": page_height}}

        result_bytes = add_text_layer_from_ocr(
            pdf_bytes, page_ocr_results, dpi=300, language="en", layout_by_page=layout_by_page,
        )

        doc = fitz.open(stream=result_bytes, filetype="pdf")
        page = doc[0]
        rects = page.search_for("ABCDEFGH")
        # 텍스트가 검색되어야 함
        assert len(rects) >= 1
        # 검색 결과가 bbox 가로 폭을 크게 초과하면 안 됨
        for found in rects:
            found_width = found.x1 - found.x0
            assert found_width <= bbox_width + 5.0, (
                f"Text width {found_width} exceeds bbox width {bbox_width}. "
                f"Font size not properly shrunk."
            )
        doc.close()

    def test_text_vertically_centered_in_bbox(self):
        """[Flow: 텍스트가 bbox 내에 수직으로 적절히 위치해야 함]
        baseline 계산이 정확하면 검색 결과의 y 범위가 bbox y 범위 내에 들어와야 한다.
        """
        pdf_bytes = _make_a4_image_pdf()
        page_width = 595.0
        page_height = 842.0

        x0, y0_top, x1, y1_top = 100.0, 300.0, 400.0, 340.0
        page_ocr_results = {1: [("Test", (x0, y0_top, x1, y1_top))]}
        layout_by_page = {1: {"width": page_width, "height": page_height}}

        result_bytes = add_text_layer_from_ocr(
            pdf_bytes, page_ocr_results, dpi=300, language="en", layout_by_page=layout_by_page,
        )

        doc = fitz.open(stream=result_bytes, filetype="pdf")
        page = doc[0]
        rects = page.search_for("Test")
        assert len(rects) == 1

        found = rects[0]
        expected_y0 = page_height - y1_top  # PDF user-space y0 (bottom)
        expected_y1 = page_height - y0_top  # PDF user-space y1 (top)

        # 텍스트가 bbox 내에 수직으로 위치해야 함 (허용 오차 3pt)
        tol = 3.0
        assert found.y0 >= expected_y0 - tol, (
            f"y0 {found.y0} below bbox bottom {expected_y0}. Text positioned too low."
        )
        assert found.y1 <= expected_y1 + tol, (
            f"y1 {found.y1} above bbox top {expected_y1}. Text positioned too high."
        )
        doc.close()

    def test_cjk_text_uses_full_bbox_width(self):
        """[Flow: CJK 텍스트는 정사각형 글리프이므로 bbox 폭을 정확히 채워야 함]
        CJK 문자는 폰트 크기와 거의 동일한 폭을 가지므로, CHAR_WIDTH_RATIO=0.85 대신
        정확한 get_text_length를 사용하면 폰트 크기가 과도하게 축소되지 않아야 한다.
        """
        pdf_bytes = _make_a4_image_pdf()
        page_width = 595.0
        page_height = 842.0

        # CJK 텍스트 4글자, bbox 너비 120pt, 높이 30pt
        x0, y0_top, x1, y1_top = 100.0, 200.0, 220.0, 230.0
        bbox_height = y1_top - y0_top  # 30pt
        page_ocr_results = {1: [("테스트", (x0, y0_top, x1, y1_top))]}
        layout_by_page = {1: {"width": page_width, "height": page_height}}

        result_bytes = add_text_layer_from_ocr(
            pdf_bytes, page_ocr_results, dpi=300, language="ko", layout_by_page=layout_by_page,
        )

        doc = fitz.open(stream=result_bytes, filetype="pdf")
        page = doc[0]
        rects = page.search_for("테스트")
        assert len(rects) >= 1

        found = rects[0]
        found_height = found.y1 - found.y0
        # CJK 텍스트 폰트 크기가 bbox 높이의 70% 이상이어야 함
        assert found_height >= bbox_height * 0.7, (
            f"CJK text height {found_height} too small vs bbox height {bbox_height}. "
            f"Font may be over-shrunk due to wrong width estimation."
        )
        doc.close()


class TestTextLayerSearcherCoordinateSpace:
    """[Flow: TextLayerSearcher.search가 PDF user-space (y=0 하단) 좌표를 반환하는지 검증]"""

    def test_search_returns_pdf_user_space_coordinates(self):
        """[Flow: Step 1 (A4 PDF에 상단 y=100~130 영역 텍스트 삽입)
              -> Step 2 (TextLayerSearcher.search 실행)
              -> Step 3 (반환된 y0, y1이 PDF user-space y=712~742 범위에 포함되는지 검증)]"""
        pdf_bytes = _make_a4_image_pdf()
        page_width = 595.0
        page_height = 842.0

        # 상단 100~130pt (top-left) 위치에 "SEARCH_TARGET"
        x0, y0_top, x1, y1_top = 100.0, 100.0, 300.0, 130.0
        page_ocr_results = {1: [("SEARCH_TARGET", (x0, y0_top, x1, y1_top))]}
        layout_by_page = {1: {"width": page_width, "height": page_height}}

        result_bytes = add_text_layer_from_ocr(
            pdf_bytes, page_ocr_results, dpi=300, language="en", layout_by_page=layout_by_page
        )

        searcher = TextLayerSearcher(result_bytes)
        try:
            rects = searcher.search(1, "SEARCH_TARGET")
            assert len(rects) == 1, f"Expected 1 match, got {len(rects)}"
            found_x0, found_y0, found_x1, found_y1 = rects[0]

            expected_pdf_user_y0 = page_height - y1_top  # 842 - 130 = 712.0 (하단 기준 y0)
            expected_pdf_user_y1 = page_height - y0_top  # 842 - 100 = 742.0 (하단 기준 y1)

            # TextLayerSearcher.search는 PDF user-space (y=0 하단) 좌표를 반환해야 하므로
            # found_y0는 ~712.0 이어야 함
            assert abs(found_y0 - expected_pdf_user_y0) <= 15.0, (
                f"y0 mismatch: got {found_y0}, expected {expected_pdf_user_y0}"
            )
            assert abs(found_y1 - expected_pdf_user_y1) <= 15.0, (
                f"y1 mismatch: got {found_y1}, expected {expected_pdf_user_y1}"
            )
        finally:
            searcher.close()
