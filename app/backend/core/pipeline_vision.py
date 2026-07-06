#!/usr/bin/env python3
# [Flow: Step 1 (PDF->PNG 렌더, 완료 페이지 즉시 OCR 제출) -> Step 2 (페이지 병렬 vision OCR) -> Step 3 (2×N 단위 진행률 콜백) -> Step 4 (페이지별 MD 표 수집)]
# 기존 ocr_run.py 의 vision 파이프라인을 함수형으로 일반화.
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from . import ocr_client, paddleocr_client
from .paddleocr_fallback import fallback_controller
from .prompts import build_vision_prompt
from ..config import settings

logger = logging.getLogger(__name__)


def _detect_provider(endpoint: str, model: str = "") -> str:
    """엔드포인트 주소/모델명으로 API 제공자를 추정한다."""
    ep = (endpoint or "").lower()
    md = (model or "").lower()
    if "llama" in ep or "gguf" in md or "gguf" in ep:
        return "llama.cpp"
    return "openai"


def run_vision(
    pdf_path: str,
    work_dir: str,
    columns: list[str],
    endpoint: str,
    model: str,
    api_key: str = "",
    extra_prompt: str = "",
    dpi: int = 300,
    workers: int | None = None,
    max_tokens: int = 10000,
    media_endpoint: str | None = None,
    media_model: str | None = None,
    media_api_key: str = "",
    on_progress: Callable[[int, int], None] | None = None,
    on_error: Callable[[int, str], None] | None = None,
) -> tuple[list[tuple[int, str]], dict[int, dict]]:
    """PDF를 PNG로 렌더링하면서 렌더링이 완료된 페이지는 즉시 OCR에 제출한다.

    [Flow: Step 1 (총 페이지 수 계산) -> Step 2 (OCR executor 생성) -> Step 3 (render_pdf에 on_page_rendered 콜백 전달, 렌더링 완료 페이지 즉시 OCR 제출) -> Step 4 (모든 OCR future 수집/대기) -> Step 5 (페이지 번호 순서로 결과 반환) -> Step 6 (searchable PDF 생성용 layout_by_page 반환)]
    """
    work = Path(work_dir)
    img_dir = work / "img"

    # Step 1: 총 페이지 수 미리 계산
    import fitz
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()

    prompt = build_vision_prompt(columns, extra_prompt)
    lock = threading.Lock()
    rendered_count = 0
    ocr_done_count = 0
    ocr_futures: set = set()
    future_to_page_num: dict = {}
    results: list[tuple[int, str | None, dict]] = []

    def update_progress() -> None:
        if not on_progress or total_pages <= 0:
            return
        progress = min(100, int((rendered_count + ocr_done_count) / (2 * total_pages) * 100))
        on_progress(progress, 100)

    def resolve_endpoint(idx: int) -> tuple[str, str, str]:
        return endpoint, model, api_key

    def _try_paddleocr_fallback(img: Path, page_num: int) -> tuple[str | None, dict]:
        """PaddleOCR 폴백으로 페이지 이미지를 처리한다.

        [Flow: Step 1 (폴백 가능 여부 확인) -> Step 2 (paddleocr_client.convert_image_with_layout 호출)
              -> Step 3 (성공 시 consume_fallback, markdown + layout 반환) -> Step 4 (실패 시 None, {})]
        """
        if not fallback_controller.can_use_fallback():
            return None, {}
        try:
            md, layout, _ = paddleocr_client.convert_image_with_layout(img)
            fb_result = ocr_client.extract_markdown_content(md)
            if not fb_result:
                return None, {}
            fallback_controller.consume_fallback()
            logger.info(f"[vision-fallback] page {page_num} PaddleOCR 폴백 성공")
            return fb_result, layout
        except Exception as e:
            logger.warning(f"[vision-fallback] page {page_num} PaddleOCR 폴백 실패: {e}")
            return None, {}

    def process(page_idx: int, page_num: int, img: Path) -> tuple[int, str | None, dict]:
        """단일 페이지 이미지를 OCR 처리한다.

        [Flow: Step 1 (PaddleOCR 폴백 우선 시도) -> Step 2 (폴백 실패 시 LLM vision 호출) -> Step 3 (예외 발생 시 최종 폴백 시도) -> Step 4 (완료 시 진행률 갱신)]
        """
        nonlocal ocr_done_count
        layout_raw: dict = {}
        try:
            # run_vision으로 라우팅된 모든 페이지는 PaddleOCR을 우선 사용한다
            if fallback_controller.is_fallback_preferred():
                fb_result, layout_raw = _try_paddleocr_fallback(img, page_num)
                if fb_result:
                    return page_num, fb_result, layout_raw
                # 폴백 실패 시 기본 요청으로 진행

            ep, mdl, key = resolve_endpoint(page_idx)
            try:
                content, _ = ocr_client.call_vision(img, prompt, ep, mdl, key, max_tokens)
                fallback_controller.record_success()
                return page_num, ocr_client.extract_markdown_content(content), layout_raw
            except Exception as e:
                fallback_controller.record_failure()
                logger.warning(f"[vision] page {page_num} 기본 요청 실패, PaddleOCR 폴백 시도: {e}")
                fb_result, layout_raw = _try_paddleocr_fallback(img, page_num)
                if fb_result:
                    return page_num, fb_result, layout_raw
                raise
        finally:
            with lock:
                ocr_done_count += 1
                update_progress()

    ocr_workers = workers if workers is not None else min(total_pages, settings.llm_max_workers)
    with ThreadPoolExecutor(max_workers=ocr_workers) as ocr_executor:
        def on_page_rendered(page_idx: int, img_path: Path) -> None:
            """페이지 렌더링이 완료되면 즉시 OCR 작업을 제출하고 진행률을 갱신한다.

            [Flow: Step 1 (페이지 번호 추출) -> Step 2 (렌더링 카운트 증가 및 진행률 갱신) -> Step 3 (OCR executor에 작업 제출)]
            """
            nonlocal rendered_count
            page_num = ocr_client.find_page_number(img_path)
            if page_num is None:
                return
            with lock:
                rendered_count += 1
                update_progress()
            future = ocr_executor.submit(process, page_idx, page_num, img_path)
            with lock:
                ocr_futures.add(future)
                future_to_page_num[future] = page_num

        # Step 3: 렌더링 시작, 완료된 페이지는 즉시 OCR로 제출
        ocr_client.render_pdf(pdf_path, str(img_dir), dpi=dpi, on_page_rendered=on_page_rendered)

        # Step 4: 모든 OCR 작업 대기
        with lock:
            pending_futures = list(ocr_futures)
        for future in as_completed(pending_futures):
            page_num = future_to_page_num.get(future)
            try:
                page_num, result, layout_raw = future.result()
                results.append((page_num, result, layout_raw))
            except Exception as e:  # noqa: BLE001
                if on_error and page_num is not None:
                    on_error(page_num, str(e))

    # Step 5: 페이지 번호 순서로 정렬하여 반환
    results.sort(key=lambda x: x[0])
    page_tables = [(page_num, result) for page_num, result, _ in results if result]
    layout_by_page: dict[int, dict] = {page_num: layout for page_num, _, layout in results if layout}
    return page_tables, layout_by_page
