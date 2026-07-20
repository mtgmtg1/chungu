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

from . import canonical_annotation_coords as cac
from .pdf_coordinate_transform import (
    device_to_pdf_user,
    device_to_pdf_user_point,
    embedpdf_rect_from_pdf_user,
    pdf_user_rect_from_embedpdf,
    pdf_user_to_device,
    pdf_user_to_device_point,
)

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


def _extract_annotation(item: Any) -> dict | None:
    """[Flow: Step 1 (item이 dict인지 확인) -> Step 2 (annotation 필드가 있으면 추출)
          -> Step 3 (annotation 객체 반환)]"""
    if not isinstance(item, dict):
        return None
    if "annotation" in item and isinstance(item["annotation"], dict):
        return item["annotation"]
    return item


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


def _parse_rect(rect: Any, page_height: float | None = None, page_x0: float = 0.0, page_y0: float = 0.0) -> fitz.Rect | None:
    """[Flow: Step 1 (EmbedPDF rect 형태 확인) -> Step 2 (origin/size 또는 x/y/width/height 추출)
          -> Step 3 (pdf_user_rect_from_embedpdf로 device-space → PDF user-space 변환)
          -> Step 4 (fitz.Rect 반환)]

    EmbedPDF rect는 device-space(원점 좌상단, y↓) 좌표를 사용한다.
    PyMuPDF는 PDF user-space(원점 좌하단, y↑)를 사용하므로 Y축 flip이 필요하다.
    좌표 변환은 pdf_coordinate_transform에서 matrix로 일원화 처리한다.
    page_height가 None이면 flip 없이 원래 좌표를 그대로 사용한다 (PyMuPDF vertex 등 PDF 좌표계 입력용).
    """
    if not isinstance(rect, dict):
        return None
    if page_height is None:
        # 하위 호환: page_height가 주어지지 않으면 y축 flip 없이 x/y/w/h를 PDF user-space로 해석
        x = rect.get("x", 0)
        y = rect.get("y", 0)
        w = rect.get("width", 0)
        h = rect.get("height", 0)
        if w <= 0 or h <= 0:
            return None
        return fitz.Rect(x, y, x + w, y + h)

    origin = rect.get("origin")
    size = rect.get("size")
    if isinstance(origin, dict) and isinstance(size, dict):
        device_rect = {"origin": origin, "size": size}
    else:
        # 하위 호환: x/y/width/height 형태도 지원
        x = rect.get("x", 0)
        y = rect.get("y", 0)
        w = rect.get("width", 0)
        h = rect.get("height", 0)
        if w <= 0 or h <= 0:
            return None
        device_rect = {"origin": {"x": x, "y": y}, "size": {"width": w, "height": h}}

    page_rect = fitz.Rect(page_x0, page_y0, page_x0 + page_height, page_y0 + page_height)
    return pdf_user_rect_from_embedpdf(device_rect, page_rect)


def _segment_rects_to_rect(segment_rects: Any, page_height: float | None = None, page_x0: float = 0.0, page_y0: float = 0.0) -> fitz.Rect | None:
    """[Flow: Step 1 (segmentRects 배열 확인) -> Step 2 (첫 번째 rect를 fitz.Rect로 변환)
          -> Step 3 (하나라도 실패하면 None 반환)]"""
    if not isinstance(segment_rects, list) or not segment_rects:
        return None
    first = segment_rects[0]
    return _parse_rect(first, page_height, page_x0, page_y0)


def _parse_point(point: Any, page_height: float | None = None, page_x0: float = 0.0, page_y0: float = 0.0) -> fitz.Point | None:
    """[Flow: Step 1 (dict 형태 확인) -> Step 2 (x/y 추출)
          -> Step 3 (device_to_pdf_user_point로 device-space → PDF user-space 변환)
          -> Step 4 (fitz.Point 반환)]

    EmbedPDF point는 device-space(y↓) 좌표를 사용한다.
    좌표 변환은 pdf_coordinate_transform에서 matrix로 일원화 처리한다.
    page_height가 None이면 flip 없이 원래 좌표를 그대로 사용한다.
    """
    if not isinstance(point, dict):
        return None
    x = point.get("x", 0)
    y = point.get("y", 0)
    if page_height is None:
        return fitz.Point(x, y)
    page_rect = fitz.Rect(page_x0, page_y0, page_x0 + page_height, page_y0 + page_height)
    return device_to_pdf_user_point((x, y), page_rect)


