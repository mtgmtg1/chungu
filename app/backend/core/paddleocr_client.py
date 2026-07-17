#!/usr/bin/env python3
# [Flow: Step 1 (파일 업로드) -> Step 2 (폴링) -> Step 3 (결과 수신) -> Step 4 (markdown + images 반환)]
# PaddleOCR 서비스 클라이언트 — paddleocr_service의 /api/convert 엔드포인트 호출
# docling_client.convert_file()과 동일한 시그니처로 기존 파이프라인 호환
import logging
import time
from pathlib import Path
from typing import Any, Callable

import requests

from ..config import settings
from .image_deskew import deskew_image
from .pdf_optimizer import optimize_pdf

logger = logging.getLogger(__name__)

UPLOAD_TIMEOUT = 300
POLL_INTERVAL = 1
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
    extra_data: dict[str, Any] | None = None,
) -> dict:
    """이미지를 PaddleOCR 서비스(/api/convert)로 전송하고 완료될 때까지 폴링하여 결과 dict를 반환한다.

    반환 dict 키: markdown, images(상대경로 리스트), layout(페이지별 bbox 원본 리스트, capture_layout=true 시),
    page_angles(90° 회전 각도 코드 리스트).
    convert_file()/convert_image_with_layout()/convert_pdf_with_layout() 등 공개 함수들이 이 내부 함수를 공유한다.
    """
    if not _is_enabled():
        raise RuntimeError("PaddleOCR fallback service is disabled")

    ext = path.suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        raise ValueError(f"PaddleOCR fallback supports images only (png/jpg/bmp/tiff/webp): {path.name}")

    base_url = _get_service_url()
    logger.info(f"[paddleocr-client] {path.name} 변환 시작 (size={path.stat().st_size / 1024 / 1024:.1f}MB)")

    # [Flow: Step 0 (미세 회전 보정) — deskew 전처리 후 보정된 이미지를 AI Studio로 전송]
    # 90° 단위 대회전은 AI Studio API의 useDocOrientationClassify=True가 담당하고,
    # 수평에서 몇 도 기울어진 미세 회전은 deskew 라이브러리로 보정한다.
    # 보정된 이미지 기준으로 bbox가 반환되므로 주석 하이라이트가 텍스트와 정렬된다.
    send_path, applied_angle = deskew_image(path)
    if applied_angle != 0.0:
        logger.info(f"[paddleocr-client] {path.name} deskew 보정 적용 ({applied_angle:.3f}°) → {send_path.name}")

    # Step 1: 비동기 변환 시작
    convert_url = f"{base_url}/api/convert"
    with open(send_path, "rb") as f:
        files = {"file": (path.name, f)}
        data = dict(extra_data or {})
        resp = requests.post(convert_url, files=files, data=data, timeout=UPLOAD_TIMEOUT)

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
                f"({elapsed:.0f}s, images={len(result.get('images', []))}, "
                f"layout_pages={len(result.get('layout', []))})"
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
) -> tuple[str, dict, int]:
    """PDF 하이라이트/여백 주석 기능용: 이미지 한 장을 변환하고 bbox 원본(layout)과 90° 회전 각도를 반환한다.

    AI Studio API의 useDocOrientationClassify=True가 보정한 90° 단위 회전 각도(0/1/2/3)를 함께 반환한다.
    클라이언트는 이 각도로 원본 이미지를 회전시켜 AI Studio 보정 결과를 재현한 후 주석 PDF를 생성한다.
    미세 회전은 _convert_and_poll 내부에서 deskew 전처리로 이미 보정되어 전송된다.

    Args:
        image_path: 변환할 페이지 이미지 경로 (렌더링 DPI를 호출자가 알고 있어야 좌표 역변환 가능)
        timeout: 최대 대기 시간 (초)
        on_progress: 진행률 콜백

    Returns:
        (markdown_text, layout_dict, angle_code) —
        layout_dict는 res.json과 동일 스키마의 단일 페이지 원본 딕셔너리. 실패 시 빈 dict.
        angle_code는 0/1/2/3(0°/90°/180°/270°) 또는 -1(미적용).
    """
    result = _convert_and_poll(
        image_path,
        timeout,
        on_progress,
        extra_data={"capture_layout": "true"},
    )
    markdown = result.get("markdown", "")
    layout_pages = result.get("layout", [])
    page_angles = result.get("page_angles", [])
    layout = layout_pages[0] if layout_pages else {}
    angle_code = page_angles[0] if page_angles else -1
    return markdown, layout, angle_code


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


