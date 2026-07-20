#!/usr/bin/env python3
# [Flow: Step 1 (이미지 기반 PDF와 OCR 결과 수신) -> Step 2 (페이지별 OCR 텍스트/bbox를 PDF 포인트 좌표로 변환)
#       -> Step 3 (PyMuPDF로 투명 텍스트 레이어 삽입) -> Step 4 (텍스트 레이어가 추가된 PDF bytes 반환)]
# 스캔 이미지 PDF 위에 PaddleOCR 결과를 투명 텍스트 레이어로 입혀 검색/선택 가능한 PDF를 만든다.
# AI 주석 생성 시 이 텍스트 레이어에서 직접 텍스트를 검색하면 bbox 변환 오차 없이 정확한 위치를 얻을 수 있다.
from __future__ import annotations

import logging
import re
from html import unescape
from typing import Any

import fitz  # PyMuPDF

from .ocr_layout import BBox
from .pdf_coordinate_transform import normalized_top_left_to_pdf_user

PDF_POINTS_PER_INCH = 72.0

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


def _strip_html_tags(content: str) -> str:
    """table 블록의 HTML 태그를 제거하고 순수 텍스트만 남긴다.

    Args:
        content: OCR이 반환한 table 블록의 HTML 문자열

    Returns:
        HTML 태그와 HTML 엔티티를 제거하고 연속 공백을 정리한 문자열
    """
    text = re.sub(r"<[^>]+>", " ", content)
    text = unescape(text)
    return " ".join(text.split())


def _extract_table_row_items(content: str, bbox: BBox) -> list[tuple[str, BBox]]:
    """table 블록의 HTML을 행(<tr>) 단위로 파싱하여 (text, row_bbox) 목록을 반환한다.

    [Flow: Step 1 (<tr> 태그로 행 분할) -> Step 2 (각 행의 <td>/<th> 셀 텍스트 추출)
          -> Step 3 (표 bbox를 행 수만큼 y축으로 균등 분할) -> Step 4 (각 행의 텍스트와 분할된 bbox 반환)]

    표 전체 텍스트를 하나의 bbox에 몰아넣으면 폰트가 너무 작아져 텍스트 선택이 불가능하다.
    행 단위로 분할하면 각 행의 텍스트가 해당 행 영역에 들어가 폰트 크기가 합리적으로 유지되고,
    사용자가 표의 특정 행을 드래그하여 텍스트를 선택할 수 있다.

    Args:
        content: table 블록의 HTML 문자열
        bbox: 표 전체 bbox (x0, y0, x1, y1)

    Returns:
        [(행 텍스트, 행 bbox), ...]. <tr>이 없으면 통째로 하나의 텍스트로 반환.
    """
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", content, re.DOTALL | re.IGNORECASE)
    if not rows:
        text = _strip_html_tags(content)
        if text:
            return [(text, bbox)]
        return []

    row_texts: list[str] = []
    for row_html in rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.DOTALL | re.IGNORECASE)
        cell_texts = [_strip_html_tags(c) for c in cells]
        cell_texts = [c for c in cell_texts if c]
        if cell_texts:
            row_texts.append(" | ".join(cell_texts))

    if not row_texts:
        text = _strip_html_tags(content)
        if text:
            return [(text, bbox)]
        return []

    # 표 bbox를 행 수만큼 y축으로 균등 분할한다.
    x0, y0, x1, y1 = bbox[:4]
    row_height = (y1 - y0) / len(row_texts)
    items: list[tuple[str, BBox]] = []
    for i, text in enumerate(row_texts):
        row_y0 = y0 + i * row_height
        row_y1 = y0 + (i + 1) * row_height
        items.append((text, (x0, row_y0, x1, row_y1)))
    return items


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

    [Flow: Step 1 (bbox 크기 확인) -> Step 2 (폰트 크기 산정: bbox 높이와 가로 폭 모두 고려)
          -> Step 3 (텍스트가 가로 폭을 넘으면 폰트 축소, 그래도 넘으면 단어 단위 줄바꿈)
          -> Step 4 (각 줄을 insert_text로 render_mode=3 투명 삽입)]

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
    # width의 90%만 사용하여 CJK/영문 혼용 시의 폭 추정 오차 여유를 둔다.
    safe_width = width * 0.9
    estimated_width = max(1, len(text)) * font_size * CHAR_WIDTH_RATIO
    if estimated_width > safe_width:
        font_size = max(1.0, safe_width / (max(1, len(text)) * CHAR_WIDTH_RATIO))

    # 축소 후에도 텍스트가 가로 폭을 넘으면 단어 단위로 줄바꿈하여 여러 줄로 삽입한다.
    estimated_width = max(1, len(text)) * font_size * CHAR_WIDTH_RATIO
    if estimated_width > width:
        words = text.split()
        if not words:
            return
        lines: list[str] = []
        current_line: list[str] = []
        current_width = 0.0
        for word in words:
            word_width = max(1, len(word)) * font_size * CHAR_WIDTH_RATIO
            if current_width + word_width > width and current_line:
                lines.append(" ".join(current_line))
                current_line = [word]
                current_width = word_width
            else:
                current_line.append(word)
                current_width += word_width
        if current_line:
            lines.append(" ".join(current_line))
        try:
            for i, line in enumerate(lines):
                baseline_y = y0 + (i + 1) * font_size
                if baseline_y > y1:
                    break
                page.insert_text(
                    fitz.Point(x0, baseline_y),
                    line,
                    fontsize=font_size,
                    fontname=font_name,
                    render_mode=INVISIBLE_RENDER_MODE,
                    overlay=True,
                )
        except Exception as e:
            logger.warning(f"[pdf_text_layer] 줄바꿈 텍스트 삽입 실패 '{text[:20]}': {e}")
        return

    # 단줄 텍스트: insert_text로 효율적으로 삽입.
    # insert_text: point가 텍스트 baseline의 왼쪽 끝이다.
    # 텍스트 상단이 bbox 상단(y0)에 맞도록 baseline = y0 + font_size
    baseline_y = y0 + font_size
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


