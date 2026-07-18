#!/usr/bin/env python3
"""[Flow: Step 1 (_extract_layout_from_result에 PDF user-space bbox 입력)
      -> Step 2 (page_height_pt와 page_height_px 비율 + 상단 블록 y 분포로 감지)
      -> Step 3 (반환된 normalized 좌표가 top-left 기준인지 검증)]

AI Studio에 원본 PDF를 직접 제출할 때 반환 bbox가 PDF user-space(y↑)일 경우,
_extract_layout_from_result가 이를 top-left normalized(y=0 상단)로 올바르게 변환하는지
검증하는 회귀 테스트입니다.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from backend.paddleocr_service.main import _extract_layout_from_result


def test_extract_layout_from_pdf_user_space():
    """[Flow: Step 1 (A4 크기 PDF user-space bbox 준비)
          -> Step 2 (page_height_px가 page_height_pt와 거의 동일한 prunedResult 구성)
          -> Step 3 (상단 블록이 페이지 상반부에 위치한 경우 PDF user-space로 감지)
          -> Step 4 (normalized 좌표가 y=0 상단 기준인지 assert)]"""

    page_height_pt = 842.0
    page_width_pt = 595.0

    # A4 페이지 상단에 위치한 타이틀 "항소이유서".
    # PDF user-space: y0=800(하단), y1=820(상단). x는 그대로.
    pdf_user_bbox = [100.0, 800.0, 300.0, 820.0]

    res = {
        "width": page_width_pt,
        "height": page_height_pt,
        "parsing_res_list": [
            {
                "block_bbox": pdf_user_bbox,
                "block_content": "항소이유서",
                "block_label": "title",
            }
        ],
    }

    layout = _extract_layout_from_result(res, page_height_pt=page_height_pt)

    assert layout.get("_coordinate_system") == "normalized"
    assert layout.get("_page_width_px") == page_width_pt
    assert layout.get("_page_height_px") == page_height_pt

    block = layout["parsing_res_list"][0]
    bbox = block["block_bbox"]

    # top-left normalized로 변환되었을 때:
    # x0, x1은 동일, y0(top) = 1 - y1/pdf_height, y1(bottom) = 1 - y0/pdf_height
    expected = [
        100.0 / page_width_pt,
        1.0 - 820.0 / page_height_pt,
        300.0 / page_width_pt,
        1.0 - 800.0 / page_height_pt,
    ]

    for i, (actual, exp) in enumerate(zip(bbox, expected)):
        assert actual == pytest.approx(exp, abs=0.001), f"bbox[{i}] mismatch: {actual} != {exp}"


def test_extract_layout_from_image_coords_still_works():
    """[Flow: Step 1 (300 DPI 이미지 좌표계 bbox 준비)
          -> Step 2 (page_height_px가 page_height_pt보다 훨씬 큰 prunedResult 구성)
          -> Step 3 (top-left normalized 변환이 기존처럼 동작하는지 assert)]"""

    page_height_pt = 842.0
    page_width_px = 2479.0
    page_height_px = 3508.0

    # 이미지 좌표계: y=0이 상단, y=200이 상단 근처의 하단.
    image_bbox = [100.0, 200.0, 300.0, 400.0]

    res = {
        "width": page_width_px,
        "height": page_height_px,
        "parsing_res_list": [
            {
                "block_bbox": image_bbox,
                "block_content": "text",
                "block_label": "text",
            }
        ],
    }

    layout = _extract_layout_from_result(res, page_height_pt=page_height_pt)
    block = layout["parsing_res_list"][0]
    bbox = block["block_bbox"]

    expected = [
        100.0 / page_width_px,
        200.0 / page_height_px,
        300.0 / page_width_px,
        400.0 / page_height_px,
    ]

    for i, (actual, exp) in enumerate(zip(bbox, expected)):
        assert actual == pytest.approx(exp, abs=0.001), f"bbox[{i}] mismatch: {actual} != {exp}"
