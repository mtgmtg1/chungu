#!/usr/bin/env python3
# [Flow: Step 1 (원본 PDF/이미지를 페이지 이미지로 렌더링, DPI 고정) -> Step 2 (페이지별 PaddleOCR bbox 확보)
#       -> Step 3 (모든 텍스트 요소(표 행 + 단락/제목 등)를 텍스트만으로 LLM에 전달해 조건에 맞는 요소 선택)
#       -> Step 4 (선택된 요소의 bbox를 PDF 좌표로 변환) -> Step 5 (pdf_annotator로 하이라이트/여백 주석 적용)
#       -> Step 6 (결과 업로드 및 job 갱신)]
# PDF 하이라이트/여백 주석 기능의 오케스트레이터. xlsx_advanced_converter.py와 동일한 job 상태
# 갱신/환불 가능 패턴을 따른다.
import json
import logging
import re
import tempfile
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from .. import settings_store
from ..config import settings
from ..db.models import Job
from ..db.session import SessionLocal
from . import cache, ocr_client, paddleocr_client, supabase_client
from .image_deskew import deskew_image
from .ocr_layout import BBox, OcrRow, OcrTextBlock, parse_layout_result
from .pdf_annotator import AnnotationTarget, build_embedpdf_annotations
from .pdf_coords import clamp_rect_to_page, px_bbox_to_pdf_rect
from .prompts import build_element_highlight_prompt, build_vision_bbox_highlight_prompt
from .xlsx_advanced_converter import _get_page_image_paths

logger = logging.getLogger(__name__)

RENDER_DPI = 200  # _get_page_image_paths가 PDF를 렌더링할 때 사용하는 DPI와 동일해야 bbox 좌표가 맞는다.
MAX_ELEMENTS_FOR_LLM = 400  # 프롬프트 폭주 방지
MAX_TEXT_BLOCK_CHARS = 200  # 텍스트 블록은 앞 200자만 LLM에 전달 (토큰 폭증 방지)

# 90° 단위 회전 각도 코드 → 실제 각도(도). AI Studio API의 doc_preprocessor_res.angle 매핑.
# 0=정상, 1=90°(반시계), 2=180°, 3=270°(반시계) — PaddleOCR 문서 기준.
ANGLE_CODE_TO_DEGREES = {0: 0, 1: 90, 2: 180, 3: 270}

# 사용자가 선택할 수 있는 하이라이트/주석 색상 팔레트 (이름 → RGB[0-1]).
# 프롬프트와 동일한 이름을 사용해야 LLM 출력이 매핑된다.
HIGHLIGHT_COLOR_PALETTE = {
    "red": (1.0, 0.25, 0.25),
    "yellow": (1.0, 0.92, 0.3),
    "green": (0.25, 0.85, 0.35),
    "blue": (0.25, 0.55, 1.0),
    "orange": (1.0, 0.6, 0.15),
    "purple": (0.65, 0.35, 0.95),
    "pink": (1.0, 0.55, 0.75),
    "gray": (0.7, 0.7, 0.7),
}
DEFAULT_HIGHLIGHT_COLOR_NAME = "yellow"


def _strip_json_fence(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"```[a-zA-Z]*\n?|\n?```", "", content).strip()
    return content


def _row_to_text(row: OcrRow) -> str:
    """표 행의 셀 텍스트를 파이프 구분 문자열로 결합한다."""
    return " | ".join(cell.strip() for cell in row.cell_texts if cell.strip())


def _text_block_to_text(block: OcrTextBlock) -> str:
    """텍스트 블록의 내용을 앞 200자로 잘라 LLM용 텍스트로 만든다."""
    text = block.text.replace("\n", " ").strip()
    if len(text) > MAX_TEXT_BLOCK_CHARS:
        text = text[:MAX_TEXT_BLOCK_CHARS] + "..."
    return text


def _annotation_display_name(job: Job, n: int) -> str:
    """주석 PDF의 표시용 파일명을 생성한다.

    원본 파일명이 있으면 확장자를 제거하고 `_annotation{N}.pdf`를 붙이고,
    없으면 `result_annotation{N}.pdf`를 반환한다.
    """
    base = job.original_filename or "result"
    stem = Path(base).stem or base
    return f"{stem}_annotation{n}.pdf"


