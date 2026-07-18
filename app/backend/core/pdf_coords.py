#!/usr/bin/env python3
# [Flow: Step 1 (렌더링에 사용한 DPI 확인) -> Step 2 (픽셀 bbox를 PDF 포인트 bbox로 스케일 변환 + y축 flip)]
# PaddleOCR-VL은 PyMuPDF로 렌더링한 페이지 PNG(픽셀 좌표, y↓ 원점 좌상단)에서 bbox를 반환한다.
# PDF 좌표계는 y↑ 원점 좌하단이므로 단순 스케일 변환만 하면 y 좌표가 거울처럼 뒤집힌다.
# 따라서 page_height_px에서 pixel y를 빼서 y축을 flip한 뒤 스케일 변환해야 한다.
from __future__ import annotations

import fitz

from .ocr_layout import BBox
from .pdf_coordinate_transform import image_top_left_to_pdf_user

PDF_POINTS_PER_INCH = 72.0


def px_bbox_to_pdf_rect(
    bbox_px: BBox,
    dpi: int,
    page_height_px: float | None = None,
) -> tuple[float, float, float, float]:
    """픽셀 bbox(xmin,ymin,xmax,ymax)를 PDF 포인트 좌표로 변환한다.

    [Flow: Step 1 (DPI 유효성 검사) -> Step 2 (스케일 계산) -> Step 3 (y축 flip 여부 확인)
          -> Step 4 (픽셀 좌표를 PDF 포인트로 변환)]

    Args:
        bbox_px: OCR이 반환한 픽셀 단위 bbox (이미지 좌표계: y↓ 원점 좌상단)
        dpi: 해당 이미지를 렌더링할 때 사용한 DPI
        page_height_px: 이미지의 픽셀 높이. y축 flip에 필요.
            None이면 y-flip 없이 단순 스케일만 변환 (레거시 호환용, 권장하지 않음).

    Returns:
        (x0, y0, x1, y1) PDF 포인트 좌표 (PDF 좌표계: y↑ 원점 좌하단)
    """
    if dpi <= 0:
        raise ValueError(f"Invalid dpi: {dpi}")

    if page_height_px is not None and page_height_px > 0:
        # pdf_coordinate_transform이 단일 matrix로 이미지 좌표계(y↓) → PDF user-space(y↑) 변환을 처리한다.
        # page_rect.width는 실제 너비 대신 point 높이로 임시 설정해도 matrix에서 y1/x0만 사용하므로 무관하다.
        point_height = page_height_px * (PDF_POINTS_PER_INCH / dpi)
        page_rect = fitz.Rect(0, 0, point_height, point_height)
        pdf_rect = image_top_left_to_pdf_user(bbox_px, page_rect, dpi)
        return (pdf_rect.x0, pdf_rect.y0, pdf_rect.x1, pdf_rect.y1)

    # 레거시: y-flip 없이 단순 스케일만 변환
    scale = PDF_POINTS_PER_INCH / float(dpi)
    x0, y0, x1, y1 = bbox_px
    return (x0 * scale, y0 * scale, x1 * scale, y1 * scale)


def clamp_rect_to_page(
    rect: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float]:
    """변환된 rect가 페이지 범위를 벗어나지 않도록 clamp한다 (OCR bbox 경계 오차 방어)."""
    x0, y0, x1, y1 = rect
    x0 = max(0.0, min(x0, page_width))
    x1 = max(0.0, min(x1, page_width))
    y0 = max(0.0, min(y0, page_height))
    y1 = max(0.0, min(y1, page_height))
    if x1 <= x0:
        x1 = min(page_width, x0 + 1.0)
    if y1 <= y0:
        y1 = min(page_height, y0 + 1.0)
    return (x0, y0, x1, y1)
