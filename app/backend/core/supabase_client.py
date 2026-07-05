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

# PDF 메타데이터 추출에 사용할 임계값
_MAX_PAGE_SIDE_MM = 350
_MM_PER_PT = 0.3528
_LOWRES_THRESHOLD_BYTES = 10 * 1024 * 1024
_LOWRES_THRESHOLD_PAGES = 50
_TEXT_LAYER_MIN_CHARS = 50


def create_fresh_service_client() -> Client:
    """스레드 안전을 위해 캐싱되지 않은 새로운 서비스 롤 클라이언트를 생성한다."""
    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError("Supabase URL/Service Key is not configured")
    return create_client(settings.supabase_url, settings.supabase_service_key)


@lru_cache
def get_service_client() -> Client:
    """서비스 롤 키로 Supabase에 접근 (백엔드 전용)."""
    return create_fresh_service_client()


@lru_cache
def get_anon_client() -> Client:
    """anon 키로 Supabase에 접근 (프론트 검증용)."""
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise RuntimeError("Supabase URL/Anon Key is not configured")
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
    # 3. 연속된 점/언더스코어 정리, 소문자화
    safe = re.sub(r"[._]{2,}", "_", safe).lower()
    # 4. 빈 이름 방지
    if not safe:
        safe = "file"
    # 5. 확장자 보존 (없으면 .bin)
    ext = Path(filename).suffix.lower() or ".bin"
    if not safe.endswith(ext):
        safe = safe + ext
    return safe


def _safe_job_path(filename: str, job_id: str | None = None) -> str:
    """업로드 파일의 안전한 Storage 경로를 생성한다."""
    safe = _sanitize_storage_filename(filename)
    if job_id:
        return f"{job_id}/{safe}"
    return safe


def _extract_pdf_metadata(data: bytes) -> dict[str, str]:
    """PDF 바이트에서 페이지 수, 텍스트 레이어, 초과 페이지 수, 저화질 필요 여부를 추출한다.

    반환값:
        page_count, oversized_page_count, has_text_layer, needs_lowres, file_size, content_type
        값은 모두 문자열로 변환되어 Storage 메타데이터에 저장된다.
    """
    try:
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(data))
        page_count = len(reader.pages)
        oversized_count = 0
        total_chars = 0
        for page in reader.pages:
            width_mm = float(page.mediabox.width) * _MM_PER_PT
            height_mm = float(page.mediabox.height) * _MM_PER_PT
            if width_mm > _MAX_PAGE_SIDE_MM or height_mm > _MAX_PAGE_SIDE_MM:
                oversized_count += 1
            try:
                text = page.extract_text() or ""
                total_chars += len(text)
            except Exception:
                pass
        needs_lowres = len(data) >= _LOWRES_THRESHOLD_BYTES or page_count >= _LOWRES_THRESHOLD_PAGES
        return {
            "page_count": str(page_count),
            "oversized_page_count": str(oversized_count),
            "has_text_layer": "true" if total_chars >= _TEXT_LAYER_MIN_CHARS else "false",
            "needs_lowres": "true" if needs_lowres else "false",
            "file_size": str(len(data)),
            "content_type": "application/pdf",
        }
    except Exception:
        return {}


def get_storage_metadata(bucket: str, path: str) -> dict[str, str] | None:
    """지정한 Storage 경로의 메타데이터를 조회한다. 실패하면 None을 반환한다."""
    if not path:
        return None
    try:
        client = get_service_client()
        info = client.storage.from_(bucket).info(path)
        return info.get("metadata") or {}
    except Exception:
        return None


def upload_input(file: BytesIO, filename: str, job_id: str) -> str:
    """업로드된 입력 파일을 pdfs 버킷에 저장하고 storage_path를 반환한다.

    PDF 파일인 경우 페이지 수, 텍스트 레이어 등의 메타데이터를 Storage에 저장한다.
    """
    client = get_service_client()
    storage_path = _safe_job_path(filename, job_id)
    content = file.read()
    content_type = "application/octet-stream"
    metadata: dict[str, str] = {"file_size": str(len(content)), "content_type": content_type}
    if Path(filename).suffix.lower() == ".pdf":
        metadata.update(_extract_pdf_metadata(content))
    client.storage.from_("pdfs").upload(
        storage_path,
        content,
        {"content-type": content_type, "upsert": "true", "metadata": metadata},
    )
    return storage_path


def upload_pdf(job_id: str, data: bytes, filename: str) -> str:
    """업로드된 PDF/문서 파일을 pdfs 버킷에 저장하고 storage_path를 반환한다.

    PDF 파일인 경우 페이지 수, 텍스트 레이어 등의 메타데이터를 Storage에 저장한다.
    """
    client = get_service_client()
    storage_path = _safe_job_path(filename, job_id)
    content_type = "application/pdf" if Path(filename).suffix.lower() == ".pdf" else "application/octet-stream"
    metadata: dict[str, str] = {"file_size": str(len(data)), "content_type": content_type}
    if Path(filename).suffix.lower() == ".pdf":
        metadata.update(_extract_pdf_metadata(data))
    client.storage.from_("pdfs").upload(
        storage_path,
        data,
        {"content-type": content_type, "upsert": "true", "metadata": metadata},
    )
    return storage_path


