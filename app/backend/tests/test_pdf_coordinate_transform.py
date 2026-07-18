#!/usr/bin/env python3
"""[Flow: Step 1 (A4 PDF page_rect 준비)
      -> Step 2 (normalized_top_left <-> pdf_user_space 변환 검증)
      -> Step 3 (pdf_user_space <-> device_space 변환 검증)
      -> Step 4 (image_top_left <-> pdf_user_space 변환 검증)]
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import fitz
import pytest

from backend.core.pdf_coordinate_transform import (
    normalized_top_left_to_pdf_user,
    pdf_user_to_normalized_top_left,
    image_top_left_to_pdf_user,
    pdf_user_to_image_top_left,
    pdf_user_to_device,
    device_to_pdf_user,
    embedpdf_rect_from_pdf_user,
    pdf_user_rect_from_embedpdf,
)


def _make_a4_page_rect() -> fitz.Rect:
    return fitz.Rect(0, 0, 595.0, 842.0)


class TestCoordinateTransform:
    """좌표계 변환이 matrix로 한 곳에서 정확히 수행되는지 검증한다."""

    def test_normalized_to_pdf_user_and_back(self):
        """[Flow: Step 1 (normalized top-left bbox 수신)
              -> Step 2 (pdf_user_space로 변환)
              -> Step 3 (다시 normalized로 역변환)
              -> Step 4 (원래 값과 일치하는지 assert)]"""
        page_rect = _make_a4_page_rect()
        normalized = fitz.Rect(0.1, 0.4, 0.3, 0.45)  # y0=top, y1=bottom

        pdf_rect = normalized_top_left_to_pdf_user(normalized, page_rect)
        assert pdf_rect.x0 == pytest.approx(59.5, abs=0.001)
        assert pdf_rect.y0 == pytest.approx(463.1, abs=0.001)  # bottom
        assert pdf_rect.x1 == pytest.approx(178.5, abs=0.001)
        assert pdf_rect.y1 == pytest.approx(505.2, abs=0.001)  # top

        back = pdf_user_to_normalized_top_left(pdf_rect, page_rect)
        assert back.x0 == pytest.approx(normalized.x0, abs=0.0001)
        assert back.y0 == pytest.approx(normalized.y0, abs=0.0001)
        assert back.x1 == pytest.approx(normalized.x1, abs=0.0001)
        assert back.y1 == pytest.approx(normalized.y1, abs=0.0001)

    def test_pdf_user_to_device_and_back(self):
        """[Flow: Step 1 (PDF user-space rect 수신)
              -> Step 2 (device_space로 변환)
              -> Step 3 (다시 PDF user-space로 역변환)
              -> Step 4 (원래 값과 일치하는지 assert)]"""
        page_rect = _make_a4_page_rect()
        pdf_rect = fitz.Rect(59.5, 463.1, 178.5, 505.2)  # y0=bottom, y1=top

        device = pdf_user_to_device(pdf_rect, page_rect)
        assert device.x0 == pytest.approx(59.5, abs=0.001)
        assert device.y0 == pytest.approx(842.0 - 505.2, abs=0.001)  # top
        assert device.x1 == pytest.approx(178.5, abs=0.001)
        assert device.y1 == pytest.approx(842.0 - 463.1, abs=0.001)  # bottom

        back = device_to_pdf_user(device, page_rect)
        assert back.x0 == pytest.approx(pdf_rect.x0, abs=0.0001)
        assert back.y0 == pytest.approx(pdf_rect.y0, abs=0.0001)
        assert back.x1 == pytest.approx(pdf_rect.x1, abs=0.0001)
        assert back.y1 == pytest.approx(pdf_rect.y1, abs=0.0001)

    def test_image_top_left_to_pdf_user(self):
        """[Flow: Step 1 (300 DPI 이미지 픽셀 bbox 수신)
              -> Step 2 (PDF user-space로 변환)
              -> Step 3 (예상 point 값과 일치하는지 assert)]"""
        page_rect = _make_a4_page_rect()
        # 300 DPI A4 픽셀 크기
        pixel_bbox = fitz.Rect(100.0, 200.0, 300.0, 400.0)  # top-left

        pdf_rect = image_top_left_to_pdf_user(pixel_bbox, page_rect, 300.0)
        scale = 72.0 / 300.0
        assert pdf_rect.x0 == pytest.approx(100.0 * scale, abs=0.001)
        assert pdf_rect.y0 == pytest.approx(842.0 - 400.0 * scale, abs=0.001)
        assert pdf_rect.x1 == pytest.approx(300.0 * scale, abs=0.001)
        assert pdf_rect.y1 == pytest.approx(842.0 - 200.0 * scale, abs=0.001)

    def test_embedpdf_rect_roundtrip(self):
        """[Flow: Step 1 (PDF user-space rect 수신)
              -> Step 2 (EmbedPDF dict로 변환)
              -> Step 3 (다시 PDF user-space로 역변환)
              -> Step 4 (원래 값과 일치하는지 assert)]"""
        page_rect = _make_a4_page_rect()
        pdf_rect = fitz.Rect(100.0, 400.0, 300.0, 600.0)

        embed = embedpdf_rect_from_pdf_user(pdf_rect, page_rect)
        assert embed["origin"]["x"] == pytest.approx(100.0, abs=0.001)
        assert embed["origin"]["y"] == pytest.approx(842.0 - 600.0, abs=0.001)
        assert embed["size"]["width"] == pytest.approx(200.0, abs=0.001)
        assert embed["size"]["height"] == pytest.approx(200.0, abs=0.001)

        back = pdf_user_rect_from_embedpdf(embed, page_rect)
        assert back.x0 == pytest.approx(pdf_rect.x0, abs=0.0001)
        assert back.y0 == pytest.approx(pdf_rect.y0, abs=0.0001)
        assert back.x1 == pytest.approx(pdf_rect.x1, abs=0.0001)
        assert back.y1 == pytest.approx(pdf_rect.y1, abs=0.0001)
