#!/usr/bin/env python3
"""[Flow: Step 1 (원본 텍스트가 있는 PDF 준비)
      -> Step 2 (OCR bbox를 상하 반전된 normalized 좌표로 설정)
      -> Step 3 (add_text_layer_from_ocr에 canary 검증을 통해 텍스트 레이어 추가)
      -> Step 4 (search_for 결과가 원본 위쪽에 집중되어 있는지 assert)]
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import fitz
import pytest

from backend.core.pdf_text_layer import add_text_layer_from_ocr


def _make_pdf_with_visible_text(text: str, x: float, y: float) -> bytes:
    """[Flow: Step 1 (fitz 문서 생성) -> Step 2 (지정 좌표에 텍스트 삽입)
          -> Step 3 (PDF bytes 반환)]"""
    pdf_doc = fitz.open()
    page = pdf_doc.new_page(width=595.0, height=842.0)
    page.insert_text(fitz.Point(x, y), text, fontsize=30, color=(0, 0, 0))
    pdf_bytes = pdf_doc.tobytes()
    pdf_doc.close()
    return pdf_bytes


def _pdf_user_to_top_left_normalized(
    rect: fitz.Rect, page_width: float, page_height: float
) -> tuple[float, float, float, float]:
    """[Flow: Step 1 (PDF user-space rect 수신)
          -> Step 2 (x를 page_width로 나눔)
          -> Step 3 (y축 flip 후 page_height로 나눔)
          -> Step 4 (normalized top-left bbox 반환)]"""
    return (
        rect.x0 / page_width,
        (page_height - rect.y1) / page_height,
        rect.x1 / page_width,
        (page_height - rect.y0) / page_height,
    )


class TestAddTextLayerFromOcrCanary:
    """add_text_layer_from_ocr의 canary page 검증이 y축 반전된 OCR bbox를 올바르게 교정하는지 검증한다."""

    def test_canary_detects_and_fixes_inverted_y(self):
        """[Flow: Step 1 (상단에 "Hello"가 있는 PDF 생성)
              -> Step 2 (상하 반전된 normalized bbox 준비)
              -> Step 3 (add_text_layer_from_ocr 실행)
              -> Step 4 (search_for 결과의 y 분포가 상단에 집중되어 있는지 assert)]"""
        text = "Hello"
        page_width = 595.0
        page_height = 842.0
        baseline_y = 780.0

        pdf_bytes = _make_pdf_with_visible_text(text, 100.0, baseline_y)

        # 원본 PDF에서 ground truth bbox 확인
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = doc[0]
        ground_truth = page.search_for(text)[0]
        doc.close()

        # 올바른 top-left normalized
        correct_normalized = _pdf_user_to_top_left_normalized(ground_truth, page_width, page_height)
        # 상하 반전된 normalized (y=0이 하단처럼 잘못 해석된 경우)
        inverted_normalized = (
            correct_normalized[0],
            1.0 - correct_normalized[3],
            correct_normalized[2],
            1.0 - correct_normalized[1],
        )

        page_ocr_results = {1: [(text, inverted_normalized)]}
        layout_by_page = {
            1: {
                "_coordinate_system": "normalized",
                "_page_width_px": page_width,
                "_page_height_px": page_height,
            }
        }

        # canary가 동작하도록 force_flip_y는 None
        result_bytes = add_text_layer_from_ocr(
            pdf_bytes,
            page_ocr_results,
            dpi=72,
            language="en",
            layout_by_page=layout_by_page,
        )

        doc2 = fitz.open(stream=result_bytes, filetype="pdf")
        page2 = doc2[0]
        matches = page2.search_for(text)
        doc2.close()

        assert len(matches) >= 1
        tops = [m.y1 for m in matches]
        # 상하 반전이 교정되지 않으면 일부 match가 페이지 하단에 생긴다.
        # 모든 match의 상단 y가 페이지 중간보다 위에 있고, 분포가 100pt 이내인지 확인.
        assert all(y > page_height / 2 for y in tops), f"하단에 match가 생김: {matches}"
        assert max(tops) - min(tops) < 100.0, f"match들이 너무 흩어짐: {matches}"

    def test_canary_keeps_correct_orientation(self):
        """[Flow: Step 1 (상단에 "Hello"가 있는 PDF 생성)
              -> Step 2 (올바른 top-left normalized bbox 준비)
              -> Step 3 (add_text_layer_from_ocr 실행)
              -> Step 4 (search_for 결과가 상단에 집중되어 있는지 assert)]"""
        text = "Hello"
        page_width = 595.0
        page_height = 842.0
        baseline_y = 780.0

        pdf_bytes = _make_pdf_with_visible_text(text, 100.0, baseline_y)

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = doc[0]
        ground_truth = page.search_for(text)[0]
        doc.close()

        correct_normalized = _pdf_user_to_top_left_normalized(ground_truth, page_width, page_height)

        page_ocr_results = {1: [(text, correct_normalized)]}
        layout_by_page = {
            1: {
                "_coordinate_system": "normalized",
                "_page_width_px": page_width,
                "_page_height_px": page_height,
            }
        }

        result_bytes = add_text_layer_from_ocr(
            pdf_bytes,
            page_ocr_results,
            dpi=72,
            language="en",
            layout_by_page=layout_by_page,
        )

        doc2 = fitz.open(stream=result_bytes, filetype="pdf")
        page2 = doc2[0]
        matches = page2.search_for(text)
        doc2.close()

        assert len(matches) >= 1
        tops = [m.y1 for m in matches]
        assert all(y > page_height / 2 for y in tops), f"match가 하단으로 내려감: {matches}"
        assert max(tops) - min(tops) < 100.0, f"match들이 너무 흩어짐: {matches}"