def _convert_bbox_to_pdf_user(
    bbox: BBox,
    page_rect: fitz.Rect,
    layout: dict[str, Any],
    dpi: float,
) -> fitz.Rect | None:
    """[Flow: Step 1 (bbox가 이미 PDF user-space인지 확인)
          -> Step 2 (0~1 normalized면 PDF user-space로 변환)
          -> Step 3 (픽셀/points top-left면 source 크기로 정규화 후 PDF user-space로 변환)
          -> Step 4 (PDF user-space fitz.Rect 반환)]

    OCR 레이아웃의 bbox는 normalized(0~1, y=0 상단), points top-left, 또는
    픽셀 top-left 좌표계로 들어올 수 있다. coordinate_system 메타데이터가 없어도
    layout의 width/height를 이용해 안전하게 PDF user-space(y=0 하단, y↑)로 변환한다.
    """
    if not bbox or len(bbox) < 4:
        return None

    try:
        x0, y0, x1, y1 = (float(v) for v in bbox[:4])
    except (ValueError, TypeError):
        return None

    coordinate_system = layout.get("_coordinate_system")

    # 이미 PDF user-space면 그대로 사용한다.
    if coordinate_system == "pdf_user_space":
        return fitz.Rect(x0, y0, x1, y1)

    # 명시적으로 normalized이거나 모든 값이 0~1 범위면 normalized로 간주한다.
    is_normalized = (
        coordinate_system == "normalized"
        or all(0.0 <= v <= 1.01 for v in (x0, y0, x1, y1))
    )

    if is_normalized:
        try:
            return normalized_top_left_to_pdf_user((x0, y0, x1, y1), page_rect)
        except Exception as e:
            logger.warning(f"[pdf_text_layer] normalized bbox 변환 실패: {e}")
            return None

    # normalized가 아니면 top-left points/pixel 좌표로 취급한다.
    # layout에 source 크기가 있으면 우선 사용하고, 없으면 PDF 페이지 크기 + dpi로 추정한다.
    source_width = layout.get("width") or layout.get("_page_width_px")
    source_height = layout.get("height") or layout.get("_page_height_px")
    if not source_width or not source_height:
        source_width = page_rect.width * dpi / PDF_POINTS_PER_INCH
        source_height = page_rect.height * dpi / PDF_POINTS_PER_INCH

    try:
        source_width = float(source_width)
        source_height = float(source_height)
    except (ValueError, TypeError):
        return None

    if source_width <= 0 or source_height <= 0:
        return None

    # top-left 좌표를 0~1 normalized로 변환한 뒤 PDF user-space로 변환한다.
    nx0 = x0 / source_width
    ny0 = y0 / source_height
    nx1 = x1 / source_width
    ny1 = y1 / source_height
    try:
        return normalized_top_left_to_pdf_user((nx0, ny0, nx1, ny1), page_rect)
    except Exception as e:
        logger.warning(f"[pdf_text_layer] pixel/points bbox 변환 실패: {e}")
        return None


