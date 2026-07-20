#!/usr/bin/env python3
"""[Flow: Step 1 (canonical normalized 좌표계 정의)
      -> Step 2 (device / PDF user-space / canonical 간 변환 함수 제공)
      -> Step 3 (pdf_coordinate_transform.py의 matrix 함수 재사용)]

Annotation JSON을 "PDF/이미지 포인트에 독립적인 canonical normalized 공간"으로
저장하기 위한 변환 유틸리티.

좌표계 정의:
- canonical: (x_norm, y_norm, w_norm, h_norm) in [0, 1]. 원점은 좌상단, y는 아래로 증가.
- device-space: (x, y, w, h) in points. 원점 좌상단, y는 아래로 증가.
- PDF user-space: (x0, y0, x1, y1) in points. 원점 좌하단, y는 위로 증가.

page_rect는 fitz.Rect(page_x0, page_y0, page_x1, page_y1) 형태이며,
width = page_x1 - page_x0, height = page_y1 - page_y0를 사용한다.
width/height를 page_height로 잘못 사용하는 버그를 피하기 위해 fitz.Rect의
속성을 직접 활용한다.
"""
from __future__ import annotations

import fitz

from .pdf_coordinate_transform import (
    normalized_top_left_to_pdf_user,
    pdf_user_to_normalized_top_left,
)


def _rect_dict_to_fitz(rect: dict) -> fitz.Rect:
    """[Flow: Step 1 (origin/size 또는 x/y/width/height 형태 수용)
          -> Step 2 (fitz.Rect로 변환)]"""
    if not isinstance(rect, dict):
        raise ValueError("rect must be a dict")
    origin = rect.get("origin") or {}
    size = rect.get("size") or {}
    x = float(origin.get("x", rect.get("x", 0)))
    y = float(origin.get("y", rect.get("y", 0)))
    w = float(size.get("width", rect.get("width", 0)))
    h = float(size.get("height", rect.get("height", 0)))
    if w <= 0 or h <= 0:
        raise ValueError("rect width/height must be positive")
    return fitz.Rect(x, y, x + w, y + h)


def _fitz_rect_to_canonical_dict(rect: fitz.Rect) -> dict:
    """[Flow: Step 1 (fitz.Rect x0<y0 정규화 확인)
          -> Step 2 ({origin, size} canonical dict로 변환)]"""
    return {
        "origin": {"x": float(rect.x0), "y": float(rect.y0)},
        "size": {
            "width": float(rect.x1 - rect.x0),
            "height": float(rect.y1 - rect.y0),
        },
    }


def device_rect_to_canonical(rect: dict, page_width: float, page_height: float) -> dict:
    """[Flow: Step 1 (device-space rect 수신)
          -> Step 2 (page_width/height로 나누어 [0,1] canonical 좌표로 변환)
          -> Step 3 (canonical rect dict 반환)]

    device-space는 page_rect의 좌상단을 원점(0,0)으로, y는 아래로 증가한다.
    """
    if page_width <= 0 or page_height <= 0:
        raise ValueError("page_width and page_height must be positive")
    device = _rect_dict_to_fitz(rect)
    return {
        "origin": {
            "x": float(device.x0 / page_width),
            "y": float(device.y0 / page_height),
        },
        "size": {
            "width": float((device.x1 - device.x0) / page_width),
            "height": float((device.y1 - device.y0) / page_height),
        },
    }


def canonical_rect_to_device(rect: dict, page_width: float, page_height: float) -> dict:
    """[Flow: Step 1 (canonical rect 수신)
          -> Step 2 (page_width/height를 곱해 device-space points로 변환)
          -> Step 3 (device rect dict 반환)]
    """
    if page_width <= 0 or page_height <= 0:
        raise ValueError("page_width and page_height must be positive")
    canonical = _rect_dict_to_fitz(rect)
    return {
        "origin": {
            "x": float(canonical.x0 * page_width),
            "y": float(canonical.y0 * page_height),
        },
        "size": {
            "width": float((canonical.x1 - canonical.x0) * page_width),
            "height": float((canonical.y1 - canonical.y0) * page_height),
        },
    }


def pdf_user_rect_to_canonical(rect: dict | fitz.Rect | tuple, page_rect: fitz.Rect) -> dict:
    """[Flow: Step 1 (PDF user-space rect 수신)
          -> Step 2 (pdf_user_to_normalized_top_left로 canonical top-left rect 획득)
          -> Step 3 ({origin, size} canonical dict 반환)]"""
    if isinstance(rect, dict):
        pdf_rect = _rect_dict_to_fitz(rect)
    else:
        pdf_rect = fitz.Rect(rect)
    normalized = pdf_user_to_normalized_top_left(pdf_rect, page_rect)
    return _fitz_rect_to_canonical_dict(normalized)


def canonical_rect_to_pdf_user(rect: dict, page_rect: fitz.Rect) -> fitz.Rect:
    """[Flow: Step 1 (canonical rect dict를 fitz.Rect로 변환)
          -> Step 2 (normalized_top_left_to_pdf_user로 PDF user-space 변환)
          -> Step 3 (PDF user-space fitz.Rect 반환)]"""
    canonical = _rect_dict_to_fitz(rect)
    return normalized_top_left_to_pdf_user(canonical, page_rect)


def canonical_point_to_pdf_user(point: dict, page_rect: fitz.Rect) -> fitz.Point:
    """[Flow: Step 1 (canonical point 수신)
          -> Step 2 (page_rect.x0/width, y1/height로 PDF user-space 좌표 계산)
          -> Step 3 (fitz.Point 반환)]"""
    if not isinstance(point, dict):
        raise ValueError("point must be a dict")
    x = float(point.get("x", 0))
    y = float(point.get("y", 0))
    return fitz.Point(
        page_rect.x0 + x * page_rect.width,
        page_rect.y1 - y * page_rect.height,
    )


def pdf_user_point_to_canonical(point: dict | fitz.Point | tuple, page_rect: fitz.Rect) -> dict:
    """[Flow: Step 1 (PDF user-space point 수신)
          -> Step 2 (page_rect 기준으로 [0,1] canonical 좌표 계산)
          -> Step 3 ({x, y} dict 반환)]"""
    if isinstance(point, dict):
        x = float(point.get("x", 0))
        y = float(point.get("y", 0))
    else:
        x = float(point[0])
        y = float(point[1])
    return {
        "x": float((x - page_rect.x0) / page_rect.width),
        "y": float((page_rect.y1 - y) / page_rect.height),
    }


def device_point_to_canonical(point: dict, page_width: float, page_height: float) -> dict:
    """[Flow: Step 1 (device-space point 수신)
          -> Step 2 (page_width/height로 나누어 [0,1] canonical point 반환)]"""
    if not isinstance(point, dict):
        raise ValueError("point must be a dict")
    return {
        "x": float(point.get("x", 0)) / page_width,
        "y": float(point.get("y", 0)) / page_height,
    }


def canonical_point_to_device(point: dict, page_width: float, page_height: float) -> dict:
    """[Flow: Step 1 (canonical point 수신)
          -> Step 2 (page_width/height를 곱해 device-space point 반환)]"""
    if not isinstance(point, dict):
        raise ValueError("point must be a dict")
    return {
        "x": float(point.get("x", 0)) * page_width,
        "y": float(point.get("y", 0)) * page_height,
    }
