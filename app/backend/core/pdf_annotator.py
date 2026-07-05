#!/usr/bin/env python3
# [Flow: Step 1 (AnnotationTarget 목록 수신) -> Step 2 (페이지별 회전 보정 행렬/원본 mediabox를 리사이즈 전에
#       미리 캡처) -> Step 3 (여백 주석 모드면 우측에만 충분히 넓은 주석 컬럼 추가, mediabox 원점 이동분을
#       기록) -> Step 4 (겹치지 않도록 우측 여백 컬럼에 주석 세로 위치를 순서대로 배치)
#       -> Step 5 (시각적 좌표를 회전 보정 행렬로 변환 후 mediabox 원점 이동분만큼 보정해 주석 적용)
#       -> Step 6 (주석이 추가된 PDF bytes 반환)]
# 하이라이트(형광펜)와 여백 주석(코멘트 박스)은 "어느 bbox에 표시할지" 로직이 완전히 동일하고
# 렌더링 방식만 다르므로 이 모듈 하나에서 같은 AnnotationTarget 데이터로 두 가지를 모두 처리한다.
#
# 회전된 PDF(/Rotate 90/180/270) 주의사항 1 (a1 프로덕션 실제 스캔 PDF로 검증하며 발견):
# OCR bbox는 fitz.Page.get_pixmap()이 렌더링한 "시각적(화면에 보이는) 이미지" 좌표를 기준으로 하는데,
# add_rect_annot()/add_freetext_annot()이 받는 Rect는 회전이 적용되기 "전" 좌표(page.rotation==0일 때만
# 시각적 좌표와 동일)를 기대한다. 따라서 시각적 bbox를 `visual_rect * page.derotation_matrix`로 변환한 뒤
# 주석 API에 전달해야 한다.
#
# 주의사항 2 (여백 추가 시 좌표가 틀어지는 문제, 실측으로 재현/확인):
# PyMuPDF의 주석/텍스트 삽입 좌표는 "PDF 절대 좌표"가 아니라 "현재 mediabox의 좌하단(x0,y0)을 원점으로
# 하는 로컬 좌표"이다. 즉 mediabox를 리사이즈하면서 x0/y0 자체가 이동하면(회전 각도에 따라 특정 방향으로만
# 여백을 늘려도 x0/y0이 함께 이동하는 경우가 있다), 리사이즈 "전" 페이지 기준으로 계산해둔 좌표가
# 리사이즈 "후" 페이지에서는 그 이동분만큼 어긋나 버린다. 이를 막기 위해 mediabox 원점 이동량
# (origin_shift)을 기록해두고, 모든 배치 좌표에서 그만큼 빼서 보정한다.
#
# 위 두 문제를 모두 피하기 위해, 여백은 (요청에 따라) 오른쪽에만 충분히 넓게 추가한다 — 상하좌우로
# 넓히면 회전된 페이지에서 원점이 이동해 정렬이 깨지는 사례가 실측되었기 때문이다. 오른쪽에 필요한
# 총 높이(주석이 겹치지 않게 쌓이는 데 필요한 높이)를 먼저 계산해 페이지 세로 길이 자체도 필요한 만큼만
# 늘린다.
from __future__ import annotations

import logging
from dataclasses import dataclass

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

MARGIN_WIDTH_PT = 190.0  # 우측 여백 주석 컬럼 너비 (포인트, 시각적 가로 방향 기준)
MARGIN_NOTE_HEIGHT_PT = 56.0
MARGIN_NOTE_GAP_PT = 6.0  # 세로로 쌓이는 코멘트 박스 사이 최소 간격
EXTRA_BOTTOM_SLACK_PT = 20.0  # 마지막 주석 아래 여유 공간
DEFAULT_HIGHLIGHT_COLOR = (1.0, 0.92, 0.3)  # 형광펜 노랑
DEFAULT_MARGIN_BORDER_COLOR = (0.85, 0.45, 0.05)


