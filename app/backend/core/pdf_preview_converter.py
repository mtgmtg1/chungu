#!/usr/bin/env python3
# [Flow: Step 1 (Supabase source_bucket에서 원본 다운로드) -> Step 2 (확장자별 변환: .hwp는 ODT 우선, PPTX/DOCX/ODT는 Unoserver 우선, 실패시 LibreOffice fallback) -> Step 3 (선형화 + 필요시 저화질 PDF 생성) -> Step 4 (pdfs/preview_pdfs Storage 업로드) -> Step 5 (서명된 URL 반환)]
import logging
import os
import socket
import subprocess
import tempfile
from pathlib import Path

import fitz

from ..config import settings

from . import supabase_client

try:
    from unoserver.client import UnoClient
except Exception:  # pragma: no cover - unoserver 클라이언트 패키지가 없을 때에도 모듈 로드가 깨지지 않도록
    UnoClient = None

logger = logging.getLogger(__name__)


_PREVIEW_PDF_BUCKET = "pdfs"
_PREVIEW_PDF_PREFIX = "preview_pdfs"
_LOWRES_PREVIEW_PDF_PREFIX = "preview_pdfs_lowres"
_LOWRES_THRESHOLD_BYTES = 10 * 1024 * 1024  # 10MB
_LOWRES_THRESHOLD_PAGES = 50
_LOWRES_DPI = 100

# PyMuPDF로 직접 PDF로 변환할 수 있는 이미지 확장자 (Unoserver/LibreOffice 불필요)
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"}


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


def _unoserver_ready(host: str, port: int, timeout: float = 2.0) -> bool:
    """지정된 호스트/포트의 Unoserver XMLRPC 서비스에 TCP 연결 가능한지 확인한다."""
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            return True
    except Exception:
        return False


def _convert_with_unoserver(input_path: Path, output_dir: Path) -> Path:
    """Unoserver XMLRPC 클라이언트로 입력 파일을 PDF로 변환한다.

    매개변수:
        input_path: 변환할 입력 파일 경로 (클라이언트 로컬 파일시스템)
        output_dir: 변환된 PDF를 저장할 디렉터리

    반환값:
        생성된 PDF 파일 경로
    """
    if UnoClient is None:
        raise RuntimeError("unoserver client package is not installed")

    output_path = output_dir / f"{input_path.stem}.pdf"
    client = UnoClient(
        server=settings.unoserver_host,
        port=str(settings.unoserver_port),
        host_location="remote",
    )
    client.convert(
        inpath=str(input_path),
        outpath=str(output_path),
        convert_to="pdf",
    )
    if not output_path.exists():
        raise FileNotFoundError(f"Unoserver PDF output not found: {output_path}")
    return output_path


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
        raise FileNotFoundError(f"LibreOffice PDF output not found: {expected}")
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
    return odt_path


def _convert_image_to_pdf(input_path: Path, output_dir: Path) -> Path:
    """PyMuPDF를 사용해 이미지를 단일 페이지 PDF로 변환한다.

    매개변수:
        input_path: 변환할 이미지 파일 경로 (.png/.jpg/.jpeg/.gif/.bmp/.webp/.tiff)
        output_dir: 변환된 PDF를 저장할 디렉터리

    반환값:
        생성된 PDF 파일 경로

    이미지 픽셀 크기를 PDF points(72 DPI)로 1:1 매핑하여 원본 비율을 보존한다.
    Unoserver/LibreOffice를 거치지 않으므로 빠르고 경량이다.
    """
    output_path = output_dir / f"{input_path.stem}.pdf"
    doc = fitz.open()
    try:
        # [Flow: Pixmap으로 이미지 픽셀 크기 획득 -> 동일 크기의 PDF 페이지 생성 -> 이미지 삽입]
        pix = fitz.Pixmap(str(input_path))
        page = doc.new_page(width=pix.width, height=pix.height)
        page.insert_image(page.rect, filename=str(input_path))
        try:
            doc.save(str(output_path), garbage=4, deflate=True)
        except Exception as e:
            if "Linearisation" in str(e) or "linear" in str(e).lower():
                doc.save(str(output_path), garbage=4, deflate=False)
            else:
                raise
    finally:
        doc.close()
    if not output_path.exists():
        raise FileNotFoundError(f"Image to PDF output not found: {output_path}")
    return output_path


def _convert_to_pdf(input_path: Path, output_dir: Path) -> Path:
    """확장자에 따라 Unoserver, hwp5odt, LibreOffice, PyMuPDF(이미지)를 이용해 PDF로 변환한다."""
    ext = input_path.suffix.lower()

    # [Flow: 이미지 확장자는 PyMuPDF로 직접 PDF 생성 (Unoserver/LibreOffice 불필요)]
    if ext in _IMAGE_EXTENSIONS:
        return _convert_image_to_pdf(input_path, output_dir)

    # [Flow: .hwp는 pyhwp hwp5odt로 ODT 변환 후 PDF로 변환. 실패하면 원본 .hwp를 Unoserver/LibreOffice에 직접 맡긴다.]
    if ext == ".hwp":
        odt_path = _run_hwp5odt(input_path, output_dir)
        if odt_path:
            input_path = odt_path
            ext = ".odt"

    # [Flow: Unoserver 우선 사용. 활성화되어 있고 TCP 연결 가능하면 변환 시도.]
    if settings.unoserver_enabled and _unoserver_ready(settings.unoserver_host, settings.unoserver_port):
        try:
            return _convert_with_unoserver(input_path, output_dir)
        except Exception as e:
            logger.warning(f"[unoserver] 변환 실패, LibreOffice fallback: {e}")

    # [Flow: Unoserver 사용 불가/실패 시 직접 LibreOffice fallback]
    return _run_libreoffice(input_path, output_dir)


