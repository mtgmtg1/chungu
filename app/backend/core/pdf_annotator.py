#!/usr/bin/env python3
# [Flow: Step 1 (AnnotationTarget 목록 수신) -> Step 2 (페이지별 시각적 크기 캡처)
#       -> Step 3 (callout 텍스트 박스를 기존 요소를 피해 빈 모서리/외곽 여백에 배치)
#       -> Step 4 (대상 요소 -> knee -> 텍스트 박스 연결점으로 calloutLine 계산)
#       -> Step 5 (EmbedPDF AnnotationTransferItem[] 배열 생성 — HIGHLIGHT + FreeTextCallout)
#       -> Step 6 (프론트 importAnnotations()로 직접 로드 가능한 JSON 반환)]
#
# 과거에는 페이지 우측에 mediabox를 확장해 여백 컬럼을 추가한 뒤 FREETEXT 박스를 배치했지만,
# JSON 오버레이 방식으로 전환하면서 mediabox 확장이 빠져 여백 박스가 페이지 밖에 떠 있어
# 보이지 않는 문제가 있었다. 이제 embedpdf의 FreeTextCallout(텍스트 박스 + 화살표 리더 라인)을
# 사용해 페이지 내 빈 영역에 주석을 배치하고 화살표로 원본 요소를 가리킨다.
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import fitz  # PyMuPDF

from .pdf_coordinate_transform import (
    embedpdf_rect_from_pdf_user,
    pdf_user_rect_from_embedpdf,
    pdf_user_to_device_point,
)
from . import canonical_annotation_coords as cac

logger = logging.getLogger(__name__)

# --- callout 텍스트 박스 크기/스타일 상수 ---
CALLOUT_TEXTBOX_WIDTH_PT = 160.0  # 텍스트 박스 고정 너비 (포인트)
CALLOUT_TEXTBOX_MIN_HEIGHT_PT = 16.0  # 최소 높이 (텍스트 1줄)
CALLOUT_TEXTBOX_MAX_HEIGHT_PT = 120.0  # 최대 높이 (약 10줄)
CALLOUT_TEXTBOX_FONT_SIZE = 8
CALLOUT_TEXTBOX_LINE_HEIGHT_PT = 11.0  # 줄 높이 (폰트 크기의 ~1.35배)
CALLOUT_TEXTBOX_PADDING_V_PT = 8.0  # 상하 패딩 합계
CALLOUT_TEXTBOX_INNER_WIDTH_PT = CALLOUT_TEXTBOX_WIDTH_PT - 12  # 좌우 6pt 여백 → 실제 텍스트 영역

# --- callout 배치 상수 ---
CALLOUT_PAGE_EDGE_PADDING_PT = 12.0  # 페이지 가장자리에서 텍스트 박스까지 최소 여유
CALLOUT_COLLISION_MARGIN_PT = 4.0  # 충돌 검사 시 기존 요소 bbox 주변 여유
CALLOUT_KNEE_MIN_OFFSET_PT = 10.0  # knee가 텍스트 박스에 너무 가까울 때 최소 오프셋

# --- callout 스타일 ---
CALLOUT_STROKE_WIDTH = 1.0
CALLOUT_LINE_ENDING_OPEN_ARROW = 4  # PdfAnnotationLineEnding.OpenArrow
CALLOUT_TEXTBOX_BG_COLOR = "#FFFFFF"
CALLOUT_TEXTBOX_FONT_COLOR = "#333333"

DEFAULT_HIGHLIGHT_COLOR = (1.0, 0.92, 0.3)  # 형광펜 노랑
DEFAULT_CALLOUT_COLOR = (0.65, 0.35, 0.95)  # 보라색 (사용자 색상 요청이 없을 때 callout 기본색)
DEFAULT_OPACITY = 0.5  # 하이라이트/callout 공통 기본 투명도 (50%)


