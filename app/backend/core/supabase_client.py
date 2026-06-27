#!/usr/bin/env python3
# [Flow: Step 1 (설정에서 URL/키 로드) -> Step 2 (Supabase 클라이언트 싱글턴) -> Step 3 (Storage/Auth 헬퍼)]
import hashlib
import re
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from supabase import Client, create_client
from unidecode import unidecode

from ..config import settings


@lru_cache
def get_service_client() -> Client:
    """서비스 롤 키로 Supabase에 접근 (백엔드 전용)."""
    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError("Supabase URL/Service Key가 설정되지 않았습니다")
    return create_client(settings.supabase_url, settings.supabase_service_key)


@lru_cache
def get_anon_client() -> Client:
    """anon 키로 Supabase에 접근 (프론트 검증용)."""
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise RuntimeError("Supabase URL/Anon Key가 설정되지 않았습니다")
    return create_client(settings.supabase_url, settings.supabase_anon_key)


def _sanitize_storage_filename(filename: str) -> str:
    """Supabase Storage 호환을 위해 ASCII 영문/숫자/기본 기호로 변환한다.

    표시용 이름(DB original_filename)은 그대로 유지하고, 저장 경로만 안전하게 만든다.
    """
    # 1. 유니코드 문자를 로마자/ASCII로 변환 (한글 -> 영문 발음, 일본어 -> romaji)
    ascii_name = unidecode(filename)
    # 2. 공백은 언더스코어로, 위험 문자는 제거
    safe = re.sub(r"[^\w\-. ]", "", ascii_name).strip()
    safe = re.sub(r"\s+", "_", safe)
    # 3. 확장자가 제거되었으면 복원
    if "." not in safe:
        ext = Path(filename).suffix
        if ext:
            safe = safe + ext
    return safe or "document"


def upload_pdf(job_id: str, data: bytes, filename: str) -> str:
    """pdfs 버킷에 PDF를 업로드하고 경로를 반환합니다."""
    client = get_service_client()
    safe_filename = _sanitize_storage_filename(filename)
    path = f"{job_id}/{safe_filename}"
    client.storage.from_("pdfs").upload(path, data, {"content-type": "application/pdf", "upsert": "true"})
    return path


def upload_input(job_id: str, data: bytes, filename: str, content_type: str = "application/octet-stream") -> str:
    """pdfs 버킷에 압축/미디어 입력 파일을 업로드하고 경로를 반환합니다."""
    client = get_service_client()
    safe_filename = _sanitize_storage_filename(filename)
    path = f"{job_id}/{safe_filename}"
    client.storage.from_("pdfs").upload(path, data, {"content-type": content_type, "upsert": "true"})
    return path


def upload_result(
    job_id: str,
    csv_path: Path | None = None,
    md_path: Path | None = None,
    xlsx_path: Path | None = None,
    docx_path: Path | None = None,
    pptx_path: Path | None = None,
    edited_md_path: Path | None = None,
) -> dict:
    """results 버킷에 CSV/MD/XLSX/DOCX/PPTX/편집된 MD를 업로드하고 경로를 반환합니다."""
    client = get_service_client()
    out = {}
    uploads = [
        (csv_path, f"{job_id}/result.csv", "text/csv"),
        (md_path, f"{job_id}/result.md", "text/markdown"),
        (xlsx_path, f"{job_id}/result.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        (docx_path, f"{job_id}/result.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        (pptx_path, f"{job_id}/result.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
        (edited_md_path, f"{job_id}/result_edited.md", "text/markdown"),
    ]
    for path, storage_path, content_type in uploads:
        if path and path.exists():
            client.storage.from_("results").upload(storage_path, path.read_bytes(), {"content-type": content_type, "upsert": "true"})
            key = storage_path.split("/")[-1].split(".")[-1]
            if key == "md" and storage_path.endswith("result_edited.md"):
                key = "edited_md"
            out[key] = storage_path
    return out


def upload_office_result(job_id: str, path: Path, ext: str) -> str:
    """단일 office 파일을 results 버킷에 업로드하고 경로를 반환합니다."""
    client = get_service_client()
    content_type_map = {
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    storage_path = f"{job_id}/result.{ext}"
    client.storage.from_("results").upload(storage_path, path.read_bytes(), {"content-type": content_type_map.get(ext, "application/octet-stream"), "upsert": "true"})
    return storage_path


def download_pdf(storage_path: str) -> BytesIO:
    """pdfs 버킷에서 PDF를 다운로드합니다."""
    client = get_service_client()
    data = client.storage.from_("pdfs").download(storage_path)
    return BytesIO(data)


def upload_image(job_id: str, local_path: Path, filename: str) -> str:
    """개별 이미지 파일을 pdfs 버킷에 업로드하고 경로를 반환합니다."""
    client = get_service_client()
    ext = Path(filename).suffix.lower()
    safe_stem = re.sub(r"[^\w\-.]", "", unidecode(Path(filename).stem)) or "image"
    unique = hashlib.md5(filename.encode("utf-8")).hexdigest()[:8]
    storage_path = f"{job_id}/images/{safe_stem}_{unique}{ext}"
    content_type_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
    }
    ext = Path(filename).suffix.lower()
    content_type = content_type_map.get(ext, "image/jpeg")
    client.storage.from_("pdfs").upload(storage_path, local_path.read_bytes(), {"content-type": content_type, "upsert": "true"})
    return storage_path


def get_signed_download_url(storage_path: str, bucket: str = "results", expires_in: int = 3600) -> str:
    """결과 파일의 서명된 다운로드 URL을 생성합니다. 외부 노출 URL로 재작성합니다."""
    client = get_service_client()
    url = client.storage.from_(bucket).create_signed_url(storage_path, expires_in).get("signedURL", "")
    if url and settings.supabase_public_url:
        internal = settings.supabase_url.rstrip("/")
        url = url.replace(internal, settings.supabase_public_url.rstrip("/"))
    return url
