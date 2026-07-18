#!/usr/bin/env python3
"""[Flow: Step 1 (PDF/이미지/device 좌표계를 Matrix로 정의)
      -> Step 2 (fitz.Matrix로 한 곳에서 모든 y-flip/스케일 변환 수행)
      -> Step 3 (다른 모듈은 이 함수만 호출하여 좌표계 변환)]

PDF 주석/검색 파이프라인에서 사용하는 좌표계:
- normalized_top_left: 0~1, y=0이 상단, y=1이 하단.
- image_top_left: 픽셀, y=0이 상단, y↓.
- pdf_user_space: PDF point, y=0이 하단(CropBox 기준), y↑.
- device_space: EmbedPDF/화면, 원점 좌상단, y↓. 페이지 MediaBox/CropBox의 x0/y1을 기준으로 상대좌표.

y-flip이 코드 곳곳에 흩어지면 실수로 좌표계를 두 번 뒤집는 버그가 생긴다.
이 모듈은 모든 변환을 fitz.Matrix로 한 곳에서 정의하고, 필요한 곳에서 재사용한다.
"""
from __future__ import annotations

import fitz


def _page_rect_to_normalized_matrix(page_rect: fitz.Rect) -> fitz.Matrix:
    """[Flow: Step 1 (page_rect.width/height 추출)
          -> Step 2 (PDF user-space -> normalized_top_left 변환 행렬 생성)]"""
    return fitz.Matrix(
        1.0 / page_rect.width, 0.0,
        0.0, -1.0 / page_rect.height,
        -page_rect.x0 / page_rect.width, page_rect.y1 / page_rect.height,
    )


def _normalized_to_page_rect_matrix(page_rect: fitz.Rect) -> fitz.Matrix:
    """[Flow: Step 1 (page_rect.width/height 추출)
          -> Step 2 (normalized_top_left -> PDF user-space 변환 행렬 생성)]"""
    return fitz.Matrix(
        page_rect.width, 0.0,
        0.0, -page_rect.height,
        page_rect.x0, page_rect.y1,
    )


def _image_to_page_rect_matrix(page_rect: fitz.Rect, dpi: float) -> fitz.Matrix:
    """[Flow: Step 1 (scale = PDF_POINTS_PER_INCH / dpi 계산)
          -> Step 2 (image_top_left -> PDF user-space 변환 행렬 생성)]"""
    scale = 72.0 / dpi
    return fitz.Matrix(
        scale, 0.0,
        0.0, -scale,
        page_rect.x0, page_rect.y1,
    )


def _page_rect_to_image_matrix(page_rect: fitz.Rect, dpi: float) -> fitz.Matrix:
    """[Flow: Step 1 (scale = PDF_POINTS_PER_INCH / dpi 계산)
          -> Step 2 (PDF user-space -> image_top_left 변환 행렬 생성)]"""
    scale = 72.0 / dpi
    return fitz.Matrix(
        1.0 / scale, 0.0,
        0.0, -1.0 / scale,
        -page_rect.x0 / scale, page_rect.y1 / scale,
    )


def _pdf_user_to_device_matrix(page_rect: fitz.Rect) -> fitz.Matrix:
    """[Flow: Step 1 (page_rect.x0/y1 추출)
          -> Step 2 (PDF user-space -> device_space 변환 행렬 생성)]"""
    return fitz.Matrix(
        1.0, 0.0,
        0.0, -1.0,
        -page_rect.x0, page_rect.y1,
    )


def _device_to_pdf_user_matrix(page_rect: fitz.Rect) -> fitz.Matrix:
    """[Flow: Step 1 (page_rect.x0/y1 추출)
          -> Step 2 (device_space -> PDF user-space 변환 행렬 생성)]"""
    return fitz.Matrix(
        1.0, 0.0,
        0.0, -1.0,
        page_rect.x0, page_rect.y1,
    )