@dataclass
class AnnotateElement:
    """주석 대상이 될 수 있는 하나의 텍스트 요소 (표 행 또는 텍스트 블록)."""

    page_no: int  # 1-based
    bbox_px: BBox  # 픽셀 좌표 (xmin, ymin, xmax, ymax) — 보정된 이미지 기준
    kind: str  # "table_row" | "text"
    text: str  # LLM에 전달할 텍스트 표현
    # 부분 하이라이트를 위해 필요한 단어/셀 단위 bbox (없으면 전체 bbox만 사용)
    word_bboxes: list[BBox] = field(default_factory=list)
    # 표 행인 경우 각 셀의 텍스트와 bbox (셀 단위 하이라이트용)
    cell_texts: list[str] = field(default_factory=list)
    cell_bboxes: list[BBox] = field(default_factory=list)


def _rotate_image_90(image_path: Path, angle_code: int, output_dir: Path) -> Path:
    """AI Studio angle_code(0/1/2/3)에 따라 이미지를 90° 단위로 회전시켜 저장한다.

    AI Studio useDocOrientationClassify=True가 보정한 방향을 클라이언트에서 재현한다.
    angle_code 1=90°, 2=180°, 3=270° (반시계방향). 0이면 원본 그대로 복사.

    Args:
        image_path: 회전시킬 이미지 경로 (deskew 보정 완료된 이미지)
        angle_code: 0/1/2/3 (AI Studio doc_preprocessor_res.angle)
        output_dir: 출력 디렉터리

    Returns:
        회전된 이미지 경로. angle_code가 0이면 원본 경로 그대로 반환.
    """
    if angle_code == 0:
        return image_path

    import cv2

    degrees = ANGLE_CODE_TO_DEGREES.get(angle_code, 0)
    if degrees == 0:
        return image_path

    img = cv2.imread(str(image_path))
    if img is None:
        logger.warning(f"[pdf_annotate] 회전용 이미지 로드 실패: {image_path.name}")
        return image_path

    # OpenCV의 회전 상수: 90° 반시계 = ROTATE_90_COUNTERCLOCKWISE, 180° = ROTATE_180,
    # 270° 반시계 = ROTATE_90_CLOCKWISE (270° CCW == 90° CW)
    if degrees == 90:
        rotated = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    elif degrees == 180:
        rotated = cv2.rotate(img, cv2.ROTATE_180)
    elif degrees == 270:
        rotated = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    else:
        return image_path

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{image_path.stem}_rot{angle_code}{image_path.suffix}"
    cv2.imwrite(str(output_path), rotated)
    logger.info(f"[pdf_annotate] {image_path.name} 90° 회전(angle_code={angle_code}) → {output_path.name}")
    return output_path