def upload_result(
    job_id: str,
    md_path: Path | None = None,
    edited_md_path: Path | None = None,
    csv_path: Path | None = None,
    xlsx_basic_path: Path | None = None,
    xlsx_advanced_path: Path | None = None,
    docx_path: Path | None = None,
    pptx_path: Path | None = None,
) -> dict[str, str]:
    """결과 파일들을 results 버킷에 업로드하고 storage_path 맵을 반환한다."""
    client = get_service_client()
    paths: dict[str, str] = {}
    base = f"{job_id}/"

    def _upload(path: Path | None, key: str, ext: str) -> None:
        if not path:
            return
        storage_path = f"{base}{key}.{ext}"
        client.storage.from_("results").upload(
            storage_path,
            path.read_bytes(),
            {"content-type": "application/octet-stream", "upsert": "true"},
        )
        paths[key] = storage_path

    _upload(md_path, "md", "md")
    _upload(edited_md_path, "edited_md", "md")
    _upload(csv_path, "csv", "csv")
    _upload(xlsx_basic_path, "xlsx_basic", "xlsx")
    _upload(xlsx_advanced_path, "xlsx_advanced", "xlsx")
    _upload(docx_path, "docx", "docx")
    _upload(pptx_path, "pptx", "pptx")
    return paths


def _get_content_type(filename: str) -> str:
    """파일 확장자에 따른 Content-Type을 반환한다."""
    content_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
    }
    ext = Path(filename).suffix.lower()
    return content_type_map.get(ext, "image/jpeg")


def upload_image_result(local_path: Path, job_id: str, filename: str) -> str:
    """OCR 결과 이미지를 results 버킷에 업로드하고 storage_path를 반환한다."""
    client = get_service_client()
    ext = Path(filename).suffix.lower()
    # 안전한 파일명으로 변환 후 저장
    safe_name = _sanitize_storage_filename(filename)
    base = hashlib.md5(safe_name.encode()).hexdigest()[:8]
    storage_path = f"{job_id}/images/{base}{ext}"
    content_type = _get_content_type(filename)
    client.storage.from_("results").upload(
        storage_path,
        local_path.read_bytes(),
        {"content-type": content_type, "upsert": "true"},
    )
    return storage_path


def upload_page_image(local_path: Path, job_id: str, page_num: int) -> str:
    """페이지 이미지를 results 버킷에 업로드하고 storage_path를 반환한다."""
    client = get_service_client()
    ext = Path(local_path.name).suffix.lower() or ".png"
    storage_path = f"{job_id}/pages/{page_num}{ext}"
    content_type = _get_content_type(f"page{ext}")
    client.storage.from_("pdfs").upload(
        storage_path,
        local_path.read_bytes(),
        {"content-type": content_type, "upsert": "true"},
    )
    return storage_path


def get_signed_download_url_with_client(client: Client, storage_path: str, bucket: str = "results", expires_in: int = 3600) -> str:
    """지정한 Supabase 클라이언트로 서명된 다운로드 URL을 생성합니다. 외부 노출 URL로 재작성합니다."""
    url = client.storage.from_(bucket).create_signed_url(storage_path, expires_in).get("signedURL", "")
    if url and settings.supabase_public_url:
        internal = settings.supabase_url.rstrip("/")
        url = url.replace(internal, settings.supabase_public_url.rstrip("/"))
    return url


def get_signed_download_url(storage_path: str, bucket: str = "results", expires_in: int = 3600) -> str:
    """결과 파일의 서명된 다운로드 URL을 생성합니다. 외부 노출 URL로 재작성합니다."""
    client = get_service_client()
    return get_signed_download_url_with_client(client, storage_path, bucket, expires_in)


def download_pdf(storage_path: str) -> BytesIO:
    """pdfs 버킷에서 지정한 storage_path의 파일을 다운로드하여 BytesIO로 반환합니다."""
    client = get_service_client()
    data = client.storage.from_("pdfs").download(storage_path)
    return BytesIO(data)


def upload_office_result(job_id: str, local_path: Path, ext: str) -> str:
    """XLSX/CSV 등 Office 변환 결과를 results 버킷에 업로드하고 storage_path를 반환합니다."""
    client = get_service_client()
    storage_path = f"{job_id}/result.{ext}"
    client.storage.from_("results").upload(
        storage_path,
        local_path.read_bytes(),
        {"content-type": "application/octet-stream", "upsert": "true"},
    )
    return storage_path


def upload_edited_xlsx(job_id: str, data: bytes, filename: str) -> str:
    """사용자가 편집한 XLSX 파일을 results 버킷에 업로드하고 storage_path를 반환합니다."""
    client = get_service_client()
    safe_name = _sanitize_storage_filename(filename)
    storage_path = f"{job_id}/edited/{safe_name}"
    client.storage.from_("results").upload(
        storage_path,
        data,
        {"content-type": "application/octet-stream", "upsert": "true"},
    )
    return storage_path


def _delete_storage_path(bucket: str, path: str) -> None:
    """단일 Storage 경로를 삭제합니다. 경로가 비어있거나 없으면 무시합니다."""
    if not path:
        return
    client = get_service_client()
    try:
        client.storage.from_(bucket).remove([path])
    except Exception:
        # 이미 삭제되었거나 존재하지 않는 파일은 무시
        pass


def delete_source_files(job) -> None:
    """OCR 원본 업로드 파일(pdfs 버킷)을 삭제합니다. DB 레코드는 유지합니다."""
    if job.pdf_storage_path:
        _delete_storage_path("pdfs", job.pdf_storage_path)
    for info in job.extracted_files or []:
        sp = info.get("storage_path") if isinstance(info, dict) else None
        if sp:
            _delete_storage_path("pdfs", sp)
    for info in job.source_images or []:
        sp = info.get("storage_path") if isinstance(info, dict) else None
        if sp:
            _delete_storage_path("results", sp)
