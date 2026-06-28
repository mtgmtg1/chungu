#!/usr/bin/env python3
# [Flow: Step 1 (Supabase에서 원본 다운로드) -> Step 2 (LibreOffice로 PDF 변환) -> Step 3 (PDF를 Supabase에 업로드) -> Step 4 (서명된 URL 반환)]
import logging
import subprocess
import tempfile
from pathlib import Path

from . import supabase_client

logger = logging.getLogger(__name__)


_PREVIEW_PDF_BUCKET = "pdfs"
_PREVIEW_PDF_PREFIX = "preview_pdfs"


def _run_libreoffice(input_path: Path, output_dir: Path) -> Path:
    """LibreOffice headless를 이용해 입력 파일을 PDF로 변환한다."""
    cmd = [
        "libreoffice",
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(input_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    expected = output_dir / f"{input_path.stem}.pdf"
    if not expected.exists():
        raise FileNotFoundError(f"LibreOffice PDF 변환 산출물을 찾을 수 없습니다: {expected}")
    return expected


def _preview_pdf_path(original_path: str) -> str:
    """원본 storage_path에 대응하는 미리보기 PDF storage_path를 생성한다."""
    safe = original_path.replace("/", "__")
    return f"{_PREVIEW_PDF_PREFIX}/{safe.rsplit('.', 1)[0]}.pdf"


def get_preview_pdf_url(original_storage_path: str, expires_in: int = 3600) -> str | None:
    """원본 파일에 대한 미리보기 PDF URL을 반환한다. 이미 변환된 PDF가 있으면 재사용한다."""
    if not original_storage_path:
        return None

    preview_path = _preview_pdf_path(original_storage_path)
    client = supabase_client.get_service_client()

    # 이미 변환된 PDF가 있으면 서명 URL 생성
    try:
        existing = client.storage.from_(_PREVIEW_PDF_BUCKET).list(_PREVIEW_PDF_PREFIX)
        names = {item["name"] for item in (existing or [])}
        if Path(preview_path).name in names:
            return supabase_client.get_signed_download_url(preview_path, bucket=_PREVIEW_PDF_BUCKET, expires_in=expires_in)
    except Exception as e:
        logger.debug(f"[preview-pdf] 기존 PDF 확인 실패: {e}")

    # 원본 파일 다운로드
    try:
        original_bytes = client.storage.from_(_PREVIEW_PDF_BUCKET).download(original_storage_path)
    except Exception as e:
        logger.warning(f"[preview-pdf] 원본 다운로드 실패 ({original_storage_path}): {e}")
        return None

    # PDF 변환
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            ext = Path(original_storage_path).suffix.lower() or ".bin"
            input_path = tmpdir_path / f"input{ext}"
            input_path.write_bytes(original_bytes)
            pdf_path = _run_libreoffice(input_path, tmpdir_path)
            client.storage.from_(_PREVIEW_PDF_BUCKET).upload(
                preview_path,
                pdf_path.read_bytes(),
                {"content-type": "application/pdf", "upsert": "true"},
            )
    except Exception as e:
        logger.warning(f"[preview-pdf] PDF 변환 실패 ({original_storage_path}): {e}")
        return None

    return supabase_client.get_signed_download_url(preview_path, bucket=_PREVIEW_PDF_BUCKET, expires_in=expires_in)
