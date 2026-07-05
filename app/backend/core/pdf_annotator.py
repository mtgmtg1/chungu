#!/usr/bin/env python3
# [Flow: Step 1 (AnnotationTarget 목록 수신) -> Step 2 (페이지별 회전 보정 행렬/원본 시각적 크기를
#       리사이즈 전에 미리 캡처) -> Step 3 (여백 주석 모드면 우측에만 여백 컬럼 추가 — 상/하/좌는 건드리지
#       않으므로 mediabox 원점 (x0,y0)이 이동하지 않아 보정 불필요) -> Step 4 (텍스트 양에 따라 높이가
#       가변되는 코멘트 박스를 겹치지 않게 우측 여백에 배치) -> Step 5 (시각적 좌표를 회전 보정 행렬로만
#       변환 후 주석 적용) -> Step 6 (주석이 추가된 PDF bytes 반환)]
# 하이라이트(형광펜)와 여백 주석(코멘트 박스)은 "어느 bbox에 표시할지" 로직이 완전히 동일하고
# 렌더링 방식만 다르므로 이 모듈 하나에서 같은 AnnotationTarget 데이터로 두 가지를 모두 처리한다.
#
# 회전된 PDF(/Rotate 90/180/270) 주의사항 (a1 프로덕션 실제 스캔 PDF로 검증하며 발견):
# OCR bbox는 fitz.Page.get_pixmap()이 렌더링한 "시각적(화면에 보이는) 이미지" 좌표를 기준으로 하는데,
# add_rect_annot()/add_freetext_annot()이 받는 Rect는 회전이 적용되기 "전" 좌표(page.rotation==0일 때만
# 시각적 좌표와 동일)를 기대한다. 따라서 시각적 bbox를 `visual_rect * page.derotation_matrix`로 변환한 뒤
# 주석 API에 전달해야 한다.
#
# 원점 이동 보정 불필요 (실측으로 확인):
# PDF 좌표계의 원점 (0,0)은 mediabox의 좌하단이다. 우측(또는 상단) 여백만 늘리면 mediabox의 x0/y0가
# 그대로 유지되어 원점이 이동하지 않는다. 좌측/하단 여백을 늘리면 x0/y0가 이동해 기존 좌표가 어긋나지만,
# 본 기능은 우측에만 여백을 추가하므로 원점 이동 보정(origin_shift)이 필요 없다.
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

MARGIN_WIDTH_PT = 190.0  # 우측 여백 주석 컬럼 너비 (포인트, 시각적 가로 방향 기준)
MARGIN_NOTE_MIN_HEIGHT_PT = 24.0  # 코멘트 박스 최소 높이 (약 2줄)
MARGIN_NOTE_MAX_HEIGHT_PT = 120.0  # 코멘트 박스 최대 높이 (약 10줄)
MARGIN_NOTE_GAP_PT = 6.0  # 세로로 쌓이는 코멘트 박스 사이 최소 간격
MARGIN_NOTE_FONT_SIZE = 8
MARGIN_NOTE_LINE_HEIGHT_PT = 11.0  # 줄 높이 (폰트 크기의 ~1.35배)
MARGIN_NOTE_PADDING_PT = 8.0  # 상하 패딩 합계
MARGIN_NOTE_INNER_WIDTH_PT = MARGIN_WIDTH_PT - 8  # 좌우 4pt씩 여백 → 실제 텍스트 영역 너비
DEFAULT_HIGHLIGHT_COLOR = (1.0, 0.92, 0.3)  # 형광펜 노랑
DEFAULT_MARGIN_BORDER_COLOR = (0.85, 0.45, 0.05)


@dataclass
class AnnotationTarget:
    """하이라이트/여백 주석 공용 대상 하나 (표의 한 행 또는 텍스트 블록에 대응)."""

    page_no: int  # 1-based
    bbox_pdf: tuple[float, float, float, float]  # (x0, y0, x1, y1), 시각적(렌더링된 이미지 기준) PDF 포인트 좌표
    comment: str
    color: tuple[float, float, float] = DEFAULT_HIGHLIGHT_COLOR


