#!/usr/bin/env python3
# [Flow: Step 1 (PDF->PNG 렌더) -> Step 2 (Tesseract 원문 추출) -> Step 3 (LLM CSV 구조화) -> Step 4 (진행률 콜백) -> Step 5 (페이지별 CSV 수집)]
# 기존 ocr_hybrid.py 의 hybrid 파이프라인을 함수형으로 일반화.
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from . import ocr_client
from .prompts import build_text_prompt


def run_hybrid(
    pdf_path: str,
    work_dir: str,
    columns: list[str],
    endpoint: str,
    model: str,
    api_key: str = "",
    extra_prompt: str = "",
    dpi: int = 150,
    ocr_workers: int = 4,
    llm_workers: int | None = None,
    max_tokens: int = 4000,
    lang: str = "kor+eng",
    on_progress: Callable[[int, int], None] | None = None,
    on_error: Callable[[int, str], None] | None = None,
) -> list[tuple[int, str]]:
    """Hybrid 파이프라인 실행 -> [(page_num, csv_block)] 반환."""
    work = Path(work_dir)
    img_dir = work / "img"
    text_dir = work / "text"
    text_dir.mkdir(parents=True, exist_ok=True)

    images = ocr_client.render_pdf(pdf_path, str(img_dir), dpi=dpi)
    pages = [(ocr_client.find_page_number(p), p) for p in images]
    pages = [(n, p) for n, p in pages if n is not None]
    pages.sort(key=lambda x: x[0])
    total = len(pages)

    # Step 2: Tesseract 원문 추출 (병렬)
    with ThreadPoolExecutor(max_workers=ocr_workers) as executor:
        futures = {
            executor.submit(ocr_client.tesseract_ocr, img, text_dir / f"page_{n:03d}.txt", lang): n
            for n, img in pages
        }
        for future in as_completed(futures):
            n = futures[future]
            try:
                future.result()
            except Exception as e:  # noqa: BLE001
                if on_error:
                    on_error(n, f"tesseract: {e}")

    # Step 3: LLM CSV 구조화 (병렬)
    results: list[tuple[int, str]] = []
    done = 0

    def structure(page_num: int) -> tuple[int, str]:
        text_path = text_dir / f"page_{page_num:03d}.txt"
        text = text_path.read_text(encoding="utf-8") if text_path.exists() else ""
        if not text.strip():
            return page_num, ",".join(columns)
        prompt = build_text_prompt(columns, text, extra_prompt)
        content, _ = ocr_client.call_text(prompt, endpoint, model, api_key, max_tokens)
        # 헤더 보강: 모델이 헤더를 빠뜨리면 붙여준다
        block = ocr_client.extract_csv(content)
        if block and not block.splitlines()[0].startswith(columns[0]):
            block = ",".join(columns) + "\n" + block
        return page_num, block

    with ThreadPoolExecutor(max_workers=llm_workers if llm_workers is not None else total) as executor:
        futures = {executor.submit(structure, n): n for n, _ in pages}
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
