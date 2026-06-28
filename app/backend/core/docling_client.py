#!/usr/bin/env python3
# [Flow: Step 1 (파일 크기로 동적 타임아웃 계산) -> Step 2 (/convert/async로 변환 시작) -> Step 3 (30s 간격 폴링) -> Step 4 (processing + health OK -> 타임아웃 연장) -> Step 5 (done/error 시 결과 반환)]
import logging
import time
from pathlib import Path
from typing import Any

import requests

from ..config import settings


logger = logging.getLogger(__name__)

POLL_INTERVAL = 30  # 폴링 주기 (초)
MIN_TIMEOUT = 3600  # 최소 타임아웃 60분
UPLOAD_TIMEOUT = 300  # 파일 업로드 타임아웃 5분


def is_enabled() -> bool:
    """Docling 전처리 서비스 사용 가능 여부."""
    return settings.docling_enabled and bool(settings.docling_service_url)


def get_service_url() -> str:
    """Docling 서비스 기본 URL."""
    return (settings.docling_service_url or "").rstrip("/")


def _compute_max_timeout(path: Path) -> float:
    """파일 크기(MB) 기반 동적 최대 타임아웃 계산: max(3600, file_size_mb * 60)."""
    try:
        size_mb = path.stat().st_size / (1024 * 1024)
    except OSError:
        size_mb = 1.0
    return max(MIN_TIMEOUT, size_mb * 60)


def _check_health() -> bool:
    """Docling 서비스 /health 확인 — 정상 응답 시 True."""
    try:
        url = f"{get_service_url()}/health"
        resp = requests.get(url, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def convert_file(path: Path, timeout: int = 1200) -> dict[str, Any]:
    """로컬 파일을 Docling 서비스로 보내 마크다운/이미지/페이지수를 받는다.

    비동기 폴링 방식:
    1. /convert/async로 파일 업로드 → task_id 즉시 반환
    2. 30초 간격으로 /convert/status/{task_id} 폴링
    3. status == processing + /health OK → 계속 대기 (동적 타임아웃까지)
    4. status == done → 결과 반환, status == error → 예외 발생
    """
    if not is_enabled():
        raise RuntimeError("Docling 전처리 서비스가 설정되지 않았습니다")

    base_url = get_service_url()
    max_wait = _compute_max_timeout(path)
    logger.info(f"[docling-client] {path.name} 변환 시작 (max_wait={max_wait:.0f}s, size={path.stat().st_size / 1024 / 1024:.1f}MB)")

    # Step 1: 비동기 변환 시작
    async_url = f"{base_url}/convert/async"
    with open(path, "rb") as f:
        files = {"file": (path.name, f, "application/octet-stream")}
        resp = requests.post(async_url, files=files, timeout=UPLOAD_TIMEOUT)

    if resp.status_code >= 400:
        logger.error(f"[docling-client] {path.name} async 시작 실패: {resp.status_code} {resp.text[:200]}")
        resp.raise_for_status()

    task_id = resp.json().get("task_id")
    if not task_id:
        raise RuntimeError(f"Docling async 변환 시작 실패: task_id 없음 (resp={resp.text[:200]})")

    logger.info(f"[docling-client] {path.name} task_id={task_id} 폴링 시작")

    # Step 2: 폴링 루프
    start_time = time.monotonic()
    status_url = f"{base_url}/convert/status/{task_id}"

    while True:
        elapsed = time.monotonic() - start_time

        # 동적 타임아웃 초과
        if elapsed > max_wait:
            raise TimeoutError(
                f"Docling 변환 타임아웃: {path.name} ({elapsed:.0f}s > {max_wait:.0f}s)"
            )

        # 상태 폴링
        try:
            status_resp = requests.get(status_url, timeout=30)
        except Exception as e:
            logger.warning(f"[docling-client] {path.name} 폴링 실패, 재시도: {e}")
            time.sleep(POLL_INTERVAL)
            continue

        if status_resp.status_code == 404:
            raise RuntimeError(f"Docling task를 찾을 수 없음: {task_id}")

        if status_resp.status_code >= 400:
            logger.warning(f"[docling-client] {path.name} 폴링 에러: {status_resp.status_code}")
            time.sleep(POLL_INTERVAL)
            continue

        data = status_resp.json()
        status = data.get("status", "")

        if status == "done":
            result = data.get("result")
            if result is None:
                raise RuntimeError(f"Docling 변환 완료지만 결과 없음: {path.name}")
            logger.info(f"[docling-client] {path.name} 변환 완료 ({elapsed:.0f}s)")
            return result

        if status == "error":
            error_msg = data.get("error", "알 수 없는 오류")
            raise RuntimeError(f"Docling 변환 실패: {path.name} - {error_msg}")

        # status == "processing": health 체크 후 계속 대기
        if status == "processing":
            if not _check_health():
                logger.warning(f"[docling-client] {path.name} Docling 서비스 health 체크 실패, 재시도")
            else:
                logger.debug(f"[docling-client] {path.name} 처리 중... ({elapsed:.0f}s)")

        time.sleep(POLL_INTERVAL)


def download_image(relative_path: str, timeout: int = 60) -> bytes:
    """b2 Docling 서비스에서 추출된 이미지 데이터를 다운로드한다."""
    if not is_enabled():
        raise RuntimeError("Docling 전처리 서비스가 설정되지 않았습니다")
    url = f"{get_service_url()}/images/{relative_path.lstrip('/')}"
    resp = requests.get(url, timeout=timeout)
    if resp.status_code >= 400:
        logger.error(f"[docling-client] 이미지 다운로드 실패: {url} -> {resp.status_code}")
        resp.raise_for_status()
    return resp.content


def health_check(timeout: int = 10) -> dict[str, str]:
    """Docling 서비스 헬스체크."""
    if not is_enabled():
        return {"status": "disabled"}
    url = f"{get_service_url()}/health"
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()
