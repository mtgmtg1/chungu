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
from io import BytesIO
from pathlib import Path

import fitz  # PyMuPDF
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from .. import settings_store
from ..config import settings
from ..db.models import Job, User
from ..db.session import SessionLocal
from . import cache, ocr_client, paddleocr_client, supabase_client
from .image_deskew import deskew_image
from .ocr_layout import BBox, OcrRow, OcrTextBlock, parse_layout_result
from .pdf_annotator import AnnotationTarget, build_embedpdf_annotations
from .pdf_coords import PDF_POINTS_PER_INCH
from .pdf_text_layer import (
    TextLayerSearcher,
    add_text_layer_from_ocr,
    extract_page_ocr_results_from_layout,
)
from .prompts import (
    build_text_search_highlight_prompt,
    build_vision_text_highlight_prompt,
)
from .xlsx_advanced_converter import _get_page_image_paths

logger = logging.getLogger(__name__)

RENDER_DPI = 300  # 업로드 시점 렌더링 DPI와 동일해야 bbox 좌표가 맞는다 (최대 300, 저해상도는 자동 낮춤).
MAX_TEXT_BLOCK_CHARS = 200  # 텍스트 블록은 앞 200자만 LLM에 전달 (토큰 폭증 방지)
MAX_PAGE_TEXT_CHARS_FOR_LLM = 3000  # 검색 가능한 PDF의 페이지 텍스트는 페이지당 최대 3000자까지 LLM에 전달

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


