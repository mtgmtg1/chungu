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
    """[Flow: Step 1 (주석 유형 숫자 분기) -> Step 2 (좌표/색상 변환 — device-space y↓를 PDF user-space y↑로 flip)
          -> Step 3 (PyMuPDF 주석 추가)]

    EmbedPDF annotation 좌표는 device-space(원점 좌상단, y↓)이다.
    PyMuPDF는 PDF user-space(원점 좌하단, y↑)를 사용하므로 Y축 flip이 필요하다.
    """
    atype = a.get("type")
    color = _hex_to_rgb(a.get("strokeColor") or a.get("color"))
    opacity = a.get("opacity", 1.0)
    page_height = page.rect.height
    page_x0 = page.rect.x0

    if atype == HIGHLIGHT:
        rect = _segment_rects_to_rect(a.get("segmentRects"), page_height, page_x0) or _parse_rect(a.get("rect"), page_height, page_x0)
        if rect:
            annot = page.add_highlight_annot(rect)
            _style_annot(annot, color, opacity)
        return

    if atype == UNDERLINE:
        rect = _segment_rects_to_rect(a.get("segmentRects"), page_height, page_x0) or _parse_rect(a.get("rect"), page_height, page_x0)
        if rect:
            annot = page.add_underline_annot(rect)
            _style_annot(annot, color, opacity)
        return

    if atype == SQUIGGLY:
        rect = _segment_rects_to_rect(a.get("segmentRects"), page_height, page_x0) or _parse_rect(a.get("rect"), page_height, page_x0)
        if rect:
            annot = page.add_squiggly_annot(rect)
            _style_annot(annot, color, opacity)
        return

    if atype == STRIKEOUT:
        rect = _segment_rects_to_rect(a.get("segmentRects"), page_height, page_x0) or _parse_rect(a.get("rect"), page_height, page_x0)
        if rect:
            annot = page.add_strikeout_annot(rect)
            _style_annot(annot, color, opacity)
        return

    if atype == FREETEXT:
        rect = _parse_rect(a.get("rect"), page_height, page_x0)
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
        rect = _parse_rect(a.get("rect"), page_height, page_x0)
        if rect:
            annot = page.add_rect_annot(rect)
            fill_color = _hex_to_rgb(a.get("color")) if a.get("color") else None
            _style_annot(annot, color, opacity, fill_color=fill_color)
        return

    if atype == CIRCLE:
        rect = _parse_rect(a.get("rect"), page_height, page_x0)
        if rect:
            annot = page.add_circle_annot(rect)
            fill_color = _hex_to_rgb(a.get("color")) if a.get("color") else None
            _style_annot(annot, color, opacity, fill_color=fill_color)
        return

    if atype == LINE:
        start = _parse_point(a.get("start"), page_height, page_x0)
        end = _parse_point(a.get("end"), page_height, page_x0)
        if start and end:
            annot = page.add_line_annot(start, end)
            _style_annot(annot, color, opacity, width=a.get("strokeWidth", 1.0))
        return

    if atype == INK:
        paths = _parse_ink_list(a.get("inkList"), page_height, page_x0) or _parse_paths(a.get("paths"), page_height, page_x0)
        if paths:
            annot = page.add_ink_annot(paths)
            _style_annot(annot, color, opacity, width=a.get("strokeWidth", 1.0))
        return

    if atype == STAMP:
        rect = _parse_rect(a.get("rect"), page_height, page_x0)
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


