#!/usr/bin/env python3
"""[Flow: Step 1 (알려진 위치의 bbox 생성) -> Step 2 (정규화 + PDF user-space 변환)
      -> Step 3 (화면상 위치가 입력 위치와 일치하는지 검증)]

스캔 PDF 하이라이트 좌표 반전 회귀 테스트.

PP-StructureV3(local_v5)는 bbox를 **이미지 픽셀 좌표(top-left origin)** 로 반환하는데,
AI Studio가 PDF를 직접 받았을 때의 규약(bottom-left)에 맞춰 만들어진 _normalize_bbox를
그대로 통과시키면 y 뒤집기가 두 번(정규화 1회 + 소비자 1회) 일어나 상쇄된다.
그 결과 페이지 상단의 텍스트가 하단에 하이라이트된다.

기존 test_ocr_v5_adapter.py 는 y 를 `0.0 <= v <= 1.0` 범위로만 검증해 이 반전을
잡지 못했다. 여기서는 y 값을 **정확히** 단언한다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from backend.paddleocr_service.main import (
    _extract_layout_from_result,
    _normalize_bbox,
    _normalize_points,
)
from backend.core.pdf_annotate_converter import _layout_bbox_to_pdf_user

W_PX, H_PX = 200.0, 100.0


class TestNormalizeBboxOrigin:
    def test_top_left_input_preserves_y(self):
        """top-left 입력(flip_y=False)은 y를 뒤집지 않고 그대로 정규화한다."""
        # 상단에서 20%~60% 위치
        out = _normalize_bbox([10, 20, 110, 60], W_PX, H_PX, flip_y=False)
        assert out[0] == pytest.approx(0.05)
        assert out[1] == pytest.approx(0.20)
        assert out[2] == pytest.approx(0.55)
        assert out[3] == pytest.approx(0.60)

    def test_bottom_left_input_flips_y(self):
        """bottom-left 입력(flip_y=True, AI Studio PDF 규약)은 y를 뒤집는다."""
        out = _normalize_bbox([10, 20, 110, 60], W_PX, H_PX, flip_y=True)
        assert out[1] == pytest.approx(1.0 - 60 / H_PX)
        assert out[3] == pytest.approx(1.0 - 20 / H_PX)

    def test_default_stays_flip_for_aistudio(self):
        """기본값은 AI Studio 경로 호환을 위해 flip_y=True 를 유지해야 한다."""
        assert _normalize_bbox([10, 20, 110, 60], W_PX, H_PX) == _normalize_bbox(
            [10, 20, 110, 60], W_PX, H_PX, flip_y=True
        )

    def test_points_follow_same_convention(self):
        out = _normalize_points([[10, 20]], W_PX, H_PX, flip_y=False)
        assert out[0][1] == pytest.approx(0.20)
        flipped = _normalize_points([[10, 20]], W_PX, H_PX, flip_y=True)
        assert flipped[0][1] == pytest.approx(0.80)


def _structure_v3_raw(y0: float, y1: float) -> dict:
    """PP-StructureV3 res.json 형태 (bbox 는 이미지 픽셀 좌표, top-left)."""
    return {
        "width": W_PX,
        "height": H_PX,
        "parsing_res_list": [
            {"block_label": "text", "block_content": "제목", "block_bbox": [10, y0, 110, y1]}
        ],
        "overall_ocr_res": {"rec_texts": ["제목"], "rec_boxes": [[10, y0, 110, y1]]},
    }


class TestEndToEndHighlightPosition:
    """정규화 → PDF user-space 전체 체인에서 화면상 위치가 보존되는지 검증한다."""

    @pytest.mark.parametrize(
        "y0_px,y1_px,label",
        [(10, 20, "페이지 최상단"), (40, 60, "페이지 중앙"), (80, 95, "페이지 최하단")],
    )
    def test_top_left_source_lands_at_same_screen_position(self, y0_px, y1_px, label):
        import fitz

        layout = _extract_layout_from_result(_structure_v3_raw(y0_px, y1_px), flip_y=False)
        norm = layout["parsing_res_list"][0]["block_bbox"]

        page_rect = fitz.Rect(0, 0, 400, 800)
        pdf_bbox = _layout_bbox_to_pdf_user(layout, tuple(norm), page_rect)

        # PDF user-space 는 y↑(하단 원점). 화면상 위치(상단 기준)로 되돌린다.
        screen_top = (page_rect.height - pdf_bbox[3]) / page_rect.height
        screen_bottom = (page_rect.height - pdf_bbox[1]) / page_rect.height

        assert screen_top == pytest.approx(y0_px / H_PX, abs=1e-6), (
            f"{label}: 상단 위치가 어긋났다 (기대 {y0_px / H_PX:.2f}, 실제 {screen_top:.2f})"
        )
        assert screen_bottom == pytest.approx(y1_px / H_PX, abs=1e-6), label

    def test_flip_y_true_on_top_left_source_mirrors_vertically(self):
        """회귀 재현: top-left 입력에 flip_y=True 를 쓰면 상하 반전된다."""
        import fitz

        layout = _extract_layout_from_result(_structure_v3_raw(10, 20), flip_y=True)
        norm = layout["parsing_res_list"][0]["block_bbox"]
        page_rect = fitz.Rect(0, 0, 400, 800)
        pdf_bbox = _layout_bbox_to_pdf_user(layout, tuple(norm), page_rect)
        screen_top = (page_rect.height - pdf_bbox[3]) / page_rect.height

        # 상단 10% 에 있어야 할 것이 하단 80% 로 간다.
        assert screen_top == pytest.approx(0.80, abs=1e-6)


def test_v5_predict_passes_flip_y_false(monkeypatch):
    """local_v5 경로는 반드시 flip_y=False 로 추출기를 구성해야 한다."""
    from backend.paddleocr_service import main as svc

    captured: dict = {}

    def _fake_predict_pages(image_paths, params=None, layout_extractor=None, **kw):
        raw = _structure_v3_raw(10, 20)
        captured["layout"] = layout_extractor(raw) if layout_extractor else None
        return [{"markdown": "", "layout": captured["layout"], "page_angle": 0}]

    monkeypatch.setattr(svc.ocr_v5, "predict_pages", _fake_predict_pages)
    svc._v5_predict([], None, capture_layout=True)

    bbox = captured["layout"]["parsing_res_list"][0]["block_bbox"]
    assert bbox[1] == pytest.approx(0.10), (
        f"local_v5 가 y 를 뒤집었다 (기대 0.10, 실제 {bbox[1]:.2f}) — flip_y=False 여야 한다"
    )
    assert bbox[3] == pytest.approx(0.20)


class TestRowOrderTopDown:
    """표 행 / 문단 줄 분할이 위에서 아래 순서인지 검증한다.

    top-left normalized 에서 첫 행은 y0(작은 값)를 받아야 한다. 2026-09-04 이전에는
    반대로 y1 에 배정했는데, 그때는 _normalize_bbox 가 좌표를 반전시켜 넣어줬기 때문에
    그 역순 배정이 반전을 상쇄하고 있었다. 근본 원인을 고친 뒤 이 보정을 남겨두면
    표 행 순서가 거꾸로 뒤집힌다.
    """

    BLOCK = (0.10, 0.20, 0.90, 0.60)  # top-left normalized, 상단 20%~60%

    def _screen_tops(self, bboxes):
        import fitz

        rect = fitz.Rect(0, 0, 500, 1000)
        tops = []
        for b in bboxes:
            pdf = _layout_bbox_to_pdf_user({"_coordinate_system": "normalized"}, tuple(b), rect)
            tops.append((rect.height - pdf[3]) / rect.height)
        return tops

    def test_ocr_layout_rows_are_top_down(self):
        from backend.core.ocr_layout import _split_bbox_into_rows

        tops = self._screen_tops(_split_bbox_into_rows(self.BLOCK, 4))
        assert tops == sorted(tops), f"첫 행이 맨 위가 아니다: {tops}"
        assert tops[0] == pytest.approx(0.20, abs=1e-6)
        assert tops[-1] == pytest.approx(0.50, abs=1e-6)

    # NOTE: pdf_text_layer(searchable PDF 텍스트 레이어)의 표 행/문단 줄 분할은
    # 여기서 다루지 않는다. 그 파이프라인은 normalized_top_left_to_pdf_user 결과를
    # PyMuPDF page.insert_text() 의 device-space 좌표로 그대로 쓰기 때문에 뒤집기
    # 횟수가 하이라이트 경로와 다르며, 자체 종단 테스트
    # (tests/test_extract_table_row_items_order.py)가 그 동작을 고정하고 있다.