@dataclass
class AnnotationTarget:
    """[Flow: Step 1 (하이라이트/callout 대상 데이터 정의) -> Step 2 (선택적 검색 결과 rects 보관)]

    하이라이트/callout 공용 대상 하나.
    단일 bbox_pdf만 있으면 단순 bbox로 주석을 생성하고,
    search_rects_pdf가 추가되면 한 주석의 segmentRects를 여러 rect로 구성할 수 있다.
    """

    page_no: int  # 1-based
    bbox_pdf: tuple[float, float, float, float]  # (x0, y0, x1, y1), 시각적(렌더링된 이미지 기준) PDF 포인트 좌표
    comment: str
    color: tuple[float, float, float] = DEFAULT_HIGHLIGHT_COLOR
    # callout 리더 라인/텍스트 박스 테두리 색. None이면 DEFAULT_CALLOUT_COLOR(보라) 사용.
    # 사용자가 명시적으로 색을 요청한 경우에만 이 필드를 설정한다.
    callout_color: tuple[float, float, float] | None = None
    # 하이라이트/callout 투명도 (0.0=완전 투명, 1.0=완전 불투명).
    # None이면 DEFAULT_OPACITY(0.5) 사용. 사용자가 투명도를 요청한 경우에만 설정.
    opacity: float | None = None
    # 텍스트 레이어 검색 결과로 얻은 여러 rect. 한 텍스트가 페이지에서 여러 줄/영역에 걸쳐 있을 때 사용.
    search_rects_pdf: list[tuple[float, float, float, float]] | None = None
    # 검색에 사용된 원본 텍스트. 주석 메타데이터로 남겨두면 프론트엔드 재검색/디버깅에 유용하다.
    search_text: str | None = None


# --- EmbedPDF PdfAnnotationSubtype enum 값 (숫자 상수) ---
HIGHLIGHT_TYPE = 9  # PdfAnnotationSubtype.HIGHLIGHT
FREETEXT_TYPE = 3  # PdfAnnotationSubtype.FREETEXT
HELVETICA_FONT = 4  # PdfStandardFont.Helvetica
LEFT_ALIGN = 0  # PdfTextAlignment.Left
TOP_ALIGN = 0  # PdfVerticalAlignment.Top


def _estimate_callout_textbox_height(text: str) -> float:
    """텍스트 길이에 따라 callout 텍스트 박스 높이를 추정한다 (최소/최대 한도 적용).

    한글/영문 혼합 기준으로 대략적인 줄 수를 계산해 높이를 결정한다.
    텍스트가 적으면 작게, 많으면 크게 — 최소 16pt(약 1줄), 최대 120pt(약 10줄).
    """
    if not text:
        return CALLOUT_TEXTBOX_MIN_HEIGHT_PT
    # 폰트 8pt 기준, 혼합 평균 약 6pt/문자 → 안전하게 약 22문자/줄
    chars_per_line = max(1, int(CALLOUT_TEXTBOX_INNER_WIDTH_PT / CALLOUT_TEXTBOX_FONT_SIZE * 1.3))
    num_lines = max(1, math.ceil(len(text) / chars_per_line))
    height = num_lines * CALLOUT_TEXTBOX_LINE_HEIGHT_PT + CALLOUT_TEXTBOX_PADDING_V_PT
    return max(CALLOUT_TEXTBOX_MIN_HEIGHT_PT, min(CALLOUT_TEXTBOX_MAX_HEIGHT_PT, height))


