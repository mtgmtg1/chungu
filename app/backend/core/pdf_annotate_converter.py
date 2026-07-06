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
from .pdf_annotator import AnnotationTarget, build_embedpdf_annotations, _rgb_to_hex
from .pdf_coords import clamp_rect_to_page, px_bbox_to_pdf_rect
from .pdf_text_layer import (
    TextLayerSearcher,
    add_text_layer_from_ocr,
    extract_page_ocr_results_from_layout,
)
from .prompts import build_element_highlight_prompt, build_vision_bbox_highlight_prompt
from .xlsx_advanced_converter import _get_page_image_paths

logger = logging.getLogger(__name__)

RENDER_DPI = 300  # 업로드 시점 렌더링 DPI와 동일해야 bbox 좌표가 맞는다 (최대 300, 저해상도는 자동 낮춤).
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


def _annotation_id(item: dict) -> str:
    """[Flow: Step 1 (EmbedPDF AnnotationTransferItem 형태 확인) -> Step 2 (annotation.id 추출)
          -> Step 3 (ID 문자열 반환)]

    EmbedPDF 주석 객체는 {"annotation": {...}} 또는 평면 dict 형태로 들어올 수 있다.
    """
    if not isinstance(item, dict):
        return ""
    if "annotation" in item and isinstance(item["annotation"], dict):
        return item["annotation"].get("id", "")
    return item.get("id", "")


def _annotation_inner(item: dict) -> dict:
    """[Flow: Step 1 (dict 여부 확인) -> Step 2 (AnnotationTransferItem 형태면 내부 annotation 추출)
          -> Step 3 (평면 dict면 그대로 반환)]

    EmbedPDF AnnotationTransferItem({"annotation": {...}})과 평면 dict 모두에서
    내부 annotation 객체를 추출한다. 주석 속성을 읽거나 갱신할 때 사용한다.
    """
    if not isinstance(item, dict):
        return {}
    if "annotation" in item and isinstance(item["annotation"], dict):
        return item["annotation"]
    return item


def _merge_annotations_for_run(
    shared_annotations_json_path: str,
    new_annotations: list[dict],
    annotation_index: int,
) -> list[dict]:
    """[Flow: Step 1 (공유 annotations.json 다운로드) -> Step 2 (동일 run의 기존 주석 분류)
          -> Step 3 (사용자 편집 주석은 보존, 미편집 주석은 제거) -> Step 4 (새 주석 추가)
          -> Step 5 (병합된 목록 반환)]

    병렬 AI 주석 생성에서 공유 JSON을 안전하게 갱신하기 위해 사용한다.
    실제 호출은 SELECT FOR UPDATE로 잠근 트랜잭션 안에서 이루어져야 한다.

    사용자가 AI 주석을 편집(색상/코멘트/위치/투명도 변경)한 경우, 해당 주석에
    `_userEdited: true` 필드가 설정되어 있으면 재생성 시 덮어쓰지 않고 보존한다.
    이렇게 하면 같은 annotation_index로 재생성해도 사용자의 수동 편집이 유지된다.
    편집되지 않은 동일 run의 주석은 제거한 뒤 새 주석으로 교체하여 멱등성을 보장한다.
    """
    prefix = f"backend-{annotation_index}-"
    client = supabase_client.get_service_client()
    try:
        existing_bytes = client.storage.from_("results").download(shared_annotations_json_path)
        existing = json.loads(existing_bytes.decode("utf-8"))
        if not isinstance(existing, list):
            existing = []
    except Exception:
        existing = []

    # [Flow: 기존 주석을 3그룹으로 분류]
    # - other: 다른 run의 주석 또는 사용자 주석 → 무조건 보존
    # - edited: 같은 run이지만 사용자가 편집한 주석 (_userEdited: true) → 보존
    # - stale: 같은 run이고 편집되지 않은 주석 → 제거 (새 주석으로 교체)
    preserved_edited: list[dict] = []
    preserved_other: list[dict] = []
    for a in existing:
        aid = _annotation_id(a)
        if not aid.startswith(prefix):
            preserved_other.append(a)
            continue
        if _is_user_edited(a):
            preserved_edited.append(a)
            logger.info(f"[pdf_annotate] 사용자 편집 주석 보존: {aid}")
        # stale 주석은 버린다

    return preserved_other + preserved_edited + new_annotations


