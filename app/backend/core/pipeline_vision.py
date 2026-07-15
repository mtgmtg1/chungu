#!/usr/bin/env python3
# [Flow: Step 1 (PDF->PNG 렌더) -> Step 2 (배치 PaddleOCR 또는 per-page LLM vision) -> Step 3 (진행률 콜백) -> Step 4 (페이지별 MD 표 수집)]
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

# AI Studio 기본 페이지 제한 — 한 job에 최대 10페이지까지 처리 가능
BATCH_SIZE = 10


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
    """PDF를 PNG로 렌더링한 후, 배치 PaddleOCR 또는 per-page LLM vision으로 변환한다.

    [Flow: Step 1 (총 페이지 수 계산) -> Step 2 (모든 페이지 렌더링 완료 대기) -> Step 3a (fallback 선호 시: 10페이지 배치로 PaddleOCR 제출, 실패 시 per-page 폴백) / Step 3b (fallback 비선호 시: per-page LLM vision) -> Step 4 (페이지 번호 순서로 결과 정렬) -> Step 5 (searchable PDF 생성용 layout_by_page 반환)]
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
    progress_state = {"rendered": 0, "ocr_done": 0}
    results: list[tuple[int, str | None, dict]] = []

    def update_progress() -> None:
        if not on_progress or total_pages <= 0:
            return
        progress = min(100, int((progress_state["rendered"] + progress_state["ocr_done"]) / (2 * total_pages) * 100))
        on_progress(progress, 100)

    def resolve_endpoint(idx: int) -> tuple[str, str, str]:
        return endpoint, model, api_key

    def _try_paddleocr_fallback(img: Path, page_num: int) -> tuple[str | None, dict]:
        """PaddleOCR 폴백으로 단일 페이지 이미지를 처리한다.

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
            logger.info(f"[vision-fallback] page {page_num} PaddleOCR 단일 폴백 성공")
            return fb_result, layout
        except Exception as e:
            logger.warning(f"[vision-fallback] page {page_num} PaddleOCR 단일 폴백 실패: {e}")
            return None, {}

    def process(page_idx: int, page_num: int, img: Path) -> tuple[int, str | None, dict]:
        """단일 페이지 이미지를 OCR 처리한다 (LLM vision 경로 + 단일 PaddleOCR 폴백).

        [Flow: Step 1 (PaddleOCR 폴백 우선 시도) -> Step 2 (폴백 실패 시 LLM vision 호출) -> Step 3 (예외 발생 시 최종 폴백 시도) -> Step 4 (완료 시 진행률 갱신)]
        """
        layout_raw: dict = {}
        try:
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
                progress_state["ocr_done"] += 1
                update_progress()

    def _process_batch(
        batch: list[tuple[int, Path]],
    ) -> list[tuple[int, str | None, dict]]:
        """한 배치(최대 10페이지)를 AI Studio에 단일 job로 제출하고 per-page 결과를 반환한다.

        [Flow: Step 1 (배치 이미지 추출) -> Step 2 (convert_images_batch_with_layout 호출) -> Step 3 (per-page 결과를 (page_num, markdown, layout) 튜플로 매핑)]
        """
        page_nums = [pn for pn, _ in batch]
        image_paths = [img for _, img in batch]
        batch_results: list[tuple[int, str | None, dict]] = []

        try:
            pages = paddleocr_client.convert_images_batch_with_layout(image_paths)
            for idx, (page_num, (md, layout, _angle)) in enumerate(zip(page_nums, pages)):
                extracted = ocr_client.extract_markdown_content(md)
                batch_results.append((page_num, extracted, layout))
            logger.info(f"[vision-batch] 배치 성공: pages {page_nums[0]}-{page_nums[-1]} ({len(page_nums)}장)")
        except Exception as e:
            logger.warning(f"[vision-batch] 배치 실패 (pages {page_nums[0]}-{page_nums[-1]}), per-page 폴백: {e}")
            raise

        return batch_results

    # Step 2: 모든 페이지 렌더링 (배치 처리를 위해 전체 완료 대기)
    def on_render_progress(done: int, total: int) -> None:
        with lock:
            progress_state["rendered"] = done
            update_progress()

    img_paths = ocr_client.render_pdf(pdf_path, str(img_dir), dpi=dpi, on_progress=on_render_progress)

    # 페이지 번호 추출 및 정렬
    page_images: list[tuple[int, Path]] = []
    for img_path in img_paths:
        page_num = ocr_client.find_page_number(img_path)
        if page_num is not None:
            page_images.append((page_num, img_path))
    page_images.sort(key=lambda x: x[0])

    if not page_images:
        return [], {}

    # Step 3: OCR 처리 경로 선택
    use_batch = fallback_controller.is_fallback_preferred() and len(page_images) > 1

    if use_batch:
        # Step 3a: 배치 PaddleOCR 경로 — 10페이지 단위로 묶어 병렬 제출
        batches = [
            page_images[i:i + BATCH_SIZE]
            for i in range(0, len(page_images), BATCH_SIZE)
        ]
        batch_workers = min(len(batches), max(1, settings.llm_max_workers // BATCH_SIZE))
        logger.info(f"[vision-batch] {len(page_images)}페이지 → {len(batches)}배치 (workers={batch_workers})")

        with ThreadPoolExecutor(max_workers=batch_workers) as batch_executor:
            future_to_batch = {
                batch_executor.submit(_process_batch, batch): batch
                for batch in batches
            }
            for future in as_completed(future_to_batch):
                batch = future_to_batch[future]
                try:
                    batch_results = future.result()
                    results.extend(batch_results)
                    with lock:
                        progress_state["ocr_done"] += len(batch_results)
                        update_progress()
                except Exception:
                    # 배치 실패 → per-page 폴백 (기존 process 함수 사용)
                    for page_idx, (page_num, img_path) in enumerate(batch):
                        try:
                            result = process(page_idx, page_num, img_path)
                            results.append(result)
                        except Exception as e:
                            if on_error:
                                on_error(page_num, str(e))
    else:
        # Step 3b: per-page LLM vision 경로 (기존 로직)
        ocr_workers = workers if workers is not None else min(total_pages, settings.llm_max_workers)
        with ThreadPoolExecutor(max_workers=ocr_workers) as ocr_executor:
            futures = {
                ocr_executor.submit(process, idx, page_num, img): page_num
                for idx, (page_num, img) in enumerate(page_images)
            }
            for future in as_completed(futures):
                page_num = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    if on_error:
                        on_error(page_num, str(e))

    # Step 4: 페이지 번호 순서로 정렬하여 반환
    results.sort(key=lambda x: x[0])
    page_tables = [(page_num, result) for page_num, result, _ in results if result]
    layout_by_page: dict[int, dict] = {page_num: layout for page_num, _, layout in results if layout}
    return page_tables, layout_by_page
