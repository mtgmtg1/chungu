#!/usr/bin/env python3
# [Flow: Step 1 (PaddleOCR bbox normalized 좌표 반환 검증)
#       -> Step 2 (normalized 좌표 -> PDF user-space 변환 검증)
#       -> Step 3 (searchable PDF 경로 bbox 좌표계 일관성 검증)
#       -> Step 4 (원인 후보 출력)]
# PaddleOCR에서 받아오는 bbox를 원문 PDF에 위치시킬 때 위치가 벗어나는 이유를
# 백엔드에서 검증하기 위한 디버깅 스크립트.
import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import fitz
from backend.paddleocr_service.main import _extract_layout_from_result
from backend.core.pdf_annotate_converter import (
    _collect_page_elements_from_searchable_pdf,
    _normalized_bbox_to_pdf_user,
    build_agent_elements_from_ocr_layout,
)

PASS = 0
FAIL = 0


def check(label, actual, expected, tol=0.001):
    """[Flow: Step 1 (실제 값과 기대 값 비교) -> Step 2 (허용 오차 이내면 PASS, 아니면 FAIL)]"""
    global PASS, FAIL
    if isinstance(expected, bool):
        ok = bool(actual) == expected
    elif isinstance(expected, (list, tuple)):
        ok = all(abs(a - e) <= tol for a, e in zip(actual, expected))
    else:
        ok = abs(actual - expected) <= tol
    status = "PASS" if ok else "FAIL"
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print(f"  [{status}] {label}")
    if not ok:
        print(f"       expected: {expected}")
        print(f"       actual:   {actual}")
    return ok


def make_a4_pdf(path):
    """[Flow: Step 1 (A4 PDF 생성) -> Step 2 (페이지 상단에 테스트 텍스트 삽입)]"""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    # insert_textbox 대신 insert_text를 사용해야 PyMuPDF가 text layer를 생성한다
    page.insert_text((100, 790), "Test text", fontsize=12)
    doc.save(str(path))
    doc.close()


def test_extract_layout_normalized():
    """[Flow: Step 1 (이미지 좌표계 mock res 생성) -> Step 2 (_extract_layout_from_result 호출)
          -> Step 3 (bbox가 0~1 normalized 좌표인지 검증)]"""
    print("\n=== _extract_layout_from_result normalized 좌표 반환 테스트 ===")
    page_width_px = 2479.0
    page_height_px = 3508.0

    res_image = {
        "height": page_height_px,
        "width": page_width_px,
        "parsing_res_list": [
            {"block_bbox": [100, 200, 300, 400], "block_content": "text", "block_label": "text"}
        ],
        "overall_ocr_res": {
            "rec_boxes": [[100, 200, 300, 400]],
            "rec_texts": ["text"]
        }
    }
    layout = _extract_layout_from_result(res_image)
    check("_coordinate_system == 'normalized'", layout.get("_coordinate_system") == "normalized", True, tol=0)
    block = layout["parsing_res_list"][0]
    bbox = block["block_bbox"]
    expected = [100 / 2479, 200 / 3508, 300 / 2479, 400 / 3508]
    check("block_bbox normalized x0", bbox[0], expected[0])
    check("block_bbox normalized y0", bbox[1], expected[1])
    check("block_bbox normalized x1", bbox[2], expected[2])
    check("block_bbox normalized y1", bbox[3], expected[3])


def test_normalized_to_pdf_user():
    """[Flow: Step 1 (normalized bbox 준비) -> Step 2 (_normalized_bbox_to_pdf_user 변환)
          -> Step 3 (PDF user-space 좌표 검증)]"""
    print("\n=== _normalized_bbox_to_pdf_user 변환 테스트 ===")
    page_width_pt = 595.0
    page_height_pt = 842.0
    # test_extract_layout_normalized의 normalized bbox를 그대로 사용
    bbox_norm = [100 / 2479, 200 / 3508, 300 / 2479, 400 / 3508]
    # 300 DPI A4 기준 PDF user-space 예상값: [24, 745.92, 72, 793.92]
    rect_pdf = _normalized_bbox_to_pdf_user(bbox_norm, page_width_pt, page_height_pt)
    check("PDF user-space x0", rect_pdf[0], 24.0, tol=0.1)
    check("PDF user-space y0", rect_pdf[1], 745.92, tol=0.1)
    check("PDF user-space x1", rect_pdf[2], 72.0, tol=0.1)
    check("PDF user-space y1", rect_pdf[3], 793.92, tol=0.1)