def _collect_page_elements(
    job: Job,
    temp_dir: Path,
) -> tuple[list[AnnotateElement], dict[int, Path]]:
    """모든 페이지를 렌더링하고 PaddleOCR bbox를 확보해 텍스트 요소 목록을 반환한다.

    [Flow: Step 1 (페이지 이미지 로드) -> Step 2 (deskew 미세 회전 보정) -> Step 3 (PaddleOCR 전송 + bbox + angle_code 수신)
          -> Step 4 (angle_code로 90° 회전 적용한 최종 이미지 준비) -> Step 5 (표 행 + 텍스트 블록 수집)]

    표의 행(table_row)과 텍스트 블록(text)을 모두 수집한다.
    반환하는 corrected_images는 "deskew + 90° 대회전 보정이 모두 완료된 정돈된 이미지"이며,
    이 이미지들로 주석 PDF를 생성하면 bbox와 완벽히 정렬된다.

    Returns:
        (elements, corrected_images) —
        elements: 주석 대상 텍스트 요소 목록 (bbox는 보정된 이미지 기준)
        corrected_images: page_no(1-based) → 정돈된 페이지 이미지 경로
    """
    image_paths = _get_page_image_paths(job, temp_dir)
    elements: list[AnnotateElement] = []
    corrected_images: dict[int, Path] = {}

    for page_no in sorted(image_paths.keys()):
        img_path = image_paths[page_no]
        try:
            _markdown, layout_raw, angle_code = paddleocr_client.convert_image_with_layout(img_path)
        except Exception as e:
            logger.warning(f"[pdf_annotate] page={page_no} PaddleOCR 레이아웃 확보 실패: {e}")
            continue

        # deskew는 paddleocr_client 내부에서 이미 적용되어 전송됐지만, 주석 PDF의 베이스 이미지도
        # 동일하게 deskew해야 bbox와 정렬된다. 여기서 원본 이미지에 deskew를 다시 적용한다.
        deskewed_path, _applied = deskew_image(img_path, output_dir=temp_dir / "deskewed")
        # 90° 단위 대회전 적용 (AI Studio 보정 결과 재현)
        final_path = _rotate_image_90(deskewed_path, angle_code, temp_dir / "rotated")
        corrected_images[page_no] = final_path

        layout = parse_layout_result(layout_raw, page_no=page_no)
        for table in layout.tables:
            for row in table.rows:
                if not any(cell.strip() for cell in row.cell_texts):
                    continue
                elements.append(AnnotateElement(
                    page_no=page_no, bbox_px=row.bbox_px, kind="table_row",
                    text=_row_to_text(row),
                    word_bboxes=[],
                    cell_texts=row.cell_texts,
                    cell_bboxes=[],  # TODO: table_res_list에서 셀 bbox 파싱하면 여기 채움
                ))
        for tb in layout.text_blocks:
            elements.append(AnnotateElement(
                page_no=page_no, bbox_px=tb.bbox_px, kind="text",
                text=_text_block_to_text(tb),
                word_bboxes=tb.word_bboxes,
                cell_texts=[],
                cell_bboxes=[],
            ))

    return elements, corrected_images


def _page_point_sizes(pdf_bytes: bytes) -> dict[int, tuple[float, float]]:
    """원본 PDF에서 페이지별 실제 크기(포인트)를 1-based page_no 기준으로 반환한다."""
    sizes: dict[int, tuple[float, float]] = {}
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for i in range(doc.page_count):
            r = doc[i].mediabox
            sizes[i + 1] = (r.width, r.height)
    finally:
        doc.close()
    return sizes


def _images_to_pdf(image_paths: dict[int, Path]) -> bytes:
    """이미지 파일들을 1장씩 PDF 페이지로 삽입해 단일 PDF 바이트를 생성한다.

    각 이미지는 원본 해상도를 기준으로 페이지 크기를 결정하되, RENDER_DPI 기준 포인트 크기로 변환한다.
    """
    doc = fitz.open()
    for page_no in sorted(image_paths.keys()):
        img_path = image_paths[page_no]
        try:
            img = fitz.Pixmap(str(img_path))
            # 이미지 픽셀 크기를 RENDER_DPI 기준 포인트로 변환
            width_pt = img.width * 72.0 / RENDER_DPI
            height_pt = img.height * 72.0 / RENDER_DPI
            page = doc.new_page(width=width_pt, height=height_pt)
            page.insert_image(fitz.Rect(0, 0, width_pt, height_pt), filename=str(img_path))
        except Exception as e:
            logger.warning(f"[pdf_annotate] 이미지→PDF 변환 실패 page={page_no}: {e}")
            continue
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def _color_name_to_rgb(color_name: str | None) -> tuple[float, float, float]:
    """LLM이 반환한 색상 이름을 RGB 튜플로 매핑한다. 인식 불가 시 기본 노랑."""
    if not color_name or not isinstance(color_name, str):
        return HIGHLIGHT_COLOR_PALETTE[DEFAULT_HIGHLIGHT_COLOR_NAME]
    normalized = color_name.strip().lower().replace(" ", "_")
    return HIGHLIGHT_COLOR_PALETTE.get(normalized, HIGHLIGHT_COLOR_PALETTE[DEFAULT_HIGHLIGHT_COLOR_NAME])