def build_embedpdf_annotations(
    pdf_bytes: bytes,
    targets: list[AnnotationTarget],
    mode: str,
    annotation_index: int = 0,
    page_elements_bboxes: dict[int, list[tuple[float, float, float, float]]] | None = None,
) -> list[dict]:
    """[Flow: Step 1 (AnnotationTarget 목록과 PDF 수신) -> Step 2 (페이지별 시각적 크기 캡처)
          -> Step 3 (callout 텍스트 박스를 기존 요소를 피해 빈 영역에 배치)
          -> Step 4 (EmbedPDF AnnotationTransferItem[] 배열 생성)
          -> Step 5 (하이라이트는 HIGHLIGHT, 코멘트는 FreeTextCallout로 변환)]

    백엔드에서 생성한 주석을 EmbedPDF의 importAnnotations()로 바로 로드할 수 있는
    AnnotationTransferItem[] 형식으로 변환한다. 이 형식은 PDF 좌표계를 그대로 사용하며
    프론트에서 사용자가 직접 수정/저장할 수 있다.

    Args:
        pdf_bytes: 원본 PDF 바이트 (페이지 시각적 크기 계산용)
        targets: AnnotationTarget 목록
        mode: "highlight" | "margin_note" | "both"
            - "highlight": 하이라이트만
            - "margin_note": callout(텍스트 박스 + 화살표)만
            - "both": 하이라이트 + callout
        annotation_index: 병렬 AI 주석 run을 구분하는 고유 인덱스. 주석 ID에 포함되어
            병합/재시도/삭제 시 run 단위 식별이 가능하다.
        page_elements_bboxes: 페이지별 기존 텍스트 요소 bbox 목록 (1-based page_no →
            [(x0, y0, x1, y1), ...] in PDF user-space). callout 배치 시 충돌 회피에 사용.
            None이면 충돌 검사 없이 모서리에 배치.

    Returns:
        EmbedPDF importAnnotations()가 기대하는 AnnotationTransferItem[] 형식
    """
    if mode not in ("highlight", "margin_note", "both"):
        raise ValueError(f"Unsupported annotate mode: {mode}")

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    enable_highlight = mode in ("highlight", "both")
    needs_callout = mode in ("margin_note", "both")

    # 페이지별 시각적 크기 캡처 (주석 좌표 변환 기준)
    page_visual_rects: dict[int, fitz.Rect] = {}
    for page in doc:
        page_visual_rects[page.number] = page.rect

    by_page: dict[int, list[AnnotationTarget]] = {}
    for t in targets:
        by_page.setdefault(t.page_no, []).append(t)
    for page_targets in by_page.values():
        page_targets.sort(key=lambda t: t.bbox_pdf[1])

    annotations: list[dict] = []

    for page_no, page_targets in by_page.items():
        if page_no < 1 or page_no > doc.page_count:
            continue
        page = doc[page_no - 1]
        visual = page_visual_rects[page.number]
        page_width = visual.x1 - visual.x0
        page_height = visual.height
        page_x0 = visual.x0
        page_y0 = visual.y0
        page_rect = fitz.Rect(page_x0, page_y0, page_x0 + page_width, page_y0 + page_height)
        element_bboxes = (page_elements_bboxes or {}).get(page_no, [])
        # 같은 페이지에서 이미 배치한 callout 텍스트 박스 — 후속 callout이 겹치지 않도록 장애물에 추가
        placed_callout_bboxes: list[tuple[float, float, float, float]] = []

        for idx, t in enumerate(page_targets):
            base_id = f"backend-{annotation_index}-{page_no}-{idx}"
            x0, y0, x1, y1 = t.bbox_pdf

            # [Flow: Step 1 (segmentRects 구성 — 검색 결과 rects가 있으면 모두 사용, 없으면 bbox_pdf 단일 rect)
            #       -> Step 2 (하이라이트 주석을 canonical rect로 생성) -> Step 3 (callout 주석 생성)]
            segment_bboxes_pdf = t.search_rects_pdf if t.search_rects_pdf else [(x0, y0, x1, y1)]
            segment_rects_ep = [
                _rect_to_canonical_rect(sx0, sy0, sx1, sy1, page_rect)
                for sx0, sy0, sx1, sy1 in segment_bboxes_pdf
            ]
            bounding_rect_ep = _rect_to_canonical_rect(x0, y0, x1, y1, page_rect)

            # 하이라이트 주석 생성 (enable_highlight일 때)
            if enable_highlight:
                highlight_annotation = {
                    "annotation": {
                        "id": f"{base_id}-highlight",
                        "type": HIGHLIGHT_TYPE,
                        "pageIndex": page_no - 1,
                        "rect": bounding_rect_ep,
                        "segmentRects": segment_rects_ep,
                        "strokeColor": _rgb_to_hex(t.color),
                        "color": _rgb_to_hex(t.color),
                        "opacity": t.opacity if t.opacity is not None else DEFAULT_OPACITY,
                        "contents": t.comment,
                    }
                }
                # [Flow: 검색에 사용된 원본 텍스트가 있으면 custom 메타데이터로 보존]
                if t.search_text:
                    highlight_annotation["annotation"]["custom"] = {"searchText": t.search_text}
                annotations.append(highlight_annotation)

            # callout 주석 생성 (needs_callout일 때)
            if needs_callout:
                # 기존 요소 + 같은 페이지에서 이미 배치한 callout 박스를 모두 장애물로 포함
                obstacles = element_bboxes + placed_callout_bboxes
                callout_anno = _build_callout_annotation(
                    target_bbox=(x0, y0, x1, y1),
                    comment=t.comment,
                    color=t.callout_color if t.callout_color is not None else DEFAULT_CALLOUT_COLOR,
                    opacity=t.opacity if t.opacity is not None else DEFAULT_OPACITY,
                    element_bboxes=obstacles,
                    page_width=page_width,
                    page_height=page_height,
                    page_x0=page_x0,
                    page_y0=page_y0,
                    base_id=f"{base_id}-callout",
                    page_index=page_no - 1,
                )
                if callout_anno:
                    # callout은 device-space로 계산되므로, 장애물 추적용 textbox 추출 후 canonical로 변환한다.
                    ann = callout_anno["annotation"]
                    rect_dev = ann["rect"]
                    rd = ann["rectangleDifferences"]
                    tb_dev = {
                        "origin": {
                            "x": rect_dev["origin"]["x"] + rd["left"],
                            "y": rect_dev["origin"]["y"] + rd["top"],
                        },
                        "size": {
                            "width": rect_dev["size"]["width"] - rd["left"] - rd["right"],
                            "height": rect_dev["size"]["height"] - rd["top"] - rd["bottom"],
                        },
                    }
                    placed_callout_bboxes.append(_device_rect_to_pdf(tb_dev, page_height, page_x0, page_y0))
                    callout_anno["annotation"] = _device_annotation_to_canonical(
                        ann, page_width, page_height
                    )
                    annotations.append(callout_anno)

    return annotations


