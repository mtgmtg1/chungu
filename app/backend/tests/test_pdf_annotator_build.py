#!/usr/bin/env python3
"""[Flow: Step 1 (가상 PDF 생성) -> Step 2 (AnnotationTarget 목록 준비)
      -> Step 3 (build_embedpdf_annotations 호출) -> Step 4 (반환된 AnnotationTransferItem 형식 검증)]

pdf_annotator.build_embedpdf_annotations가 EmbedPDF importAnnotations()에 필요한
AnnotationTransferItem[] 형식으로 주석을 생성하는지 단위 테스트한다.
이 테스트는 프론트엔드로 전달되는 JSON 구조 자체의 정합성을 백엔드 단에서 선제적으로 검증하기 위해 마련한다.
"""
import sys
import os
import io

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz
import pytest

from core.pdf_annotator import (
    AnnotationTarget,
    build_embedpdf_annotations,
    HIGHLIGHT_TYPE,
    FREETEXT_TYPE,
    HELVETICA_FONT,
    LEFT_ALIGN,
    TOP_ALIGN,
    DEFAULT_OPACITY,
    CALLOUT_TEXTBOX_FONT_SIZE,
    CALLOUT_TEXTBOX_FONT_COLOR,
    CALLOUT_TEXTBOX_BG_COLOR,
    CALLOUT_LINE_ENDING_OPEN_ARROW,
    CALLOUT_STROKE_WIDTH,
)


def _make_a4_pdf() -> bytes:
    """[Flow: PyMuPDF 문서 생성 -> A4 페이지 삽입 -> 바이트로 저장 -> 반환]"""
    doc = fitz.open()
    doc.new_page(width=595.0, height=842.0)
    stream = io.BytesIO()
    doc.save(stream)
    doc.close()
    return stream.getvalue()


def _target(page_no: int = 1, bbox_pdf: tuple[float, float, float, float] = (100, 700, 200, 720), comment: str = "test"):
    """[Flow: 기본 인자로 AnnotationTarget 인스턴스 생성 -> 반환]"""
    return AnnotationTarget(page_no=page_no, bbox_pdf=bbox_pdf, comment=comment)