def _parse_paths(paths: Any, page_height: float | None = None, page_x0: float = 0.0, page_y0: float = 0.0) -> list[list[fitz.Point]] | None:
    """[Flow: Step 1 (list 형태 확인) -> Step 2 (stroke별 point 변환) -> Step 3 (2점 이상 stroke만 반환)]"""
    if not isinstance(paths, list):
        return None
    strokes: list[list[fitz.Point]] = []
    for stroke in paths:
        if not isinstance(stroke, list):
            continue
        points = [_parse_point(p, page_height, page_x0, page_y0) for p in stroke]
        points = [p for p in points if p]
        if len(points) >= 2:
            strokes.append(points)
    return strokes if strokes else None


def _parse_ink_list(ink_list: Any, page_height: float | None = None, page_x0: float = 0.0, page_y0: float = 0.0) -> list[list[fitz.Point]] | None:
    """[Flow: Step 1 (inkList 형태 확인) -> Step 2 (ink 항목별 points 변환)
          -> Step 3 (2점 이상 stroke만 반환)]"""
    if not isinstance(ink_list, list):
        return None
    strokes: list[list[fitz.Point]] = []
    for ink in ink_list:
        if not isinstance(ink, dict):
            continue
        points = [_parse_point(p, page_height, page_x0, page_y0) for p in ink.get("points", [])]
        points = [p for p in points if p]
        if len(points) >= 2:
            strokes.append(points)
    return strokes if strokes else None


def _page_rect_from_dimensions(page_dimensions: dict | None, page_no: int) -> fitz.Rect | None:
    """[Flow: Step 1 (page_dimensions dict에서 페이지 번호 조회)
          -> Step 2 (width/height/x0/y0로 fitz.Rect 생성) -> Step 3 (없으면 None)]"""
    if not page_dimensions:
        return None
    dims = page_dimensions.get(str(page_no)) or page_dimensions.get(page_no)
    if not isinstance(dims, dict):
        return None
    width = float(dims.get("width_pt", 0))
    height = float(dims.get("height_pt", 0))
    x0 = float(dims.get("x0", 0))
    y0 = float(dims.get("y0", 0))
    if width <= 0 or height <= 0:
        return None
    return fitz.Rect(x0, y0, x0 + width, y0 + height)


def _rect_to_canonical(rect: dict, page_rect: fitz.Rect, source_space: str) -> dict:
    """[Flow: Step 1 (source_space에 따라 canonical rect로 변환)]"""
    if source_space == "canonical":
        return dict(rect)
    if source_space == "device":
        return cac.device_rect_to_canonical(rect, page_rect.width, page_rect.height)
    if source_space == "pdf_user":
        return cac.pdf_user_rect_to_canonical(rect, page_rect)
    return dict(rect)


def _rect_from_canonical(rect: dict, page_rect: fitz.Rect, target_space: str) -> dict:
    """[Flow: Step 1 (canonical rect를 target_space로 변환)]"""
    if target_space == "canonical":
        return dict(rect)
    if target_space == "device":
        return cac.canonical_rect_to_device(rect, page_rect.width, page_rect.height)
    if target_space == "pdf_user":
        pdf_rect = cac.canonical_rect_to_pdf_user(rect, page_rect)
        return {
            "origin": {"x": pdf_rect.x0, "y": pdf_rect.y0},
            "size": {"width": pdf_rect.x1 - pdf_rect.x0, "height": pdf_rect.y1 - pdf_rect.y0},
        }
    return dict(rect)