@dataclass
class AnnotationTarget:
    """하이라이트/여백 주석 공용 대상 하나 (표의 한 행에 대응)."""

    page_no: int  # 1-based
    bbox_pdf: tuple[float, float, float, float]  # (x0, y0, x1, y1), 시각적(렌더링된 이미지 기준) PDF 포인트 좌표
    comment: str
    color: tuple[float, float, float] = DEFAULT_HIGHLIGHT_COLOR


def annotate_pdf(pdf_bytes: bytes, targets: list[AnnotationTarget], mode: str) -> bytes:
    """원본 PDF에 하이라이트 및/또는 여백 주석을 추가한 새 PDF를 반환한다.

    Args:
        pdf_bytes: 원본 PDF 바이트
        targets: 표시할 행(bbox+코멘트) 목록. bbox_pdf는 시각적(회전 반영된) 좌표 기준.
        mode: "highlight" | "margin_note" | "both"

    Returns:
        주석이 추가된 PDF 바이트
    """
    if mode not in ("highlight", "margin_note", "both"):
        raise ValueError(f"Unsupported annotate mode: {mode}")

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    needs_margin = mode in ("margin_note", "both")

    # Step 1: 리사이즈 전에 페이지별 "회전 보정 행렬", "원본 시각적 크기", "원본 mediabox 원점"을
    # 미리 캡처해둔다. mediabox를 바꾸면 이 값들이 달라지므로, 항상 원본 상태 기준(=OCR bbox가 측정된
    # 기준)을 써야 한다.
    derotation_matrices: dict[int, fitz.Matrix] = {}
    visual_rects: dict[int, fitz.Rect] = {}
    original_origins: dict[int, tuple[float, float]] = {}
    for page in doc:
        derotation_matrices[page.number] = page.derotation_matrix
        visual_rects[page.number] = page.rect
        mb = page.mediabox
        original_origins[page.number] = (mb.x0, mb.y0)

    by_page: dict[int, list[AnnotationTarget]] = {}
    for t in targets:
        by_page.setdefault(t.page_no, []).append(t)
    for page_targets in by_page.values():
        page_targets.sort(key=lambda t: t.bbox_pdf[1])

    # Step 2: 여백 주석이 필요하면 각 페이지의 "시각적 우측"에만 여백 컬럼을 추가한다 (좌/상/하는 건드리지
    # 않는다). 필요한 세로 길이는 쌓일 주석 개수에 따라 미리 계산해, 겹치지 않을 만큼만 페이지를 늘린다.
    note_tops_by_page: dict[int, dict[int, float]] = {}
    origin_shifts: dict[int, tuple[float, float]] = {}
    if needs_margin:
        for page_no, page_targets in by_page.items():
            if page_no < 1 or page_no > doc.page_count:
                continue
            page = doc[page_no - 1]
            visual = visual_rects[page.number]
            # top_bound을 아주 낮게 잡아 첫 주석은 자기 행의 y위치에 자연스럽게 배치되고,
            # 이후 겹칠 때만 아래로 밀려나게 한다 (항상 페이지 맨 위부터 쌓이지 않도록).
            note_tops = _layout_margin_notes(page_targets, top_bound=float("-inf"))
            note_tops_by_page[page.number] = note_tops
            required_bottom = max([visual.y1] + [t + MARGIN_NOTE_HEIGHT_PT for t in note_tops.values()])
            new_visual = fitz.Rect(visual.x0, visual.y0, visual.x1 + MARGIN_WIDTH_PT, required_bottom + EXTRA_BOTTOM_SLACK_PT)
            new_raw_mediabox = new_visual * derotation_matrices[page.number]
            page.set_mediabox(new_raw_mediabox)
            old_origin = original_origins[page.number]
            origin_shifts[page.number] = (new_raw_mediabox.x0 - old_origin[0], new_raw_mediabox.y0 - old_origin[1])

    # Step 3: 페이지별로 하이라이트/여백 주석 적용
    for page_no, page_targets in by_page.items():
        if page_no < 1 or page_no > doc.page_count:
            logger.warning(f"[pdf_annotator] 잘못된 page_no={page_no} (총 {doc.page_count}페이지), 건너뜀")
            continue
        page = doc[page_no - 1]
        matrix = derotation_matrices[page.number]
        shift = origin_shifts.get(page.number, (0.0, 0.0))
        visual = visual_rects[page.number]
        note_tops = note_tops_by_page.get(page.number, {})

        for t in page_targets:
            note_top = note_tops.get(id(t))
            _apply_target(page, t, mode, matrix, shift, visual.x1 if needs_margin else None, note_top)

    return doc.tobytes()


