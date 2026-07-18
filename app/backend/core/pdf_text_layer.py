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
from .pdf_coords import clamp_rect_to_page
from .pdf_coordinate_transform import normalized_top_left_to_pdf_user

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


def _flip_pdf_user_rect_vertically(rect: fitz.Rect, page_rect: fitz.Rect) -> fitz.Rect:
    """[Flow: Step 1 (PDF user-space rect 수신)
          -> Step 2 (페이지 중심 y = (y0 + y1) / 2를 기준으로 y축 반전)
          -> Step 3 (뒤집힌 fitz.Rect 반환)]

    OCR 좌표계가 실제로는 PDF user-space(y↑)였을 때, top-left normalized 변환을
    거치면 상하가 반대로 계산된다. 이 함수는 PDF user-space rect를 페이지 세로축
    중심으로 뒤집어 올바른 위치를 복원한다.
    """
    mid_y = page_rect.y0 + page_rect.y1
    return fitz.Rect(rect.x0, mid_y - rect.y1, rect.x1, mid_y - rect.y0)


def _rect_iou(a: fitz.Rect, b: fitz.Rect) -> float:
    """[Flow: Step 1 (두 fitz.Rect 교차) -> Step 2 (교차 영역 / 합집합 영역)
          -> Step 3 (IoU 반환)]"""
    if not a or not b:
        return 0.0
    inter = a & b
    if not inter or inter.is_empty or inter.is_infinite:
        return 0.0
    union = a | b
    if not union or union.is_empty or union.is_infinite or union.get_area() <= 0:
        return 0.0
    return inter.get_area() / union.get_area()