def _linearize_pdf(input_path: Path, output_path: Path) -> None:
    """PDF를 Fast Web View(linearized) 형식으로 재저장하여 첫 페이지 바이트만 받아도 렌더링 가능하게 한다.
    PyMuPDF 최신 버전에서 linearization이 미지원인 경우 garbage/deflate만 적용한다."""
    doc = fitz.open(str(input_path))
    try:
        try:
            doc.save(str(output_path), linear=True, garbage=4, deflate=True)
        except Exception as e:
            if "Linearisation" in str(e) or "linear" in str(e).lower():
                logger.debug(f"[linearize] linearization 미지원, 일반 저장으로 폴백: {e}")
                doc.save(str(output_path), garbage=4, deflate=True)
            else:
                raise
    finally:
        doc.close()


def _create_lowres_preview_pdf(input_path: Path, output_path: Path, dpi: int = _LOWRES_DPI) -> None:
    """각 페이지를 저해상도 이미지로 렌더링하여 용량이 작은 미리보기 PDF를 생성한다."""
    src = fitz.open(str(input_path))
    dst = fitz.open()
    try:
        for page in src:
            rect = page.rect
            zoom = dpi / 72
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            new_page = dst.new_page(width=rect.width, height=rect.height)
            new_page.insert_image(rect, pixmap=pix)
        try:
            dst.save(str(output_path), linear=True, garbage=4, deflate=True)
        except Exception as e:
            if "Linearisation" in str(e) or "linear" in str(e).lower():
                logger.debug(f"[lowres] linearization 미지원, 일반 저장으로 폴백: {e}")
                dst.save(str(output_path), garbage=4, deflate=True)
            else:
                raise
    finally:
        src.close()
        dst.close()


def _needs_lowres_pdf(pdf_path: Path) -> bool:
    """PDF 파일 크기와 페이지 수를 기준으로 저화질 미리보기 생성이 필요한지 판단한다."""
    size = pdf_path.stat().st_size
    if size >= _LOWRES_THRESHOLD_BYTES:
        return True
    try:
        doc = fitz.open(str(pdf_path))
        try:
            return doc.page_count >= _LOWRES_THRESHOLD_PAGES
        finally:
            doc.close()
    except Exception:
        return False


def _preview_pdf_path(original_path: str) -> str:
    """원본 storage_path에 대응하는 미리보기 PDF storage_path를 생성한다."""
    safe = original_path.replace("/", "__")
    return f"{_PREVIEW_PDF_PREFIX}/{safe.rsplit('.', 1)[0]}.pdf"


def _lowres_preview_pdf_path(original_path: str) -> str:
    """원본 storage_path에 대응하는 저화질 미리보기 PDF storage_path를 생성한다."""
    safe = original_path.replace("/", "__")
    return f"{_LOWRES_PREVIEW_PDF_PREFIX}/{safe.rsplit('.', 1)[0]}.pdf"


def _get_existing_preview_url(storage_path: str, expires_in: int) -> str | None:
    """Storage에 이미 존재하는 미리보기 PDF에 대한 서명 URL을 생성한다."""
    if not storage_path:
        return None
    try:
        prefix = str(Path(storage_path).parent)
        client = supabase_client.get_service_client()
        existing = client.storage.from_(_PREVIEW_PDF_BUCKET).list(prefix)
        names = {item["name"] for item in (existing or [])}
        if Path(storage_path).name in names:
            return supabase_client.get_signed_download_url(storage_path, bucket=_PREVIEW_PDF_BUCKET, expires_in=expires_in)
    except Exception as e:
        logger.debug(f"[preview-pdf] 기존 PDF 확인 실패 ({storage_path}): {e}")
    return None


