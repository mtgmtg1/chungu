#!/usr/bin/env python3
# [Flow: Step 1 (원본 PDF 페이지 이미지 렌더링, DPI 고정) -> Step 2 (페이지별 PaddleOCR bbox 확보)
#       -> Step 3 (모든 표의 행을 텍스트만으로 LLM에 전달해 조건에 맞는 행 선택) -> Step 4 (선택된 행의 bbox를
#       PDF 좌표로 변환) -> Step 5 (pdf_annotator로 하이라이트/여백 주석 적용) -> Step 6 (결과 업로드 및 job 갱신)]
# PDF 하이라이트/여백 주석 기능의 오케스트레이터. xlsx_advanced_converter.py와 동일한 job 상태
# 갱신/환불 가능 패턴을 따른다.
import json
import logging
import re
import tempfile
import traceback
from pathlib import Path

import fitz  # PyMuPDF

from .. import settings_store
from ..config import settings
from ..db.models import Job
from ..db.session import SessionLocal
from . import ocr_client, paddleocr_client, supabase_client
from .ocr_layout import OcrRow, parse_layout_result
from .pdf_annotator import AnnotationTarget, annotate_pdf
from .pdf_coords import clamp_rect_to_page, px_bbox_to_pdf_rect
from .prompts import build_row_highlight_prompt
from .xlsx_advanced_converter import _get_page_image_paths

logger = logging.getLogger(__name__)

RENDER_DPI = 200  # _get_page_image_paths가 PDF를 렌더링할 때 사용하는 DPI와 동일해야 bbox 좌표가 맞는다.
MAX_ROWS_FOR_LLM = 400  # 프롬프트 폭주 방지


def _strip_json_fence(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"```[a-zA-Z]*\n?|\n?```", "", content).strip()
    return content


def _collect_page_rows(job: Job, temp_dir: Path) -> list[tuple[int, OcrRow]]:
    """모든 페이지를 렌더링하고 PaddleOCR bbox를 확보해 (page_no, OcrRow) 목록을 반환한다."""
    image_paths = _get_page_image_paths(job, temp_dir)
    row_entries: list[tuple[int, OcrRow]] = []

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
                row_entries.append((page_no, row))

    return row_entries


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


def _select_rows_with_llm(
    row_entries: list[tuple[int, OcrRow]],
    instruction: str,
    want_llm_comment: bool,
    endpoint: str,
    model: str,
    api_key: str,
) -> list[dict]:
    """LLM에게 행 텍스트만 전달해 조건에 맞는 행 인덱스+코멘트를 받는다 (좌표 추론은 시키지 않는다)."""
    if not row_entries:
        return []

    truncated = row_entries[:MAX_ROWS_FOR_LLM]
    rows_text = [entry[1].cell_texts for entry in truncated]
    prompt = build_row_highlight_prompt(rows_text, instruction, want_llm_comment)

    content, _ = ocr_client.call_text(prompt, endpoint, model, api_key, max_tokens=4000)
    content = _strip_json_fence(content)
    try:
        data = json.loads(content)
    except Exception as e:
        raise ValueError(f"LLM 응답 JSON 파싱 실패: {e} (content={content[:200]})")

    matches = data.get("matches", []) if isinstance(data, dict) else []
    if not isinstance(matches, list):
        return []
    return [m for m in matches if isinstance(m, dict) and "row_index" in m]


def run(job_id: str, instruction: str, mode: str, comment_mode: str) -> dict:
    """하이라이트/여백 주석 작업을 실행하고 job 상태를 갱신한다."""
    db = SessionLocal()
    job = db.get(Job, job_id)
    if job is None:
        db.close()
        return {"error": "job not found"}

    endpoint = job.endpoint or settings_store.get_setting(db, "llm_endpoint") or settings.default_llm_endpoint
    model = job.model or settings_store.get_setting(db, "llm_model") or settings.default_llm_model
    api_key = settings_store.get_setting(db, "llm_api_key") or ""
    want_llm_comment = comment_mode == "llm_summary"

    try:
        if not job.pdf_storage_path:
            raise ValueError("원본 PDF가 없어 하이라이트/여백 주석을 생성할 수 없습니다 (이미지 단일 업로드 등)")

        pdf_bytes = supabase_client.download_pdf(job.pdf_storage_path).read()
        page_point_sizes = _page_point_sizes(pdf_bytes)

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_dir = Path(tmpdir)

            row_entries = _collect_page_rows(job, temp_dir)
            if not row_entries:
                raise ValueError("표를 인식하지 못해 하이라이트/여백 주석 대상을 찾을 수 없습니다")

            matches = _select_rows_with_llm(row_entries, instruction, want_llm_comment, endpoint, model, api_key)
            if not matches:
                job.annotate_status = "done"
                job.annotate_refundable = False
                job.result_annotated_pdf_storage_path = ""
                job.annotate_recovery_notes = [{"reason": "조건에 맞는 행을 찾지 못했습니다"}]
                db.commit()
                return {"job_id": job_id, "status": "done", "matched_rows": 0}

            targets: list[AnnotationTarget] = []
            skipped = 0
            for m in matches:
                idx = m.get("row_index")
                if not isinstance(idx, int) or idx < 0 or idx >= len(row_entries):
                    skipped += 1
                    continue
                page_no, row = row_entries[idx]
                rect_pdf = px_bbox_to_pdf_rect(row.bbox_px, dpi=RENDER_DPI)
                page_pt = page_point_sizes.get(page_no)
                if page_pt:
                    rect_pdf = clamp_rect_to_page(rect_pdf, page_pt[0], page_pt[1])
                comment = str(m.get("comment") or instruction).strip() or instruction
                targets.append(AnnotationTarget(page_no=page_no, bbox_pdf=rect_pdf, comment=comment))

            if not targets:
                raise ValueError("LLM이 선택한 행을 원본 bbox로 매핑하지 못했습니다")

            annotated_bytes = annotate_pdf(pdf_bytes, targets, mode)
            storage_path = f"{job.id}/annotated.pdf"
            client = supabase_client.get_service_client()
            client.storage.from_("results").upload(
                storage_path,
                annotated_bytes,
                {"content-type": "application/pdf", "upsert": "true"},
            )

            job.result_annotated_pdf_storage_path = storage_path
            job.annotate_status = "done"
            job.annotate_refundable = False
            job.annotate_recovery_notes = [{"skipped_matches": skipped}] if skipped else []
            db.commit()
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
