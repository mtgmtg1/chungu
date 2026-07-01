#!/usr/bin/env python3
# [Flow: Step 1 (Docling 서비스에서 마크다운 추출) -> Step 2 (LLM refinement 선택) -> Step 3 (페이지 결과 반환)]
import logging
import tempfile
from pathlib import Path
from typing import Callable

from . import docling_client, hwp_converter, ocr_client
from .prompts import build_docling_refinement_prompt
from ..config import settings

logger = logging.getLogger(__name__)


def _detect_provider(endpoint: str, model: str) -> str:
    if "18080" in endpoint or "llama" in model.lower():
        return "llama.cpp"
    return "openai"


def _resize_image_if_needed(image_path: Path, max_size: int) -> Path:
    from PIL import Image
    with Image.open(image_path) as img:
        w, h = img.size
    if max(w, h) <= max_size:
        return image_path
    resized = image_path.with_suffix(".resized.png")
    import subprocess
    subprocess.run(
        ["magick", str(image_path), "-resize", f"{max_size}x{max_size}", str(resized)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return resized


def run_docling(
    file_path: Path,
    work_dir: str,
    columns: list[str],
    endpoint: str = "",
    model: str = "",
    api_key: str = "",
    extra_prompt: str = "",
    use_refinement: bool = False,
    max_tokens: int = 10000,
    media_endpoint: str | None = None,
    media_model: str | None = None,
    media_api_key: str = "",
    max_images: int | None = None,
    image_max_size: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    on_error: Callable[[int, str], None] | None = None,
    ocr_engine: str = "tesseract",
) -> list[tuple[int, str]]:
    """Docling 서비스로 문서를 변환하고, 선택적으로 LLM 후처리를 수행한다.

    [Flow: Step 1 (Docling 서비스 변환) -> Step 2 (마크다운 추출) -> Step 3 (LLM refinement) -> Step 4 (페이지 결과 반환)]
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    if on_progress:
        on_progress(0, 100)

    try:
        markdown, image_paths = docling_client.convert_file(
            file_path, ocr_engine=ocr_engine, on_progress=on_progress,
        )
    except Exception as e:
        logger.exception(f"[docling] {file_path.name} 변환 실패: {e}")
        if on_error:
            on_error(1, str(e))
        return []

    if not use_refinement:
        if on_progress:
            on_progress(100, 100)
        return [(1, markdown)]

    max_images = max_images if max_images is not None else settings.docling_max_images_per_doc
    max_size = image_max_size if image_max_size is not None else settings.docling_image_max_size
    selected_images = image_paths[:max_images]
    resized_images = [_resize_image_if_needed(p, max_size) for p in selected_images]

    prompt = build_docling_refinement_prompt(columns, markdown, extra_prompt)
    target_endpoint = media_endpoint or endpoint
    target_model = media_model or model
    target_api_key = media_api_key or api_key
    provider = _detect_provider(target_endpoint, target_model)

    try:
        content, _ = ocr_client.call_media(
            prompt, target_endpoint, target_model, target_api_key,
            image_paths=resized_images, max_tokens=max_tokens, provider=provider,
        )
        refined = ocr_client.extract_markdown_content(content)
        if on_progress:
            on_progress(100, 100)
        return [(1, refined)]
    except Exception as e:
        logger.warning(f"[docling-refinement] {file_path.name} LLM 후처리 실패, 원본 사용: {e}")
        if on_error:
            on_error(1, f"refinement failed: {e}")
        if on_progress:
            on_progress(100, 100)
        return [(1, markdown)]


def run_hwp(
    file_path: Path,
    work_dir: str,
    columns: list[str],
    endpoint: str,
    model: str,
    api_key: str = "",
    extra_prompt: str = "",
    use_refinement: bool = False,
    max_tokens: int = 10000,
    media_endpoint: str | None = None,
    media_model: str | None = None,
    media_api_key: str = "",
    max_images: int | None = None,
    image_max_size: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    on_error: Callable[[int, str], None] | None = None,
    ocr_engine: str = "tesseract",
) -> list[tuple[int, str]]:
    """HWP/HWPX 전처리 파이프라인: HWP -> DOCX -> Docling -> (선택) LLM refinement.

    [Flow: Step 1 (HWP -> DOCX 변환) -> Step 2 (DOCX -> Docling 변환) -> Step 3 (실패 시 pyhwp2md fallback) -> Step 4 (LLM refinement)]
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    try:
        docx_path = hwp_converter.convert_to_docx(file_path, work)
        logger.info(f"[hwp] {file_path.name} -> DOCX 변환 성공, Docling 경로로 처리합니다")
        return run_docling(
            docx_path, work_dir, columns, endpoint, model, api_key, extra_prompt,
            use_refinement, max_tokens, media_endpoint, media_model, media_api_key,
            max_images, image_max_size, on_progress, on_error, ocr_engine,
        )
    except Exception as e:
        logger.warning(f"[hwp] {file_path.name} DOCX/Docling 처리 실패, pyhwp2md fallback: {e}")

    img_dir = work / "hwp_images"
    try:
        result = hwp_converter.convert_hwp(file_path, img_dir)
    except Exception as e:
        logger.exception(f"[hwp] {file_path.name} 변환 실패: {e}")
        if on_error:
            on_error(1, str(e))
        return []

    markdown = result.get("markdown", "")
    image_paths = [img_dir / p for p in result.get("images", [])]

    if not use_refinement:
        return [(1, markdown)]

    max_images = max_images if max_images is not None else settings.docling_max_images_per_doc
    max_size = image_max_size if image_max_size is not None else settings.docling_image_max_size
    selected_images = image_paths[:max_images]
    resized_images = [_resize_image_if_needed(p, max_size) for p in selected_images]

    prompt = build_docling_refinement_prompt(columns, markdown, extra_prompt)
    target_endpoint = media_endpoint or endpoint
    target_model = media_model or model
    target_api_key = media_api_key or api_key
    provider = _detect_provider(target_endpoint, target_model)

    try:
        content, _ = ocr_client.call_media(
            prompt, target_endpoint, target_model, target_api_key,
            image_paths=resized_images, max_tokens=max_tokens, provider=provider,
        )
        refined = ocr_client.extract_markdown_content(content)
        return [(1, refined)]
    except Exception as e:
        logger.warning(f"[hwp-refinement] {file_path.name} LLM 후처리 실패, 원본 사용: {e}")
        if on_error:
            on_error(1, f"refinement failed: {e}")
        return [(1, markdown)]