def _build_callout_annotation(
    target_bbox: tuple[float, float, float, float],
    comment: str,
    color: tuple[float, float, float],
    opacity: float,
    element_bboxes: list[tuple[float, float, float, float]],
    page_width: float,
    page_height: float,
    page_x0: float,
    page_y0: float,
    base_id: str,
    page_index: int,
) -> dict | None:
    """[Flow: Step 1 (텍스트 박스 크기 추정) -> Step 2 (빈 모서리/외곽 여백 탐색)
          -> Step 3 (calloutLine 3점 계산) -> Step 4 (overallRect + RD 계산)
          -> Step 5 (FreeTextCallout AnnotationTransferItem 반환)]

    페이지 내 기존 요소를 피해 callout 텍스트 박스를 배치하고, 대상 요소에서
    텍스트 박스로 이어지는 화살표 리더 라인을 계산한다.

    모든 좌표는 PDF user-space(원점 좌하단, y↑)로 계산한 뒤 마지막에 device-space로 변환한다.
    CropBox/MediaBox가 페이지 원점에서 어긋난 경우 page_x0, page_y0를 반영한다.
    """
    tb_w = CALLOUT_TEXTBOX_WIDTH_PT
    tb_h = _estimate_callout_textbox_height(comment)

    # 텍스트 박스가 페이지에 들어가지 않으면 null 반환
    if tb_w > page_width - 2 * CALLOUT_PAGE_EDGE_PADDING_PT:
        logger.warning(f"[callout] 페이지가 너무 좁아 텍스트 박스를 배치할 수 없음 (page_width={page_width})")
        return None

    # 빈 영역 탐색 — 기존 요소를 피해 텍스트 박스를 배치할 최적 위치 찾기
    textbox_pdf = _find_free_callout_slot(
        target_bbox=target_bbox,
        element_bboxes=element_bboxes,
        page_width=page_width,
        page_height=page_height,
        page_x0=page_x0,
        page_y0=page_y0,
        tb_w=tb_w,
        tb_h=tb_h,
    )

    # calloutLine 3점 [arrowTip, knee, connectionPoint]을 PDF user-space로 계산
    callout_line_pdf = _compute_callout_line(target_bbox, textbox_pdf)

    # PDF user-space → device-space 변환 (원점 좌하단 → 좌상단, y축 flip)
    textbox_dev = _pdf_rect_to_device(textbox_pdf, page_height, page_x0, page_y0)
    callout_line_dev = [
        _pdf_point_to_device(p[0], p[1], page_height, page_x0, page_y0)
        for p in callout_line_pdf
    ]

    # overallRect: 텍스트 박스 + calloutLine을 모두 감싸는 AABB (device-space)
    overall_rect_dev = _compute_callout_overall_rect(textbox_dev, callout_line_dev)
    # rectangleDifferences: overallRect → 텍스트 박스 inset (device-space)
    rd = _compute_rd_from_textbox(overall_rect_dev, textbox_dev)

    stroke_hex = _rgb_to_hex(color)

    return {
        "annotation": {
            "id": base_id,
            "type": FREETEXT_TYPE,
            "intent": "FreeTextCallout",
            "pageIndex": page_index,
            "rect": overall_rect_dev,
            "rectangleDifferences": rd,
            "calloutLine": callout_line_dev,
            "lineEnding": CALLOUT_LINE_ENDING_OPEN_ARROW,
            "strokeColor": stroke_hex,
            "strokeWidth": CALLOUT_STROKE_WIDTH,
            "contents": comment,
            "fontFamily": HELVETICA_FONT,
            "fontSize": CALLOUT_TEXTBOX_FONT_SIZE,
            "fontColor": CALLOUT_TEXTBOX_FONT_COLOR,
            "textAlign": LEFT_ALIGN,
            "verticalAlign": TOP_ALIGN,
            "color": CALLOUT_TEXTBOX_BG_COLOR,
            "opacity": opacity,
        }
    }


