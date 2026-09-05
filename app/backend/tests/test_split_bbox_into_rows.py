#!/usr/bin/env python3
"""[Flow: Step 1 (표 block_bbox + 행 수 입력) -> Step 2 (_split_bbox_into_rows 호출)
      -> Step 3 (첫 행이 y0(작은 값), 마지막 행이 y1(큰 값)에 배치되는지 검증)]

_split_bbox_into_rows는 표 block_bbox를 세로로 row_count등분한다.
이 bbox는 0~1 top-left normalized(y=0이 상단)이므로 첫 HTML 행이 y0(작은 값)를 받는다.

2026-09-04 이전에는 반대로 첫 행을 y1(큰 값)에 배정했고 이 테스트도 그것을 고정했다.
그때는 paddleocr_service의 _normalize_bbox가 top-left 입력에도 y를 뒤집어(bottom-left 가정)
좌표가 반전된 채 들어왔고, 역순 배정이 그 반전을 국소적으로 상쇄하고 있었다.
근본 원인(_extract_layout_from_result의 flip_y)을 고쳤으므로 보정도 함께 걷어냈다.

소비 경로: _split_bbox_into_rows -> OcrTable.rows[].bbox_px
        -> pdf_annotate_converter._layout_bbox_to_pdf_user -> bbox_pdf (추가 flip 없이 사용).
종단 검증: tests/test_layout_coordinate_origin.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from backend.core.ocr_layout import _split_bbox_into_rows


class TestSplitBboxIntoRows:
    """_split_bbox_into_rows가 표 행을 올바른 순서로 분할하는지 검증한다."""

    def test_first_row_near_y0_top(self):
        """[Flow: 3행 표 bbox -> _split_bbox_into_rows -> 첫 행이 y0에 가까운지 검증]

        첫 HTML 행(i=0)은 표의 시각적 맨 위이며, top-left 좌표계에서 맨 위는 y0(작은 값)이다.
        """
        # block_bbox: y0=100, y1=400 (top-left, y↓ — 100이 위, 400이 아래)
        rows = _split_bbox_into_rows((0.0, 100.0, 500.0, 400.0), 3)
        assert len(rows) == 3

        # 첫 행이 y0(100)에 가장 가까워야 함
        first_row = rows[0]
        assert first_row[1] == 100.0, (
            f"첫 행의 y0이 block y0(100)과 같아야 함, got {first_row[1]}"
        )
        assert first_row[3] == 200.0, (
            f"첫 행의 y1이 200이어야 함 (100 + 300/3), got {first_row[3]}"
        )

    def test_last_row_near_y1_bottom(self):
        """[Flow: 3행 표 bbox -> _split_bbox_into_rows -> 마지막 행이 y1에 가까운지 검증]

        마지막 HTML 행은 표의 시각적 맨 아래이며, top-left 좌표계에서 맨 아래는 y1(큰 값)이다.
        """
        rows = _split_bbox_into_rows((0.0, 100.0, 500.0, 400.0), 3)
        last_row = rows[2]
        assert last_row[3] == 400.0, (
            f"마지막 행의 y1이 block y1(400)과 같아야 함, got {last_row[3]}"
        )
        assert last_row[1] == 300.0, (
            f"마지막 행의 y0이 300이어야 함 (400 - 300/3), got {last_row[1]}"
        )

    def test_rows_monotonic_increasing_y(self):
        """[Flow: 5행 표 bbox -> _split_bbox_into_rows -> 행 y가 단조 증가하는지 검증]

        top-left 좌표계에서는 아래로 갈수록 y가 커지므로, 행 인덱스가 증가할수록
        y도 증가해야 한다 (첫 행이 y0에 가깝고 마지막이 y1에 가까움).
        """
        rows = _split_bbox_into_rows((0.0, 0.0, 500.0, 500.0), 5)
        assert len(rows) == 5

        y_centers = [(r[1] + r[3]) / 2 for r in rows]
        for i in range(1, len(y_centers)):
            assert y_centers[i] > y_centers[i - 1], (
                f"행 {i}의 y_center({y_centers[i]})가 행 {i-1}({y_centers[i-1]})보다 "
                f"커야 함 (단조 증가)"
            )

    def test_x_coordinates_preserved(self):
        """[Flow: 표 bbox -> _split_bbox_into_rows -> x 좌표가 보존되는지 검증]

        행 분할은 y축만 수행하므로 모든 행의 x0, x1이 block_bbox와 동일해야 한다.
        """
        rows = _split_bbox_into_rows((50.0, 100.0, 450.0, 400.0), 4)
        for i, row in enumerate(rows):
            assert row[0] == 50.0, f"행 {i}의 x0가 50이어야 함, got {row[0]}"
            assert row[2] == 450.0, f"행 {i}의 x1이 450이어야 함, got {row[2]}"

    def test_zero_rows_returns_empty(self):
        """[Flow: 행 수 0 -> _split_bbox_into_rows -> 빈 목록 반환 검증]"""
        rows = _split_bbox_into_rows((0.0, 0.0, 100.0, 100.0), 0)
        assert rows == []

    def test_single_row_returns_full_bbox(self):
        """[Flow: 1행 표 -> _split_bbox_into_rows -> 전체 bbox 반환 검증]"""
        rows = _split_bbox_into_rows((0.0, 100.0, 500.0, 400.0), 1)
        assert len(rows) == 1
        assert rows[0] == (0.0, 100.0, 500.0, 400.0)
