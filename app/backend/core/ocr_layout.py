#!/usr/bin/env python3
# [Flow: Step 1 (AI Studio/로컬 PaddleOCR-VL 1.6 원본 JSON 수신) -> Step 2 (parsing_res_list에서 table 블록 추출)
#       -> Step 3 (block_content의 HTML 표를 행 단위로 파싱) -> Step 4 (행 bbox는 테이블 block_bbox를
#       행 개수만큼 세로로 균등 분할해 추정) -> Step 5 (PageLayout 반환)]
# PaddleOCR-VL 1.6 원본 결과(res.json / AI Studio prunedResult)를 하이라이트/여백 주석 기능에서
# 공통으로 쓸 수 있는 형태로 정규화한다.
#
# 실측 스키마 (a1 프로덕션에서 실제 AI Studio 응답을 덤프해 확인, 2026-07-05):
#   { "page_count": null, "width": <px>, "height": <px>,
#     "layout_det_res": {"boxes": [...]},
#     "parsing_res_list": [
#       {"block_label": "table"|"text"|"title"|"seal"|"image"|"figure_title"|...,
#        "block_content": "<table>...</table>" (표인 경우) 또는 일반 텍스트,
#        "block_bbox": [xmin, ymin, xmax, ymax],  # 블록 전체 bbox (픽셀), 셀/행 단위 bbox는 없음
#        "block_id": int, "block_order": int, "group_id": int,
#        "block_polygon_points": [[x,y], ...]},
#       ...
#     ]}
#
# PP-StructureV3 계열 문서에 흔한 table_res_list/cell_box_list 스키마와는 다르다 (VLM 통합 파싱 결과라
# 표는 block 하나 + HTML 문자열로만 내려온다). 행 단위 bbox가 없으므로, 표 block_bbox의 세로 범위를
# HTML의 <tr> 개수만큼 균등 분할해 각 행의 근사 bbox로 사용한다 (표 전체 폭 x 균등 분할 높이).
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import lxml.html

logger = logging.getLogger(__name__)

BBox = tuple[float, float, float, float]  # (xmin, ymin, xmax, ymax), 픽셀 단위


@dataclass
class OcrCell:
    text: str


@dataclass
class OcrRow:
    """표의 한 행. bbox_px는 표 block_bbox를 행 개수로 균등 분할한 근사값(셀 단위 정밀도 없음)."""

    row_index: int
    cells: list[OcrCell]
    bbox_px: BBox

    @property
    def cell_texts(self) -> list[str]:
        return [c.text for c in self.cells]


@dataclass
class OcrTable:
    rows: list[OcrRow]
    block_bbox: BBox


@dataclass
class PageLayout:
    page_no: int  # 1-based
    tables: list[OcrTable] = field(default_factory=list)


def _parse_html_table_rows(html_fragment: str) -> list[list[str]]:
    """<table> HTML 문자열을 행×셀 텍스트 리스트로 파싱한다. office_converter.py와 동일하게 lxml recover 모드 사용."""
    if not html_fragment or "<table" not in html_fragment.lower():
        return []
    parser = lxml.html.HTMLParser(recover=True)
    try:
        root = lxml.html.fromstring(f"<html><body>{html_fragment}</body></html>", parser=parser)
    except Exception as e:
        logger.warning(f"[ocr_layout] 표 HTML 파싱 실패: {e}")
        return []

    table_el = root.find(".//table")
    if table_el is None:
        return []

    rows: list[list[str]] = []
    for tr in table_el.findall(".//tr"):
        cells = [c.text_content().strip() for c in tr.findall("./td") + tr.findall("./th")]
        if cells:
            rows.append(cells)
    return rows


def _split_bbox_into_rows(block_bbox: BBox, row_count: int) -> list[BBox]:
    """표 block_bbox를 세로로 row_count등분해 각 행의 근사 bbox를 만든다 (행 높이가 균등하다고 가정)."""
    x0, y0, x1, y1 = block_bbox
    if row_count <= 0:
        return []
    row_height = (y1 - y0) / row_count
    return [(x0, y0 + i * row_height, x1, y0 + (i + 1) * row_height) for i in range(row_count)]


def _parse_table_block(block: dict) -> OcrTable | None:
    bbox = block.get("block_bbox")
    if not bbox or len(bbox) < 4:
        return None
    rows_text = _parse_html_table_rows(block.get("block_content", ""))
    if not rows_text:
        return None

    block_bbox: BBox = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    row_bboxes = _split_bbox_into_rows(block_bbox, len(rows_text))

    rows: list[OcrRow] = []
    for idx, (cells_text, row_bbox) in enumerate(zip(rows_text, row_bboxes)):
        rows.append(OcrRow(row_index=idx, cells=[OcrCell(text=c) for c in cells_text], bbox_px=row_bbox))
    return OcrTable(rows=rows, block_bbox=block_bbox)


def parse_layout_result(raw: dict, page_no: int = 1) -> PageLayout:
    """AI Studio prunedResult 또는 로컬 res.json 딕셔너리 하나를 PageLayout으로 정규화한다."""
    if not raw:
        return PageLayout(page_no=page_no)
    try:
        blocks = raw.get("parsing_res_list") or []
        tables: list[OcrTable] = []
        for block in blocks:
            if not isinstance(block, dict) or block.get("block_label") != "table":
                continue
            table = _parse_table_block(block)
            if table is not None:
                tables.append(table)
        return PageLayout(page_no=page_no, tables=tables)
    except Exception as e:
        logger.warning(f"[ocr_layout] 페이지 {page_no} 레이아웃 파싱 실패: {e}")
        return PageLayout(page_no=page_no)
