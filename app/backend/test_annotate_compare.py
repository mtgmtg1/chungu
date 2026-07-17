#!/usr/bin/env python3
"""두 가지 주석 파이프라인을 비교 테스트하는 스크립트.

Pipeline A (기존): PaddleOCR로 bbox 검출 → LLM 텍스트 기반 요소 선택 → 주석 적용
Pipeline B (Vision LLM only): Vision LLM이 이미지를 직접 보고 bbox 검출 + 요소 선택 → 주석 적용

사용법 (Docker 컨테이너 내부):
    python -m backend.test_annotate_compare /tmp/table2.png "100만원이 넘는 거래에 하이라이트하고 주석으로 내용을 달아줘"

결과:
    /tmp/annotate_pipeline_a_paddleocr.pdf  — PaddleOCR 기반 파이프라인 결과
    /tmp/annotate_pipeline_b_vision_llm.pdf — Vision LLM 기반 파이프라인 결과
"""
import json
import logging
import re
import sys
import tempfile
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

from .config import settings
from .core import ocr_client, paddleocr_client
from .core.ocr_layout import parse_layout_result
from .core.pdf_annotator import AnnotationTarget, build_embedpdf_annotations
from .core.pdf_coords import clamp_rect_to_page, px_bbox_to_pdf_rect
from .core.prompts import build_text_search_highlight_prompt, build_vision_text_highlight_prompt

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

RENDER_DPI = 200
MAX_ELEMENTS_FOR_LLM = 400
MAX_TEXT_BLOCK_CHARS = 200

LLM_ENDPOINT = settings.default_llm_endpoint
LLM_MODEL = settings.default_llm_model
LLM_API_KEY = settings.default_llm_api_key or ""


def _strip_json_fence(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"```[a-zA-Z]*\n?|\n?```", "", content).strip()
    return content


def _image_to_pdf(image_path: Path) -> bytes:
    """단일 이미지를 PDF로 변환한다 (RENDER_DPI 기준 포인트 크기)."""
    doc = fitz.open()
    img = fitz.Pixmap(str(image_path))
    width_pt = img.width * 72.0 / RENDER_DPI
    height_pt = img.height * 72.0 / RENDER_DPI
    page = doc.new_page(width=width_pt, height=height_pt)
    page.insert_image(fitz.Rect(0, 0, width_pt, height_pt), filename=str(image_path))
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


# ---------------------------------------------------------------------------
# Pipeline A: PaddleOCR 기반 (기존 로직)
# ---------------------------------------------------------------------------