def _point_to_canonical(point: dict, page_rect: fitz.Rect, source_space: str) -> dict:
    """[Flow: Step 1 (source_space point를 canonical point로 변환)]"""
    if source_space == "canonical":
        return dict(point)
    if source_space == "device":
        return cac.device_point_to_canonical(point, page_rect.width, page_rect.height)
    if source_space == "pdf_user":
        return cac.pdf_user_point_to_canonical(point, page_rect)
    return dict(point)


def _point_from_canonical(point: dict, page_rect: fitz.Rect, target_space: str) -> dict:
    """[Flow: Step 1 (canonical point를 target_space point로 변환)]"""
    if target_space == "canonical":
        return dict(point)
    if target_space == "device":
        return cac.canonical_point_to_device(point, page_rect.width, page_rect.height)
    if target_space == "pdf_user":
        pdf_point = cac.canonical_point_to_pdf_user(point, page_rect)
        return {"x": pdf_point.x, "y": pdf_point.y}
    return dict(point)


def _rd_to_canonical(rd: dict, page_rect: fitz.Rect, source_space: str) -> dict:
    """[Flow: Step 1 (rectangleDifferences를 canonical normalized inset으로 변환)]

    left/right는 page_width로, top/bottom은 page_height로 나눈다.
    """
    if source_space == "canonical":
        return dict(rd)
    left = float(rd.get("left", 0))
    right = float(rd.get("right", 0))
    top = float(rd.get("top", 0))
    bottom = float(rd.get("bottom", 0))
    if source_space in ("device", "pdf_user"):
        return {
            "left": left / page_rect.width,
            "right": right / page_rect.width,
            "top": top / page_rect.height,
            "bottom": bottom / page_rect.height,
        }
    return dict(rd)


def _rd_from_canonical(rd: dict, page_rect: fitz.Rect, target_space: str) -> dict:
    """[Flow: Step 1 (canonical rectangleDifferences를 target_space points로 변환)]"""
    if target_space == "canonical":
        return dict(rd)
    left = float(rd.get("left", 0))
    right = float(rd.get("right", 0))
    top = float(rd.get("top", 0))
    bottom = float(rd.get("bottom", 0))
    if target_space in ("device", "pdf_user"):
        return {
            "left": left * page_rect.width,
            "right": right * page_rect.width,
            "top": top * page_rect.height,
            "bottom": bottom * page_rect.height,
        }
    return dict(rd)


def _convert_annotation_item(
    raw: dict,
    page_rect: fitz.Rect,
    input_space: str,
    output_space: str,
) -> dict:
    """[Flow: Step 1 (annotation 객체 추출)
          -> Step 2 (rect/segmentRects/calloutLine/points/rectangleDifferences를 source_space에서 canonical로 변환)
          -> Step 3 (canonical에서 output_space로 변환)
          -> Step 4 (갱신된 annotation dict 반환)]

    device / pdf_user / canonical 간 모든 주석 좌표를 변환한다.
    """
    if input_space == output_space:
        return raw

    item = dict(raw)
    a = _extract_annotation(item) or item

    def _rect(r):
        if not isinstance(r, dict):
            return r
        canonical = _rect_to_canonical(r, page_rect, input_space)
        return _rect_from_canonical(canonical, page_rect, output_space)

    def _point(p):
        if not isinstance(p, dict):
            return p
        canonical = _point_to_canonical(p, page_rect, input_space)
        return _point_from_canonical(canonical, page_rect, output_space)

    def _rd(rd):
        if not isinstance(rd, dict):
            return rd
        canonical = _rd_to_canonical(rd, page_rect, input_space)
        return _rd_from_canonical(canonical, page_rect, output_space)

    if "rect" in a and isinstance(a["rect"], dict):
        a["rect"] = _rect(a["rect"])
    if "segmentRects" in a and isinstance(a["segmentRects"], list):
        a["segmentRects"] = [_rect(r) for r in a["segmentRects"] if isinstance(r, dict)]
    if "calloutLine" in a and isinstance(a["calloutLine"], list):
        a["calloutLine"] = [_point(p) for p in a["calloutLine"] if isinstance(p, dict)]
    if "start" in a and isinstance(a["start"], dict):
        a["start"] = _point(a["start"])
    if "end" in a and isinstance(a["end"], dict):
        a["end"] = _point(a["end"])
    if "rectangleDifferences" in a and isinstance(a["rectangleDifferences"], dict):
        a["rectangleDifferences"] = _rd(a["rectangleDifferences"])
    if "inkList" in a and isinstance(a["inkList"], list):
        a["inkList"] = [
            {
                **ink,
                "points": [_point(p) for p in ink.get("points", []) if isinstance(p, dict)],
            }
            for ink in a["inkList"]
            if isinstance(ink, dict)
        ]
    if "paths" in a and isinstance(a["paths"], list):
        a["paths"] = [
            [_point(p) for p in stroke if isinstance(p, dict)]
            for stroke in a["paths"]
            if isinstance(stroke, list)
        ]

    return item


