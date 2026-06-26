#!/usr/bin/env python3
# [Flow: Step 1 (파일별 유형 감지) -> Step 2 (비디오 프레임/오디오 준비) -> Step 3 (LLM 멀티모달 호출) -> Step 4 (통일된 마크다운 표 수집) -> Step 5 (진행률 콜백)]
from pathlib import Path
from typing import Callable

from . import media_loader, ocr_client
from .prompts import build_media_prompt


def _format_time(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _process_file(
    file_path: Path,
    file_type: str,
    prompt: str,
    endpoint: str,
    model: str,
    api_key: str,
    work_dir: Path,
    max_tokens: int = 10000,
) -> tuple[str, str]:
    """단일 미디어/이미지 파일을 처리해 통일된 마크다운 표 문자열을 반환한다."""
    if file_type == "image":
        content, _ = ocr_client.call_media(
            prompt,
            endpoint,
            model,
            api_key,
            image_paths=[file_path],
            max_tokens=max_tokens,
        )
        return content, ""

    if file_type == "audio":
        duration = media_loader.get_media_duration_seconds(file_path)
        content, _ = ocr_client.call_media(
            prompt,
            endpoint,
            model,
            api_key,
            audio_path=file_path,
            max_tokens=max_tokens,
        )
        return content, _format_time(duration)

    if file_type == "video":
        duration = media_loader.get_media_duration_seconds(file_path)
        frames = media_loader.extract_video_frames(file_path, max_frames=4, work_dir=work_dir)
        content, _ = ocr_client.call_media(
            prompt,
            endpoint,
            model,
            api_key,
            image_paths=frames,
            max_tokens=max_tokens,
        )
        return content, _format_time(duration)

    return "", ""


def run_media(
    files: list[tuple[str, Path]],
    work_dir: str,
    columns: list[str],
    endpoint: str,
    model: str,
    api_key: str = "",
    extra_prompt: str = "",
    max_tokens: int = 10000,
    on_progress: Callable[[int, int], None] | None = None,
    on_error: Callable[[str, str], None] | None = None,
) -> list[tuple[str, str, str]]:
    """미디어/이미지 파일 목록을 처리해 [(filename, position, markdown_table)] 반환.

    files: [(file_type, file_path)]
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    prompt = build_media_prompt(columns, extra_prompt)
    total = len(files)
    results: list[tuple[str, str, str]] = []
    done = 0

    for file_type, file_path in files:
        filename = file_path.name
        try:
            content, position = _process_file(
                file_path, file_type, prompt, endpoint, model, api_key, work, max_tokens
            )
            table = ocr_client.extract_markdown_table(content)
            results.append((filename, position, table))
        except Exception as e:
            if on_error:
                on_error(filename, str(e))
            results.append((filename, "", ""))
        finally:
            done += 1
            if on_progress:
                on_progress(done, total)

    return results
