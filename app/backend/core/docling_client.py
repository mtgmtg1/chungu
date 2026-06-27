#!/usr/bin/env python3
# [Flow: Step 1 (설정에서 Docling 서비스 URL 확인) -> Step 2 (파일을 b2 서비스로 전송) -> Step 3 (마크다운/이미지/페이지수 반환)]
import logging
from pathlib import Path
from typing import Any

import requests

from ..config import settings


logger = logging.getLogger(__name__)


def is_enabled() -> bool:
    """Docling 전처리 서비스 사용 가능 여부."""
    return settings.docling_enabled and bool(settings.docling_service_url)


def get_service_url() -> str:
    """Docling 서비스 기본 URL."""
    return (settings.docling_service_url or "").rstrip("/")


def convert_file(path: Path, timeout: int = 1200) -> dict[str, Any]:
    """로컬 파일을 b2 Docling 서비스로 보내 마크다운/이미지/페이지수를 받는다."""
    if not is_enabled():
        raise RuntimeError("Docling 전처리 서비스가 설정되지 않았습니다")

    url = f"{get_service_url()}/convert/file"
    logger.info(f"[docling-client] {path.name} -> {url}")

    with open(path, "rb") as f:
        files = {"file": (path.name, f, "application/octet-stream")}
        resp = requests.post(url, files=files, timeout=timeout)

    if resp.status_code >= 400:
        logger.error(f"[docling-client] {path.name} 실패: {resp.status_code} {resp.text[:200]}")
        resp.raise_for_status()

    return resp.json()


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