def _apply_matrix(rect: fitz.Rect | tuple[float, float, float, float] | None, matrix: fitz.Matrix) -> fitz.Rect | None:
    """[Flow: Step 1 (입력을 fitz.Rect로 변환) -> Step 2 (matrix 곱셈)
          -> Step 3 (정규화된 fitz.Rect 반환)]"""
    if rect is None:
        return None
    if isinstance(rect, (list, tuple)):
        if len(rect) < 4:
            return None
        rect = fitz.Rect(float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
    transformed = rect * matrix
    # fitz.Rect는 x0<x1, y0<y1로 자동 정규화된다.
    return fitz.Rect(transformed)


def normalized_top_left_to_pdf_user(
    rect: fitz.Rect | tuple[float, float, float, float],
    page_rect: fitz.Rect,
) -> fitz.Rect:
    """[Flow: Step 1 (normalized_top_left rect 수신)
          -> Step 2 (_normalized_to_page_rect_matrix로 변환)
          -> Step 3 (PDF user-space fitz.Rect 반환)]"""
    result = _apply_matrix(rect, _normalized_to_page_rect_matrix(page_rect))
    if result is None:
        raise ValueError("normalized_top_left_to_pdf_user: invalid rect")
    return result


def pdf_user_to_normalized_top_left(
    rect: fitz.Rect | tuple[float, float, float, float],
    page_rect: fitz.Rect,
) -> fitz.Rect:
    """[Flow: Step 1 (PDF user-space rect 수신)
          -> Step 2 (_page_rect_to_normalized_matrix로 변환)
          -> Step 3 (normalized_top_left fitz.Rect 반환)]"""
    result = _apply_matrix(rect, _page_rect_to_normalized_matrix(page_rect))
    if result is None:
        raise ValueError("pdf_user_to_normalized_top_left: invalid rect")
    return result


def image_top_left_to_pdf_user(
    rect: fitz.Rect | tuple[float, float, float, float],
    page_rect: fitz.Rect,
    dpi: float,
) -> fitz.Rect:
    """[Flow: Step 1 (image_top_left rect 수신)
          -> Step 2 (_image_to_page_rect_matrix로 변환)
          -> Step 3 (PDF user-space fitz.Rect 반환)]"""
    result = _apply_matrix(rect, _image_to_page_rect_matrix(page_rect, dpi))
    if result is None:
        raise ValueError("image_top_left_to_pdf_user: invalid rect")
    return result


def pdf_user_to_image_top_left(
    rect: fitz.Rect | tuple[float, float, float, float],
    page_rect: fitz.Rect,
    dpi: float,
) -> fitz.Rect:
    """[Flow: Step 1 (PDF user-space rect 수신)
          -> Step 2 (_page_rect_to_image_matrix로 변환)
          -> Step 3 (image_top_left fitz.Rect 반환)]"""
    result = _apply_matrix(rect, _page_rect_to_image_matrix(page_rect, dpi))
    if result is None:
        raise ValueError("pdf_user_to_image_top_left: invalid rect")
    return result


def pdf_user_to_device(
    rect: fitz.Rect | tuple[float, float, float, float],
    page_rect: fitz.Rect,
) -> fitz.Rect:
    """[Flow: Step 1 (PDF user-space rect 수신)
          -> Step 2 (_pdf_user_to_device_matrix로 변환)
          -> Step 3 (device_space fitz.Rect 반환; y=0이 상단, y값 증가=아래)]"""
    result = _apply_matrix(rect, _pdf_user_to_device_matrix(page_rect))
    if result is None:
        raise ValueError("pdf_user_to_device: invalid rect")
    return result


def device_to_pdf_user(
    rect: fitz.Rect | tuple[float, float, float, float],
    page_rect: fitz.Rect,
) -> fitz.Rect:
    """[Flow: Step 1 (device_space rect 수신)
          -> Step 2 (_device_to_pdf_user_matrix로 변환)
          -> Step 3 (PDF user-space fitz.Rect 반환)]"""
    result = _apply_matrix(rect, _device_to_pdf_user_matrix(page_rect))
    if result is None:
        raise ValueError("device_to_pdf_user: invalid rect")
    return result


def pdf_user_to_device_point(
    point: fitz.Point | tuple[float, float],
    page_rect: fitz.Rect,
) -> fitz.Point:
    """[Flow: Step 1 (PDF user-space point 수신)
          -> Step 2 (_pdf_user_to_device_matrix로 변환)
          -> Step 3 (device_space fitz.Point 반환)]"""
    matrix = _pdf_user_to_device_matrix(page_rect)
    if isinstance(point, (list, tuple)):
        point = fitz.Point(float(point[0]), float(point[1]))
    return point * matrix


def device_to_pdf_user_point(
    point: fitz.Point | tuple[float, float],
    page_rect: fitz.Rect,
) -> fitz.Point:
    """[Flow: Step 1 (device_space point 수신)
          -> Step 2 (_device_to_pdf_user_matrix로 변환)
          -> Step 3 (PDF user-space fitz.Point 반환)]"""
    matrix = _device_to_pdf_user_matrix(page_rect)
    if isinstance(point, (list, tuple)):
        point = fitz.Point(float(point[0]), float(point[1]))
    return point * matrix


def embedpdf_rect_from_pdf_user(
    pdf_rect: fitz.Rect | tuple[float, float, float, float],
    page_rect: fitz.Rect,
) -> dict:
    """[Flow: Step 1 (PDF user-space rect를 device_space으로 변환)
          -> Step 2 (origin.y = top, size.height = height로 EmbedPDF rect dict 생성)]"""
    device = pdf_user_to_device(pdf_rect, page_rect)
    return {
        "origin": {"x": device.x0, "y": device.y0},
        "size": {"width": max(0.0, device.x1 - device.x0), "height": max(0.0, device.y1 - device.y0)},
    }


def pdf_user_rect_from_embedpdf(
    embedpdf_rect: dict,
    page_rect: fitz.Rect,
) -> fitz.Rect:
    """[Flow: Step 1 (EmbedPDF rect dict를 device_space rect로 변환)
          -> Step 2 (device_to_pdf_user로 PDF user-space fitz.Rect 반환)]"""
    if not isinstance(embedpdf_rect, dict):
        raise ValueError("pdf_user_rect_from_embedpdf: expected dict")
    origin = embedpdf_rect.get("origin") or {}
    size = embedpdf_rect.get("size") or {}
    x = float(origin.get("x", embedpdf_rect.get("x", 0)))
    y = float(origin.get("y", embedpdf_rect.get("y", 0)))
    w = float(size.get("width", embedpdf_rect.get("width", 0)))
    h = float(size.get("height", embedpdf_rect.get("height", 0)))
    device = fitz.Rect(x, y, x + w, y + h)
    return device_to_pdf_user(device, page_rect)