def _searchable_display_name(job: Job) -> str:
    """searchable PDF의 표시용 파일명을 생성한다.

    원본 파일명이 있으면 확장자를 제거하고 `_searchable.pdf`를 붙이고,
    없으면 `result_searchable.pdf`를 반환한다.
    """
    base = job.original_filename or "result"
    stem = Path(base).stem or base
    return f"{stem}_searchable.pdf"


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
    """[Flow: Step 1 (item이 dict인지 확인) -> Step 2 (annotation 내부 dict 추출) -> Step 3 (반환)]

    EmbedPDF AnnotationTransferItem에서 내부 annotation dict를 추출한다 (평면 dict도 지원).
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
    bbox_px: BBox  # PDF user-space 좌표 (x0, y0, x1, y1) — _collect_page_elements_*에서 변환 완료
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


def _extract_pages_to_pdf(
    input_pdf_path: Path,
    output_pdf_path: Path,
    page_range: list[int],
) -> None:
    """원본 PDF에서 지정한 페이지만 추출해 새 PDF를 생성한다.

    [Flow: Step 1 (원본 PDF 열기) -> Step 2 (page_range에 해당하는 페이지 선택)
          -> Step 3 (새 PDF에 페이지 복사) -> Step 4 (저장)]

    Args:
        input_pdf_path: 원본 PDF 경로
        output_pdf_path: 출력 PDF 경로
        page_range: 1-based 페이지 번호 리스트
    """
    doc = fitz.open(str(input_pdf_path))
    new_doc = fitz.open()
    for page_no in page_range:
        if 1 <= page_no <= len(doc):
            new_doc.insert_pdf(doc, from_page=page_no - 1, to_page=page_no - 1)
    new_doc.save(str(output_pdf_path))
    new_doc.close()
    doc.close()


def _collect_page_elements_image(
    job: Job,
    temp_dir: Path,
    page_range: list[int] | None = None,
) -> tuple[list[AnnotateElement], dict[int, Path], dict[int, dict]]:
    """페이지를 렌더링하고 PaddleOCR bbox를 확보해 텍스트 요소 목록을 반환한다 (이미지 입력 경로).

    [Flow: Step 1 (page_range가 주어지면 해당 페이지만 이미지화) -> Step 2 (deskew 미세 회전 보정)
          -> Step 3 (PaddleOCR 전송 + bbox + angle_code 수신)
          -> Step 4 (angle_code로 90° 회전 적용한 최종 이미지 준비) -> Step 5 (표 행 + 텍스트 블록 수집)
          -> Step 6 (layout 원본 보관 — 텍스트 레이어 생성용)]

    표의 행(table_row)과 텍스트 블록(text)을 모두 수집한다.
    반환하는 corrected_images는 "deskew + 90° 대회전 보정이 모두 완료된 정돈된 이미지"이며,
    이 이미지들로 주석 PDF를 생성하면 bbox와 완벽히 정렬된다.
    """
    image_paths = _get_page_image_paths(job, temp_dir, page_range=page_range)
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

    # PaddleOCR layout bbox 좌표계를 감지해 PDF user-space로 변환한다.
    # 서비스 버전/응답에 따라 normalized, 픽셀, top-left points 등이 섞여 있을 수 있다.
    if elements and corrected_images:
        pdf_bytes = _images_to_pdf(corrected_images)
        page_rects = _page_rects(pdf_bytes)
        for el in elements:
            rect = page_rects.get(el.page_no)
            if not rect:
                continue
            layout_raw = layout_by_page.get(el.page_no)
            el.bbox_px = _layout_bbox_to_pdf_user(layout_raw, el.bbox_px, rect, dpi=dpi)
            el.word_bboxes = [
                _layout_bbox_to_pdf_user(layout_raw, b, rect, dpi=dpi)
                for b in el.word_bboxes
            ]

    return elements, corrected_images, layout_by_page


def _collect_page_elements_pdf_direct(
    job: Job,
    temp_dir: Path,
    page_range: list[int] | None = None,
) -> tuple[list[AnnotateElement], dict[int, Path], dict[int, dict]]:
    """원본 PDF를 PaddleOCR 서비스에 직접 제출해 텍스트 요소를 수집한다 (PDF 원본 입력 경로).

    [Flow: Step 1 (원본 PDF 다운로드) -> Step 2 (page_range가 주어지면 해당 페이지만 추출)
          -> Step 3 (원본 PDF를 PaddleOCR /api/convert/pdf에 직접 업로드)
          -> Step 4 (페이지별 layout + angle_code 수신)
          -> Step 5 (원본 페이지 이미지 렌더링 + angle_code 회전 보정)
          -> Step 6 (표 행 + 텍스트 블록 수집) -> Step 7 (layout 원본 보관)]

    AI Studio API는 10페이지 이하 원본 PDF만 직접 처리할 수 있으므로,
    이 함수는 /api/convert/pdf가 지원하는 범위 내에서만 사용해야 한다.
    """
    elements: list[AnnotateElement] = []
    corrected_images: dict[int, Path] = {}
    layout_by_page: dict[int, dict] = {}

    if not job.pdf_storage_path:
        logger.warning("[pdf_annotate] PDF 직접 입력 경로: pdf_storage_path가 없어 이미지 경로로 폴백")
        return _collect_page_elements_image(job, temp_dir, page_range)

    try:
        input_bytes = supabase_client.download_pdf(job.pdf_storage_path).read()
        input_path = temp_dir / "input.pdf"
        input_path.write_bytes(input_bytes)
    except Exception as e:
        logger.warning(f"[pdf_annotate] PDF 직접 입력 경로: 원본 PDF 다운로드 실패, 이미지 경로로 폴백: {e}")
        return _collect_page_elements_image(job, temp_dir, page_range)

    submit_path = input_path
    if page_range:
        submit_path = temp_dir / "page_range.pdf"
        _extract_pages_to_pdf(input_path, submit_path, sorted(page_range))
        page_no_map = {idx: page_no for idx, page_no in enumerate(sorted(page_range))}
    else:
        doc = fitz.open(str(input_path))
        page_no_map = {idx: idx + 1 for idx in range(len(doc))}
        doc.close()

    try:
        pages = paddleocr_client.convert_pdf_with_layout(submit_path)
        layout_pages = [p[1] for p in pages]
        angle_codes = [p[2] for p in pages]
    except Exception as e:
        logger.warning(f"[pdf_annotate] PDF 직접 입력 경로: PaddleOCR PDF 변환 실패, 이미지 경로로 폴백: {e}")
        return _collect_page_elements_image(job, temp_dir, page_range)

    image_paths = _get_page_image_paths(job, temp_dir, page_range=page_range)
    page_rects = _page_rects(input_bytes)

    for idx, page_no in page_no_map.items():
        if idx >= len(layout_pages):
            continue

        layout_raw = layout_pages[idx]
        angle_code = angle_codes[idx] if idx < len(angle_codes) else -1
        layout_by_page[page_no] = layout_raw or {}

        img_path = image_paths.get(page_no)
        if img_path:
            deskewed_path, _applied = deskew_image(img_path, output_dir=temp_dir / "deskewed")
            final_path = _rotate_image_90(deskewed_path, angle_code, temp_dir / "rotated")
            corrected_images[page_no] = final_path

        rect = page_rects.get(page_no)
        if not rect:
            logger.warning(f"[pdf_annotate] PDF 직접 입력 경로: page={page_no} 페이지 rect를 찾을 수 없어 건너뜀")
            continue

        layout = parse_layout_result(layout_raw, page_no=page_no)
        for table in layout.tables:
            for row in table.rows:
                if not any(cell.strip() for cell in row.cell_texts):
                    continue
                bbox_pdf = _layout_bbox_to_pdf_user(layout_raw, row.bbox_px, rect, dpi=RENDER_DPI)
                elements.append(AnnotateElement(
                    page_no=page_no, bbox_px=bbox_pdf, kind="table_row",
                    text=_row_to_text(row),
                    word_bboxes=[],
                    cell_texts=row.cell_texts,
                    cell_bboxes=[],
                ))
        for tb in layout.text_blocks:
            bbox_pdf = _layout_bbox_to_pdf_user(layout_raw, tb.bbox_px, rect, dpi=RENDER_DPI)
            word_bboxes_pdf = [
                _layout_bbox_to_pdf_user(layout_raw, b, rect, dpi=RENDER_DPI)
                for b in tb.word_bboxes
            ]
            elements.append(AnnotateElement(
                page_no=page_no, bbox_px=bbox_pdf, kind="text",
                text=_text_block_to_text(tb),
                word_bboxes=word_bboxes_pdf,
                cell_texts=[],
                cell_bboxes=[],
            ))

    return elements, corrected_images, layout_by_page


def _collect_page_elements(
    job: Job,
    temp_dir: Path,
    page_range: list[int] | None = None,
    use_pdf_direct: bool = False,
) -> tuple[list[AnnotateElement], dict[int, Path], dict[int, dict]]:
    """페이지를 렌더링하고 PaddleOCR bbox를 확보해 텍스트 요소 목록을 반환한다.

    [Flow: Step 1 (use_pdf_direct 및 page_range 조건 확인)
          -> Step 2 (PDF 직접 경로 또는 이미지 경로로 분기)
          -> Step 3 (각 경로에서 elements, corrected_images, layout_by_page 수집)]

    Args:
        job: Job 모델
        temp_dir: 임시 출력 디렉터리
        page_range: 1-based 페이지 번호 리스트. None이면 전체 페이지를 처리한다.
        use_pdf_direct: True면 원본 PDF를 PaddleOCR 서비스에 직접 제출한다.
            /api/convert/pdf는 10페이지 이하만 지원하므로, page_range가 10페이지를 초과하면
            자동으로 이미지 경로로 폴백한다.

    Returns:
        (elements, corrected_images, layout_by_page) —
        elements: 주석 대상 텍스트 요소 목록 (bbox는 PDF user-space)
        corrected_images: page_no(1-based) → 정돈된 페이지 이미지 경로
        layout_by_page: page_no → PaddleOCR layout 원본 dict (overall_ocr_res 포함, bbox는 normalized 좌표)
    """
    if use_pdf_direct and (page_range is None or len(page_range) <= max(1, settings.ocr_batch_size)):
        return _collect_page_elements_pdf_direct(job, temp_dir, page_range)
    return _collect_page_elements_image(job, temp_dir, page_range)


def _ensure_searchable_pdf(
    job: Job,
    temp_dir: Path,
    language: str = "en",
) -> tuple[bytes, list[AnnotateElement], dict[int, dict], bool]:
    """[Flow: Step 1 (job.searchable_pdf_storage_path 확인)
          -> Step 2 (없으면 PaddleOCR로 OCR 수행 → corrected_images + layout_by_page 획득)
          -> Step 3 (보정된 이미지로 PDF 생성 → add_text_layer_from_ocr로 텍스트 레이어 추가)
          -> Step 4 (searchable PDF Storage 업로드 → job.searchable_pdf_storage_path 설정)]

    모든 PDF가 PaddleOCR을 거쳐 텍스트 레이어가 있는 searchable PDF가 되도록 보장한다.
    """
    if job.searchable_pdf_storage_path:
        try:
            pdf_bytes = supabase_client.download_pdf(job.searchable_pdf_storage_path).read()
            logger.info(f"[pdf_annotate] searchable PDF 사용: {job.searchable_pdf_storage_path}")
            return pdf_bytes, [], {}, False
        except Exception as e:
            logger.warning(f"[pdf_annotate] searchable PDF 다운로드 실패, PaddleOCR로 재생성: {e}")

    elements, corrected_images, layout_by_page = _collect_page_elements(
        job, temp_dir, page_range=None, use_pdf_direct=True
    )
    if not corrected_images:
        raise ValueError("PaddleOCR로 페이지 이미지를 확보하지 못해 searchable PDF를 생성할 수 없습니다")

    pdf_bytes = _images_to_pdf(corrected_images)
    page_ocr_results = extract_page_ocr_results_from_layout(layout_by_page)
    if page_ocr_results:
        pdf_bytes = add_text_layer_from_ocr(
            pdf_bytes, page_ocr_results, dpi=RENDER_DPI, language=language,
            layout_by_page=layout_by_page,
        )

    try:
        from io import BytesIO
        storage_path = supabase_client.upload_input(BytesIO(pdf_bytes), "searchable.pdf", job.id)
        job.searchable_pdf_storage_path = storage_path
    except Exception as e:
        logger.warning(f"[pdf_annotate] searchable PDF 업로드 실패 (계속 진행): {e}")

    return pdf_bytes, elements, layout_by_page, True


def _normalized_bbox_to_pdf_user(
    bbox: tuple[float, float, float, float],
    page_width_pt: float,
    page_height_pt: float,
    page_x0: float = 0.0,
    page_y0: float = 0.0,
) -> tuple[float, float, float, float]:
    """PaddleOCR에서 반환한 0~1 normalized 좌표(y=0이 상단)를 PDF user-space(y↑, y=0이 하단)로 변환한다.

    [Flow: Step 1 (x 좌표에 페이지 너비를 곱하고 page_x0 오프셋 추가)
          -> Step 2 (y 좌표를 1에서 뺀 뒤 페이지 높이를 곱하고 page_y0 오프셋 추가)
          -> Step 3 (PDF user-space [x0, y0, x1, y1] 반환)]

    이미지 좌표계(y↓)에서 normalized 좌표를 얻었으므로, PDF user-space로 변환할 때는
    y축을 flip해야 한다. CropBox/ArtBox가 있는 PDF에서는 page_x0/page_y0 오프셋을
    고려해야 한다.
    """
    nx0, ny0, nx1, ny1 = bbox
    return (
        nx0 * page_width_pt + page_x0,
        (1 - ny1) * page_height_pt + page_y0,
        nx1 * page_width_pt + page_x0,
        (1 - ny0) * page_height_pt + page_y0,
    )


def _layout_bbox_to_pdf_user(
    layout_raw: dict | None,
    bbox: tuple[float, float, float, float],
    page_rect: fitz.Rect | None,
    dpi: int = RENDER_DPI,
) -> tuple[float, float, float, float]:
    """OCR layout의 bbox 좌표계를 감지해 PDF user-space로 변환한다.

    [Flow: Step 1 (_coordinate_system 확인: normalized면 그대로 변환)
          -> Step 2 (heuristic: 값이 0~1 범위면 normalized로 간주)
          -> Step 3 (source_width/source_height 확인: _page_width_px/width 우선)
          -> Step 4 (source 크기로 normalized 후 PDF user-space로 변환)]

    PaddleOCR 서비스 버전에 따라 layout bbox가 0~1 normalized, 픽셀, 또는
    PDF top-left 좌표로 저장되어 있을 수 있다. 이 헬퍼는 메타데이터가 없어도
    대부분의 경우를 올바르게 변환한다.
    """
    if not bbox or not page_rect:
        return bbox

    x0, y0, x1, y1 = bbox
    coordinate_system = (layout_raw or {}).get("_coordinate_system")

    # 명시적으로 normalized로 표시되어 있거나, 모든 값이 0~1이면 normalized로 간주한다.
    is_normalized = coordinate_system == "normalized" or all(0.0 <= v <= 1.01 for v in (x0, y0, x1, y1))
    if is_normalized:
        return _normalized_bbox_to_pdf_user(bbox, page_rect.width, page_rect.height, page_rect.x0, page_rect.y0)

    # normalized가 아니면 source 좌표계의 단위(픽셀 또는 top-left points)로 취급한다.
    source_width = (layout_raw or {}).get("_page_width_px") or (layout_raw or {}).get("width")
    source_height = (layout_raw or {}).get("_page_height_px") or (layout_raw or {}).get("height")
    if not source_width or not source_height:
        # 메타데이터 없이 픽셀 좌표로 가정하고 PDF 포인트로 환산한다.
        source_width = page_rect.width * dpi / PDF_POINTS_PER_INCH
        source_height = page_rect.height * dpi / PDF_POINTS_PER_INCH
    source_width = float(source_width)
    source_height = float(source_height)
    if source_width <= 0 or source_height <= 0:
        return bbox

    nx0 = x0 / source_width
    ny0 = y0 / source_height
    nx1 = x1 / source_width
    ny1 = y1 / source_height
    return _normalized_bbox_to_pdf_user(
        (nx0, ny0, nx1, ny1), page_rect.width, page_rect.height, page_rect.x0, page_rect.y0
    )


def _page_rects(pdf_bytes: bytes) -> dict[int, fitz.Rect]:
    """원본 PDF에서 페이지별 실제 rect(CropBox/ArtBox를 고려한 page.rect)를 1-based page_no 기준으로 반환한다."""
    rects: dict[int, fitz.Rect] = {}
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for i in range(doc.page_count):
            rects[i + 1] = doc[i].rect
    finally:
        doc.close()
    return rects


def _page_point_sizes(pdf_bytes: bytes) -> dict[int, tuple[float, float]]:
    """원본 PDF에서 페이지별 실제 크기(포인트)를 1-based page_no 기준으로 반환한다."""
    return {page_no: (rect.width, rect.height) for page_no, rect in _page_rects(pdf_bytes).items()}


def collect_elements_for_agent(
    job_id: str,
    page_range: list[int] | None = None,
    dpi: int = RENDER_DPI,
) -> tuple[list[dict], bytes | None, dict[int, dict]]:
    """[Flow: Step 1 (job_id로 Job 조회) -> Step 2 (searchable PDF 여부 확인)
          -> Step 3 (searchable PDF 또는 PaddleOCR로 elements 추출)
          -> Step 4 (page_range 필터링) -> Step 5 (픽셀 bbox를 PDF 포인트로 변환)
          -> Step 6 (agent가 사용할 JSON serializable dict 목록 + 주석 베이스 PDF bytes + OCR layout 반환)]

    LangGraph annotator agent가 사용할 텍스트 요소 목록을 추출한다.
    PDF 좌표는 이미지 픽셀 좌표를 PDF 포인트로 변환해 state["elements"]에 저장한다.
    함께 반환된 pdf_bytes는 agent가 최종 주석 JSON을 생성할 때 사용한다.
    layout_by_page는 agent 도구에서 재사용할 수 있도록 Storage에 저장할 수 있다.
    """
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
    finally:
        db.close()
    if job is None:
        return [], None, {}

    layout_by_page: dict[int, dict] = {}
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_dir = Path(tmpdir)
        searchable_pdf_bytes: bytes | None = None
        if job.searchable_pdf_storage_path:
            try:
                searchable_pdf_bytes = supabase_client.download_pdf(job.searchable_pdf_storage_path).read()
                logger.info(f"[collect_elements_for_agent] searchable PDF 사용: {job.searchable_pdf_storage_path}")
            except Exception as e:
                logger.warning(f"[collect_elements_for_agent] searchable PDF 다운로드 실패: {e}")

        if searchable_pdf_bytes:
            elements, _corrected = _collect_page_elements_from_searchable_pdf(searchable_pdf_bytes, temp_dir, dpi=dpi)
            pdf_bytes = searchable_pdf_bytes
        else:
            elements, corrected_images, layout_by_page = _collect_page_elements(
                job, temp_dir, page_range=page_range, use_pdf_direct=True
            )
            if not corrected_images:
                return [], None, layout_by_page
            pdf_bytes = _images_to_pdf(corrected_images)
            page_ocr_results = extract_page_ocr_results_from_layout(layout_by_page)
            if page_ocr_results:
                pdf_bytes = add_text_layer_from_ocr(
                    pdf_bytes, page_ocr_results, dpi=dpi, language=job.language or "en",
                    layout_by_page=layout_by_page,
                )

        if not elements:
            return [], pdf_bytes, layout_by_page

        page_point_sizes = _page_point_sizes(pdf_bytes)
        if page_range is not None:
            page_set = set(page_range)
            elements = [e for e in elements if e.page_no in page_set]
            if not elements:
                return [], pdf_bytes

        results: list[dict] = []
        for el in elements:
            # paddleocr_service에서 bbox를 PDF user-space로 정규화해서 반환하므로
            # 추가 y축 flip 없이 그대로 bbox_pdf로 사용한다.
            bbox_pdf = el.bbox_px
            cell_bboxes_pdf = list(el.cell_bboxes)
            results.append(
                {
                    "page_no": el.page_no,
                    "bbox_px": el.bbox_px,
                    "bbox_pdf": bbox_pdf,
                    "kind": el.kind,
                    "text": el.text,
                    "word_bboxes": el.word_bboxes,
                    "cell_texts": el.cell_texts,
                    "cell_bboxes_pdf": cell_bboxes_pdf,
                }
            )
        return results, pdf_bytes, layout_by_page


def build_agent_elements_from_ocr_layout(
    layout_by_page: dict[int, dict],
    pdf_bytes: bytes,
    page_range: list[int] | None = None,
    dpi: int = RENDER_DPI,
) -> list[dict]:
    """[Flow: Step 1 (page_range 필터링) -> Step 2 (pdf_bytes에서 페이지 크기 추출)
          -> Step 3 (layout_by_page 파싱) -> Step 4 (표 행 + 텍스트 블록 → PDF 좌표 변환)
          -> Step 5 (agent용 요소 목록 반환)]

    이미 확보된 OCR layout_by_page로부터 AI 에이전트가 사용할 페이지 요소 목록을 생성한다.
    collect_elements_for_agent()와 동일한 좌표 변환 및 텍스트 추출 로직을 재사용한다.

    Args:
        layout_by_page: page_no(1-based) → PaddleOCR layout 원본 dict
        pdf_bytes: 페이지 크기를 알기 위한 PDF bytes
        page_range: 1-based 페이지 번호 리스트. None이면 모든 페이지
        dpi: 렌더링 DPI

    Returns:
        agent용 요소 dict 목록 (page_no, bbox_pdf, text, kind)
    """
    page_rects = _page_rects(pdf_bytes)
    page_set = set(page_range) if page_range is not None else None
    results: list[dict] = []
    for page_no_raw, layout_raw in layout_by_page.items():
        page_no = int(page_no_raw) if isinstance(page_no_raw, str) else page_no_raw
        if page_set is not None and page_no not in page_set:
            continue
        layout = parse_layout_result(layout_raw, page_no=page_no)
        rect = page_rects.get(page_no)
        # PaddleOCR layout bbox 좌표계를 감지해 PDF user-space로 변환한다.
        # 서비스 버전/응답에 따라 normalized, 픽셀, top-left points 등이 섞여 있을 수 있다.
        for table in layout.tables:
            for row in table.rows:
                if not any(cell.strip() for cell in row.cell_texts):
                    continue
                results.append({
                    "page_no": page_no,
                    "bbox_pdf": _layout_bbox_to_pdf_user(layout_raw, row.bbox_px, rect, dpi=dpi),
                    "text": _row_to_text(row),
                    "kind": "table_row",
                })
        for tb in layout.text_blocks:
            results.append({
                "page_no": page_no,
                "bbox_pdf": _layout_bbox_to_pdf_user(layout_raw, tb.bbox_px, rect, dpi=dpi),
                "text": _text_block_to_text(tb),
                "kind": "text",
            })
    return results


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

            # page.get_text("blocks")보다 "dict"이 PyMuPDF 버전 간에 더 안정적이다.
            text_dict = page.get_text("dict")
            blocks = text_dict.get("blocks", []) if isinstance(text_dict, dict) else []
            for block in blocks:
                try:
                    bbox = block["bbox"]
                    x0, y0, x1, y1 = bbox
                    text = "".join(
                        span["text"]
                        for line in block.get("lines", [])
                        for span in line.get("spans", [])
                    )
                except Exception:
                    continue
                if not text or not text.strip():
                    continue
                # searchable PDF의 텍스트 레이어는 이미 PDF user-space(y↑) 좌표이므로
                # _matches_to_targets와 일관되게 그대로 사용한다. 이미지 좌표계로 변환하면
                # 위치가 완전히 망가진다.
                bbox_px: BBox = (float(x0), float(y0), float(x1), float(y1))
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


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    """[Flow: Step 1 (0-1 float RGB 값을 0-255로 변환) -> Step 2 (16진수 문자열로 포맷)]

    LLM 색상 이름을 HEX 색상 코드로 변환한다. embedpdf 주석의 color 필드는 HEX 형태를 사용한다.
    """
    r, g, b = rgb
    return f"#{int(round(r * 255)):02x}{int(round(g * 255)):02x}{int(round(b * 255)):02x}"


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


def _union_rects(rects: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    """[Flow: Step 1 (여러 rect의 좌표를 수집) -> Step 2 (최소/최대 x, y 계산) -> Step 3 (합친 bbox 반환)]

    검색 결과로 나온 여러 rect를 하나의 bounding box로 합친다.
    """
    if not rects:
        return (0.0, 0.0, 0.0, 0.0)
    min_x = min(r[0] for r in rects)
    min_y = min(r[1] for r in rects)
    max_x = max(r[2] for r in rects)
    max_y = max(r[3] for r in rects)
    return (min_x, min_y, max_x, max_y)


def _collect_targets_with_searchable_text(
    pdf_bytes: bytes,
    instruction: str,
    endpoint: str,
    model: str,
    api_key: str,
    page_range: list[int] | None = None,
) -> tuple[list[AnnotationTarget], str | None, str | None]:
    """[Flow: Step 1 (searchable PDF에서 페이지별 텍스트 추출)
          -> Step 2 (LLM에 텍스트만 전달해 강조할 내용 수신)
          -> Step 3 (TextLayerSearcher로 모든 페이지에서 text 검색)
          -> Step 4 (매칭된 모든 rect를 bounding box + segmentRects로 변환)
          -> Step 5 (AnnotationTarget 목록 반환)]

    텍스트 레이어가 있는 PDF에서 LLM이 좌표/페이지에 관여하지 않고,
    강조해야 할 정확한 텍스트만 반환하면 백엔드가 텍스트 레이어를 검색해 형광펜을 칠한다.
    같은 텍스트가 한 페이지에서 여러 번 나타나면 모든 위치를 highlight한다.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page_numbers = page_range if page_range else list(range(1, doc.page_count + 1))
        page_texts: list[tuple[int, str]] = []
        for page_no in page_numbers:
            if page_no < 1 or page_no > doc.page_count:
                continue
            page = doc[page_no - 1]
            raw_text = page.get_text()
            if len(raw_text) > MAX_PAGE_TEXT_CHARS_FOR_LLM:
                raw_text = raw_text[:MAX_PAGE_TEXT_CHARS_FOR_LLM] + "..."
            page_texts.append((page_no, raw_text))
    finally:
        doc.close()

    if not page_texts:
        return [], None, None

    prompt = build_text_search_highlight_prompt(page_texts, instruction, want_llm_comment=True)
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

    targets: list[AnnotationTarget] = []
    page_rect_map = _page_rects(pdf_bytes)
    text_searcher = TextLayerSearcher(pdf_bytes)
    try:
        for m in matches:
            text = str(m.get("text") or "").strip()
            if not text:
                continue

            comment = str(m.get("comment") or "").strip()
            color_name = m.get("color")
            color = _color_name_to_rgb(color_name)
            callout_color = color if color_name else None
            opacity = _parse_opacity(m.get("opacity"))

            found_by_page = text_searcher.search_all_pages(text, page_range=page_range)
            if not found_by_page:
                logger.info(f"[pdf_annotate] 텍스트 레이어 검색 실패: '{text[:50]}'")
                continue

            for page_no, rects in found_by_page:
                if not rects:
                    continue
                p_rect = page_rect_map.get(page_no)
                p_h = p_rect.height if p_rect else 842.0
                pdf_user_rects = [(rx0, p_h - ry1, rx1, p_h - ry0) for rx0, ry0, rx1, ry1 in rects]
                bounding_rect = _union_rects(pdf_user_rects)
                targets.append(AnnotationTarget(
                    page_no=page_no,
                    bbox_pdf=bounding_rect,
                    comment=comment,
                    color=color,
                    callout_color=callout_color,
                    opacity=opacity,
                    search_rects_pdf=pdf_user_rects,
                    search_text=text,
                ))
    finally:
        text_searcher.close()

    return targets, mode, comment_mode


