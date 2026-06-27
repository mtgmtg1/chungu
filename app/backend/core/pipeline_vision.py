#!/usr/bin/env python3
# [Flow: Step 1 (PDF->PNG 렌더) -> Step 2 (페이지 병렬 vision OCR) -> Step 3 (진행률 콜백) -> Step 4 (페이지별 MD 표 수집)]
# 기존 ocr_run.py 의 vision 파이프라인을 함수형으로 일반화.
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from . import ocr_client
from .prompts import build_vision_prompt
from ..config import settings


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
    - ≤20: 1:4 (vLLM:E4B), 소량은 E4B가 4배 빠름
    - 21~200: 1:1, 균형
    - >200: 4:1, vLLM 고배치가 압도적
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
        if not (media_endpoint and media_model):
            return endpoint, model, api_key
        if total <= 20:
            use_media = (idx % 5 != 0)       # 1:4 (E4B 80%)
        elif total <= 200:
            use_media = (idx % 2 != 0)       # 1:1 (50/50)
        else:
            use_media = (idx % 5 == 0)       # 4:1 (vLLM 80%)
        if use_media:
            return media_endpoint, media_model, media_api_key
        return endpoint, model, api_key

    def process(page_idx: int, page_num: int, img: Path) -> tuple[int, str]:
        ep, mdl, key = resolve_endpoint(page_idx)
        page_text = ocr_client.extract_pdf_page_text(pdf_path, page_num)
        content, _ = ocr_client.call_vision(img, prompt, ep, mdl, key, max_tokens, page_text=page_text)
        return page_num, ocr_client.extract_markdown_content(content)

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