def _find_free_callout_slot(
    target_bbox: tuple[float, float, float, float],
    element_bboxes: list[tuple[float, float, float, float]],
    page_width: float,
    page_height: float,
    page_x0: float,
    page_y0: float,
    tb_w: float,
    tb_h: float,
) -> tuple[float, float, float, float]:
    """[Flow: Step 1 (후보 영역 8개 생성 — 4 모서리 + 4 외곽 여백) -> Step 2 (각 후보별 충돌 검사)
          -> Step 3 (충돌 없는 후보 중 대상에 가장 가까운 것 선택)
          -> Step 4 (전부 충돌하면 최소 겹침 후보 선택)]

    페이지 내 기존 텍스트 요소와 대상 요소를 피해 callout 텍스트 박스를 배치할
    최적의 빈 영역을 찾는다. PDF user-space 좌표를 사용한다.
    CropBox/MediaBox가 페이지 원점에서 어긋난 경우 page_x0, page_y0를 반영한다.

    Returns:
        (x0, y0, x1, y1) 텍스트 박스 영역 (PDF user-space)
    """
    pad = CALLOUT_PAGE_EDGE_PADDING_PT
    tx_cx = (target_bbox[0] + target_bbox[2]) / 2
    tx_cy = (target_bbox[1] + target_bbox[3]) / 2

    # CropBox/MediaBox 오프셋을 반영한 페이지 절대 좌표 범위
    page_x1 = page_x0 + page_width
    page_y1 = page_y0 + page_height

    # 후보 영역 8개: 4 모서리 + 4 외곽 여백 중심
    # (x0, y0, x1, y1) in PDF user-space (원점 좌하단, y↑)
    candidates: list[tuple[float, float, float, float]] = [
        # 4 모서리
        (page_x0 + pad, page_y1 - tb_h - pad, page_x0 + pad + tb_w, page_y1 - pad),  # 좌상
        (page_x1 - tb_w - pad, page_y1 - tb_h - pad, page_x1 - pad, page_y1 - pad),  # 우상
        (page_x0 + pad, page_y0 + pad, page_x0 + pad + tb_w, page_y0 + pad + tb_h),  # 좌하
        (page_x1 - tb_w - pad, page_y0 + pad, page_x1 - pad, page_y0 + pad + tb_h),  # 우하
        # 4 외곽 여백 중심
        ((page_x0 + page_x1 - tb_w) / 2, page_y1 - tb_h - pad, (page_x0 + page_x1 + tb_w) / 2, page_y1 - pad),  # 상단 중앙
        ((page_x0 + page_x1 - tb_w) / 2, page_y0 + pad, (page_x0 + page_x1 + tb_w) / 2, page_y0 + pad + tb_h),  # 하단 중앙
        (page_x0 + pad, (page_y0 + page_y1 - tb_h) / 2, page_x0 + pad + tb_w, (page_y0 + page_y1 + tb_h) / 2),  # 좌측 중앙
        (page_x1 - tb_w - pad, (page_y0 + page_y1 - tb_h) / 2, page_x1 - pad, (page_y0 + page_y1 + tb_h) / 2),  # 우측 중앙
    ]

    margin = CALLOUT_COLLISION_MARGIN_PT
    # 충돌 검사 대상: 기존 요소 + 대상 요소 자체 (대상 위에 텍스트 박스를 올리지 않음)
    obstacles = list(element_bboxes) + [target_bbox]

    best_slot = None
    best_distance = float("inf")
    best_overlap = float("inf")

    for slot in candidates:
        slot_cx = (slot[0] + slot[2]) / 2
        slot_cy = (slot[1] + slot[3]) / 2
        distance = math.hypot(slot_cx - tx_cx, slot_cy - tx_cy)

        # 충돌 면적 계산 (모든 장애물과의 겹침 합계)
        total_overlap = 0.0
        for obs in obstacles:
            ox0, oy0, ox1, oy1 = obs
            # 장애물 bbox에 margin을 추가해 여유 확보
            overlap_w = max(0.0, min(slot[2], ox1 + margin) - max(slot[0], ox0 - margin))
            overlap_h = max(0.0, min(slot[3], oy1 + margin) - max(slot[1], oy0 - margin))
            total_overlap += overlap_w * overlap_h

        if total_overlap == 0.0:
            # 충돌 없음 — 거리가 가장 가까운 것 선택
            if distance < best_distance:
                best_distance = distance
                best_slot = slot
        elif best_slot is None:
            # 아직 충돌 없는 후보를 못 찾음 — 최소 겹침 후보 기록
            if total_overlap < best_overlap:
                best_overlap = total_overlap
                best_slot = slot

    # 후보가 없으면 좌상단 고정 (폴백)
    if best_slot is None:
        best_slot = candidates[0]

    return best_slot