def _narrow_bbox_by_scope(element: AnnotateElement, scope: str | None) -> BBox | None:
    """LLM이 지정한 scope에 따라 element의 bbox를 좁힌다.

    [Flow: Step 1 (scope 파싱) -> Step 2 (scope 유형별 bbox 계산) -> Step 3 (좁힌 bbox 반환)]

    지원 scope:
      - "full" 또는 None → element 전체 bbox 반환
      - "first_column" → 표 첫 번째 셀 bbox (셀 bbox 없으면 전체)
      - "last_column" → 표 마지막 셀 bbox (셀 bbox 없으면 전체)
      - "amount_cell" / "name_cell" / "date_cell" → 셀 텍스트에서 키워드 기반 매칭
      - "keyword: <word>" → 텍스트 블록/표 셀에서 키워드가 포함된 영역 bbox
      - "column N" → N번째 셀 bbox (1-based, 셀 bbox 없으면 전체)

    Args:
        element: 주석 대상 요소 (word_bboxes/cell_texts/cell_bboxes 포함 가능)
        scope: LLM이 반환한 highlight_scope 문자열

    Returns:
        좁혀진 bbox 또는 None. None이면 element 전체 bbox를 사용한다.
    """
    full_bbox = element.bbox_px
    if not scope or scope.strip().lower() == "full":
        return None

    scope_clean = scope.strip().lower()

    # 표 셀 단위 scope
    if element.kind == "table_row" and element.cell_texts:
        # first_column / last_column
        if scope_clean == "first_column" and element.cell_bboxes:
            return element.cell_bboxes[0]
        if scope_clean == "last_column" and element.cell_bboxes:
            return element.cell_bboxes[-1]
        if scope_clean.startswith("column "):
            try:
                idx = int(scope_clean.split(" ", 1)[1]) - 1  # 1-based → 0-based
                if 0 <= idx < len(element.cell_bboxes):
                    return element.cell_bboxes[idx]
            except ValueError:
                pass

        # keyword 기반 셀 매칭 (amount_cell, name_cell, date_cell, keyword:xxx)
        keyword = None
        if scope_clean in ("amount_cell", "name_cell", "date_cell"):
            keyword_map = {
                "amount_cell": ["amount", "금액", "가격", "합계", "total", "sum", "price"],
                "name_cell": ["name", "이름", "성명", "명", "담당자", "고객"],
                "date_cell": ["date", "날짜", "일자", "연월일", "기간", "period"],
            }
            keywords = keyword_map.get(scope_clean, [])
        elif scope_clean.startswith("keyword:"):
            keywords = [scope_clean.split(":", 1)[1].strip().lower()]
        else:
            keywords = []

        if keywords and element.cell_bboxes:
            best_idx = -1
            best_score = -1.0
            for idx, cell_text in enumerate(element.cell_texts):
                cell_lower = cell_text.lower()
                for kw in keywords:
                    if kw in cell_lower:
                        # 헤더 행과 구분하기 위해 짧은 셀 텍스트 우선 (데이터가 짧음)
                        score = 1.0 / max(1, len(cell_text))
                        if score > best_score:
                            best_score = score
                            best_idx = idx
                        break
            if 0 <= best_idx < len(element.cell_bboxes):
                return element.cell_bboxes[best_idx]

    # 텍스트 블록/표 행 공통 keyword scope
    if scope_clean.startswith("keyword:"):
        keyword = scope_clean.split(":", 1)[1].strip().lower()
    elif scope_clean not in ("full", "first_column", "last_column") and not scope_clean.startswith("column "):
        # scope_clean 자체를 키워드로 간주 (예: "amount", "name")
        keyword = scope_clean
    else:
        keyword = None

    if keyword and element.word_bboxes:
        # word_bboxes에 텍스트가 없으므로 keyword가 블록 텍스트에 있으면
        # 블록 내 모든 word_bboxes를 사용해 좌우 폭을 줄인다.
        # 더 정밀하게 하려면 word_bboxes에 텍스트도 포함해야 함.
        if keyword in element.text.lower():
            matched = element.word_bboxes
            min_x = min(b[0] for b in matched)
            min_y = min(b[1] for b in matched)
            max_x = max(b[2] for b in matched)
            max_y = max(b[3] for b in matched)
            return (min_x, min_y, max_x, max_y)

    return None