def _estimate_note_height(text: str) -> float:
    """텍스트 길이에 따라 코멘트 박스 높이를 추정한다 (최소/최대 한도 적용).

    한글/영문 혼합 기준으로 대략적인 줄 수를 계산해 높이를 결정한다.
    텍스트가 적으면 작게, 많으면 크게 — 최소 24pt(약 2줄), 최대 120pt(약 10줄).
    """
    if not text:
        return MARGIN_NOTE_MIN_HEIGHT_PT
    # 폰트 8pt 기준, 한글은 약 8pt 폭, 영문은 약 4pt 폭 → 혼합 평균 약 6pt/문자
    # 안전하게 약 22문자/줄로 추정
    chars_per_line = max(1, int(MARGIN_NOTE_INNER_WIDTH_PT / MARGIN_NOTE_FONT_SIZE * 1.3))
    num_lines = max(1, math.ceil(len(text) / chars_per_line))
    height = num_lines * MARGIN_NOTE_LINE_HEIGHT_PT + MARGIN_NOTE_PADDING_PT
    return max(MARGIN_NOTE_MIN_HEIGHT_PT, min(MARGIN_NOTE_MAX_HEIGHT_PT, height))


def annotate_pdf(pdf_bytes: bytes, targets: list[AnnotationTarget], mode: str) -> bytes:
    """원본 PDF에 하이라이트 및/또는 여백 주석을 추가한 새 PDF를 반환한다.

    Args:
        pdf_bytes: 원본 PDF 바이트
        targets: 표시할 요소(bbox+코멘트) 목록. bbox_pdf는 시각적(회전 반영된) 좌표 기준.
        mode: "highlight" | "margin_note" | "both"

    Returns:
        주석이 추가된 PDF 바이트
    """
    if mode not in ("highlight", "margin_note", "both"):
        raise ValueError(f"Unsupported annotate mode: {mode}")

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    needs_margin = mode in ("margin_note", "both")

    # Step 1: 리사이즈 전에 페이지별 "회전 보정 행렬"과 "원본 시각적 크기"를 캡처.
    # mediabox를 바꾸면 이 값들이 달라지므로, 항상 원본 상태 기준(=OCR bbox가 측정된 기준)을 써야 한다.
    derotation_matrices: dict[int, fitz.Matrix] = {}
    visual_rects: dict[int, fitz.Rect] = {}
    for page in doc:
        derotation_matrices[page.number] = page.derotation_matrix
        visual_rects[page.number] = page.rect

    by_page: dict[int, list[AnnotationTarget]] = {}
    for t in targets:
        by_page.setdefault(t.page_no, []).append(t)
    for page_targets in by_page.values():
        page_targets.sort(key=lambda t: t.bbox_pdf[1])

    # Step 2: 여백 주석이 필요하면 각 페이지의 "시각적 우측"에만 여백 컬럼을 추가한다.
    # 상/하/좌는 건드리지 않으므로 mediabox 원점 (x0,y0)이 이동하지 않아 보정이 불필요하다.
    note_layouts_by_page: dict[int, dict[int, tuple[float, float]]] = {}  # id(t) -> (top, height)
    if needs_margin:
        for page_no, page_targets in by_page.items():
            if page_no < 1 or page_no > doc.page_count:
                continue
            page = doc[page_no - 1]
            visual = visual_rects[page.number]
            note_layouts = _layout_margin_notes(page_targets, page_bottom=visual.y1)
            note_layouts_by_page[page.number] = note_layouts
            # 우측은 항상 여백 추가. 주석이 페이지 하단을 넘어가면 하단도 늘림.
            # PaddleOCR-VL / PDF 시각 좌표계의 원점은 좌상단이므로 우측/하단 확장은 원점 이동을 유발하지 않는다.
            required_bottom = max([visual.y1] + [top + height for top, height in note_layouts.values()])
            new_visual = fitz.Rect(visual.x0, visual.y0, visual.x1 + MARGIN_WIDTH_PT, required_bottom + EXTRA_BOTTOM_SLACK_PT)
            new_raw_mediabox = new_visual * derotation_matrices[page.number]
            page.set_mediabox(new_raw_mediabox)

    # Step 3: 페이지별로 하이라이트/여백 주석 적용
    for page_no, page_targets in by_page.items():
        if page_no < 1 or page_no > doc.page_count:
            logger.warning(f"[pdf_annotator] 잘못된 page_no={page_no} (총 {doc.page_count}페이지), 건너뜀")
            continue
        page = doc[page_no - 1]
        matrix = derotation_matrices[page.number]
        visual = visual_rects[page.number]
        note_layouts = note_layouts_by_page.get(page.number, {})

        for t in page_targets:
            layout = note_layouts.get(id(t))
            note_top, note_height = layout if layout else (None, None)
            _apply_target(page, t, mode, matrix, visual.x1 if needs_margin else None, note_top, note_height)

    return doc.tobytes()


