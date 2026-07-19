#!/usr/bin/env python3
"""[Flow: Step 1 (A4 page_rect 생성) -> Step 2 (device <-> canonical, pdf_user <-> canonical 변환)
      -> Step 3 (round-trip 및 직접 값 검증)]

canonical_annotation_coords 모듈이 device-space / PDF user-space / canonical normalized
공간 사이에서 올바르게 변환하는지 검증한다.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import fitz
import pytest

from backend.core import canonical_annotation_coords as cac


def _a4_page_rect() -> fitz.Rect:
    """[Flow: Step 1 (A4 크기 595x842 pt의 page_rect 생성)]"""
    return fitz.Rect(0.0, 0.0, 595.0, 842.0)


class TestCanonicalAnnotationCoords:
    """device / PDF user-space / canonical 간 rect/point 변환을 검증한다."""

    def test_device_rect_to_canonical_and_back(self):
        """[Flow: device rect -> canonical -> device round-trip]"""
        page_rect = _a4_page_rect()
        device_rect = {"origin": {"x": 59.5, "y": 84.2}, "size": {"width": 119.0, "height": 168.4}}

        canonical = cac.device_rect_to_canonical(device_rect, page_rect.width, page_rect.height)
        assert canonical["origin"]["x"] == pytest.approx(0.1, abs=1e-9)
        assert canonical["origin"]["y"] == pytest.approx(0.1, abs=1e-9)
        assert canonical["size"]["width"] == pytest.approx(0.2, abs=1e-9)
        assert canonical["size"]["height"] == pytest.approx(0.2, abs=1e-9)

        restored = cac.canonical_rect_to_device(canonical, page_rect.width, page_rect.height)
        assert restored["origin"]["x"] == pytest.approx(59.5, abs=1e-9)
        assert restored["origin"]["y"] == pytest.approx(84.2, abs=1e-9)
        assert restored["size"]["width"] == pytest.approx(119.0, abs=1e-9)
        assert restored["size"]["height"] == pytest.approx(168.4, abs=1e-9)

    def test_pdf_user_rect_to_canonical_and_back(self):
        """[Flow: PDF user-space rect -> canonical -> PDF user-space round-trip]"""
        page_rect = _a4_page_rect()
        # PDF user-space: origin bottom-left, y up. A4 842pt. rect y0=700, y1=720 => height 20 near top.
        pdf_rect = {"origin": {"x": 100.0, "y": 700.0}, "size": {"width": 100.0, "height": 20.0}}

        canonical = cac.pdf_user_rect_to_canonical(pdf_rect, page_rect)
        # canonical top-left y = (page.y1 - pdf.y1) / height
        assert canonical["origin"]["x"] == pytest.approx(100.0 / 595.0, rel=1e-6)
        assert canonical["origin"]["y"] == pytest.approx((842.0 - 720.0) / 842.0, rel=1e-6)
        assert canonical["size"]["width"] == pytest.approx(100.0 / 595.0, rel=1e-6)
        assert canonical["size"]["height"] == pytest.approx(20.0 / 842.0, rel=1e-6)

        restored_fitz = cac.canonical_rect_to_pdf_user(canonical, page_rect)
        assert restored_fitz.x0 == pytest.approx(100.0, abs=1e-3)
        assert restored_fitz.y0 == pytest.approx(700.0, abs=1e-3)
        assert restored_fitz.x1 == pytest.approx(200.0, abs=1e-3)
        assert restored_fitz.y1 == pytest.approx(720.0, abs=1e-3)

    def test_canonical_point_to_pdf_user_and_back(self):
        """[Flow: canonical point -> PDF user-space point -> canonical round-trip]"""
        page_rect = _a4_page_rect()
        canonical_point = {"x": 0.5, "y": 0.25}

        pdf_point = cac.canonical_point_to_pdf_user(canonical_point, page_rect)
        assert pdf_point.x == pytest.approx(297.5, abs=1e-9)
        assert pdf_point.y == pytest.approx(842.0 - 0.25 * 842.0, abs=1e-9)

        restored = cac.pdf_user_point_to_canonical(pdf_point, page_rect)
        assert restored["x"] == pytest.approx(0.5, abs=1e-9)
        assert restored["y"] == pytest.approx(0.25, abs=1e-9)

    def test_device_point_to_canonical_and_back(self):
        """[Flow: device point -> canonical point -> device round-trip]"""
        page_rect = _a4_page_rect()
        device_point = {"x": 59.5, "y": 84.2}

        canonical = cac.device_point_to_canonical(device_point, page_rect.width, page_rect.height)
        assert canonical["x"] == pytest.approx(0.1, abs=1e-9)
        assert canonical["y"] == pytest.approx(0.1, abs=1e-9)

        restored = cac.canonical_point_to_device(canonical, page_rect.width, page_rect.height)
        assert restored["x"] == pytest.approx(59.5, abs=1e-9)
        assert restored["y"] == pytest.approx(84.2, abs=1e-9)

    def test_rect_dict_to_fitz_accepts_x_y_width_height(self):
        """[Flow: 하위 호환 {x, y, width, height} rect도 fitz.Rect로 변환]"""
        rect = cac._rect_dict_to_fitz({"x": 10.0, "y": 20.0, "width": 30.0, "height": 40.0})
        assert rect.x0 == 10.0
        assert rect.y0 == 20.0
        assert rect.x1 == 40.0
        assert rect.y1 == 60.0

    def test_invalid_rect_raises_value_error(self):
        """[Flow: width/height가 0 이하면 ValueError 발생]"""
        with pytest.raises(ValueError):
            cac._rect_dict_to_fitz({"origin": {"x": 0, "y": 0}, "size": {"width": 0, "height": 10}})
