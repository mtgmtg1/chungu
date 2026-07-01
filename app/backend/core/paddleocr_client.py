#!/usr/bin/env python3
# [Flow: Step 1 (파일 업로드) -> Step 2 (폴링) -> Step 3 (결과 수신) -> Step 4 (markdown + images 반환)]
# PaddleOCR 서비스 클라이언트 — paddleocr_service의 /api/convert 엔드포인트 호출
# docling_client.convert_file()과 동일한 시그니처로 기존 파이프라인 호환
import logging
import time
from pathlib import Path
from typing import Callable

import requests

from ..config import settings

logger = logging.getLogger(__name__)

UPLOAD_TIMEOUT = 300
POLL_INTERVAL = 5
POLL_TIMEOUT = 30
MAX_POLL_DURATION = 1800

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}


def _get_service_url() -> str:
    """PaddleOCR 서비스 URL을 반환한다."""
    return settings.paddleocr_service_url.rstrip("/")


def _is_enabled() -> bool:
    """PaddleOCR 폴백 기능이 활성화되어 있는지 확인한다."""
    return settings.paddleocr_fallback_enabled


def convert_file(
    path: Path,
    timeout: int = MAX_POLL_DURATION,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[str, list[Path]]:
    """이미지 파일을 PaddleOCR 서비스(AI Studio API)로 전송하여 markdown과 이미지 경로를 받는다.

    AI Studio API는 이미지만 지원하므로 PDF/오피스 문서는 거부한다.
    docling_client.convert_file()과 동일한 시그니처로 기존 파이프라인에 삽입 가능하다.
    비동기 폴링 방식:
    1. /api/convert로 이미지 업로드 → task_id 즉시 반환
    2. 5초 간격으로 /api/convert/status/{task_id} 폴링
    3. status == done → (markdown, image_paths) 반환, status == error → 예외 발생

    Args:
        path: 변환할 이미지 파일 경로 (png/jpg/bmp/tiff/webp)
        timeout: 최대 대기 시간 (초)
        on_progress: 진행률 콜백 (done, total) 형태

    Returns:
        (markdown_text, image_paths) 튜플
    """
    if not _is_enabled():
        raise RuntimeError("PaddleOCR 폴백 서비스가 비활성화되어 있습니다")

    ext = path.suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        raise ValueError(f"PaddleOCR 폴백은 이미지만 지원합니다 (png/jpg/bmp/tiff/webp): {path.name}")

    base_url = _get_service_url()
    logger.info(f"[paddleocr-client] {path.name} 변환 시작 (size={path.stat().st_size / 1024 / 1024:.1f}MB)")

    # Step 1: 비동기 변환 시작
    convert_url = f"{base_url}/api/convert"
    with open(path, "rb") as f:
        files = {"file": (path.name, f)}
        resp = requests.post(convert_url, files=files, timeout=UPLOAD_TIMEOUT)

    if resp.status_code >= 400:
        logger.error(f"[paddleocr-client] {path.name} 변환 시작 실패: {resp.status_code} {resp.text[:200]}")
        resp.raise_for_status()

    task_id = resp.json().get("task_id")
    if not task_id:
        raise RuntimeError(f"PaddleOCR 변환 시작 실패: task_id 없음 (resp={resp.text[:200]})")

    logger.info(f"[paddleocr-client] {path.name} task_id={task_id} 폴링 시작")

    # Step 2: 폴링 루프
    start_time = time.monotonic()
    status_url = f"{base_url}/api/convert/status/{task_id}"

    while True:
        elapsed = time.monotonic() - start_time

        if elapsed > timeout:
            raise TimeoutError(f"PaddleOCR 변환 타임아웃: {path.name} ({elapsed:.0f}s > {timeout}s)")

        try:
            status_resp = requests.get(status_url, timeout=POLL_TIMEOUT)
        except Exception as e:
            logger.warning(f"[paddleocr-client] {path.name} 폴링 실패, 재시도: {e}")
            time.sleep(POLL_INTERVAL)
            continue

        if status_resp.status_code == 404:
            raise RuntimeError(f"PaddleOCR task를 찾을 수 없음: {task_id}")

        if status_resp.status_code >= 400:
            logger.warning(f"[paddleocr-client] {path.name} 폴링 에러: {status_resp.status_code}")
            time.sleep(POLL_INTERVAL)
            continue

        data = status_resp.json()
        status = data.get("status", "")

        if status == "done":
            result = data.get("result")
            if result is None:
                raise RuntimeError(f"PaddleOCR 변환 완료지만 결과 없음: {path.name}")
            markdown = result.get("markdown", "")
            relative_images = result.get("images", [])
            image_paths = [Path(img) for img in relative_images]
            logger.info(f"[paddleocr-client] {path.name} 변환 완료 ({elapsed:.0f}s, images={len(image_paths)})")
            if on_progress:
                on_progress(100, 100)
            return markdown, image_paths

        if status == "error":
            error_msg = data.get("error", "알 수 없는 오류")
            raise RuntimeError(f"PaddleOCR 변환 실패: {path.name} - {error_msg}")

        # status == "processing": 경과 시간 기반 추정 진행률
        if status == "processing":
            if on_progress:
                est_pct = min(99, int(elapsed / timeout * 99))
                on_progress(est_pct, 100)

        time.sleep(POLL_INTERVAL)


def convert_image(image_path: Path, timeout: int = 600) -> str:
    """단일 이미지를 PaddleOCR 서비스로 전송하여 markdown 텍스트만 반환한다.

    pipeline_vision 및 pipeline_media의 이미지 폴백용 경량 함수.

    Args:
        image_path: 변환할 이미지 파일 경로
        timeout: 최대 대기 시간 (초)

    Returns:
        markdown 텍스트
    """
    markdown, _ = convert_file(image_path, timeout=timeout)
    return markdown