def _parse_rect(rect: Any, page_height: float | None = None, page_x0: float = 0.0) -> fitz.Rect | None:
    """[Flow: Step 1 (EmbedPDF rect 형태 확인) -> Step 2 (origin/size 또는 x/y/width/height 추출)
          -> Step 3 (device-space y↓를 PDF user-space y↑로 flip) -> Step 4 (fitz.Rect 반환)]

    EmbedPDF rect는 device-space(원점 좌상단, y↓) 좌표를 사용한다.
    PyMuPDF는 PDF user-space(원점 좌하단, y↑)를 사용하므로 Y축 flip이 필요하다.
    page_height가 None이면 flip 없이 원래 좌표를 그대로 사용한다 (PyMuPDF vertex 등 PDF 좌표계 입력용).

    Args:
        rect: EmbedPDF rect dict ({origin: {x, y}, size: {width, height}} 또는 {x, y, width, height})
        page_height: 페이지 높이 (PDF user-space). Y축 flip에 사용. None이면 flip 스킵.
        page_x0: 페이지 x 오프셋 (CropBox/MediaBox). device-space x를 PDF user-space로 변환.
    """
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
        if page_height is not None:
            # device-space(y↓) → PDF user-space(y↑): y축 flip
            pdf_y1 = page_height - y
            pdf_y0 = page_height - y - h
            return fitz.Rect(x + page_x0, pdf_y0, x + w + page_x0, pdf_y1)
        return fitz.Rect(x, y, x + w, y + h)
    x = origin.get("x", 0)
    y = origin.get("y", 0)
    w = size.get("width", 0)
    h = size.get("height", 0)
    if w <= 0 or h <= 0:
        return None
    if page_height is not None:
        # device-space(y↓) → PDF user-space(y↑): y축 flip
        pdf_y1 = page_height - y
        pdf_y0 = page_height - y - h
        return fitz.Rect(x + page_x0, pdf_y0, x + w + page_x0, pdf_y1)
    # page_height가 None이면 flip 없이 원래 좌표 사용 (PyMuPDF vertex 등)
    return fitz.Rect(x, y - h, x + w, y)


def _segment_rects_to_rect(segment_rects: Any, page_height: float | None = None, page_x0: float = 0.0) -> fitz.Rect | None:
    """[Flow: Step 1 (segmentRects 배열 확인) -> Step 2 (첫 번째 rect를 fitz.Rect로 변환)
          -> Step 3 (하나라도 실패하면 None 반환)]"""
    if not isinstance(segment_rects, list) or not segment_rects:
        return None
    first = segment_rects[0]
    return _parse_rect(first, page_height, page_x0)


def _parse_point(point: Any, page_height: float | None = None, page_x0: float = 0.0) -> fitz.Point | None:
    """[Flow: Step 1 (dict 형태 확인) -> Step 2 (x/y 추출) -> Step 3 (Y축 flip 후 fitz.Point 반환)]

    EmbedPDF point는 device-space(y↓) 좌표를 사용한다.
    page_height가 None이면 flip 없이 원래 좌표를 그대로 사용한다 (PyMuPDF vertex 등 PDF 좌표계 입력용).

    Args:
        point: {x, y} dict (device-space)
        page_height: 페이지 높이. Y축 flip에 사용. None이면 flip 스킵.
        page_x0: 페이지 x 오프셋 (CropBox/MediaBox).
    """
    if not isinstance(point, dict):
        return None
    x = point.get("x", 0)
    y = point.get("y", 0)
    if page_height is not None:
        # device-space(y↓) → PDF user-space(y↑): y축 flip
        return fitz.Point(x + page_x0, page_height - y)
    return fitz.Point(x, y)


def _parse_paths(paths: Any, page_height: float | None = None, page_x0: float = 0.0) -> list[list[fitz.Point]] | None:
    """[Flow: Step 1 (list 형태 확인) -> Step 2 (stroke별 point 변환) -> Step 3 (2점 이상 stroke만 반환)]"""
    if not isinstance(paths, list):
        return None
    strokes: list[list[fitz.Point]] = []
    for stroke in paths:
        if not isinstance(stroke, list):
            continue
        points = [_parse_point(p, page_height, page_x0) for p in stroke]
        points = [p for p in points if p]
        if len(points) >= 2:
            strokes.append(points)
    return strokes if strokes else None


