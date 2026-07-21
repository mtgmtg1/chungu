#!/usr/bin/env python3
# [Flow: Step 1 (top-left y-down bbox 입력) -> Step 2 (_normalize_bbox 변환)
#       -> Step 3 (top-left normalized 결과 검증) -> Step 4 (PDF user-space round-trip 검증)]
# _normalize_bbox의 bbox_origin 파라미터가 top_left/bottom_left를 올바르게 구분하는지 검증한다.
# 로컬 PaddleOCR pipeline은 이미지 좌표계(top-left y↓)로 bbox를 반환하므로 y flip이 없어야 하고,
# AI Studio PDF 직접 제출 경로는 PDF user-space(bottom-left y↑)로 bbox를 반환하므로 y flip이 필요하다.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import fitz
import pytest

from backend.paddleocr_service.main import _normalize_bbox, _extract_layout_from_result
from backend.core.pdf_coordinate_transform import normalized_top_left_to_pdf_user


PAGE_WIDTH_PX = 1000.0
PAGE_HEIGHT_PX = 1000.0


def test_top_left_origin_no_y_flip():
    """[Flow: top-left y↓ bbox는 y flip 없이 단순 정규화만 수행되어야 함]

    이미지 상단(y=100~150)의 텍스트 bbox를 top_left origin으로 변환하면
    normalized y도 상단(0.10~0.15)이 되어야 한다.
    """
    bbox = [100.0, 100.0, 300.0, 150.0]  # top-left y↓: y0=위쪽=100, y1=아래쪽=150
    result = _normalize_bbox(bbox, PAGE_WIDTH_PX, PAGE_HEIGHT_PX, bbox_origin="top_left")
    assert result == pytest.approx([0.1, 0.1, 0.3, 0.15], abs=1e-6)


def test_bottom_left_origin_y_flip():
    """[Flow: bottom-left y↑ bbox는 y flip으로 top-left normalized로 변환되어야 함]

    PDF user-space 하단(y=100~150, y↑에서 작은 값=아래쪽)의 텍스트 bbox를
    bottom_left origin으로 변환하면 normalized y는 상단(0.85~0.90)이 되어야 한다.
    """
    bbox = [100.0, 100.0, 300.0, 150.0]  # bottom-left y↑: y0=아래쪽=100, y1=위쪽=150
    result = _normalize_bbox(bbox, PAGE_WIDTH_PX, PAGE_HEIGHT_PX, bbox_origin="bottom_left")
    # y0' = 1 - y1/H = 1 - 150/1000 = 0.85 (top-left에서 위쪽... 실제로는 아래쪽)
    # y1' = 1 - y0/H = 1 - 100/1000 = 0.90 (top-left에서 아래쪽)
    assert result == pytest.approx([0.1, 0.85, 0.3, 0.90], abs=1e-6)


def test_top_left_roundtrip_to_pdf_user_space():
    """[Flow: top-left y↓ bbox -> normalized -> PDF user-space 변환 시 y가 뒤집히지 않아야 함]

    핵심 회귀 테스트: 로컬 PaddleOCR pipeline 경로에서 이미지 상단 텍스트가
    PDF user-space 상단(y↑에서 큰 값)에 위치해야 한다.
    기존 버그에서는 y flip이 중복 상쇄되어 상단 텍스트가 PDF 하단에 그려졌다.
    """
    # 이미지 상단 텍스트 (top-left y↓): y=100~150
    bbox_top_left = [100.0, 100.0, 300.0, 150.0]
    normalized = _normalize_bbox(bbox_top_left, PAGE_WIDTH_PX, PAGE_HEIGHT_PX, bbox_origin="top_left")

    # 300 DPI 가정: PDF page = 1000px * 72/300 = 240pt
    page_rect = fitz.Rect(0, 0, 240.0, 240.0)
    pdf_user = normalized_top_left_to_pdf_user(normalized, page_rect)

    # 올바른 변환: top-left y=100~150 -> normalized 0.10~0.15 -> PDF y = 240*(1-0.15) ~ 240*(1-0.10) = 204~216
    # 기존 버그: y flip 중복 상쇄로 normalized 0.85~0.90 -> PDF y = 24~36 (하단에 그려짐)
    assert pdf_user.y0 == pytest.approx(204.0, abs=1.0), (
        f"y0 (하단)이 올바르지 않습니다. actual={pdf_user.y0}, expected≈204. "
        f"이미지 상단 텍스트가 PDF 상단(큰 y값)에 그려져야 합니다."
    )
    assert pdf_user.y1 == pytest.approx(216.0, abs=1.0), (
        f"y1 (상단)이 올바르지 않습니다. actual={pdf_user.y1}, expected≈216."
    )