def _convert_annotations_to_canonical(
    annotations: list[dict],
    pdf_bytes: bytes,
    input_space: str = "device",
) -> list[dict]:
    """[Flow: Step 1 (PDF 열기) -> Step 2 (페이지별 page_rect 캐시)
          -> Step 3 (각 annotation을 canonical로 변환) -> Step 4 (목록 반환)]"""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page_rects = {page.number + 1: page.rect for page in doc}
    finally:
        doc.close()

    converted: list[dict] = []
    for raw in annotations:
        a = _extract_annotation(raw)
        if not a:
            converted.append(raw)
            continue
        page_index = a.get("pageIndex")
        if not isinstance(page_index, int) or page_index < 0:
            converted.append(raw)
            continue
        page_no = page_index + 1
        page_rect = page_rects.get(page_no)
        if page_rect is None:
            converted.append(raw)
            continue
        converted.append(_convert_annotation_item(raw, page_rect, input_space, "canonical"))
    return converted


def _convert_annotations(
    annotations: list[dict],
    pdf_bytes: bytes,
    input_space: str,
    output_space: str,
) -> list[dict]:
    """[Flow: Step 1 (PDF 열기) -> Step 2 (페이지별 page_rect 캐시)
          -> Step 3 (annotation item을 input_space에서 output_space로 변환)
          -> Step 4 (목록 반환)]"""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page_rects = {page.number + 1: page.rect for page in doc}
    finally:
        doc.close()

    converted: list[dict] = []
    for raw in annotations:
        a = _extract_annotation(raw)
        if not a:
            converted.append(raw)
            continue
        page_index = a.get("pageIndex")
        if not isinstance(page_index, int) or page_index < 0:
            converted.append(raw)
            continue
        page_no = page_index + 1
        page_rect = page_rects.get(page_no)
        if page_rect is None:
            converted.append(raw)
            continue
        converted.append(_convert_annotation_item(raw, page_rect, input_space, output_space))
    return converted