def get_preview_pdf_url(
    original_storage_path: str,
    source_bucket: str = "pdfs",
    expires_in: int = 3600,
) -> str | None:
    """원본 파일에 대한 미리보기 PDF URL을 반환한다. 이미 변환된 PDF가 있으면 재사용한다.

    매개변수:
        original_storage_path: 원본 파일의 Storage 경로
        source_bucket: 원본 파일이 위치한 Supabase Storage 버킷 (기본값: pdfs)
        expires_in: 서명 URL 만료 시간(초)

    반환값:
        변환된 미리보기 PDF의 서명 URL, 실패 시 None
    """
    if not original_storage_path:
        return None

    preview_path = _preview_pdf_path(original_storage_path)
    existing = _get_existing_preview_url(preview_path, expires_in)
    if existing:
        return existing

    client = supabase_client.get_service_client()

    # [Flow: 원본 파일은 source_bucket에서 다운로드 (sandbox 결과는 jobs 버킷)]
    try:
        original_bytes = client.storage.from_(source_bucket).download(original_storage_path)
    except Exception as e:
        logger.warning(f"[preview-pdf] 원본 다운로드 실패 ({source_bucket}/{original_storage_path}): {e}")
        return None

    # PDF 변환
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            ext = Path(original_storage_path).suffix.lower() or ".bin"
            input_path = tmpdir_path / f"input{ext}"
            input_path.write_bytes(original_bytes)
            pdf_path = _convert_to_pdf(input_path, tmpdir_path)

            # 선형화 적용
            linearized_path = tmpdir_path / "linearized.pdf"
            _linearize_pdf(pdf_path, linearized_path)

            client.storage.from_(_PREVIEW_PDF_BUCKET).upload(
                preview_path,
                linearized_path.read_bytes(),
                {"content-type": "application/pdf", "upsert": "true"},
            )
    except Exception as e:
        logger.warning(f"[preview-pdf] PDF 변환 실패 ({original_storage_path}): {e}")
        return None

    return supabase_client.get_signed_download_url(preview_path, bucket=_PREVIEW_PDF_BUCKET, expires_in=expires_in)


def get_lowres_preview_pdf_url(
    original_storage_path: str,
    source_bucket: str = "pdfs",
    expires_in: int = 3600,
) -> str | None:
    """대용량 원본 파일에 대한 저화질 미리보기 PDF URL을 반환한다.

    매개변수:
        original_storage_path: 원본 파일의 Storage 경로
        source_bucket: 원본 파일이 위치한 Supabase Storage 버킷 (기본값: pdfs)
        expires_in: 서명 URL 만료 시간(초)
    """
    if not original_storage_path:
        return None

    lowres_path = _lowres_preview_pdf_path(original_storage_path)
    client = supabase_client.get_service_client()

    # 이미 저화질 PDF가 있으면 재사용
    try:
        existing_lowres = client.storage.from_(_PREVIEW_PDF_BUCKET).list(_LOWRES_PREVIEW_PDF_PREFIX)
        names = {item["name"] for item in (existing_lowres or [])}
        if Path(lowres_path).name in names:
            return supabase_client.get_signed_download_url(lowres_path, bucket=_PREVIEW_PDF_BUCKET, expires_in=expires_in)
    except Exception as e:
        logger.debug(f"[preview-pdf-lowres] 기존 저화질 PDF 확인 실패: {e}")

    is_original_pdf = Path(original_storage_path).suffix.lower() == ".pdf"
    highres_path = original_storage_path if is_original_pdf else _preview_pdf_path(original_storage_path)

    # 원본이 PDF가 아니면 고화질 미리보기 PDF가 있는지 확인하고 없으면 생성
    if not is_original_pdf:
        try:
            existing_preview = client.storage.from_(_PREVIEW_PDF_BUCKET).list(_PREVIEW_PDF_PREFIX)
            names = {item["name"] for item in (existing_preview or [])}
            if Path(highres_path).name not in names:
                return get_preview_pdf_url(original_storage_path, source_bucket=source_bucket, expires_in=expires_in)
        except Exception as e:
            logger.debug(f"[preview-pdf-lowres] 기존 PDF 확인 실패: {e}")
            return None

    # 고화질 원본/미리보기 PDF 다운로드
    try:
        highres_bytes = client.storage.from_(_PREVIEW_PDF_BUCKET).download(highres_path)
    except Exception as e:
        logger.warning(f"[preview-pdf-lowres] 고화질 PDF 다운로드 실패 ({highres_path}): {e}")
        return None

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            highres_local = tmpdir_path / "highres.pdf"
            highres_local.write_bytes(highres_bytes)

            if not _needs_lowres_pdf(highres_local):
                # 저화질이 필요 없으면 고화질 URL 반환
                return supabase_client.get_signed_download_url(highres_path, bucket=_PREVIEW_PDF_BUCKET, expires_in=expires_in)

            lowres_local = tmpdir_path / "lowres.pdf"
            _create_lowres_preview_pdf(highres_local, lowres_local)
            client.storage.from_(_PREVIEW_PDF_BUCKET).upload(
                lowres_path,
                lowres_local.read_bytes(),
                {"content-type": "application/pdf", "upsert": "true"},
            )
    except Exception as e:
        logger.warning(f"[preview-pdf-lowres] 저화질 PDF 생성 실패 ({original_storage_path}): {e}")
        # 실패 시 고화질 URL 폴백
        try:
            return supabase_client.get_signed_download_url(highres_path, bucket=_PREVIEW_PDF_BUCKET, expires_in=expires_in)
        except Exception:
            return None

    return supabase_client.get_signed_download_url(lowres_path, bucket=_PREVIEW_PDF_BUCKET, expires_in=expires_in)
