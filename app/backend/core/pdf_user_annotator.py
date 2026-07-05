#!/usr/bin/env python3
# [Flow: Step 1 (PDF bytes와 Fresh Air PDF annotation 배열 수신)
#       -> Step 2 (페이지별 주석 그룹화)
#       -> Step 3 (색상/좌표 변환)
#       -> Step 4 (PyMuPDF 주석 추가)
#       -> Step 5 (주석이 추가된 PDF bytes 반환)]
from __future__ import annotations

import logging
from typing import Any

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


def apply_user_annotations(pdf_bytes: bytes, annotations: list[dict]) -> bytes:
    """[Flow: Step 1 (PDF 열기) -> Step 2 (페이지별 주석 그룹화)
          -> Step 3 (각 주석을 PyMuPDF로 적용) -> Step 4 (새 PDF bytes 반환)]

    원본 PDF에 사용자가 편집한 Fresh Air PDF 형식의 주석을 추가한다.

    Args:
        pdf_bytes: 원본 PDF 바이트
        annotations: Fresh Air PDF importAnnotations/exportAnnotations 형식의 annotation 객체 배열

    Returns:
        주석이 추가된 PDF bytes
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    by_page: dict[int, list[dict]] = {}
    for a in annotations:
        page_number = a.get("pageNumber")
        if not isinstance(page_number, int) or page_number < 1:
            continue
        by_page.setdefault(page_number, []).append(a)

    for page_no, page_annotations in by_page.items():
        if page_no > doc.page_count:
            logger.warning(f"[pdf_user_annotator] 잘못된 pageNumber {page_no} (총 {doc.page_count}페이지), 건너뜀")
            continue
        page = doc[page_no - 1]
        for a in page_annotations:
            try:
                _apply_annotation(page, a)
            except Exception as e:
                logger.warning(f"[pdf_user_annotator] 주석 적용 실패 {a.get('id')}: {e}")

    return doc.tobytes()


def _apply_annotation(page: fitz.Page, a: dict) -> None:
    """[Flow: Step 1 (주석 유형 분기) -> Step 2 (좌표/색상 변환) -> Step 3 (PyMuPDF 주석 추가)]"""
    atype = a.get("type", "")
    color = _hex_to_rgb(a.get("color", "#000000"))
    opacity = a.get("opacity", 1.0)

    if atype == "highlight":
        rect = _quad_to_rect(a.get("quads"))
        if rect:
            annot = page.add_highlight_annot(rect)
            _style_annot(annot, color, opacity)
        return

    if atype == "underline":
        rect = _quad_to_rect(a.get("quads"))
        if rect:
            annot = page.add_underline_annot(rect)
            _style_annot(annot, color, opacity)
        return

    if atype == "strikeout":
        rect = _quad_to_rect(a.get("quads"))
        if rect:
            annot = page.add_strikeout_annot(rect)
            _style_annot(annot, color, opacity)
        return

    if atype == "free-text":
        rect = _parse_rect(a.get("rect"))
        if rect:
            text = a.get("content", "")
            font_size = a.get("fontSize", 14)
            annot = page.add_freetext_annot(
                rect,
                text,
                fontsize=font_size,
                text_color=color,
                rotate=page.rotation,
            )
            annot.set_opacity(opacity)
            annot.update()
        return

    if atype == "rectangle":
        rect = _parse_rect(a.get("rect"))
        if rect:
            annot = page.add_rect_annot(rect)
            fill_color = _hex_to_rgb(a.get("fillColor")) if a.get("fillColor") else None
            _style_annot(annot, color, opacity, fill_color=fill_color)
        return

    if atype == "circle":
        rect = _parse_rect(a.get("rect"))
        if rect:
            annot = page.add_circle_annot(rect)
            fill_color = _hex_to_rgb(a.get("fillColor")) if a.get("fillColor") else None
            _style_annot(annot, color, opacity, fill_color=fill_color)
        return

    if atype in ("line", "arrow"):
        start = _parse_point(a.get("start"))
        end = _parse_point(a.get("end"))
        if start and end:
            annot = page.add_line_annot(start, end)
            _style_annot(annot, color, opacity, width=a.get("width", 1.0))
        return

    if atype == "ink":
        paths = _parse_paths(a.get("paths"))
        if paths:
            annot = page.add_ink_annot(paths)
            _style_annot(annot, color, opacity, width=a.get("width", 1.0))
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
    """[Flow: Step 1 (dict 형태 확인) -> Step 2 (x/y/width/height 추출) -> Step 3 (fitz.Rect 반환)]"""
    if not isinstance(rect, dict):
        return None
    x = rect.get("x", 0)
    y = rect.get("y", 0)
    w = rect.get("width", 0)
    h = rect.get("height", 0)
    if w <= 0 or h <= 0:
        return None
    return fitz.Rect(x, y, x + w, y + h)


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


def _quad_to_rect(quads: Any) -> fitz.Rect | None:
    """[Flow: Step 1 (quads 배열 확인) -> Step 2 (Quad 객체 또는 8숫자 배열 파싱)
          -> Step 3 (fitz.Rect 반환)]"""
    if not isinstance(quads, list) or not quads:
        return None
    first = quads[0]
    # Quad 객체 형식: {topLeft, topRight, bottomLeft, bottomRight}
    if isinstance(first, dict):
        tl = _parse_point(first.get("topLeft"))
        br = _parse_point(first.get("bottomRight"))
        if tl and br:
            return fitz.Rect(tl, br)
    # 8개 숫자 배열 형식: [x1,y1,x2,y2,x3,y3,x4,y4]
    if isinstance(first, list) and len(first) == 8:
        xs = first[0::2]
        ys = first[1::2]
        return fitz.Rect(min(xs), min(ys), max(xs), max(ys))
    return None