def _matches_to_targets(
    matches: list[dict],
    elements: list[AnnotateElement],
    page_point_sizes: dict[int, tuple[float, float]],
) -> list[AnnotationTarget]:
    """LLM이 반환한 match 목록을 AnnotationTarget 목록으로 변환한다 (scope/색상 적용)."""
    targets: list[AnnotationTarget] = []
    for m in matches:
        idx = m.get("element_index")
        if not isinstance(idx, int) or idx < 0 or idx >= len(elements):
            continue
        el = elements[idx]
        scope = m.get("highlight_scope")
        narrowed_bbox = _narrow_bbox_by_scope(el, scope)
        bbox_px = narrowed_bbox if narrowed_bbox is not None else el.bbox_px
        rect_pdf = px_bbox_to_pdf_rect(bbox_px, dpi=RENDER_DPI)
        page_pt = page_point_sizes.get(el.page_no)
        if page_pt:
            rect_pdf = clamp_rect_to_page(rect_pdf, page_pt[0], page_pt[1])
        comment = str(m.get("comment") or "").strip()
        color = _color_name_to_rgb(m.get("color"))
        targets.append(AnnotationTarget(page_no=el.page_no, bbox_pdf=rect_pdf, comment=comment, color=color))
    return targets


def _collect_targets_with_vision_llm(
    image_paths: dict[int, Path],
    instruction: str,
    endpoint: str,
    model: str,
    api_key: str,
) -> tuple[list[AnnotationTarget], str | None, str | None]:
    """Vision LLM에 페이지 이미지를 보내 정밀 bbox + 색상 + 코멘트를 얻어 AnnotationTarget 목록을 반환한다.

    [Flow: Step 1 (페이지별 이미지 순회) -> Step 2 (Gemma4 해상도 맞춤) -> Step 3 (Vision LLM bbox 요청)
          -> Step 4 (원본 이미지 좌표로 스케일 복원) -> Step 5 (AnnotationTarget 생성)
          -> Step 6 (페이지별 mode/comment_mode 추출, 마지막 유효 값 사용)]

    프롬프트는 LLM이 사용자 요청에 따라 표시 방식(mode)과 코멘트 모드(comment_mode)를
    결정하도록 유도한다. 반환된 값은 상위 run()에서 최종 주석 옵션으로 오버라이드한다.
    """
    targets: list[AnnotationTarget] = []
    mode: str | None = None
    comment_mode: str | None = None
    for page_no, img_path in sorted(image_paths.items()):
        try:
            from PIL import Image

            with Image.open(img_path) as img:
                img_w, img_h = img.size
            fitted = ocr_client.fit_image_to_gemma4_resolution(img_path)
            with Image.open(fitted) as fitted_img:
                fitted_w, fitted_h = fitted_img.size
            scale_x = img_w / fitted_w if fitted_w > 0 else 1.0
            scale_y = img_h / fitted_h if fitted_h > 0 else 1.0

            # 코멘트는 AI 요약으로 생성한 뒤, comment_mode가 user_text이면 백엔드에서 교체한다.
            prompt = build_vision_bbox_highlight_prompt(instruction, fitted_w, fitted_h, want_llm_comment=True)
            content, _ = ocr_client.call_vision(img_path, prompt, endpoint, model, api_key, max_tokens=4000)
            content = _strip_json_fence(content)
            try:
                data = json.loads(content)
            except json.JSONDecodeError as e:
                logger.warning(f"[pdf_annotate] page={page_no} Vision LLM JSON 파싱 실패: {e}")
                continue

            page_mode = data.get("mode") if isinstance(data, dict) else None
            page_comment_mode = data.get("comment_mode") if isinstance(data, dict) else None
            if page_mode in ("highlight", "margin_note", "both"):
                mode = page_mode
            if page_comment_mode in ("user_text", "llm_summary"):
                comment_mode = page_comment_mode

            matches = data.get("matches", []) if isinstance(data, dict) else []
            for m in matches:
                bbox = m.get("bbox")
                if not isinstance(bbox, list) or len(bbox) < 4:
                    continue
                try:
                    x0 = float(bbox[0]) * scale_x
                    y0 = float(bbox[1]) * scale_y
                    x1 = float(bbox[2]) * scale_x
                    y1 = float(bbox[3]) * scale_y
                except (ValueError, TypeError):
                    continue
                rect_pdf = px_bbox_to_pdf_rect((x0, y0, x1, y1), dpi=RENDER_DPI)
                comment = str(m.get("comment") or "").strip()
                color = _color_name_to_rgb(m.get("color"))
                targets.append(AnnotationTarget(page_no=page_no, bbox_pdf=rect_pdf, comment=comment, color=color))
        except Exception as e:
            logger.warning(f"[pdf_annotate] page={page_no} Vision LLM 처리 실패: {e}")
            continue
    return targets, mode, comment_mode


