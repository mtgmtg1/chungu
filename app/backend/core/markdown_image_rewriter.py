#!/usr/bin/env python3
# [Flow: Step 1 (data:image base64 정규식 매칭) -> Step 2 (base64 디코딩 및 content hash 계산)
#       -> Step 3 (중복 방지 캐시 확인) -> Step 4 (Supabase Storage 업로드) -> Step 5 (proxy URL로 치환)]
"""마크다운 내 data:image base64 인라인 이미지를 Supabase Storage에 업로드하고 proxy URL로 치환한다."""
import base64
import hashlib
import logging
import re

from . import supabase_client


logger = logging.getLogger(__name__)


# data:image/{mime};base64,{base64} 형태의 인라인 이미지 URI를 매칭한다.
_INLINE_IMAGE_DATA_URI_RE = re.compile(
    r"data:image/([^;\s]+);base64,([A-Za-z0-9+/=]+)",
    re.IGNORECASE,
)


# MIME 타입 -> (확장자, HTTP content-type) 매핑
_MIME_INFO: dict[str, tuple[str, str]] = {
    "png": ("png", "image/png"),
    "jpeg": ("jpg", "image/jpeg"),
    "jpg": ("jpg", "image/jpeg"),
    "webp": ("webp", "image/webp"),
    "gif": ("gif", "image/gif"),
}


def _get_mime_info(mime: str) -> tuple[str, str]:
    """MIME 타입 문자열에서 파일 확장자와 content-type을 반환한다."""
    normalized = mime.lower().strip()
    return _MIME_INFO.get(normalized, ("png", "image/png"))


def _upload_inline_image(
    image_bytes: bytes,
    mime: str,
    job_id: str,
    bucket: str,
    cache: dict[str, str],
) -> str:
    """이미지 bytes를 Supabase Storage에 업로드하고 proxy URL을 반환한다."""
    content_hash = hashlib.md5(image_bytes).hexdigest()[:16]
    if content_hash in cache:
        return cache[content_hash]

    ext, content_type = _get_mime_info(mime)
    storage_path = f"{job_id}/images/{content_hash}.{ext}"
    client = supabase_client.get_service_client()
    client.storage.from_(bucket).upload(
        storage_path,
        image_bytes,
        {"content-type": content_type, "upsert": "true"},
    )
    proxy_url = f"/api/jobs/{job_id}/ocr-images/{storage_path}"
    cache[content_hash] = proxy_url
    return proxy_url


def rewrite_inline_images_to_storage(
    markdown: str,
    job_id: str,
    bucket: str = "results",
    placeholder: str = "[image]",
) -> str:
    """마크다운 내 data:image base64 인라인 이미지를 Supabase Storage에 업로드하고 proxy URL로 치환한다.

    Args:
        markdown: 처리할 마크다운 문자열
        job_id: Storage 경로 및 proxy URL에 사용할 job ID
        bucket: 업로드할 Supabase Storage 버킷 (기본값: results)
        placeholder: 업로드 실패 시 사용할 대체 문자열

    Returns:
        base64 이미지가 proxy URL로 치환된 마크다운
    """
    if not markdown:
        return markdown

    cache: dict[str, str] = {}

    def _replace(match: re.Match) -> str:
        mime = match.group(1)
        b64 = match.group(2)
        try:
            image_bytes = base64.b64decode(b64)
            if not image_bytes:
                return placeholder
            return _upload_inline_image(image_bytes, mime, job_id, bucket, cache)
        except Exception as e:
            logger.warning(f"[rewrite-inline-images:{job_id}] 이미지 업로드 실패: {e}")
            return placeholder

    return _INLINE_IMAGE_DATA_URI_RE.sub(_replace, markdown)