def convert_images_batch_with_layout(
    image_paths: list[Path],
    timeout: int = 1800,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[tuple[str, dict, int]]:
    """여러 페이지 이미지를 하나의 AI Studio job로 배치 변환하고 per-page 결과를 반환한다.

    [Flow: Step 1 (이미지들을 /api/convert/batch에 업로드) -> Step 2 (task_id 폴링) -> Step 3 (per-page 결과 리스트 반환)]

    AI Studio 기본 제한(10페이지)을 초과하지 않도록 호출자가 분할하여 호출해야 한다.
    반환 리스트 순서는 image_paths 순서와 동일하다.

    Args:
        image_paths: 변환할 페이지 이미지 경로 리스트 (최대 10장)
        timeout: 최대 대기 시간 (초)
        on_progress: 진행률 콜백

    Returns:
        [(markdown, layout, angle_code), ...] — image_paths 순서대로 per-page 결과
    """
    if not _is_enabled():
        raise RuntimeError("PaddleOCR fallback service is disabled")

    if not image_paths:
        return []

    base_url = _get_service_url()
    batch_url = f"{base_url}/api/convert/batch"
    logger.info(f"[paddleocr-batch] {len(image_paths)}장 배치 변환 시작")

    # Step 1: 다중 이미지 업로드
    files_payload = []
    opened_files = []
    for img_path in image_paths:
        f = open(img_path, "rb")
        opened_files.append(f)
        files_payload.append(("files", (img_path.name, f)))

    try:
        resp = requests.post(batch_url, files=files_payload, timeout=UPLOAD_TIMEOUT)
    finally:
        for f in opened_files:
            f.close()

    if resp.status_code >= 400:
        logger.error(f"[paddleocr-batch] 배치 시작 실패: {resp.status_code} {resp.text[:200]}")
        resp.raise_for_status()

    task_id = resp.json().get("task_id")
    if not task_id:
        raise RuntimeError(f"Failed to start batch conversion: no task_id (resp={resp.text[:200]})")

    logger.info(f"[paddleocr-batch] task_id={task_id} 폴링 시작")

    # Step 2: 폴링 루프
    start_time = time.monotonic()
    status_url = f"{base_url}/api/convert/batch/status/{task_id}"

    while True:
        elapsed = time.monotonic() - start_time

        if elapsed > timeout:
            raise TimeoutError(f"PaddleOCR batch timeout: {elapsed:.0f}s > {timeout}s")

        try:
            status_resp = requests.get(status_url, timeout=POLL_TIMEOUT)
        except Exception as e:
            logger.warning(f"[paddleocr-batch] 폴링 실패, 재시도: {e}")
            time.sleep(POLL_INTERVAL)
            continue

        if status_resp.status_code == 404:
            raise RuntimeError(f"PaddleOCR batch task not found: {task_id}")

        if status_resp.status_code >= 400:
            logger.warning(f"[paddleocr-batch] 폴링 에러: {status_resp.status_code}")
            time.sleep(POLL_INTERVAL)
            continue

        data = status_resp.json()
        status = data.get("status", "")

        if status == "done":
            result = data.get("result")
            if result is None:
                raise RuntimeError("PaddleOCR batch completed but no result")
            pages = result.get("pages", [])
            logger.info(f"[paddleocr-batch] 배치 변환 완료 ({elapsed:.0f}s, {len(pages)}페이지)")
            if on_progress:
                on_progress(100, 100)
            return [
                (page.get("markdown", ""), page.get("layout", {}), page.get("page_angle", -1))
                for page in pages
            ]

        if status == "error":
            error_msg = data.get("error", "Unknown error")
            raise RuntimeError(f"PaddleOCR batch failed: {error_msg}")

        # status == "processing": 추정 진행률
        if status == "processing" and on_progress:
            est_pct = min(99, int(elapsed / timeout * 99))
            on_progress(est_pct, 100)

        time.sleep(POLL_INTERVAL)


def convert_pdf_with_layout(
    pdf_path: Path,
    timeout: int = 1800,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[tuple[str, dict, int]]:
    """원본 PDF를 렌더링 없이 AI Studio에 직접 제출하여 per-page 결과를 반환한다.

    [Flow: Step 1 (PDF를 /api/convert/pdf에 업로드) -> Step 2 (task_id 폴링) -> Step 3 (per-page 결과 리스트 반환)]

    원본 PDF가 10페이지 이하인 경우, 이미지 렌더링/deskew/PDF 재병합을 생략하고
    원본 PDF를 AI Studio에 직접 제출하여 불필요한 왕복을 제거한다.
    AI Studio 기본 제한(10페이지)을 초과하면 서비스가 400 에러를 반환한다.

    Args:
        pdf_path: 변환할 PDF 파일 경로 (최대 10페이지)
        timeout: 최대 대기 시간 (초)
        on_progress: 진행률 콜백

    Returns:
        [(markdown, layout, angle_code), ...] — 페이지 순서대로 per-page 결과
    """
    if not _is_enabled():
        raise RuntimeError("PaddleOCR fallback service is disabled")

    base_url = _get_service_url()
    pdf_url = f"{base_url}/api/convert/pdf"

    # PDF 무손실 압축 (업로드 크기 감소)
    pdf_path = optimize_pdf(pdf_path)
    pdf_size = pdf_path.stat().st_size / 1024 / 1024
    logger.info(f"[paddleocr-pdf] {pdf_path.name} 직접 변환 시작 ({pdf_size:.1f}MB)")

    # Step 1: PDF 업로드
    with open(pdf_path, "rb") as f:
        files = {"file": (pdf_path.name, f)}
        resp = requests.post(pdf_url, files=files, timeout=UPLOAD_TIMEOUT)

    if resp.status_code >= 400:
        logger.error(f"[paddleocr-pdf] 직접 변환 시작 실패: {resp.status_code} {resp.text[:200]}")
        resp.raise_for_status()

    task_id = resp.json().get("task_id")
    if not task_id:
        raise RuntimeError(f"Failed to start PDF conversion: no task_id (resp={resp.text[:200]})")

    logger.info(f"[paddleocr-pdf] task_id={task_id} 폴링 시작")

    # Step 2: 폴링 루프
    start_time = time.monotonic()
    status_url = f"{base_url}/api/convert/pdf/status/{task_id}"

    while True:
        elapsed = time.monotonic() - start_time

        if elapsed > timeout:
            raise TimeoutError(f"PaddleOCR PDF timeout: {elapsed:.0f}s > {timeout}s")

        try:
            status_resp = requests.get(status_url, timeout=POLL_TIMEOUT)
        except Exception as e:
            logger.warning(f"[paddleocr-pdf] 폴링 실패, 재시도: {e}")
            time.sleep(POLL_INTERVAL)
            continue

        if status_resp.status_code == 404:
            raise RuntimeError(f"PaddleOCR PDF task not found: {task_id}")

        if status_resp.status_code >= 400:
            logger.warning(f"[paddleocr-pdf] 폴링 에러: {status_resp.status_code}")
            time.sleep(POLL_INTERVAL)
            continue

        data = status_resp.json()
        status = data.get("status", "")

        if status == "done":
            result = data.get("result")
            if result is None:
                raise RuntimeError("PaddleOCR PDF completed but no result")
            pages = result.get("pages", [])
            logger.info(f"[paddleocr-pdf] 직접 변환 완료 ({elapsed:.0f}s, {len(pages)}페이지)")
            if on_progress:
                on_progress(100, 100)
            return [
                (page.get("markdown", ""), page.get("layout", {}), page.get("page_angle", -1))
                for page in pages
            ]

        if status == "error":
            error_msg = data.get("error", "Unknown error")
            raise RuntimeError(f"PaddleOCR PDF failed: {error_msg}")

        if status == "processing" and on_progress:
            est_pct = min(99, int(elapsed / timeout * 99))
            on_progress(est_pct, 100)

        time.sleep(POLL_INTERVAL)
