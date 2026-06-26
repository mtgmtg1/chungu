#!/usr/bin/env python3
# [Flow: Step 1 (PDF->PNG 렌더) -> Step 2 (페이지 병렬 vision OCR) -> Step 3 (진행률 콜백) -> Step 4 (페이지별 MD 표 수집)]
# 기존 ocr_run.py 의 vision 파이프라인을 함수형으로 일반화.
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from . import ocr_client
from .prompts import build_vision_prompt


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
    on_progress: Callable[[int, int], None] | None = None,
    on_error: Callable[[int, str], None] | None = None,
) -> list[tuple[int, str]]:
    """Vision 파이프라인 실행 -> [(page_num, markdown_table)] 반환."""
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

    def process(page_num: int, img: Path) -> tuple[int, str]:
        page_text = ocr_client.extract_pdf_page_text(pdf_path, page_num)
        content, _ = ocr_client.call_vision(img, prompt, endpoint, model, api_key, max_tokens, page_text=page_text)
        return page_num, ocr_client.extract_markdown_content(content)

    with ThreadPoolExecutor(max_workers=workers if workers is not None else total) as executor:
        futures = {executor.submit(process, n, p): n for n, p in pages}
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