def _compute_callout_line(
    target_bbox: tuple[float, float, float, float],
    textbox: tuple[float, float, float, float],
) -> list[tuple[float, float]]:
    """[Flow: Step 1 (대상/텍스트 박스 중심 계산) -> Step 2 (arrowTip = 대상 가장자리 중점)
          -> Step 3 (knee = L자 꺾임점) -> Step 4 (connectionPoint = 텍스트 박스 가장자리 중점)
          -> Step 5 (knee가 텍스트 박스 내부면 2점 callout으로 폴백)]

    calloutLine의 점들을 PDF user-space로 계산한다.
    calloutLine = [arrowTip, knee, connectionPoint]
    - arrowTip: 화살표 끝이 가리키는 대상 요소의 가장자리 중점
    - knee: L자 꺾임점 (대상과 텍스트 박스 사이)
    - connectionPoint: 텍스트 박스 가장자리에서 리더 라인이 연결되는 중점

    embedpdf 렌더러는 calloutLine[0]에 화살표 머리를 그리고, calloutLine을 polyline으로 연결한다.
    """
    tx0, ty0, tx1, ty1 = target_bbox
    bx0, by0, bx1, by1 = textbox
    target_cx = (tx0 + tx1) / 2
    target_cy = (ty0 + ty1) / 2
    box_cx = (bx0 + bx1) / 2
    box_cy = (by0 + by1) / 2
    dx = box_cx - target_cx
    dy = box_cy - target_cy

    # arrowTip: 대상 요소의 텍스트 박스 쪽 가장자리 중점
    if abs(dx) >= abs(dy):
        arrow_tip = (tx1, target_cy) if dx > 0 else (tx0, target_cy)
    else:
        arrow_tip = (target_cx, ty1) if dy > 0 else (target_cx, ty0)

    # knee: L자 꺾임점 — 대상과 텍스트 박스의 상대 위치에 따라 수평/수직 우선
    if abs(dx) >= abs(dy):
        # 수평 방향 우선: arrowTip에서 수평으로 나간 뒤 텍스트 박스 높이로 꺾임
        knee = (box_cx, arrow_tip[1])
    else:
        # 수직 방향 우선: arrowTip에서 수직으로 나간 뒤 텍스트 박스 너비로 꺽임
        knee = (arrow_tip[0], box_cy)

    # knee가 텍스트 박스 내부에 있으면 2점 callout으로 폴백 (직선)
    if _point_in_rect(knee, textbox, margin=CALLOUT_KNEE_MIN_OFFSET_PT):
        connection_point = _nearest_textbox_edge_midpoint(arrow_tip, textbox)
        return [arrow_tip, connection_point]

    # connectionPoint: knee 위치 기준으로 텍스트 박스의 가장 가까운 변 중점
    # (embedpdf의 computeCalloutConnectionPoint와 동일 로직)
    connection_point = _compute_callout_connection_point(knee, textbox)

    return [arrow_tip, knee, connection_point]


def _compute_callout_connection_point(
    knee: tuple[float, float],
    textbox: tuple[float, float, float, float],
) -> tuple[float, float]:
    """[Flow: Step 1 (knee와 텍스트 박스 중심의 상대 위치 계산)
          -> Step 2 (|dx| >= |dy|면 좌/우 변 중점, 아니면 상/하 변 중점)
          -> Step 3 (해당 변의 중점 반환)]

    embedpdf의 computeCalloutConnectionPoint와 동일한 로직.
    knee 위치가 텍스트 박스 중심 기준 어느 방향에 가까운지에 따라
    가장 가까운 변의 중점을 연결점으로 반환한다.
    """
    bx0, by0, bx1, by1 = textbox
    cx = (bx0 + bx1) / 2
    cy = (by0 + by1) / 2
    dx = knee[0] - cx
    dy = knee[1] - cy
    if abs(dx) >= abs(dy):
        return (bx1, cy) if dx > 0 else (bx0, cy)
    return (cx, by1) if dy > 0 else (cx, by0)


def _nearest_textbox_edge_midpoint(
    point: tuple[float, float],
    textbox: tuple[float, float, float, float],
) -> tuple[float, float]:
    """점에서 가장 가까운 텍스트 박스 변의 중점을 반환한다 (2점 callout 폴백용)."""
    bx0, by0, bx1, by1 = textbox
    cx = (bx0 + bx1) / 2
    cy = (by0 + by1) / 2
    # 4 변의 중점과의 거리 비교
    edges = [
        (bx0, cy),  # 좌
        (bx1, cy),  # 우
        (cx, by0),  # 하
        (cx, by1),  # 상
    ]
    return min(edges, key=lambda e: math.hypot(e[0] - point[0], e[1] - point[1]))


def _point_in_rect(
    point: tuple[float, float],
    rect: tuple[float, float, float, float],
    margin: float = 0.0,
) -> bool:
    """점이 rect 내부 (margin 여유 포함)에 있는지 확인한다."""
    return (
        rect[0] - margin <= point[0] <= rect[2] + margin
        and rect[1] - margin <= point[1] <= rect[3] + margin
    )