def _parse_ink_list(ink_list: Any, page_height: float | None = None, page_x0: float = 0.0) -> list[list[fitz.Point]] | None:
    """[Flow: Step 1 (inkList 형태 확인) -> Step 2 (ink 항목별 points 변환)
          -> Step 3 (2점 이상 stroke만 반환)]"""
    if not isinstance(ink_list, list):
        return None
    strokes: list[list[fitz.Point]] = []
    for ink in ink_list:
        if not isinstance(ink, dict):
            continue
        points = [_parse_point(p, page_height, page_x0) for p in ink.get("points", [])]
        points = [p for p in points if p]
        if len(points) >= 2:
            strokes.append(points)
    return strokes if strokes else None


# [Flow: Step 1 (PyMuPDF 색상 튜플 수신) -> Step 2 (0-255 변환) -> Step 3 (hex 문자열 반환)]
# PyMuPDF의 annot.colors는 stroke/fill 각각 (r, g, b) 0-1 튜플로 반환한다.
EMBEDPDF_TYPE_MAP = {
    # PyMuPDF 버전에 따라 상수 이름이 다를 수 있으므로 getattr로 안전하게 참조한다.
    getattr(fitz, "PDF_ANNOT_HIGHLIGHT", 8): HIGHLIGHT,
    getattr(fitz, "PDF_ANNOT_UNDERLINE", 9): UNDERLINE,
    getattr(fitz, "PDF_ANNOT_SQUIGGLY", 10): SQUIGGLY,
    getattr(fitz, "PDF_ANNOT_STRIKEOUT", getattr(fitz, "PDF_ANNOT_STRIKE_OUT", 11)): STRIKEOUT,
    getattr(fitz, "PDF_ANNOT_FREETEXT", 2): FREETEXT,
    getattr(fitz, "PDF_ANNOT_SQUARE", 4): SQUARE,
    getattr(fitz, "PDF_ANNOT_CIRCLE", 5): CIRCLE,
    getattr(fitz, "PDF_ANNOT_LINE", 3): LINE,
    getattr(fitz, "PDF_ANNOT_INK", 14): INK,
    getattr(fitz, "PDF_ANNOT_STAMP", 12): STAMP,
}


def _fitz_color_to_hex(color: Any) -> str | None:
    """[Flow: Step 1 (PyMuPDF 색상 튜플 수신) -> Step 2 (0-255 변환) -> Step 3 (hex 문자열 반환)]"""
    if not isinstance(color, (tuple, list)) or len(color) < 3:
        return None
    try:
        r, g, b = int(round(color[0] * 255)), int(round(color[1] * 255)), int(round(color[2] * 255))
        return f"#{r:02X}{g:02X}{b:02X}"
    except (TypeError, ValueError):
        return None


def _fitz_rect_to_embedpdf_rect(rect: fitz.Rect, page_height: float, page_x0: float = 0.0) -> dict:
    """[Flow: Step 1 (PyMuPDF Rect 수신) -> Step 2 (page.rect.x0 기준 상대좌표로 변환)
          -> Step 3 (y축 flip) -> Step 4 (origin/size 형태 반환)]

    PyMuPDF Rect는 좌하단 원점, y가 위로 증가하는 PDF 좌표계를 사용한다.
    EmbedPDF는 origin이 좌상단, y가 아래로 증가하는 device-space 좌표계를 사용하므로
    y축을 page_height - y1로 flip해야 한다.

    CropBox/MediaBox가 있는 PDF에서 page.rect.x0이 0이 아닐 경우, EmbedPDF 좌표는
    page.rect의 왼쪽 끝을 기준으로 한 상대좌표를 사용하므로 x0에서 page_x0을 빼준다.
    """
    x0, y0, x1, y1 = rect.x0, rect.y0, rect.x1, rect.y1
    return {
        "origin": {"x": x0 - page_x0, "y": page_height - y1},
        "size": {"width": max(0.0, x1 - x0), "height": max(0.0, y1 - y0)},
    }


