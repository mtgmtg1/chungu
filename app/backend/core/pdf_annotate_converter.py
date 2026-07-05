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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF

from .. import settings_store
from ..config import settings
from ..db.models import Job
from ..db.session import SessionLocal
from . import cache, ocr_client, paddleocr_client, supabase_client
from .ocr_layout import BBox, OcrRow, OcrTextBlock, parse_layout_result
from .pdf_annotator import AnnotationTarget, annotate_pdf
from .pdf_coords import clamp_rect_to_page, px_bbox_to_pdf_rect
from .prompts import build_element_highlight_prompt
from .xlsx_advanced_converter import _get_page_image_paths

logger = logging.getLogger(__name__)

RENDER_DPI = 200  # _get_page_image_paths가 PDF를 렌더링할 때 사용하는 DPI와 동일해야 bbox 좌표가 맞는다.
MAX_ELEMENTS_FOR_LLM = 400  # 프롬프트 폭주 방지
MAX_TEXT_BLOCK_CHARS = 200  # 텍스트 블록은 앞 200자만 LLM에 전달 (토큰 폭증 방지)


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
    bbox_px: BBox  # 픽셀 좌표 (xmin, ymin, xmax, ymax)
    kind: str  # "table_row" | "text"
    text: str  # LLM에 전달할 텍스트 표현


def _collect_page_elements(job: Job, temp_dir: Path) -> list[AnnotateElement]:
    """모든 페이지를 렌더링하고 PaddleOCR bbox를 확보해 텍스트 요소 목록을 반환한다.

    표의 행(table_row)과 텍스트 블록(text)을 모두 수집한다.
    """
    image_paths = _get_page_image_paths(job, temp_dir)
    elements: list[AnnotateElement] = []

    for page_no in sorted(image_paths.keys()):
        img_path = image_paths[page_no]
        try:
            _markdown, layout_raw = paddleocr_client.convert_image_with_layout(img_path)
        except Exception as e:
            logger.warning(f"[pdf_annotate] page={page_no} PaddleOCR 레이아웃 확보 실패: {e}")
            continue

        layout = parse_layout_result(layout_raw, page_no=page_no)
        for table in layout.tables:
            for row in table.rows:
                if not any(cell.strip() for cell in row.cell_texts):
                    continue
                elements.append(AnnotateElement(
                    page_no=page_no, bbox_px=row.bbox_px, kind="table_row",
                    text=_row_to_text(row),
                ))
        for tb in layout.text_blocks:
            elements.append(AnnotateElement(
                page_no=page_no, bbox_px=tb.bbox_px, kind="text",
                text=_text_block_to_text(tb),
            ))

    return elements


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


def _select_elements_with_llm(
    elements: list[AnnotateElement],
    instruction: str,
    want_llm_comment: bool,
    endpoint: str,
    model: str,
    api_key: str,
) -> list[dict]:
    """LLM에게 요소 텍스트만 전달해 조건에 맞는 요소 인덱스+코멘트를 받는다 (좌표 추론은 시키지 않는다).

    주석 코멘트는 사용자가 instruction에 사용한 언어로 작성되도록 프롬프트에 지시한다
    (프롬프트가 "사용자 조건 문구와 같은 언어로 작성"하라고 LLM에 가이드한다).
    """
    if not elements:
        return []

    truncated = elements[:MAX_ELEMENTS_FOR_LLM]
    element_dicts = [{"kind": e.kind, "text": e.text} for e in truncated]
    prompt = build_element_highlight_prompt(element_dicts, instruction, want_llm_comment)

    content, _ = ocr_client.call_text(prompt, endpoint, model, api_key, max_tokens=4000)
    content = _strip_json_fence(content)
    try:
        data = json.loads(content)
    except Exception as e:
        raise ValueError(f"LLM 응답 JSON 파싱 실패: {e} (content={content[:200]})")

    matches = data.get("matches", []) if isinstance(data, dict) else []
    if not isinstance(matches, list):
        return []
    return [m for m in matches if isinstance(m, dict) and "element_index" in m]


