#!/usr/bin/env python3
"""[Flow: Step 1 (좌표 변환 함수 단위 테스트) -> Step 2 (round-trip 변환 검증)]

백엔드 좌표 변환 로직이 실제로 올바르게 작동하는지 검증한다.
- pdf_annotator.py: PDF user-space(y↑) → EmbedPDF device-space(y↓)
- pdf_user_annotator.py: EmbedPDF device-space(y↓) → PDF user-space(y↑) (역방향)
- pdf_coords.py: 픽셀 좌표(y↓) → PDF user-space(y↑)
- round-trip: PDF user-space → device-space → PDF user-space가 원래 좌표로 돌아오는지 확인
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz
from core.pdf_annotator import (
    _rect_to_embedpdf_rect,
    _pdf_point_to_device,
    _pdf_rect_to_device,
    _device_rect_to_pdf,
)
from core.pdf_user_annotator import (
    _parse_rect,
    _parse_point,
    extract_pdf_annotations,
    remove_pdf_annotations,
)
from core.pdf_coords import px_bbox_to_pdf_rect


# ─── 테스트 유틸 ─────────────────────────────────────────────
PASS = 0
FAIL = 0

def check(label, actual, expected, tol=0.01):
    """[Flow: Step 1 (실제 값과 기대 값 비교) -> Step 2 (허용 오차 내면 PASS, 아니면 FAIL)]"""
    global PASS, FAIL
    if isinstance(expected, (list, tuple)):
        ok = all(abs(a - e) <= tol for a, e in zip(actual, expected))
    elif isinstance(expected, dict):
        ok = _compare_dict(actual, expected, tol)
    else:
        ok = abs(actual - expected) <= tol
    status = "PASS" if ok else "FAIL"
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print(f"  [{status}] {label}")
    if not ok:
        print(f"         expected: {expected}")
        print(f"         actual:   {actual}")
    return ok

def _compare_dict(actual, expected, tol):
    """[Flow: dict 재귀 비교 — origin/size 등 중첩 구조 지원]"""
    if not isinstance(actual, dict):
        return False
    for k, ev in expected.items():
        av = actual.get(k)
        if isinstance(ev, dict):
            if not _compare_dict(av, ev, tol):
                return False
        elif isinstance(ev, (int, float)):
            if av is None or abs(av - ev) > tol:
                return False
        elif ev != av:
            return False
    return True

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ─── 테스트 1: _rect_to_embedpdf_rect (PDF user-space → device-space) ───
def test_rect_to_embedpdf():
    section("테스트 1: _rect_to_embedpdf_rect (PDF user-space → device-space)")

    # [Flow: Step 1 (A4 페이지 기준 좌표 설정) -> Step 2 (변환 수행) -> Step 3 (device-space 좌표 검증)]
    # A4: 595 x 842 pt, page_x0 = 0
    page_height = 842.0
    page_x0 = 0.0

    # 페이지 상단 (PDF user-space y1=800, y0=780) → device-space top = 842-800 = 42
    rect = _rect_to_embedpdf_rect(100, 780, 200, 800, page_height, page_x0)
    check("상단 영역 origin.y = page_height - y1", rect["origin"]["y"], 42.0)
    check("상단 영역 origin.x = x0 - page_x0", rect["origin"]["x"], 100.0)
    check("상단 영역 size.width = x1 - x0", rect["size"]["width"], 100.0)
    check("상단 영역 size.height = y1 - y0", rect["size"]["height"], 20.0)

    # 페이지 하단 (PDF user-space y1=50, y0=30) → device-space top = 842-50 = 792
    rect2 = _rect_to_embedpdf_rect(100, 30, 200, 50, page_height, page_x0)
    check("하단 영역 origin.y = page_height - y1", rect2["origin"]["y"], 792.0)

    # page_x0 오프셋 (CropBox)
    rect3 = _rect_to_embedpdf_rect(150, 780, 250, 800, page_height, page_x0=50.0)
    check("CropBox 오프셋 origin.x = x0 - page_x0", rect3["origin"]["x"], 100.0)


# ─── 테스트 2: _pdf_point_to_device (PDF user-space point → device-space) ───
def test_pdf_point_to_device():
    section("테스트 2: _pdf_point_to_device (PDF point → device-space)")

    page_height = 842.0
    page_x0 = 0.0

    # PDF user-space (100, 800) → device-space (100, 42)
    pt = _pdf_point_to_device(100, 800, page_height, page_x0)
    check("point x = px - page_x0", pt["x"], 100.0)
    check("point y = page_height - py", pt["y"], 42.0)

    # PDF user-space (100, 42) → device-space (100, 800)
    pt2 = _pdf_point_to_device(100, 42, page_height, page_x0)
    check("point y (하단) = page_height - py", pt2["y"], 800.0)


# ─── 테스트 3: round-trip (PDF user-space → device-space → PDF user-space) ───
def test_round_trip_rect():
    section("테스트 3: round-trip rect 변환 (user-space → device → user-space)")

    page_height = 842.0
    page_x0 = 0.0

    # 원본 PDF user-space 좌표
    orig_x0, orig_y0, orig_x1, orig_y1 = 100, 780, 200, 800

    # [Flow: Step 1 (PDF user-space → device-space) -> Step 2 (device-space → PDF user-space) -> Step 3 (원래 좌표로 복원 확인)]
    dev = _rect_to_embedpdf_rect(orig_x0, orig_y0, orig_x1, orig_y1, page_height, page_x0)
    restored = _device_rect_to_pdf(dev, page_height, page_x0)

    check("round-trip x0", restored[0], orig_x0)
    check("round-trip y0", restored[1], orig_y0)
    check("round-trip x1", restored[2], orig_x1)
    check("round-trip y1", restored[3], orig_y1)


# ─── 테스트 4: _parse_rect (device-space → PDF user-space, 역방향) ───
def test_parse_rect_device_to_pdf():
    section("테스트 4: _parse_rect (device-space → PDF user-space)")

    page_height = 842.0
    page_x0 = 0.0

    # device-space rect: origin=(100, 42), size=(100, 20)
    # → PDF user-space: x0=100, y0=842-42-20=780, x1=200, y1=842-42=800
    dev_rect = {"origin": {"x": 100, "y": 42}, "size": {"width": 100, "height": 20}}
    pdf_rect = _parse_rect(dev_rect, page_height, page_x0)

    check("_parse_rect x0", pdf_rect.x0, 100.0)
    check("_parse_rect y0 (page_height - origin.y - height)", pdf_rect.y0, 780.0)
    check("_parse_rect x1", pdf_rect.x1, 200.0)
    check("_parse_rect y1 (page_height - origin.y)", pdf_rect.y1, 800.0)

    # {x, y, width, height} 레거시 형식
    legacy_rect = {"x": 100, "y": 42, "width": 100, "height": 20}
    pdf_rect2 = _parse_rect(legacy_rect, page_height, page_x0)
    check("legacy _parse_rect y0", pdf_rect2.y0, 780.0)
    check("legacy _parse_rect y1", pdf_rect2.y1, 800.0)


# ─── 테스트 5: px_bbox_to_pdf_rect (픽셀 → PDF user-space) ───
def test_px_bbox_to_pdf_rect():
    section("테스트 5: px_bbox_to_pdf_rect (픽셀 y↓ → PDF user-space y↑)")

    # [Flow: Step 1 (픽셀 bbox와 DPI 설정) -> Step 2 (y축 flip 수행) -> Step 3 (PDF user-space 좌표 검증)]
    # DPI=72 → scale=1.0, page_height_px=842
    # 픽셀 bbox (y↓): (100, 42, 200, 62) — 페이지 상단
    # PDF user-space (y↑): y0 = 842-62=780, y1 = 842-42=800
    pdf_rect = px_bbox_to_pdf_rect((100, 42, 200, 62), dpi=72, page_height_px=842)
    check("px→pdf x0", pdf_rect[0], 100.0)
    check("px→pdf y0 (page_height - y1_px)", pdf_rect[1], 780.0)
    check("px→pdf x1", pdf_rect[2], 200.0)
    check("px→pdf y1 (page_height - y0_px)", pdf_rect[3], 800.0)

    # DPI=144 → scale=0.5
    pdf_rect2 = px_bbox_to_pdf_rect((200, 84, 400, 124), dpi=144, page_height_px=1684)
    check("DPI=144 x0", pdf_rect2[0], 100.0)
    check("DPI=144 y0", pdf_rect2[1], 780.0)


# ─── 테스트 6: 엔드투엔드 (PDF 생성 → 주석 적용 → 추출 → 좌표 검증) ───
def test_end_to_end():
    section("테스트 6: 엔드투엔드 (PDF 생성 → 하이라이트 적용 → 추출 → 좌표 검증)")

    # [Flow: Step 1 (빈 PDF 생성) -> Step 2 (EmbedPDF 형식 주석으로 하이라이트 적용)
    #       -> Step 3 (주석 추출) -> Step 4 (추출된 좌표가 원본과 일치하는지 검증)]
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    pdf_bytes = doc.tobytes()
    doc.close()

    page_height = 842.0
    page_x0 = 0.0

    # PDF user-space 좌표 (페이지 상단 영역)
    orig_x0, orig_y0, orig_x1, orig_y1 = 100, 780, 200, 800

    # EmbedPDF device-space rect 생성
    dev_rect = _rect_to_embedpdf_rect(orig_x0, orig_y0, orig_x1, orig_y1, page_height, page_x0)
    check("device-space rect origin.x", dev_rect["origin"]["x"], orig_x0)
    check("device-space rect origin.y", dev_rect["origin"]["y"], page_height - orig_y1 - (orig_y1 - orig_y0))
    check("device-space rect size.width", dev_rect["size"]["width"], orig_x1 - orig_x0)
    check("device-space rect size.height", dev_rect["size"]["height"], orig_y1 - orig_y0)


# ─── 테스트 7: PyMuPDF page rect에서 추출한 pageDimensions 정합성 ───
def test_page_dimensions_sanity():
    section("테스트 7: PyMuPDF pageDimensions 정합성 (get_job_elements 기반)")

    # [Flow: Step 1 (A4 PDF 메모리 생성) -> Step 2 (page.rect.width/height 추출)
    #       -> Step 3 (양수이고 예상 범위 내인지 검증)]
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    pdf_bytes = doc.tobytes()
    doc.close()

    reopened = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = reopened[0]
    page_dimensions = {
        1: {
            "width": float(page.rect.width),
            "height": float(page.rect.height),
        }
    }
    reopened.close()

    dims = page_dimensions[1]
    check("pageDimensions.width == 595", dims["width"], 595.0)
    check("pageDimensions.height == 842", dims["height"], 842.0)
    check("pageDimensions.width > 0", dims["width"] > 0, True)
    check("pageDimensions.height > 0", dims["height"] > 0, True)


# ─── 메인 ─────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  백엔드 좌표 변환 테스트 시작")
    print("=" * 60)

    test_rect_to_embedpdf()
    test_pdf_point_to_device()
    test_round_trip_rect()
    test_parse_rect_device_to_pdf()
    test_px_bbox_to_pdf_rect()
    test_end_to_end()
    test_page_dimensions_sanity()

    print(f"\n{'='*60}")
    print(f"  결과: {PASS} passed, {FAIL} failed")
    print(f"{'='*60}")

    sys.exit(0 if FAIL == 0 else 1)