def extract_pdf_annotations(pdf_bytes: bytes) -> list[dict]:
    """[Flow: Step 1 (원본 PDF 열기) -> Step 2 (페이지별 내장 주석 순회)
          -> Step 3 (EmbedPDF AnnotationTransferItem 형식으로 변환) -> Step 4 (목록 반환)]

    원본 PDF에 이미 내장된 하이라이트/여백 주석 등을 EmbedPDF JSON 오버레이 형식으로
    변환한다. 이를 통해 원본 주석을 embedpdf에서 오버레이로만 표시하고, PDF 자체에는
    주석을 남기지 않아 중복 추가/누적 문제를 방지할 수 있다.

    Args:
        pdf_bytes: 원본 PDF 바이트

    Returns:
        EmbedPDF AnnotationTransferItem[] 형식의 주석 목록
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    annotations: list[dict] = []
    for page in doc:
        page_height = page.rect.height
        for idx, annot in enumerate(page.annots()):
            try:
                annot_type = annot.type[0] if isinstance(annot.type, tuple) else annot.type
                embed_type = EMBEDPDF_TYPE_MAP.get(annot_type)
                if embed_type is None:
                    continue
                rect = _fitz_rect_to_embedpdf_rect(annot.rect, page_height, page.rect.x0)
                colors = annot.colors or {}
                stroke_color = _fitz_color_to_hex(colors.get("stroke")) if colors.get("stroke") else None
                fill_color = _fitz_color_to_hex(colors.get("fill")) if colors.get("fill") else None
                color = stroke_color or fill_color or "#FFEB3B"
                opacity = getattr(annot, "opacity", 1.0)
                if not isinstance(opacity, (int, float)):
                    opacity = 1.0
                info = annot.info or {}
                contents = info.get("content", "") or ""
                annotation = {
                    "id": f"original-{page.number}-{idx}",
                    "type": embed_type,
                    "pageIndex": page.number,
                    "rect": rect,
                    "contents": contents,
                    "opacity": opacity,
                }
                if embed_type in (HIGHLIGHT, UNDERLINE, SQUIGGLY, STRIKEOUT):
                    annotation["segmentRects"] = [rect]
                    annotation["strokeColor"] = color
                    annotation["color"] = color
                elif embed_type in (SQUARE, CIRCLE, INK, STAMP):
                    annotation["color"] = color
                    if fill_color:
                        annotation["fillColor"] = fill_color
                elif embed_type == LINE:
                    annotation["color"] = color
                    # PyMuPDF vertex는 이미 PDF user-space(y↑) 좌표이므로 flip 없이 그대로 사용 (page_height=None)
                    start = _parse_point(annot.vertices[0]) if annot.vertices else None
                    end = _parse_point(annot.vertices[1]) if annot.vertices and len(annot.vertices) > 1 else None
                    if start and end:
                        annotation["start"] = {"x": start.x, "y": start.y}
                        annotation["end"] = {"x": end.x, "y": end.y}
                elif embed_type == FREETEXT:
                    annotation["fontFamily"] = 4  # Helvetica
                    annotation["fontSize"] = info.get("fontsize", 12) or 12
                    annotation["fontColor"] = color
                    annotation["textAlign"] = 0
                    annotation["verticalAlign"] = 0
                annotations.append({"annotation": annotation})
            except Exception as e:
                logger.warning(f"[extract_pdf_annotations] page={page.number} idx={idx} 변환 실패: {e}")
                continue
    return annotations


def remove_pdf_annotations(pdf_bytes: bytes) -> bytes:
    """[Flow: Step 1 (원본 PDF 열기) -> Step 2 (페이지별 내장 주석 삭제)
          -> Step 3 (주석이 제거된 PDF bytes 반환)]"""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        for annot in list(page.annots()):
            try:
                page.delete_annot(annot)
            except Exception as e:
                logger.warning(f"[remove_pdf_annotations] page={page.number} 주석 삭제 실패: {e}")
    return doc.tobytes()
