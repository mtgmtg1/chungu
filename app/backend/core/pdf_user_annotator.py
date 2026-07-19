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

# 주석 JSON에 좌표계 기준을 기록하는 메타데이터 키
COORDINATE_CONTEXT_KEY = "_coordinate_context"


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


def _extract_page_dimensions_from_pdf_bytes(pdf_bytes: bytes) -> dict[str, dict]:
    """[Flow: Step 1 (PDF bytes를 fitz 문서로 열기)
          -> Step 2 (페이지별 rect 추출)
          -> Step 3 (width/height/x0/y0/rotation dict로 반환)]

    주석 좌표 변환에 사용할 page rect 메타데이터를 1-based page_no 문자열 키로 반환한다.
    """
    page_dimensions: dict[str, dict] = {}
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for page in doc:
            rect = page.rect
            page_dimensions[str(page.number + 1)] = {
                "width": float(rect.width),
                "height": float(rect.height),
                "x0": float(rect.x0),
                "y0": float(rect.y0),
                "rotation": int(page.rotation),
            }
    finally:
        doc.close()
    return page_dimensions


def _build_coordinate_context(
    pdf_storage_path: str,
    bucket: str,
    page_dimensions: dict[str, dict],
    input_space: str,
) -> dict:
    """[Flow: Step 1 (좌표 기준 PDF 경로/버킷/페이지 크기/좌표계 수신)
          -> Step 2 (_coordinate_context dict 조립)
          -> Step 3 (반환)]

    AnnotationTransferItem에 첨부될 좌표계 컨텍스트 메타데이터를 생성한다.
    """
    return {
        "pdf_storage_path": pdf_storage_path,
        "bucket": bucket,
        "page_dimensions": page_dimensions,
        "input_space": input_space,
    }


def _attach_coordinate_context(
    annotations: list[dict],
    context: dict,
    overwrite: bool = True,
) -> list[dict]:
    """[Flow: Step 1 (주석 목록 수신) -> Step 2 (각 항목 루트에 _coordinate_context 설정)
          -> Step 3 (목록 반환)]

    각 AnnotationTransferItem 루트 dict에 좌표계 컨텍스트를 추가한다.
    overwrite=False이면 기존 _coordinate_context가 있는 항목은 덮어쓰지 않는다.
    """
    for item in annotations:
        if not isinstance(item, dict):
            continue
        if not overwrite and COORDINATE_CONTEXT_KEY in item:
            continue
        item[COORDINATE_CONTEXT_KEY] = context
    return annotations


def _get_coordinate_context(item: Any) -> dict | None:
    """[Flow: Step 1 (AnnotationTransferItem 수신) -> Step 2 (루트의 _coordinate_context 추출)
          -> Step 3 (dict 또는 None 반환)]"""
    if not isinstance(item, dict):
        return None
    context = item.get(COORDINATE_CONTEXT_KEY)
    if isinstance(context, dict):
        return context
    return None


def _get_pdf_bytes_for_context(
    context: dict,
    cache: dict[tuple[str, str], bytes] | None = None,
) -> bytes | None:
    """[Flow: Step 1 (컨텍스트에서 pdf_storage_path/bucket 추출)
          -> Step 2 (cache 확인) -> Step 3 (Supabase Storage 다운로드)
          -> Step 4 (실패 시 반대 bucket 폴백) -> Step 5 (cache 저장 및 bytes 반환)]

    _coordinate_context에 기록된 PDF Storage 경로로부터 bytes를 다운로드한다.
    """
    pdf_storage_path = context.get("pdf_storage_path")
    if not pdf_storage_path:
        return None
    bucket = context.get("bucket") or "pdfs"
    cache_key = (bucket, pdf_storage_path)
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    # lazy import: core 모듈을 단독으로 임포트하는 테스트에서 top-level circular import를 피한다.
    try:
        from . import supabase_client
    except ImportError:
        from backend.core import supabase_client

    client = supabase_client.get_service_client()
    data: bytes | None = None
    for try_bucket in (bucket, "results" if bucket != "results" else "pdfs"):
        try:
            data = client.storage.from_(try_bucket).download(pdf_storage_path)
            if data:
                break
        except Exception:
            continue
    if data is None:
        logger.warning(f"[_get_pdf_bytes_for_context] PDF 다운로드 실패: {bucket}/{pdf_storage_path}")
        return None
    if cache is not None:
        cache[cache_key] = data
    return data


