#!/usr/bin/env python3
# [Flow: Step 1 (PDF 첫 페이지 렌더) -> Step 2 (vLLM OCR) -> Step 3 (E4B OCR) -> Step 4 (결과 비교 출력)]
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from backend.core import ocr_client
from backend.core.prompts import build_vision_prompt
from backend.config import settings


def compare_ocr(pdf_path: str, work_dir: str, columns: list[str] | None = None) -> tuple[str, str]:
    """동일한 PDF 첫 페이지를 vLLM과 E4B로 각각 OCR하여 결과를 반환한다."""
    columns = columns or ["품목", "수량", "단가", "금액"]
    img_dir = Path(work_dir) / "compare_img"
    img_dir.mkdir(parents=True, exist_ok=True)
    images = ocr_client.render_pdf(pdf_path, str(img_dir), dpi=300)
    if not images:
        raise FileNotFoundError(f"PDF에서 이미지를 렌더링할 수 없습니다: {pdf_path}")
    img = images[0]
    prompt = build_vision_prompt(columns)

    print("=== vLLM (default) ===")
    vllm_content, _ = ocr_client.call_vision(
        img,
        prompt,
        settings.default_llm_endpoint,
        settings.default_llm_model,
        settings.default_llm_api_key,
    )
    print(vllm_content)

    print("\n=== E4B (media) ===")
    e4b_content, _ = ocr_client.call_vision(
        img,
        prompt,
        settings.media_llm_endpoint,
        settings.media_llm_model,
        settings.media_llm_api_key,
    )
    print(e4b_content)

    return vllm_content, e4b_content


if __name__ == "__main__":
    import sys

    pdf = sys.argv[1] if len(sys.argv) > 1 else "/tmp/input.pdf"
    compare_ocr(pdf, "/tmp/compare")