def _is_user_edited(item: dict) -> bool:
    """[Flow: Step 1 (annotation 객체 추출) -> Step 2 (_userEdited 필드 확인) -> Step 3 (반환)]

    주석 객체에 _userEdited: true 필드가 있으면 사용자가 편집한 것으로 간주한다.
    EmbedPDF AnnotationTransferItem 형태({"annotation": {...}})와 평면 dict 모두 지원한다.
    """
    if not isinstance(item, dict):
        return False
    if "annotation" in item and isinstance(item["annotation"], dict):
        return bool(item["annotation"].get("_userEdited", False))
    return bool(item.get("_userEdited", False))


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
) -> tuple[list[AnnotateElement], dict[int, Path], dict[int, dict]]:
    """모든 페이지를 렌더링하고 PaddleOCR bbox를 확보해 텍스트 요소 목록을 반환한다.

    [Flow: Step 1 (페이지 이미지 로드) -> Step 2 (deskew 미세 회전 보정) -> Step 3 (PaddleOCR 전송 + bbox + angle_code 수신)
          -> Step 4 (angle_code로 90° 회전 적용한 최종 이미지 준비) -> Step 5 (표 행 + 텍스트 블록 수집)
          -> Step 6 (layout 원본 보관 — 텍스트 레이어 생성용)]

    표의 행(table_row)과 텍스트 블록(text)을 모두 수집한다.
    반환하는 corrected_images는 "deskew + 90° 대회전 보정이 모두 완료된 정돈된 이미지"이며,
    이 이미지들로 주석 PDF를 생성하면 bbox와 완벽히 정렬된다.

    Returns:
        (elements, corrected_images, layout_by_page) —
        elements: 주석 대상 텍스트 요소 목록 (bbox는 보정된 이미지 기준)
        corrected_images: page_no(1-based) → 정돈된 페이지 이미지 경로
        layout_by_page: page_no → PaddleOCR layout 원본 dict (overall_ocr_res 포함)
    """
    image_paths = _get_page_image_paths(job, temp_dir)
    elements: list[AnnotateElement] = []
    corrected_images: dict[int, Path] = {}
    layout_by_page: dict[int, dict] = {}

    for page_no in sorted(image_paths.keys()):
        img_path = image_paths[page_no]
        try:
            _markdown, layout_raw, angle_code = paddleocr_client.convert_image_with_layout(img_path)
        except Exception as e:
            logger.warning(f"[pdf_annotate] page={page_no} PaddleOCR 레이아웃 확보 실패: {e}")
            continue

        layout_by_page[page_no] = layout_raw or {}

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

    return elements, corrected_images, layout_by_page


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


def _render_pdf_to_image_paths(
    pdf_bytes: bytes,
    temp_dir: Path,
    dpi: int = RENDER_DPI,
) -> dict[int, Path]:
    """[Flow: Step 1 (PDF bytes를 임시 파일로 저장) -> Step 2 (ocr_client.render_pdf로 페이지 이미지 렌더링)
          -> Step 3 (페이지 번호 추출) -> Step 4 (page_no → 이미지 경로 매핑 반환)]

    searchable PDF 등 외부에서 이미 확보된 PDF bytes로부터 페이지 이미지를 생성한다.
    """
    image_paths: dict[int, Path] = {}
    input_path = temp_dir / "input.pdf"
    input_path.write_bytes(pdf_bytes)
    try:
        ocr_client.render_pdf(str(input_path), str(temp_dir), dpi=dpi)
        for p in sorted(temp_dir.glob("page-*.png")):
            try:
                page_num = int(p.stem.split("-")[-1])
                image_paths[page_num] = p
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"[_render_pdf_to_image_paths] PDF 렌더링 실패: {e}")
    return image_paths


