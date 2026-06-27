#!/usr/bin/env python3
# [Flow: Step 1 (Docling 서비스로 문서 변환) -> Step 2 (이미지 다운로드) -> Step 3 (use_docling_refinement 옵션 분기) -> Step 4 (LLM 후처리 또는 마크다운 그대로) -> Step 5 (페이지 결과 반환)]
import logging
from pathlib import Path
from typing import Callable

from PIL import Image

from . import docling_client, hwp_converter, ocr_client
from .prompts import build_docling_refinement_prompt
from ..config import settings


logger = logging.getLogger(__name__)


def _detect_provider(endpoint: str, model: str = "") -> str:
    """엔드포인트 주소/모델명으로 API 제공자를 추정한다."""
    ep = (endpoint or "").lower()
    md = (model or "").lower()
    if "llama" in ep or "gguf" in md or "gguf" in ep:
        return "llama.cpp"
    return "openai"


def _resize_image_if_needed(image_path: Path, max_size: int) -> Path:
    """이미지 긴 변을 max_size 픽셀 이하로 줄인다."""
    if not image_path.exists():
        return image_path
    try:
        with Image.open(image_path) as img:
            w, h = img.size
            if max(w, h) <= max_size:
                return image_path
            if w > h:
                new_w = max_size
                new_h = max(1, int(h * max_size / w))
            else:
                new_h = max_size
                new_w = max(1, int(w * max_size / h))
            resized = img.resize((new_w, new_h), Image.LANCZOS)
        resized_path = image_path.with_suffix(".resized.png")
        resized.save(resized_path, "PNG")
        return resized_path
    except Exception as e:
        logger.warning(f"[docling-image] 리사이즈 실패 {image_path}: {e}")
        return image_path


def _download_images(images: list[str], image_dir: Path, max_images: int, max_size: int) -> list[Path]:
    """b2 Docling 서비스에서 이미지를 다운로드하고 크기를 조정한다."""
    image_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []
    for rel in images[:max_images]:
        try:
            data = docling_client.download_image(rel)
            out = image_dir / Path(rel).name
            out.write_bytes(data)
            downloaded.append(_resize_image_if_needed(out, max_size))
        except Exception as e:
            logger.warning(f"[docling-image] {rel} 다운로드 실패: {e}")
            continue
    return downloaded


def run_docling(
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
) -> list[tuple[int, str]]:
    """Docling 전처리 파이프라인 실행 -> [(page_num, markdown)] 반환.

    - Docling 서비스(b2)에서 마크다운/이미지/페이지수를 받는다.
    - use_refinement=True면 이미지를 포함해 LLM 후처리를 수행한다.
    - LLM 후처리 실패 시 원본 Docling 마크다운을 사용한다.
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    img_dir = work / "docling_images"

    try:
        result = docling_client.convert_file(file_path)
    except Exception as e:
        logger.exception(f"[docling] {file_path.name} 변환 실패: {e}")
        if on_error:
            on_error(1, str(e))
        return []

    markdown = result.get("markdown", "")
    page_count = result.get("page_count", 1) or 1
    images = result.get("images", [])

    if not use_refinement:
        return [(1, markdown)]

    max_images = max_images if max_images is not None else settings.docling_max_images_per_doc
    max_size = image_max_size if image_max_size is not None else settings.docling_image_max_size
    image_paths = _download_images(images, img_dir, max_images, max_size)

    prompt = build_docling_refinement_prompt(columns, markdown, extra_prompt)
    target_endpoint = media_endpoint or endpoint
    target_model = media_model or model
    target_api_key = media_api_key or api_key
    provider = _detect_provider(target_endpoint, target_model)

    try:
        content, _ = ocr_client.call_media(
            prompt,
            target_endpoint,
            target_model,
            target_api_key,
            image_paths=image_paths,
            max_tokens=max_tokens,
            provider=provider,
        )
        refined = ocr_client.extract_markdown_content(content)
        return [(1, refined)]
    except Exception as e:
        logger.warning(f"[docling-refinement] {file_path.name} LLM 후처리 실패, 원본 사용: {e}")
        if on_error:
            on_error(1, f"refinement failed: {e}")
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
) -> list[tuple[int, str]]:
    """HWP/HWPX 전처리 파이프라인 실행 -> [(page_num, markdown)] 반환.

    - pyhwp2md로 마크다운을 추출하고 pyhwp로 BinData 이미지를 추출한다.
    - use_refinement=True면 이미지를 포함해 LLM 후처리를 수행한다.
    - LLM 후처리 실패 시 원본 마크다운을 사용한다.
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    img_dir = work / "hwp_images"

    try:
        result = hwp_converter.convert_hwp(file_path, img_dir)
    except Exception as e:
        logger.exception(f"[hwp] {file_path.name} 변환 실패: {e}")
        if on_error:
            on_error(1, str(e))
        return []

    markdown = result.get("markdown", "")
    page_count = result.get("page_count", 1) or 1
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
            prompt,
            target_endpoint,
            target_model,
            target_api_key,
            image_paths=resized_images,
            max_tokens=max_tokens,
            provider=provider,
        )
        refined = ocr_client.extract_markdown_content(content)
        return [(1, refined)]
    except Exception as e:
        logger.warning(f"[hwp-refinement] {file_path.name} LLM 후처리 실패, 원본 사용: {e}")
        if on_error:
            on_error(1, f"refinement failed: {e}")
        return [(1, markdown)]
