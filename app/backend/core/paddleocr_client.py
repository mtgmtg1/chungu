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


def _convert_and_poll(
    path: Path,
    timeout: int,
    on_progress: Callable[[int, int], None] | None,
) -> dict:
    """이미지를 PaddleOCR 서비스(/api/convert)로 전송하고 완료될 때까지 폴링하여 결과 dict를 반환한다.

    반환 dict 키: markdown, images(상대경로 리스트), layout(페이지별 bbox 원본 리스트, 보통 1개).
    convert_file()/convert_image_with_layout() 등 공개 함수들이 이 내부 함수를 공유한다.
    """
    if not _is_enabled():
        raise RuntimeError("PaddleOCR fallback service is disabled")

    ext = path.suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        raise ValueError(f"PaddleOCR fallback supports images only (png/jpg/bmp/tiff/webp): {path.name}")

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
        raise RuntimeError(f"Failed to start PaddleOCR conversion: no task_id (resp={resp.text[:200]})")

    logger.info(f"[paddleocr-client] {path.name} task_id={task_id} 폴링 시작")

    # Step 2: 폴링 루프
    start_time = time.monotonic()
    status_url = f"{base_url}/api/convert/status/{task_id}"

    while True:
        elapsed = time.monotonic() - start_time

        if elapsed > timeout:
            raise TimeoutError(f"PaddleOCR conversion timeout: {path.name} ({elapsed:.0f}s > {timeout}s)")

        try:
            status_resp = requests.get(status_url, timeout=POLL_TIMEOUT)
        except Exception as e:
            logger.warning(f"[paddleocr-client] {path.name} 폴링 실패, 재시도: {e}")
            time.sleep(POLL_INTERVAL)
            continue

        if status_resp.status_code == 404:
            raise RuntimeError(f"PaddleOCR task not found: {task_id}")

        if status_resp.status_code >= 400:
            logger.warning(f"[paddleocr-client] {path.name} 폴링 에러: {status_resp.status_code}")
            time.sleep(POLL_INTERVAL)
            continue

        data = status_resp.json()
        status = data.get("status", "")

        if status == "done":
            result = data.get("result")
            if result is None:
                raise RuntimeError(f"PaddleOCR conversion completed but no result: {path.name}")
            logger.info(
                f"[paddleocr-client] {path.name} 변환 완료 "
                f"({elapsed:.0f}s, images={len(result.get('images', []))})"
            )
            if on_progress:
                on_progress(100, 100)
            return result

        if status == "error":
            error_msg = data.get("error", "Unknown error")
            raise RuntimeError(f"PaddleOCR conversion failed: {path.name} - {error_msg}")

        # status == "processing": 경과 시간 기반 추정 진행률
        if status == "processing":
            if on_progress:
                est_pct = min(99, int(elapsed / timeout * 99))
                on_progress(est_pct, 100)

        time.sleep(POLL_INTERVAL)


def convert_file(
    path: Path,
    timeout: int = MAX_POLL_DURATION,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[str, list[Path]]:
    """이미지 파일을 PaddleOCR 서비스(AI Studio API)로 전송하여 markdown과 이미지 경로를 받는다.

    AI Studio API는 이미지만 지원하므로 PDF/오피스 문서는 거부한다.
    docling_client.convert_file()과 동일한 시그니처로 기존 파이프라인에 삽입 가능하다.

    Returns:
        (markdown_text, image_paths) 튜플
    """
    result = _convert_and_poll(path, timeout, on_progress)
    markdown = result.get("markdown", "")
    image_paths = [Path(img) for img in result.get("images", [])]
    return markdown, image_paths


def convert_image_with_layout(
    image_path: Path,
    timeout: int = 600,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[str, dict]:
    """PDF 하이라이트/여백 주석 기능용: 이미지 한 장을 변환하고 bbox 원본(layout)까지 반환한다.

    PaddleOCR 서비스는 요청마다 useDocOrientationClassify/useDocUnwarping을 False로 고정 전송하므로
    (paddleocr_service/main.py `_aistudio_submit_job` 참고) 반환되는 bbox는 항상 원본 이미지 좌표 기준이다.

    로컬 PaddleOCR-VL 1.6 서버로 전환할 때는 이 함수 내부에서 호출하는 엔드포인트만
    (`base_url/api/convert` → `base_url/convert/layout` 등) 교체하면 되고, 반환 스키마는 동일하게 유지된다.

    Args:
        image_path: 변환할 페이지 이미지 경로 (렌더링 DPI를 호출자가 알고 있어야 좌표 역변환 가능)
        timeout: 최대 대기 시간 (초)
        on_progress: 진행률 콜백

    Returns:
        (markdown_text, layout_dict) — layout_dict는 res.json과 동일 스키마의 단일 페이지 원본 딕셔너리
        (layout_det_res/overall_ocr_res/table_res_list 등). 실패 시 빈 dict.
    """
    result = _convert_and_poll(image_path, timeout, on_progress)
    markdown = result.get("markdown", "")
    layout_pages = result.get("layout", [])
    layout = layout_pages[0] if layout_pages else {}
    return markdown, layout


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