def run_pipeline_a(image_path: Path, instruction: str, mode: str, want_llm_comment: bool) -> bytes:
    """PaddleOCR로 bbox를 검출하고 LLM이 텍스트만으로 요소를 선택하는 기존 파이프라인."""
    logger.info("[Pipeline A] PaddleOCR 레이아웃 추출 시작...")
    _markdown, layout_raw = paddleocr_client.convert_image_with_layout(image_path)
    layout = parse_layout_result(layout_raw, page_no=1)
    logger.info(f"[Pipeline A] PaddleOCR 완료: tables={len(layout.tables)}, text_blocks={len(layout.text_blocks)}")

    # 요소 수집 (표 행 + 텍스트 블록)
    elements: list[dict] = []
    element_bboxes: list[tuple[float, float, float, float]] = []
    for table in layout.tables:
        for row in table.rows:
            if not any(cell.strip() for cell in row.cell_texts):
                continue
            text = " | ".join(c.strip() for c in row.cell_texts if c.strip())
            elements.append({"kind": "table_row", "text": text})
            element_bboxes.append(row.bbox_px)
    for tb in layout.text_blocks:
        text = tb.text.replace("\n", " ").strip()[:MAX_TEXT_BLOCK_CHARS]
        elements.append({"kind": "text", "text": text})
        element_bboxes.append(tb.bbox_px)

    logger.info(f"[Pipeline A] 수집된 요소: {len(elements)}개")
    if not elements:
        raise ValueError("PaddleOCR로 텍스트 요소를 찾지 못했습니다")

    # PaddleOCR로부터 추출한 전체 텍스트를 한 페이지로 구성
    page_text = "\n".join(el.get("text", "") for el in elements)
    prompt = build_text_search_highlight_prompt([(1, page_text)], instruction, want_llm_comment)
    logger.info("[Pipeline A] LLM 텍스트 선택 요청...")
    content, _ = ocr_client.call_text(prompt, LLM_ENDPOINT, LLM_MODEL, LLM_API_KEY, max_tokens=4000)
    content = _strip_json_fence(content)
    data = json.loads(content)
    matches = data.get("matches", []) if isinstance(data, dict) else []
    logger.info(f"[Pipeline A] LLM 선택 결과: {len(matches)}개 매칭")

    # 주석 타겟 생성
    pdf_bytes = _image_to_pdf(image_path)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_width = doc[0].mediabox.width
    page_height = doc[0].mediabox.height
    doc.close()

    # 이미지 픽셀 높이 (y축 flip용)
    from PIL import Image as PILImage
    with PILImage.open(image_path) as img:
        img_h = img.height

    targets: list[AnnotationTarget] = []
    for m in matches:
        text = str(m.get("text") or "").strip()
        if not text:
            continue
        # OCR로 수집한 텍스트 중 일치하는 첫 번째 요소의 bbox 사용
        for el, bbox_px in zip(elements, element_bboxes):
            if text in el.get("text", "") or el.get("text", "") in text:
                rect_pdf = px_bbox_to_pdf_rect(bbox_px, dpi=RENDER_DPI, page_height_px=img_h)
                rect_pdf = clamp_rect_to_page(rect_pdf, page_width, page_height)
                comment = str(m.get("comment") or instruction).strip() or instruction
                targets.append(AnnotationTarget(page_no=1, bbox_pdf=rect_pdf, comment=comment))
                break

    logger.info(f"[Pipeline A] 주석 적용: {len(targets)}개 타겟")
    annotations = build_embedpdf_annotations(pdf_bytes, targets, mode)
    return pdf_bytes, annotations


# ---------------------------------------------------------------------------
# Pipeline B: Vision LLM text + OCR bbox 검색
# ---------------------------------------------------------------------------