def _select_elements_with_llm(
    elements: list[AnnotateElement],
    instruction: str,
    endpoint: str,
    model: str,
    api_key: str,
) -> tuple[list[dict], str | None, str | None]:
    """LLM에게 요소 텍스트만 전달해 조건에 맞는 요소 인덱스+코멘트+scope+색상을 받는다.

    [Flow: Step 1 (요소 목록을 LLM용 dict로 변환) -> Step 2 (프롬프트 생성 후 텍스트 LLM 호출)
          -> Step 3 (JSON 파싱) -> Step 4 (matches 필터링 및 mode/comment_mode 추출)]

    프롬프트는 LLM이 표시 방식(mode)과 코멘트 모드(comment_mode)를 사용자 요청에 따라
    결정하도록 유도한다. 반환된 mode/comment_mode는 상위 run()에서 최종 주석 생성
    옵션으로 오버라이드에 사용된다.
    """
    if not elements:
        return [], None, None

    truncated = elements[:MAX_ELEMENTS_FOR_LLM]
    element_dicts = [{"kind": e.kind, "text": e.text} for e in truncated]
    # 코멘트는 AI가 요약하도록 생성한 뒤, comment_mode가 user_text이면 백엔드에서 교체한다.
    prompt = build_element_highlight_prompt(element_dicts, instruction, want_llm_comment=True)

    content, _ = ocr_client.call_text(prompt, endpoint, model, api_key, max_tokens=4000)
    content = _strip_json_fence(content)
    try:
        data = json.loads(content)
    except Exception as e:
        raise ValueError(f"LLM 응답 JSON 파싱 실패: {e} (content={content[:200]})")

    mode = data.get("mode") if isinstance(data, dict) else None
    comment_mode = data.get("comment_mode") if isinstance(data, dict) else None
    matches = data.get("matches", []) if isinstance(data, dict) else []
    if not isinstance(matches, list):
        return [], mode, comment_mode
    return [m for m in matches if isinstance(m, dict) and "element_index" in m], mode, comment_mode


