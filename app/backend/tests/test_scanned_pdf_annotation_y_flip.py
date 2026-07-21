#!/usr/bin/env python3
"""[Flow: Step 1 (A4 스캔 PDF 시뮬레이션 및 텍스트 레이어 생성) 
      -> Step 2 (상단/중간/하단 위치별 TextLayerSearcher 검색)
      -> Step 3 (input_space='pdf_user' 시 canonical & device 좌표 변환 검증)
      -> Step 4 (input_space='device' 시 Y축 반전 오류 시뮬레이션 및 차이 증명)]

스캔 PDF 주석 생성 시 input_space='pdf_user'가 적용되어 Y좌표가 위아래로 반대로
뒤집히지 않고 올바른 Y 위치에 고정되는지 검증하는 정교한 테스트 세트입니다.
"""
import io
import os
import sys
import fitz
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.core.pdf_text_layer import add_text_layer_from_ocr, TextLayerSearcher
from backend.core.pdf_user_annotator import _convert_annotations_to_canonical
from backend.core.canonical_annotation_coords import canonical_rect_to_device


def _make_scanned_a4_pdf_with_text() -> tuple[bytes, float, float]:
    """A4 크기 (595.0 x 842.0 pt) 스캔 PDF 및 텍스트 레이어를 생성한다."""
    doc = fitz.open()
    doc.new_page(width=595.0, height=842.0)
    stream = io.BytesIO()
    doc.save(stream)
    pdf_bytes = stream.getvalue()
    doc.close()

    page_width = 595.0
    page_height = 842.0

    # 상단 텍스트 "Header Title" (Top Y = 100.0, Bottom Y = 130.0, X = 100.0~400.0, points top-left)
    # 하단 텍스트 "Footer Date"  (Top Y = 750.0, Bottom Y = 780.0, X = 100.0~400.0, points top-left)
    page_ocr_results = {
        1: [
            ("Header Title", (100.0, 100.0, 400.0, 130.0)),
            ("Footer Date", (100.0, 750.0, 400.0, 780.0)),
        ]
    }
    layout_by_page = {
        1: {
            "width": page_width,
            "height": page_height,
        }
    }

    searchable_pdf_bytes = add_text_layer_from_ocr(
        pdf_bytes,
        page_ocr_results,
        dpi=300,
        language="en",
        layout_by_page=layout_by_page,
    )
    return searchable_pdf_bytes, page_width, page_height


class TestScannedPdfAnnotationYFlip:
    """스캔 PDF 주석 좌표계 반전 버그 방지 및 정밀도 검증 테스트"""

    def test_pdf_user_input_space_calculates_correct_top_left_canonical(self):
        """[Flow: Step 1 (TextLayerSearcher로 상단 텍스트 검색)
              -> Step 2 (input_space='pdf_user'로 canonical 변환)
              -> Step 3 (origin.y가 상단 100pt/842pt ~ 0.1188 근처인지 assert)]
        """
        pdf_bytes, page_width, page_height = _make_scanned_a4_pdf_with_text()
        searcher = TextLayerSearcher(pdf_bytes)

        # 상단 텍스트 검색
        rects = searcher.search(1, "Header Title")
        searcher.close()
        assert len(rects) == 1, f"Expected 1 match, got {len(rects)}"

        x0, y0, x1, y1 = rects[0]
        # TextLayerSearcher 반환값은 PDF user-space (원점 좌하단, y↑)
        # 상단 텍스트 (top_y=100, bottom_y=130):
        # expected y0 (bottom) = 842 - 130 = 712.0
        # expected y1 (top)    = 842 - 100 = 742.0
        assert abs(y0 - (page_height - 130.0)) < 5.0
        assert abs(y1 - (page_height - 100.0)) < 5.0

        # AI 백엔드가 만드는 주석 payload (PDF user-space)
        width = x1 - x0
        height = y1 - y0
        raw_annotation = {
            "annotation": {
                "id": "test-ai-header",
                "type": 9,  # HIGHLIGHT
                "pageIndex": 0,
                "rect": {"origin": {"x": x0, "y": y0}, "size": {"width": width, "height": height}},
                "segmentRects": [{"origin": {"x": x0, "y": y0}, "size": {"width": width, "height": height}}],
                "color": "#FFEE4D",
            }
        }

        # [핵심] input_space='pdf_user' 로 변환 수행
        canonical_annotations = _convert_annotations_to_canonical(
            [raw_annotation], pdf_bytes, input_space="pdf_user"
        )
        assert len(canonical_annotations) == 1

        anno = canonical_annotations[0]["annotation"]
        canonical_rect = anno["rect"]
        origin_y = canonical_rect["origin"]["y"]

        # canonical 좌표계는 원점이 좌상단(y↓)이므로 상단 텍스트(top_y=100)의 y는 100 / 842 ~ 0.1188 이어야 함
        expected_canonical_y = 100.0 / page_height
        assert abs(origin_y - expected_canonical_y) < 0.02, (
            f"Canonical Y {origin_y:.4f} differs from expected top Y {expected_canonical_y:.4f}. "
            f"Y-axis may be flipped upside down!"
        )

        # Device space (뷰어 렌더링 좌표계)로 재변환
        device_rect = canonical_rect_to_device(canonical_rect, page_width, page_height)
        device_y = device_rect["origin"]["y"]
        assert abs(device_y - 100.0) < 5.0, (
            f"Device Y {device_y:.2f}pt is far from original top Y 100.0pt"
        )

    def test_device_input_space_misinterpretation_causes_y_flip_error(self):
        """[Flow: 잘못된 input_space='device' 적용 시 Y좌표가 하단 712pt 위치로 오반전됨을 증명]
        """
        pdf_bytes, page_width, page_height = _make_scanned_a4_pdf_with_text()
        searcher = TextLayerSearcher(pdf_bytes)
        rects = searcher.search(1, "Header Title")
        searcher.close()

        x0, y0, x1, y1 = rects[0]
        width = x1 - x0
        height = y1 - y0

        raw_annotation = {
            "annotation": {
                "id": "test-ai-header-wrong",
                "type": 9,
                "pageIndex": 0,
                "rect": {"origin": {"x": x0, "y": y0}, "size": {"width": width, "height": height}},
                "color": "#FFEE4D",
            }
        }

        # [오류 시뮬레이션] input_space='device'로 부를 경우
        wrong_canonical_annotations = _convert_annotations_to_canonical(
            [raw_annotation], pdf_bytes, input_space="device"
        )
        wrong_anno = wrong_canonical_annotations[0]["annotation"]
        wrong_canonical_y = wrong_anno["rect"]["origin"]["y"]

        # y0(712pt)가 Y-flip 없이 712 / 842 ~ 0.8456 (페이지 하단)으로 뒤집힘!
        expected_wrong_y = y0 / page_height
        assert abs(wrong_canonical_y - expected_wrong_y) < 0.02

        wrong_device_rect = canonical_rect_to_device(wrong_anno["rect"], page_width, page_height)
        wrong_device_y = wrong_device_rect["origin"]["y"]

        # 상단(100pt) 텍스트가 바닥(712pt) 위치로 그려지는 오적용 입증
        assert abs(wrong_device_y - 712.0) < 5.0
        assert abs(wrong_device_y - 100.0) > 500.0, "Input space 'device' incorrectly flips Y"