def test_top_left_origin_bug_regression_with_bottom_left():
    """[Flow: 기존 버그 재현 — top-left y↓ bbox를 bottom_left origin으로 변환하면 y가 뒤집힘]

    기존 _normalize_bbox는 bbox_origin 구분 없이 항상 y flip을 수행했다.
    로컬 PaddleOCR pipeline의 top-left y↓ bbox에 y flip을 적용하면
    normalized y가 0.85~0.90(아래쪽)이 되고, PDF user-space 변환 후 y=24~36(하단)이 되어
    이미지 상단 텍스트가 PDF 하단에 그려지는 버그가 발생한다.
    이 테스트는 해당 버그가 bottom_left origin misuse로 재현됨을 확인한다.
    """
    bbox_top_left = [100.0, 100.0, 300.0, 150.0]
    # 잘못된 origin 지정 (기존 버그 동작)
    normalized_buggy = _normalize_bbox(bbox_top_left, PAGE_WIDTH_PX, PAGE_HEIGHT_PX, bbox_origin="bottom_left")
    page_rect = fitz.Rect(0, 0, 240.0, 240.0)
    pdf_user_buggy = normalized_top_left_to_pdf_user(normalized_buggy, page_rect)
    # 버그: 이미지 상단 텍스트가 PDF 하단(y=24~36)에 그려짐
    assert pdf_user_buggy.y0 < 50.0, (
        f"기존 버그 재현 실패. actual y0={pdf_user_buggy.y0}. "
        f"bottom_left origin을 top-left bbox에 적용하면 y가 하단으로 뒤집혀야 합니다."
    )


def test_bottom_left_roundtrip_to_pdf_user_space():
    """[Flow: bottom-left y↑ bbox -> normalized -> PDF user-space 변환 시 원래 좌표 복원]

    AI Studio PDF 직접 제출 경로: PDF user-space 하단(y=100~150, y↑) 텍스트가
    round-trip 후 동일한 PDF user-space 좌표로 복원되어야 한다.
    """
    # PDF user-space 하단 텍스트 (bottom-left y↑): y=100~150 (y↑에서 작은 값=아래쪽)
    bbox_bottom_left = [100.0, 100.0, 300.0, 150.0]
    normalized = _normalize_bbox(bbox_bottom_left, PAGE_WIDTH_PX, PAGE_HEIGHT_PX, bbox_origin="bottom_left")

    page_rect = fitz.Rect(0, 0, 1000.0, 1000.0)
    pdf_user = normalized_top_left_to_pdf_user(normalized, page_rect)

    # round-trip: 원래 PDF user-space 좌표로 복원되어야 함
    assert pdf_user.x0 == pytest.approx(100.0, abs=1.0)
    assert pdf_user.x1 == pytest.approx(300.0, abs=1.0)
    assert pdf_user.y0 == pytest.approx(100.0, abs=1.0)
    assert pdf_user.y1 == pytest.approx(150.0, abs=1.0)


def test_extract_layout_records_bbox_origin():
    """[Flow: _extract_layout_from_result가 _bbox_origin 메타데이터를 기록하는지 검증]

    소비자가 layout의 bbox_origin을 확인할 수 있어야 디버깅이 가능하다.
    """
    res = {
        "width": 1000.0,
        "height": 1000.0,
        "parsing_res_list": [
            {"block_bbox": [100, 100, 300, 150], "block_content": "text", "block_label": "text"}
        ],
    }
    layout_top = _extract_layout_from_result(res, bbox_origin="top_left")
    assert layout_top.get("_bbox_origin") == "top_left"

    layout_bottom = _extract_layout_from_result(res, bbox_origin="bottom_left")
    assert layout_bottom.get("_bbox_origin") == "bottom_left"


def test_extract_layout_top_left_normalizes_without_y_flip():
    """[Flow: _extract_layout_from_result가 top_left origin에서 y flip 없이 정규화하는지 검증]

    통합 회귀: parsing_res_list와 overall_ocr_res 모두에 top_left origin이 적용되어야 한다.
    """
    res = {
        "width": 1000.0,
        "height": 1000.0,
        "parsing_res_list": [
            {"block_bbox": [100, 100, 300, 150], "block_content": "text", "block_label": "text"}
        ],
        "overall_ocr_res": {
            "rec_boxes": [[100, 100, 300, 150]],
            "rec_texts": ["text"],
        },
    }
    layout = _extract_layout_from_result(res, bbox_origin="top_left")
    block_bbox = layout["parsing_res_list"][0]["block_bbox"]
    rec_box = layout["overall_ocr_res"]["rec_boxes"][0]
    expected = [0.1, 0.1, 0.3, 0.15]
    assert block_bbox == pytest.approx(expected, abs=1e-6)
    assert rec_box == pytest.approx(expected, abs=1e-6)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
