#!/usr/bin/env python3
# [Flow: Step 1 (API key 인증) -> Step 2 (파일 업로드/비용 계산) -> Step 3 (confirm 시 포인트 차감 + Celery) -> Step 4 (상태 조회/다운로드)]
import json
import tempfile
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
from ...core import archive_handler, media_loader, office_converter, points_service, supabase_client
from ...core.llm_xlsx_converter import convert_markdown_to_xlsx_with_settings
from ...core.prompts import DEFAULT_COLUMNS
from ...core.rate_limit import add_daily_spent_points, enforce_rate_limit
from ...db.models import ApiKey, ApiUsage, Job, User
from ...db.session import get_db
from ... import settings_store
from ...workers.tasks import run_job

router = APIRouter(prefix="/jobs", tags=["jobs"])

MEDIA_EXTENSIONS = {
    ".pdf", ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif",
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma",
    ".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm", ".m4v",
}


def _parse_columns(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return list(DEFAULT_COLUMNS)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list) and parsed:
            return [str(c).strip() for c in parsed if str(c).strip()]
    except json.JSONDecodeError:
        pass
    return [c.strip() for c in raw.split(",") if c.strip()]


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
        "cost_points": job.cost_points,
        "error_log": job.error_log,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "downloadable": job.status == "done",
        "xlsx_converted": bool(job.result_xlsx_storage_path),
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
    auth: tuple[CurrentUser, ApiKey] = Depends(require_api_key_with_key),
    db: Session = Depends(get_db),
):
    """파일을 업로드하고 비용 미리보기를 반환합니다. 포인트는 아직 차감되지 않습니다."""
    user, api_key = auth
    enforce_rate_limit(request, api_key.id, api_key.rate_limit_rpm)

    if not files:
        raise HTTPException(status_code=400, detail="파일을 선택하세요")
    if pipeline not in ("vision", "hybrid"):
        pipeline = settings_store.get_setting(db, "default_pipeline") or "vision"

    max_mb = int(settings_store.get_setting(db, "max_file_mb") or "200")
    total_size = 0
    file_data: List[bytes] = []
    for file in files:
        if not file.filename:
            raise HTTPException(status_code=400, detail="파일 이름이 없습니다")
        ext = Path(file.filename).suffix.lower()
        if ext not in MEDIA_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"지원하지 않는 파일 형식입니다: {file.filename}")
        data = await file.read()
        total_size += len(data)
        file_data.append(data)

    if total_size > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"전체 파일이 너무 큽니다 (최대 {max_mb}MB)")

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

    is_single_pdf = len(files) == 1 and files[0].filename.lower().endswith(".pdf")
    original_filename = files[0].filename if len(files) == 1 else f"{len(files)}_files.zip"

    job = Job(
        user_id=uuid.UUID(user.user_id),
        email=user.email,
        pipeline=pipeline,
        columns=_parse_columns(columns),
        prompt=prompt.strip(),
        dpi=dpi,
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
        if is_single_pdf:
            data = file_data[0]
            pages = len(PdfReader(BytesIO(data)).pages)
            total_files = 1
            storage_path = supabase_client.upload_pdf(job.id, data, files[0].filename)
            job.pdf_storage_path = storage_path
            job.file_type = "pdf"
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
                    if ftype == "pdf":
                        try:
                            pages += len(PdfReader(fp).pages)
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
            raise HTTPException(status_code=413, detail=f"페이지가 너무 많습니다 (최대 {max_pages})")

        job.total_pages = pages
        db.commit()
    except HTTPException:
        raise
    except Exception as e:
        db.delete(job)
        db.commit()
        raise HTTPException(status_code=502, detail=f"파일 처리 실패: {e}")

    cost = points_service.calculate_cost(db, pages=pages, image_count=image_count, audio_seconds=audio_seconds, video_seconds=video_seconds)
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
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    if job.status != "pending":
        raise HTTPException(status_code=400, detail="이미 처리되었거나 취소된 작업입니다")

    db_user = db.get(User, job.user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

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
    if job.file_type == "pdf":
        image_count = 0
        audio_seconds = 0
        video_seconds = 0

    cost = points_service.calculate_cost(db, pages=pages, image_count=image_count, audio_seconds=audio_seconds, video_seconds=video_seconds)
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
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
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


def _ensure_xlsx_bundle(job: Job, db: Session) -> int:
    """CSV/XLSX 다운로드가 가능하도록 xlsx 변환을 한 번 수행한다. 이미 변환된 경우 0을 반환한다."""
    if job.result_xlsx_storage_path:
        return 0
    db_user = db.get(User, job.user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
    units = job.total_pages if job.total_pages else (job.total_files or 1)
    cost = units * 3
    try:
        points_service.spend_points(db, db_user, cost, f"API xlsx 변환: {job.original_filename}")
    except ValueError as e:
        raise HTTPException(status_code=402, detail=str(e))
    markdown = _get_markdown_content(job)
    if not markdown.strip():
        raise HTTPException(status_code=400, detail="변환할 마크다운 결과가 없습니다")
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "result.xlsx"
        convert_markdown_to_xlsx_with_settings(markdown, out_path, db)
        storage_path = supabase_client.upload_office_result(job.id, out_path, "xlsx")
    job.result_xlsx_storage_path = storage_path
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
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    if job.status != "done":
        raise HTTPException(status_code=400, detail="완료된 작업만 다운로드할 수 있습니다")

    # csv와 xlsx는 번들: xlsx 변환 완료 시에만 다운로드, 미변환 시 동일 요금으로 변환 후 제공
    points_spent = 0
    if type in ("csv", "xlsx"):
        points_spent = _ensure_xlsx_bundle(job, db)

    path_map = {
        "csv": job.result_csv_storage_path,
        "md": job.result_edited_md_storage_path or job.result_md_storage_path,
        "xlsx": job.result_xlsx_storage_path,
        "docx": job.result_docx_storage_path,
        "pptx": job.result_pptx_storage_path,
    }
    path = path_map.get(type)
    if not path:
        raise HTTPException(status_code=404, detail="결과 파일이 없습니다")

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
        raise HTTPException(status_code=502, detail=f"다운로드 링크 생성 실패: {e}")


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
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    if job.status != "done":
        raise HTTPException(status_code=400, detail="완료된 작업만 변환할 수 있습니다")

    fmt = str(payload.get("format", "")).lower()
    if fmt not in ("xlsx", "docx", "pptx"):
        raise HTTPException(status_code=400, detail="지원하지 않는 변환 형식입니다")

    db_user = db.get(User, job.user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    # 이미 변환된 파일이 있으면 비용 없이 재사용
    existing_path = {
        "xlsx": job.result_xlsx_storage_path,
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
            raise HTTPException(status_code=502, detail=f"다운로드 링크 생성 실패: {e}")

    points_spent = 0
    if fmt == "xlsx":
        units = job.total_pages if job.total_pages else (job.total_files or 1)
        cost = units * 3
        points_spent = cost
        try:
            points_service.spend_points(db, db_user, cost, f"API xlsx 변환: {job.original_filename}")
        except ValueError as e:
            raise HTTPException(status_code=402, detail=str(e))

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
            if fmt == "xlsx":
                convert_markdown_to_xlsx_with_settings(markdown, out_path, db)
            elif fmt == "docx":
                office_converter.markdown_to_docx(markdown, out_path)
            else:
                office_converter.markdown_to_pptx(markdown, out_path)
            storage_path = supabase_client.upload_office_result(job_id, out_path, fmt)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"변환 실패: {e}")

    if fmt == "xlsx":
        job.result_xlsx_storage_path = storage_path
    elif fmt == "docx":
        job.result_docx_storage_path = storage_path
    else:
        job.result_pptx_storage_path = storage_path
    db.commit()

    try:
        url = supabase_client.get_signed_download_url(storage_path, bucket="results", expires_in=3600)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"다운로드 링크 생성 실패: {e}")

    add_daily_spent_points(api_key.id, points_spent)
    _log_api_usage(
        db, api_key, uuid.UUID(user.user_id), "/api/v1/jobs/convert", 200,
        points_spent=points_spent, job_id=job.id,
        client_ip=request.client.host if request.client else "",
    )
    return {"download_url": url, "format": fmt, "storage_path": storage_path}
