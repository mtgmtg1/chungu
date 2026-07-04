#!/usr/bin/env python3
# [Flow: Step 1 (원본/미리보기 PDF storage_path 확인) -> Step 2 (PDF 바이트 다운로드) -> Step 3 (페이지 범위의 썸네일 생성/캐싱) -> Step 4 (서명된 URL 목록 반환)]
import hashlib
import logging
import tempfile
from pathlib import Path
from typing import BinaryIO

import fitz

from . import pdf_preview_converter, supabase_client

logger = logging.getLogger(__name__)

_BUCKET = "pdfs"
_THUMBNAIL_PREFIX = "pdf-thumbnails"
_THUMBNAIL_WIDTH = 150
_THUMBNAIL_DPR = 2
_MAX_THUMBNAILS_PER_REQUEST = 100
_UPLOAD_OPTS = {"content-type": "image/png", "upsert": "true"}


def _cache_key(pdf_bytes: bytes) -> str:
    """PDF 내용의 md5 해시 앞 12자리를 썸네일 캐시 키로 사용한다.

    동일한 storage_path라도 내용이 변경되면 썸네일을 새로 생성하도록 하기 위해
    파일 내용 기반 해시를 사용한다.
    """
    return hashlib.md5(pdf_bytes).hexdigest()[:12]


def _thumbnail_path(cache_key: str, page: int) -> str:
    """썸네일 Storage 경로를 생성한다."""
    return f"{_THUMBNAIL_PREFIX}/{cache_key}/{page}.png"


def _download_pdf(storage_path: str, bucket: str = _BUCKET) -> bytes:
    """Supabase Storage에서 PDF 바이트를 다운로드한다."""
    client = supabase_client.get_service_client()
    return client.storage.from_(bucket).download(storage_path)


def _list_existing_thumbnail_names(cache_key: str) -> set[str]:
    """이미 생성되어 있는 썸네일 파일명 집합을 반환한다."""
    client = supabase_client.get_service_client()
    try:
        items = client.storage.from_(_BUCKET).list(f"{_THUMBNAIL_PREFIX}/{cache_key}")
        return {item["name"] for item in (items or []) if isinstance(item, dict)}
    except Exception as e:
        logger.debug(f"[pdf-thumbnail] 썸네일 목록 조회 실패: {e}")
        return set()


def _resolve_pdf_storage_path(source_storage_path: str, source_type: str) -> str | None:
    """원본 파일 유형에 따라 썸네일을 생성할 PDF storage_path를 반환한다.

    PDF 원본이면 원본 경로를 그대로 사용하고, DOCX/HWP는 LibreOffice 변환된
    미리보기 PDF 경로를 사용한다. 미리보기 PDF가 아직 없으면 None을 반환한다.
    """
    if source_type == "pdf":
        return source_storage_path

    if source_type in ("docx", "hwp"):
        preview_path = pdf_preview_converter._preview_pdf_path(source_storage_path)
        client = supabase_client.get_service_client()
        try:
            prefix = pdf_preview_converter._PREVIEW_PDF_PREFIX
            existing = client.storage.from_(_BUCKET).list(prefix)
            names = {item["name"] for item in (existing or []) if isinstance(item, dict)}
            if Path(preview_path).name in names:
                return preview_path
        except Exception as e:
            logger.debug(f"[pdf-thumbnail] 미리보기 PDF 확인 실패: {e}")
        return None

    return None


def _get_page_count(pdf_bytes: bytes) -> int:
    """PyMuPDF로 PDF의 총 페이지 수를 반환한다."""
    doc = fitz.open(stream=pdf_bytes)
    count = doc.page_count
    doc.close()
    return count


def _render_page(pdf_doc: fitz.Document, page_num: int, width: int = _THUMBNAIL_WIDTH) -> bytes:
    """PyMuPDF로 단일 페이지를 지정 너비의 PNG 썸네일로 렌더링한다.

    매개변수:
        pdf_doc: 열린 PyMuPDF 문서
        page_num: 1-based 페이지 번호
        width: 썸네일 표시 너비(px). DPR을 곱한 해상도로 렌더링한다.

    반환값:
        PNG 이미지 바이트
    """
    page = pdf_doc.load_page(page_num - 1)
    rect = page.rect
    scale = (width * _THUMBNAIL_DPR) / max(rect.width, 1)
    matrix = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=matrix)
    return pix.tobytes("png")


def _upload_thumbnail(path: str, data: bytes) -> None:
    """생성된 썸네일 PNG를 Supabase Storage에 업로드한다."""
    client = supabase_client.get_service_client()
    client.storage.from_(_BUCKET).upload(path, data, _UPLOAD_OPTS)


def get_or_create_thumbnails(
    source_storage_path: str,
    source_type: str,
    start_page: int = 1,
    end_page: int | None = None,
    width: int = _THUMBNAIL_WIDTH,
    expires_in: int = 3600,
) -> tuple[int, list[dict]]:
    """PDF 썸네일을 생성하거나 캐시에서 가져와 서명된 URL 목록을 반환한다.

    매개변수:
        source_storage_path: 원본 파일의 Supabase Storage 경로
        source_type: "pdf" | "docx" | "hwp"
        start_page: 생성/조회 시작 페이지(1-based)
        end_page: 생성/조회 종료 페이지(미지정 시 마지막 페이지)
        width: 썸네일 표시 너비(px)
        expires_in: 서명 URL 만료 시간(초)

    반환값:
        (총 페이지 수, [{"page": int, "url": str}, ...]) 튜플

    예외:
        PDF를 열거나 렌더링할 수 없으면 HTTPException을 발생시킨다.
    """
    pdf_storage_path = _resolve_pdf_storage_path(source_storage_path, source_type)
    if not pdf_storage_path:
        return 0, []

    try:
        pdf_bytes = _download_pdf(pdf_storage_path)
    except Exception as e:
        logger.warning(f"[pdf-thumbnail] PDF 다운로드 실패 ({pdf_storage_path}): {e}")
        return 0, []

    cache_key = _cache_key(pdf_bytes)
    total_pages = _get_page_count(pdf_bytes)

    if start_page < 1:
        start_page = 1
    if end_page is None or end_page > total_pages:
        end_page = total_pages
    if start_page > end_page:
        return total_pages, []

    # 단일 요청으로 과도한 시간이 소요되는 것을 방지하기 위해 범위를 제한한다.
    if end_page - start_page + 1 > _MAX_THUMBNAILS_PER_REQUEST:
        end_page = start_page + _MAX_THUMBNAILS_PER_REQUEST - 1

    existing_names = _list_existing_thumbnail_names(cache_key)

    doc = fitz.open(stream=pdf_bytes)
    try:
        results = []
        for page_num in range(start_page, end_page + 1):
            filename = f"{page_num}.png"
            thumb_path = _thumbnail_path(cache_key, page_num)

            if filename not in existing_names:
                try:
                    img_bytes = _render_page(doc, page_num, width=width)
                    _upload_thumbnail(thumb_path, img_bytes)
                except Exception as e:
                    logger.warning(f"[pdf-thumbnail] 페이지 {page_num} 렌더링 실패: {e}")
                    continue

            try:
                url = supabase_client.get_signed_download_url(thumb_path, bucket=_BUCKET, expires_in=expires_in)
                results.append({"page": page_num, "url": url})
            except Exception as e:
                logger.warning(f"[pdf-thumbnail] 페이지 {page_num} 서명 URL 생성 실패: {e}")
                continue
    finally:
        doc.close()

    return total_pages, results
