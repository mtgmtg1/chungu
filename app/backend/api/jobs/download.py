from __future__ import annotations

import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from ...auth.api_key_auth import require_api_key_or_session
from ...auth.supabase_auth import CurrentUser
from ...core import office_converter, points_service, subscription_service, supabase_client, xlsx_advanced_converter
from ...core.job_helpers import convert_format_alias
from ...db.models import Job, User
from ...db.session import get_db
from ._shared import (
    _ensure_xlsx_basic_bundle,
    _get_markdown_content,
    _is_job_expired,
    _job_summary,
    _require_job_access,
    _require_job_not_expired,
    get_current_user_or_api_key,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api', tags=['jobs'])

@router.get("/jobs/{job_id}/download")
def download_job(
    job_id: str,
    type: str = "xlsx",
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    if job.status != "done":
        raise HTTPException(status_code=400, detail="Only completed jobs can be downloaded")

    type = convert_format_alias(type)

    # csv/xlsx 기본 변환은 동일한 번들로 처리; advanced는 별도 경로 사용
    if type in ("csv_basic", "xlsx_basic"):
        _ensure_xlsx_basic_bundle(job, db)

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
        return {"download_url": url}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Failed to generate download URL: {e}")



@router.post("/jobs/{job_id}/convert")
def convert_job(
    job_id: str,
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    if job.status != "done":
        raise HTTPException(status_code=400, detail="Only completed jobs can be converted")

    fmt = convert_format_alias(str(payload.get("format", "")).lower())
    if fmt not in ("xlsx_basic", "csv_basic", "xlsx_advanced", "docx", "pptx"):
        raise HTTPException(status_code=400, detail="Unsupported conversion format")

    from ..db.models import User

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
                return {"download_url": url, "format": fmt, "storage_path": existing_path}
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Failed to generate download URL: {e}")
        # 번들 생성 (csv + xlsx 동시에 생성되며 1P/페이지 차감)
        _ensure_xlsx_basic_bundle(job, db)
        storage_path = {
            "xlsx_basic": job.result_xlsx_basic_storage_path,
            "csv_basic": job.result_csv_storage_path,
        }.get(fmt)
        if not storage_path:
            raise HTTPException(status_code=502, detail="Conversion result path not found")
        try:
            url = supabase_client.get_signed_download_url(storage_path, bucket="results", expires_in=3600)
            return {"download_url": url, "format": fmt, "storage_path": storage_path}
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to generate download URL: {e}")

    # Excel 고급 변환: 구독 사용량 차감 후 비동기 Celery task로 큐잉
    if fmt == "xlsx_advanced":
        if job.result_xlsx_advanced_storage_path:
            try:
                url = supabase_client.get_signed_download_url(job.result_xlsx_advanced_storage_path, bucket="results", expires_in=3600)
                return {"download_url": url, "format": fmt, "storage_path": job.result_xlsx_advanced_storage_path}
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Failed to generate download URL: {e}")
        if job.xlsx_advanced_status == "processing":
            raise HTTPException(status_code=409, detail="Advanced conversion already in progress")
        units = job.total_pages if job.total_pages else (job.total_files or 1)
        try:
            result = subscription_service.reserve_usage(
                db,
                db_user,
                basic_pages=0,
                premium_pages=units,
            )
        except ValueError as e:
            raise HTTPException(status_code=402, detail=str(e))
        job.xlsx_advanced_status = "processing"
        job.xlsx_advanced_refundable = True
        job.xlsx_advanced_reserved_pages = units
        job.xlsx_advanced_reserved_period_start = datetime.fromisoformat(result["period_start"])
        job.xlsx_advanced_cost_points = result["cost_points"]
        db.commit()
        from ..workers import tasks
        task = tasks.convert_xlsx_advanced.delay(job_id)
        job.result_xlsx_advanced_job_id = task.id
        db.commit()
        return {"job_id": task.id, "format": fmt, "status": "processing"}

    # docx / pptx 변환 (기존 동기 방식, 비용 무료)
    existing_path = {
        "docx": job.result_docx_storage_path,
        "pptx": job.result_pptx_storage_path,
    }.get(fmt)
    if existing_path:
        try:
            url = supabase_client.get_signed_download_url(existing_path, bucket="results", expires_in=3600)
            return {"download_url": url, "format": fmt, "storage_path": existing_path}
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to generate download URL: {e}")

    try:
        markdown = _get_markdown_content(job)
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

    return {"download_url": url, "format": fmt, "storage_path": storage_path}



@router.post("/jobs/{job_id}/save-edited-xlsx")
async def save_edited_xlsx(
    job_id: str,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """사용자가 편집한 xlsx 파일을 업로드하고 Storage 경로를 저장한다."""
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    if job.status != "done":
        raise HTTPException(status_code=400, detail="Only completed jobs can be edited")

    try:
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="Empty file")
        storage_path = supabase_client.upload_edited_xlsx(job_id, data, file.filename or "result_edited.xlsx")
        job.result_edited_xlsx_storage_path = storage_path
        db.commit()
        url = supabase_client.get_signed_download_url(storage_path, bucket="results", expires_in=3600)
        return {"download_url": url, "storage_path": storage_path}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[save_edited_xlsx] 저장 실패: %s", e)
        raise HTTPException(status_code=502, detail=f"Failed to save edited file: {e}")



@router.get("/jobs/{job_id}/edited-xlsx-url")
def get_edited_xlsx_url(
    job_id: str,
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """저장된 편집 xlsx의 signed download URL을 반환한다."""
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    if not job.result_edited_xlsx_storage_path:
        raise HTTPException(status_code=404, detail="No saved edited file")
    try:
        url = supabase_client.get_signed_download_url(job.result_edited_xlsx_storage_path, bucket="results", expires_in=3600)
        return {"download_url": url, "storage_path": job.result_edited_xlsx_storage_path}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to generate download URL: {e}")



@router.post("/jobs/{job_id}/xlsx-advanced-action")
def xlsx_advanced_action(
    job_id: str,
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """Excel 고급 변환 완전 실패 시 재시도 또는 포인트 환불을 처리한다."""
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    if job.xlsx_advanced_status != "error" or not job.xlsx_advanced_refundable:
        raise HTTPException(status_code=400, detail="Not in a refundable or retryable state")

    action = str(payload.get("action", "")).lower()
    if action not in ("retry", "refund"):
        raise HTTPException(status_code=400, detail="Unsupported action")

    from ..db.models import User
    db_user = db.get(User, job.user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    units = job.total_pages if job.total_pages else (job.total_files or 1)

    if action == "refund":
        # 크레딧 환불: 예약 시 기록한 기간을 사용
        period_start = job.xlsx_advanced_reserved_period_start
        subscription_service.release_usage(
            db,
            db_user,
            basic_pages=0,
            premium_pages=job.xlsx_advanced_reserved_pages or units,
            period_start=period_start,
        )
        refunded_points = job.xlsx_advanced_cost_points
        job.xlsx_advanced_refundable = False
        job.xlsx_advanced_reserved_pages = 0
        job.xlsx_advanced_reserved_period_start = None
        job.xlsx_advanced_cost_points = 0
        db.commit()
        return {"refunded": True, "premium_pages": units, "refunded_points": refunded_points}

    # retry: 상태 초기화 후 비용 없이 task 재실행
    job.xlsx_advanced_status = "processing"
    job.xlsx_advanced_refundable = False
    job.result_xlsx_advanced_storage_path = ""
    db.commit()
    from ..workers import tasks
    task = tasks.convert_xlsx_advanced.delay(job_id)
    job.result_xlsx_advanced_job_id = task.id
    db.commit()
    return {"job_id": task.id, "status": "processing"}



@router.get("/download/{token}")
def legacy_download(token: str, type: str = "csv", db: Session = Depends(get_db)):
    job = db.get(Job, token)
    if job is None or job.download_token != token:
        raise HTTPException(status_code=404, detail="Invalid download link")
    if job.expires_at and job.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="Download link expired")

    if type == "csv":
        if not job.result_xlsx_storage_path:
            raise HTTPException(status_code=402, detail="CSV download requires XLSX conversion first")
        path = job.result_csv_storage_path
    else:
        path = job.result_md_storage_path
    if not path:
        # Storage로 이전되지 않은 예전 파일은 로컬 경로 사용
        local = job.result_csv_path if type == "csv" else job.result_md_path
        if not local or not Path(local).exists():
            raise HTTPException(status_code=404, detail="Result file not found")
        base = Path(_normalize_display_name(job.original_filename)).stem or "result"
        ext = "md" if type == "md" else "csv"
        return FileResponse(local, media_type="text/csv" if type == "csv" else "text/markdown", filename=f"{base}.{ext}")

    try:
        url = supabase_client.get_signed_download_url(path, bucket="results", expires_in=3600)
        return {"download_url": url}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Failed to generate download URL: {e}")



@router.get("/dl/{token}")
def email_download_redirect(token: str, type: str = "xlsx_basic", db: Session = Depends(get_db)):
    """이메일 다운로드 버튼용 redirect 엔드포인트 (auth 없이 download_token으로 직접 다운로드)."""
    job = db.get(Job, token)
    if job is None or job.download_token != token:
        raise HTTPException(status_code=404, detail="Invalid download link")
    if job.status != "done":
        raise HTTPException(status_code=400, detail="Only completed jobs can be downloaded")

    fmt = convert_format_alias(type)
    path_map = {
        "csv_basic": job.result_csv_storage_path,
        "md": job.result_edited_md_storage_path or job.result_md_storage_path,
        "xlsx_basic": job.result_xlsx_basic_storage_path,
        "xlsx_advanced": job.result_xlsx_advanced_storage_path,
        "docx": job.result_docx_storage_path,
        "pptx": job.result_pptx_storage_path,
    }
    path = path_map.get(fmt)

    # [Flow: 경로가 비어 있으면 on-demand 변환 (이메일 다운로드 약속 이행)]
    if not path and fmt == "docx":
        path = _generate_office_on_demand(job, fmt, db)

    if not path:
        raise HTTPException(status_code=404, detail="Result file not found")

    try:
        url = supabase_client.get_signed_download_url(path, bucket="results", expires_in=3600)
        return RedirectResponse(url, status_code=302)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Failed to generate download URL: {e}")



def _generate_office_on_demand(job: Job, fmt: str, db: Session) -> str:
    """이메일 다운로드용 on-demand 변환: 마크다운을 DOCX로 변환하여 Storage에 업로드하고 경로를 반환한다.

    매개변수:
        job: 변환할 Job 객체
        fmt: 변환 포맷 ("docx")
        db: 데이터베이스 세션

    반환값:
        Storage 경로 문자열 (변환 실패 시 빈 문자열)
    """
    markdown = _get_markdown_content(job)
    if not markdown.strip():
        return ""
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "result.docx"
            office_converter.markdown_to_docx(markdown, out_path)
            storage_path = supabase_client.upload_office_result(job.id, out_path, "docx")
            job.result_docx_storage_path = storage_path
            db.commit()
            return storage_path
    except Exception as e:
        logger.warning(f"[email_download] on-demand {fmt} 변환 실패 (job={job.id}): {e}")
        return ""