def _compute_callout_overall_rect(
    textbox_dev: dict,
    callout_line_dev: list[dict],
) -> dict:
    """[Flow: Step 1 (텍스트 박스 + calloutLine 모든 점 수집) -> Step 2 (AABB 계산)
          -> Step 3 (strokeWidth 패딩 추가) -> Step 4 (EmbedPDF Rect 형식 반환)]

    embedpdf의 computeCalloutOverallRect와 동일한 로직.
    텍스트 박스와 calloutLine(화살표 포함)을 모두 감싸는 bounding rect를 device-space로 계산한다.
    이 rect는 주석의 선택/히트테스트 영역으로 사용된다.
    """
    all_x = [textbox_dev["origin"]["x"], textbox_dev["origin"]["x"] + textbox_dev["size"]["width"]]
    all_y = [textbox_dev["origin"]["y"], textbox_dev["origin"]["y"] + textbox_dev["size"]["height"]]
    for p in callout_line_dev:
        all_x.append(p["x"])
        all_y.append(p["y"])

    pad = CALLOUT_STROKE_WIDTH  # 화살표/라인 끝부분 여유
    min_x = min(all_x) - pad
    min_y = min(all_y) - pad
    max_x = max(all_x) + pad
    max_y = max(all_y) + pad
    return {
        "origin": {"x": min_x, "y": min_y},
        "size": {"width": max_x - min_x, "height": max_y - min_y},
    }


def _compute_rd_from_textbox(overall_rect: dict, textbox: dict) -> dict:
    """[Flow: Step 1 (overallRect와 텍스트 박스의 위치 차이 계산)
          -> Step 4 (PdfRectDifferences {left, top, right, bottom} 반환)]

    embedpdf의 computeRDFromTextBox와 동일 로직.
    overallRect에서 텍스트 박스까지의 inset(여백)을 계산한다.
    """
    tb_right = textbox["origin"]["x"] + textbox["size"]["width"]
    tb_bottom = textbox["origin"]["y"] + textbox["size"]["height"]
    ov_right = overall_rect["origin"]["x"] + overall_rect["size"]["width"]
    ov_bottom = overall_rect["origin"]["y"] + overall_rect["size"]["height"]
    return {
        "left": textbox["origin"]["x"] - overall_rect["origin"]["x"],
        "top": textbox["origin"]["y"] - overall_rect["origin"]["y"],
        "right": ov_right - tb_right,
        "bottom": ov_bottom - tb_bottom,
    }


def _pdf_point_to_device(
    px: float,
    py: float,
    page_height: float,
    page_x0: float = 0.0,
    page_y0: float = 0.0,
) -> dict:
    """[Flow: Step 1 (PDF user-space 좌표 수신) -> Step 2 (page rect 생성)
          -> Step 3 (pdf_user_to_device_point로 변환) -> Step 4 (EmbedPDF Position {x, y} 반환)]

    PDF user-space(원점 좌하단, y↑)를 embedpdf device-space(원점 좌상단, y↓)로 변환.
    좌표 변환은 pdf_coordinate_transform에서 matrix로 일원화 처리한다.
    """
    page_rect = fitz.Rect(page_x0, page_y0, page_x0 + page_height, page_y0 + page_height)
    device_point = pdf_user_to_device_point((px, py), page_rect)
    return {"x": device_point.x, "y": device_point.y}


def _pdf_rect_to_device(
    rect: tuple[float, float, float, float],
    page_height: float,
    page_x0: float = 0.0,
    page_y0: float = 0.0,
) -> dict:
    """[Flow: Step 1 (PDF user-space rect 수신) -> Step 2 (page rect 생성)
          -> Step 3 (embedpdf_rect_from_pdf_user로 변환) -> Step 4 (EmbedPDF Rect {origin, size} 반환)]

    PDF user-space rect를 embedpdf device-space Rect로 변환.
    _rect_to_embedpdf_rect와 동일한 중앙 변환 함수를 사용한다.
    """
    page_rect = fitz.Rect(page_x0, page_y0, page_x0 + page_height, page_y0 + page_height)
    return embedpdf_rect_from_pdf_user(rect, page_rect)


