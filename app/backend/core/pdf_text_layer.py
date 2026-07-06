#!/usr/bin/env python3
# [Flow: Step 1 (이미지 기반 PDF와 OCR 결과 수신) -> Step 2 (페이지별 OCR 텍스트/bbox를 PDF 포인트 좌표로 변환)
#       -> Step 3 (PyMuPDF로 투명 텍스트 레이어 삽입) -> Step 4 (텍스트 레이어가 추가된 PDF bytes 반환)]
# 스캔 이미지 PDF 위에 PaddleOCR 결과를 투명 텍스트 레이어로 입혀 검색/선택 가능한 PDF를 만든다.
# AI 주석 생성 시 이 텍스트 레이어에서 직접 텍스트를 검색하면 bbox 변환 오차 없이 정확한 위치를 얻을 수 있다.
from __future__ import annotations

import logging
from typing import Any

import fitz  # PyMuPDF

from .ocr_layout import BBox
from .pdf_coords import clamp_rect_to_page, px_bbox_to_pdf_rect

logger = logging.getLogger(__name__)

# PyMuPDF built-in CJK 폰트 매핑. 별도 폰트 파일 없이 한/중/일 문자를 지원한다.
FONT_NAME_BY_LANGUAGE = {
    "ko": "korea",
    "ja": "japan",
    "zh": "china-ss",
    "zht": "china-ts",
    "en": "helv",
}
DEFAULT_FONT_NAME = "korea"

# 투명 텍스트를 위한 render_mode: 3 = neither fill nor stroke (보이지 않음)
INVISIBLE_RENDER_MODE = 3

# bbox 높이 대비 폰트 크기 비율. 너무 크면 가로 폭을 초과해 잘릴 수 있다.
FONT_SIZE_RATIO = 0.85
# 문자 폭 추정 비율 (폰트 크기 대비). CJK 문자 기준으로 대략 1.0, 영문은 0.6 정도.
CHAR_WIDTH_RATIO = 0.85
# baseline 조정: insert_text의 point y는 baseline이며, 텍스트 상단이 bbox 상단에 맞도록 baseline = y0 + font_size


def _normalize_rec_text(text: Any) -> str:
    """PaddleOCR rec_texts 항목에서 순수 텍스트를 추출한다.

    Args:
        text: OCR이 반환한 텍스트 (보통 str, 간혹 숫자 등)

    Returns:
        앞뒤 공백을 제거한 문자열
    """
    if not isinstance(text, str):
        text = str(text) if text is not None else ""
    return text.strip()


def _pick_font_name(language: str | None) -> str:
    """언어 코드에 맞는 PyMuPDF built-in 폰트 이름을 반환한다.

    Args:
        language: ko/ja/zh/zht/en 등 언어 코드

    Returns:
        PyMuPDF fontname 문자열
    """
    if not language:
        return DEFAULT_FONT_NAME
    normalized = language.lower().split("-")[0]
    return FONT_NAME_BY_LANGUAGE.get(normalized, DEFAULT_FONT_NAME)


def _insert_invisible_text(
    page: fitz.Page,
    text: str,
    rect: tuple[float, float, float, float],
    font_name: str,
) -> None:
    """주어진 bbox 안에 투명 텍스트를 삽입한다.

    Args:
        page: PyMuPDF Page 객체
        text: 삽입할 텍스트
        rect: (x0, y0, x1, y1) PDF 포인트 좌표
        font_name: PyMuPDF 폰트 이름
    """
    x0, y0, x1, y1 = rect
    width = x1 - x0
    height = y1 - y0
    if width <= 0 or height <= 0:
        return

    # bbox 높이에 맞춰 기본 폰트 크기를 결정한다.
    font_size = max(1.0, height * FONT_SIZE_RATIO)

    # 텍스트가 bbox 가로 폭을 넘지 않도록 폰트 크기를 축소한다.
    estimated_width = max(1, len(text)) * font_size * CHAR_WIDTH_RATIO
    if estimated_width > width:
        font_size = max(1.0, width / (max(1, len(text)) * CHAR_WIDTH_RATIO))

    # insert_text: point가 텍스트 baseline의 왼쪽 끝이다.
    # 텍스트 상단이 bbox 상단(y0)에 맞도록 baseline = y0 + font_size
    baseline_y = y0 + font_size

    # render_mode=3으로 보이지 않게 만든다. overlay=True로 이미지 위에 삽입하면 선택/검색이 잘 된다.
    try:
        page.insert_text(
            fitz.Point(x0, baseline_y),
            text,
            fontsize=font_size,
            fontname=font_name,
            render_mode=INVISIBLE_RENDER_MODE,
            overlay=True,
        )
    except Exception as e:
        logger.warning(f"[pdf_text_layer] 텍스트 레이어 삽입 실패 '{text[:20]}': {e}")


