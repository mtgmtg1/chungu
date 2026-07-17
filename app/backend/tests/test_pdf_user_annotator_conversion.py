#!/usr/bin/env python3
"""[Flow: Step 1 (device-space/PDF user-space annotation 샘플 생성)
      -> Step 2 (_convert_annotation_to_pdf_user / _convert_annotations_to_pdf_user 호출)
      -> Step 3 (round-trip 좌표 복원 검증)]

pdf_user_annotator의 device-space ↔ PDF user-space 변환이 실제로 올바르게
동작하는지 검증한다. get_job_annotations API가 AI 백엔드에 device 좌표를 반환하고,
AI 백엔드 save_annotations이 다시 PDF user-space로 저장하는 플로우에서
좌표계 오류가 없음을 보장하기 위한 테스트다.
"""
import sys
import os
import io

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz
import pytest

from core.pdf_user_annotator import (
    _convert_annotation_to_pdf_user,
    _convert_annotations_to_pdf_user,
    _convert_annotation_to_device_space,
    _convert_annotations_to_device_space,
    _extract_annotation,
)


def _make_a4_pdf_bytes() -> bytes:
    """[Flow: PyMuPDF 문서 생성 -> A4 페이지 -> 바이트 반환]"""
    doc = fitz.open()
    doc.new_page(width=595.0, height=842.0)
    stream = io.BytesIO()
    doc.save(stream)
    doc.close()
    return stream.getvalue()


def _device_highlight_rect() -> dict:
    """[Flow: A4 페이지 상단 영역 device-space rect 생성 -> 반환]

    PDF user-space (100, 780, 200, 800) -> device-space origin=(100, 42), size=(100, 20)
    """
    return {
        "origin": {"x": 100.0, "y": 42.0},
        "size": {"width": 100.0, "height": 20.0},
    }


