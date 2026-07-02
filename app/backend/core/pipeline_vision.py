#!/usr/bin/env python3
# [Flow: Step 1 (PDF->PNG 렌더) -> Step 2 (페이지 병렬 vision OCR) -> Step 3 (진행률 콜백) -> Step 4 (페이지별 MD 표 수집)]
# 기존 ocr_run.py 의 vision 파이프라인을 함수형으로 일반화.
import logging
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
) -> list[tuple[int, str]]:
    """Vision 파이프라인 실행 -> [(page_num, markdown_table)] 반환.

    media_endpoint가 제공되면 페이지를 처리량에 따라 동적 분배한다.
    속도가 유사하므로 페이지를 vLLM에 집중하고, E4B는 오디오/비디오 우선 처리를 위해
    이미지 부하를 크게 줄인다.
    - ≤6: 1:3 (E4B 1/3)
    - 7~59: 1:5 (E4B 1/5)
    - ≥60: 1:10 (E4B 1/10)
    """
    work = Path(work_dir)
    img_dir = work / "img"
    images = ocr_client.render_pdf(pdf_path, str(img_dir), dpi=dpi)
    pages = [(ocr_client.find_page_number(p), p) for p in images]
    pages = [(n, p) for n, p in pages if n is not None]
    pages.sort(key=lambda x: x[0])
    total = len(pages)
    prompt = build_vision_prompt(columns, extra_prompt)

    results: list[tuple[int, str]] = []
    done = 0

    def resolve_endpoint(idx: int) -> tuple[str, str, str]:
        return endpoint, model, api_key

    def _try_paddleocr_fallback(img: Path, page_num: int) -> str | None:
        """PaddleOCR 폴백으로 페이지 이미지를 처리한다.

        [Flow: Step 1 (폴백 가능 여부 확인) -> Step 2 (paddleocr_client.convert_image 호출) -> Step 3 (성공 시 consume_fallback, markdown 반환) -> Step 4 (실패 시 None)]
        """
        if not fallback_controller.can_use_fallback():
            return None
        try:
            md = paddleocr_client.convert_image(img)
            fallback_controller.consume_fallback()
            logger.info(f"[vision-fallback] page {page_num} PaddleOCR 폴백 성공")
            return ocr_client.extract_markdown_content(md)
        except Exception as e:
            logger.warning(f"[vision-fallback] page {page_num} PaddleOCR 폴백 실패: {e}")
            return None

    def process(page_idx: int, page_num: int, img: Path) -> tuple[int, str]:
        # run_vision으로 라우팅된 모든 페이지는 PaddleOCR을 우선 사용한다
        if fallback_controller.is_fallback_preferred():
            fb_result = _try_paddleocr_fallback(img, page_num)
            if fb_result is not None:
                return page_num, fb_result
            # 폴백 실패 시 기본 요청으로 진행

        ep, mdl, key = resolve_endpoint(page_idx)
        try:
            content, _ = ocr_client.call_vision(img, prompt, ep, mdl, key, max_tokens)
            fallback_controller.record_success()
            return page_num, ocr_client.extract_markdown_content(content)
        except Exception as e:
            fallback_controller.record_failure()
            logger.warning(f"[vision] page {page_num} 기본 요청 실패, PaddleOCR 폴백 시도: {e}")
            fb_result = _try_paddleocr_fallback(img, page_num)
            if fb_result is not None:
                return page_num, fb_result
            raise

    with ThreadPoolExecutor(max_workers=workers if workers is not None else min(total, settings.llm_max_workers)) as executor:
        futures = {executor.submit(process, idx, n, p): n for idx, (n, p) in enumerate(pages)}
        for future in as_completed(futures):
            page_num = futures[future]
            try:
                results.append(future.result())
            except Exception as e:  # noqa: BLE001
                if on_error:
                    on_error(page_num, str(e))
            finally:
                done += 1
                if on_progress:
                    on_progress(done, total)
    return results