def _device_rect_to_pdf(
    rect_dev: dict,
    page_height: float,
    page_x0: float = 0.0,
    page_y0: float = 0.0,
) -> tuple[float, float, float, float]:
    """[Flow: Step 1 (device-space Rect 수신) -> Step 2 (page rect 생성)
          -> Step 3 (pdf_user_rect_from_embedpdf로 변환) -> Step 4 (PDF user-space tuple 반환)]

    embedpdf device-space Rect를 PDF user-space tuple로 역변환.
    같은 페이지의 후속 callout 배치 시 장애물 좌표계를 맞추기 위해 사용.
    """
    page_rect = fitz.Rect(page_x0, page_y0, page_x0 + page_height, page_y0 + page_height)
    pdf_rect = pdf_user_rect_from_embedpdf(rect_dev, page_rect)
    return (pdf_rect.x0, pdf_rect.y0, pdf_rect.x1, pdf_rect.y1)


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    """[Flow: Step 1 (0-1 RGB 튜플 수신) -> Step 2 (각 채널을 8비트 정수로 변환)
          -> Step 3 (6자리 hex 문자열 반환)]"""
    r, g, b = rgb
    return f"#{int(round(r * 255)):02X}{int(round(g * 255)):02X}{int(round(b * 255)):02X}"


def _rect_to_embedpdf_rect(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    page_height: float,
    page_x0: float = 0.0,
    page_y0: float = 0.0,
) -> dict:
    """[Flow: Step 1 (PDF user-space fitz.Rect와 page rect 생성)
          -> Step 2 (embedpdf_rect_from_pdf_user로 device-space 변환)
          -> Step 3 (EmbedPDF Rect dict 반환)]

    PDF 좌표계는 원점이 좌하단이고 y는 위로 증가한다. EmbedPDF는 annotation rect의
    origin.y를 device-space(원점 좌상단, y↓)로 해석해 CSS `top: origin.y * scale`로
    직접 렌더링한다. pdf_coordinate_transform.embedpdf_rect_from_pdf_user에서
    matrix로 y축 flip과 CropBox offset을 한 번에 처리한다.
    """
    pdf_rect = fitz.Rect(x0, y0, x1, y1)
    # 하위 호환용 helper: width/height를 page_height로 잘못 사용하지만,
    # PDF user-space <-> device-space matrix는 x1을 사용하지 않으므로 기존 테스트에 영향 없음.
    page_rect = fitz.Rect(page_x0, page_y0, page_x0 + page_height, page_y0 + page_height)
    return embedpdf_rect_from_pdf_user(pdf_rect, page_rect)


def _rect_to_canonical_rect(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    page_rect: fitz.Rect,
) -> dict:
    """[Flow: Step 1 (PDF user-space fitz.Rect 생성)
          -> Step 2 (pdf_user_rect_to_canonical로 [0,1] canonical rect 변환)
          -> Step 3 (canonical {origin, size} dict 반환)]

    page_rect의 x0, y0, width, height를 모두 올바르게 사용한다.
    """
    return cac.pdf_user_rect_to_canonical(fitz.Rect(x0, y0, x1, y1), page_rect)


def _pdf_point_to_canonical(
    px: float,
    py: float,
    page_rect: fitz.Rect,
) -> dict:
    """[Flow: Step 1 (PDF user-space point 수신)
          -> Step 2 (pdf_user_point_to_canonical로 [0,1] canonical point 변환)
          -> Step 3 ({x, y} dict 반환)]"""
    return cac.pdf_user_point_to_canonical(fitz.Point(px, py), page_rect)


def _device_annotation_to_canonical(
    annotation: dict,
    page_width: float,
    page_height: float,
) -> dict:
    """[Flow: Step 1 (device-space annotation dict 수신)
          -> Step 2 (rect/segmentRects/calloutLine/rectangleDifferences를 canonical로 변환)
          -> Step 3 (갱신된 annotation dict 반환)]

    callout 등 EmbedPDF 형식의 좌표를 canonical normalized 공간으로 변환한다.
    rectangleDifferences는 페이지 크기로 나누어 normalized inset으로 변환한다.
    """
    ann = dict(annotation)
    if "rect" in ann and isinstance(ann["rect"], dict):
        ann["rect"] = cac.device_rect_to_canonical(ann["rect"], page_width, page_height)
    if "segmentRects" in ann and isinstance(ann["segmentRects"], list):
        ann["segmentRects"] = [
            cac.device_rect_to_canonical(r, page_width, page_height)
            for r in ann["segmentRects"]
            if isinstance(r, dict)
        ]
    if "calloutLine" in ann and isinstance(ann["calloutLine"], list):
        ann["calloutLine"] = [
            cac.device_point_to_canonical(p, page_width, page_height)
            for p in ann["calloutLine"]
            if isinstance(p, dict)
        ]
    if "rectangleDifferences" in ann and isinstance(ann["rectangleDifferences"], dict):
        rd = ann["rectangleDifferences"]
        ann["rectangleDifferences"] = {
            "left": float(rd.get("left", 0)) / page_width,
            "top": float(rd.get("top", 0)) / page_height,
            "right": float(rd.get("right", 0)) / page_width,
            "bottom": float(rd.get("bottom", 0)) / page_height,
        }
    return ann