def run(
    job_id: str,
    instruction: str,
    mode: str,
    comment_mode: str,
    language: str = "en",
    advanced: bool = False,
    annotation_index: int = 0,
) -> dict:
    """하이라이트/여백 주석 작업을 실행하고 job 상태를 갱신한다.

    Args:
        job_id: 작업 ID
        instruction: 사용자가 입력한 조건 문구
        mode: "highlight" | "margin_note" | "both"
        comment_mode: "user_text" | "llm_summary"
        language: 사용자 언어 코드 ("ko"/"en"/"ja") — 주석 코멘트가 이 언어로 작성된다
        advanced: True이면 Vision LLM 파이프라인(정밀 bbox + 색상) 사용, False이면 기존 PaddleOCR 기반 파이프라인
        annotation_index: API 수준에서 원자적으로 할당된 고유 인덱스 (파일명 충돌 방지)
    """
    db = SessionLocal()
    job = db.get(Job, job_id)
    if job is None:
        db.close()
        return {"error": "job not found"}

    # 하위 호환: 목록 컬럼 추가 전에 생성된 단일 주석 PDF를 목록으로 마이그레이션
    if job.result_annotated_pdf_storage_path and not (job.annotated_pdf_files or []):
        job.annotated_pdf_files = [
            {
                "storage_path": job.result_annotated_pdf_storage_path,
                "filename": _annotation_display_name(job, 1),
                "instruction": job.annotate_instruction,
                "mode": job.annotate_mode,
                "comment_mode": job.annotate_comment_mode,
                "created_at": job.finished_at.isoformat() if job.finished_at else datetime.now(timezone.utc).isoformat(),
            }
        ]
        db.commit()

    next_index = annotation_index

    endpoint = job.endpoint or settings_store.get_setting(db, "llm_endpoint") or settings.default_llm_endpoint
    model = job.model or settings_store.get_setting(db, "llm_model") or settings.default_llm_model
    api_key = settings_store.get_setting(db, "llm_api_key") or ""

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_dir = Path(tmpdir)
            image_paths = _get_page_image_paths(job, temp_dir)
            if not image_paths:
                raise ValueError("원본 파일을 이미지로 렌더링하지 못해 주석을 생성할 수 없습니다")

            llm_mode: str | None = None
            llm_comment_mode: str | None = None
            if advanced:
                # [Flow: 고급주석 — Vision LLM이 이미지를 직접 보고 정밀 bbox + 색상 + 코멘트 반환]
                pdf_bytes = _images_to_pdf(image_paths)
                page_point_sizes = _page_point_sizes(pdf_bytes)
                targets, llm_mode, llm_comment_mode = _collect_targets_with_vision_llm(
                    image_paths, instruction, endpoint, model, api_key
                )
                if not targets:
                    _update_entry_status(db, job_id, next_index, "done", recovery_notes=[{"reason": "조건에 맞는 요소를 찾지 못했습니다"}])
                    return {"job_id": job_id, "status": "done", "matched_rows": 0}
            else:
                # [Flow: 주석 PDF 베이스 — 정돈된 이미지(deskew + 90° 대회전 보정 완료)로 PDF 생성]
                # 원본 PDF를 사용하지 않고 보정된 페이지 이미지로 새 PDF를 생성한다.
                # 이유: bbox가 "deskew + AI Studio 90° 보정된 이미지" 기준으로 반환되므로,
                # 주석 PDF의 베이스도 동일하게 보정된 이미지여야 bbox와 완벽히 정렬된다.
                # 원본 PDF 벡터 품질 손실(텍스트 선택 불가)은 사용자가 명시적으로 수용한 트레이드오프.
                elements, corrected_images = _collect_page_elements(job, temp_dir)
                if not elements:
                    raise ValueError("텍스트 요소를 인식하지 못해 하이라이트/여백 주석 대상을 찾을 수 없습니다")
                if not corrected_images:
                    raise ValueError("보정된 페이지 이미지를 생성하지 못해 주석 PDF를 만들 수 없습니다")

                pdf_bytes = _images_to_pdf(corrected_images)
                page_point_sizes = _page_point_sizes(pdf_bytes)

                matches, llm_mode, llm_comment_mode = _select_elements_with_llm(
                    elements, instruction, endpoint, model, api_key
                )
                if not matches:
                    _update_entry_status(db, job_id, next_index, "done", recovery_notes=[{"reason": "조건에 맞는 요소를 찾지 못했습니다"}])
                    return {"job_id": job_id, "status": "done", "matched_rows": 0}

                targets = _matches_to_targets(matches, elements, page_point_sizes)

            if not targets:
                raise ValueError("LLM이 선택한 요소를 원본 bbox로 매핑하지 못했습니다")

            # LLM이 사용자 요청에 따라 mode/comment_mode를 결정하면 프론트에서 전달된 기본값을 오버라이드한다.
            if llm_mode in ("highlight", "margin_note", "both"):
                mode = llm_mode
            if llm_comment_mode in ("user_text", "llm_summary"):
                comment_mode = llm_comment_mode
            # user_text 모드면 모든 코멘트를 사용자가 입력한 문구 그대로 교체한다.
            if comment_mode == "user_text":
                for t in targets:
                    t.comment = instruction

            # [Flow: 주석 표시 — embedpdf JSON 오버레이 방식]
            # annotate_pdf()로 주석을 PDF에 구워 넣는 대신, 깨끗한 보정 이미지 PDF를
            # 표시 기반으로 두고 embedpdf JSON(AnnotationTransferItem[])을 프론트에서
            # 오버레이한다. 단일 진실원이자 사용자 편집 가능. flatten 다운로드는
            # 프론트의 embedpdf export plugin(saveAsCopy)이 처리한다.
            embedpdf_annotations = build_embedpdf_annotations(pdf_bytes, targets, mode)
            storage_path = f"{job.id}/annotated_{next_index}.pdf"
            annotations_json_storage_path = f"{job.id}/annotated_{next_index}.annotations.json"
            display_name = _annotation_display_name(job, next_index)
            client = supabase_client.get_service_client()
            client.storage.from_("results").upload(
                storage_path,
                pdf_bytes,
                {"content-type": "application/pdf", "upsert": "true"},
            )
            client.storage.from_("results").upload(
                annotations_json_storage_path,
                json.dumps(embedpdf_annotations, ensure_ascii=False).encode("utf-8"),
                {"content-type": "application/json", "upsert": "true"},
            )

            # 동시 쓰기 안전성을 위해 SELECT FOR UPDATE로 행을 잠근다.
            # 해당 index의 processing entry를 done 상태로 갱신한다.
            locked_job = db.execute(
                select(Job).where(Job.id == job_id).with_for_update()
            ).scalar_one()
            files = list(locked_job.annotated_pdf_files or [])
            entry_found = False
            for e in files:
                if e.get("index") == next_index:
                    e["status"] = "done"
                    e["storage_path"] = storage_path
                    e["annotations_json_storage_path"] = annotations_json_storage_path
                    e["filename"] = display_name
                    e["instruction"] = instruction
                    e["mode"] = mode
                    e["comment_mode"] = comment_mode
                    e["created_at"] = datetime.now(timezone.utc).isoformat()
                    entry_found = True
                    break
            if not entry_found:
                # 사용자가 취소하여 entry가 제거된 경우 업로드된 결과 파일을 정리한다.
                supabase_client.delete_storage_path("results", storage_path)
                supabase_client.delete_storage_path("results", annotations_json_storage_path)
                db.rollback()
                return {"job_id": job_id, "status": "cancelled", "matched_rows": 0}
            locked_job.annotated_pdf_files = files
            flag_modified(locked_job, "annotated_pdf_files")
            locked_job.result_annotated_pdf_storage_path = storage_path
            locked_job.annotate_status = "done"
            locked_job.annotate_refundable = False
            locked_job.annotate_recovery_notes = []
            db.commit()
            cache.invalidate_pattern(f"preview:{job_id}:*")
            return {"job_id": job_id, "status": "done", "matched_rows": len(targets)}

    except Exception as e:
        logger.exception(f"[pdf_annotate_converter] {job_id} 주석 생성 실패: {e}")
        tb = traceback.format_exc()
        _update_entry_status(db, job_id, next_index, "error", recovery_notes=[{"reason": str(e), "traceback": tb[-2000:]}])
        return {"job_id": job_id, "status": "error", "error": str(e)}
    finally:
        db.close()