def _get_page_rect_from_context(context: dict, page_no: int) -> fitz.Rect | None:
    """[Flow: Step 1 (컨텍스트의 page_dimensions 확인)
          -> Step 2 (해당 page_no의 width/height/x0/y0로 fitz.Rect 생성)
          -> Step 3 (fitz.Rect 또는 None 반환)]"""
    page_dimensions = context.get("page_dimensions")
    if not isinstance(page_dimensions, dict):
        return None
    dims = page_dimensions.get(str(page_no))
    if not isinstance(dims, dict):
        return None
    width = dims.get("width")
    height = dims.get("height")
    if width is None or height is None:
        return None
    x0 = dims.get("x0", 0.0)
    y0 = dims.get("y0", 0.0)
    return fitz.Rect(float(x0), float(y0), float(x0) + float(width), float(y0) + float(height))


def _get_page_rect_for_annotation(
    item: Any,
    fallback_dimensions: dict[int, dict] | None = None,
) -> fitz.Rect | None:
    """[Flow: Step 1 (annotation의 pageIndex 확인)
          -> Step 2 (item의 _coordinate_context에서 page rect 조회)
          -> Step 3 (없으면 fallback_dimensions에서 조회)
          -> Step 4 (fitz.Rect 또는 None 반환)]"""
    a = _extract_annotation(item)
    if not a:
        return None
    page_index = a.get("pageIndex")
    if not isinstance(page_index, int) or page_index < 0:
        return None
    page_no = page_index + 1

    context = _get_coordinate_context(item)
    if context:
        rect = _get_page_rect_from_context(context, page_no)
        if rect is not None:
            return rect

    if fallback_dimensions and page_no in fallback_dimensions:
        dims = fallback_dimensions[page_no]
        width = dims.get("width")
        height = dims.get("height")
        if width is not None and height is not None:
            x0 = dims.get("x0", 0.0)
            y0 = dims.get("y0", 0.0)
            return fitz.Rect(float(x0), float(y0), float(x0) + float(width), float(y0) + float(height))
    return None