class TestBuildEmbedpdfAnnotations:
    """build_embedpdf_annotations가 AnnotationTransferItem[]을 올바르게 생성한다."""

    def test_highlight_mode_returns_highlight_annotation(self):
        # [Flow: PDF 바이트 획득 -> highlight 모드로 변환 -> 결과 길이/필드 검증]
        pdf_bytes = _make_a4_pdf()
        targets = [_target()]

        result = build_embedpdf_annotations(pdf_bytes, targets, mode="highlight")

        assert isinstance(result, list)
        assert len(result) == 1
        item = result[0]
        assert "annotation" in item
        ann = item["annotation"]
        assert ann["type"] == HIGHLIGHT_TYPE
        assert ann["pageIndex"] == 0
        assert ann["contents"] == "test"
        assert ann["opacity"] == DEFAULT_OPACITY
        # build_embedpdf_annotations는 canonical normalized (0-1, 좌상단 원점) 좌표를 반환한다.
        # A4 842pt 기준 PDF user-space (100,700,200,720) -> canonical
        page_width, page_height = 595.0, 842.0
        rect = ann["rect"]
        assert rect["origin"]["x"] == pytest.approx(100.0 / page_width, rel=1e-5)
        assert rect["origin"]["y"] == pytest.approx((page_height - 720.0) / page_height, rel=1e-5)
        assert rect["size"]["width"] == pytest.approx(100.0 / page_width, rel=1e-5)
        assert rect["size"]["height"] == pytest.approx(20.0 / page_height, rel=1e-5)
        assert "segmentRects" in ann
        assert len(ann["segmentRects"]) == 1
        assert "strokeColor" in ann
        assert "color" in ann

    def test_margin_note_mode_returns_callout_annotation(self):
        # [Flow: PDF 바이트 획득 -> margin_note 모드로 변환 -> callout 필드 검증]
        pdf_bytes = _make_a4_pdf()
        targets = [_target()]

        result = build_embedpdf_annotations(pdf_bytes, targets, mode="margin_note")

        assert len(result) == 1
        ann = result[0]["annotation"]
        assert ann["type"] == FREETEXT_TYPE
        assert ann["intent"] == "FreeTextCallout"
        assert ann["pageIndex"] == 0
        assert ann["contents"] == "test"
        assert ann["fontFamily"] == HELVETICA_FONT
        assert ann["fontSize"] == CALLOUT_TEXTBOX_FONT_SIZE
        assert ann["fontColor"] == CALLOUT_TEXTBOX_FONT_COLOR
        assert ann["textAlign"] == LEFT_ALIGN
        assert ann["verticalAlign"] == TOP_ALIGN
        assert ann["color"] == CALLOUT_TEXTBOX_BG_COLOR
        assert ann["lineEnding"] == CALLOUT_LINE_ENDING_OPEN_ARROW
        assert ann["strokeWidth"] == CALLOUT_STROKE_WIDTH
        assert "rect" in ann
        assert "rectangleDifferences" in ann
        assert "calloutLine" in ann
        assert isinstance(ann["calloutLine"], list)
        assert len(ann["calloutLine"]) in (2, 3)

    def test_both_mode_returns_highlight_and_callout(self):
        # [Flow: both 모드 요청 -> 하이라이트 1개 + callout 1개 총 2개 생성 확인]
        pdf_bytes = _make_a4_pdf()
        targets = [_target()]

        result = build_embedpdf_annotations(pdf_bytes, targets, mode="both")

        assert len(result) == 2
        types = {item["annotation"]["type"] for item in result}
        assert types == {HIGHLIGHT_TYPE, FREETEXT_TYPE}

    def test_page_index_is_zero_based_and_out_of_range_is_skipped(self):
        # [Flow: page_no=2로 A4 1페이지 문서에 요청 -> 빈 리스트 반환 확인]
        pdf_bytes = _make_a4_pdf()
        targets = [_target(page_no=2)]

        result = build_embedpdf_annotations(pdf_bytes, targets, mode="highlight")

        assert result == []

    def test_empty_targets_returns_empty_list(self):
        # [Flow: 대상 없음 -> 빈 리스트 반환]
        pdf_bytes = _make_a4_pdf()

        result = build_embedpdf_annotations(pdf_bytes, [], mode="highlight")

        assert result == []

    def test_callout_avoids_existing_elements(self):
        # [Flow: 페이지 중앙에 기존 요소 배치 -> callout이 다른 위치에 배치되는지 확인]
        pdf_bytes = _make_a4_pdf()
        # 페이지 중앙 큰 장애물
        obstacles = {1: [(200, 400, 400, 600)]}
        targets = [_target(bbox_pdf=(100, 700, 200, 720), comment="avoid")]

        result = build_embedpdf_annotations(
            pdf_bytes, targets, mode="margin_note", page_elements_bboxes=obstacles
        )

        assert len(result) == 1
        ann = result[0]["annotation"]
        rect = ann["rect"]
        # build_embedpdf_annotations는 canonical (0-1) 좌표를 반환하므로 device points로 환산해 비교
        page_width, page_height = 595.0, 842.0
        tx0 = rect["origin"]["x"] * page_width
        ty0 = rect["origin"]["y"] * page_height
        tx1 = tx0 + rect["size"]["width"] * page_width
        ty1 = ty0 + rect["size"]["height"] * page_height
        # obstacle (200,400,400,600)은 PDF user-space; device-space y_top=842-600=242, y_bottom=842-400=442
        assert (tx1 <= 200.0 or tx0 >= 400.0) or (ty1 <= 242.0 or ty0 >= 442.0)

    def test_targets_sorted_by_y_within_page(self):
        # [Flow: 같은 페이지에 y좌표가 뒤죽박죽인 대상 2개 -> 결과 순서가 y0 기준 오름차순인지 확인]
        pdf_bytes = _make_a4_pdf()
        targets = [
            _target(bbox_pdf=(100, 500, 200, 520), comment="lower"),
            _target(bbox_pdf=(100, 700, 200, 720), comment="upper"),
        ]

        result = build_embedpdf_annotations(pdf_bytes, targets, mode="highlight")

        assert len(result) == 2
        # y0 기준 오름차순(PDF user-space)이므로 lower(500) 먼저, upper(700) 다음
        assert result[0]["annotation"]["contents"] == "lower"
        assert result[1]["annotation"]["contents"] == "upper"

    def test_search_rects_pdf_creates_multiple_segment_rects(self):
        # [Flow: 한 대상에 여러 검색 결과 rects가 있을 때 -> segmentRects가 모두 포함되고 custom에 searchText가 남는지 확인]
        pdf_bytes = _make_a4_pdf()
        target = AnnotationTarget(
            page_no=1,
            bbox_pdf=(50, 700, 250, 720),
            comment="multiple",
            search_rects_pdf=[(50, 700, 150, 720), (150, 700, 250, 720)],
            search_text="hello",
        )

        result = build_embedpdf_annotations(pdf_bytes, [target], mode="highlight")

        assert len(result) == 1
        ann = result[0]["annotation"]
        assert ann["type"] == HIGHLIGHT_TYPE
        assert "segmentRects" in ann
        assert len(ann["segmentRects"]) == 2
        assert ann["custom"] == {"searchText": "hello"}
