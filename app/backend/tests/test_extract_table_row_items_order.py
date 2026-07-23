#!/usr/bin/env python3
"""[Flow: Step 1 (normalized top-left 표 bbox + HTML 행 준비)
      -> Step 2 (_extract_table_row_items로 행별 bbox 분할)
      -> Step 3 (각 행 bbox를 normalized_top_left_to_pdf_user로 device-space 변환)
      -> Step 4 (HTML 순서상 첫 행이 표의 시각적 "위쪽"에 배치되는지 검증)]

버그 재현: 스캔 PDF의 표에서 아래쪽 행에 달려야 할 주석이 위쪽 행에 달리고,
그 반대도 마찬가지로 발생하는 문제. 실제 원인은 좌표계(device vs pdf_user)가 아니라
_extract_table_row_items의 행 배정 방향이 반대라서 발생한다.

pdf_text_layer._insert_invisible_text -> page.insert_text()는 device-space(y=0 상단)를
직접 사용하고, _convert_bbox_to_pdf_user(normalized_top_left_to_pdf_user)는
"top-left normalized" 입력을 "PDF user-space"로 뒤집는 변환을 적용한다. 단일 블록(제목 등)은
이 두 번의 뒤집힘이 상쇄되어 절대 위치가 우연히 맞게 나오지만, 표는 행 단위로 쪼개는
_extract_table_row_items가 원본 y0(작은 값)에 HTML 첫 행을 배정하기 때문에,
변환 이후 첫 행이 표의 "아래쪽 끝"에 배치되는 반전이 발생한다.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import fitz

from backend.core.pdf_text_layer import _extract_table_row_items
from backend.core.pdf_coordinate_transform import normalized_top_left_to_pdf_user


class TestExtractTableRowItemsOrder:
    """_extract_table_row_items가 HTML 행 순서를 시각적으로 올바른 방향에 배치하는지 검증한다."""

    def test_first_html_row_maps_to_visual_top_of_table_in_device_space(self):
        """[Flow: 표 bbox(normalized top-left) + 2행 HTML -> 행 분할
              -> 각 행을 normalized_top_left_to_pdf_user로 변환(파이프라인이 실제로 device-space로 사용)
              -> 첫 HTML 행의 y가 표 전체 범위의 "위쪽"(작은 y)에 위치하는지 검증]

        실제 job 데이터 기반: table_bbox=(0.035, 0.301, 0.962, 0.803, normalized top-left)
        page A4 (595.44 x 842.04). 표 전체는 파이프라인을 거치면 device-space 상에서
        y=165.9(위쪽 끝) ~ 588.6(아래쪽 끝)에 위치해야 한다.
        HTML 첫 행("수용기관")은 표의 "위쪽"에 있어야 하므로 device y가 165.9에 가까워야 한다.
        """
        page_rect = fitz.Rect(0, 0, 595.44, 842.04)
        table_bbox = (0.035, 0.301, 0.962, 0.803)
        html = (
            "<table>"
            "<tr><td>수용기관</td><td>수원구치소</td></tr>"
            "<tr><td>수용자명</td><td>응우옌안뚜안</td></tr>"
            "</table>"
        )

        row_items = _extract_table_row_items(html, table_bbox)
        assert len(row_items) == 2

        first_row_text, first_row_bbox = row_items[0]
        last_row_text, last_row_bbox = row_items[-1]
        assert "수용기관" in first_row_text
        assert "수용자명" in last_row_text

        # 파이프라인이 실제로 사용하는 변환(정상 블록은 이 변환의 이중 상쇄로 절대 위치가 맞음)
        first_row_device = normalized_top_left_to_pdf_user(first_row_bbox, page_rect)
        last_row_device = normalized_top_left_to_pdf_user(last_row_bbox, page_rect)

        # 표 전체의 device-space 범위 계산 (참고용 경계값)
        whole_device = normalized_top_left_to_pdf_user(table_bbox, page_rect)

        # 첫 HTML 행(수용기관)은 표의 "위쪽 끝"(작은 device y)에 있어야 한다.
        assert first_row_device.y0 < last_row_device.y0, (
            f"첫 행(수용기관) device y0={first_row_device.y0:.1f}가 "
            f"마지막 행(수용자명) device y0={last_row_device.y0:.1f}보다 커서는 안 된다. "
            "행 순서가 반전되어 표 내부에서 위아래 주석이 뒤바뀌는 버그를 나타낸다."
        )
        # 첫 행은 표 전체의 위쪽 경계(y0)에 가까워야 한다.
        assert abs(first_row_device.y0 - whole_device.y0) < 5.0, (
            f"첫 행이 표 전체의 위쪽 경계({whole_device.y0:.1f})에 가까워야 하는데 "
            f"{first_row_device.y0:.1f}에 위치함"
        )
        # 마지막 행은 표 전체의 아래쪽 경계(y1)에 가까워야 한다.
        assert abs(last_row_device.y1 - whole_device.y1) < 5.0, (
            f"마지막 행이 표 전체의 아래쪽 경계({whole_device.y1:.1f})에 가까워야 하는데 "
            f"{last_row_device.y1:.1f}에 위치함"
        )

    def test_ten_rows_preserve_monotonic_visual_order(self):
        """[Flow: 10행 표 -> 행 분할 -> device-space 변환 -> y가 HTML 순서대로 단조 증가하는지 검증]

        실제 job(변호인 접견예약 확인증)과 동일한 10행 표 구조로 회귀를 방지한다.
        """
        page_rect = fitz.Rect(0, 0, 595.44, 842.04)
        table_bbox = (0.035, 0.301, 0.962, 0.803)
        labels = [
            "수용기관", "수용자명", "사건구분", "사건번호", "변호인 성명",
            "휴대폰 번호", "주소", "변호사 등록번호", "소속법률사무소", "예약일시",
        ]
        html = "<table>" + "".join(f"<tr><td>{label}</td><td>값</td></tr>" for label in labels) + "</table>"

        row_items = _extract_table_row_items(html, table_bbox)
        assert len(row_items) == 10

        device_y0s = [
            normalized_top_left_to_pdf_user(bbox, page_rect).y0 for _text, bbox in row_items
        ]
        # HTML 순서(수용기관 -> 예약일시)대로 device y0가 단조 증가해야 한다
        # (수용기관이 가장 위=작은 y, 예약일시가 가장 아래=큰 y).
        for i in range(len(device_y0s) - 1):
            assert device_y0s[i] < device_y0s[i + 1], (
                f"행 {i}({labels[i]}) device_y0={device_y0s[i]:.1f}가 "
                f"행 {i+1}({labels[i+1]}) device_y0={device_y0s[i+1]:.1f}보다 작아야 한다"
            )