def run(job_id: str, instruction: str, mode: str, comment_mode: str, language: str = "en") -> dict:
    """하이라이트/여백 주석 작업을 실행하고 job 상태를 갱신한다.

    Args:
        job_id: 작업 ID
        instruction: 사용자가 입력한 조건 문구
        mode: "highlight" | "margin_note" | "both"
        comment_mode: "user_text" | "llm_summary"
        language: 사용자 언어 코드 ("ko"/"en"/"ja") — 주석 코멘트가 이 언어로 작성된다
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

    endpoint = job.endpoint or settings_store.get_setting(db, "llm_endpoint") or settings.default_llm_endpoint
    model = job.model or settings_store.get_setting(db, "llm_model") or settings.default_llm_model
    api_key = settings_store.get_setting(db, "llm_api_key") or ""
    want_llm_comment = comment_mode == "llm_summary"

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_dir = Path(tmpdir)
            image_paths = _get_page_image_paths(job, temp_dir)
            if not image_paths:
                raise ValueError("원본 파일을 이미지로 렌더링하지 못해 주석을 생성할 수 없습니다")

            # 원본 PDF가 있으면 다운로드, 없으면 이미지로 PDF 생성
            if job.pdf_storage_path:
                pdf_bytes = supabase_client.download_pdf(job.pdf_storage_path).read()
            else:
                pdf_bytes = _images_to_pdf(image_paths)
            page_point_sizes = _page_point_sizes(pdf_bytes)

            elements = _collect_page_elements(job, temp_dir)
            if not elements:
                raise ValueError("텍스트 요소를 인식하지 못해 하이라이트/여백 주석 대상을 찾을 수 없습니다")

            matches = _select_elements_with_llm(elements, instruction, want_llm_comment, endpoint, model, api_key)
            if not matches:
                job.annotate_status = "done"
                job.annotate_refundable = False
                job.result_annotated_pdf_storage_path = ""
                job.annotate_recovery_notes = [{"reason": "조건에 맞는 요소를 찾지 못했습니다"}]
                db.commit()
                return {"job_id": job_id, "status": "done", "matched_rows": 0}

            targets: list[AnnotationTarget] = []
            skipped = 0
            for m in matches:
                idx = m.get("element_index")
                if not isinstance(idx, int) or idx < 0 or idx >= len(elements):
                    skipped += 1
                    continue
                el = elements[idx]
                rect_pdf = px_bbox_to_pdf_rect(el.bbox_px, dpi=RENDER_DPI)
                page_pt = page_point_sizes.get(el.page_no)
                if page_pt:
                    rect_pdf = clamp_rect_to_page(rect_pdf, page_pt[0], page_pt[1])
                comment = str(m.get("comment") or instruction).strip() or instruction
                targets.append(AnnotationTarget(page_no=el.page_no, bbox_pdf=rect_pdf, comment=comment))

            if not targets:
                raise ValueError("LLM이 선택한 요소를 원본 bbox로 매핑하지 못했습니다")

            annotated_bytes = annotate_pdf(pdf_bytes, targets, mode)
            annotated_files = job.annotated_pdf_files or []
            next_index = len(annotated_files) + 1
            storage_path = f"{job.id}/annotated_{next_index}.pdf"
            display_name = _annotation_display_name(job, next_index)
            client = supabase_client.get_service_client()
            client.storage.from_("results").upload(
                storage_path,
                annotated_bytes,
                {"content-type": "application/pdf", "upsert": "true"},
            )

            entry = {
                "storage_path": storage_path,
                "filename": display_name,
                "instruction": instruction,
                "mode": mode,
                "comment_mode": comment_mode,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            job.annotated_pdf_files = annotated_files + [entry]
            job.result_annotated_pdf_storage_path = storage_path
            job.annotate_status = "done"
            job.annotate_refundable = False
            job.annotate_recovery_notes = [{"skipped_matches": skipped}] if skipped else []
            db.commit()
            cache.invalidate_pattern(f"preview:{job_id}:*")
            return {"job_id": job_id, "status": "done", "matched_rows": len(targets)}

    except Exception as e:
        logger.exception(f"[pdf_annotate_converter] {job_id} 주석 생성 실패: {e}")
        tb = traceback.format_exc()
        job.annotate_status = "error"
        job.annotate_refundable = True
        job.annotate_recovery_notes = [{"reason": str(e), "traceback": tb[-2000:]}]
        db.commit()
        return {"job_id": job_id, "status": "error", "error": str(e)}
    finally:
        db.close()