def _layout_margin_notes(
    page_targets: list[AnnotationTarget],
    page_bottom: float,
) -> dict[int, tuple[float, float]]:
    """같은 페이지의 코멘트 박스들이 서로 겹치지 않도록 세로 위치(top)와 높이(height)를 배정한다.

    각 코멘트 박스는 원래 자기 행의 y중심에 배치하되, 이전 박스의 아래쪽 경계보다 위로는
    올라가지 못하게 밀어낸다. 텍스트 양에 따라 박스 높이가 가변된다.
    페이지 하단을 넘어가면 하단으로 밀려나는 것을 허용한다 (필요 시 페이지 하단이 확장됨).

    Returns:
        id(target) -> (top_y, height) 매핑
    """
    layouts: dict[int, tuple[float, float]] = {}
    next_available_top = float("-inf")
    for t in page_targets:
        height = _estimate_note_height(t.comment)
        _, y0, _, y1 = t.bbox_pdf
        desired_top = (y0 + y1) / 2 - height / 2
        actual_top = max(desired_top, next_available_top)
        layouts[id(t)] = (actual_top, height)
        next_available_top = actual_top + height + MARGIN_NOTE_GAP_PT
    return layouts


def _apply_target(
    page: fitz.Page,
    target: AnnotationTarget,
    mode: str,
    matrix: fitz.Matrix,
    original_visual_x1: float | None,
    note_top: float | None,
    note_height: float | None,
) -> None:
    """[Flow: Step 1 (시각적 좌표 -> 회전 보정 변환) -> Step 2 (하이라이트 적용)
    -> Step 3 (여백 주석 + 연결선 적용)]

    원점 이동 보정은 불필요하다 — 우측에만 여백을 추가하므로 mediabox 원점 (x0,y0)이 이동하지 않는다.
    """
    x0, y0, x1, y1 = target.bbox_pdf
    visual_rect = fitz.Rect(x0, y0, x1, y1)
    raw_rect = visual_rect * matrix  # 회전 보정만 (원점 이동 보정 불필요)

    if mode in ("highlight", "both"):
        # add_highlight_annot()는 텍스트 레이어(글리프)가 있는 PDF에서 검색된 quad를 넣을 때만 정확한
        # 사각형으로 렌더링된다. 스캔본처럼 텍스트 레이어가 없는 사각형 bbox를 넣으면 MuPDF가 임의의
        # 타원형 브러시 형태로 그려버리는 문제가 실측 확인됨 -> Square 주석(add_rect_annot)에
        # 반투명 채우기를 적용해 정확한 사각형 형광펜 효과를 낸다.
        annot = page.add_rect_annot(raw_rect)
        if annot is not None:
            annot.set_colors(stroke=target.color, fill=target.color)
            annot.set_opacity(0.45)
            annot.set_border(width=0)
            annot.update()

    if mode in ("margin_note", "both") and original_visual_x1 is not None and note_top is not None and note_height is not None:
        margin_x0 = original_visual_x1 + 4
        margin_x1 = original_visual_x1 + MARGIN_WIDTH_PT - 4
        margin_visual_rect = fitz.Rect(margin_x0, note_top, margin_x1, note_top + note_height)
        margin_raw_rect = margin_visual_rect * matrix
        # 하이라이트된 행의 우측 끝에서, 겹치지 않게 재배치된 코멘트 박스로 이어지는 연결선(callout).
        # 행 위치와 박스 위치가 세로로 어긋날 수 있어(겹침 방지 재배치) 각지지 않도록 무릎점(knee)을 넣는다.
        row_mid_y = (y0 + y1) / 2
        note_mid_y = note_top + note_height / 2
        callout = [
            fitz.Point(x1, row_mid_y) * matrix,
            fitz.Point(margin_x0 - 8, note_mid_y) * matrix,
            fitz.Point(margin_x0, note_mid_y) * matrix,
        ]
        page.add_freetext_annot(
            margin_raw_rect,
            target.comment,
            fontsize=MARGIN_NOTE_FONT_SIZE,
            text_color=DEFAULT_MARGIN_BORDER_COLOR,
            border_width=0.75,
            callout=callout,
            rotate=page.rotation,
        )
