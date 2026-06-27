#!/usr/bin/env python3
# [Flow: Step 1 (파일별 유형 감지) -> Step 2 (오디오/비디오는 30초 세그먼트 분할) -> Step 3 (프레임+오디오 추출) -> Step 4 (세그먼트별 LLM 멀티모달 호출) -> Step 5 (표 병합) -> Step 6 (진행률 콜백)]
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from . import media_loader, ocr_client
from .prompts import build_audio_prompt, build_media_prompt, build_video_prompt
from ..config import settings

logger = logging.getLogger(__name__)


def _format_time(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


SEGMENT_SECONDS = 30
VIDEO_FPS = 1
MAX_FRAMES_PER_SEGMENT = 30


def _merge_tables(tables: list[str]) -> str:
    """여러 마크다운 표의 데이터 행을 하나의 표로 병합한다."""
    if not tables:
        return ""
    tables = [t.strip() for t in tables if t.strip()]
    if len(tables) <= 1:
        return tables[0] if tables else ""

    header = ""
    separator = ""
    for line in tables[0].splitlines():
        if line.startswith("|"):
            if not header:
                header = line
            elif not separator:
                separator = line
            else:
                break

    rows = []
    for table in tables:
        for line in table.splitlines():
            if not line.startswith("|"):
                continue
            if line == header or line == separator:
                continue
            if all("-" in c or c.strip() == "" for c in line.split("|")[1:-1]):
                continue
            rows.append(line)

    if not header or not rows:
        return tables[0]
    return "\n".join([header, separator] + rows)


def _process_file(
    file_path: Path,
    file_type: str,
    prompt: str,
    endpoint: str,
    model: str,
    api_key: str,
    work_dir: Path,
    max_tokens: int = 10000,
    provider: str = "openai",
) -> tuple[str, str]:
    """단일 미디어/이미지 파일을 처리해 통일된 마크다운 표 문자열을 반환한다.

    - 이미지: prompt를 그대로 사용
    - 오디오/비디오: prompt를 extra_prompt로 사용해 30초 세그먼트별로 요청 후 병합
    """
    if file_type == "image":
        content, _ = ocr_client.call_media(
            prompt,
            endpoint,
            model,
            api_key,
            image_paths=[file_path],
            max_tokens=max_tokens,
            provider=provider,
        )
        return content, ""

    if file_type == "audio":
        duration = media_loader.get_media_duration_seconds(file_path)
        if duration <= 0:
            return "", ""

        audio_tables: list[str] = []
        for seg_start in range(0, duration, SEGMENT_SECONDS):
            seg_end = min(seg_start + SEGMENT_SECONDS, duration)
            if seg_end <= seg_start:
                break
            seg_audio = media_loader.extract_audio_segment(file_path, start=seg_start, end=seg_end, work_dir=work_dir)
            if not seg_audio:
                logger.warning(f"[audio-segment] {file_path.name} [{seg_start}-{seg_end}] 오디오 추출 실패")
                continue
            seg_prompt = build_audio_prompt(prompt, segment_start=seg_start, segment_end=seg_end)
            try:
                content, _ = ocr_client.call_media(
                    seg_prompt,
                    endpoint,
                    model,
                    api_key,
                    audio_path=seg_audio,
                    max_tokens=max_tokens,
                    provider=provider,
                )
            except Exception as e:
                logger.exception(f"[audio-segment] {file_path.name} [{seg_start}-{seg_end}] 처리 실패: {e}")
                continue
            table = ocr_client.extract_markdown_table(content)
            audio_tables.append(table)

        merged = _merge_tables(audio_tables)
        return merged, _format_time(duration)

    if file_type == "video":
        duration = media_loader.get_media_duration_seconds(file_path)
        if duration <= 0:
            return "", ""

        video_tables: list[str] = []
        for seg_start in range(0, duration, SEGMENT_SECONDS):
            seg_end = min(seg_start + SEGMENT_SECONDS, duration)
            if seg_end <= seg_start:
                break

            frames = media_loader.extract_video_frames(
                file_path,
                max_frames=MAX_FRAMES_PER_SEGMENT,
                work_dir=work_dir,
                start=seg_start,
                end=seg_end,
                fps=VIDEO_FPS,
            )
            seg_audio = media_loader.extract_video_audio(file_path, start=seg_start, end=seg_end, work_dir=work_dir)
            frame_timestamps = [ts for ts, _ in frames]
            frame_paths = [fp for _, fp in frames]
            seg_prompt = build_video_prompt(
                prompt,
                frame_timestamps=frame_timestamps,
                segment_start=seg_start,
                segment_end=seg_end,
                has_audio=seg_audio is not None,
            )

            try:
                content, _ = ocr_client.call_media(
                    seg_prompt,
                    endpoint,
                    model,
                    api_key,
                    image_paths=frame_paths,
                    audio_path=seg_audio,
                    max_tokens=max_tokens,
                    provider=provider,
                )
            except Exception as e:
                logger.warning(f"[video-segment] {file_path.name} [{seg_start}-{seg_end}] audio+frames 실패, frames-only fallback: {e}")
                try:
                    content, _ = ocr_client.call_media(
                        seg_prompt,
                        endpoint,
                        model,
                        api_key,
                        image_paths=frame_paths,
                        max_tokens=max_tokens,
                        provider=provider,
                    )
                except Exception as e2:
                    logger.exception(f"[video-segment] {file_path.name} [{seg_start}-{seg_end}] frames-only fallback도 실패: {e2}")
                    continue

            table = ocr_client.extract_markdown_table(content)
            video_tables.append(table)

        merged = _merge_tables(video_tables)
        return merged, _format_time(duration)

    return "", ""


def _detect_provider(endpoint: str, model: str = "") -> str:
    """엔드포인트 주소/모델명으로 API 제공자를 추정한다."""
    ep = (endpoint or "").lower()
    md = (model or "").lower()
    if "llama" in ep or "gguf" in md or "gguf" in ep:
        return "llama.cpp"
    return "openai"


def run_media(
    files: list[tuple[str, Path]],
    work_dir: str,
    columns: list[str],
    endpoint: str,
    model: str,
    api_key: str = "",
    extra_prompt: str = "",
    max_tokens: int = 10000,
    media_endpoint: str | None = None,
    media_model: str | None = None,
    media_api_key: str = "",
    workers: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    on_error: Callable[[str, str], None] | None = None,
) -> list[tuple[str, str, str]]:
    """미디어/이미지 파일 목록을 처리해 [(filename, position, markdown_table)] 반환.

    files: [(file_type, file_path)]
    오디오/비디오는 media_endpoint로 전송한다.
    이미지는 endpoint와 media_endpoint에 처리량에 따라 동적 분배한다.
    - ≤20: 1:4 (vLLM:E4B), 소량은 E4B가 4배 빠름
    - 21~200: 1:1, 균형
    - >200: 4:1, vLLM 고배치가 압도적
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    image_prompt = build_media_prompt(columns, extra_prompt)
    total = len(files)
    results: list[tuple[str, str, str]] = []
    done = 0
    image_counter = 0

    def _resolve(file_type: str, file_path: Path) -> tuple[str, Path, str, str, str, str, str]:
        nonlocal image_counter
        filename = file_path.name
        if file_type in ("audio", "video") and media_endpoint and media_model:
            target_endpoint = media_endpoint
            target_model = media_model
            target_api_key = media_api_key
            target_provider = _detect_provider(media_endpoint, media_model)
            target_prompt = extra_prompt
            logger.info(f"[media-routing] {filename} ({file_type}) -> E4B media LLM: {target_endpoint} / {target_model} / provider={target_provider}")
        elif file_type == "image" and media_endpoint and media_model:
            image_counter += 1
            if total <= 20:
                use_media = (image_counter % 5 != 0)       # 1:4 (E4B 80%)
            elif total <= 200:
                use_media = (image_counter % 2 != 0)       # 1:1 (50/50)
            else:
                use_media = (image_counter % 5 == 0)       # 4:1 (vLLM 80%)
            if use_media:
                target_endpoint = media_endpoint
                target_model = media_model
                target_api_key = media_api_key
                target_provider = _detect_provider(media_endpoint, media_model)
                target_prompt = image_prompt
                logger.info(f"[media-routing] {filename} ({file_type}) -> E4B media LLM (image share): {target_endpoint} / {target_model} / provider={target_provider}")
            else:
                target_endpoint = endpoint
                target_model = model
                target_api_key = api_key
                target_provider = _detect_provider(endpoint, model)
                target_prompt = image_prompt
                logger.info(f"[media-routing] {filename} ({file_type}) -> default LLM: {target_endpoint} / {target_model} / provider={target_provider}")
        else:
            target_endpoint = endpoint
            target_model = model
            target_api_key = api_key
            target_provider = _detect_provider(endpoint, model)
            target_prompt = image_prompt
            logger.info(f"[media-routing] {filename} ({file_type}) -> default LLM: {target_endpoint} / {target_model} / provider={target_provider}")
        return (file_type, file_path, target_prompt, target_endpoint, target_model, target_api_key, target_provider)

    def _process(item: tuple[str, Path, str, str, str, str, str]) -> tuple[str, str, str]:
        file_type, file_path, target_prompt, target_endpoint, target_model, target_api_key, target_provider = item
        filename = file_path.name
        try:
            content, position = _process_file(
                file_path, file_type, target_prompt, target_endpoint, target_model, target_api_key, work, max_tokens, target_provider
            )
            table = ocr_client.extract_markdown_table(content)
            logger.info(f"[media-result] {filename} ({file_type}) -> position={position}, table_length={len(table)}")
            return (filename, position, table)
        except Exception as e:
            logger.exception(f"[media-error] {filename} ({file_type}) failed at {target_endpoint}: {e}")
            if on_error:
                on_error(filename, str(e))
            return (filename, "", "")

    items = [_resolve(file_type, file_path) for file_type, file_path in files]
    max_w = workers if workers is not None else min(total, settings.llm_max_workers + settings.media_max_workers)
    with ThreadPoolExecutor(max_workers=max_w) as executor:
        futures = {executor.submit(_process, item): item[1].name for item in items}
        for future in as_completed(futures):
            filename = futures[future]
            try:
                results.append(future.result())
            except Exception as e:
                if on_error:
                    on_error(filename, str(e))
                results.append((filename, "", ""))
            finally:
                done += 1
                if on_progress:
                    on_progress(done, total)

    return results
