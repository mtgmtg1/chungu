#!/usr/bin/env python3
# [Flow: Step 1 (렌더링에 사용한 DPI 확인) -> Step 2 (픽셀 bbox를 PDF 포인트 bbox로 스케일 변환)]
# PaddleOCR-VL은 PyMuPDF로 렌더링한 페이지 PNG(픽셀 좌표)에서 bbox를 반환한다.
# 하이라이트/여백 주석 기능은 이 픽셀 bbox를 동일한 fitz.Page 객체에 주석으로 추가해야 하므로
# 렌더링에 사용한 zoom(=dpi/72)의 역수로 스케일만 되돌리면 된다. (회전은 페이지를 직접 렌더링한
# fitz.Page.get_pixmap()이 이미 반영하므로 별도 회전 행렬 계산이 필요 없다.)
from __future__ import annotations

from .ocr_layout import BBox

PDF_POINTS_PER_INCH = 72.0


def px_bbox_to_pdf_rect(bbox_px: BBox, dpi: int) -> tuple[float, float, float, float]:
    """픽셀 bbox(xmin,ymin,xmax,ymax)를 PDF 포인트 좌표로 변환한다.

    Args:
        bbox_px: OCR이 반환한 픽셀 단위 bbox
        dpi: 해당 이미지를 렌더링할 때 사용한 DPI (예: paddleocr_service._pdf_to_images 기본 200)

    Returns:
        (x0, y0, x1, y1) PDF 포인트 좌표
    """
    if dpi <= 0:
        raise ValueError(f"Invalid dpi: {dpi}")
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