def add_text_layer_from_ocr(
    pdf_bytes: bytes,
    page_ocr_results: dict[int, list[tuple[str, BBox]]],
    dpi: int = 200,
    language: str | None = None,
) -> bytes:
    """이미지 기반 PDF에 PaddleOCR 결과를 투명 텍스트 레이어로 추가한다.

    [Flow: Step 1 (PDF 열기) -> Step 2 (페이지별 OCR 텍스트/bbox 순회)
          -> Step 3 (픽셀 bbox를 PDF 포인트 rect로 변환 및 clamp) -> Step 4 (투명 텍스트 삽입)
          -> Step 5 (PDF bytes 반환)]

    Args:
        pdf_bytes: 이미지 기반 PDF bytes
        page_ocr_results: page_no(1-based) -> [(text, bbox_px), ...]
        dpi: 이미지 렌더링 DPI (기본 200)
        language: 언어 코드 (ko/ja/zh/zht/en). None이면 기본 CJK 폰트 사용.

    Returns:
        텍스트 레이어가 추가된 PDF bytes
    """
    if not page_ocr_results:
        return pdf_bytes

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    font_name = _pick_font_name(language)

    for page in doc:
        page_no = page.number + 1
        items = page_ocr_results.get(page_no, [])
        if not items:
            continue

        page_width = page.rect.width
        page_height = page.rect.height

        for text, bbox_px in items:
            text = _normalize_rec_text(text)
            if not text:
                continue
            try:
                rect_pdf = px_bbox_to_pdf_rect(bbox_px, dpi=dpi)
            except Exception as e:
                logger.warning(f"[pdf_text_layer] page={page_no} bbox 변환 실패: {e}")
                continue

            rect = clamp_rect_to_page(rect_pdf, page_width, page_height)
            if rect[2] <= rect[0] or rect[3] <= rect[1]:
                continue

            _insert_invisible_text(page, text, rect, font_name)

    return doc.tobytes()


def extract_page_ocr_results_from_layout(
    layout_by_page: dict[int, dict],
) -> dict[int, list[tuple[str, BBox]]]:
    """PaddleOCR 서비스가 반환한 layout dict에서 페이지별 (text, bbox_px) 목록을 추출한다.

    [Flow: Step 1 (layout_by_page 순회) -> Step 2 (overall_ocr_res의 rec_texts/rec_boxes 추출)
          -> Step 3 (유효한 텍스트/bbox만 반환)]

    Args:
        layout_by_page: page_no(1-based) -> PaddleOCR layout dict (overall_ocr_res 포함)

    Returns:
        page_no -> [(text, bbox_px), ...]
    """
    results: dict[int, list[tuple[str, BBox]]] = {}
    for page_no, layout in layout_by_page.items():
        ocr_res = layout.get("overall_ocr_res") or {}
        if not isinstance(ocr_res, dict):
            continue
        texts = ocr_res.get("rec_texts") or []
        boxes = ocr_res.get("rec_boxes") or []
        if not isinstance(texts, list) or not isinstance(boxes, list):
            continue

        page_items: list[tuple[str, BBox]] = []
        for text, box in zip(texts, boxes):
            if not isinstance(box, (list, tuple)) or len(box) < 4:
                continue
            try:
                bbox_px: BBox = (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
            except (ValueError, TypeError):
                continue
            normalized_text = _normalize_rec_text(text)
            if normalized_text:
                page_items.append((normalized_text, bbox_px))
        if page_items:
            results[page_no] = page_items
    return results


class TextLayerSearcher:
    """텍스트 레이어가 추가된 PDF에서 텍스트를 검색하여 PDF 포인트 bbox를 반환한다."""

    def __init__(self, pdf_bytes: bytes):
        """텍스트 레이어 PDF를 연다.

        Args:
            pdf_bytes: 텍스트 레이어가 추가된 PDF bytes
        """
        self.doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    def search(self, page_no: int, text: str) -> list[tuple[float, float, float, float]]:
        """주어진 페이지에서 텍스트를 검색해 bbox 목록을 반환한다.

        Args:
            page_no: 1-based 페이지 번호
            text: 검색할 텍스트

        Returns:
            [(x0, y0, x1, y1), ...] PDF 포인트 좌표 목록
        """
        if not text or page_no < 1 or page_no > self.doc.page_count:
            return []
        page = self.doc[page_no - 1]
        rects = page.search_for(text)
        return [(r.x0, r.y0, r.x1, r.y1) for r in rects]

    def close(self) -> None:
        """PDF 문서를 닫는다."""
        if self.doc:
            self.doc.close()
            self.doc = None
