#!/usr/bin/env python3
# [Flow: Step 1 (PDF bytes와 EmbedPDF annotation 배열 수신)
#       -> Step 2 (각 항목에서 annotation 객체 추출)
#       -> Step 3 (페이지별 주석 그룹화)
#       -> Step 4 (색상/좌표 변환)
#       -> Step 5 (PyMuPDF 주석 추가)
#       -> Step 6 (주석이 추가된 PDF bytes 반환)]
from __future__ import annotations

import logging
from typing import Any

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# EmbedPDF PdfAnnotationSubtype enum 값 (숫자 상수)
# 참고: https://cdn.jsdelivr.net/npm/@embedpdf/models/dist/pdf.d.ts
FREETEXT = 3
LINE = 4
SQUARE = 5
CIRCLE = 6
HIGHLIGHT = 9
UNDERLINE = 10
SQUIGGLY = 11
STRIKEOUT = 12
STAMP = 13
INK = 15


def apply_user_annotations(pdf_bytes: bytes, annotations: list[dict]) -> bytes:
    """[Flow: Step 1 (PDF 열기) -> Step 2 (각 항목에서 annotation 객체 추출)
          -> Step 3 (페이지별 주석 그룹화) -> Step 4 (각 주석을 PyMuPDF로 적용)
          -> Step 5 (새 PDF bytes 반환)]

    원본 PDF에 사용자가 편집한 EmbedPDF 형식의 주석을 추가한다.
    입력은 EmbedPDF exportAnnotations()가 반환하는 AnnotationTransferItem[] 형식이며,
    하위 호환을 위해 annotation 객체 배열도 수용한다.

    Args:
        pdf_bytes: 원본 PDF 바이트
        annotations: EmbedPDF AnnotationTransferItem[] 또는 annotation 객체 배열

    Returns:
        주석이 추가된 PDF bytes
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    by_page: dict[int, list[dict]] = {}
    for item in annotations:
        a = _extract_annotation(item)
        if not a:
            continue
        page_index = a.get("pageIndex")
        if not isinstance(page_index, int) or page_index < 0:
            continue
        page_number = page_index + 1  # EmbedPDF는 0-based, PyMuPDF는 0-based이나 로직상 1-based로 처리
        by_page.setdefault(page_number, []).append(a)

    applied = 0
    for page_no, page_annotations in by_page.items():
        if page_no > doc.page_count:
            logger.warning(f"[pdf_user_annotator] 잘못된 pageIndex {page_no - 1} (총 {doc.page_count}페이지), 건너뜀")
            continue
        page = doc[page_no - 1]
        for a in page_annotations:
            try:
                _apply_annotation(page, a)
                applied += 1
            except Exception as e:
                logger.warning(f"[pdf_user_annotator] 주석 적용 실패 {a.get('id')}: {e}")

    logger.info(f"[pdf_user_annotator] 총 {len(annotations)}개 항목 중 {applied}개 주석 적용 완료")
    return doc.tobytes()


def _extract_annotation(item: Any) -> dict | None:
    """[Flow: Step 1 (item이 dict인지 확인) -> Step 2 (annotation 필드가 있으면 추출)
          -> Step 3 (annotation 객체 반환)]"""
    if not isinstance(item, dict):
        return None
    if "annotation" in item and isinstance(item["annotation"], dict):
        return item["annotation"]
    return item


def _apply_annotation(page: fitz.Page, a: dict) -> None:
    """[Flow: Step 1 (주석 유형 숫자 분기) -> Step 2 (좌표/색상 변환) -> Step 3 (PyMuPDF 주석 추가)]"""
    atype = a.get("type")
    color = _hex_to_rgb(a.get("strokeColor") or a.get("color"))
    opacity = a.get("opacity", 1.0)

    if atype == HIGHLIGHT:
        rect = _segment_rects_to_rect(a.get("segmentRects")) or _parse_rect(a.get("rect"))
        if rect:
            annot = page.add_highlight_annot(rect)
            _style_annot(annot, color, opacity)
        return

    if atype == UNDERLINE:
        rect = _segment_rects_to_rect(a.get("segmentRects")) or _parse_rect(a.get("rect"))
        if rect:
            annot = page.add_underline_annot(rect)
            _style_annot(annot, color, opacity)
        return

    if atype == SQUIGGLY:
        rect = _segment_rects_to_rect(a.get("segmentRects")) or _parse_rect(a.get("rect"))
        if rect:
            annot = page.add_squiggly_annot(rect)
            _style_annot(annot, color, opacity)
        return

    if atype == STRIKEOUT:
        rect = _segment_rects_to_rect(a.get("segmentRects")) or _parse_rect(a.get("rect"))
        if rect:
            annot = page.add_strikeout_annot(rect)
            _style_annot(annot, color, opacity)
        return

    if atype == FREETEXT:
        rect = _parse_rect(a.get("rect"))
        if rect:
            text = a.get("contents", "")
            font_size = a.get("fontSize", 14)
            font_color = _hex_to_rgb(a.get("fontColor")) if a.get("fontColor") else (0.0, 0.0, 0.0)
            annot = page.add_freetext_annot(
                rect,
                text,
                fontsize=font_size,
                text_color=font_color,
                rotate=page.rotation,
            )
            annot.set_opacity(opacity)
            annot.update()
        return

    if atype == SQUARE:
        rect = _parse_rect(a.get("rect"))
        if rect:
            annot = page.add_rect_annot(rect)
            fill_color = _hex_to_rgb(a.get("color")) if a.get("color") else None
            _style_annot(annot, color, opacity, fill_color=fill_color)
        return

    if atype == CIRCLE:
        rect = _parse_rect(a.get("rect"))
        if rect:
            annot = page.add_circle_annot(rect)
            fill_color = _hex_to_rgb(a.get("color")) if a.get("color") else None
            _style_annot(annot, color, opacity, fill_color=fill_color)
        return

    if atype == LINE:
        start = _parse_point(a.get("start"))
        end = _parse_point(a.get("end"))
        if start and end:
            annot = page.add_line_annot(start, end)
            _style_annot(annot, color, opacity, width=a.get("strokeWidth", 1.0))
        return

    if atype == INK:
        paths = _parse_ink_list(a.get("inkList")) or _parse_paths(a.get("paths"))
        if paths:
            annot = page.add_ink_annot(paths)
            _style_annot(annot, color, opacity, width=a.get("strokeWidth", 1.0))
        return

    if atype == STAMP:
        rect = _parse_rect(a.get("rect"))
        if rect:
            annot = page.add_stamp_annot(rect, stamp=0)
            _style_annot(annot, color, opacity)
        return


def _style_annot(
    annot: fitz.Annot | None,
    color: tuple[float, float, float],
    opacity: float,
    fill_color: tuple[float, float, float] | None = None,
    width: float | None = None,
) -> None:
    """[Flow: Step 1 (annot null 체크) -> Step 2 (색상/채움/두께/투명도 설정) -> Step 3 (update)]"""
    if annot is None:
        return
    if fill_color:
        annot.set_colors(stroke=color, fill=fill_color)
    else:
        annot.set_colors(stroke=color)
    if width is not None:
        annot.set_border(width=width)
    annot.set_opacity(opacity)
    annot.update()


def _hex_to_rgb(hex_color: str | None) -> tuple[float, float, float]:
    """[Flow: Step 1 (# 제거) -> Step 2 (6자리 hex 파싱) -> Step 3 (0-1 RGB 튜플 반환)]"""
    if not hex_color:
        return (0.0, 0.0, 0.0)
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return (0.0, 0.0, 0.0)
    try:
        return (
            int(hex_color[0:2], 16) / 255.0,
            int(hex_color[2:4], 16) / 255.0,
            int(hex_color[4:6], 16) / 255.0,
        )
    except ValueError:
        return (0.0, 0.0, 0.0)


def _parse_rect(rect: Any) -> fitz.Rect | None:
    """[Flow: Step 1 (EmbedPDF rect 형태 확인) -> Step 2 (origin/size 추출) -> Step 3 (fitz.Rect 반환)]"""
    if not isinstance(rect, dict):
        return None
    origin = rect.get("origin")
    size = rect.get("size")
    if not isinstance(origin, dict) or not isinstance(size, dict):
        # 하위 호환: x/y/width/height 형태도 지원
        x = rect.get("x", 0)
        y = rect.get("y", 0)
        w = rect.get("width", 0)
        h = rect.get("height", 0)
        if w <= 0 or h <= 0:
            return None
        return fitz.Rect(x, y, x + w, y + h)
    x = origin.get("x", 0)
    y = origin.get("y", 0)
    w = size.get("width", 0)
    h = size.get("height", 0)
    if w <= 0 or h <= 0:
        return None
    # EmbedPDF Rect는 origin이 좌상단, PDF 좌표계는 y가 위로 증가하므로
    # fitz.Rect(x0, y0, x1, y1)에서 y0 = origin.y - height, y1 = origin.y
    return fitz.Rect(x, y - h, x + w, y)


def _segment_rects_to_rect(segment_rects: Any) -> fitz.Rect | None:
    """[Flow: Step 1 (segmentRects 배열 확인) -> Step 2 (첫 번째 rect를 fitz.Rect로 변환)
          -> Step 3 (하나라도 실패하면 None 반환)]"""
    if not isinstance(segment_rects, list) or not segment_rects:
        return None
    first = segment_rects[0]
    return _parse_rect(first)


def _parse_point(point: Any) -> fitz.Point | None:
    """[Flow: Step 1 (dict 형태 확인) -> Step 2 (x/y 추출) -> Step 3 (fitz.Point 반환)]"""
    if not isinstance(point, dict):
        return None
    return fitz.Point(point.get("x", 0), point.get("y", 0))


def _parse_paths(paths: Any) -> list[list[fitz.Point]] | None:
    """[Flow: Step 1 (list 형태 확인) -> Step 2 (stroke별 point 변환) -> Step 3 (2점 이상 stroke만 반환)]"""
    if not isinstance(paths, list):
        return None
    strokes: list[list[fitz.Point]] = []
    for stroke in paths:
        if not isinstance(stroke, list):
            continue
        points = [_parse_point(p) for p in stroke]
        points = [p for p in points if p]
        if len(points) >= 2:
            strokes.append(points)
    return strokes if strokes else None


def _parse_ink_list(ink_list: Any) -> list[list[fitz.Point]] | None:
    """[Flow: Step 1 (inkList 형태 확인) -> Step 2 (ink 항목별 points 변환)
          -> Step 3 (2점 이상 stroke만 반환)]"""
    if not isinstance(ink_list, list):
        return None
    strokes: list[list[fitz.Point]] = []
    for ink in ink_list:
        if not isinstance(ink, dict):
            continue
        points = [_parse_point(p) for p in ink.get("points", [])]
        points = [p for p in points if p]
        if len(points) >= 2:
            strokes.append(points)
    return strokes if strokes else None