def _convert_annotation_to_device_space(
    raw: dict,
    page_height: float,
    page_x0: float = 0.0,
    page_y0: float = 0.0,
) -> dict:
    """[Flow: Step 1 (PDF user-space annotation 수신) -> Step 2 (page rect 생성)
          -> Step 3 (embedpdf_rect_from_pdf_user / pdf_user_to_device_point로 변환)
          -> Step 4 (변환된 annotation 반환)]

    AI 백엔드가 보내는 PDF user-space 좌표를 embedpdf device-space로 변환한다.
    모든 좌표 변환은 pdf_coordinate_transform에서 matrix로 일원화 처리한다.
    """
    a = dict(raw)
    page_rect = fitz.Rect(page_x0, page_y0, page_x0 + page_height, page_y0 + page_height)

    def _pdf_rect_to_device(rect: Any) -> dict | None:
        if not rect:
            return None
        if isinstance(rect, (list, tuple)) and len(rect) >= 4:
            try:
                pdf_rect = fitz.Rect(*(float(v) for v in rect[:4]))
            except (ValueError, TypeError):
                return None
            return embedpdf_rect_from_pdf_user(pdf_rect, page_rect)
        if not isinstance(rect, dict):
            return None
        x = rect.get("x", rect.get("origin", {}).get("x"))
        y = rect.get("y", rect.get("origin", {}).get("y"))
        w = rect.get("width", rect.get("size", {}).get("width"))
        h = rect.get("height", rect.get("size", {}).get("height"))
        if x is None or y is None or w is None or h is None:
            return None
        try:
            x, y, w, h = float(x), float(y), float(w), float(h)
        except (ValueError, TypeError):
            return None
        pdf_rect = fitz.Rect(x, y, x + w, y + h)
        return embedpdf_rect_from_pdf_user(pdf_rect, page_rect)

    def _pdf_point_to_device(p: Any) -> dict | None:
        if not isinstance(p, dict):
            return None
        x = p.get("x")
        y = p.get("y")
        if x is None or y is None:
            return None
        try:
            device_point = pdf_user_to_device_point((float(x), float(y)), page_rect)
            return {"x": device_point.x, "y": device_point.y}
        except (ValueError, TypeError):
            return None

    if "rect" in a:
        converted = _pdf_rect_to_device(a["rect"])
        if converted:
            a["rect"] = converted
    if "segmentRects" in a and isinstance(a["segmentRects"], list):
        a["segmentRects"] = [(_pdf_rect_to_device(r) or r) for r in a["segmentRects"]]
    if "start" in a:
        converted = _pdf_point_to_device(a["start"])
        if converted:
            a["start"] = converted
    if "end" in a:
        converted = _pdf_point_to_device(a["end"])
        if converted:
            a["end"] = converted
    if "inkList" in a and isinstance(a["inkList"], list):
        a["inkList"] = [
            {
                **ink,
                "points": [(_pdf_point_to_device(p) or p) for p in ink.get("points", [])],
            }
            for ink in a["inkList"]
            if isinstance(ink, dict)
        ]
    if "paths" in a and isinstance(a["paths"], list):
        a["paths"] = [
            [(_pdf_point_to_device(p) or p) for p in stroke]
            for stroke in a["paths"]
            if isinstance(stroke, list)
        ]
    if "calloutLine" in a and isinstance(a["calloutLine"], list):
        a["calloutLine"] = [
            (_pdf_point_to_device(p) or p) for p in a["calloutLine"] if isinstance(p, dict)
        ]
    return a


def _convert_annotation_to_pdf_user(
    raw: dict,
    page_height: float,
    page_x0: float = 0.0,
    page_y0: float = 0.0,
) -> dict:
    """[Flow: Step 1 (embedpdf device-space annotation dict 추출) -> Step 2 (page rect 생성)
          -> Step 3 (pdf_user_rect_from_embedpdf / device_to_pdf_user_point으로 PDF user-space 변환)
          -> Step 4 (원본 형식 유지 반환)]

    embedpdf device-space 좌표(원점 좌상단, y↓)를 PDF user-space(원점 좌하단, y↑)로 역변환한다.
    AnnotationTransferItem({annotation: {...}}) 형식이면 원본 dict를 수정하고 그대로 반환한다.
    """
    a = _extract_annotation(raw)
    if not a:
        return raw

    page_rect = fitz.Rect(page_x0, page_y0, page_x0 + page_height, page_y0 + page_height)

    def _device_rect_to_pdf_user(rect: dict) -> dict:
        pdf_rect = pdf_user_rect_from_embedpdf(rect, page_rect)
        return {
            "origin": {"x": pdf_rect.x0, "y": pdf_rect.y0},
            "size": {"width": max(0.0, pdf_rect.x1 - pdf_rect.x0), "height": max(0.0, pdf_rect.y1 - pdf_rect.y0)},
        }

    def _device_point_to_pdf_user(p: dict) -> dict:
        pdf_point = device_to_pdf_user_point((p["x"], p["y"]), page_rect)
        return {"x": pdf_point.x, "y": pdf_point.y}

    if "rect" in a and isinstance(a["rect"], dict):
        a["rect"] = _device_rect_to_pdf_user(a["rect"])
    if "segmentRects" in a and isinstance(a["segmentRects"], list):
        a["segmentRects"] = [_device_rect_to_pdf_user(r) for r in a["segmentRects"] if isinstance(r, dict)]
    if "calloutLine" in a and isinstance(a["calloutLine"], list):
        a["calloutLine"] = [_device_point_to_pdf_user(p) for p in a["calloutLine"] if isinstance(p, dict)]
    return raw


