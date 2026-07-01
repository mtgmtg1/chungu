#!/usr/bin/env python3
# [Flow: Step 1 (Docling 서비스에서 마크다운 추출) -> Step 2 (마크다운을 LLM에 전송) -> Step 3 (CSV 구조화) -> Step 4 (페이지 결과 반환)]
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from . import docling_client, ocr_client
from .prompts import build_text_prompt
from ..config import settings

logger = logging.getLogger(__name__)


def run_hybrid(
    pdf_path: Path,
    work_dir: str,
    columns: list[str],
    endpoint: str,
    model: str,
    api_key: str = "",
    extra_prompt: str = "",
    max_tokens: int = 4000,
    ocr_engine: str = "tesseract",
    on_progress: Callable[[int, int], None] | None = None,
    on_error: Callable[[int, str], None] | None = None,
    ocr_workers: int = 4,
    workers: int | None = None,
) -> list[tuple[int, str]]:
    """Hybrid 파이프라인: Docling 마크다운 -> LLM CSV 구조화.

    [Flow: Step 1 (Docling 서비스에서 마크다운 추출) -> Step 2 (LLM에 CSV 변환 요청) -> Step 3 (CSV 결과 반환)]
    """
    if on_progress:
        on_progress(0, 1)

    try:
        markdown, _image_paths = docling_client.convert_file(pdf_path, ocr_engine=ocr_engine)
    except Exception as e:
        logger.exception(f"[hybrid] {pdf_path.name} Docling 변환 실패: {e}")
        if on_error:
            on_error(1, str(e))
        return []

    prompt = build_text_prompt(columns, markdown, extra_prompt)
    try:
        content, _ = ocr_client.call_text(prompt, endpoint, model, api_key, max_tokens)
        block = ocr_client.extract_csv(content)
        if block and not block.splitlines()[0].startswith(columns[0]):
            block = ",".join(columns) + "\n" + block
        if on_progress:
            on_progress(1, 1)
        return [(1, block)]
    except Exception as e:
        logger.exception(f"[hybrid] {pdf_path.name} LLM 구조화 실패: {e}")
        if on_error:
            on_error(1, str(e))
        if on_progress:
            on_progress(1, 1)
        return [(1, "")]