def test_searchable_pdf_path():
    """[Flow: Step 1 (검색 가능한 PDF 생성) -> Step 2 (_collect_page_elements_from_searchable_pdf 호출)
          -> Step 3 (bbox_px가 PDF user-space인지 확인)]"""
    print("\n=== _collect_page_elements_from_searchable_pdf 좌표계 테스트 ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "test.pdf"
        make_a4_pdf(pdf_path)
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        elements, corrected_images = _collect_page_elements_from_searchable_pdf(
            pdf_bytes, Path(tmpdir), dpi=300
        )
        if not elements:
            print("  [FAIL] 텍스트 요소를 찾지 못함")
            return
        el = elements[0]
        print(f"  검출된 요소 bbox_px: {el.bbox_px}")
        print(f"  검출된 요소 text: {el.text[:50]}")
        # bbox_px는 PDF user-space에 근접해야 함 (insert_text로 (100, 790)에 배치)
        check("searchable PDF bbox가 PDF user-space에 근접", el.bbox_px, (100.0, 777.0, 146.0, 794.0), tol=5.0)
        print("  [INFO] searchable PDF 경로에서 bbox_px는 이제 PDF user-space 그대로입니다.")


def test_build_agent_elements_coordinate_system():
    """[Flow: Step 1 (A4 PDF bytes 생성) -> Step 2 (raw 픽셀 layout과 normalized layout 준비)
          -> Step 3 (build_agent_elements_from_ocr_layout 호출)
          -> Step 4 (두 좌표계가 동일한 PDF user-space bbox를 반환하는지 검증)]"""
    print("\n=== build_agent_elements_from_ocr_layout 좌표계 감지 테스트 ===")
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    pdf_bytes = doc.tobytes()
    doc.close()

    # PaddleOCR이 반환한 픽셀 좌표 (y=0이 상단, y=3508이 하단)
    pixel_bbox = [34.0, 29.5, 561.0, 53.1]
    page_width_px = 2479.0
    page_height_px = 3508.0

    raw_pixel_layout = {
        1: {
            "width": page_width_px,
            "height": page_height_px,
            "parsing_res_list": [
                {"block_bbox": pixel_bbox, "block_content": "작업일보", "block_label": "title"}
            ],
        }
    }

    normalized_bbox = [v / page_width_px if i % 2 == 0 else v / page_height_px for i, v in enumerate(pixel_bbox)]
    normalized_layout = {
        1: {
            "width": page_width_px,
            "height": page_height_px,
            "_coordinate_system": "normalized",
            "_page_width_px": page_width_px,
            "_page_height_px": page_height_px,
            "parsing_res_list": [
                {"block_bbox": normalized_bbox, "block_content": "작업일보", "block_label": "title"}
            ],
        }
    }

    pixel_results = build_agent_elements_from_ocr_layout(raw_pixel_layout, pdf_bytes)
    norm_results = build_agent_elements_from_ocr_layout(normalized_layout, pdf_bytes)

    if not pixel_results or not norm_results:
        print("  [FAIL] OCR layout에서 요소를 추출하지 못함")
        global FAIL
        FAIL += 1
        return

    pixel_el = pixel_results[0]
    norm_el = norm_results[0]
    print(f"  raw pixel -> bbox_pdf: {pixel_el['bbox_pdf']}")
    print(f"  normalized -> bbox_pdf: {norm_el['bbox_pdf']}")

    expected = (8.16, 829.25, 134.65, 834.92)
    check("pixel layout bbox가 PDF user-space로 정확히 변환", pixel_el["bbox_pdf"], expected, tol=0.1)
    check("normalized layout bbox가 PDF user-space로 정확히 변환", norm_el["bbox_pdf"], expected, tol=0.1)
    check("두 좌표계 변환 결과가 동일", pixel_el["bbox_pdf"], norm_el["bbox_pdf"], tol=0.1)


def main():
    """[Flow: Step 1 (각 테스트 실행) -> Step 2 (PASS/FAIL 집계)]"""
    test_extract_layout_normalized()
    test_normalized_to_pdf_user()
    test_searchable_pdf_path()
    test_build_agent_elements_coordinate_system()
    print(f"\n=== 결과: {PASS} passed, {FAIL} failed ===")


if __name__ == "__main__":
    main()