class TestAnnotationConversion:
    """pdf_user_annotator 좌표 변환 단위 테스트."""

    def test_convert_annotation_to_pdf_user_with_annotation_transfer_item(self):
        # [Flow: AnnotationTransferItem 형태의 device-space 주석 -> PDF user-space로 변환]
        dev_rect = _device_highlight_rect()
        raw = {
            "annotation": {
                "id": "backend-1-1-0-highlight",
                "type": 9,
                "pageIndex": 0,
                "rect": dev_rect,
                "segmentRects": [dev_rect],
                "color": "#FFEB3B",
                "opacity": 0.5,
                "contents": "AI 하이라이트",
            }
        }

        result = _convert_annotation_to_pdf_user(raw, page_height=842.0, page_x0=0.0, page_y0=0.0)

        # 원본 dict가 그대로 반환되고 내부 annotation dict가 수정되어야 함
        assert result is raw
        a = result["annotation"]
        pdf_rect = a["rect"]
        assert pdf_rect["origin"]["x"] == pytest.approx(100.0, abs=0.01)
        assert pdf_rect["origin"]["y"] == pytest.approx(780.0, abs=0.01)
        assert pdf_rect["size"]["width"] == pytest.approx(100.0, abs=0.01)
        assert pdf_rect["size"]["height"] == pytest.approx(20.0, abs=0.01)

        seg = a["segmentRects"][0]
        assert seg["origin"]["y"] == pytest.approx(780.0, abs=0.01)

    def test_convert_annotation_to_pdf_user_flat_dict(self):
        # [Flow: 평면 dict 형태의 device-space 주석 -> PDF user-space로 변환]
        dev_rect = _device_highlight_rect()
        raw = {
            "id": "flat-highlight",
            "type": 9,
            "pageIndex": 0,
            "rect": dev_rect,
            "contents": "flat",
        }

        result = _convert_annotation_to_pdf_user(raw, page_height=842.0, page_x0=0.0, page_y0=0.0)

        assert result is raw
        assert raw["rect"]["origin"]["y"] == pytest.approx(780.0, abs=0.01)

    def test_device_to_pdf_user_round_trip(self):
        # [Flow: PDF user-space -> device-space -> PDF user-space round-trip 검증]
        page_height = 842.0
        page_x0 = 0.0
        page_y0 = 0.0

        pdf_user_rect = {
            "origin": {"x": 120.0, "y": 760.0},
            "size": {"width": 80.0, "height": 25.0},
        }
        pdf_user_annot = {
            "annotation": {
                "id": "round-trip",
                "type": 9,
                "pageIndex": 0,
                "rect": pdf_user_rect,
                "contents": "round",
            }
        }

        # PDF user-space -> device-space
        device_annot = _convert_annotation_to_device_space(
            pdf_user_annot["annotation"], page_height=page_height, page_x0=page_x0, page_y0=page_y0
        )

        # device-space -> PDF user-space
        restored = _convert_annotation_to_pdf_user(
            {"annotation": device_annot}, page_height=page_height, page_x0=page_x0, page_y0=page_y0
        )

        restored_rect = restored["annotation"]["rect"]
        assert restored_rect["origin"]["x"] == pytest.approx(120.0, abs=0.01)
        assert restored_rect["origin"]["y"] == pytest.approx(760.0, abs=0.01)
        assert restored_rect["size"]["width"] == pytest.approx(80.0, abs=0.01)
        assert restored_rect["size"]["height"] == pytest.approx(25.0, abs=0.01)

    def test_convert_annotations_to_pdf_user_with_pdf_bytes(self):
        # [Flow: 실제 PDF 바이트에서 페이지 크기 추출 -> 다중 주석 일괄 변환]
        pdf_bytes = _make_a4_pdf_bytes()
        annotations = [
            {
                "annotation": {
                    "id": "a1",
                    "type": 9,
                    "pageIndex": 0,
                    "rect": _device_highlight_rect(),
                    "contents": "first",
                }
            },
            {
                "annotation": {
                    "id": "a2",
                    "type": 9,
                    "pageIndex": 0,
                    "rect": {"origin": {"x": 50.0, "y": 100.0}, "size": {"width": 30.0, "height": 15.0}},
                    "contents": "second",
                }
            },
        ]

        result = _convert_annotations_to_pdf_user(annotations, pdf_bytes)

        assert len(result) == 2
        first = result[0]["annotation"]["rect"]
        assert first["origin"]["y"] == pytest.approx(780.0, abs=0.01)

        # second: origin.y=100, height=15 -> PDF user-space y = 842 - 100 - 15 = 727
        second = result[1]["annotation"]["rect"]
        assert second["origin"]["y"] == pytest.approx(727.0, abs=0.01)

    def test_callout_line_conversion(self):
        # [Flow: device-space calloutLine -> PDF user-space로 변환]
        raw = {
            "annotation": {
                "id": "callout-1",
                "type": 3,
                "intent": "FreeTextCallout",
                "pageIndex": 0,
                "rect": _device_highlight_rect(),
                "calloutLine": [
                    {"x": 150.0, "y": 52.0},
                    {"x": 150.0, "y": 30.0},
                    {"x": 200.0, "y": 30.0},
                ],
                "contents": "callout test",
            }
        }

        result = _convert_annotation_to_pdf_user(raw, page_height=842.0, page_x0=0.0, page_y0=0.0)

        line = result["annotation"]["calloutLine"]
        assert len(line) == 3
        # device (150, 52) -> PDF user-space y = 842 - 52 = 790
        assert line[0]["y"] == pytest.approx(790.0, abs=0.01)
        assert line[0]["x"] == pytest.approx(150.0, abs=0.01)

    def test_convert_annotations_to_device_space_list(self):
        # [Flow: list wrapper가 반환값을 무시하지 않고 실제로 변환하는지 검증]
        pdf_bytes = _make_a4_pdf_bytes()
        pdf_user_rect = {
            "origin": {"x": 120.0, "y": 760.0},
            "size": {"width": 80.0, "height": 25.0},
        }
        annotations = [
            {
                "annotation": {
                    "id": "list-nested",
                    "type": 9,
                    "pageIndex": 0,
                    "rect": pdf_user_rect,
                    "contents": "nested",
                }
            },
            {
                "id": "list-flat",
                "type": 9,
                "pageIndex": 0,
                "rect": {"origin": {"x": 50.0, "y": 100.0}, "size": {"width": 30.0, "height": 15.0}},
                "contents": "flat",
            },
        ]

        result = _convert_annotations_to_device_space(annotations, pdf_bytes)

        # nested: origin.y=760, height=25 -> device y = 842 - 760 - 25 = 57
        assert len(result) == 2
        nested = result[0]["annotation"]["rect"]
        assert nested["origin"]["y"] == pytest.approx(57.0, abs=0.01)
        assert nested["origin"]["x"] == pytest.approx(120.0, abs=0.01)
        assert nested["size"]["height"] == pytest.approx(25.0, abs=0.01)

        # flat: origin.y=100, height=15 -> device y = 842 - 100 - 15 = 727
        flat = result[1]["rect"]
        assert flat["origin"]["y"] == pytest.approx(727.0, abs=0.01)

    def test_callout_line_device_to_pdf_user_round_trip(self):
        # [Flow: device-space calloutLine -> PDF user-space -> device-space round-trip 검증]
        raw = {
            "annotation": {
                "id": "callout-round",
                "type": 3,
                "intent": "FreeTextCallout",
                "pageIndex": 0,
                "rect": _device_highlight_rect(),
                "calloutLine": [
                    {"x": 150.0, "y": 52.0},
                    {"x": 150.0, "y": 30.0},
                    {"x": 200.0, "y": 30.0},
                ],
                "contents": "callout round",
            }
        }

        # device -> PDF user-space
        pdf_user = _convert_annotation_to_pdf_user(raw, page_height=842.0, page_x0=0.0, page_y0=0.0)
        line_pdf = pdf_user["annotation"]["calloutLine"]
        assert line_pdf[0]["y"] == pytest.approx(790.0, abs=0.01)

        # PDF user-space -> device-space
        device = _convert_annotation_to_device_space(pdf_user["annotation"], page_height=842.0, page_x0=0.0, page_y0=0.0)
        line_device = device["calloutLine"]
        assert line_device[0]["y"] == pytest.approx(52.0, abs=0.01)
        assert line_device[0]["x"] == pytest.approx(150.0, abs=0.01)