def _convert_annotations_to_pdf_user(
    annotations: list[dict],
    pdf_bytes: bytes,
    input_space: str = "device",
) -> list[dict]:
    """[Flow: Step 1 (PDF 열기) -> Step 2 (페이지별 page_rect 캐시)
          -> Step 3 (주석을 PDF user-space로 변환) -> Step 4 (목록 반환)]

    저장된 device-space 또는 canonical 좌표를 AI 백엔드가 사용하는 PDF user-space로 변환한다.
    input_space가 "device"면 기존 embedpdf device-space, "canonical"이면 canonical normalized를,
    "pdf_user"면 아무 변환 없이 그대로 반환한다.
    """
    return _convert_annotations(annotations, pdf_bytes, input_space, "pdf_user")


def _convert_annotations_to_device_space(
    annotations: list[dict],
    pdf_bytes: bytes,
    input_space: str = "pdf_user",
) -> list[dict]:
    """[Flow: Step 1 (PDF 열기) -> Step 2 (페이지별 page_rect 캐시)
          -> Step 3 (주석을 embedpdf device-space로 변환) -> Step 4 (목록 반환)]

    AI 백엔드가 보내는 PDF user-space 또는 canonical 좌표를 embedpdf device-space로 변환한다.
    """
    return _convert_annotations(annotations, pdf_bytes, input_space, "device")


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


def _fitz_rect_to_embedpdf_rect(rect: fitz.Rect, page_height: float, page_x0: float = 0.0, page_y0: float = 0.0) -> dict:
    """[Flow: Step 1 (PyMuPDF Rect 수신) -> Step 2 (page rect 생성)
          -> Step 3 (embedpdf_rect_from_pdf_user로 y-flip/offset 변환)
          -> Step 4 (origin/size 형태 반환)]

    PyMuPDF Rect는 좌하단 원점, y가 위로 증가하는 PDF 좌표계를 사용한다.
    EmbedPDF는 origin이 좌상단, y가 아래로 증가하는 device-space 좌표계를 사용하므로
    pdf_coordinate_transform에서 matrix로 y-flip과 CropBox offset을 한 번에 처리한다.
    """
    page_rect = fitz.Rect(page_x0, page_y0, page_x0 + page_height, page_y0 + page_height)
    return embedpdf_rect_from_pdf_user(rect, page_rect)


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
        page_y0 = page.rect.y0
        page_y1 = page_height + page_y0
        for idx, annot in enumerate(page.annots()):
            try:
                annot_type = annot.type[0] if isinstance(annot.type, tuple) else annot.type
                embed_type = EMBEDPDF_TYPE_MAP.get(annot_type)
                if embed_type is None:
                    continue
                rect = cac.pdf_user_rect_to_canonical(annot.rect, page.rect)
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
                    # [Flow: PyMuPDF vertex는 PDF user-space(y↑) 좌표이므로 device-space(y↓)로 flip]
                    # _parse_point는 dict 입력을 기대하고 device→user-space 방향이므로,
                    # PyMuPDF vertex(tuple/Point, PDF user-space)에는 직접 변환 로직을 사용한다.
                    if annot.vertices and len(annot.vertices) >= 2:
                        v0 = annot.vertices[0]
                        v1 = annot.vertices[1]
                        # PyMuPDF 버전에 따라 tuple 또는 fitz.Point 반환
                        v0x, v0y = (float(v0[0]), float(v0[1])) if isinstance(v0, (tuple, list)) else (float(v0.x), float(v0.y))
                        v1x, v1y = (float(v1[0]), float(v1[1])) if isinstance(v1, (tuple, list)) else (float(v1.x), float(v1.y))
                        annotation["start"] = cac.pdf_user_point_to_canonical(fitz.Point(v0x, v0y), page.rect)
                        annotation["end"] = cac.pdf_user_point_to_canonical(fitz.Point(v1x, v1y), page.rect)
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
