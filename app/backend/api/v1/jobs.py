#!/usr/bin/env python3
# [Flow: Step 1 (API key 인증) -> Step 2 (파일 업로드/비용 계산) -> Step 3 (confirm 시 포인트 차감 + Celery) -> Step 4 (상태 조회/다운로드)]
import asyncio
import json
import logging
import tempfile
import unicodedata
import uuid
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import List

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile, status
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...auth.api_key_auth import require_api_key_with_key
from ...auth.supabase_auth import CurrentUser
from ...core import archive_handler, docling_client, hwp_converter, media_loader, office_converter, points_service, supabase_client
from ...core.job_helpers import convert_format_alias, parse_columns
from ...core.prompts import DEFAULT_COLUMNS
from ...core.rate_limit import add_daily_spent_points, enforce_rate_limit
from ...db.models import ApiKey, ApiUsage, Job, User
from ...db.session import get_db
from ... import settings_store
from ...workers.tasks import run_job

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _normalize_display_name(name: str | None) -> str:
    """표시용 파일명을 Unicode 조합 정규형(NFC)으로 변환한다.

    macOS에서 생성된 압축 파일 등에 포함된 한글 파일명이 분해 정규형(NFD)으로
    저장되어 있으면 자음/모음이 분리되어 보일 수 있다.
    """
    if not name:
        return ""
    try:
        return unicodedata.normalize("NFC", name)
    except Exception:
        return name


async def _count_pages_with_docling(data: bytes, filename: str) -> int:
    """Docling 서비스에 파일을 보내 페이지 수를 추정한다. 실패하면 1을 반환한다.

    [Flow: Step 1 (Docling 비활성화 시 1 반환) -> Step 2 (임시 파일로 변환 요청) -> Step 3 (실패 시 1 반환)]
    """
    if not docling_client.is_enabled():
        return 1
    suffix = Path(filename).suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        await asyncio.to_thread(docling_client.convert_file, tmp_path)
        return 1
    except Exception as e:
        logger.warning(f"[docling-page-count] {filename} 실패: {e}")
        return 1
    finally:
        tmp_path.unlink(missing_ok=True)


MEDIA_EXTENSIONS = {
    ".pdf", ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif",
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma",
    ".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm", ".m4v",
    ".md",
    ".docx", ".doc", ".dotx", ".docm",
    ".pptx", ".ppt", ".potx", ".ppsx", ".pptm", ".potm", ".ppsm",
    ".xlsx", ".xls", ".xlsm",
    ".hwp", ".hwpx",
}


def _job_summary(job: Job) -> dict:
    return {
        "job_id": job.id,
        "status": job.status,
        "pipeline": job.pipeline,
        "file_type": job.file_type,
        "filename": job.original_filename,
        "total_pages": job.total_pages,
        "done_pages": job.done_pages,
        "total_files": job.total_files,
        "done_files": job.done_files,
        "media_duration_seconds": job.media_duration_seconds,
        "ocr_model": job.ocr_model or "premium",
        "ocr_engine": job.ocr_engine or "easyocr",
        "cost_points": job.cost_points,
        "error_log": job.error_log,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "downloadable": job.status == "done",
        "xlsx_converted": bool(job.result_xlsx_storage_path),
        "xlsx_basic_converted": bool(job.result_xlsx_basic_storage_path),
        "xlsx_advanced_converted": bool(job.result_xlsx_advanced_storage_path),
        "xlsx_advanced_status": job.xlsx_advanced_status,
        "xlsx_advanced_job_id": job.result_xlsx_advanced_job_id,
        "xlsx_advanced_refundable": job.xlsx_advanced_refundable,
        "xlsx_advanced_recovery_notes": job.xlsx_advanced_recovery_notes,
        "refundable": job.refundable,
        "retry_count": job.retry_count,
    }