def _collect_page_elements_from_searchable_pdf(
    pdf_bytes: bytes,
    temp_dir: Path,
    dpi: int = RENDER_DPI,
) -> tuple[list[AnnotateElement], dict[int, Path]]:
    """[Flow: Step 1 (searchable PDF 열기) -> Step 2 (페이지별 이미지 렌더링 + deskew 보정)
          -> Step 3 (텍스트 레이어에서 텍스트 블록 추출) -> Step 4 (AnnotateElement 생성)]

    searchable PDF의 텍스트 레이어에서 이미 OCR이 완료된 텍스트/bbox를 추출해
    AnnotateElement 목록과 페이지 이미지를 반환한다. 별도 PaddleOCR 호출 없이
    AI 주석 생성에 필요한 요소를 확보한다. 렌더링된 페이지 이미지에 deskew를 적용해
    기울어진 스캔 문서도 수평으로 정렬된 주석 PDF 표시 이미지를 제공한다.
    """
    scale = dpi / 72.0
    elements: list[AnnotateElement] = []
    corrected_images: dict[int, Path] = {}

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for page in doc:
            page_no = page.number + 1
            raw_img_path = temp_dir / f"page-raw-{page_no:04d}.png"
            try:
                pix = page.get_pixmap(dpi=dpi)
                pix.save(str(raw_img_path))
            except Exception as e:
                logger.warning(f"[_collect_page_elements_from_searchable_pdf] page={page_no} 이미지 렌더링 실패: {e}")
                continue

            # deskew 보정 적용
            deskewed_path, _applied = deskew_image(raw_img_path, output_dir=temp_dir / "deskewed")
            img_path = temp_dir / f"page-{page_no:04d}.png"
            if deskewed_path != raw_img_path:
                # deskew가 적용된 경우 최종 경로로 복사/이동
                import shutil
                shutil.move(str(deskewed_path), str(img_path))
            else:
                # deskew 미적용 시 원본을 최종 경로로 이동
                import shutil
                shutil.move(str(raw_img_path), str(img_path))
            corrected_images[page_no] = img_path

            # 이미지 픽셀 높이 (y축 flip용: PDF 좌표계 y↑ → 이미지 좌표계 y↓)
            page_height_px = page.rect.height * scale

            blocks = page.get_text("blocks")
            for block in blocks:
                try:
                    x0, y0, x1, y1, text, _block_no, _block_type = block
                except Exception:
                    continue
                if not text or not text.strip():
                    continue
                # PDF 좌표계(y↑) → 이미지 좌표계(y↓)로 변환
                img_y0 = page_height_px - y1 * scale  # bbox 상단(PDF) → 이미지 상단(y↓)
                img_y1 = page_height_px - y0 * scale  # bbox 하단(PDF) → 이미지 하단(y↓)
                bbox_px: BBox = (int(x0 * scale), int(img_y0), int(x1 * scale), int(img_y1))
                elements.append(AnnotateElement(
                    page_no=page_no,
                    bbox_px=bbox_px,
                    kind="text",
                    text=text.strip(),
                    word_bboxes=[],
                    cell_texts=[],
                    cell_bboxes=[],
                ))
    finally:
        doc.close()
    return elements, corrected_images


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