def _update_entry_status(db, job_id: str, annotation_index: int, status: str, recovery_notes: list = None):
    """해당 index의 annotated_pdf_files entry 상태를 갱신한다 (동시 쓰기 안전).

    [Flow: Step 1 (SELECT FOR UPDATE로 행 잠금) -> Step 2 (entry 찾아 status 갱신) -> Step 3 (entry가 없으면 취소된 것으로 간주하고 commit 없이 반환) -> Step 4 (commit)]
    """
    locked_job = db.execute(
        select(Job).where(Job.id == job_id).with_for_update()
    ).scalar_one()
    files = list(locked_job.annotated_pdf_files or [])
    entry_found = False
    for e in files:
        if e.get("index") == annotation_index:
            e["status"] = status
            if recovery_notes is not None:
                e["recovery_notes"] = recovery_notes
            entry_found = True
            break
    if not entry_found:
        # 사용자가 취소하여 entry가 제거된 경우 상태 갱신을 무시한다.
        db.rollback()
        return
    locked_job.annotated_pdf_files = files
    flag_modified(locked_job, "annotated_pdf_files")
    # 하위 호환: 단일 status 필드도 갱신
    locked_job.annotate_status = status
    if status == "error":
        locked_job.annotate_refundable = True
        locked_job.annotate_recovery_notes = recovery_notes or []
    elif status == "done":
        locked_job.annotate_refundable = False
        locked_job.annotate_recovery_notes = recovery_notes or []
    db.commit()