def _detect_flip_with_canary(
    pdf_bytes: bytes,
    page_ocr_results: dict[int, list[tuple[str, BBox]]],
    layout_by_page: dict[int, dict] | None,
) -> bool:
    """[Flow: Step 1 (원본 PDF에서 ground truth 텍스트 한 개 선택)
          -> Step 2 (해당 텍스트의 원본 bbox와 OCR bbox를 PDF user-space로 변환)
          -> Step 3 (두 변환 방향 중 ground truth와 더 잘 겹치는 쪽 선택)
          -> Step 4 (파일 전체에 적용할 flip_y 플래그 반환)]

    원본 PDF에 동일 텍스트가 있는 페이지 하나를 canary로 삼아,
    OCR bbox가 원본 텍스트 위치와 일치하는지 검증한다.
    모든 페이지는 같은 PDF/같은 OCR 변환 경로를 공유하므로 파일당 1개 페이지만 검증해도 된다.
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        logger.warning(f"[pdf_text_layer] canary PDF 열기 실패: {e}")
        return False

    try:
        for page_no, items in page_ocr_results.items():
            if page_no < 1 or page_no > doc.page_count:
                continue
            page = doc[page_no - 1]
            for text, bbox in items:
                text = _normalize_rec_text(text)
                if not text or len(text) < 2:
                    continue
                if not bbox or len(bbox) < 4:
                    continue

                ground_truth_rects = page.search_for(text)
                if not ground_truth_rects:
                    continue

                layout = (layout_by_page or {}).get(page_no, {})
                coordinate_system = layout.get("_coordinate_system")
                page_width_px = layout.get("_page_width_px")
                page_height_px = layout.get("_page_height_px")
                is_normalized = coordinate_system == "normalized" and page_width_px and page_height_px

                try:
                    if is_normalized:
                        ocr_rect = normalized_top_left_to_pdf_user(bbox, page.rect)
                    else:
                        ocr_rect = fitz.Rect(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
                except Exception:
                    continue

                flipped_rect = _flip_pdf_user_rect_vertically(ocr_rect, page.rect)

                best_standard = max((_rect_iou(ocr_rect, gt) for gt in ground_truth_rects), default=0.0)
                best_flipped = max((_rect_iou(flipped_rect, gt) for gt in ground_truth_rects), default=0.0)

                logger.info(
                    f"[pdf_text_layer] canary page={page_no} text='{text[:20]}' "
                    f"standard_iou={best_standard:.3f} flipped_iou={best_flipped:.3f}"
                )

                if best_flipped > best_standard and best_flipped > 0.3:
                    return True
                return False
    finally:
        doc.close()

    return False


def _insert_text_layer_into_doc(
    doc: fitz.Document,
    page_ocr_results: dict[int, list[tuple[str, BBox]]],
    layout_by_page: dict[int, dict] | None,
    language: str | None,
    flip_y: bool = False,
) -> None:
    """[Flow: Step 1 (문서의 각 페이지 순회)
          -> Step 2 (layout coordinate_system 확인)
          -> Step 3 (normalized_top_left_to_pdf_user로 PDF user-space 변환)
          -> Step 4 (flip_y=True면 페이지 세로축 중심으로 y-flip)
          -> Step 5 (페이지 경계 내로 clamp) -> Step 6 (투명 텍스트 삽입)]"""
    font_name = _pick_font_name(language)

    for page in doc:
        page_no = page.number + 1
        items = page_ocr_results.get(page_no, [])
        if not items:
            continue

        page_rect = page.rect
        layout = (layout_by_page or {}).get(page_no, {})
        coordinate_system = layout.get("_coordinate_system")
        page_width_px = layout.get("_page_width_px")
        page_height_px = layout.get("_page_height_px")
        is_normalized = coordinate_system == "normalized" and page_width_px and page_height_px

        for text, bbox_pdf in items:
            text = _normalize_rec_text(text)
            if not text:
                continue
            if not bbox_pdf or len(bbox_pdf) < 4:
                continue

            try:
                if is_normalized:
                    ocr_rect = normalized_top_left_to_pdf_user(bbox_pdf, page_rect)
                else:
                    ocr_rect = fitz.Rect(float(bbox_pdf[0]), float(bbox_pdf[1]), float(bbox_pdf[2]), float(bbox_pdf[3]))
            except Exception as e:
                logger.warning(f"[pdf_text_layer] bbox 변환 실패 '{text[:20]}': {e}")
                continue

            if flip_y:
                ocr_rect = _flip_pdf_user_rect_vertically(ocr_rect, page_rect)

            # 페이지 경계 내로 clamp. CropBox/MediaBox offset도 자동 처리.
            clamped_rect = ocr_rect & page_rect
            if not clamped_rect or clamped_rect.is_empty or clamped_rect.is_infinite:
                continue

            _insert_invisible_text(page, text, (clamped_rect.x0, clamped_rect.y0, clamped_rect.x1, clamped_rect.y1), font_name)


def add_text_layer_from_ocr(
    pdf_bytes: bytes,
    page_ocr_results: dict[int, list[tuple[str, BBox]]],
    dpi: int = 300,
    language: str | None = None,
    layout_by_page: dict[int, dict] | None = None,
    force_flip_y: bool | None = None,
) -> bytes:
    """이미지 기반 PDF에 PaddleOCR 결과를 투명 텍스트 레이어로 추가한다.

    [Flow: Step 1 (canary 페이지 1개로 OCR y-flip 여부 검증)
          -> Step 2 (PDF 열기) -> Step 3 (페이지별 OCR 텍스트/bbox 순회)
          -> Step 4 (layout coordinate_system 확인: normalized면 PDF user-space로 변환)
          -> Step 5 (flip_y 플래그 적용) -> Step 6 (페이지 경계 내에 맞춤)
          -> Step 7 (투명 텍스트 삽입) -> Step 8 (PDF bytes 반환)]

    Args:
        pdf_bytes: 이미지 기반 PDF bytes
        page_ocr_results: page_no(1-based) -> [(text, bbox_pdf), ...]
            paddleocr_service에서 normalized(0~1, y=0 상단) 또는 PDF user-space(y↑)
            좌표로 정규화된 bbox일 수 있다.
        dpi: 이미지 렌더링 DPI (기본 300). 현재는 좌표계 변환에 사용하지 않지만
            하위 호환을 위해 시그니처를 유지한다.
        language: 언어 코드 (ko/ja/zh/zht/en). None이면 기본 CJK 폰트 사용.
        layout_by_page: page_no -> PaddleOCR layout dict.
            coordinate_system="normalized"이면 page_width_px/height_px를 참조해
            PDF user-space로 변환한다.
        force_flip_y: True/False로 강제할 수 있다. None이면 canary 1페이지 검증 결과를 사용한다.

    Returns:
        텍스트 레이어가 추가된 PDF bytes
    """
    if not page_ocr_results:
        return pdf_bytes

    if force_flip_y is None:
        flip_y = _detect_flip_with_canary(pdf_bytes, page_ocr_results, layout_by_page)
    else:
        flip_y = force_flip_y

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        _insert_text_layer_into_doc(doc, page_ocr_results, layout_by_page, language, flip_y)
        return doc.tobytes()
    finally:
        doc.close()


# 텍스트가 포함될 수 있는 block_label 집합 (ocr_layout.py와 동일 기준).
# image/figure 등 텍스트가 없는 블록은 searchable PDF 텍스트 레이어에서도 제외한다.
_TEXT_BLOCK_LABELS_FOR_TEXT_LAYER = {
    "text", "title", "figure_title", "seal", "header", "footer", "reference", "formula",
}


def _extract_items_from_overall_ocr_res(layout: dict) -> list[tuple[str, BBox]]:
    """overall_ocr_res에서 (text, bbox) 목록을 추출한다 (구 스키마 호환).

    [Flow: Step 1 (overall_ocr_res 확인) -> Step 2 (rec_texts/rec_boxes 병렬 순회) -> Step 3 (유효한 항목만 반환)]

    Returns:
        [(text, bbox_px), ...]. overall_ocr_res가 없거나 형식이 맞지 않으면 빈 리스트.
    """
    ocr_res = layout.get("overall_ocr_res") or {}
    if not isinstance(ocr_res, dict):
        return []
    texts = ocr_res.get("rec_texts") or []
    boxes = ocr_res.get("rec_boxes") or []
    if not isinstance(texts, list) or not isinstance(boxes, list):
        return []

    items: list[tuple[str, BBox]] = []
    for text, box in zip(texts, boxes):
        if not isinstance(box, (list, tuple)) or len(box) < 4:
            continue
        try:
            bbox_px: BBox = (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
        except (ValueError, TypeError):
            continue
        normalized_text = _normalize_rec_text(text)
        if normalized_text:
            items.append((normalized_text, bbox_px))
    return items


def _extract_items_from_parsing_res_list(layout: dict) -> list[tuple[str, BBox]]:
    """parsing_res_list에서 (text, bbox) 목록을 추출한다 (신 스키마 폴백).

    [Flow: Step 1 (parsing_res_list 순회) -> Step 2 (텍스트 블록만 필터링) -> Step 3 (block_content/block_bbox 추출) -> Step 4 (유효한 항목만 반환)]

    AI Studio API가 overall_ocr_res를 더 이상 반환하지 않는 경우, parsing_res_list의
    텍스트 블록(block_content + block_bbox)을 사용해 텍스트 레이어를 생성한다.
    표(table) 블록은 block_content가 HTML이므로 제외한다.
    """
    blocks = layout.get("parsing_res_list") or []
    if not isinstance(blocks, list):
        return []

    items: list[tuple[str, BBox]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_label = block.get("block_label", "text")
        if block_label not in _TEXT_BLOCK_LABELS_FOR_TEXT_LAYER:
            continue
        bbox = block.get("block_bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
            continue
        content = block.get("block_content", "")
        if not isinstance(content, str):
            content = str(content) if content else ""
        text = content.strip()
        if not text:
            continue
        try:
            bbox_px: BBox = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        except (ValueError, TypeError):
            continue
        items.append((text, bbox_px))
    return items


def extract_page_ocr_results_from_layout(
    layout_by_page: dict[int, dict],
) -> dict[int, list[tuple[str, BBox]]]:
    """PaddleOCR 서비스가 반환한 layout dict에서 페이지별 (text, bbox_px) 목록을 추출한다.

    [Flow: Step 1 (layout_by_page 순회) -> Step 2 (overall_ocr_res 우선 시도, 없으면 parsing_res_list 폴백)
          -> Step 3 (유효한 텍스트/bbox만 반환)]

    Args:
        layout_by_page: page_no(1-based) -> PaddleOCR layout dict

    Returns:
        page_no -> [(text, bbox_px), ...]
    """
    results: dict[int, list[tuple[str, BBox]]] = {}
    for page_no, layout in layout_by_page.items():
        if not isinstance(layout, dict):
            continue
        # 구 스키마: overall_ocr_res에서 단어 단위 추출 (좀 더 정밀한 bbox)
        page_items = _extract_items_from_overall_ocr_res(layout)
        # 신 스키마 폴백: overall_ocr_res가 없으면 parsing_res_list에서 블록 단위 추출
        if not page_items:
            page_items = _extract_items_from_parsing_res_list(layout)
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

        [Flow: Step 1 (전체 텍스트 검색) -> Step 2 (실패 시 첫 줄로 검색)
              -> Step 3 (실패 시 단어 단위 검색) -> Step 4 (모든 매칭 rect를 합친 bbox 반환)]

        Args:
            page_no: 1-based 페이지 번호
            text: 검색할 텍스트

        Returns:
            [(x0, y0, x1, y1), ...] PDF 포인트 좌표 목록
        """
        if not text or page_no < 1 or page_no > self.doc.page_count:
            return []
        page = self.doc[page_no - 1]

        # Step 1: 전체 텍스트로 검색
        rects = page.search_for(text)
        if rects:
            return [(r.x0, r.y0, r.x1, r.y1) for r in rects]

        # Step 2: 멀티라인 텍스트인 경우 첫 줄로 검색
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if len(lines) > 1:
            rects = page.search_for(lines[0])
            if rects:
                return [(r.x0, r.y0, r.x1, r.y1) for r in rects]

        # Step 3: 첫 줄도 실패하면 의미있는 첫 단어로 검색
        words = text.replace("\n", " ").split()
        if words:
            # 2글자 이상 단어 사용 (1글자는 너무 많은 매칭 발생)
            for word in words:
                if len(word) >= 2:
                    rects = page.search_for(word)
                    if rects:
                        return [(r.x0, r.y0, r.x1, r.y1) for r in rects]
                    break

        return []

    def search_all_pages(
        self,
        text: str,
        page_range: list[int] | None = None,
    ) -> list[tuple[int, list[tuple[float, float, float, float]]]]:
        """[Flow: Step 1 (검색 대상 페이지 번호 결정) -> Step 2 (각 페이지에서 전체 텍스트 검색)
              -> Step 3 (매칭된 페이지별 bbox 목록 반환)]

        텍스트 레이어 PDF의 모든 페이지(또는 지정한 페이지 범위)에서 동일한 텍스트를 검색한다.
        한 페이지에서 동일한 텍스트가 여러 번 나타나면 해당 페이지에 대한 bbox 목록에 모두 포함된다.

        Args:
            text: 검색할 텍스트
            page_range: 1-based 페이지 번호 리스트. None이면 전체 페이지를 검색한다.

        Returns:
            [(page_no, [(x0, y0, x1, y1), ...]), ...] 형태의 매칭 결과 목록
        """
        if not text or not text.strip():
            return []

        page_numbers = page_range if page_range else list(range(1, self.doc.page_count + 1))
        results: list[tuple[int, list[tuple[float, float, float, float]]]] = []
        for page_no in page_numbers:
            if page_no < 1 or page_no > self.doc.page_count:
                continue
            rects = self.search(page_no, text)
            if rects:
                results.append((page_no, rects))
        return results

    def close(self) -> None:
        """PDF 문서를 닫는다."""
        if self.doc:
            self.doc.close()
            self.doc = None