def _log_api_usage(
    db: Session,
    api_key: ApiKey,
    user_id: uuid.UUID,
    endpoint: str,
    status_code: int,
    points_spent: int = 0,
    job_id: str | None = None,
    client_ip: str = "",
) -> None:
    usage = ApiUsage(
        api_key_id=api_key.id,
        user_id=user_id,
        endpoint=endpoint,
        job_id=job_id,
        points_spent=points_spent,
        http_status=status_code,
        client_ip=client_ip,
    )
    db.add(usage)
    db.commit()


@router.post("/upload")
async def upload_job(
    request: Request,
    files: List[UploadFile] = File(...),
    pipeline: str = Form("vision"),
    columns: str = Form(""),
    prompt: str = Form(""),
    dpi: int = Form(300),
    relative_paths: str = Form(""),
    docling_refinement: bool = Form(False),
    ocr_model: str = Form("premium"),
    ocr_engine: str = Form("easyocr"),
    auth: tuple[CurrentUser, ApiKey] = Depends(require_api_key_with_key),
    db: Session = Depends(get_db),
):
    """파일을 업로드하고 비용 미리보기를 반환합니다. 포인트는 아직 차감되지 않습니다.

    [Flow: Step 1 (파일 검증) -> Step 2 (단일 PDF/Office/HWP 또는 멀티파일 분석) -> Step 3 (비용 계산)]
    """
    user, api_key = auth
    enforce_rate_limit(request, api_key.id, api_key.rate_limit_rpm)

    if not files:
        raise HTTPException(status_code=400, detail="No files selected")
    if pipeline not in ("vision", "hybrid"):
        pipeline = settings_store.get_setting(db, "default_pipeline") or "vision"
    if ocr_model not in ("basic", "premium"):
        ocr_model = "premium"
    if ocr_engine not in ("tesseract", "easyocr", "rapidocr"):
        ocr_engine = "easyocr"

    max_mb = int(settings_store.get_setting(db, "max_file_mb") or "200")
    total_size = 0
    file_data: List[bytes] = []
    for file in files:
        if not file.filename:
            raise HTTPException(status_code=400, detail="Missing filename")
        ext = Path(file.filename).suffix.lower()
        if ext not in MEDIA_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported file format: {file.filename}")
        data = await file.read()
        total_size += len(data)
        file_data.append(data)

    if total_size > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Total file size exceeds limit (max {max_mb}MB)")

    rel_paths = []
    if relative_paths:
        try:
            rel_paths = json.loads(relative_paths)
            if not isinstance(rel_paths, list):
                rel_paths = []
        except Exception:
            rel_paths = []

    def _relative_path(i: int) -> str:
        if i < len(rel_paths) and rel_paths[i]:
            return rel_paths[i]
        return files[i].filename

    # 단일 파일 업로드 시 파일 유형을 먼저 파악
    is_single_file = len(files) == 1
    single_file_type = "pdf"
    if is_single_file:
        single_file_type = media_loader.detect_file_type(Path(files[0].filename))

    original_filename = files[0].filename if is_single_file else f"{len(files)}_files.zip"

    job = Job(
        user_id=uuid.UUID(user.user_id),
        email=user.email,
        pipeline=pipeline,
        columns=parse_columns(columns),
        prompt=prompt.strip(),
        dpi=dpi,
        use_docling_refinement=docling_refinement,
        ocr_model=ocr_model,
        ocr_engine=ocr_engine,
        original_filename=original_filename,
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    pages = 0
    image_count = 0
    audio_seconds = 0
    video_seconds = 0
    total_files = 0
    try:
        # [Flow: 단일 PDF/Office/HWP — Docling 또는 pyhwp로 페이지 수 추정]
        if is_single_file and single_file_type in media_loader.DOCLING_TYPES:
            data = file_data[0]
            if single_file_type == "pdf":
                pages = len(PdfReader(BytesIO(data)).pages)
            else:
                pages = await _count_pages_with_docling(data, files[0].filename)
            total_files = 1
            storage_path = supabase_client.upload_input(BytesIO(data), files[0].filename, job.id)
            job.pdf_storage_path = storage_path
            job.file_type = single_file_type
        elif is_single_file and single_file_type in media_loader.HWP_TYPES:
            # [Flow: 단일 HWP/HWPX — pyhwp로 페이지 수 추정]
            data = file_data[0]
            suffix = Path(files[0].filename).suffix
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(data)
                tmp_path = Path(tmp.name)
            try:
                pages = await asyncio.to_thread(hwp_converter.get_page_count, tmp_path)
            except Exception as e:
                logger.warning(f"[hwp-page-count] {files[0].filename} 실패: {e}")
                pages = 1
            finally:
                tmp_path.unlink(missing_ok=True)
            total_files = 1
            storage_path = supabase_client.upload_input(BytesIO(data), files[0].filename, job.id)
            job.pdf_storage_path = storage_path
            job.file_type = single_file_type
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                extracted: list[Path] = []
                for i, (file, data) in enumerate(zip(files, file_data)):
                    rel_path = _relative_path(i)
                    if archive_handler.is_archive(file.filename):
                        archive_dest = tmp_path / f"extracted_{rel_path}"
                        archive_dest.mkdir(parents=True, exist_ok=True)
                        extracted.extend(archive_handler.extract_all_recursive(file.filename, data, archive_dest))
                    else:
                        file_path = tmp_path / rel_path
                        file_path.parent.mkdir(parents=True, exist_ok=True)
                        file_path.write_bytes(data)
                        extracted.append(file_path)

                for fp in extracted:
                    ftype = media_loader.detect_file_type(fp)
                    if ftype in media_loader.DOCLING_TYPES:
                        try:
                            if ftype == "pdf":
                                pages += len(PdfReader(fp).pages)
                            else:
                                pages += await _count_pages_with_docling(fp.read_bytes(), fp.name)
                        except Exception:
                            pass
                        total_files += 1
                    elif ftype in media_loader.HWP_TYPES:
                        try:
                            pages += await asyncio.to_thread(hwp_converter.get_page_count, fp)
                        except Exception:
                            pass
                        total_files += 1
                    elif ftype == "image":
                        image_count += 1
                        total_files += 1
                    elif ftype == "audio":
                        audio_seconds += media_loader.get_media_duration_seconds(fp)
                        total_files += 1
                    elif ftype == "video":
                        video_seconds += media_loader.get_media_duration_seconds(fp)
                        total_files += 1
                    elif ftype == "markdown":
                        # [Flow: markdown 파일은 페이지/미디어 비용 없이 total_files에만 카운트 — 텍스트가 그대로 결과]
                        total_files += 1

                job.total_files = total_files
                job.media_duration_seconds = audio_seconds + video_seconds
                job.extracted_files = [
                    {"path": str(p.relative_to(tmp_path)), "type": media_loader.detect_file_type(p), "size": p.stat().st_size}
                    for p in extracted
                ]

                if len(files) == 1:
                    storage_path = supabase_client.upload_input(job.id, file_data[0], files[0].filename)
                    job.pdf_storage_path = storage_path
                    job.file_type = "archive" if archive_handler.is_archive(files[0].filename) else "mixed"
                else:
                    zip_path = tmp_path / f"{job.id}.zip"
                    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                        for i, (file, data) in enumerate(zip(files, file_data)):
                            zf.writestr(_relative_path(i), data)
                    storage_path = supabase_client.upload_input(job.id, zip_path.read_bytes(), zip_path.name, "application/zip")
                    job.pdf_storage_path = storage_path
                    job.file_type = "mixed"

        max_pages = int(settings_store.get_setting(db, "max_pages") or "2000")
        if pages > max_pages:
            db.delete(job)
            db.commit()
            raise HTTPException(status_code=413, detail=f"Too many pages (max {max_pages})")

        job.total_pages = pages
        db.commit()
    except HTTPException:
        raise
    except Exception as e:
        db.delete(job)
        db.commit()
        raise HTTPException(status_code=502, detail=f"File processing failed: {e}")

    has_media = audio_seconds > 0 or video_seconds > 0
    if has_media and ocr_model == "basic":
        ocr_model = "premium"
        job.ocr_model = "premium"
        db.commit()

    docling_refinement_pages = pages if docling_refinement else 0
    cost = points_service.calculate_cost(
        db, pages=pages, image_count=image_count, audio_seconds=audio_seconds,
        video_seconds=video_seconds, docling_refinement_pages=docling_refinement_pages,
        ocr_model=ocr_model,
    )
    _log_api_usage(
        db, api_key, uuid.UUID(user.user_id), "/api/v1/jobs/upload", 200, points_spent=0, job_id=job.id,
        client_ip=request.client.host if request.client else "",
    )
    return {
        "job_id": job.id,
        "status": job.status,
        "file_type": job.file_type,
        "total_pages": pages,
        "total_files": total_files,
        "media_duration_seconds": audio_seconds + video_seconds,
        "docling_refinement": docling_refinement,
        "docling_refinement_pages": docling_refinement_pages,
        "ocr_model": ocr_model,
        "ocr_engine": ocr_engine,
        "has_media": has_media,
        "cost": cost,
        "balance": user.points_balance,
    }


@router.post("/{job_id}/confirm")
def confirm_job(
    request: Request,
    job_id: str,
    auth: tuple[CurrentUser, ApiKey] = Depends(require_api_key_with_key),
    db: Session = Depends(get_db),
):
    """작업을 승인하고 포인트를 차감한 후 Celery worker에 큐잉합니다."""
    user, api_key = auth
    enforce_rate_limit(request, api_key.id, api_key.rate_limit_rpm)

    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "pending":
        raise HTTPException(status_code=400, detail="Job already processed or cancelled")

    db_user = db.get(User, job.user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    pages = job.total_pages
    image_count = 0
    audio_seconds = 0
    video_seconds = 0
    for info in job.extracted_files or []:
        ftype = info.get("type", "")
        if ftype == "image":
            image_count += 1
        elif ftype == "audio":
            audio_seconds += info.get("duration", 0)
        elif ftype == "video":
            video_seconds += info.get("duration", 0)
    # 단일 PDF/Office/HWP 문서는 extracted_files가 없고 file_type으로 판단
    if job.file_type in media_loader.DOCLING_TYPES or job.file_type in media_loader.HWP_TYPES:
        image_count = 0
        audio_seconds = 0
        video_seconds = 0

    ocr_model = job.ocr_model or "premium"
    docling_refinement_pages = pages if job.use_docling_refinement else 0
    cost = points_service.calculate_cost(
        db, pages=pages, image_count=image_count, audio_seconds=audio_seconds,
        video_seconds=video_seconds, docling_refinement_pages=docling_refinement_pages,
        ocr_model=ocr_model,
    )
    try:
        points_service.spend_points(db, db_user, cost["points"], f"API 작업: {job.original_filename}")
    except ValueError as e:
        raise HTTPException(status_code=402, detail=str(e))

    job.cost_points = cost["points"]
    job.status = "queued"
    db.commit()

    run_job.delay(job.id)

    add_daily_spent_points(api_key.id, cost["points"])
    _log_api_usage(
        db, api_key, uuid.UUID(user.user_id), "/api/v1/jobs/confirm", 200,
        points_spent=cost["points"], job_id=job.id,
        client_ip=request.client.host if request.client else "",
    )
    return {"job_id": job.id, "status": job.status, "remaining_points": db_user.points_balance}


@router.get("/{job_id}")
def get_job(
    request: Request,
    job_id: str,
    auth: tuple[CurrentUser, ApiKey] = Depends(require_api_key_with_key),
    db: Session = Depends(get_db),
):
    """작업 상태를 조회합니다."""
    user, api_key = auth
    enforce_rate_limit(request, api_key.id, api_key.rate_limit_rpm)
    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_summary(job)


@router.get("")
def list_jobs(
    request: Request,
    auth: tuple[CurrentUser, ApiKey] = Depends(require_api_key_with_key),
    db: Session = Depends(get_db),
    limit: int = 100,
):
    """사용자의 작업 목록을 반환합니다."""
    user, api_key = auth
    enforce_rate_limit(request, api_key.id, api_key.rate_limit_rpm)
    rows = db.execute(
        select(Job).where(Job.user_id == uuid.UUID(user.user_id)).order_by(Job.created_at.desc()).limit(limit)
    ).scalars().all()
    return [_job_summary(j) for j in rows]


def _get_markdown_content(job: Job) -> str:
    """편집된 마크다운이 있으면 사용하고, 없으면 원본 마크다운을 다운로드한다."""
    client = supabase_client.get_service_client()
    if job.result_edited_md_storage_path:
        return client.storage.from_("results").download(job.result_edited_md_storage_path).decode("utf-8")
    if job.result_md_storage_path:
        return client.storage.from_("results").download(job.result_md_storage_path).decode("utf-8")
    return ""


def _ensure_xlsx_basic_bundle(job: Job, db: Session) -> int:
    """CSV/XLSX 기본 변환 번들을 한 번 수행한다. 이미 변환된 경우 0을 반환한다."""
    if job.result_xlsx_basic_storage_path and job.result_csv_storage_path:
        return 0
    db_user = db.get(User, job.user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    units = job.total_pages if job.total_pages else (job.total_files or 1)
    cost = units * 1
    try:
        points_service.spend_points(db, db_user, cost, f"API Excel 기본변환: {job.original_filename}")
    except ValueError as e:
        raise HTTPException(status_code=402, detail=str(e))
    markdown = _get_markdown_content(job)
    if not markdown.strip():
        raise HTTPException(status_code=400, detail="No markdown result to convert")
    with tempfile.TemporaryDirectory() as tmpdir:
        xlsx_path = Path(tmpdir) / "result.xlsx"
        csv_path = Path(tmpdir) / "result.csv"
        office_converter.markdown_to_xlsx_basic(markdown, xlsx_path)
        office_converter.markdown_to_csv_basic(markdown, csv_path)
        xlsx_storage_path = supabase_client.upload_office_result(job.id, xlsx_path, "xlsx")
        csv_storage_path = supabase_client.upload_office_result(job.id, csv_path, "csv")
    job.result_xlsx_basic_storage_path = xlsx_storage_path
    job.result_xlsx_storage_path = xlsx_storage_path  # 하위 호환
    job.result_csv_storage_path = csv_storage_path
    job.xlsx_basic_converted = True
    db.commit()
    return cost


@router.get("/{job_id}/download")
def download_job(
    request: Request,
    job_id: str,
    type: str = "xlsx",
    auth: tuple[CurrentUser, ApiKey] = Depends(require_api_key_with_key),
    db: Session = Depends(get_db),
):
    """완료된 작업의 결과 파일 다운로드용 signed URL을 반환합니다."""
    user, api_key = auth
    enforce_rate_limit(request, api_key.id, api_key.rate_limit_rpm)

    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "done":
        raise HTTPException(status_code=400, detail="Only completed jobs can be downloaded")

    # csv/xlsx 기본 변환은 동일한 번들로 처리; advanced는 별도 경로 사용
    type = convert_format_alias(type)
    points_spent = 0
    if type in ("csv_basic", "xlsx_basic"):
        points_spent = _ensure_xlsx_basic_bundle(job, db)

    path_map = {
        "csv_basic": job.result_csv_storage_path,
        "md": job.result_edited_md_storage_path or job.result_md_storage_path,
        "xlsx_basic": job.result_xlsx_basic_storage_path,
        "xlsx_advanced": job.result_xlsx_advanced_storage_path,
        "docx": job.result_docx_storage_path,
        "pptx": job.result_pptx_storage_path,
    }
    path = path_map.get(type)
    if not path:
        raise HTTPException(status_code=404, detail="Result file not found")

    try:
        url = supabase_client.get_signed_download_url(path, bucket="results", expires_in=3600)
        add_daily_spent_points(api_key.id, points_spent)
        _log_api_usage(
            db, api_key, uuid.UUID(user.user_id), "/api/v1/jobs/download", 200, job_id=job.id,
            points_spent=points_spent,
            client_ip=request.client.host if request.client else "",
        )
        return {"download_url": url}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to generate download URL: {e}")


@router.post("/{job_id}/convert")
def convert_job(
    request: Request,
    job_id: str,
    payload: dict = Body(...),
    auth: tuple[CurrentUser, ApiKey] = Depends(require_api_key_with_key),
    db: Session = Depends(get_db),
):
    """마크다운 결과를 office 파일로 변환합니다. xlsx 변환은 추가 비용이 발생합니다."""
    user, api_key = auth
    enforce_rate_limit(request, api_key.id, api_key.rate_limit_rpm)

    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "done":
        raise HTTPException(status_code=400, detail="Only completed jobs can be converted")

    fmt = convert_format_alias(str(payload.get("format", "")).lower())
    if fmt not in ("xlsx_basic", "csv_basic", "xlsx_advanced", "docx", "pptx"):
        raise HTTPException(status_code=400, detail="Unsupported conversion format")

    db_user = db.get(User, job.user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Excel 기본/고급 변환: 이미 변환된 파일이 있으면 비용 없이 재사용
    if fmt in ("xlsx_basic", "csv_basic"):
        existing_path = {
            "xlsx_basic": job.result_xlsx_basic_storage_path,
            "csv_basic": job.result_csv_storage_path,
        }.get(fmt)
        if existing_path:
            try:
                url = supabase_client.get_signed_download_url(existing_path, bucket="results", expires_in=3600)
                _log_api_usage(
                    db, api_key, uuid.UUID(user.user_id), "/api/v1/jobs/convert", 200,
                    points_spent=0, job_id=job.id,
                    client_ip=request.client.host if request.client else "",
                )
                return {"download_url": url, "format": fmt, "storage_path": existing_path}
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Failed to generate download URL: {e}")
        points_spent = _ensure_xlsx_basic_bundle(job, db)
        storage_path = {
            "xlsx_basic": job.result_xlsx_basic_storage_path,
            "csv_basic": job.result_csv_storage_path,
        }.get(fmt)
        if not storage_path:
            raise HTTPException(status_code=502, detail="Conversion result path not found")
        try:
            url = supabase_client.get_signed_download_url(storage_path, bucket="results", expires_in=3600)
            add_daily_spent_points(api_key.id, points_spent)
            _log_api_usage(
                db, api_key, uuid.UUID(user.user_id), "/api/v1/jobs/convert", 200,
                points_spent=points_spent, job_id=job.id,
                client_ip=request.client.host if request.client else "",
            )
            return {"download_url": url, "format": fmt, "storage_path": storage_path}
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to generate download URL: {e}")

    if fmt == "xlsx_advanced":
        if job.result_xlsx_advanced_storage_path:
            try:
                url = supabase_client.get_signed_download_url(job.result_xlsx_advanced_storage_path, bucket="results", expires_in=3600)
                _log_api_usage(
                    db, api_key, uuid.UUID(user.user_id), "/api/v1/jobs/convert", 200,
                    points_spent=0, job_id=job.id,
                    client_ip=request.client.host if request.client else "",
                )
                return {"download_url": url, "format": fmt, "storage_path": job.result_xlsx_advanced_storage_path}
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Failed to generate download URL: {e}")
        if job.xlsx_advanced_status == "processing":
            raise HTTPException(status_code=409, detail="Advanced conversion already in progress")
        units = job.total_pages if job.total_pages else (job.total_files or 1)
        cost = units * 3
        try:
            points_service.spend_points(db, db_user, cost, f"API Excel 고급변환: {job.original_filename}")
        except ValueError as e:
            raise HTTPException(status_code=402, detail=str(e))
        job.xlsx_advanced_status = "processing"
        job.xlsx_advanced_refundable = False
        db.commit()
        from ...workers import tasks
        task = tasks.convert_xlsx_advanced.delay(job_id)
        job.result_xlsx_advanced_job_id = task.id
        db.commit()
        add_daily_spent_points(api_key.id, cost)
        _log_api_usage(
            db, api_key, uuid.UUID(user.user_id), "/api/v1/jobs/convert", 200,
            points_spent=cost, job_id=job.id,
            client_ip=request.client.host if request.client else "",
        )
        return {"job_id": task.id, "format": fmt, "status": "processing"}

    # docx / pptx 변환 (기존 동기 방식, 비용 무료)
    existing_path = {
        "docx": job.result_docx_storage_path,
        "pptx": job.result_pptx_storage_path,
    }.get(fmt)
    if existing_path:
        try:
            url = supabase_client.get_signed_download_url(existing_path, bucket="results", expires_in=3600)
            _log_api_usage(
                db, api_key, uuid.UUID(user.user_id), "/api/v1/jobs/convert", 200,
                points_spent=0, job_id=job.id,
                client_ip=request.client.host if request.client else "",
            )
            return {"download_url": url, "format": fmt, "storage_path": existing_path}
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to generate download URL: {e}")

    def _get_markdown() -> str:
        client = supabase_client.get_service_client()
        if job.result_edited_md_storage_path:
            return client.storage.from_("results").download(job.result_edited_md_storage_path).decode("utf-8")
        if job.result_md_storage_path:
            return client.storage.from_("results").download(job.result_md_storage_path).decode("utf-8")
        return ""

    try:
        markdown = _get_markdown()
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / f"result.{fmt}"
            if fmt == "docx":
                office_converter.markdown_to_docx(markdown, out_path)
            else:
                office_converter.markdown_to_pptx(markdown, out_path)
            storage_path = supabase_client.upload_office_result(job_id, out_path, fmt)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Conversion failed: {e}")

    if fmt == "docx":
        job.result_docx_storage_path = storage_path
    else:
        job.result_pptx_storage_path = storage_path
    db.commit()

    try:
        url = supabase_client.get_signed_download_url(storage_path, bucket="results", expires_in=3600)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to generate download URL: {e}")

    _log_api_usage(
        db, api_key, uuid.UUID(user.user_id), "/api/v1/jobs/convert", 200,
        points_spent=0, job_id=job.id,
        client_ip=request.client.host if request.client else "",
    )
    return {"download_url": url, "format": fmt, "storage_path": storage_path}


@router.post("/{job_id}/xlsx-advanced-action")
def xlsx_advanced_action(
    request: Request,
    job_id: str,
    payload: dict = Body(...),
    auth: tuple[CurrentUser, ApiKey] = Depends(require_api_key_with_key),
    db: Session = Depends(get_db),
):
    """Excel 고급 변환 완전 실패 시 재시도 또는 포인트 환불을 처리한다."""
    user, api_key = auth
    enforce_rate_limit(request, api_key.id, api_key.rate_limit_rpm)

    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.xlsx_advanced_status != "error" or not job.xlsx_advanced_refundable:
        raise HTTPException(status_code=400, detail="Not in a refundable or retryable state")

    action = str(payload.get("action", "")).lower()
    if action not in ("retry", "refund"):
        raise HTTPException(status_code=400, detail="Unsupported action")

    db_user = db.get(User, job.user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    units = job.total_pages if job.total_pages else (job.total_files or 1)
    cost = units * 3

    if action == "refund":
        points_service.refund_points(db, db_user, cost, f"API Excel 고급변환 환불: {job.original_filename}")
        job.xlsx_advanced_refundable = False
        db.commit()
        add_daily_spent_points(api_key.id, -cost)
        _log_api_usage(
            db, api_key, uuid.UUID(user.user_id), "/api/v1/jobs/xlsx-advanced-action", 200,
            points_spent=-cost, job_id=job.id,
            client_ip=request.client.host if request.client else "",
        )
        return {"refunded": True, "points": cost}

    job.xlsx_advanced_status = "processing"
    job.xlsx_advanced_refundable = False
    job.result_xlsx_advanced_storage_path = ""
    db.commit()
    from ...workers import tasks
    task = tasks.convert_xlsx_advanced.delay(job_id)
    job.result_xlsx_advanced_job_id = task.id
    db.commit()
    _log_api_usage(
        db, api_key, uuid.UUID(user.user_id), "/api/v1/jobs/xlsx-advanced-action", 200,
        points_spent=0, job_id=job.id,
        client_ip=request.client.host if request.client else "",
    )
    return {"job_id": task.id, "status": "processing"}


@router.post("/{job_id}/action")
def job_action(
    request: Request,
    job_id: str,
    payload: dict = Body(...),
    auth: tuple[CurrentUser, ApiKey] = Depends(require_api_key_with_key),
    db: Session = Depends(get_db),
):
    """문서 파싱 최종 실패 시 재시도 또는 포인트 환불을 처리한다."""
    user, api_key = auth
    enforce_rate_limit(request, api_key.id, api_key.rate_limit_rpm)

    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "error" or not job.refundable:
        raise HTTPException(status_code=400, detail="Not in a refundable or retryable state")

    action = str(payload.get("action", "")).lower()
    if action not in ("retry", "refund"):
        raise HTTPException(status_code=400, detail="Unsupported action")

    db_user = db.get(User, job.user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if action == "refund":
        if job.cost_points > 0:
            points_service.refund_points(db, db_user, job.cost_points, f"API 문서 파싱 환불: {job.original_filename}")
        job.refundable = False
        db.commit()
        add_daily_spent_points(api_key.id, -job.cost_points)
        _log_api_usage(
            db, api_key, uuid.UUID(user.user_id), "/api/v1/jobs/action", 200,
            points_spent=-job.cost_points, job_id=job.id,
            client_ip=request.client.host if request.client else "",
        )
        return {"refunded": True, "points": job.cost_points}

    # retry: 상태 초기화 후 비용 없이 task 재실행
    job.status = "queued"
    job.retry_count = 0
    job.refundable = False
    job.result_csv_storage_path = ""
    job.result_md_storage_path = ""
    db.commit()
    run_job.delay(job_id)
    _log_api_usage(
        db, api_key, uuid.UUID(user.user_id), "/api/v1/jobs/action", 200,
        points_spent=0, job_id=job.id,
        client_ip=request.client.host if request.client else "",
    )
    return {"job_id": job_id, "status": "queued"}


@router.patch("/{job_id}/title")
def rename_job(
    request: Request,
    job_id: str,
    payload: dict = Body(...),
    auth: tuple[CurrentUser, ApiKey] = Depends(require_api_key_with_key),
    db: Session = Depends(get_db),
):
    """Job의 표시 이름(original_filename)을 수정한다.

    [Flow: Step 1 (job 조회 및 소유자 검증) -> Step 2 (새 이름 검증) -> Step 3 (DB 업데이트)]

    모든 상태(pending/processing/done/error)에서 수정 가능하다.
    새 이름은 1~200자여야 한다.
    """
    user, api_key = auth
    enforce_rate_limit(request, api_key.id, api_key.rate_limit_rpm)

    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")

    new_title = str(payload.get("title", "") or "").strip()
    if not new_title:
        raise HTTPException(status_code=400, detail="Title must not be empty")
    if len(new_title) > 200:
        raise HTTPException(status_code=400, detail="Title must be 200 characters or less")

    job.original_filename = _normalize_display_name(new_title)
    db.commit()

    _log_api_usage(
        db, api_key, uuid.UUID(user.user_id), "/api/v1/jobs/title", 200,
        points_spent=0, job_id=job.id,
        client_ip=request.client.host if request.client else "",
    )
    return _job_summary(job)
