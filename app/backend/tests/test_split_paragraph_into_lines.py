#!/usr/bin/env python3
"""[Flow: Step 1 (문단 텍스트 + 블록 bbox 입력) -> Step 2 (_split_paragraph_into_lines 호출)
      -> Step 3 (각 줄의 bbox가 블록 bbox의 세로 영역을 분할한 위치인지 검증)]

문단 텍스트가 여러 줄인 경우, _split_paragraph_into_lines는 텍스트를 줄 단위로
분할하고 각 줄에 블록 bbox의 세로 영역을 분할한 bbox를 할당해야 한다.
이렇게 분할된 줄별 (text, bbox) 항목이 add_text_layer_from_ocr에 전달되면,
각 줄이 적절한 fontsize로 올바른 y 위치에 배치된다.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from backend.core.pdf_text_layer import _split_paragraph_into_lines


class TestSplitParagraphIntoLines:
    """_split_paragraph_into_lines가 문단을 줄 단위로 분할하는지 검증한다."""

    def test_short_text_single_line(self):
        """[Flow: 짧은 텍스트 -> _split_paragraph_into_lines -> 1줄 반환 검증]

        짧은 텍스트는 한 줄에 들어가므로 분할 없이 원본 bbox를 반환해야 한다.
        """
        bbox = (50.0, 100.0, 500.0, 130.0)  # 너비 450, 높이 30
        lines = _split_paragraph_into_lines("짧은 텍스트", bbox)
        assert len(lines) == 1
        assert lines[0][0] == "짧은 텍스트"
        # bbox가 원본과 동일해야 함
        assert lines[0][1] == bbox

    def test_long_text_split_into_multiple_lines(self):
        """[Flow: 긴 텍스트 -> _split_paragraph_into_lines -> 여러 줄로 분할 검증]

        bbox 너비에 비해 텍스트가 길면, 텍스트가 여러 줄로 분할되어야 한다.
        각 줄의 bbox는 블록 bbox의 세로 영역을 줄 수만큼 분할한 위치여야 한다.

        [주의] 이 bbox는 normalized(0~1, y=0 상단) 좌표계에서 변환된 것이다.
        _convert_bbox_to_pdf_user가 y를 뒤집으므로, 첫 줄이 y1(큰 값)에 가깝게
        배정되어야 변환 후 device-space 상단에 표시된다.
        이것은 _split_bbox_into_rows와 동일한 역순 배정 패턴이다.
        """
        # 너비 400, 높이 80 (약 3~4줄 분량)
        bbox = (50.0, 100.0, 450.0, 180.0)
        long_text = "변호인 일반접견 예약이 완료되었습니다. 변호인 일반접견 예약 확인(수용기관, 수용번호, 수용자명, 소송사건 대리인 변호사접견 횟수(월) 0/4)"
        lines = _split_paragraph_into_lines(long_text, bbox)

        # 2줄 이상으로 분할되어야 함
        assert len(lines) >= 2, f"긴 텍스트는 2줄 이상으로 분할되어야 함, got {len(lines)}줄"

        # 각 줄의 bbox가 블록 bbox의 세로 영역을 역순으로 분할한 위치인지 확인
        # 첫 줄(i=0)이 y1(180)에 가깝고, 마지막 줄이 y0(100)에 가까워야 함
        block_height = 180.0 - 100.0  # 80
        line_height = block_height / len(lines)
        for i, (text, line_bbox) in enumerate(lines):
            expected_y0 = 180.0 - (i + 1) * line_height
            expected_y1 = 180.0 - i * line_height
            assert abs(line_bbox[1] - expected_y0) < 0.1, (
                f"줄 {i}의 y0가 {expected_y0:.1f}이어야 함 (역순 배정), got {line_bbox[1]:.1f}"
            )
            assert abs(line_bbox[3] - expected_y1) < 0.1, (
                f"줄 {i}의 y1이 {expected_y1:.1f}이어야 함 (역순 배정), got {line_bbox[3]:.1f}"
            )
            # x 좌표는 블록 bbox와 동일해야 함
            assert line_bbox[0] == 50.0
            assert line_bbox[2] == 450.0

    def test_first_line_near_y1_top_after_conversion(self):
        """[Flow: 첫 줄이 y1(큰 값)에 가깝게 배정되는지 검증]

        _split_paragraph_into_lines의 bbox는 normalized(0~1, y=0 상단)에서
        변환된 좌표이다. _convert_bbox_to_pdf_user가 y를 뒤집으므로,
        첫 줄이 y1(큰 값)에 배정되어야 변환 후 device-space 상단에 표시된다.
        """
        bbox = (50.0, 100.0, 450.0, 180.0)
        long_text = "첫째줄텍스트 둘째줄텍스트 셋째줄텍스트 넷째줄텍스트 다섯째줄텍스트"
        lines = _split_paragraph_into_lines(long_text, bbox)

        if len(lines) >= 2:
            first_line_bbox = lines[0][1]
            last_line_bbox = lines[-1][1]
            # 첫 줄의 y1이 블록 y1(180)과 같아야 함
            assert first_line_bbox[3] == 180.0, (
                f"첫 줄의 y1이 블록 y1(180)과 같아야 함, got {first_line_bbox[3]}"
            )
            # 마지막 줄의 y0이 블록 y0(100)과 같아야 함
            assert last_line_bbox[1] == 100.0, (
                f"마지막 줄의 y0이 블록 y0(100)과 같아야 함, got {last_line_bbox[1]}"
            )

    def test_lines_y_monotonic_decreasing(self):
        """[Flow: 줄 인덱스가 증가할수록 y가 감소하는지 검증 (역순 배정)]

        첫 줄이 y1(큰 값)에, 마지막 줄이 y0(작은 값)에 배정되므로,
        줄 인덱스가 증가할수록 y_center가 감소해야 한다.
        """
        bbox = (50.0, 100.0, 450.0, 200.0)
        long_text = "첫째줄 둘째줄 셋째줄 넷째줄 다섯째줄 여섯째줄 일곱째줄 여덟째줄"
        lines = _split_paragraph_into_lines(long_text, bbox)

        if len(lines) >= 2:
            y_centers = [(bbox[1] + bbox[3]) / 2.0 for _, bbox in lines]
            for i in range(1, len(y_centers)):
                assert y_centers[i] < y_centers[i - 1], (
                    f"줄 {i}의 y_center({y_centers[i]:.1f})가 줄 {i-1}({y_centers[i-1]:.1f})보다 "
                    f"작아야 함 (역순 배정으로 단조 감소)"
                )

    def test_all_lines_text_concatenation_matches_original(self):
        """[Flow: 분할된 줄 텍스트를 합치면 원본 텍스트와 같아야 함 검증]"""
        bbox = (50.0, 100.0, 450.0, 180.0)
        original = "변호인 일반접견 예약이 완료되었습니다. 변호인 일반접견 예약 확인(수용기관, 수용번호, 수용자명, 소송사건 대리인 변호사접견 횟수(월) 0/4)"
        lines = _split_paragraph_into_lines(original, bbox)
        # 모든 줄의 텍스트를 공백으로 연결하면 원본과 같아야 함
        reconstructed = " ".join(text for text, _ in lines)
        # 공백 정규화 (연속 공백 제거)
        import re
        normalized_original = re.sub(r'\s+', ' ', original).strip()
        normalized_reconstructed = re.sub(r'\s+', ' ', reconstructed).strip()
        assert normalized_original == normalized_reconstructed, (
            f"분할된 텍스트를 합치면 원본과 같아야 함\n"
            f"원본: {normalized_original!r}\n"
            f"재구성: {normalized_reconstructed!r}"
        )

    def test_newline_in_text_split(self):
        """[Flow: 텍스트에 \\n이 포함된 경우 -> 줄바꿈 문자 기준으로 분할 검증]

        [주의] 첫 줄이 y1(큰 값)에 가깝게 역순 배정되어야 변환 후 상단에 표시됨.
        """
        bbox = (50.0, 100.0, 450.0, 160.0)
        text = "첫째 줄\n둘째 줄\n셋째 줄"
        lines = _split_paragraph_into_lines(text, bbox)
        assert len(lines) == 3
        assert lines[0][0] == "첫째 줄"
        assert lines[1][0] == "둘째 줄"
        assert lines[2][0] == "셋째 줄"
        # 각 줄의 bbox가 세로로 역순 분할되어야 함
        # 첫 줄(i=0): y1=160, y0=160-20=140
        # 둘째 줄(i=1): y1=140, y0=120
        # 셋째 줄(i=2): y1=120, y0=100
        line_height = 60.0 / 3  # 20
        for i, (_, line_bbox) in enumerate(lines):
            expected_y1 = 160.0 - i * line_height
            expected_y0 = 160.0 - (i + 1) * line_height
            assert abs(line_bbox[1] - expected_y0) < 0.1, (
                f"줄 {i}의 y0가 {expected_y0:.1f}이어야 함 (역순), got {line_bbox[1]:.1f}"
            )
            assert abs(line_bbox[3] - expected_y1) < 0.1, (
                f"줄 {i}의 y1이 {expected_y1:.1f}이어야 함 (역순), got {line_bbox[3]:.1f}"
            )

    def test_empty_text_returns_empty(self):
        """[Flow: 빈 텍스트 -> _split_paragraph_into_lines -> 빈 목록 반환 검증]"""
        lines = _split_paragraph_into_lines("", (50.0, 100.0, 450.0, 130.0))
        assert lines == []