def _collect_targets_with_vision_llm(
    image_paths: dict[int, Path],
    pdf_bytes: bytes,
    instruction: str,
    endpoint: str,
    model: str,
    api_key: str,
    page_range: list[int] | None = None,
) -> tuple[list[AnnotationTarget], str | None, str | None]:
    """[Flow: Step 1 (페이지별 이미지 순회) -> Step 2 (Gemma4 해상도 맞춤)
          -> Step 3 (Vision LLM에 텍스트 내용만 요청)
          -> Step 4 (TextLayerSearcher로 searchable PDF에서 text 검색)
          -> Step 5 (매칭된 모든 rect를 bounding rect + segmentRects로 변환)
          -> Step 6 (페이지별 mode/comment_mode 추출, 마지막 유효 값 사용)]

    Vision LLM은 이미지에서 조건에 맞는 텍스트 내용만 반환하고,
    백엔드가 searchable PDF의 텍스트 레이어에서 해당 text를 검색해 bbox를 결정한다.
    """
    targets: list[AnnotationTarget] = []
    mode: str | None = None
    comment_mode: str | None = None
    page_rect_map = _page_rects(pdf_bytes)
    text_searcher = TextLayerSearcher(pdf_bytes)
    try:
        for page_no, img_path in sorted(image_paths.items()):
            if page_range is not None and page_no not in page_range:
                continue
            try:
                fitted = ocr_client.fit_image_to_gemma4_resolution(img_path)

                # 코멘트는 AI 요약으로 생성한 뒤, comment_mode가 user_text이면 백엔드에서 교체한다.
                prompt = build_vision_text_highlight_prompt(instruction, want_llm_comment=True)
                content, _ = ocr_client.call_vision(fitted, prompt, endpoint, model, api_key, max_tokens=4000)
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
                    text = str(m.get("text") or "").strip()
                    if not text:
                        continue
                    comment = str(m.get("comment") or "").strip()
                    color_name = m.get("color")
                    color = _color_name_to_rgb(color_name)
                    callout_color = color if color_name else None
                    opacity = _parse_opacity(m.get("opacity"))

                    # Vision LLM이 본 페이지에서만 검색한다.
                    found = text_searcher.search(page_no, text)
                    if not found:
                        logger.info(f"[pdf_annotate] page={page_no} 텍스트 레이어 검색 실패: '{text[:50]}'")
                        continue

                    p_rect = page_rect_map.get(page_no)
                    p_h = p_rect.height if p_rect else 842.0
                    pdf_user_found = [(rx0, p_h - ry1, rx1, p_h - ry0) for rx0, ry0, rx1, ry1 in found]
                    bounding_rect = _union_rects(pdf_user_found)
                    targets.append(AnnotationTarget(
                        page_no=page_no,
                        bbox_pdf=bounding_rect,
                        comment=comment,
                        color=color,
                        callout_color=callout_color,
                        opacity=opacity,
                        search_rects_pdf=pdf_user_found,
                        search_text=text,
                    ))
            except Exception as e:
                logger.warning(f"[pdf_annotate] page={page_no} Vision LLM 처리 실패: {e}")
                continue
    finally:
        text_searcher.close()
    return targets, mode, comment_mode


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

    next_index = annotation_index
    shared_annotations_json_path = f"{job.id}/annotated.annotations.json"

    endpoint = job.endpoint or settings_store.get_setting(db, "llm_endpoint") or settings.default_llm_endpoint
    model = job.model or settings_store.get_setting(db, "llm_model") or settings.default_llm_model
    api_key = settings_store.get_setting(db, "llm_api_key") or ""

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_dir = Path(tmpdir)

            # [Flow: searchable PDF 확보 — PaddleOCR로 텍스트 레이어가 없으면 생성]
            # 모든 PDF는 검색 가능한 텍스트 레이어를 가진 PDF를 베이스로 사용한다.
            pdf_bytes, elements, layout_by_page, _created = _ensure_searchable_pdf(
                job, temp_dir, language=language
            )
            if _created:
                # searchable PDF 경로를 즉시 DB에 저장 (worker 중단 시 재사용)
                db.commit()

            # [Flow: OCR layout 저장 — agent의 get_elements/search_text가 재사용할 수 있도록]
            if layout_by_page:
                try:
                    data = json.dumps(layout_by_page, ensure_ascii=False, default=str).encode("utf-8")
                    storage_path = f"{job.id}/ocr_layout.json"
                    client = supabase_client.get_service_client()
                    client.storage.from_("results").upload(
                        storage_path,
                        data,
                        {"content-type": "application/json", "upsert": "true"},
                    )
                    job.result_ocr_layout_storage_path = storage_path
                    db.commit()
                    logger.info(f"[pdf_annotate] {job.id} OCR layout 저장 완료: {storage_path}")
                except Exception as e:
                    logger.warning(f"[pdf_annotate] {job.id} OCR layout 저장 실패: {e}")

            page_point_sizes = _page_point_sizes(pdf_bytes)
            llm_mode: str | None = None
            llm_comment_mode: str | None = None

            if advanced:
                # [Flow: 고급주석 — Vision LLM이 이미지를 보고 텍스트 내용만 반환, 백엔드가 검색]
                image_paths = _render_pdf_to_image_paths(pdf_bytes, temp_dir, dpi=RENDER_DPI)
                if page_range is not None:
                    page_set = set(page_range)
                    image_paths = {p: path for p, path in image_paths.items() if p in page_set}
                    if not image_paths:
                        _update_entry_status(db, job_id, next_index, "done", recovery_notes=[{"reason": "지정한 페이지 범위에 해당하는 페이지가 없습니다"}])
                        return {"job_id": job_id, "status": "done", "matched_rows": 0}
                    logger.info(f"[pdf_annotate] page_range 필터 적용: {sorted(page_set)} ({len(image_paths)}페이지)")

                targets, llm_mode, llm_comment_mode = _collect_targets_with_vision_llm(
                    image_paths, pdf_bytes, instruction, endpoint, model, api_key, page_range=page_range
                )
            else:
                # [Flow: 일반주석 — LLM이 페이지 텍스트를 보고 텍스트 내용만 반환, 백엔드가 검색]
                targets, llm_mode, llm_comment_mode = _collect_targets_with_searchable_text(
                    pdf_bytes, instruction, endpoint, model, api_key, page_range=page_range
                )

            if not targets:
                _update_entry_status(db, job_id, next_index, "done", recovery_notes=[{"reason": "조건에 맞는 텍스트를 찾지 못했습니다"}])
                return {"job_id": job_id, "status": "done", "matched_rows": 0}

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
            # 프론트에서 오버레이한다. 하이라이트는 HIGHLIGHT, 코멘트는 TEXT(sticky note — 메모 아이콘 +
            # 클릭 시 팝업)로 생성한다. sticky note 아이콘은 대상 텍스트 시작 위치에 직접 겹쳐 배치된다.
            # 단일 진실원이자 사용자 편집 가능. flatten 다운로드는 프론트의 embedpdf export
            # plugin(saveAsCopy)이 처리한다.
            # job당 searchable PDF는 job.searchable_pdf_storage_path를 사용하며,
            # annotations.json에만 주석을 누적한다.
            shared_storage_path = job.searchable_pdf_storage_path
            if not shared_storage_path:
                # _ensure_searchable_pdf에서 업로드 실패한 경우 재업로드
                from io import BytesIO
                shared_storage_path = supabase_client.upload_input(BytesIO(pdf_bytes), "searchable.pdf", job.id)
                job.searchable_pdf_storage_path = shared_storage_path
            display_name = _searchable_display_name(job)

            # [Flow: 페이지 요소 bbox 수집 — 레거시 callout 호환성 인자.
            # sticky note는 대상 텍스트 위치에 직접 배치하므로 충돌 회피에 사용하지 않지만,
            # build_embedpdf_annotations 시그니처 호환성을 위해 그대로 수집해 전달한다.]
            # elements의 bbox_px를 PDF user-space 좌표로 변환해 페이지별로 그룹화한다.
            page_elements_bboxes: dict[int, list[tuple[float, float, float, float]]] = {}
            for el in elements:
                # paddleocr_service에서 bbox를 PDF user-space로 정규화해서 반환하므로
                # 추가 변환 없이 그대로 수집한다.
                page_elements_bboxes.setdefault(el.page_no, []).append(el.bbox_px)
            for t in targets:
                page_elements_bboxes.setdefault(t.page_no, []).append(t.bbox_pdf)

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
            client = supabase_client.get_service_client()
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
            if not locked_job.searchable_pdf_storage_path:
                locked_job.searchable_pdf_storage_path = shared_storage_path
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

    user_language = "ko"
    if job.user_id:
        try:
            user = db.get(User, job.user_id)
            if user and user.language:
                user_language = user.language
        except Exception:
            pass

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
            # sticky note(TEXT=1)와 레거시 callout(FREETEXT/FreeTextCallout) 모두 코멘트 주석으로 취급.
            # 신규 주석은 sticky note로 생성되지만, 기존 callout 주석도 편집할 수 있어야 한다.
            is_note = (
                atype in ("freetext", "freetextcallout", "text", "sticky")
                or intent == "freetextcallout"
            )
            comment = ann.get("contents", "") or ""
            color = ann.get("color", "") or ann.get("strokeColor", "") or ""
            # 코멘트 주석(sticky note/callout)은 comment를 원본 텍스트로 전달해 LLM이 재작성 가능.
            # 하이라이트 주석은 원본 텍스트 추출을 생략하고 comment만 전달 (색상 변경 중심).
            text = comment if is_note else ""
            editable.append({
                "id": aid,
                "type": "sticky" if is_note else "highlight",
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
            user_language=user_language,
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
                # sticky note/callout 주석은 strokeColor(아이콘/테두리 색)도 함께 갱신
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