def _insert_text_layer_into_doc(
    doc: fitz.Document,
    page_ocr_results: dict[int, list[tuple[str, BBox]]],
    layout_by_page: dict[int, dict] | None,
    language: str | None,
    dpi: float = 300.0,
) -> None:
    """[Flow: Step 1 (문서의 각 페이지 순회)
          -> Step 2 (_convert_bbox_to_pdf_user로 bbox를 PDF user-space로 변환)
          -> Step 3 (페이지 경계 내로 clamp) -> Step 4 (투명 텍스트 삽입)]"""
    font_name = _pick_font_name(language)

    for page in doc:
        page_no = page.number + 1
        items = page_ocr_results.get(page_no, [])
        if not items:
            continue

        page_rect = page.rect
        layout = (layout_by_page or {}).get(page_no, {})

        for text, bbox_pdf in items:
            text = _normalize_rec_text(text)
            if not text:
                continue
            if not bbox_pdf or len(bbox_pdf) < 4:
                continue

            ocr_rect = _convert_bbox_to_pdf_user(bbox_pdf, page_rect, layout, dpi)
            if not ocr_rect:
                continue

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
) -> bytes:
    """이미지 기반 PDF에 PaddleOCR 결과를 투명 텍스트 레이어로 추가한다.

    [Flow: Step 1 (PDF 열기) -> Step 2 (페이지별 OCR 텍스트/bbox 순회)
          -> Step 3 (layout coordinate_system 확인: normalized면 PDF user-space로 변환)
          -> Step 4 (페이지 경계 내에 맞춤) -> Step 5 (투명 텍스트 삽입)
          -> Step 6 (PDF bytes 반환)]

    Args:
        pdf_bytes: 이미지 기반 PDF bytes
        page_ocr_results: page_no(1-based) -> [(text, bbox_pdf), ...]
            좌표계는 normalized(0~1, y=0 상단) 또는 points/pixel top-left(y=0 상단)일 수 있다.
            layout_by_page에 width/height가 있으면 이를 이용해 PDF user-space로 변환한다.
        dpi: 이미지 렌더링 DPI (기본 300). pixel 좌표 변환 시 page 크기 추정에 사용한다.
        language: 언어 코드 (ko/ja/zh/zht/en). None이면 기본 CJK 폰트 사용.
        layout_by_page: page_no -> PaddleOCR layout dict.
            coordinate_system="normalized" 또는 width/height를 참조해 PDF user-space로 변환한다.

    Returns:
        텍스트 레이어가 추가된 PDF bytes
    """
    if not page_ocr_results:
        return pdf_bytes

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        _insert_text_layer_into_doc(doc, page_ocr_results, layout_by_page, language, dpi=dpi)
        return doc.tobytes()
    finally:
        doc.close()


# 텍스트가 포함될 수 있는 block_label 집합 (ocr_layout.py와 동일 기준).
# image/figure 등 텍스트가 없는 블록은 searchable PDF 텍스트 레이어에서도 제외한다.
_TEXT_BLOCK_LABELS_FOR_TEXT_LAYER = {
    "text", "title", "figure_title", "seal", "header", "footer", "reference", "formula",
    "paragraph_title", "table",
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
    표(table) 블록은 HTML을 행(<tr>) 단위로 파싱하여 각 행의 텍스트를 표 bbox를
    행 수만큼 분할한 영역에 각각 삽입한다.
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
        try:
            bbox_px: BBox = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        except (ValueError, TypeError):
            continue
        # table 블록은 HTML을 행 단위로 파싱하여 각 행의 텍스트를 분할된 bbox에 삽입한다.
        if block_label == "table":
            table_items = _extract_table_row_items(content, bbox_px)
            items.extend(table_items)
            continue
        text = content.strip()
        if not text:
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