def _parse_opacity(value) -> float | None:
    """LLM이 반환한 opacity 값을 0.0~1.0 float로 변환한다. None/무효면 None 반환.

    [Flow: Step 1 (None/빈 값 확인) -> Step 2 (0~100 정수면 백분율로 변환)
          -> Step 3 (float 변환 + 0.0~1.0 clamp) -> Step 4 (유효하면 반환, 아니면 None)]

    사용자가 "50%", "0.3", "30%" 등으로 요청한 경우를 처리한다.
    0~1 범위면 그대로, 1~100 범위면 백분율로 간주해 100으로 나눈다.
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (ValueError, TypeError):
        return None
    # 1~100 범위면 백분율로 간주 (예: 50 → 0.5, 30 → 0.3)
    if v > 1.0:
        v = v / 100.0
    return max(0.0, min(1.0, v))


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
    text_searcher: TextLayerSearcher | None = None,
) -> list[AnnotationTarget]:
    """LLM이 반환한 match 목록을 AnnotationTarget 목록으로 변환한다 (scope/색상 적용).

    [Flow: Step 1 (match 순회) -> Step 2 (element_index 유효성 검사)
          -> Step 3 (텍스트 레이어 검색 우선 — 없으면 OCR bbox 사용) -> Step 4 (페이지 범위 clamp)
          -> Step 5 (AnnotationTarget 생성)]

    텍스트 레이어가 추가된 PDF가 있으면, OCR bbox 변환 대신 PDF 텍스트 레이어에서 직접
    텍스트를 검색하여 bbox를 얻는다. 이 방식은 좌표 변환 오차 없이 정확한 위치를 제공한다.
    """
    targets: list[AnnotationTarget] = []
    for m in matches:
        idx = m.get("element_index")
        if not isinstance(idx, int) or idx < 0 or idx >= len(elements):
            continue
        el = elements[idx]
        scope = m.get("highlight_scope")
        narrowed_bbox = _narrow_bbox_by_scope(el, scope)
        bbox_px = narrowed_bbox if narrowed_bbox is not None else el.bbox_px

        # 텍스트 레이어에서 직접 검색하면 bbox 변환 오차를 피할 수 있다.
        rect_pdf: tuple[float, float, float, float] | None = None
        if text_searcher is not None:
            search_text = el.text.replace(" | ", " ").strip()[:80]
            if search_text:
                found = text_searcher.search(el.page_no, search_text)
                if found:
                    rect_pdf = found[0]
                    logger.info(f"[pdf_annotate] 텍스트 레이어 검색 성공 page={el.page_no}: '{search_text[:30]}'")
                else:
                    logger.info(f"[pdf_annotate] 텍스트 레이어 검색 실패 page={el.page_no}: '{search_text[:30]}'")

        if rect_pdf is None:
            # 폴백: 픽셀 bbox를 PDF 좌표로 변환 (y축 flip 포함)
            page_pt = page_point_sizes.get(el.page_no)
            if page_pt:
                page_height_px = page_pt[1] * RENDER_DPI / 72.0
                rect_pdf = px_bbox_to_pdf_rect(bbox_px, dpi=RENDER_DPI, page_height_px=page_height_px)
            else:
                rect_pdf = px_bbox_to_pdf_rect(bbox_px, dpi=RENDER_DPI)

        page_pt = page_point_sizes.get(el.page_no)
        if page_pt:
            rect_pdf = clamp_rect_to_page(rect_pdf, page_pt[0], page_pt[1])
        comment = str(m.get("comment") or "").strip()
        color_name = m.get("color")
        color = _color_name_to_rgb(color_name)
        # 사용자가 명시적으로 색상을 요청한 경우에만 callout에도 같은 색 적용.
        # 요청이 없으면 callout_color=None → pdf_annotator에서 DEFAULT_CALLOUT_COLOR(보라) 사용.
        callout_color = color if color_name else None
        # 사용자가 투명도를 요청한 경우에만 opacity 설정. 없으면 None → 기본 0.5.
        opacity = _parse_opacity(m.get("opacity"))
        targets.append(AnnotationTarget(
            page_no=el.page_no, bbox_pdf=rect_pdf, comment=comment,
            color=color, callout_color=callout_color, opacity=opacity,
        ))
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
                rect_pdf = px_bbox_to_pdf_rect((x0, y0, x1, y1), dpi=RENDER_DPI, page_height_px=img_h)
                comment = str(m.get("comment") or "").strip()
                color_name = m.get("color")
                color = _color_name_to_rgb(color_name)
                callout_color = color if color_name else None
                opacity = _parse_opacity(m.get("opacity"))
                targets.append(AnnotationTarget(
                    page_no=page_no, bbox_pdf=rect_pdf, comment=comment,
                    color=color, callout_color=callout_color, opacity=opacity,
                ))
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
    page_range: list[int] | None = None,
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
        page_range: 처리할 1-based 페이지 번호 리스트. None이면 전체 페이지를 처리한다.
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

            # [Flow: searchable PDF가 있으면 이를 사용 — OCR 중복 방지]
            searchable_pdf_bytes: bytes | None = None
            if job.searchable_pdf_storage_path:
                try:
                    searchable_pdf_bytes = supabase_client.download_pdf(job.searchable_pdf_storage_path).read()
                    logger.info(f"[pdf_annotate] searchable PDF 사용: {job.searchable_pdf_storage_path}")
                except Exception as e:
                    logger.warning(f"[pdf_annotate] searchable PDF 다운로드 실패, 원본 PDF 사용: {e}")

            if searchable_pdf_bytes:
                image_paths = _render_pdf_to_image_paths(searchable_pdf_bytes, temp_dir, dpi=RENDER_DPI)
            else:
                image_paths = _get_page_image_paths(job, temp_dir)
            if not image_paths:
                raise ValueError("원본 파일을 이미지로 렌더링하지 못해 주석을 생성할 수 없습니다")

            # [Flow: 페이지 범위 필터링 — 지정한 페이지만 처리하여 LLM 프롬프트 폭주 방지]
            # page_range가 None이면 전체 페이지를 처리한다 (현행 동작).
            # page_range는 1-based 페이지 번호 리스트이며, image_paths/elements/targets에 모두 적용된다.
            if page_range is not None:
                page_set = set(page_range)
                image_paths = {p: path for p, path in image_paths.items() if p in page_set}
                if not image_paths:
                    _update_entry_status(db, job_id, next_index, "done", recovery_notes=[{"reason": "지정한 페이지 범위에 해당하는 페이지가 없습니다"}])
                    return {"job_id": job_id, "status": "done", "matched_rows": 0}
                logger.info(f"[pdf_annotate] page_range 필터 적용: {sorted(page_set)} ({len(image_paths)}페이지)")

            llm_mode: str | None = None
            llm_comment_mode: str | None = None
            elements: list[AnnotateElement] = []  # callout 배치 시 충돌 회피용 (고급주석 경로에서는 미사용)
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
                if searchable_pdf_bytes:
                    # [Flow: searchable PDF 기반 AI 주석 — OCR 생략]
                    # 업로드 시점에 이미 생성된 searchable PDF의 텍스트 레이어에서 요소를 추출하고
                    # 동일한 PDF를 주석 베이스로 재사용한다. 별도 PaddleOCR 호출이 없어 훨씬 빠르다.
                    elements, corrected_images = _collect_page_elements_from_searchable_pdf(
                        searchable_pdf_bytes, temp_dir, dpi=RENDER_DPI
                    )
                    if not elements:
                        raise ValueError("searchable PDF에서 텍스트 요소를 찾을 수 없습니다")
                    if not corrected_images:
                        raise ValueError("searchable PDF에서 페이지 이미지를 생성하지 못해 주석 PDF를 만들 수 없습니다")
                    pdf_bytes = searchable_pdf_bytes
                    page_point_sizes = _page_point_sizes(pdf_bytes)
                else:
                    # [Flow: 주석 PDF 베이스 — 정돈된 이미지(deskew + 90° 대회전 보정 완료)로 PDF 생성]
                    # 원본 PDF를 사용하지 않고 보정된 페이지 이미지로 새 PDF를 생성한다.
                    # 이유: bbox가 "deskew + AI Studio 90° 보정된 이미지" 기준으로 반환되므로,
                    # 주석 PDF의 베이스도 동일하게 보정된 이미지여야 bbox와 완벽히 정렬된다.
                    # 원본 PDF 벡터 품질 손실(텍스트 선택 불가)은 사용자가 명시적으로 수용한 트레이드오프.
                    elements, corrected_images, layout_by_page = _collect_page_elements(job, temp_dir)
                    if not elements:
                        raise ValueError("텍스트 요소를 인식하지 못해 하이라이트/여백 주석 대상을 찾을 수 없습니다")
                    if not corrected_images:
                        raise ValueError("보정된 페이지 이미지를 생성하지 못해 주석 PDF를 만들 수 없습니다")

                    pdf_bytes = _images_to_pdf(corrected_images)
                    page_point_sizes = _page_point_sizes(pdf_bytes)

                    # [Flow: 텍스트 레이어 추가 — OCR 결과로 검색/선택 가능한 PDF 생성]
                    # 텍스트 레이어가 있으면 AI 주석 생성 시 텍스트 검색으로 정확한 bbox를 얻는다.
                    page_ocr_results = extract_page_ocr_results_from_layout(layout_by_page)
                    if page_ocr_results:
                        pdf_bytes = add_text_layer_from_ocr(
                            pdf_bytes, page_ocr_results, dpi=RENDER_DPI, language=language
                        )
                        page_point_sizes = _page_point_sizes(pdf_bytes)

                # [Flow: elements를 페이지 범위로 필터링 — LLM에 지정 페이지 요소만 전달]
                if page_range is not None:
                    page_set = set(page_range)
                    elements = [e for e in elements if e.page_no in page_set]

                matches, llm_mode, llm_comment_mode = _select_elements_with_llm(
                    elements, instruction, endpoint, model, api_key
                )
                if not matches:
                    _update_entry_status(db, job_id, next_index, "done", recovery_notes=[{"reason": "조건에 맞는 요소를 찾지 못했습니다"}])
                    return {"job_id": job_id, "status": "done", "matched_rows": 0}

                text_searcher = None
                if pdf_bytes:
                    text_searcher = TextLayerSearcher(pdf_bytes)
                try:
                    targets = _matches_to_targets(matches, elements, page_point_sizes, text_searcher)
                finally:
                    if text_searcher:
                        text_searcher.close()

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
            # 깨끗한 보정 이미지 PDF를 표시 기반으로 두고 embedpdf JSON(AnnotationTransferItem[])을
            # 프론트에서 오버레이한다. 하이라이트는 HIGHLIGHT, 코멘트는 FreeTextCallout(텍스트 박스 +
            # 화살표 리더 라인)로 생성한다. callout 텍스트 박스는 기존 요소를 피해 페이지 내 빈
            # 모서리/외곽 여백에 배치된다. 단일 진실원이자 사용자 편집 가능. flatten 다운로드는
            # 프론트의 embedpdf export plugin(saveAsCopy)이 처리한다.
            # job당 하나의 공유 파일에 누적되며, run별로 고유 ID prefix를 가진다.
            shared_storage_path = f"{job.id}/annotated.pdf"
            shared_annotations_json_path = f"{job.id}/annotated.annotations.json"
            display_name = _annotation_display_name(job, 1)

            # [Flow: 기존 공유 PDF가 있으면 재사용하여 사용자 주석 보존]
            # 사용자가 이미 AI 주석 PDF에 그린 주석을 덮어쓰지 않도록, Storage에
            # 기존 PDF가 있으면 그것을 표시 기반으로 재사용한다. 텍스트 내용은
            # 원본과 동일하므로 AI 주석 좌표 정렬에 영향을 주지 않는다.
            client = supabase_client.get_service_client()
            existing_pdf_bytes = None
            should_upload_pdf = False
            try:
                existing_pdf_bytes = client.storage.from_("results").download(shared_storage_path)
            except Exception:
                existing_pdf_bytes = None
            if existing_pdf_bytes:
                pdf_bytes = existing_pdf_bytes
                logger.info(f"[pdf_annotate] 기존 공유 PDF 재사용: {shared_storage_path}")
            else:
                should_upload_pdf = True

            # [Flow: callout 배치용 페이지 요소 bbox — 기존 텍스트 요소를 피해 텍스트 박스 배치]
            # elements의 bbox_px를 PDF user-space 좌표로 변환해 페이지별로 그룹화한다.
            # 고급주석(Vision LLM) 경로에서는 elements가 비어 있어 충돌 검사 없이 모서리에 배치된다.
            page_elements_bboxes: dict[int, list[tuple[float, float, float, float]]] = {}
            for el in elements:
                page_pt = page_point_sizes.get(el.page_no)
                if page_pt:
                    page_height_px = page_pt[1] * RENDER_DPI / 72.0
                    rect_pdf = px_bbox_to_pdf_rect(el.bbox_px, dpi=RENDER_DPI, page_height_px=page_height_px)
                else:
                    rect_pdf = px_bbox_to_pdf_rect(el.bbox_px, dpi=RENDER_DPI)
                page_elements_bboxes.setdefault(el.page_no, []).append(rect_pdf)

            embedpdf_annotations = build_embedpdf_annotations(
                pdf_bytes, targets, mode, annotation_index=next_index,
                page_elements_bboxes=page_elements_bboxes,
            )

            # 동시 쓰기 안전성을 위해 SELECT FOR UPDATE로 행을 잠근다.
            # 공유 annotations.json에 새 주석을 병합하고, 공유 PDF/JSON을 업로드한다.
            locked_job = db.execute(
                select(Job).where(Job.id == job_id).with_for_update()
            ).scalar_one()
            files = list(locked_job.annotated_pdf_files or [])
            entry_found = any(e.get("index") == next_index for e in files)
            if not entry_found:
                # 사용자가 취소하여 entry가 제거된 경우 업로드하지 않고 종료한다.
                db.rollback()
                return {"job_id": job_id, "status": "cancelled", "matched_rows": 0}

            merged_annotations = _merge_annotations_for_run(
                shared_annotations_json_path, embedpdf_annotations, next_index
            )
            if should_upload_pdf:
                client.storage.from_("results").upload(
                    shared_storage_path,
                    pdf_bytes,
                    {"content-type": "application/pdf", "upsert": "true"},
                )
            client.storage.from_("results").upload(
                shared_annotations_json_path,
                json.dumps(merged_annotations, ensure_ascii=False).encode("utf-8"),
                {"content-type": "application/json", "upsert": "true"},
            )

            for e in files:
                if e.get("index") == next_index:
                    e["status"] = "done"
                    e["storage_path"] = shared_storage_path
                    e["annotations_json_storage_path"] = shared_annotations_json_path
                    e["filename"] = display_name
                    e["instruction"] = instruction
                    e["mode"] = mode
                    e["comment_mode"] = comment_mode
                    e["created_at"] = datetime.now(timezone.utc).isoformat()
                    e["generated_annotation_ids"] = [
                        _annotation_id(a) for a in embedpdf_annotations
                    ]
                    break
            locked_job.annotated_pdf_files = files
            flag_modified(locked_job, "annotated_pdf_files")
            locked_job.result_annotated_pdf_storage_path = shared_storage_path
            # 병렬 run 중 processing이 남아 있으면 전체 상태를 processing으로 유지한다.
            has_processing = any(e.get("status") == "processing" for e in files)
            locked_job.annotate_status = "processing" if has_processing else "done"
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
    # 하위 호환: 단일 status 필드도 갱신. 병렬 run이 있을 때는 전체 상태를 반영한다.
    has_processing = any(e.get("status") == "processing" for e in files)
    has_error = any(e.get("status") == "error" for e in files)
    if has_processing:
        locked_job.annotate_status = "processing"
    elif has_error:
        locked_job.annotate_status = "error"
    else:
        locked_job.annotate_status = "done" if files else ""
    if status == "error":
        locked_job.annotate_refundable = True
        locked_job.annotate_recovery_notes = recovery_notes or []
    elif status == "done":
        locked_job.annotate_refundable = False
        locked_job.annotate_recovery_notes = recovery_notes or []
    db.commit()


def run_edit(
    job_id: str,
    instruction: str,
    page_range: list[int] | None,
    annotation_index: int,
) -> dict:
    """[Flow: Step 1 (공유 annotations.json 다운로드) -> Step 2 (page_range로 편집 대상 AI 주석 추출)
          -> Step 3 (LLM으로 색상/코멘트 재편집) -> Step 4 (기존 주석의 id/rect는 유지하고 속성만 갱신)
          -> Step 5 (병합 후 annotations.json 업로드) -> Step 6 (entry 상태 done 갱신)]

    기존 AI 주석의 색상/코멘트를 사용자 instruction에 맞게 LLM으로 재편집한다.
    지정한 페이지 범위의 기존 AI 주석(backend-* prefix, _userEdited 아님)만 편집 대상으로 삼고,
    사용자 수동 편집 주석과 다른 페이지의 주석은 건드리지 않는다.
    기존 주석의 id/rect/calloutLine/pageIndex는 유지하고 color/contents만 갱신하여
    embedpdf에서 같은 주석으로 인식되도록 한다.

    Args:
        job_id: 작업 ID
        instruction: 사용자가 입력한 편집 조건 (예: "색상을 빨간색으로", "코멘트를 간결하게")
        page_range: 편집 대상 1-based 페이지 번호 리스트. None이면 전체 페이지.
        annotation_index: API 수준에서 원자적으로 할당된 고유 인덱스 (entry 추적용)
    """
    db = SessionLocal()
    job = db.get(Job, job_id)
    if job is None:
        db.close()
        return {"error": "job not found"}

    next_index = annotation_index
    endpoint = job.endpoint or settings_store.get_setting(db, "llm_endpoint") or settings.default_llm_endpoint
    model = job.model or settings_store.get_setting(db, "llm_model") or settings.default_llm_model
    api_key = settings_store.get_setting(db, "llm_api_key") or ""

    try:
        shared_annotations_json_path = f"{job.id}/annotated.annotations.json"
        client = supabase_client.get_service_client()

        # [Flow: Step 1 — 공유 annotations.json 다운로드]
        try:
            existing_bytes = client.storage.from_("results").download(shared_annotations_json_path)
            existing = json.loads(existing_bytes.decode("utf-8"))
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []

        if not existing:
            _update_entry_status(db, job_id, next_index, "done", recovery_notes=[{"reason": "편집할 기존 주석이 없습니다"}])
            return {"job_id": job_id, "status": "done", "edited_count": 0}

        # [Flow: Step 2 — page_range로 편집 대상 AI 주석 추출]
        # backend-* prefix 주석만 편집 대상 (사용자 주석 제외).
        # _userEdited 주석은 사용자가 수동 편집한 것이므로 보존 (제외).
        # page_range는 1-based, 주석의 pageIndex는 0-based이므로 +1 변환.
        page_set = set(page_range) if page_range else None
        editable: list[dict] = []
        for item in existing:
            aid = _annotation_id(item)
            if not aid.startswith("backend-"):
                continue
            if _is_user_edited(item):
                continue
            ann = _annotation_inner(item)
            page_index = ann.get("pageIndex")
            if page_index is None:
                continue
            page_no = page_index + 1
            if page_set is not None and page_no not in page_set:
                continue
            atype = str(ann.get("type", "")).lower()
            intent = str(ann.get("intent", "")).lower()
            is_callout = atype in ("freetext", "freetextcallout") or intent == "freetextcallout"
            comment = ann.get("contents", "") or ""
            color = ann.get("color", "") or ann.get("strokeColor", "") or ""
            # callout 주석은 comment를 원본 텍스트로 전달해 LLM이 재작성 가능.
            # 하이라이트 주석은 원본 텍스트 추출을 생략하고 comment만 전달 (색상 변경 중심).
            text = comment if is_callout else ""
            editable.append({
                "id": aid,
                "type": "callout" if is_callout else "highlight",
                "color": color,
                "comment": comment,
                "text": text,
                "_item": item,
            })

        if not editable:
            _update_entry_status(db, job_id, next_index, "done", recovery_notes=[{"reason": "지정한 페이지에 편집할 AI 주석이 없습니다"}])
            return {"job_id": job_id, "status": "done", "edited_count": 0}

        # [Flow: Step 3 — LLM으로 색상/코멘트 재편집]
        from .prompts import build_annotation_edit_prompt
        prompt = build_annotation_edit_prompt(
            [{"id": a["id"], "type": a["type"], "color": a["color"], "comment": a["comment"], "text": a["text"]} for a in editable],
            instruction,
        )
        content, _ = ocr_client.call_text(prompt, endpoint, model, api_key, max_tokens=4000)
        content = _strip_json_fence(content)
        try:
            data = json.loads(content)
        except Exception as e:
            raise ValueError(f"LLM 응답 JSON 파싱 실패: {e} (content={content[:200]})")
        edits = data.get("edits", []) if isinstance(data, dict) else []
        if not isinstance(edits, list):
            edits = []

        # 색상 이름 → hex 매핑 (HIGHLIGHT_COLOR_PALETTE 기반)
        color_name_to_hex = {name: _rgb_to_hex(rgb) for name, rgb in HIGHLIGHT_COLOR_PALETTE.items()}
        edits_by_id: dict[str, dict] = {}
        for e in edits:
            if not isinstance(e, dict) or "id" not in e:
                continue
            edits_by_id[str(e["id"])] = e

        # [Flow: Step 4 — 기존 주석의 id/rect는 유지하고 color/contents만 갱신]
        edited_count = 0
        for a in editable:
            edit = edits_by_id.get(a["id"])
            if edit is None:
                continue
            ann = _annotation_inner(a["_item"])
            new_color_name = str(edit.get("color", "")).strip().lower()
            if new_color_name in color_name_to_hex:
                new_hex = color_name_to_hex[new_color_name]
                ann["color"] = new_hex
                # callout 주석은 strokeColor(테두리/리더 라인 색)도 함께 갱신
                if "strokeColor" in ann:
                    ann["strokeColor"] = new_hex
            new_comment = edit.get("comment")
            if new_comment is not None and str(new_comment).strip():
                ann["contents"] = str(new_comment).strip()
            edited_count += 1

        # [Flow: Step 5 — 병합: 편집 대상이 아닌 주석 보존, 편집 대상은 갱신된 버전으로 교체]
        edited_ids = {a["id"] for a in editable}
        editable_by_id = {a["id"]: a["_item"] for a in editable}
        preserved: list[dict] = []
        for item in existing:
            aid = _annotation_id(item)
            if aid in edited_ids:
                preserved.append(editable_by_id[aid])
            else:
                preserved.append(item)

        # 동시 쓰기 안전성을 위해 SELECT FOR UPDATE로 행 잠금
        locked_job = db.execute(
            select(Job).where(Job.id == job_id).with_for_update()
        ).scalar_one()
        files = list(locked_job.annotated_pdf_files or [])
        entry_found = any(e.get("index") == next_index for e in files)
        if not entry_found:
            # 사용자가 취소하여 entry가 제거된 경우 업로드하지 않고 종료한다.
            db.rollback()
            return {"job_id": job_id, "status": "cancelled", "edited_count": 0}

        client.storage.from_("results").upload(
            shared_annotations_json_path,
            json.dumps(preserved, ensure_ascii=False).encode("utf-8"),
            {"content-type": "application/json", "upsert": "true"},
        )

        # [Flow: Step 6 — entry 상태 done 갱신]
        for e in files:
            if e.get("index") == next_index:
                e["status"] = "done"
                e["instruction"] = instruction
                e["page_range"] = page_range
                e["edited_count"] = edited_count
                e["annotations_json_storage_path"] = shared_annotations_json_path
                e["created_at"] = datetime.now(timezone.utc).isoformat()
                break
        locked_job.annotated_pdf_files = files
        flag_modified(locked_job, "annotated_pdf_files")
        has_processing = any(e.get("status") == "processing" for e in files)
        locked_job.annotate_status = "processing" if has_processing else "done"
        locked_job.annotate_refundable = False
        db.commit()
        cache.invalidate_pattern(f"preview:{job_id}:*")
        logger.info(f"[pdf_annotate_edit] {job_id} 주석 편집 완료: {edited_count}개 갱신")
        return {"job_id": job_id, "status": "done", "edited_count": edited_count}

    except Exception as e:
        logger.exception(f"[pdf_annotate_edit] {job_id} 주석 편집 실패: {e}")
        tb = traceback.format_exc()
        _update_entry_status(db, job_id, next_index, "error", recovery_notes=[{"reason": str(e), "traceback": tb[-2000:]}])
        return {"job_id": job_id, "status": "error", "error": str(e)}
    finally:
        db.close()