def run_pipeline_b(image_path: Path, instruction: str, mode: str, want_llm_comment: bool) -> bytes:
    """Vision LLM이 이미지에서 텍스트 내용만 반환하고, PaddleOCR로 bbox를 검색하는 파이프라인."""
    with Image.open(image_path) as img:
        img_w, img_h = img.size
    logger.info(f"[Pipeline B] 이미지 크기: {img_w}x{img_h}")

    fitted = ocr_client.fit_image_to_gemma4_resolution(image_path)
    prompt = build_vision_text_highlight_prompt(instruction, want_llm_comment)
    logger.info("[Pipeline B] Vision LLM 텍스트 내용 요청...")
    content, _ = ocr_client.call_vision(fitted, prompt, LLM_ENDPOINT, LLM_MODEL, LLM_API_KEY, max_tokens=4000)
    content = _strip_json_fence(content)

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"[Pipeline B] JSON 파싱 실패: {e}")
        logger.error(f"[Pipeline B] LLM 응답 (앞 500자): {content[:500]}")
        raise

    matches = data.get("matches", []) if isinstance(data, dict) else []
    logger.info(f"[Pipeline B] LLM 반환 매칭: {len(matches)}개")

    # PaddleOCR로 bbox를 확보해 Vision LLM이 반환한 text를 검색한다.
    _md, layout_raw = paddleocr_client.convert_image_with_layout(image_path)
    ocr_texts: list[str] = []
    ocr_bboxes: list[tuple[float, float, float, float]] = []
    overall = (layout_raw or {}).get("overall_ocr_res", {}) if isinstance(layout_raw, dict) else {}
    for rec_text, rec_box in zip(overall.get("rec_texts", []), overall.get("rec_boxes", [])):
        if isinstance(rec_text, str) and isinstance(rec_box, (list, tuple)) and len(rec_box) == 4:
            ocr_texts.append(rec_text.strip())
            ocr_bboxes.append(tuple(float(v) for v in rec_box))

    # PDF 생성 (원본 이미지 기준)
    pdf_bytes = _image_to_pdf(image_path)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_width = doc[0].mediabox.width
    page_height = doc[0].mediabox.height
    doc.close()

    targets: list[AnnotationTarget] = []
    for m in matches:
        text = str(m.get("text") or "").strip()
        if not text:
            continue
        for ocr_text, ocr_box in zip(ocr_texts, ocr_bboxes):
            if text in ocr_text or ocr_text in text:
                # normalized 좌표라고 가정하고 픽셀 좌표로 변환
                x0, y0, x1, y1 = ocr_box
                if all(0 <= v <= 1.01 for v in (x0, y0, x1, y1)):
                    x0 *= img_w
                    y0 *= img_h
                    x1 *= img_w
                    y1 *= img_h
                rect_pdf = px_bbox_to_pdf_rect((x0, y0, x1, y1), dpi=RENDER_DPI, page_height_px=img_h)
                rect_pdf = clamp_rect_to_page(rect_pdf, page_width, page_height)
                comment = str(m.get("comment") or instruction).strip() or instruction
                targets.append(AnnotationTarget(page_no=1, bbox_pdf=rect_pdf, comment=comment))
                logger.info(f"[Pipeline B] 매칭: text={text!r} comment={comment!r}")
                break

    logger.info(f"[Pipeline B] 주석 적용: {len(targets)}개 타겟")
    if not targets:
        logger.warning("[Pipeline B] 매칭된 타겟이 없습니다. 빈 PDF를 반환합니다.")
        return pdf_bytes, []
    annotations = build_embedpdf_annotations(pdf_bytes, targets, mode)
    return pdf_bytes, annotations


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 3:
        print("Usage: python -m backend.test_annotate_compare <image_path> <instruction> [mode] [comment_mode]")
        print("Example: python -m backend.test_annotate_compare /tmp/table2.png '100만원이 넘는 거래에 하이라이트하고 주석으로 내용을 달아줘' both llm_summary")
        sys.exit(1)

    image_path = Path(sys.argv[1])
    instruction = sys.argv[2]
    mode = sys.argv[3] if len(sys.argv) > 3 else "both"
    comment_mode = sys.argv[4] if len(sys.argv) > 4 else "llm_summary"
    want_llm_comment = comment_mode == "llm_summary"

    if not image_path.exists():
        print(f"Error: image not found: {image_path}")
        sys.exit(1)

    out_a_pdf = Path("/tmp/annotate_pipeline_a_paddleocr.pdf")
    out_a_json = Path("/tmp/annotate_pipeline_a_paddleocr.annotations.json")
    out_b_pdf = Path("/tmp/annotate_pipeline_b_vision_llm.pdf")
    out_b_json = Path("/tmp/annotate_pipeline_b_vision_llm.annotations.json")

    # Pipeline A: PaddleOCR 기반
    print(f"\n{'='*60}")
    print("Pipeline A: PaddleOCR + LLM text selection")
    print(f"{'='*60}")
    try:
        pdf_a, ann_a = run_pipeline_a(image_path, instruction, mode, want_llm_comment)
        out_a_pdf.write_bytes(pdf_a)
        out_a_json.write_text(json.dumps(ann_a, ensure_ascii=False, indent=2))
        print(f"[OK] Pipeline A 결과 저장: {out_a_pdf} ({len(pdf_a)} bytes), {out_a_json} ({len(ann_a)} annotations)")
    except Exception as e:
        print(f"[FAIL] Pipeline A 오류: {e}")
        import traceback
        traceback.print_exc()

    # Pipeline B: Vision LLM only
    print(f"\n{'='*60}")
    print("Pipeline B: Vision LLM direct bbox detection")
    print(f"{'='*60}")
    try:
        pdf_b, ann_b = run_pipeline_b(image_path, instruction, mode, want_llm_comment)
        out_b_pdf.write_bytes(pdf_b)
        out_b_json.write_text(json.dumps(ann_b, ensure_ascii=False, indent=2))
        print(f"[OK] Pipeline B 결과 저장: {out_b_pdf} ({len(pdf_b)} bytes), {out_b_json} ({len(ann_b)} annotations)")
    except Exception as e:
        print(f"[FAIL] Pipeline B 오류: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n{'='*60}")
    print("완료. 결과 파일:")
    print(f"  Pipeline A (PaddleOCR): {out_a_pdf} + {out_a_json}")
    print(f"  Pipeline B (Vision LLM): {out_b_pdf} + {out_b_json}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
