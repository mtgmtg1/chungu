#!/usr/bin/env python3
# [Flow: Step 1 (설정에서 URL/키 로드) -> Step 2 (Supabase 클라이언트 싱글턴) -> Step 3 (Storage/Auth 헬퍼)]
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from supabase import Client, create_client

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


def upload_pdf(job_id: str, data: bytes, filename: str) -> str:
    """pdfs 버킷에 PDF를 업로드하고 경로를 반환합니다."""
    client = get_service_client()
    path = f"{job_id}/{filename}"
    client.storage.from_("pdfs").upload(path, data, {"content-type": "application/pdf", "upsert": "true"})
    return path


def upload_input(job_id: str, data: bytes, filename: str, content_type: str = "application/octet-stream") -> str:
    """pdfs 버킷에 압축/미디어 입력 파일을 업로드하고 경로를 반환합니다."""
    client = get_service_client()
    path = f"{job_id}/{filename}"
    client.storage.from_("pdfs").upload(path, data, {"content-type": content_type, "upsert": "true"})
    return path


def upload_result(
    job_id: str,
    csv_path: Path | None = None,
    md_path: Path | None = None,
    xlsx_path: Path | None = None,
) -> dict:
    """results 버킷에 CSV/MD/XLSX를 업로드하고 경로를 반환합니다."""
    client = get_service_client()
    out = {}
    if csv_path and csv_path.exists():
        p = f"{job_id}/result.csv"
        client.storage.from_("results").upload(p, csv_path.read_bytes(), {"content-type": "text/csv", "upsert": "true"})
        out["csv"] = p
    if md_path and md_path.exists():
        p = f"{job_id}/result.md"
        client.storage.from_("results").upload(p, md_path.read_bytes(), {"content-type": "text/markdown", "upsert": "true"})
        out["md"] = p
    if xlsx_path and xlsx_path.exists():
        p = f"{job_id}/result.xlsx"
        client.storage.from_("results").upload(p, xlsx_path.read_bytes(), {"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "upsert": "true"})
        out["xlsx"] = p
    return out


def download_pdf(storage_path: str) -> BytesIO:
    """pdfs 버킷에서 PDF를 다운로드합니다."""
    client = get_service_client()
    data = client.storage.from_("pdfs").download(storage_path)
    return BytesIO(data)


def get_signed_download_url(storage_path: str, bucket: str = "results", expires_in: int = 3600) -> str:
    """결과 파일의 서명된 다운로드 URL을 생성합니다."""
    client = get_service_client()
    return client.storage.from_(bucket).create_signed_url(storage_path, expires_in).get("signedURL", "")
