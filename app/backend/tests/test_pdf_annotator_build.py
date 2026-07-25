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
    TEXT_TYPE,
    HELVETICA_FONT,
    LEFT_ALIGN,
    TOP_ALIGN,
    DEFAULT_OPACITY,
    CALLOUT_TEXTBOX_FONT_SIZE,
    CALLOUT_TEXTBOX_FONT_COLOR,
    CALLOUT_TEXTBOX_BG_COLOR,
    CALLOUT_LINE_ENDING_OPEN_ARROW,
    CALLOUT_STROKE_WIDTH,
    STICKY_NOTE_ICON_SIZE_PT,
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
        # A4 842pt 기준 PDF user-space (100,700,200,720) -> device-space
        # origin.y = page_height - y1 = 842 - 720 = 122
        rect = ann["rect"]
        assert rect["origin"]["x"] == pytest.approx(100.0, abs=0.01)
        assert rect["origin"]["y"] == pytest.approx(122.0, abs=0.01)
        assert rect["size"]["width"] == pytest.approx(100.0, abs=0.01)
        assert rect["size"]["height"] == pytest.approx(20.0, abs=0.01)
        assert "segmentRects" in ann
        assert len(ann["segmentRects"]) == 1
        assert "strokeColor" in ann
        assert "color" in ann

    def test_margin_note_mode_returns_sticky_note_annotation(self):
        # [Flow: PDF 바이트 획득 -> margin_note 모드로 변환 -> sticky note 필드 검증]
        pdf_bytes = _make_a4_pdf()
        targets = [_target()]

        result = build_embedpdf_annotations(pdf_bytes, targets, mode="margin_note")

        assert len(result) == 1
        ann = result[0]["annotation"]
        # sticky note는 embedpdf TEXT(type=1)로 생성된다.
        assert ann["type"] == TEXT_TYPE
        assert ann["pageIndex"] == 0
        assert ann["contents"] == "test"
        # sticky note는 callout 전용 필드(intent/calloutLine/rectangleDifferences/font*)를 갖지 않는다.
        assert "intent" not in ann
        assert "calloutLine" not in ann
        assert "rectangleDifferences" not in ann
        assert "fontFamily" not in ann
        # 아이콘 색은 strokeColor/color로 설정된다.
        assert "strokeColor" in ann
        assert "color" in ann
        # 아이콘은 고정 크기 STICKY_NOTE_ICON_SIZE_PT 로 배치된다.
        rect = ann["rect"]
        assert rect["size"]["width"] == pytest.approx(STICKY_NOTE_ICON_SIZE_PT, abs=0.01)
        assert rect["size"]["height"] == pytest.approx(STICKY_NOTE_ICON_SIZE_PT, abs=0.01)

    def test_both_mode_returns_highlight_and_sticky_note(self):
        # [Flow: both 모드 요청 -> 하이라이트 1개 + sticky note 1개 총 2개 생성 확인]
        pdf_bytes = _make_a4_pdf()
        targets = [_target()]

        result = build_embedpdf_annotations(pdf_bytes, targets, mode="both")

        assert len(result) == 2
        types = {item["annotation"]["type"] for item in result}
        assert types == {HIGHLIGHT_TYPE, TEXT_TYPE}

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

    def test_sticky_note_placed_at_target_text_location(self):
        # [Flow: 대상 텍스트 bbox -> sticky note 아이콘이 대상 텍스트 시작 위치에 배치되는지 확인]
        # sticky note는 callout과 달리 충돌 회피를 하지 않고 대상 텍스트 위치에 직접 겹쳐 배치한다.
        pdf_bytes = _make_a4_pdf()
        # 페이지 중앙 큰 장애물 — sticky note는 이를 무시하고 대상 텍스트 위치에 배치된다.
        obstacles = {1: [(200, 400, 400, 600)]}
        targets = [_target(bbox_pdf=(100, 700, 200, 720), comment="on text")]

        result = build_embedpdf_annotations(
            pdf_bytes, targets, mode="margin_note", page_elements_bboxes=obstacles
        )

        assert len(result) == 1
        ann = result[0]["annotation"]
        assert ann["type"] == TEXT_TYPE
        rect = ann["rect"]
        # 대상 텍스트 시작 x(100)에 아이콘이 배치되어야 한다.
        assert rect["origin"]["x"] == pytest.approx(100.0, abs=0.01)
        # 아이콘 크기는 고정 크기.
        assert rect["size"]["width"] == pytest.approx(STICKY_NOTE_ICON_SIZE_PT, abs=0.01)
        assert rect["size"]["height"] == pytest.approx(STICKY_NOTE_ICON_SIZE_PT, abs=0.01)

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