def _layout_margin_notes(page_targets: list[AnnotationTarget], top_bound: float) -> dict[int, float]:
    """같은 페이지의 코멘트 박스들이 서로 겹치지 않도록 세로 위치(top y)를 순서대로 배정한다.

    각 코멘트 박스는 원래 자기 행의 y중심에 배치하되, 이전 박스의 아래쪽 경계보다 위로는
    올라가지 못하게 밀어낸다. 반환값은 target의 id() -> top y 매핑.
    """
    note_tops: dict[int, float] = {}
    next_available_top = top_bound
    for t in page_targets:
        _, y0, _, y1 = t.bbox_pdf
        desired_top = (y0 + y1) / 2 - MARGIN_NOTE_HEIGHT_PT / 2
        actual_top = max(desired_top, next_available_top)
        note_tops[id(t)] = actual_top
        next_available_top = actual_top + MARGIN_NOTE_HEIGHT_PT + MARGIN_NOTE_GAP_PT
    return note_tops


def _shift_rect(rect: fitz.Rect, shift: tuple[float, float]) -> fitz.Rect:
    """mediabox 원점 이동량만큼 보정한다 (로컬 좌표계 재정렬)."""
    return fitz.Rect(rect.x0 - shift[0], rect.y0 - shift[1], rect.x1 - shift[0], rect.y1 - shift[1])


def _shift_point(point: fitz.Point, shift: tuple[float, float]) -> fitz.Point:
    return fitz.Point(point.x - shift[0], point.y - shift[1])


def _apply_target(
    page: fitz.Page,
    target: AnnotationTarget,
    mode: str,
    matrix: fitz.Matrix,
    shift: tuple[float, float],
    original_visual_x1: float | None,
    note_top: float | None,
) -> None:
    """[Flow: Step 1 (시각적 좌표 -> raw 좌표 변환 -> 원점 이동 보정) -> Step 2 (하이라이트 적용)
    -> Step 3 (여백 주석 + 연결선 적용)]"""
    x0, y0, x1, y1 = target.bbox_pdf
    visual_rect = fitz.Rect(x0, y0, x1, y1)
    raw_rect = _shift_rect(visual_rect * matrix, shift)

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

    if mode in ("margin_note", "both") and original_visual_x1 is not None and note_top is not None:
        margin_x0 = original_visual_x1 + 4
        margin_x1 = original_visual_x1 + MARGIN_WIDTH_PT - 4
        margin_visual_rect = fitz.Rect(margin_x0, note_top, margin_x1, note_top + MARGIN_NOTE_HEIGHT_PT)
        margin_raw_rect = _shift_rect(margin_visual_rect * matrix, shift)
        # 하이라이트된 행의 우측 끝에서, 겹치지 않게 재배치된 코멘트 박스로 이어지는 연결선(callout).
        # 행 위치와 박스 위치가 세로로 어긋날 수 있어(겹침 방지 재배치) 각지지 않도록 무릎점(knee)을 넣는다.
        row_mid_y = (y0 + y1) / 2
        note_mid_y = note_top + MARGIN_NOTE_HEIGHT_PT / 2
        callout = [
            _shift_point(fitz.Point(x1, row_mid_y) * matrix, shift),
            _shift_point(fitz.Point(margin_x0 - 8, note_mid_y) * matrix, shift),
            _shift_point(fitz.Point(margin_x0, note_mid_y) * matrix, shift),
        ]
        page.add_freetext_annot(
            margin_raw_rect,
            target.comment,
            fontsize=8,
            text_color=DEFAULT_MARGIN_BORDER_COLOR,
            border_width=0.75,
            callout=callout,
            rotate=page.rotation,
        )
