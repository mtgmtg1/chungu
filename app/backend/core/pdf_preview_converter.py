#!/usr/bin/env python3
# [Flow: Step 1 (Supabase에서 원본 다운로드) -> Step 2 (LibreOffice로 PDF 변환) -> Step 3 (PDF를 Supabase에 업로드) -> Step 4 (서명된 URL 반환)]
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from . import supabase_client

logger = logging.getLogger(__name__)


_PREVIEW_PDF_BUCKET = "pdfs"
_PREVIEW_PDF_PREFIX = "preview_pdfs"


def _libreoffice_env() -> dict[str, str]:
    """LibreOffice headless 변환에 필요한 locale 및 사용자 프로필 경로를 설정한다."""
    return {
        **dict(os.environ),
        "LANG": "ko_KR.UTF-8",
        "LC_ALL": "ko_KR.UTF-8",
        "HOME": "/tmp",
        "XDG_CONFIG_HOME": "/tmp/.config",
        "XDG_CACHE_HOME": "/tmp/.cache",
    }


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
    env = _libreoffice_env()
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120, env=env)
    stdout_text = result.stdout.decode("utf-8", errors="ignore")
    stderr_text = result.stderr.decode("utf-8", errors="ignore")
    if result.returncode != 0:
        logger.warning(f"[libreoffice] 변환 실패 (returncode={result.returncode}): {stderr_text[:1000]} {stdout_text[:500]}")
        raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)
    if stderr_text:
        logger.debug(f"[libreoffice] stderr: {stderr_text[:500]}")
    expected = output_dir / f"{input_path.stem}.pdf"
    if not expected.exists():
        raise FileNotFoundError(f"LibreOffice PDF 변환 산출물을 찾을 수 없습니다: {expected}")
    return expected


def _run_hwp5odt(input_path: Path, output_dir: Path) -> Path | None:
    """pyhwp의 hwp5odt로 HWP -> ODT 변환 후 LibreOffice로 PDF로 변환한다."""
    ext = input_path.suffix.lower()
    if ext != ".hwp":
        return None
    odt_path = output_dir / f"{input_path.stem}.odt"
    cmd = [
        "hwp5odt",
        "--output",
        str(odt_path),
        str(input_path),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120, env=_libreoffice_env())
    except FileNotFoundError:
        logger.debug("[hwp5odt] hwp5odt 명령을 찾을 수 없어 LibreOffice 직접 변환을 사용합니다")
        return None
    except subprocess.CalledProcessError as e:
        stderr_text = e.stderr.decode("utf-8", errors="ignore") if e.stderr else ""
        logger.debug(f"[hwp5odt] HWP -> ODT 변환 실패: {stderr_text[:500]}")
        return None
    if not odt_path.exists():
        return None
    return _run_libreoffice(odt_path, output_dir)


def _convert_to_pdf(input_path: Path, output_dir: Path) -> Path:
    """확장자에 따라 LibreOffice 또는 hwp5odt를 이용해 PDF로 변환한다."""
    ext = input_path.suffix.lower()
    if ext == ".hwp":
        try:
            result = _run_hwp5odt(input_path, output_dir)
            if result:
                return result
        except Exception as e:
            logger.debug(f"[hwp5odt] fallback 실패, LibreOffice 직접 변환 시도: {e}")
    return _run_libreoffice(input_path, output_dir)


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
            pdf_path = _convert_to_pdf(input_path, tmpdir_path)
            client.storage.from_(_PREVIEW_PDF_BUCKET).upload(
                preview_path,
                pdf_path.read_bytes(),
                {"content-type": "application/pdf", "upsert": "true"},
            )
    except Exception as e:
        logger.warning(f"[preview-pdf] PDF 변환 실패 ({original_storage_path}): {e}")
        return None

    return supabase_client.get_signed_download_url(preview_path, bucket=_PREVIEW_PDF_BUCKET, expires_in=expires_in)