def _parse_rect(
    rect: Any,
    page_height: float | None = None,
    page_x0: float = 0.0,
    page_y0: float = 0.0,
    page_width: float | None = None,
) -> fitz.Rect | None:
    """[Flow: Step 1 (EmbedPDF rect 형태 확인) -> Step 2 (origin/size 또는 x/y/width/height 추출)
          -> Step 3 (pdf_user_rect_from_embedpdf로 device-space → PDF user-space 변환)
          -> Step 4 (fitz.Rect 반환)]

    EmbedPDF rect는 device-space(원점 좌상단, y↓) 좌표를 사용한다.
    PyMuPDF는 PDF user-space(원점 좌하단, y↑)를 사용하므로 Y축 flip이 필요하다.
    좌표 변환은 pdf_coordinate_transform에서 matrix로 일원화 처리한다.
    page_height가 None이면 flip 없이 원래 좌표를 그대로 사용한다 (PyMuPDF vertex 등 PDF 좌표계 입력용).
    page_width가 주어지지 않으면 page_height를 사용한다 (하위 호환).
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

    if page_width is None:
        page_width = page_height

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

    page_rect = fitz.Rect(page_x0, page_y0, page_x0 + page_width, page_y0 + page_height)
    return pdf_user_rect_from_embedpdf(device_rect, page_rect)


def _segment_rects_to_rect(
    segment_rects: Any,
    page_height: float | None = None,
    page_x0: float = 0.0,
    page_y0: float = 0.0,
    page_width: float | None = None,
) -> fitz.Rect | None:
    """[Flow: Step 1 (segmentRects 배열 확인) -> Step 2 (첫 번째 rect를 fitz.Rect로 변환)
          -> Step 3 (하나라도 실패하면 None 반환)]"""
    if not isinstance(segment_rects, list) or not segment_rects:
        return None
    first = segment_rects[0]
    return _parse_rect(first, page_height, page_x0, page_y0, page_width)


def _parse_point(
    point: Any,
    page_height: float | None = None,
    page_x0: float = 0.0,
    page_y0: float = 0.0,
    page_width: float | None = None,
) -> fitz.Point | None:
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
    if page_width is None:
        page_width = page_height
    page_rect = fitz.Rect(page_x0, page_y0, page_x0 + page_width, page_y0 + page_height)
    return device_to_pdf_user_point((x, y), page_rect)


def _parse_paths(
    paths: Any,
    page_height: float | None = None,
    page_x0: float = 0.0,
    page_y0: float = 0.0,
    page_width: float | None = None,
) -> list[list[fitz.Point]] | None:
    """[Flow: Step 1 (list 형태 확인) -> Step 2 (stroke별 point 변환) -> Step 3 (2점 이상 stroke만 반환)]"""
    if not isinstance(paths, list):
        return None
    strokes: list[list[fitz.Point]] = []
    for stroke in paths:
        if not isinstance(stroke, list):
            continue
        points = [_parse_point(p, page_height, page_x0, page_y0, page_width) for p in stroke]
        points = [p for p in points if p]
        if len(points) >= 2:
            strokes.append(points)
    return strokes if strokes else None


def _parse_ink_list(
    ink_list: Any,
    page_height: float | None = None,
    page_x0: float = 0.0,
    page_y0: float = 0.0,
    page_width: float | None = None,
) -> list[list[fitz.Point]] | None:
    """[Flow: Step 1 (inkList 형태 확인) -> Step 2 (ink 항목별 points 변환)
          -> Step 3 (2점 이상 stroke만 반환)]"""
    if not isinstance(ink_list, list):
        return None
    strokes: list[list[fitz.Point]] = []
    for ink in ink_list:
        if not isinstance(ink, dict):
            continue
        points = [_parse_point(p, page_height, page_x0, page_y0, page_width) for p in ink.get("points", [])]
        points = [p for p in points if p]
        if len(points) >= 2:
            strokes.append(points)
    return strokes if strokes else None


def _convert_annotation_to_device_space(
    raw: dict,
    page_height: float,
    page_x0: float = 0.0,
    page_y0: float = 0.0,
    page_width: float | None = None,
) -> dict:
    """[Flow: Step 1 (PDF user-space annotation 수신) -> Step 2 (page rect 생성)
          -> Step 3 (embedpdf_rect_from_pdf_user / pdf_user_to_device_point로 변환)
          -> Step 4 (변환된 annotation 반환)]

    AI 백엔드가 보내는 PDF user-space 좌표를 embedpdf device-space로 변환한다.
    모든 좌표 변환은 pdf_coordinate_transform에서 matrix로 일원화 처리한다.
    """
    a = dict(raw)
    if page_width is None:
        page_width = page_height
    page_rect = fitz.Rect(page_x0, page_y0, page_x0 + page_width, page_y0 + page_height)

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
    page_width: float | None = None,
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

    if page_width is None:
        page_width = page_height
    page_rect = fitz.Rect(page_x0, page_y0, page_x0 + page_width, page_y0 + page_height)

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
    pdf_bytes: bytes | None,
) -> list[dict]:
    """[Flow: Step 1 (fallback PDF bytes에서 페이지 크기 캐시)
          -> Step 2 (각 annotation의 _coordinate_context 또는 fallback에서 page rect 확보)
          -> Step 3 (device-space → PDF user-space 변환) -> Step 4 (변환된 목록 반환)]

    저장된 embedpdf device-space 좌표를 AI 백엔드가 생성하는 PDF user-space 좌표계로 일괄 역변환한다.
    각 주석의 _coordinate_context가 있으면 해당 PDF 기준, 없으면 fallback pdf_bytes 기준으로 변환한다.
    """
    fallback_dimensions: dict[int, dict] = {}
    if pdf_bytes:
        for page_no_str, dims in _extract_page_dimensions_from_pdf_bytes(pdf_bytes).items():
            try:
                fallback_dimensions[int(page_no_str)] = dims
            except ValueError:
                continue

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

        page_rect = _get_page_rect_for_annotation(raw, fallback_dimensions)
        if page_rect is None:
            converted.append(raw)
            continue
        _convert_annotation_to_pdf_user(
            raw,
            page_rect.height,
            page_rect.x0,
            page_rect.y0,
            page_rect.width,
        )
        converted.append(raw)
    return converted


def _convert_annotations_to_device_space(
    annotations: list[dict],
    pdf_bytes: bytes | None,
) -> list[dict]:
    """[Flow: Step 1 (fallback PDF bytes에서 페이지 크기 캐시)
          -> Step 2 (각 annotation의 _coordinate_context 또는 fallback에서 page rect 확보)
          -> Step 3 (PDF user-space → device-space 변환) -> Step 4 (변환된 목록 반환)]

    AI 백엔드가 보내는 PDF user-space 좌표를 embedpdf device-space로 일괄 변환한다.
    각 주석의 _coordinate_context가 있으면 해당 PDF 기준, 없으면 fallback pdf_bytes 기준으로 변환한다.
    """
    fallback_dimensions: dict[int, dict] = {}
    if pdf_bytes:
        for page_no_str, dims in _extract_page_dimensions_from_pdf_bytes(pdf_bytes).items():
            try:
                fallback_dimensions[int(page_no_str)] = dims
            except ValueError:
                continue

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

        page_rect = _get_page_rect_for_annotation(raw, fallback_dimensions)
        if page_rect is None:
            converted.append(raw)
            continue
        converted_a = _convert_annotation_to_device_space(
            a,
            page_rect.height,
            page_rect.x0,
            page_rect.y0,
            page_rect.width,
        )
        if "annotation" in raw and isinstance(raw["annotation"], dict):
            raw["annotation"] = converted_a
            converted.append(raw)
        else:
            converted.append(converted_a)
    return converted


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


def _fitz_rect_to_embedpdf_rect(
    rect: fitz.Rect,
    page_height: float,
    page_x0: float = 0.0,
    page_y0: float = 0.0,
    page_width: float | None = None,
) -> dict:
    """[Flow: Step 1 (PyMuPDF Rect 수신) -> Step 2 (page rect 생성)
          -> Step 3 (embedpdf_rect_from_pdf_user로 y-flip/offset 변환)
          -> Step 4 (origin/size 형태 반환)]

    PyMuPDF Rect는 좌하단 원점, y가 위로 증가하는 PDF 좌표계를 사용한다.
    EmbedPDF는 origin이 좌상단, y가 아래로 증가하는 device-space 좌표계를 사용하므로
    pdf_coordinate_transform에서 matrix로 y-flip과 CropBox offset을 한 번에 처리한다.
    """
    if page_width is None:
        page_width = page_height
    page_rect = fitz.Rect(page_x0, page_y0, page_x0 + page_width, page_y0 + page_height)
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
        page_width = page.rect.width
        page_y0 = page.rect.y0
        page_y1 = page_height + page_y0
        for idx, annot in enumerate(page.annots()):
            try:
                annot_type = annot.type[0] if isinstance(annot.type, tuple) else annot.type
                embed_type = EMBEDPDF_TYPE_MAP.get(annot_type)
                if embed_type is None:
                    continue
                rect = _fitz_rect_to_embedpdf_rect(annot.rect, page_height, page.rect.x0, page_y0, page_width)
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
                        annotation["start"] = {"x": v0x - page.rect.x0, "y": page_y1 - v0y}
                        annotation["end"] = {"x": v1x - page.rect.x0, "y": page_y1 - v1y}
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
