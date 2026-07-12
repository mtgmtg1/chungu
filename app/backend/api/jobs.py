#!/usr/bin/env python3
# [Flow: Step 1 (업로드 -> 파일 유형 감지/압축 해제/Storage 저장) -> Step 2 (비용 계산) -> Step 3 (승인 -> 포인트 차감 + Celery) -> Step 4 (상태 폴링/Storage 다운로드)]
import asyncio
import concurrent.futures
import hashlib
import json
import logging
import math
import re as _re
import tempfile
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, List

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from pypdf import PdfReader
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from .. import settings_store
from ..config import settings
from ..auth.api_key_auth import require_api_key_or_session
from ..auth.supabase_auth import CurrentUser, get_current_admin, get_current_user
from ..celery_app import celery as celery_app


def get_current_user_or_api_key(
    auth: tuple[CurrentUser, Any] = Depends(require_api_key_or_session),
) -> CurrentUser:
    """[Flow: Step 1 (세션 또는 API key 인증) -> Step 2 (CurrentUser만 반환)]

    웹 포털 세션과 API key를 모두 허용하면서 기존 CurrentUser 의존성과 호환되는
    wrapper dependency.
    """
    return auth[0]
from ..core import archive_handler, cache, converter, docling_client, hwp_converter, media_loader, office_converter, pdf_preview_converter, pdf_user_annotator, points_service, subscription_service, supabase_client


logger = logging.getLogger(__name__)
from ..core.prompts import DEFAULT_COLUMNS
from ..db.models import Job, User
from ..db.session import get_db
from ..workers.tasks import run_job, run_job_added_files

router = APIRouter(prefix="/api", tags=["jobs"])

# OCR 업로드 원본 파일 및 변환 결과의 Supabase Storage 보관 기간 (일)
# 보관 기간이 지난 후에는 UI에서만 만료로 표시하고, 실제 Storage 삭제는 별도 아카이빙 스토리지 구성 전까지 수행하지 않는다.
RETENTION_DAYS = 30


def _calculate_work_units(pages: int, image_count: int, audio_seconds: int, video_seconds: int) -> int:
    """시간진행바용 총 작업량을 계산한다.

    매개변수:
        pages: PDF/Office/HWP 문서 페이지 수
        image_count: 이미지 파일 수
        audio_seconds: 오디오 총 재생 시간(초)
        video_seconds: 비디오 총 재생 시간(초)

    반환값:
        총 작업량 단위(1페이지=1, 1이미지=1, 오디오 2초=1, 비디오 1초=1)
    """
    audio_units = math.ceil(audio_seconds / 2) if audio_seconds > 0 else 0
    video_units = video_seconds if video_seconds > 0 else 0
    return max(1, pages + image_count + audio_units + video_units)


def _calculate_media_info(job: Job) -> dict:
    """Job의 extracted_files 및 파일 유형을 기준으로 구독 차감에 사용할 단위를 계산한다.

    반환값:
        {
            "pages": int,
            "image_count": int,
            "audio_seconds": int,
            "video_seconds": int,
            "docling_refinement_pages": int,
        }
    """
    pages = job.total_pages or 0
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
    if job.file_type in media_loader.DOCLING_TYPES or job.file_type in media_loader.HWP_TYPES:
        image_count = 0
        audio_seconds = 0
        video_seconds = 0
    docling_refinement_pages = job.total_pages if job.use_docling_refinement else 0
    return {
        "pages": pages,
        "image_count": image_count,
        "audio_seconds": audio_seconds,
        "video_seconds": video_seconds,
        "docling_refinement_pages": docling_refinement_pages,
    }


def _subscription_units_from_job(job: Job) -> dict:
    """Job 정보를 기반으로 구독 사용량 예약 단위를 계산한다.

    반환값:
        {"basic_pages": int, "premium_pages": int, "media_seconds": int}
    """
    info = _calculate_media_info(job)
    pages = info["pages"]
    image_count = info["image_count"]
    audio_seconds = info["audio_seconds"]
    video_seconds = info["video_seconds"]
    docling_refinement_pages = info["docling_refinement_pages"]
    ocr_model = job.ocr_model or "premium"

    basic_pages = pages + image_count if ocr_model == "basic" else 0
    premium_pages = pages + image_count if ocr_model != "basic" else 0
    premium_pages += docling_refinement_pages
    media_seconds = audio_seconds + video_seconds
    return {
        "basic_pages": basic_pages,
        "premium_pages": premium_pages,
        "media_seconds": media_seconds,
    }


def _subscription_would_exceed_for_model(db: Session, job: Job, db_user: User, ocr_model: str) -> dict:
    """지정한 OCR 모델로 작업을 실행할 때 구독 한도 초과 여부를 반환한다.

    반환값: {"ok": bool, "reason": str|None}
    """
    info = _calculate_media_info(job)
    pages = info["pages"]
    image_count = info["image_count"]
    audio_seconds = info["audio_seconds"]
    video_seconds = info["video_seconds"]
    docling_refinement_pages = info["docling_refinement_pages"]

    basic_pages = pages + image_count if ocr_model == "basic" else 0
    premium_pages = pages + image_count if ocr_model != "basic" else 0
    premium_pages += docling_refinement_pages
    media_seconds = audio_seconds + video_seconds

    check = subscription_service.check_enough(
        db,
        db_user,
        basic_pages=basic_pages,
        premium_pages=premium_pages,
        media_seconds=media_seconds,
    )
    return {"ok": check["ok"], "reason": check["reason"]}


def _job_expires_at(job: Job) -> datetime:
    """작업 생성 시점으로부터 30일 후의 만료 시각을 계산한다."""
    created = job.created_at or datetime.now(timezone.utc)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created + timedelta(days=RETENTION_DAYS)


def _is_job_expired(job: Job) -> bool:
    """작업 생성 시점으로부터 30일이 지났는지 확인한다."""
    return datetime.now(timezone.utc) >= _job_expires_at(job)


def _require_job_not_expired(job: Job) -> None:
    """만료된 작업에 접근할 경우 404 오류를 발생시킨다."""
    if _is_job_expired(job):
        raise HTTPException(status_code=404, detail="Job expired")


def _source_expires_at(job: Job) -> datetime:
    """작업 생성 시점으로부터 30일 후의 만료 시각을 계산한다. (하위 호환)"""
    return _job_expires_at(job)


MEDIA_EXTENSIONS = {
    ".pdf", ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif",
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma",
    ".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm", ".m4v",
    ".docx", ".doc", ".dotx", ".docm",
    ".pptx", ".ppt", ".potx", ".ppsx", ".pptm", ".potm", ".ppsm",
    ".xlsx", ".xls", ".xlsm",
    ".html", ".htm", ".xhtml",
    ".hwp", ".hwpx",
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


async def _count_pages_with_docling(data: bytes, filename: str) -> int:
    """Docling 서비스에 파일을 보내 page_count를 얻는다. 실패하면 1을 반환."""
    if not docling_client.is_enabled():
        return 1
    suffix = Path(filename).suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        _markdown, _images = await asyncio.to_thread(docling_client.convert_file, tmp_path)
        return 1
    except Exception as e:
        logger.warning(f"[docling-page-count] {filename} 실패: {e}")
        return 1
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post("/jobs/upload")
async def upload_job(
    files: List[UploadFile] = File(...),
    pipeline: str = Form("vision"),
    columns: str = Form(""),
    prompt: str = Form(""),
    dpi: int = Form(300),
    relative_paths: str = Form(""),
    docling_refinement: bool = Form(False),
    ocr_model: str = Form("premium"),
    ocr_engine: str = Form("easyocr"),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
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
        columns=_parse_columns(columns),
        prompt=prompt.strip(),
        dpi=dpi,
        use_docling_refinement=docling_refinement,
        ocr_model=ocr_model,
        ocr_engine=ocr_engine,
        original_filename=original_filename,
        file_size=total_size,
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
    file_type = "pdf"

    try:
        if is_single_file and single_file_type in media_loader.DOCLING_TYPES:
            # 단일 PDF/오피스 문서: Docling 서비스로 페이지 수 추정
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
            # 단일 HWP/HWPX 문서: pyhwp로 페이지 수 추정
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
            # 여러 파일/아카이브: 임시 디렉터리에 저장 후 분석
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

                job.total_files = total_files
                job.media_duration_seconds = audio_seconds + video_seconds
                job.extracted_files = [
                    {"path": str(p.relative_to(tmp_path)), "type": media_loader.detect_file_type(p), "size": p.stat().st_size}
                    for p in extracted
                ]

                # Storage에는 원본 파일들을 압축하여 하나로 업로드
                if is_single_file:
                    storage_path = supabase_client.upload_input(BytesIO(file_data[0]), files[0].filename, job.id)
                    job.pdf_storage_path = storage_path
                    job.file_type = "archive" if archive_handler.is_archive(files[0].filename) else "mixed"
                else:
                    zip_path = tmp_path / f"{job.id}.zip"
                    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                        for i, (file, data) in enumerate(zip(files, file_data)):
                            zf.writestr(_relative_path(i), data)
                    storage_path = supabase_client.upload_input(BytesIO(zip_path.read_bytes()), zip_path.name, job.id)
                    job.pdf_storage_path = storage_path
                    job.file_type = "mixed"

        max_pages = int(settings_store.get_setting(db, "max_pages") or "2000")
        if pages > max_pages:
            db.delete(job)
            db.commit()
            raise HTTPException(status_code=413, detail=f"Too many pages (max {max_pages})")

        job.total_pages = pages
        job.total_work_units = _calculate_work_units(pages, image_count, audio_seconds, video_seconds)
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
    user_id = uuid.UUID(user.user_id)
    cost_basic = points_service.calculate_cost(db, pages=pages, image_count=image_count, audio_seconds=audio_seconds, video_seconds=video_seconds, docling_refinement_pages=0, ocr_model="basic", user_id=user_id)
    cost_premium = points_service.calculate_cost(db, pages=pages, image_count=image_count, audio_seconds=audio_seconds, video_seconds=video_seconds, docling_refinement_pages=docling_refinement_pages, ocr_model="premium", user_id=user_id)
    cost = cost_premium if ocr_model == "premium" else cost_basic
    free_remaining = points_service.get_daily_free_remaining(db, user_id)
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
        "cost_basic": cost_basic,
        "cost_premium": cost_premium,
        "free_pages_remaining": free_remaining,
        "balance": user.points_balance,
    }


# ===== TUS Resumable Upload 지원 =====
# [Flow: Step 1 (init: 임시 Job 생성 + Storage 경로 반환) ->
#        Step 2 (프론트엔드에서 TUS 청크 업로드) ->
#        Step 3 (create: Storage 파일 분석 + 비용 계산)]

async def _analyze_extracted_files(extracted: list[Path]) -> tuple:
    """추출된 파일 목록을 분석하여 (pages, image_count, audio_seconds, video_seconds, total_files)를 반환한다."""
    pages = 0
    image_count = 0
    audio_seconds = 0
    video_seconds = 0
    total_files = 0

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

    return pages, image_count, audio_seconds, video_seconds, total_files


@router.post("/jobs/init")
async def init_job(
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """TUS 업로드용 임시 Job을 생성하고 Storage 업로드 경로를 반환한다."""
    files = payload.get("files", [])
    if not files:
        raise HTTPException(status_code=400, detail="No files selected")

    pipeline = payload.get("pipeline", "vision")
    if pipeline not in ("vision", "hybrid"):
        pipeline = settings_store.get_setting(db, "default_pipeline") or "vision"
    ocr_model = payload.get("ocr_model", "premium")
    if ocr_model not in ("basic", "premium"):
        ocr_model = "premium"
    ocr_engine = payload.get("ocr_engine", "easyocr")
    if ocr_engine not in ("tesseract", "easyocr", "rapidocr"):
        ocr_engine = "easyocr"

    for f in files:
        ext = Path(f["name"]).suffix.lower()
        if ext not in MEDIA_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported file format: {f['name']}")

    max_mb = int(settings_store.get_setting(db, "max_file_mb") or "200")
    total_size = sum(f.get("size", 0) for f in files)
    if total_size > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Total file size exceeds limit (max {max_mb}MB)")

    is_single_file = len(files) == 1
    original_filename = files[0]["name"] if is_single_file else f"{len(files)}_files.zip"

    job = Job(
        user_id=uuid.UUID(user.user_id),
        email=user.email,
        pipeline=pipeline,
        columns=_parse_columns(payload.get("columns", "")),
        prompt=payload.get("prompt", "").strip(),
        dpi=payload.get("dpi", 300),
        use_docling_refinement=payload.get("docling_refinement", False),
        ocr_model=ocr_model,
        ocr_engine=ocr_engine,
        original_filename=original_filename,
        status="uploading",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    upload_paths = []
    for f in files:
        safe_name = supabase_client._sanitize_storage_filename(f["name"])
        storage_path = f"{job.id}/{safe_name}"
        upload_paths.append({
            "original": f["name"],
            "storage_name": safe_name,
            "storage_path": storage_path,
            "relative_path": f.get("relative_path", f["name"]),
            "size": f.get("size", 0),
        })

    return {"job_id": job.id, "upload_paths": upload_paths}


@router.post("/jobs/{job_id}/create")
async def create_job(
    job_id: str,
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """TUS 업로드 완료 후 Storage의 파일을 분석하여 비용을 계산한다."""
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    if job.status != "uploading":
        raise HTTPException(status_code=400, detail="Only uploading jobs can be processed")

    files_info = payload.get("files", [])
    if not files_info:
        raise HTTPException(status_code=400, detail="No file information provided")

    is_single_file = len(files_info) == 1
    total_size = sum(f.get("size", 0) for f in files_info)
    pages = 0
    image_count = 0
    audio_seconds = 0
    video_seconds = 0
    total_files = 0

    try:
        job.file_size = total_size
        if is_single_file:
            info = files_info[0]
            storage_path = info["storage_path"]
            filename = info["original_name"]
            data = supabase_client.download_pdf(storage_path).read()
            single_file_type = media_loader.detect_file_type(Path(filename))

            if single_file_type in media_loader.DOCLING_TYPES:
                if single_file_type == "pdf":
                    pages = len(PdfReader(BytesIO(data)).pages)
                else:
                    pages = await _count_pages_with_docling(data, filename)
                total_files = 1
                job.pdf_storage_path = storage_path
                job.file_type = single_file_type
            elif single_file_type in media_loader.HWP_TYPES:
                suffix = Path(filename).suffix
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                    tmp.write(data)
                    tmp_path = Path(tmp.name)
                try:
                    pages = await asyncio.to_thread(hwp_converter.get_page_count, tmp_path)
                except Exception as e:
                    logger.warning(f"[hwp-page-count] {filename} 실패: {e}")
                    pages = 1
                finally:
                    tmp_path.unlink(missing_ok=True)
                total_files = 1
                job.pdf_storage_path = storage_path
                job.file_type = single_file_type
            else:
                with tempfile.TemporaryDirectory() as tmpdir:
                    tmp_path = Path(tmpdir)
                    file_path = tmp_path / info.get("relative_path", filename)
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_bytes(data)
                    extracted: list[Path] = []
                    if archive_handler.is_archive(filename):
                        archive_dest = tmp_path / "extracted"
                        archive_dest.mkdir(parents=True, exist_ok=True)
                        extracted.extend(archive_handler.extract_all_recursive(filename, data, archive_dest))
                    else:
                        extracted.append(file_path)

                    pages, image_count, audio_seconds, video_seconds, total_files = await _analyze_extracted_files(extracted)

                    job.total_files = total_files
                    job.media_duration_seconds = audio_seconds + video_seconds
                    job.extracted_files = [
                        {"path": str(p.relative_to(tmp_path)), "type": media_loader.detect_file_type(p), "size": p.stat().st_size}
                        for p in extracted
                    ]
                    job.pdf_storage_path = storage_path
                    job.file_type = "archive" if archive_handler.is_archive(filename) else "mixed"
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                multi_extracted: list[Path] = []
                for info in files_info:
                    storage_path = info["storage_path"]
                    filename = info["original_name"]
                    rel_path = info.get("relative_path", filename)
                    data = supabase_client.download_pdf(storage_path).read()
                    if archive_handler.is_archive(filename):
                        archive_dest = tmp_path / f"extracted_{rel_path}"
                        archive_dest.mkdir(parents=True, exist_ok=True)
                        multi_extracted.extend(archive_handler.extract_all_recursive(filename, data, archive_dest))
                    else:
                        file_path = tmp_path / rel_path
                        file_path.parent.mkdir(parents=True, exist_ok=True)
                        file_path.write_bytes(data)
                        multi_extracted.append(file_path)

                pages, image_count, audio_seconds, video_seconds, total_files = await _analyze_extracted_files(multi_extracted)

                job.total_files = total_files
                job.media_duration_seconds = audio_seconds + video_seconds
                job.extracted_files = [
                    {"path": str(p.relative_to(tmp_path)), "type": media_loader.detect_file_type(p), "size": p.stat().st_size}
                    for p in multi_extracted
                ]

                zip_path = tmp_path / f"{job.id}.zip"
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for info in files_info:
                        rel_path = info.get("relative_path", info["original_name"])
                        data = supabase_client.download_pdf(info["storage_path"]).read()
                        zf.writestr(rel_path, data)
                storage_path = supabase_client.upload_input(BytesIO(zip_path.read_bytes()), zip_path.name, job.id)
                job.pdf_storage_path = storage_path
                job.file_type = "mixed"

        max_pages = int(settings_store.get_setting(db, "max_pages") or "2000")
        if pages > max_pages:
            db.delete(job)
            db.commit()
            raise HTTPException(status_code=413, detail=f"Too many pages (max {max_pages})")

        job.total_pages = pages
        job.total_work_units = _calculate_work_units(pages, image_count, audio_seconds, video_seconds)
        job.status = "pending"
        db.commit()
    except HTTPException:
        raise
    except Exception as e:
        job.status = "error"
        job.error_log = str(e)
        db.commit()
        raise HTTPException(status_code=502, detail=f"File processing failed: {e}")

    has_media = audio_seconds > 0 or video_seconds > 0
    if has_media and job.ocr_model == "basic":
        job.ocr_model = "premium"
        db.commit()

    docling_refinement_pages = pages if job.use_docling_refinement else 0
    user_id = uuid.UUID(user.user_id)

    # 구독형 요금제: pending 상태에서도 사전 한도 체크
    db_user = db.get(User, user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    units = _subscription_units_from_job(job)
    check_basic = _subscription_would_exceed_for_model(db, job, db_user, "basic")
    check_premium = _subscription_would_exceed_for_model(db, job, db_user, "premium")
    check_current = check_premium if (job.ocr_model or "premium") != "basic" else check_basic
    status = subscription_service.get_subscription_status(db, db_user)

    return {
        "job_id": job.id,
        "status": job.status,
        "file_type": job.file_type,
        "total_pages": pages,
        "total_files": total_files,
        "media_duration_seconds": audio_seconds + video_seconds,
        "docling_refinement": job.use_docling_refinement,
        "docling_refinement_pages": docling_refinement_pages,
        "ocr_model": job.ocr_model or "premium",
        "ocr_engine": job.ocr_engine,
        "has_media": has_media,
        "subscription": {
            "plan": status["plan"],
            "active": status["active"],
            "limits": status["limits"],
            "used": status["used"],
            "remaining": status["remaining"],
            "would_exceed": not check_current["ok"],
            "would_exceed_basic": not check_basic["ok"],
            "would_exceed_premium": not check_premium["ok"],
            "reason": check_current["reason"],
            "reason_basic": check_basic["reason"],
            "reason_premium": check_premium["reason"],
        },
        "cost": {"points": 0, "usd": "$0.00"},
        "cost_basic": {"points": 0, "usd": "$0.00"},
        "cost_premium": {"points": 0, "usd": "$0.00"},
        "free_pages_remaining": 0,
        "balance": 0,
    }


# [Flow: Step 1 (완료된 Job에 파일 추가 — Storage 업로드 경로 할당) -> Step 2 (TUS 업로드) -> Step 3 (confirm-add-files에서 분석 + 증분 변환)]
@router.post("/jobs/{job_id}/init-add-files")
async def init_add_files(
    job_id: str,
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """기존 완료된 Job에 새 파일을 추가하기 위한 Storage 업로드 경로를 반환한다.

    init_job과 달리 새 Job을 생성하지 않고 기존 Job ID를 그대로 사용한다.
    파일 검증(확장자, 크기)은 init_job과 동일하게 수행한다.
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    if job.status != "done":
        raise HTTPException(status_code=400, detail="Only completed jobs can accept additional files")

    files = payload.get("files", [])
    if not files:
        raise HTTPException(status_code=400, detail="No files selected")

    for f in files:
        ext = Path(f["name"]).suffix.lower()
        if ext not in MEDIA_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported file format: {f['name']}")

    max_mb = int(settings_store.get_setting(db, "max_file_mb") or "200")
    total_size = sum(f.get("size", 0) for f in files)
    if total_size > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Total file size exceeds limit (max {max_mb}MB)")

    # [Flow: 파일명에 고유 접미사 추가 — 기존 파일과 같은 이름이어도 Storage 덮어쓰기 방지]
    upload_paths = []
    for f in files:
        safe_name = supabase_client._sanitize_storage_filename(f["name"])
        stem = Path(safe_name).stem
        ext = Path(safe_name).suffix
        unique_suffix = uuid.uuid4().hex[:8]
        unique_name = f"{stem}_{unique_suffix}{ext}"
        storage_path = f"{job.id}/{unique_name}"
        upload_paths.append({
            "original": f["name"],
            "storage_name": unique_name,
            "storage_path": storage_path,
            "relative_path": f.get("relative_path", f["name"]),
            "size": f.get("size", 0),
        })

    return {"job_id": job.id, "upload_paths": upload_paths}


# [Flow: Step 1 (TUS 업로드 완료 후 새 파일 다운로드/분석) -> Step 2 (extracted_files에 새 항목 추가 — status=processing, is_new=true) -> Step 3 (run_job_added_files Celery 태스크 트리거) -> Step 4 (프론트엔드에서 폴링으로 완료 대기)]
@router.post("/jobs/{job_id}/confirm-add-files")
async def confirm_add_files(
    job_id: str,
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """TUS 업로드 완료 후 새 파일들을 분석하여 기존 Job의 extracted_files에 추가하고 증분 변환을 트리거한다.

    기존 결과는 유지되며, 새 파일만 변환되어 결과에 추가된다.
    단일 PDF/DOCX/HWP Job에 파일을 추가하는 경우 file_type을 "mixed"로 전환한다.
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    if job.status != "done":
        raise HTTPException(status_code=400, detail="Only completed jobs can accept additional files")

    files_info = payload.get("files", [])
    if not files_info:
        raise HTTPException(status_code=400, detail="No file information provided")

    # [Flow: Step 1 (새 파일들을 Storage에서 다운로드/압축 해제) -> Step 2 (파일 타입별 분류)]
    new_extracted_infos: list[dict] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        all_extracted: list[Path] = []
        for info in files_info:
            storage_path = info["storage_path"]
            filename = info["original_name"]
            rel_path = info.get("relative_path", filename)
            expected_size = info.get("size", 0)
            data = supabase_client.download_pdf(storage_path).read()
            # [Flow: TUS 업로드 후 Storage 파일 크기 검증 — 클라이언트가 보낸 크기와 다르면 잘못된 파일이 업로드되었을 수 있음]
            actual_size = len(data)
            if expected_size and actual_size != expected_size:
                logger.warning(
                    f"[confirm-add-files:{job.id}] {filename} Storage 크기 불일치: "
                    f"예상={expected_size}, 실제={actual_size}, storage_path={storage_path}"
                )
            if archive_handler.is_archive(filename):
                archive_dest = tmp_path / f"extracted_{rel_path}"
                archive_dest.mkdir(parents=True, exist_ok=True)
                all_extracted.extend(archive_handler.extract_all_recursive(filename, data, archive_dest))
            else:
                file_path = tmp_path / rel_path
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_bytes(data)
                all_extracted.append(file_path)

        # [Flow: Step 3 (새 파일 info 생성 — Storage 업로드 + 타입 감지 + processing 상태)]
        for fp in all_extracted:
            ftype = media_loader.detect_file_type(fp)
            info_entry = {
                "path": str(fp.name),
                "type": ftype,
                "size": fp.stat().st_size,
                "duration": media_loader.get_media_duration_seconds(fp) if ftype in ("audio", "video") else 0,
                "result_markdown": "",
                "status": "processing",
                "is_new": True,
            }
            # 이미지/문서 파일은 Storage에 업로드하여 source_files에서 미리보기 가능하도록 함
            # unique_suffix=True — 기존 파일과 같은 이름이어도 Storage 덮어쓰기 방지
            if ftype == "image":
                try:
                    info_entry["storage_path"] = supabase_client.upload_image(job.id, fp, fp.name)
                except Exception as e:
                    logger.warning(f"[confirm-add-files:{job.id}] 이미지 업로드 실패: {fp.name}: {e}")
            elif ftype in media_loader.DOCLING_TYPES or ftype in media_loader.HWP_TYPES:
                try:
                    info_entry["storage_path"] = supabase_client.upload_input(
                        BytesIO(fp.read_bytes()), fp.name, job.id, unique_suffix=True
                    )
                except Exception as e:
                    logger.warning(f"[confirm-add-files:{job.id}] 문서 업로드 실패: {fp.name}: {e}")
            elif ftype in ("audio", "video"):
                try:
                    info_entry["storage_path"] = supabase_client.upload_input(
                        BytesIO(fp.read_bytes()), fp.name, job.id, unique_suffix=True
                    )
                except Exception as e:
                    logger.warning(f"[confirm-add-files:{job.id}] 미디어 업로드 실패: {fp.name}: {e}")

            # 새 파일의 원본 데이터를 작업 디렉토리에 저장 (Celery 태스크에서 다운로드 대신 사용)
            work_dir = Path(settings.data_dir) / "jobs" / job_id / "added_files"
            work_dir.mkdir(parents=True, exist_ok=True)
            dest_path = work_dir / fp.name
            if not dest_path.exists():
                dest_path.write_bytes(fp.read_bytes())

            new_extracted_infos.append(info_entry)

    # [Flow: Step 4 (기존 extracted_files에 새 항목 병합)]
    existing_files = job.extracted_files or []
    # 단일 PDF/DOCX/HWP Job의 경우 extracted_files가 비어 있을 수 있으므로
    # 기존 원본 파일을 extracted_files에 합성 항목으로 추가
    # 기존 변환 결과 마크다운을 가져와 result_markdown에 채워 넣는다 —
    # 이후 run_job_added_files이 combined markdown을 재생성할 때 기존 파일 내용이 누락되지 않도록 함
    if not existing_files and job.pdf_storage_path and job.file_type in ("pdf", "docx", "hwp"):
        existing_markdown = _extract_single_file_markdown(job)
        existing_files = [{
            "path": job.original_filename or Path(job.pdf_storage_path).name,
            "type": job.file_type,
            "size": job.file_size or 0,
            "duration": 0,
            "result_markdown": existing_markdown,
            "storage_path": job.pdf_storage_path,
        }]

    merged_files = existing_files + new_extracted_infos
    job.extracted_files = merged_files
    # 단일 파일 타입 Job에 새 파일이 추가되면 mixed로 전환
    if job.file_type in ("pdf", "docx", "hwp") and len(merged_files) > 1:
        job.file_type = "mixed"
    flag_modified(job, "extracted_files")
    db.commit()

    # [Flow: Step 5 (구독 사용량 사전 한도 체크)]
    new_pages, new_image_count, new_audio_seconds, new_video_seconds, _ = await _analyze_extracted_files(
        [Path(Path(settings.data_dir) / "jobs" / job_id / "added_files" / info["path"]) for info in new_extracted_infos]
    )
    db_user = db.get(User, job.user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    new_units = _calculate_work_units(new_pages, new_image_count, new_audio_seconds, new_video_seconds)
    if new_units > 0:
        ocr_model = job.ocr_model or "premium"
        basic_pages = new_pages + new_image_count if ocr_model == "basic" else 0
        premium_pages = new_pages + new_image_count if ocr_model != "basic" else 0
        premium_pages += new_pages if job.use_docling_refinement else 0
        media_seconds = new_audio_seconds + new_video_seconds
        try:
            subscription_service.reserve_usage(
                db,
                db_user,
                basic_pages=basic_pages,
                premium_pages=premium_pages,
                media_seconds=media_seconds,
            )
        except ValueError as e:
            raise HTTPException(status_code=402, detail=str(e))

    # [Flow: Step 6 (증분 변환 Celery 태스크 트리거)]
    run_job_added_files.delay(job.id)
    logger.info(f"[confirm-add-files:{job.id}] 증분 변환 태스크 트리거 — 새 파일 {len(new_extracted_infos)}개")

    # preview 캐시 무효화
    cache.invalidate_pattern(f"preview:{job.id}:*")

    return {
        "job_id": job.id,
        "status": job.status,
        "added_files_count": len(new_extracted_infos),
        "total_files": len(merged_files),
    }


@router.put("/jobs/{job_id}")
def update_job(
    job_id: str,
    payload: dict,
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    if job.status != "pending":
        raise HTTPException(status_code=400, detail="Only pending jobs can be modified")

    if "pipeline" in payload and payload["pipeline"] in ("vision", "hybrid"):
        job.pipeline = payload["pipeline"]
    if "ocr_model" in payload and payload["ocr_model"] in ("basic", "premium"):
        job.ocr_model = payload["ocr_model"]
    if "ocr_engine" in payload and payload["ocr_engine"] in ("tesseract", "easyocr", "rapidocr"):
        job.ocr_engine = payload["ocr_engine"]
    if "columns" in payload:
        job.columns = _parse_columns(payload["columns"])
    if "prompt" in payload:
        job.prompt = str(payload["prompt"]).strip()

    # 오디오/비디오가 포함된 작업은 고급 모델로 강제
    has_media = job.media_duration_seconds > 0
    if has_media and job.ocr_model == "basic":
        job.ocr_model = "premium"

    db.commit()
    return _job_summary(job)


@router.post("/jobs/{job_id}/confirm")
def confirm_job(
    job_id: str,
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    if job.status != "pending":
        raise HTTPException(status_code=400, detail="Job already processed or cancelled")

    from ..db.models import User

    db_user = db.get(User, job.user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # 구독형 요금제: 사용량 예약 (멱등성 위해 Job에 예약 기록 저장)
    units = _subscription_units_from_job(job)
    try:
        result = subscription_service.reserve_usage(
            db,
            db_user,
            basic_pages=units["basic_pages"],
            premium_pages=units["premium_pages"],
            media_seconds=units["media_seconds"],
        )
    except ValueError as e:
        raise HTTPException(status_code=402, detail=str(e))

    job.reserved_basic_pages = units["basic_pages"]
    job.reserved_premium_pages = units["premium_pages"]
    job.reserved_media_seconds = units["media_seconds"]
    job.reserved_period_start = datetime.fromisoformat(result["period_start"])
    job.cost_points = 0
    job.status = "queued"
    db.commit()

    run_job.delay(job.id)
    return {"job_id": job.id, "status": job.status, "subscription": result}


@router.get("/jobs")
def list_jobs(
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
    limit: int = 100,
):
    # [Flow: Step 1 (개발 bypass 사용자면 전체 작업 조회) -> Step 2 (일반 사용자면 본인 작업만 필터) -> Step 3 (요약 목록 반환)]
    query = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if not user.is_dev_bypass:
        query = query.where(Job.user_id == uuid.UUID(user.user_id))
    rows = db.execute(query).scalars().all()
    return [_job_summary(j) for j in rows]


@router.get("/jobs/{job_id}")
def get_job(job_id: str, user: CurrentUser = Depends(get_current_user_or_api_key), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    summary = _job_summary(job)
    if job.status == "pending":
        user_id = uuid.UUID(user.user_id)
        pages = job.total_pages or 0
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
        if job.file_type in media_loader.DOCLING_TYPES or job.file_type in media_loader.HWP_TYPES:
            image_count = 0
            audio_seconds = 0
            video_seconds = 0
        docling_refinement_pages = pages if job.use_docling_refinement else 0
        summary["has_media"] = audio_seconds > 0 or video_seconds > 0

        # 구독형 요금제: 잔여 한도 및 초과 여부를 함께 반환
        db_user = db.get(User, user_id)
        if db_user is None:
            raise HTTPException(status_code=404, detail="User not found")
        check_basic = _subscription_would_exceed_for_model(db, job, db_user, "basic")
        check_premium = _subscription_would_exceed_for_model(db, job, db_user, "premium")
        check_current = check_premium if (job.ocr_model or "premium") != "basic" else check_basic
        status = subscription_service.get_subscription_status(db, db_user)
        summary["subscription"] = {
            "plan": status["plan"],
            "active": status["active"],
            "limits": status["limits"],
            "used": status["used"],
            "remaining": status["remaining"],
            "would_exceed": not check_current["ok"],
            "would_exceed_basic": not check_basic["ok"],
            "would_exceed_premium": not check_premium["ok"],
            "reason": check_current["reason"],
            "reason_basic": check_basic["reason"],
            "reason_premium": check_premium["reason"],
        }
        summary["cost_basic"] = {"points": 0, "usd": "$0.00"}
        summary["cost_premium"] = {"points": 0, "usd": "$0.00"}
        summary["free_pages_remaining"] = 0
        summary["cost"] = summary["cost_basic"] if (job.ocr_model or "premium") == "basic" else summary["cost_premium"]
    return summary


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str, user: CurrentUser = Depends(get_current_user_or_api_key), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    try:
        supabase_client.delete_source_files(job)
    except Exception as e:
        logger.warning(f"[delete_job] {job_id} Storage 정리 중 오류 (무시): {e}")
    db.delete(job)
    db.commit()
    return {"deleted": True}


def _delete_original_file(job: Job, source_index: int, db: Session) -> dict:
    """지정한 인덱스의 원본 파일을 Storage와 DB에서 삭제한다.

    [Flow: Step 1 (단일 파일 업로드면 pdf_storage_path 직접 삭제) -> Step 2 (다중 파일이면 extracted_files에서 항목 제거) -> Step 3 (preview 캐시 무효화) -> Step 4 (DB commit 후 결과 반환)]
    """
    files = job.extracted_files or []
    if not files and job.pdf_storage_path and source_index == 0:
        supabase_client.delete_storage_path("pdfs", job.pdf_storage_path)
        job.pdf_storage_path = ""
        cache.invalidate_pattern(f"preview:{job.id}:*")
        db.commit()
        return {"deleted": True, "source_kind": "original", "source_index": 0}
    if source_index >= len(files):
        raise HTTPException(status_code=404, detail="Source file not found")
    info = files[source_index]
    if not isinstance(info, dict):
        raise HTTPException(status_code=500, detail="Invalid source file metadata")
    bucket = info.get("bucket", "pdfs")
    storage_path = info.get("storage_path")
    if storage_path:
        supabase_client.delete_storage_path(bucket, storage_path)
    files.pop(source_index)
    job.extracted_files = files
    cache.invalidate_pattern(f"preview:{job.id}:*")
    db.commit()
    return {"deleted": True, "source_kind": "original", "source_index": source_index}


def _delete_annotation_file(job: Job, source_index: int, db: Session) -> dict:
    """AI 주석 파일을 Storage와 DB에서 삭제한다.

    [Flow: Step 1 (하위 호환 단일 주석이면 result_annotated_pdf_storage_path 삭제)
          -> Step 2 (annotated_pdf_files에서 대상 entry 찾기)
          -> Step 3 (공유 파일을 사용하는 모든 entry의 processing task 취소 및 환불)
          -> Step 4 (공유 Storage 파일 삭제) -> Step 5 (모든 AI 주석 entry 제거 + 상태 초기화)
          -> Step 6 (preview 캐시 무효화)]

    UI에서는 AI 주석 entry들이 하나의 파일로 축소되어 표시되므로, 삭제 시 job의 모든 AI 주석과
    공유 파일을 한 번에 제거한다. source_index는 annotated_pdf_files 내의 position이 아닌
    entry의 index 필드 값이다.
    """
    entries = list(job.annotated_pdf_files or [])
    if not entries and job.result_annotated_pdf_storage_path and source_index == 0:
        supabase_client.delete_storage_path("results", job.result_annotated_pdf_storage_path)
        job.result_annotated_pdf_storage_path = ""
        job.annotated_pdf_files = []
        flag_modified(job, "annotated_pdf_files")
        cache.invalidate_pattern(f"preview:{job.id}:*")
        db.commit()
        return {"deleted": True, "source_kind": "annotation", "source_index": 0}

    # index 필드로 대상 entry 찾기 (position 기반이 아님)
    target_entry = next((e for e in entries if e.get("index") == source_index), None)
    if target_entry is None:
        raise HTTPException(status_code=404, detail="Annotation file not found")

    # 공유 파일을 사용하는 entry들을 모두 삭제. 대상 entry와 동일한 storage_path를
    # 사용하는 entry를 "같은 AI 주석 파일"로 간주한다.
    shared_storage_path = target_entry.get("storage_path")
    shared_annotations_json_path = target_entry.get("annotations_json_storage_path")
    entries_to_remove = [
        e for e in entries
        if not shared_storage_path or e.get("storage_path") == shared_storage_path
    ]
    kept_entries = [e for e in entries if e not in entries_to_remove]

    for entry in entries_to_remove:
        if entry.get("status") == "processing":
            task_id = entry.get("task_id")
            if task_id:
                celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
            if job.user_id and job.annotate_refundable:
                from ..db.models import User
                db_user = db.get(User, job.user_id)
                if db_user and not db_user.is_admin:
                    premium_pages = entry.get("premium_pages", 0)
                    period_start_raw = entry.get("period_start")
                    if premium_pages:
                        subscription_service.release_usage(
                            db,
                            db_user,
                            premium_pages=premium_pages,
                            period_start=datetime.fromisoformat(period_start_raw) if period_start_raw else None,
                        )

    if shared_storage_path:
        supabase_client.delete_storage_path("results", shared_storage_path)
    if shared_annotations_json_path:
        supabase_client.delete_storage_path("results", shared_annotations_json_path)

    job.annotated_pdf_files = kept_entries
    flag_modified(job, "annotated_pdf_files")
    if not kept_entries:
        job.result_annotated_pdf_storage_path = ""
        job.annotate_status = ""
    else:
        job.annotate_status = _overall_annotation_status(kept_entries)
    job.annotate_refundable = False
    cache.invalidate_pattern(f"preview:{job.id}:*")
    db.commit()
    return {"deleted": True, "source_kind": "annotation", "source_index": source_index}


@router.delete("/jobs/{job_id}/source-files/{source_kind}/{source_index}")
def delete_source_file(
    job_id: str,
    source_kind: str,
    source_index: int,
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """결과 페이지의 원본 파일 목록에서 선택한 파일만 Storage와 DB에서 삭제한다.

    [Flow: Step 1 (job 접근 권한 및 만료 상태 검증) -> Step 2 (source_kind 유효성 검사) -> Step 3 (원본/주석 각각의 삭제 헬퍼 호출)]
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    if source_kind not in ("original", "annotation"):
        raise HTTPException(status_code=400, detail="Invalid source kind")
    if source_index < 0:
        raise HTTPException(status_code=400, detail="Invalid source index")
    if source_kind == "original":
        return _delete_original_file(job, source_index, db)
    return _delete_annotation_file(job, source_index, db)


def _convert_format_alias(fmt: str) -> str:
    """구형 'xlsx'/'csv' 요청을 새 기본 변환 포맷으로 매핑한다."""
    return {"xlsx": "xlsx_basic", "csv": "csv_basic"}.get(fmt, fmt)


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

    type = _convert_format_alias(type)

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
        "annotated_pdf": job.result_annotated_pdf_storage_path,
    }
    path = path_map.get(type)
    if not path:
        raise HTTPException(status_code=404, detail="Result file not found")

    try:
        url = supabase_client.get_signed_download_url(path, bucket="results", expires_in=3600)
        return {"download_url": url}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Failed to generate download URL: {e}")


def _get_markdown_content(job: Job) -> str:
    """편집된 마크다운이 있으면 사용하고, 없으면 원본 마크다운을 다운로드한다."""
    client = supabase_client.get_service_client()
    if job.result_edited_md_storage_path:
        data = client.storage.from_("results").download(job.result_edited_md_storage_path)
        return data.decode("utf-8")
    if job.result_md_storage_path:
        data = client.storage.from_("results").download(job.result_md_storage_path)
        return data.decode("utf-8")
    if job.result_md_path and Path(job.result_md_path).exists():
        return Path(job.result_md_path).read_text(encoding="utf-8")
    return ""


# [Flow: Step 1 (기존 마크다운 다운로드) -> Step 2 (파일 구분자 제거) -> Step 3 (순수 마크다운 반환)]
_FILE_MARKER_RE = _re.compile(r"<!--\s*파일\s+\d+\s*-->\s*\n*", _re.IGNORECASE)


def _extract_single_file_markdown(job: Job) -> str:
    """단일 파일 Job의 기존 변환 결과 마크다운에서 파일 구분자를 제거한 순수 내용을 반환한다.

    매개변수:
        job: Job 객체 (result_edited_md_storage_path 또는 result_md_storage_path 사용)

    반환값:
        파일 구분자(`<!-- 파일 N -->`)가 제거된 순수 마크다운 문자열.
        기존 마크다운이 없으면 빈 문자열.

    주요 논리:
        _get_markdown_content로 전체 마크다운을 가져온 뒤, 파일 구분자를 제거한다.
        단일 파일 Job이므로 파일 구분자는 최대 1개이며, 제거 후 남은 내용이
        해당 파일의 result_markdown이 된다.
    """
    try:
        full_markdown = _get_markdown_content(job)
    except Exception as e:
        logger.warning(f"[extract-single-file-markdown:{job.id}] 마크다운 로드 실패: {e}")
        return ""
    if not full_markdown.strip():
        return ""
    # 파일 구분자(`<!-- 파일 N -->`) 제거 후 앞뒤 공백 정리
    cleaned = _FILE_MARKER_RE.sub("", full_markdown).strip()
    return cleaned


_PAGE_MARKER_RE = _re.compile(r"<!--\s*페이지\s*(\d+)\s*-->", _re.IGNORECASE)


def _image_files(job: Job) -> list[tuple[int, dict]]:
    """extracted_files에서 이미지 파일만 순서대로 (page_num, info)로 반환한다."""
    files = job.extracted_files or []
    images: list[tuple[int, dict]] = []
    for idx, info in enumerate(files):
        if isinstance(info, dict) and info.get("type") == "image" and info.get("storage_path"):
            images.append((idx + 1, info))
    return images


def _build_source_file_item(info: dict, idx: int, source_kind: str = "original") -> dict | None:
    """단일 파일에 대한 source_files 항목을 생성한다.

    [Flow: Step 1 (metadata 유효성 검사) -> Step 2 (signed URL 생성) -> Step 3 (source_files 항목 반환, source_kind/source_index 포함)]
    """
    if not isinstance(info, dict) or not info.get("storage_path"):
        return None
    ftype = info.get("type", "")
    if ftype not in ("pdf", "image", "audio", "video", "docx", "hwp", "file"):
        return None
    bucket = info.get("bucket", "pdfs")
    try:
        storage_path = info["storage_path"]
        if ftype in ("pdf", "docx", "hwp"):
            # [Flow: iframe 네이티브 PDF 뷰어는 점진적 렌더링을 지원하므로 저화질 PDF 생성 불필요]
            # 원본 PDF의 서명 URL을 직접 반환 (저화질 생성은 200초+ 블로킹 발생)
            preview_url = supabase_client.get_signed_download_url(storage_path, bucket=bucket, expires_in=3600)
            if not preview_url:
                return None
            item = {
                "name": info.get("path", info.get("storage_path", "")),
                "type": ftype,
                "url": preview_url,
                "storage_path": storage_path,
                "bucket": bucket,
                "page_num": idx + 1,
                "result_markdown": info.get("result_markdown", ""),
                "preview_url": preview_url,
                "source_index": idx,
                "source_kind": source_kind,
                "status": info.get("status", ""),
            }
            # [Flow: 개별 searchable PDF가 있으면 preview_url을 대체 — 텍스트 검색/선택 가능]
            # 각 extracted_files 항목은 자체 searchable_pdf_storage_path를 가질 수 있다.
            # job.searchable_pdf_storage_path (Job 레벨)는 첫 번째 원본 PDF에만 해당하므로
            # 여기서는 개별 항목의 searchable_pdf_storage_path만 사용한다.
            individual_searchable = info.get("searchable_pdf_storage_path")
            if individual_searchable:
                try:
                    searchable_url = supabase_client.get_signed_download_url(
                        individual_searchable, bucket="pdfs", expires_in=3600
                    )
                    if searchable_url:
                        item["preview_url"] = searchable_url
                except Exception as e:
                    logger.warning(f"[source_files] 개별 searchable PDF URL 생성 실패: {e}")
            return item
        # file 타입 (csv, md, xlsx, txt, html 등) — 다운로드용 signed URL만 생성
        if ftype == "file":
            try:
                download_url = supabase_client.get_signed_download_url(storage_path, bucket=bucket, expires_in=3600)
            except Exception:
                return None
            if not download_url:
                return None
            return {
                "name": info.get("path", info.get("storage_path", "")),
                "type": "file",
                "url": download_url,
                "storage_path": storage_path,
                "bucket": bucket,
                "page_num": idx + 1,
                "result_markdown": info.get("result_markdown", ""),
                "source_index": idx,
                "source_kind": source_kind,
                "status": info.get("status", ""),
            }
        # image/audio/video는 원본 signed URL만 필요
        client = supabase_client.create_fresh_service_client()
        url = supabase_client.get_signed_download_url_with_client(client, storage_path, bucket=bucket, expires_in=3600)
        item = {
            "name": info.get("path", info.get("storage_path", "")),
            "type": ftype,
            "url": url,
            "storage_path": storage_path,
            "page_num": idx + 1,
            "result_markdown": info.get("result_markdown", ""),
            "preview_url": url,
            "source_index": idx,
            "source_kind": source_kind,
            "status": info.get("status", ""),
        }
        # 이미지에 searchable PDF가 있으면 preview_url을 대체 (텍스트 검색/선택 가능)
        if ftype == "image":
            searchable_path = info.get("searchable_pdf_storage_path")
            if searchable_path:
                try:
                    searchable_url = supabase_client.get_signed_download_url_with_client(
                        client, searchable_path, bucket="pdfs", expires_in=3600
                    )
                    if searchable_url:
                        item["preview_url"] = searchable_url
                except Exception as e:
                    logger.warning(f"[source_files] 이미지 searchable PDF URL 생성 실패: {e}")
        return item
    except Exception:
        return None


def _source_files(job: Job) -> list[dict]:
    """extracted_files에서 미리보기 가능한 파일 목록과 파일별 파싱 결과를 반환한다.

    단일 PDF/DOCX/HWP 업로드는 extracted_files가 비어 있을 수 있으므로 원본을
    합성 항목으로 추가한다. 생성된 주석 PDF는 results 버킷에서 가져와 파일 탭에
    마지막에 추가한다.

    병렬 처리로 signed URL 생성 시간을 줄인다. max_workers=3으로 제한하여
    Supabase Storage rate limit과 스레드 안전 문제를 완화한다.
    """
    files = job.extracted_files or []
    source_files: list[dict] = []
    if not files and job.pdf_storage_path and job.file_type in ("pdf", "docx", "hwp"):
        # 단일 파일 업로드: extracted_files가 없으므로 원본 파일을 직접 표시
        original_item = _build_source_file_item(
            {
                "path": job.original_filename or Path(job.pdf_storage_path).name,
                "storage_path": job.pdf_storage_path,
                "type": job.file_type,
            },
            0,
            source_kind="original",
        )
        if original_item:
            source_files.append(original_item)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(_build_source_file_item, info, idx, "original") for idx, info in enumerate(files)]
            results = [f.result() for f in futures]
        source_files = [item for item in results if item is not None]

    # [Flow: 원본 PDF에 대한 사용자 주석 JSON URL 설정]
    # 원본 PDF에 내장된 주석이 있으면 clean PDF로 교체하고, 추출한 주석을 JSON 오버레이로
    # 초기화한다. 이렇게 하면 embedpdf가 PDF 내장 주석을 중복 렌더링/저장하는 문제를
    # 방지할 수 있다. docx/hwp는 여기서 PDF로 변환되지 않으므로 제외한다.
    # [Flow: searchable PDF는 첫 번째 원본 PDF에만 적용 — job.searchable_pdf_storage_path는
    # Job 레벨 단일 값이므로, 모든 PDF 항목에 덮어쓰면 새로 추가된 파일이 원본 PDF로 보이는 문제 발생]
    first_original_pdf_index = next(
        (i for i, item in enumerate(source_files)
         if item.get("source_kind") == "original" and item.get("type") == "pdf"),
        None,
    )
    for i, item in enumerate(source_files):
        if item.get("source_kind") != "original" or item.get("type") != "pdf":
            continue
        clean_url, extracted_annotations = _ensure_clean_source_pdf(
            job.id, item.get("storage_path"), item.get("bucket", "pdfs")
        )
        if clean_url:
            item["url"] = clean_url
            item["preview_url"] = clean_url
        if extracted_annotations:
            # [Flow: 파일별 주석 분리 — source_index를 전달하여 해당 파일의 주석 JSON에 저장]
            _initialize_user_annotations_json(job.id, extracted_annotations, item.get("source_index", 0))

        # [Flow: searchable PDF가 있으면 미리보기 URL을 대체 — 첫 번째 원본 PDF에만 적용]
        # 다운로드용 url은 원본 clean PDF를 유지하고, preview_url만 searchable PDF로 변경.
        # 이렇게 하면 사용자는 뷰어에서 텍스트 검색/선택이 가능한 PDF를 보지만,
        # 다운로드는 원본 PDF를 받는다.
        # job.searchable_pdf_storage_path는 단일 PDF Job의 원본에 대한 것이므로,
        # 첫 번째 원본 PDF에만 적용한다. 추가로 업로드된 파일은 _build_source_file_item에서
        # 개별 searchable_pdf_storage_path가 설정된 경우에만 searchable PDF를 사용한다.
        if i == first_original_pdf_index and job.searchable_pdf_storage_path:
            try:
                searchable_url = supabase_client.get_signed_download_url(
                    job.searchable_pdf_storage_path, bucket="pdfs", expires_in=3600
                )
                if searchable_url:
                    item["preview_url"] = searchable_url
            except Exception as e:
                logger.warning(f"[source_files:{job.id}] searchable PDF URL 생성 실패: {e}")

    # [Flow: AI 주석을 원본 PDF 탭에 병합 — 별도 파일 탭을 생성하지 않는다]
    # 병렬 AI 주석 생성은 모두 동일한 공유 파일/annotations.json을 사용하므로,
    # 완료된 주석을 첫 번째 원본 PDF 항목에 annotations_json_url로 부착한다.
    # processing/error 상태는 FAB 위 상태 카드에서만 표시하며, 원본 파일 탭에는
    # 별도 항목을 추가하지 않는다.
    annotated_entries = list(job.annotated_pdf_files or [])
    if not annotated_entries and job.annotate_status == "done" and job.result_annotated_pdf_storage_path:
        # 하위 호환: 목록 컬럼 추가 전에 생성된 단일 주석 PDF
        stem = Path(job.original_filename).stem if job.original_filename else "result"
        annotated_entries = [
            {
                "index": 1,
                "status": "done",
                "storage_path": job.result_annotated_pdf_storage_path,
                "annotations_json_storage_path": None,
                "filename": f"{stem}_annotation1.pdf",
            }
        ]

    shared_annotations_json_path = None
    if annotated_entries:
        annotated_entries = sorted(annotated_entries, key=lambda e: e.get("index", 0))
        # 신규 공유 annotations.json 경로를 사용하는 entry를 우선 선택한다.
        shared_annotations_json_path = next(
            (
                e.get("annotations_json_storage_path")
                for e in annotated_entries
                if e.get("annotations_json_storage_path")
            ),
            None,
        )
        if not shared_annotations_json_path:
            # 하위 호환 또는 초기 상태: 공유 경로로 폴백
            shared_annotations_json_path = f"{job.id}/annotated.annotations.json"

        overall_status = _overall_annotation_status(annotated_entries)
        if overall_status == "done" and shared_annotations_json_path:
            try:
                annotations_json_url = supabase_client.get_signed_download_url(
                    shared_annotations_json_path, bucket="results", expires_in=3600
                )
            except Exception:
                annotations_json_url = None
            if annotations_json_url:
                # 첫 번째 원본 PDF/DOCX/HWP 항목에 주석 JSON URL을 부착한다.
                for item in source_files:
                    if item.get("source_kind") == "original" and item.get("type") in ("pdf", "docx", "hwp"):
                        item["annotations_json_url"] = annotations_json_url
                        break

    # [Flow: 파일별 user_annotations_{source_index}.json이 존재하면 AI 주석과 병합하여 각 파일에 설정]
    # 사용자가 직접 추가/편집한 주석은 파일별로 분리된 user_annotations_{source_index}.json에 저장되며,
    # 여기서 AI 주석 JSON과 병합해 각 원본 탭에서 두 주석을 중복 없이 볼 수 있도록 한다.
    # 파일별 주석 JSON이 없으면 기존 공유 user_annotations.json으로 폴백 (하위 호환).
    for item in source_files:
        if item.get("source_kind") != "original" or item.get("type") not in ("pdf", "docx", "hwp"):
            continue
        file_source_index = item.get("source_index", 0)
        # [Flow: 파일별 주석 JSON 경로 — source_index별로 분리]
        per_file_user_annotations_path = f"{job.id}/user_annotations_{file_source_index}.json"
        # 하위 호환: 파일별 주석 JSON이 없으면 공유 user_annotations.json 사용
        fallback_user_annotations_path = f"{job.id}/user_annotations.json"
        # 파일별 주석 JSON이 존재하는지 확인
        user_annotations_json_path = per_file_user_annotations_path
        try:
            user_annotations_url = supabase_client.get_signed_download_url(
                user_annotations_json_path, bucket="results", expires_in=3600
            )
        except Exception:
            user_annotations_url = None
        # 파일별 주석 JSON이 없으면 공유 user_annotations.json으로 폴백 (첫 번째 파일만)
        if not user_annotations_url and file_source_index == 0:
            user_annotations_json_path = fallback_user_annotations_path
            try:
                user_annotations_url = supabase_client.get_signed_download_url(
                    user_annotations_json_path, bucket="results", expires_in=3600
                )
            except Exception:
                user_annotations_url = None
        if user_annotations_url:
            merged_url = _merge_annotation_jsons(
                job.id, shared_annotations_json_path, user_annotations_json_path
            )
            if merged_url:
                item["annotations_json_url"] = merged_url
    return source_files


def _deduplicate_annotations(annotations: list[dict]) -> list[dict]:
    """[Flow: Step 1 (각 주석의 pageIndex/rect/type/contents 기준 키 생성)
          -> Step 2 (이미 본 키는 제거) -> Step 3 (중복 제거된 목록 반환)]

    EmbedPDF 뷰어에서 exportAnnotations() 시 PDF 내장 주석이 반복 포함되면서
    동일한 pageIndex/rect/type/contents를 가진 주석이 누적되는 경우가 있다.
    이런 중복을 제거해 user_annotations.json이 계속 불어나는 것을 막는다.
    """
    seen: set[str] = set()
    result: list[dict] = []
    for item in annotations:
        if not isinstance(item, dict):
            continue
        a = item.get("annotation") if "annotation" in item else item
        if not isinstance(a, dict):
            continue
        key = json.dumps(
            {
                "pageIndex": a.get("pageIndex"),
                "rect": a.get("rect"),
                "type": a.get("type"),
                "contents": a.get("contents", ""),
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _annotation_id(item: dict) -> str:
    """[Flow: Step 1 (item이 dict인지 확인) -> Step 2 (annotation.id 추출) -> Step 3 (반환)]

    EmbedPDF AnnotationTransferItem에서 주석 ID를 추출한다.
    """
    if not isinstance(item, dict):
        return ""
    if "annotation" in item and isinstance(item["annotation"], dict):
        return item["annotation"].get("id", "")
    return item.get("id", "")


def _merge_annotation_jsons(
    job_id: str,
    ai_annotations_path: str | None,
    user_annotations_path: str,
) -> str | None:
    """[Flow: Step 1 (AI 주석 JSON 다운로드) -> Step 2 (사용자 주석 JSON 다운로드)
          -> Step 3 (위치 기반 중복 제거 후 병합) -> Step 4 (merged_annotations.json 업로드)
          -> Step 5 (signed URL 반환)]

    AI 주석 JSON과 사용자 주석 JSON을 병합하여 원본 PDF 탭에서 한 번에 표시한다.
    동일한 pageIndex/rect/type/contents를 가진 주석은 _deduplicate_annotations로
    하나만 남겨 색이 진해지는 중복 렌더링을 방지한다.
    """
    client = supabase_client.get_service_client()
    merged: list[dict] = []
    if ai_annotations_path:
        try:
            ai_bytes = client.storage.from_("results").download(ai_annotations_path)
            ai_list = json.loads(ai_bytes.decode("utf-8"))
            if isinstance(ai_list, list):
                merged.extend(ai_list)
        except Exception:
            pass
    try:
        user_bytes = client.storage.from_("results").download(user_annotations_path)
        user_list = json.loads(user_bytes.decode("utf-8"))
        if isinstance(user_list, list):
            merged.extend(user_list)
    except Exception:
        pass
    merged = _deduplicate_annotations(merged)
    merged_path = f"{job_id}/merged_annotations.json"
    try:
        client.storage.from_("results").upload(
            merged_path,
            json.dumps(merged, ensure_ascii=False).encode("utf-8"),
            {"content-type": "application/json", "upsert": "true"},
        )
        return supabase_client.get_signed_download_url(
            merged_path, bucket="results", expires_in=3600
        )
    except Exception as e:
        logger.warning(f"[_merge_annotation_jsons] {job_id} 병합 업로드 실패: {e}")
        return None


def _annotation_inner(item: dict) -> dict:
    """EmbedPDF AnnotationTransferItem에서 내부 annotation dict를 추출한다 (평면 dict도 지원)."""
    if not isinstance(item, dict):
        return {}
    if "annotation" in item and isinstance(item["annotation"], dict):
        return item["annotation"]
    return item


def _is_annotation_edited(current: dict, original: dict) -> bool:
    """[Flow: Step 1 (내부 annotation 객체 추출) -> Step 2 (주요 필드 비교) -> Step 3 (변경 여부 반환)]

    사용자가 AI 주석을 편집했는지 확인한다. rect, color, contents, opacity, calloutLine
    필드 중 하나라도 다르면 편집된 것으로 간주한다. 이미 _userEdited가 설정되어 있으면 true.
    """
    cur = _annotation_inner(current)
    orig = _annotation_inner(original)
    if cur.get("_userEdited") or orig.get("_userEdited"):
        return True
    # 주요 필드 비교 — rect, color, contents, opacity, calloutLine
    for field in ("rect", "color", "contents", "opacity", "calloutLine", "strokeColor", "strokeWidth"):
        if cur.get(field) != orig.get(field):
            return True
    return False


def _mark_user_edited(item: dict) -> None:
    """주석 객체에 _userEdited: true 플래그를 설정한다 (내부 annotation dict에 설정)."""
    if "annotation" in item and isinstance(item["annotation"], dict):
        item["annotation"]["_userEdited"] = True
    else:
        item["_userEdited"] = True


def _parse_page_range(raw: str | None, total_pages: int) -> list[int] | None:
    """[Flow: Step 1 (빈 입력 → None 반환하여 전체 페이지 의미) -> Step 2 (콤마로 분할)
          -> Step 3 (각 토큰을 범위 파싱) -> Step 4 (1-based 페이지 번호 집합 반환)]

    "1-5,7,10-12" 형태의 문자열을 1-based 페이지 번호 리스트로 변환한다.
    빈 문자열이나 None이면 None을 반환하며, 이는 "전체 페이지"를 의미한다.
    범위가 total_pages를 초과하면 잘라내고, 역순 범위(예: 5-3)도 허용한다.

    Args:
        raw: 사용자 입력 페이지 범위 문자열 (예: "1-5,7,10-12")
        total_pages: PDF 전체 페이지 수 (초과 범위 클램프용)

    Returns:
        정렬된 1-based 페이지 번호 리스트. 빈 입력이면 None (전체 페이지 의미).
    """
    if not raw or not raw.strip():
        return None
    pages: set[int] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            parts = token.split("-", 1)
            try:
                start = int(parts[0])
                end = int(parts[1])
            except (ValueError, IndexError):
                continue
            if start > end:
                start, end = end, start
            for p in range(start, end + 1):
                if 1 <= p <= total_pages:
                    pages.add(p)
        else:
            try:
                p = int(token)
            except ValueError:
                continue
            if 1 <= p <= total_pages:
                pages.add(p)
    if not pages:
        return None
    return sorted(pages)


def _overall_annotation_status(entries: list[dict]) -> str:
    """[Flow: Step 1 (processing entry 존재 확인) -> Step 2 (error entry 존재 확인)
          -> Step 3 (전체 상태 문자열 반환)]

    AI 주석 entry 목록에서 전체 상태를 결정한다. processing이 하나라도 있으면 processing,
    없으면서 error가 하나라도 있으면 error, 모두 done이거나 비어있으면 done을 반환한다.
    """
    if any(e.get("status") == "processing" for e in entries):
        return "processing"
    if any(e.get("status") == "error" for e in entries):
        return "error"
    return "done" if entries else ""


def _ensure_clean_source_pdf(
    job_id: str,
    storage_path: str,
    bucket: str = "pdfs",
) -> tuple[str | None, list[dict] | None]:
    """[Flow: Step 1 (clean PDF signed URL 생성 시도) -> Step 2 (없으면 원본 PDF 다운로드)
          -> Step 3 (내장 주석 추출) -> Step 4 (주석이 있으면 clean PDF 생성/업로드)
          -> Step 5 (preview 캐시 무효화 후 clean PDF URL과 추출한 주석 반환)]

    원본 PDF에 내장된 주석이 있으면, 주석을 제거한 clean PDF를 생성하고 추출한 주석을
    EmbedPDF JSON 형식으로 반환한다. clean PDF가 이미 존재하면 URL만 반환한다.

    clean PDF 경로는 storage_path를 기반으로 고유하게 생성하여, 같은 Job의 여러 PDF 파일이
    서로 덮어쓰지 않도록 한다.
    """
    # [Flow: storage_path 기반 고유 clean PDF 경로 생성 — 여러 파일이 같은 Job에 있어도 충돌 방지]
    path_hash = hashlib.md5(storage_path.encode("utf-8")).hexdigest()[:12]
    clean_storage_path = f"{job_id}/clean_{path_hash}.pdf"

    # Step 1: clean PDF가 이미 존재하는지 download()로 확인한다.
    # get_signed_download_url()은 존재하지 않는 객체라도 signed URL을 반환하므로
    # clean PDF가 실제로 없는데도 있다고 판단하는 문제가 발생한다.
    try:
        client = supabase_client.get_service_client()
        client.storage.from_(bucket).download(clean_storage_path)
        url = supabase_client.get_signed_download_url(clean_storage_path, bucket=bucket, expires_in=3600)
        if url:
            return url, None
    except Exception as e:
        logger.info(f"[_ensure_clean_source_pdf] {job_id} clean.pdf 아직 없음(생성 필요): {e}")

    # Step 2: 원본 PDF 다운로드
    try:
        client = supabase_client.get_service_client()
        pdf_bytes = client.storage.from_(bucket).download(storage_path)
    except Exception as e:
        logger.warning(f"[_ensure_clean_source_pdf] {job_id} 원본 PDF 다운로드 실패: {e}")
        return None, None

    # Step 3: 내장 주석 추출
    try:
        annotations = pdf_user_annotator.extract_pdf_annotations(pdf_bytes)
    except Exception as e:
        logger.warning(f"[_ensure_clean_source_pdf] {job_id} 주석 추출 실패: {e}")
        return None, None

    if not annotations:
        return None, []

    # Step 4: clean PDF 생성 및 업로드
    try:
        clean_bytes = pdf_user_annotator.remove_pdf_annotations(pdf_bytes)
        client = supabase_client.get_service_client()
        client.storage.from_(bucket).upload(
            clean_storage_path,
            clean_bytes,
            {"content-type": "application/pdf", "upsert": "true"},
        )
        url = supabase_client.get_signed_download_url(clean_storage_path, bucket=bucket, expires_in=3600)
        # clean PDF가 새로 생겼으므로 preview 캐시를 무효화해 source_files 응답이 갱신되도록 한다.
        cache.invalidate_pattern(f"preview:{job_id}:*")
        return url, annotations
    except Exception as e:
        logger.warning(f"[_ensure_clean_source_pdf] {job_id} clean PDF 업로드 실패: {e}")
        return None, None


def _initialize_user_annotations_json(job_id: str, annotations: list[dict], source_index: int = 0) -> None:
    """[Flow: Step 1 (기존 주석 JSON 다운로드) -> Step 2 (기존 주석과 병합)
          -> Step 3 (중복 제거) -> Step 4 (저장 및 preview 캐시 무효화)]

    원본 PDF에서 추출한 내장 주석을 파일별 주석 JSON에 초기값으로 저장한다.
    이미 파일이 존재하면 기존 주석과 병합한 뒤 중복을 제거하여 덮어쓴다.

    매개변수:
        job_id: Job ID
        annotations: 초기화할 주석 목록
        source_index: 파일 인덱스 (해당 인덱스의 user_annotations_{source_index}.json에 저장)
    """
    # [Flow: 파일별 주석 분리 — source_index별로 분리된 JSON에 저장]
    storage_path = f"{job_id}/user_annotations_{source_index}.json"
    try:
        client = supabase_client.get_service_client()
        try:
            existing_bytes = client.storage.from_("results").download(storage_path)
            existing = json.loads(existing_bytes.decode("utf-8"))
            if isinstance(existing, list):
                annotations = existing + annotations
        except Exception:
            pass
        annotations = _deduplicate_annotations(annotations)
        client.storage.from_("results").upload(
            storage_path,
            json.dumps(annotations, ensure_ascii=False).encode("utf-8"),
            {"content-type": "application/json", "upsert": "true"},
        )
        cache.invalidate_pattern(f"preview:{job_id}:*")
    except Exception as e:
        logger.warning(f"[_initialize_user_annotations_json] {job_id} 초기 주석 저장 실패: {e}")


def _detect_source_type(job: Job) -> str | None:
    """원본 파일의 실제 유형에 따라 source_type을 반환한다."""
    if not job.pdf_storage_path:
        return None
    files = job.extracted_files or []
    if len(files) == 1:
        ftype = files[0].get("type", "")
        if ftype in ("audio", "video", "docx", "hwp"):
            return ftype
    # 파일명 확장자 기준 fallback
    ext = Path(job.pdf_storage_path).suffix.lower()
    if ext in (".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"):
        return "audio"
    if ext in (".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm", ".m4v"):
        return "video"
    if ext in (".docx", ".doc"):
        return "docx"
    if ext in (".hwp", ".hwpx"):
        return "hwp"
    return "pdf"


def _require_job_access(job: Job | None, user: CurrentUser) -> None:
    """[Flow: Step 1 (job 존재 여부 확인) -> Step 2 (개발 bypass 사용자면 통과) -> Step 3 (소유자 불일치 시 404)]
    작업 접근 권한을 검증한다. 개발 bypass 사용자는 소유자와 관계없이 모든 작업에 접근 가능하다.
    """
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if user.is_dev_bypass:
        return
    if str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")


def _split_markdown_by_pages(markdown: str) -> list[tuple[int, str]]:
    """페이지 마커를 기준으로 마크다운을 분할한다."""
    matches = list(_PAGE_MARKER_RE.finditer(markdown))
    if not matches:
        content = markdown.strip()
        if content:
            return [(1, content)]
        return []
    pages: list[tuple[int, str]] = []
    for idx, match in enumerate(matches):
        page_num = int(match.group(1))
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown)
        content = markdown[start:end].strip()
        if content:
            pages.append((page_num, content))
    return pages


def _ensure_xlsx_basic_bundle(job: Job, db: Session) -> None:
    """CSV/XLSX 기본 변환 번들을 한 번 수행한다. 이미 변환된 경우 아무것도 하지 않는다.
    구독형 요금제: basic_pages 단위로 사용량을 차감한다."""
    if job.result_xlsx_basic_storage_path and job.result_csv_storage_path:
        return
    from ..db.models import User
    db_user = db.get(User, job.user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    units = job.total_pages if job.total_pages else (job.total_files or 1)
    try:
        subscription_service.reserve_usage(
            db,
            db_user,
            basic_pages=units,
            premium_pages=0,
            media_seconds=0,
        )
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


def _preview_cache_key(job_id: str, start_page: int, end_page: int | None) -> str:
    """preview_job 응답을 캐싱하기 위한 Redis 키를 생성한다."""
    return f"preview:{job_id}:{start_page}:{end_page or 'last'}"


@router.get("/jobs/{job_id}/preview")
def preview_job(
    job_id: str,
    start_page: int = Query(1, ge=1, description="시작 페이지 번호"),
    end_page: int | None = Query(None, ge=1, description="종료 페이지 번호(미지정 시 마지막 페이지)"),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """완료된 작업의 마크다운 결과를 페이지 단위로 조회한다."""
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    if not job.result_md_storage_path and not job.result_edited_md_storage_path:
        detail = f"Result file not ready (status={job.status}, md_path={job.result_md_storage_path or '-'}, edited_path={job.result_edited_md_storage_path or '-'}, error_log={job.error_log or '-'}"
        raise HTTPException(status_code=400, detail=detail)

    cache_key = _preview_cache_key(job_id, start_page, end_page)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        markdown = _get_markdown_content(job)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to generate preview: {e}")

    pages = _split_markdown_by_pages(markdown)
    page_nums = [num for num, _ in pages]
    last_page = max(page_nums) if page_nums else 1
    effective_end = end_page if end_page is not None else last_page
    if effective_end < start_page:
        effective_end = start_page

    # [Flow: 페이지 마커를 포함하여 partial_markdown 구성 — FlowViewer 노드 클릭 시 PDF 페이지 스크롤 연동에 필요]
    # _split_markdown_by_pages는 마커를 제거한 content만 반환하므로, 여기서 마커를 다시 붙여 복원.
    # SimpleEditor/MarkdownPreview는 페이지 마커를 숨김 처리하므로 사용자에게 보이지 않음.
    selected = [(num, content) for num, content in pages if start_page <= num <= effective_end]
    partial_markdown = "\n\n---\n\n".join(
        f"<!-- 페이지 {num} -->\n\n{content}" for num, content in selected
    )

    source_url = None
    source_type = None
    image_urls: list[str] = []
    if job.pdf_storage_path:
        try:
            source_type = _detect_source_type(job)
            # [Flow: iframe 네이티브 PDF 뷰어는 점진적 렌더링을 지원하므로 저화질 PDF 생성 불필요]
            # 원본 PDF의 서명 URL을 직접 반환 (저화질 생성은 200초+ 블로킹 발생)
            source_url = supabase_client.get_signed_download_url(job.pdf_storage_path, bucket="pdfs", expires_in=3600)
        except Exception:
            pass

    images = _image_files(job)
    if images:
        source_type = "images"
        for page_num, info in images:
            if start_page <= page_num <= effective_end:
                try:
                    url = supabase_client.get_signed_download_url(info["storage_path"], bucket="pdfs", expires_in=3600)
                    image_urls.append(url)
                except Exception:
                    pass

    source_files = _source_files(job)
    result = {
        "job": _job_summary(job),
        "markdown": partial_markdown,
        "source_url": source_url,
        "source_type": source_type,
        "image_urls": image_urls,
        "source_files": source_files,
        "start_page": start_page,
        "end_page": effective_end,
        "last_page": last_page,
    }
    cache.set(cache_key, result, ttl_seconds=300)
    return result


@router.get("/jobs/{job_id}/preview/pages")
def preview_job_pages(
    job_id: str,
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """완료된 작업의 페이지 목록 메타데이터를 반환한다."""
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    if not job.result_md_storage_path and not job.result_edited_md_storage_path:
        detail = f"Result file not ready (status={job.status}, md_path={job.result_md_storage_path or '-'}, edited_path={job.result_edited_md_storage_path or '-'}, error_log={job.error_log or '-'}"
        raise HTTPException(status_code=400, detail=detail)

    try:
        markdown = _get_markdown_content(job)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to generate preview: {e}")

    pages = _split_markdown_by_pages(markdown)
    images = _image_files(job)
    image_map = {page_num: info for page_num, info in images}
    out_pages = []
    for num, content in pages:
        entry: dict = {"page_num": num, "preview": content[:200].replace("\n", " ").strip()}
        info = image_map.get(num)
        if info:
            try:
                entry["image_url"] = supabase_client.get_signed_download_url(info["storage_path"], bucket="pdfs", expires_in=3600)
            except Exception:
                pass
        out_pages.append(entry)

    return {
        "job": _job_summary(job),
        "total_pages": len(pages),
        "pages": out_pages,
    }


@router.put("/jobs/{job_id}/result")
def save_result_markdown(
    job_id: str,
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    if job.status != "done":
        raise HTTPException(status_code=400, detail="Only completed jobs can be edited")

    file_markdowns = payload.get("file_markdowns")
    if isinstance(file_markdowns, list):
        files = job.extracted_files or []
        for idx, info in enumerate(files):
            if idx < len(file_markdowns):
                info["result_markdown"] = str(file_markdowns[idx])
        job.extracted_files = files
        markdown = converter.build_combined_file_markdowns(
            [info.get("result_markdown", "") for info in files]
        )
    else:
        markdown = str(payload.get("markdown", ""))

    with tempfile.TemporaryDirectory() as tmpdir:
        edited_path = Path(tmpdir) / "result_edited.md"
        edited_path.write_text(markdown, encoding="utf-8")
        try:
            storage_path = supabase_client.upload_result(
                job_id, edited_md_path=edited_path
            ).get("edited_md", "")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to save edited markdown: {e}")
    job.result_edited_md_storage_path = storage_path
    job.result_edited_md_path = ""
    db.commit()
    cache.invalidate_pattern(f"preview:{job_id}:*")
    return {"job_id": job.id, "saved": True, "storage_path": storage_path}


@router.patch("/jobs/{job_id}/result/pages/{page_num}")
def save_result_page(
    job_id: str,
    page_num: int,
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """특정 페이지의 마크다운만 갱신하고 전체 편집 마크다운을 다시 저장한다."""
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    if job.status != "done":
        raise HTTPException(status_code=400, detail="Only completed jobs can be edited")

    new_content = str(payload.get("markdown", "")).strip()
    try:
        markdown = _get_markdown_content(job)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to load markdown: {e}")

    pages = _split_markdown_by_pages(markdown)
    if not pages:
        raise HTTPException(status_code=400, detail="No pages found")
    target_idx = next((idx for idx, (num, _) in enumerate(pages) if num == page_num), None)
    if target_idx is None:
        raise HTTPException(status_code=404, detail="Page not found")

    pages[target_idx] = (page_num, new_content)
    updated = "\n\n---\n\n".join([f"<!-- 페이지 {num} -->\n\n{content}" for num, content in pages])

    with tempfile.TemporaryDirectory() as tmpdir:
        edited_path = Path(tmpdir) / "result_edited.md"
        edited_path.write_text(updated, encoding="utf-8")
        try:
            storage_path = supabase_client.upload_result(
                job_id, edited_md_path=edited_path
            ).get("edited_md", "")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to save edited markdown: {e}")
    job.result_edited_md_storage_path = storage_path
    job.result_edited_md_path = ""
    db.commit()
    cache.invalidate_pattern(f"preview:{job_id}:*")
    return {"job_id": job.id, "page_num": page_num, "saved": True, "storage_path": storage_path}


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

    fmt = _convert_format_alias(str(payload.get("format", "")).lower())
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
                media_seconds=0,
            )
        except ValueError as e:
            raise HTTPException(status_code=402, detail=str(e))
        job.xlsx_advanced_status = "processing"
        job.xlsx_advanced_refundable = True
        job.xlsx_advanced_reserved_pages = units
        job.xlsx_advanced_reserved_period_start = datetime.fromisoformat(result["period_start"])
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
        # 구독 사용량 환불: 예약 시 기록한 기간을 사용
        period_start = job.xlsx_advanced_reserved_period_start
        subscription_service.release_usage(
            db,
            db_user,
            basic_pages=0,
            premium_pages=job.xlsx_advanced_reserved_pages or units,
            media_seconds=0,
            period_start=period_start,
        )
        job.xlsx_advanced_refundable = False
        job.xlsx_advanced_reserved_pages = 0
        job.xlsx_advanced_reserved_period_start = None
        db.commit()
        return {"refunded": True, "premium_pages": job.xlsx_advanced_reserved_pages or units}

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



@router.post("/jobs/{job_id}/annotate")
def annotate_job(
    job_id: str,
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """원본 PDF/이미지에서 조건에 맞는 텍스트 요소(표 행, 단락, 제목 등)를 하이라이트/여백 주석으로 표시한다 (xlsx_advanced와 동일한 과금/큐잉 패턴)."""
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    if job.status != "done":
        raise HTTPException(status_code=400, detail="Only completed jobs can be annotated")

    instruction = str(payload.get("instruction", "")).strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction is required")
    mode = str(payload.get("mode", "highlight")).lower()
    if mode not in ("highlight", "margin_note", "both"):
        raise HTTPException(status_code=400, detail="Unsupported mode")
    comment_mode = str(payload.get("comment_mode", "user_text")).lower()
    if comment_mode not in ("user_text", "llm_summary"):
        raise HTTPException(status_code=400, detail="Unsupported comment_mode")
    advanced = bool(payload.get("advanced", False))

    # [Flow: 페이지 범위 파싱 — 빈 값이면 None(전체 페이지), 지정하면 해당 페이지만 처리]
    # 프론트에서 기본값으로 현재 보고 있는 페이지를 전달하므로, 명시적으로 "전체"를 원할 때만
    # page_range를 비워 보내지 않는다. 과금은 지정한 페이지 수만큼 계산한다.
    total_pages = job.total_pages if job.total_pages else (job.total_files or 1)
    raw_page_range = payload.get("page_range")
    if raw_page_range is not None and not isinstance(raw_page_range, str):
        # 리스트/숫자 형태로 오면 문자열로 정규화
        if isinstance(raw_page_range, list):
            raw_page_range = ",".join(str(p) for p in raw_page_range)
        else:
            raw_page_range = str(raw_page_range)
    page_range = _parse_page_range(raw_page_range, total_pages)
    page_range_count = len(page_range) if page_range else total_pages

    # 동일한 instruction/mode/comment_mode/advanced/page_range로 이미 생성된 주석이 있으면 재사용
    existing = next(
        (
            e
            for e in (job.annotated_pdf_files or [])
            if e.get("instruction") == instruction
            and e.get("mode") == mode
            and e.get("comment_mode") == comment_mode
            and bool(e.get("advanced", False)) == advanced
            and e.get("page_range") == page_range
        ),
        None,
    )
    if not existing and job.result_annotated_pdf_storage_path and job.annotate_instruction == instruction and job.annotate_mode == mode and job.annotate_comment_mode == comment_mode:
        # 하위 호환: 목록 컬럼 추가 전에 생성된 단일 주석 PDF
        stem = Path(job.original_filename).stem if job.original_filename else "result"
        existing = {
            "storage_path": job.result_annotated_pdf_storage_path,
            "filename": f"{stem}_annotation1.pdf",
        }
    if existing:
        try:
            url = supabase_client.get_signed_download_url(existing["storage_path"], bucket="results", expires_in=3600)
            return {"download_url": url, "status": "done", "storage_path": existing["storage_path"], "filename": existing.get("filename")}
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to generate download URL: {e}")

    # 비회원 사용자 체크
    if job.user_id is None:
        raise HTTPException(status_code=402, detail="구독이 필요한 기능입니다.")

    from ..db.models import User
    db_user = db.get(User, job.user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # 관리자 체크 (무제한 사용)
    if db_user.is_admin:
        # 관리자는 구독 체크 없이 바로 처리
        units = page_range_count
        job.annotate_instruction = instruction
        job.annotate_mode = mode
        job.annotate_comment_mode = comment_mode
        job.annotate_advanced = advanced
        job.annotate_status = "processing"
        job.annotate_refundable = False  # 관리자는 환불 불필요
        job.annotate_reserved_pages = 0  # 관리자는 예약 불필요
        job.annotate_reserved_period_start = None
    else:
        # 일반 사용자는 구독 체크 — 지정한 페이지 수만큼만 과금
        units = page_range_count
        # 고급주석은 페이지당 Vision LLM 호출 → 일반 주석보다 비용이 높음. credits를 2배로 사용.
        if advanced:
            units *= 2
        try:
            sub_result = subscription_service.reserve_usage(
                db,
                db_user,
                basic_pages=0,
                premium_pages=units,
                media_seconds=0,
            )
        except ValueError as e:
            raise HTTPException(status_code=402, detail=str(e))

        job.annotate_instruction = instruction
        job.annotate_mode = mode
        job.annotate_comment_mode = comment_mode
        job.annotate_advanced = advanced
        job.annotate_status = "processing"
        job.annotate_refundable = True
        job.annotate_reserved_pages = units
        job.annotate_reserved_period_start = datetime.fromisoformat(sub_result["period_start"])

    # 구독 체크 통과 후 원자적으로 다음 인덱스를 할당한다.
    # 인덱스는 병렬 run 추적 및 재시도 식별용이며, 실제 파일은 job당 하나의 공유 파일을 사용한다.
    # 동시 쓰기 충돌은 worker에서 SELECT FOR UPDATE로 잠근 뒤 annotations.json을 병합하여 해결한다.
    idx_result = db.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(annotated_pdf_next_index=Job.annotated_pdf_next_index + 1)
        .returning(Job.annotated_pdf_next_index)
    )
    db.commit()
    annotation_index = idx_result.scalar()
    if not annotation_index:
        raise HTTPException(status_code=500, detail="주석 인덱스 할당에 실패했습니다.")

    shared_storage_path = f"{job.id}/annotated.pdf"
    shared_annotations_json_path = f"{job.id}/annotated.annotations.json"

    # processing entry를 annotated_pdf_files에 추가한다.
    # 동시 쓰기 안전성을 위해 SELECT FOR UPDATE로 행을 잠근다.
    locked_job = db.execute(
        select(Job).where(Job.id == job_id).with_for_update()
    ).scalar_one()
    annotated_files = list(locked_job.annotated_pdf_files or [])
    processing_entry = {
        "index": annotation_index,
        "status": "processing",
        "instruction": instruction,
        "mode": mode,
        "comment_mode": comment_mode,
        "advanced": advanced,
        "page_range": page_range,
        "storage_path": shared_storage_path,
        "annotations_json_storage_path": shared_annotations_json_path,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    annotated_files.append(processing_entry)
    locked_job.annotated_pdf_files = annotated_files
    flag_modified(locked_job, "annotated_pdf_files")
    db.commit()

    from ..workers import tasks
    task = tasks.annotate_pdf_job.delay(
        job_id, instruction, mode, comment_mode, advanced=advanced,
        annotation_index=annotation_index, page_range=page_range,
    )
    try:
        locked_job = db.execute(
            select(Job).where(Job.id == job_id).with_for_update()
        ).scalar_one()
        files = list(locked_job.annotated_pdf_files or [])
        for e in files:
            if e.get("index") == annotation_index:
                e["task_id"] = task.id
                e["premium_pages"] = units
                e["period_start"] = (
                    job.annotate_reserved_period_start.isoformat()
                    if job.annotate_reserved_period_start
                    else None
                )
                break
        locked_job.annotated_pdf_files = files
        flag_modified(locked_job, "annotated_pdf_files")
        locked_job.annotate_job_id = task.id
        db.commit()
    except Exception:
        # task ID 저장 실패 시 Celery 작업을 취소하고 entry를 error 상태로 변경한다
        db.rollback()
        celery_app.control.revoke(task.id, terminate=True, signal="SIGTERM")
        locked_job = db.execute(
            select(Job).where(Job.id == job_id).with_for_update()
        ).scalar_one()
        files = list(locked_job.annotated_pdf_files or [])
        for e in files:
            if e.get("index") == annotation_index:
                e["status"] = "error"
                e["recovery_notes"] = [{"reason": "작업 큐잉 실패: task ID 저장 에러"}]
                break
        locked_job.annotated_pdf_files = files
        flag_modified(locked_job, "annotated_pdf_files")
        locked_job.annotate_status = _overall_annotation_status(files)
        locked_job.annotate_refundable = False
        db.commit()
        raise HTTPException(status_code=500, detail="주석 작업 큐잉에 실패했습니다. 다시 시도해주세요.")
    return {"job_id": task.id, "status": "processing", "annotation_index": annotation_index}


@router.post("/jobs/{job_id}/annotate-action")
def annotate_action(
    job_id: str,
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """PDF 주석 생성 실패 시 재시도를 처리한다 (구독제이므로 환불은 제공하지 않는다).

    annotation_index로 지정한 실패 entry를 재시도한다.
    annotation_index가 0이면 공유 AI 주석 파일에 포함된 모든 error entry를 재시도한다.
    UI에서 AI 주석이 하나로 축소되어 표시되므로, 사용자가 재시도 버튼을 누르면
    모든 실패한 run을 한 번에 재시도할 수 있다.
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)

    # 비회원 사용자 체크
    if job.user_id is None:
        raise HTTPException(status_code=402, detail="구독이 필요한 기능입니다.")

    action = str(payload.get("action", "")).lower()
    if action != "retry":
        raise HTTPException(status_code=400, detail="Unsupported action")

    annotation_index = int(payload.get("annotation_index", 0))

    from ..db.models import User
    db_user = db.get(User, job.user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    entries = list(job.annotated_pdf_files or [])
    if annotation_index == 0:
        # 공유 AI 주석 파일에서 실패한 모든 run을 재시도한다.
        error_entries = [e for e in entries if e.get("status") == "error"]
        if not error_entries:
            raise HTTPException(status_code=400, detail="No error annotations to retry")
    else:
        # 하위 호환: 특정 인덱스의 entry만 재시도한다.
        entry = next((e for e in entries if e.get("index") == annotation_index), None)
        if entry is None:
            raise HTTPException(status_code=404, detail="Annotation entry not found")
        if entry.get("status", "done") != "error":
            raise HTTPException(status_code=400, detail="Not in a retryable state")
        error_entries = [entry]

    # 공유 annotations.json에서 재시도 대상 run의 기존 주석을 제거한다.
    # 이렇게 하면 worker가 재생성한 주석이 중복 추가되는 것을 방지한다.
    shared_annotations_json_path = error_entries[0].get("annotations_json_storage_path")
    retry_indices = {e.get("index") for e in error_entries}
    if shared_annotations_json_path and retry_indices:
        try:
            client = supabase_client.get_service_client()
            existing_bytes = client.storage.from_("results").download(shared_annotations_json_path)
            existing = json.loads(existing_bytes.decode("utf-8"))
            if isinstance(existing, list):
                filtered = [
                    a for a in existing
                    if not any(_annotation_id(a).startswith(f"backend-{idx}-") for idx in retry_indices)
                ]
                client.storage.from_("results").upload(
                    shared_annotations_json_path,
                    json.dumps(filtered, ensure_ascii=False).encode("utf-8"),
                    {"content-type": "application/json", "upsert": "true"},
                )
        except Exception:
            logger.exception(f"[annotate_action] {job_id} 공유 주석 JSON 정리 실패")

    for entry in error_entries:
        entry["status"] = "processing"
        entry["recovery_notes"] = []
    job.annotated_pdf_files = entries
    flag_modified(job, "annotated_pdf_files")
    job.annotate_status = "processing"
    job.annotate_refundable = False
    db.commit()

    from ..workers import tasks
    tasks_to_track: list[tuple[dict, Any]] = []
    for entry in error_entries:
        idx = entry.get("index")
        task = tasks.annotate_pdf_job.delay(
            job_id,
            entry.get("instruction", ""),
            entry.get("mode", "highlight"),
            entry.get("comment_mode", "user_text"),
            advanced=bool(entry.get("advanced", False)),
            annotation_index=idx,
            page_range=entry.get("page_range"),
        )
        tasks_to_track.append((entry, task))

    try:
        locked_job = db.execute(
            select(Job).where(Job.id == job_id).with_for_update()
        ).scalar_one()
        files = list(locked_job.annotated_pdf_files or [])
        for entry, task in tasks_to_track:
            idx = entry.get("index")
            for e in files:
                if e.get("index") == idx:
                    e["task_id"] = task.id
                    break
        locked_job.annotated_pdf_files = files
        flag_modified(locked_job, "annotated_pdf_files")
        locked_job.annotate_job_id = tasks_to_track[0][1].id if tasks_to_track else ""
        db.commit()
    except Exception:
        db.rollback()
        for _, task in tasks_to_track:
            celery_app.control.revoke(task.id, terminate=True, signal="SIGTERM")
        locked_job = db.execute(
            select(Job).where(Job.id == job_id).with_for_update()
        ).scalar_one()
        files = list(locked_job.annotated_pdf_files or [])
        for entry, _ in tasks_to_track:
            idx = entry.get("index")
            for e in files:
                if e.get("index") == idx:
                    e["status"] = "error"
                    e["recovery_notes"] = [{"reason": "재시도 작업 큐잉 실패: task ID 저장 에러"}]
                    break
        locked_job.annotated_pdf_files = files
        flag_modified(locked_job, "annotated_pdf_files")
        locked_job.annotate_status = _overall_annotation_status(files)
        locked_job.annotate_refundable = False
        db.commit()
        raise HTTPException(status_code=500, detail="주석 재시도 큐잉에 실패했습니다. 다시 시도해주세요.")

    if tasks_to_track:
        return {
            "job_id": tasks_to_track[0][1].id,
            "status": "processing",
            "annotation_index": annotation_index,
            "retried_indices": [e.get("index") for e, _ in tasks_to_track],
        }
    return {"job_id": None, "status": "processing", "annotation_index": annotation_index}


@router.post("/jobs/{job_id}/annotate-cancel")
def cancel_annotation_job(
    job_id: str,
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (job 조회 및 권한 확인) -> Step 2 (annotation_index로 entry 찾기)
          -> Step 3 (Celery task 강제 종료) -> Step 4 (entry 제거) -> Step 5 (상태 갱신)]

    진행 중인 AI 주석 작업을 취소한다. 이미 실행 중인 Celery worker를
    terminate=True로 강제 종료하여 LLM 호출도 함께 중단한다.
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)

    annotation_index = payload.get("annotation_index")
    if not isinstance(annotation_index, int):
        raise HTTPException(status_code=400, detail="annotation_index is required")

    locked_job = db.execute(
        select(Job).where(Job.id == job_id).with_for_update()
    ).scalar_one()
    files = list(locked_job.annotated_pdf_files or [])
    target_entry = next((e for e in files if e.get("index") == annotation_index), None)
    if target_entry is None:
        raise HTTPException(status_code=404, detail="Annotation job not found")
    if target_entry.get("status") != "processing":
        raise HTTPException(status_code=400, detail="Only processing jobs can be cancelled")

    task_id = target_entry.get("task_id")
    if task_id:
        try:
            celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
        except Exception as e:
            logger.warning(f"[annotate-cancel] {job_id} task {task_id} revoke 실패: {e}")

    files = [e for e in files if e.get("index") != annotation_index]
    locked_job.annotated_pdf_files = files
    flag_modified(locked_job, "annotated_pdf_files")
    locked_job.annotate_status = _overall_annotation_status(files)
    locked_job.annotate_refundable = False
    db.commit()
    cache.invalidate_pattern(f"preview:{job_id}:*")
    return {"cancelled": True, "annotation_index": annotation_index}


@router.post("/jobs/{job_id}/annotate-edit")
def annotate_edit_job_endpoint(
    job_id: str,
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (job 조회 및 권한 확인) -> Step 2 (instruction/page_range 파싱)
          -> Step 3 (구독 체크 및 원자적 인덱스 할당) -> Step 4 (processing entry 추가)
          -> Step 5 (Celery annotate_edit_job 큐잉) -> Step 6 (task_id 저장)]

    기존 AI 주석의 색상/코멘트를 사용자 instruction에 맞게 LLM으로 재편집한다.
    지정한 페이지 범위의 기존 AI 주석만 편집 대상이며, 사용자 수동 편집 주석은 보존된다.
    과금은 지정한 페이지 수만큼 계산한다 (기존 annotate와 동일 단가).
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    if job.status != "done":
        raise HTTPException(status_code=400, detail="Only completed jobs can be annotated")

    instruction = str(payload.get("instruction", "")).strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction is required")

    # [Flow: 페이지 범위 파싱 — 빈 값이면 None(전체 페이지), 지정하면 해당 페이지만 편집]
    total_pages = job.total_pages if job.total_pages else (job.total_files or 1)
    raw_page_range = payload.get("page_range")
    if raw_page_range is not None and not isinstance(raw_page_range, str):
        if isinstance(raw_page_range, list):
            raw_page_range = ",".join(str(p) for p in raw_page_range)
        else:
            raw_page_range = str(raw_page_range)
    page_range = _parse_page_range(raw_page_range, total_pages)
    page_range_count = len(page_range) if page_range else total_pages

    # 비회원 사용자 체크
    if job.user_id is None:
        raise HTTPException(status_code=402, detail="구독이 필요한 기능입니다.")

    from ..db.models import User
    db_user = db.get(User, job.user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # 관리자 체크 (무제한 사용)
    if db_user.is_admin:
        units = page_range_count
        job.annotate_status = "processing"
        job.annotate_refundable = False
        job.annotate_reserved_pages = 0
        job.annotate_reserved_period_start = None
    else:
        # 일반 사용자는 구독 체크 — 지정한 페이지 수만큼만 과금 (편집은 생성과 동일 단가)
        units = page_range_count
        try:
            sub_result = subscription_service.reserve_usage(
                db,
                db_user,
                basic_pages=0,
                premium_pages=units,
                media_seconds=0,
            )
        except ValueError as e:
            raise HTTPException(status_code=402, detail=str(e))
        job.annotate_status = "processing"
        job.annotate_refundable = True
        job.annotate_reserved_pages = units
        job.annotate_reserved_period_start = datetime.fromisoformat(sub_result["period_start"])

    # 원자적으로 다음 인덱스를 할당한다 (entry 추적용).
    idx_result = db.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(annotated_pdf_next_index=Job.annotated_pdf_next_index + 1)
        .returning(Job.annotated_pdf_next_index)
    )
    db.commit()
    annotation_index = idx_result.scalar()
    if not annotation_index:
        raise HTTPException(status_code=500, detail="주석 인덱스 할당에 실패했습니다.")

    shared_storage_path = f"{job.id}/annotated.pdf"
    shared_annotations_json_path = f"{job.id}/annotated.annotations.json"

    # processing entry를 annotated_pdf_files에 추가한다 (edit: true 플래그로 편집 run임을 표시).
    locked_job = db.execute(
        select(Job).where(Job.id == job_id).with_for_update()
    ).scalar_one()
    annotated_files = list(locked_job.annotated_pdf_files or [])
    processing_entry = {
        "index": annotation_index,
        "status": "processing",
        "instruction": instruction,
        "edit": True,
        "page_range": page_range,
        "storage_path": shared_storage_path,
        "annotations_json_storage_path": shared_annotations_json_path,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    annotated_files.append(processing_entry)
    locked_job.annotated_pdf_files = annotated_files
    flag_modified(locked_job, "annotated_pdf_files")
    db.commit()

    from ..workers import tasks
    task = tasks.annotate_edit_job.delay(
        job_id, instruction, page_range, annotation_index,
    )
    try:
        locked_job = db.execute(
            select(Job).where(Job.id == job_id).with_for_update()
        ).scalar_one()
        files = list(locked_job.annotated_pdf_files or [])
        for e in files:
            if e.get("index") == annotation_index:
                e["task_id"] = task.id
                e["premium_pages"] = units
                e["period_start"] = (
                    job.annotate_reserved_period_start.isoformat()
                    if job.annotate_reserved_period_start
                    else None
                )
                break
        locked_job.annotated_pdf_files = files
        flag_modified(locked_job, "annotated_pdf_files")
        locked_job.annotate_job_id = task.id
        db.commit()
    except Exception:
        db.rollback()
        celery_app.control.revoke(task.id, terminate=True, signal="SIGTERM")
        locked_job = db.execute(
            select(Job).where(Job.id == job_id).with_for_update()
        ).scalar_one()
        files = list(locked_job.annotated_pdf_files or [])
        for e in files:
            if e.get("index") == annotation_index:
                e["status"] = "error"
                e["recovery_notes"] = [{"reason": "큐잉 실패"}]
                break
        locked_job.annotated_pdf_files = files
        flag_modified(locked_job, "annotated_pdf_files")
        locked_job.annotate_status = _overall_annotation_status(files)
        locked_job.annotate_refundable = False
        db.commit()
        raise HTTPException(status_code=500, detail="주석 편집 큐잉에 실패했습니다. 다시 시도해주세요.")
    return {"job_id": task.id, "status": "processing", "annotation_index": annotation_index}





@router.post("/jobs/{job_id}/user-annotations")
def save_user_annotations(
    job_id: str,
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (job 조회 및 권한 확인) -> Step 2 (source_index에 해당하는 주석 PDF 항목 찾기)
          -> Step 3 (Storage에서 PDF 다운로드) -> Step 4 (사용자 주석을 PyMuPDF로 적용)
          -> Step 5 (새 PDF 및 annotations.json 업로드) -> Step 6 (preview 캐시 무효화 후 OK 반환)]

    사용자가 EmbedPDF 뷰어에서 추가/편집한 주석을 받아 기존 annotation PDF에 병합한다.
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)

    source_index = payload.get("source_index")
    annotations = payload.get("annotations")
    input_space = payload.get("input_space", "device")
    if not isinstance(source_index, int) or not isinstance(annotations, list):
        raise HTTPException(status_code=400, detail="Invalid source_index or annotations")
    if input_space not in ("device", "pdf_user"):
        raise HTTPException(status_code=400, detail="Invalid input_space")

    def _has_annotation(item):
        if not isinstance(item, dict):
            return False
        if "annotation" in item and isinstance(item["annotation"], dict):
            return item["annotation"].get("type") is not None and item["annotation"].get("pageIndex") is not None
        return item.get("type") is not None and item.get("pageIndex") is not None

    valid_annotations = [a for a in annotations if _has_annotation(a)]
    valid_annotations = _deduplicate_annotations(valid_annotations)
    valid_count = len(valid_annotations)
    logger.info(f"[save_user_annotations] {job_id} source_index={source_index} raw={len(annotations)} valid={valid_count}")
    if valid_count == 0:
        raise HTTPException(status_code=400, detail="No valid annotations found")

    # [Flow: source_index가 -1이면 원본 PDF에 대한 사용자 주석을 JSON으로만 저장한다]
    # 별도의 주석 PDF 파일을 생성하지 않고, 원본 PDF 뷰어에서 annotations_json_url로 로드한다.
    # source_index >= 0이면 파일별로 분리된 user_annotations_{source_index}.json에 저장한다.
    if source_index < 0:
        return _save_user_annotations_json(job, valid_annotations, db, source_index, input_space)

    # [Flow: source_index >= 0 — AI 주석 PDF가 있는지 확인]
    # AI 주석 PDF가 있으면 기존 동작 (주석 PDF에 병합), 없으면 파일별 주석 JSON으로 저장.
    locked_job = db.execute(
        select(Job).where(Job.id == job_id).with_for_update()
    ).scalar_one()
    entries = list(locked_job.annotated_pdf_files or [])
    has_annotation_pdf = False
    if not entries:
        # 하위 호환: 목록 컬럼 추가 전에 생성된 단일 주석 PDF
        if locked_job.result_annotated_pdf_storage_path and source_index == 0:
            stem = Path(locked_job.original_filename).stem if locked_job.original_filename else "result"
            entries = [
                {
                    "index": 1,
                    "status": "done",
                    "storage_path": locked_job.result_annotated_pdf_storage_path,
                    "annotations_json_storage_path": None,
                    "filename": f"{stem}_annotation1.pdf",
                }
            ]
            has_annotation_pdf = True
    else:
        # index 필드로 entry 찾기 — 해당 source_index에 AI 주석 PDF가 있는지 확인
        has_annotation_pdf = any(e.get("index") == source_index for e in entries)

    # [Flow: AI 주석 PDF가 없으면 파일별 주석 JSON으로 저장 — 파일 추가 시 주석 합쳐짐 방지]
    if not has_annotation_pdf:
        return _save_user_annotations_json(job, valid_annotations, db, source_index)

    # index 필드로 entry 찾기 (position 기반이 아님)
    # 하위 호환: source_index == 0이면 index == 1과 매칭 (단일 주석 PDF의 index는 1부터 시작)
    entry = next((e for e in entries if e.get("index") == source_index), None)
    if entry is None and source_index == 0:
        entry = next((e for e in entries if e.get("index") == 1), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="Annotation file not found")

    storage_path = entry.get("storage_path")
    if not storage_path:
        raise HTTPException(status_code=404, detail="Annotation file not found")

    annotations_json_storage_path = entry.get("annotations_json_storage_path")
    if not annotations_json_storage_path:
        # 공유 AI 주석 파일을 사용하는 신규 모드에서는 고정된 경로를 사용한다.
        annotations_json_storage_path = f"{job_id}/annotated.annotations.json"

    try:
        client = supabase_client.get_service_client()
        pdf_bytes = client.storage.from_("results").download(storage_path)
        new_pdf_bytes = pdf_user_annotator.apply_user_annotations(
            pdf_bytes, valid_annotations, input_space=input_space
        )
        client.storage.from_("results").upload(
            storage_path,
            new_pdf_bytes,
            {"content-type": "application/pdf", "upsert": "true"},
        )

        # 기존 AI 주석 JSON이 있으면 사용자 주석과 병합.
        # [Flow: 사용자가 AI 주석을 편집한 경우(_userEdited 또는 내용 변경) 감지하여 보존]
        try:
            existing_bytes = client.storage.from_("results").download(annotations_json_storage_path)
            existing = json.loads(existing_bytes.decode("utf-8"))
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []

        # 기존 AI 주석을 ID 기준으로 인덱싱
        existing_by_id: dict[str, dict] = {}
        for a in existing:
            aid = _annotation_id(a)
            if aid.startswith("backend-"):
                existing_by_id[aid] = a

        # export된 주석을 AI 주석과 사용자 주석으로 분류하되,
        # AI 주석 중 사용자가 편집한 것은 _userEdited 플래그를 설정해 보존
        ai_annotations: list[dict] = []
        user_annotations: list[dict] = []
        for a in valid_annotations:
            if not isinstance(a, dict):
                continue
            aid = _annotation_id(a)
            if aid.startswith("backend-"):
                orig = existing_by_id.get(aid)
                if orig is None:
                    # 기존에 없는 AI 주석 — 새로 추가된 것으로 간주
                    ai_annotations.append(a)
                elif _is_annotation_edited(a, orig):
                    # 사용자가 편집한 AI 주석 — _userEdited 플래그 설정 후 보존
                    _mark_user_edited(a)
                    ai_annotations.append(a)
                    logger.info(f"[save_user_annotations] {job_id} AI 주석 편집 감지: {aid}")
                else:
                    # 변경 없음 — 기존 것 유지 (멱등성)
                    ai_annotations.append(orig)
            else:
                user_annotations.append(a)

        # 기존 JSON에만 있고 export에 없는 AI 주석 (사용자가 삭제한 것)은 제외
        exported_ai_ids = {_annotation_id(a) for a in ai_annotations}
        for aid, orig in existing_by_id.items():
            if aid not in exported_ai_ids:
                # 삭제된 주석 — 사용자가 의도적으로 삭제한 것이므로 포함하지 않음
                logger.info(f"[save_user_annotations] {job_id} AI 주석 삭제 감지: {aid}")

        merged = ai_annotations + user_annotations

        client.storage.from_("results").upload(
            annotations_json_storage_path,
            json.dumps(merged, ensure_ascii=False).encode("utf-8"),
            {"content-type": "application/json", "upsert": "true"},
        )
        if entry.get("annotations_json_storage_path") != annotations_json_storage_path:
            entry["annotations_json_storage_path"] = annotations_json_storage_path
            locked_job.annotated_pdf_files = entries
            flag_modified(locked_job, "annotated_pdf_files")
            db.commit()
        cache.invalidate_pattern(f"preview:{job_id}:*")
        return {
            "ok": True,
            "storage_path": storage_path,
            "annotations_json_storage_path": annotations_json_storage_path,
        }
    except Exception as e:
        logger.exception(f"[save_user_annotations] {job_id} source_index={source_index} 실패: {e}")
        raise HTTPException(status_code=500, detail=f"주석 저장 실패: {e}")


def _is_user_annotation(item: dict) -> bool:
    """[Flow: Step 1 (annotation 내부 dict 추출) -> Step 2 (AI 주석 id prefix 확인)
          -> Step 3 (_userEdited 플래그 확인) -> Step 4 (사용자 주석 여부 반환)]

    AI 주석은 id가 'backend-'로 시작한다. 사용자가 직접 추가한 주석은 그렇지 않으며,
    사용자가 AI 주석을 직접 편집한 경우(_userEdited=true)에도 사용자 주석으로 간주한다.
    """
    if not isinstance(item, dict):
        return False
    a = _annotation_inner(item)
    annotation_id = a.get("id", "")
    if annotation_id.startswith("backend-"):
        return bool(a.get("_userEdited"))
    return True


def _save_user_annotations_json(
    job: Job,
    annotations: list,
    db: Session,
    source_index: int = -1,
    input_space: str = "device",
) -> dict:
    """[Flow: Step 1 (사용자 주석만 필터링) -> Step 2 (AI 주석 JSON 다운로드)
          -> Step 3 (input_space가 pdf_user이면 PDF user-space → device-space 변환)
          -> Step 4 (중복 제거 후 병합) -> Step 5 (results 버킷에 저장)
          -> Step 6 (preview 캐시 무효화)]

    원본 PDF에 대한 사용자 주석을 JSON 형태로만 저장한다.
    별도의 주석 PDF 파일을 생성하지 않고, 원본 PDF 뷰어에서 annotations_json_url로 로드한다.
    AI 주석과의 병합은 _source_files()에서 수행하며, 여기서는 사용자 주석만 저장해
    동일한 주석이 반복 저장되면서 색이 진해지는 것을 방지한다.

    매개변수:
        job: Job 객체
        annotations: 저장할 주석 목록
        db: DB 세션
        source_index: 파일 인덱스 (-1이면 기존 공유 user_annotations.json, 0 이상이면
            user_annotations_{source_index}.json에 저장하여 파일별 주석 분리)
        input_space: 입력 좌표계 ("device" 또는 "pdf_user")

    반환값:
        저장 결과 dict (ok, annotations_json_storage_path)
    """
    job_id = job.id
    # [Flow: source_index >= 0이면 파일별로 분리된 주석 JSON 사용 — 파일 추가 시 주석 합쳐짐 방지]
    if source_index >= 0:
        storage_path = f"{job_id}/user_annotations_{source_index}.json"
    else:
        storage_path = f"{job_id}/user_annotations.json"
    try:
        client = supabase_client.get_service_client()
        # AI 주석은 제외하고 사용자가 추가/편집한 주석만 저장한다.
        user_annotations = [a for a in annotations if _is_user_annotation(a)]

        # [Flow: AI 백엔드가 보내는 PDF user-space 좌표를 device-space로 변환]
        # 뷰어는 항상 device-space를 기대하므로, JSON 저장 전에 좌표계를 맞춘다.
        if input_space == "pdf_user" and user_annotations:
            original_path = job.pdf_storage_path
            if original_path:
                try:
                    pdf_bytes = client.storage.from_("pdfs").download(original_path)
                    user_annotations = pdf_user_annotator._convert_annotations_to_device_space(
                        user_annotations, pdf_bytes
                    )
                except Exception as e:
                    logger.warning(f"[_save_user_annotations_json] {job_id} PDF user-space 변환 실패: {e}")

        user_annotations = _deduplicate_annotations(user_annotations)
        client.storage.from_("results").upload(
            storage_path,
            json.dumps(user_annotations, ensure_ascii=False).encode("utf-8"),
            {"content-type": "application/json", "upsert": "true"},
        )
        cache.invalidate_pattern(f"preview:{job_id}:*")
        return {
            "ok": True,
            "annotations_json_storage_path": storage_path,
        }
    except Exception as e:
        logger.exception(f"[_save_user_annotations_json] {job_id} 실패: {e}")
        raise HTTPException(status_code=500, detail=f"주석 저장 실패: {e}")


def _annotation_display_name(job: Job, n: int) -> str:
    """[Flow: Step 1 (원본 파일명 확인) -> Step 2 (확장자 제거) -> Step 3 (주석 순서 접미사 추가)]"""
    stem = Path(job.original_filename).stem if job.original_filename else "result"
    return f"{stem}_annotation{n}.pdf"


def _create_user_annotated_pdf(job: Job, annotations: list, db: Session) -> dict:
    """[Flow: Step 1 (원본 PDF storage_path 확인) -> Step 2 (기존 user 모드 주석 PDF 확인)
          -> Step 3a (있으면 해당 파일 덮어쓰기) -> Step 3b (없으면 원본 PDF 다운로드 후 새 파일 생성)
          -> Step 4 (results 버킷에 PDF + JSON 업로드) -> Step 5 (DB commit 및 preview 캐시 무효화)]

    사용자가 원본 PDF에 직접 추가한 주석을 받아 annotation PDF 파일을 생성/갱신한다.
    이미 user 모드 주석 PDF가 존재하면 덮어쓰고, 없으면 새로 생성한다.
    자동 저장이 반복되어도 파일이 계속 늘어나지 않도록 한다.
    """
    job_id = job.id
    original_path = job.pdf_storage_path
    if not original_path:
        raise HTTPException(status_code=404, detail="Original PDF not found")

    try:
        client = supabase_client.get_service_client()

        # [Flow: 기존 user 모드 주석 PDF가 있으면 재사용한다]
        annotated_files = list(job.annotated_pdf_files or [])
        existing_user_entry = next(
            (e for e in annotated_files if e.get("mode") == "user"),
            None,
        )

        if existing_user_entry:
            # [Flow: Step 3a (기존 user 주석 PDF 경로 재사용)]
            storage_path = existing_user_entry.get("storage_path")
            annotations_json_storage_path = existing_user_entry.get("annotations_json_storage_path")
            if not storage_path:
                raise HTTPException(status_code=500, detail="Invalid user annotation entry")
            if not annotations_json_storage_path:
                annotations_json_storage_path = f"{job_id}/annotated_{existing_user_entry.get('index', 1)}.annotations.json"
            # 기존 주석 PDF를 다운로드하여 원본에 주석을 다시 적용하는 대신,
            # 원본 PDF에 최신 주석을 적용하여 덮어쓴다 (사용자 주석은 원본 기준).
            pdf_bytes = client.storage.from_("pdfs").download(original_path)
            new_pdf_bytes = pdf_user_annotator.apply_user_annotations(pdf_bytes, annotations)
        else:
            # [Flow: Step 3b (원본 PDF 다운로드 후 새 주석 PDF 생성)]
            pdf_bytes = client.storage.from_("pdfs").download(original_path)
            new_pdf_bytes = pdf_user_annotator.apply_user_annotations(pdf_bytes, annotations)

            # 원자적으로 다음 인덱스를 할당한다.
            result = db.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(annotated_pdf_next_index=Job.annotated_pdf_next_index + 1)
                .returning(Job.annotated_pdf_next_index)
            )
            db.commit()
            next_index = result.scalar()
            if not next_index:
                raise HTTPException(status_code=500, detail="Failed to allocate annotation index")

            storage_path = f"{job_id}/annotated_{next_index}.pdf"
            annotations_json_storage_path = f"{job_id}/annotated_{next_index}.annotations.json"

            entry = {
                "index": next_index,
                "status": "done",
                "storage_path": storage_path,
                "annotations_json_storage_path": annotations_json_storage_path,
                "filename": _annotation_display_name(job, next_index),
                "instruction": "",
                "mode": "user",
                "comment_mode": "user",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            annotated_files.append(entry)
            job.annotated_pdf_files = annotated_files
            flag_modified(job, "annotated_pdf_files")
            job.result_annotated_pdf_storage_path = storage_path

        client.storage.from_("results").upload(
            storage_path,
            new_pdf_bytes,
            {"content-type": "application/pdf", "upsert": "true"},
        )
        client.storage.from_("results").upload(
            annotations_json_storage_path,
            json.dumps(annotations, ensure_ascii=False).encode("utf-8"),
            {"content-type": "application/json", "upsert": "true"},
        )

        # 기존 entry의 annotations_json_storage_path가 비어 있었다면 갱신한다.
        if existing_user_entry and not existing_user_entry.get("annotations_json_storage_path"):
            existing_user_entry["annotations_json_storage_path"] = annotations_json_storage_path
            job.annotated_pdf_files = annotated_files
            flag_modified(job, "annotated_pdf_files")

        db.commit()
        cache.invalidate_pattern(f"preview:{job_id}:*")
        return {
            "ok": True,
            "storage_path": storage_path,
            "annotations_json_storage_path": annotations_json_storage_path,
        }
    except Exception as e:
        logger.exception(f"[_create_user_annotated_pdf] {job_id} 실패: {e}")
        raise HTTPException(status_code=500, detail=f"주석 PDF 생성 실패: {e}")


@router.post("/jobs/{job_id}/action")
def job_action(
    job_id: str,
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """문서 파싱 최종 실패 시 재시도 또는 포인트 환불을 처리한다."""
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    if job.status != "error" or not job.refundable:
        raise HTTPException(status_code=400, detail="Not in a refundable or retryable state")

    action = str(payload.get("action", "")).lower()
    if action not in ("retry", "refund"):
        raise HTTPException(status_code=400, detail="Unsupported action")

    from ..db.models import User
    db_user = db.get(User, job.user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if action == "refund":
        # 구독 사용량 환불: 예약 시 기록한 기간과 단위를 사용
        refunded_basic = job.reserved_basic_pages
        refunded_premium = job.reserved_premium_pages
        refunded_media = job.reserved_media_seconds
        subscription_service.release_usage(
            db,
            db_user,
            basic_pages=refunded_basic,
            premium_pages=refunded_premium,
            media_seconds=refunded_media,
            period_start=job.reserved_period_start,
        )
        job.reserved_basic_pages = 0
        job.reserved_premium_pages = 0
        job.reserved_media_seconds = 0
        job.reserved_period_start = None
        job.refundable = False
        db.commit()
        return {"refunded": True, "basic_pages": refunded_basic, "premium_pages": refunded_premium, "media_seconds": refunded_media}

    # retry: 상태 초기화 후 비용 없이 task 재실행
    job.status = "queued"
    job.retry_count = 0
    job.refundable = False
    job.result_csv_storage_path = ""
    job.result_md_storage_path = ""
    job.result_csv_path = ""
    job.result_md_path = ""
    db.commit()
    run_job.delay(job_id)
    return {"job_id": job_id, "status": "queued"}


def _upload_ocr_layout(db: Session, job: Job, layout_by_page: dict[int, dict]) -> None:
    """[Flow: Step 1 (layout_by_page를 JSON 직렬화) -> Step 2 (results 버킷에 업로드)
          -> Step 3 (Job DB에 경로 저장)]

    OCR로 확보한 layout_by_page를 Storage에 저장해 이후 get_elements/search_text 호출이
    PaddleOCR을 재실행하지 않도록 한다.
    """
    try:
        data = json.dumps(layout_by_page, ensure_ascii=False, default=str).encode("utf-8")
        storage_path = f"{job.id}/ocr_layout.json"
        client = supabase_client.get_service_client()
        client.storage.from_("results").upload(
            storage_path,
            data,
            {"content-type": "application/json", "upsert": "true"},
        )
        job.result_ocr_layout_storage_path = storage_path
        db.commit()
        logger.info(f"[get_job_elements] {job.id} OCR layout 저장 완료: {storage_path}")
    except Exception as e:
        logger.warning(f"[get_job_elements] {job.id} OCR layout 저장 실패: {e}")


# [Flow: Step 1 (job 조회 및 권한 확인) -> Step 2 (searchable PDF 다운로드)
#       -> Step 3 (PyMuPDF로 페이지별 텍스트 블록 추출) -> Step 4 (요소 목록 반환)]
# Node.js AI 백엔드의 PDF 주석 도구가 요소를 조회하기 위한 전용 엔드포인트.
@router.get("/jobs/{job_id}/elements")
def get_job_elements(
    job_id: str,
    page_no: int | None = None,
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (job 조회) -> Step 2 (searchable PDF 확보) -> Step 3 (텍스트 블록 추출)
          -> Step 4 (page_no 필터링) -> Step 5 (요소 목록 반환)]

    AI 에이전트가 PDF 주석을 추가할 때 참조할 페이지별 텍스트 요소를 반환한다.
    각 요소는 page_no, bbox_pdf (PDF user-space 좌표), text 를 포함한다.
    """
    import fitz
    import time as _time

    start_time = _time.monotonic()
    used_ocr_layout = False
    used_ocr_fallback = False

    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)

    # searchable PDF 우선, 없으면 원본 PDF 사용
    storage_path = job.searchable_pdf_storage_path
    bucket = "pdfs"
    if not storage_path:
        # 다중 파일의 경우 첫 번째 PDF의 searchable path를 찾는다
        files = job.extracted_files or []
        for info in files:
            sp = info.get("searchable_pdf_storage_path")
            if sp:
                storage_path = sp
                break
    if not storage_path and job.pdf_storage_path:
        storage_path = job.pdf_storage_path
        bucket = "pdfs"

    if not storage_path:
        raise HTTPException(status_code=404, detail="No PDF available for this job")

    try:
        client = supabase_client.get_service_client()
        pdf_bytes = client.storage.from_(bucket).download(storage_path)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to download PDF: {e}")

    elements: list[dict] = []
    page_dimensions: dict[int, dict] = {}
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for page in doc:
            current_page_no = page.number + 1
            page_dimensions[current_page_no] = {
                "width": float(page.rect.width),
                "height": float(page.rect.height),
            }
            if page_no is not None and current_page_no != page_no:
                continue
            blocks = page.get_text("blocks")
            for block in blocks:
                try:
                    x0, y0, x1, y1, text, _block_no, _block_type = block
                except Exception:
                    continue
                if not text or not text.strip():
                    continue
                elements.append({
                    "page_no": current_page_no,
                    "bbox_pdf": [float(x0), float(y0), float(x1), float(y1)],
                    "text": text.strip(),
                    "kind": "text",
                })
    finally:
        doc.close()

    # [Flow: 텍스트 레이어가 없는 스캔 PDF(searchable_pdf_storage_path 미생성)에서는 위 블록 추출이
    # 항상 빈 리스트를 반환한다. 이 경우 1) 저장된 OCR layout이 있으면 재사용하고,
    # 2) 없으면 PaddleOCR 기반 collect_elements_for_agent()로 요소를 재추출해 폴백한다.]
    ocr_page_range = [page_no] if page_no is not None else None
    if not elements:
        # 1) 저장된 OCR layout 재사용
        if job.result_ocr_layout_storage_path:
            try:
                from ..core.pdf_annotate_converter import build_agent_elements_from_ocr_layout

                layout_raw = client.storage.from_("results").download(job.result_ocr_layout_storage_path)
                layout_by_page = {int(k): v for k, v in json.loads(layout_raw.decode("utf-8")).items()}
                ocr_elements = build_agent_elements_from_ocr_layout(layout_by_page, pdf_bytes, page_range=ocr_page_range)
                if ocr_elements:
                    elements = [
                        {
                            "page_no": el["page_no"],
                            "bbox_pdf": list(el["bbox_pdf"]),
                            "text": el["text"],
                            "kind": el.get("kind", "text"),
                        }
                        for el in ocr_elements
                    ]
                    used_ocr_layout = True
                    logger.info(f"[get_job_elements] {job_id} 저장된 OCR layout 사용: {len(elements)}개 요소")
            except Exception as e:
                logger.warning(f"[get_job_elements] {job_id} 저장된 OCR layout 사용 실패: {e}")

        # 2) OCR layout이 없거나 실패하면 PaddleOCR 폴백
        if not elements:
            try:
                from ..core.pdf_annotate_converter import collect_elements_for_agent

                ocr_elements, ocr_pdf_bytes, layout_by_page = collect_elements_for_agent(job_id, page_range=ocr_page_range)
            except Exception as e:
                logger.warning(f"[get_job_elements] {job_id} OCR 폴백 실패: {e}")
                ocr_elements, ocr_pdf_bytes, layout_by_page = [], None, {}

            if ocr_elements:
                elements = [
                    {
                        "page_no": el["page_no"],
                        "bbox_pdf": list(el["bbox_pdf"]),
                        "text": el["text"],
                        "kind": el.get("kind", "text"),
                    }
                    for el in ocr_elements
                ]
                used_ocr_fallback = True
                if ocr_pdf_bytes:
                    ocr_doc = fitz.open(stream=ocr_pdf_bytes, filetype="pdf")
                    try:
                        for page in ocr_doc:
                            page_dimensions[page.number + 1] = {
                                "width": float(page.rect.width),
                                "height": float(page.rect.height),
                            }
                    finally:
                        ocr_doc.close()

                # 다음 호출을 위해 OCR layout을 Storage에 저장
                if layout_by_page:
                    _upload_ocr_layout(db, job, layout_by_page)

    import time as _time
    total_elapsed = _time.monotonic() - start_time
    return Response(
        json.dumps({"elements": elements, "total": len(elements), "page_dimensions": page_dimensions}, ensure_ascii=False, default=str),
        media_type="application/json",
        headers={
            "X-Total-Elapsed": str(round(total_elapsed * 1000)),
            "X-Used-OCR-Layout": str(used_ocr_layout).lower(),
            "X-Used-OCR-Fallback": str(used_ocr_fallback).lower(),
            "X-OCR-Layout-Path": str(job.result_ocr_layout_storage_path or ""),
        },
    )


# [Flow: Step 1 (job 조회) -> Step 2 (searchable PDF 다운로드) -> Step 3 (텍스트 검색)
#       -> Step 4 (page_no 필터링) -> Step 5 (매치 목록 반환)]
# Node.js AI 백엔드의 search_text 도구가 호출하는 엔드포인트.
@router.get("/jobs/{job_id}/search-text")
def search_job_text(
    job_id: str,
    query: str = Query(..., description="검색어 또는 정규식"),
    page_no: int | None = None,
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (job 조회) -> Step 2 (searchable PDF 확보) -> Step 3 (PyMuPDF search)
          -> Step 4 (page_no 필터링) -> Step 5 (매치 목록 반환)]

    PDF 텍스트 레이어에서 키워드/정규식 검색을 수행한다.
    """
    import fitz
    import time as _time

    start_time = _time.monotonic()
    used_ocr_layout = False
    used_ocr_fallback = False

    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)

    storage_path = job.searchable_pdf_storage_path
    bucket = "pdfs"
    if not storage_path:
        files = job.extracted_files or []
        for info in files:
            sp = info.get("searchable_pdf_storage_path")
            if sp:
                storage_path = sp
                break
    if not storage_path and job.pdf_storage_path:
        storage_path = job.pdf_storage_path
        bucket = "pdfs"

    if not storage_path:
        raise HTTPException(status_code=404, detail="No PDF available for this job")

    try:
        client = supabase_client.get_service_client()
        pdf_bytes = client.storage.from_(bucket).download(storage_path)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to download PDF: {e}")

    matches: list[dict] = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for page in doc:
            current_page_no = page.number + 1
            if page_no is not None and current_page_no != page_no:
                continue
            # 정규식 검색과 일반 텍스트 검색 모두 지원
            try:
                rects = page.search_for(query)
            except Exception:
                # 정규식이 유효하지 않으면 일반 텍스트로 폴백
                rects = page.search_for(query.replace("\\", ""))
            for rect in rects:
                matches.append({
                    "page_no": current_page_no,
                    "bbox_pdf": [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)],
                    "text": page.get_textbox(rect).strip(),
                })
    finally:
        doc.close()

    # [Flow: 텍스트 레이어가 없는 스캔 PDF에서는 위 search_for가 항상 매치 0개를 반환한다.
    # 1) 저장된 OCR layout이 있으면 재사용하고, 2) 없으면 PaddleOCR 폴백으로
    # 요소 텍스트에 대해 대소문자 무관 정규식 매칭을 수행한다.]
    ocr_page_range = [page_no] if page_no is not None else None
    if not matches:
        ocr_elements: list[dict] = []
        # 1) 저장된 OCR layout 재사용
        if job.result_ocr_layout_storage_path:
            try:
                from ..core.pdf_annotate_converter import build_agent_elements_from_ocr_layout

                layout_raw = client.storage.from_("results").download(job.result_ocr_layout_storage_path)
                layout_by_page = {int(k): v for k, v in json.loads(layout_raw.decode("utf-8")).items()}
                ocr_elements = build_agent_elements_from_ocr_layout(layout_by_page, pdf_bytes, page_range=ocr_page_range)
                if ocr_elements:
                    used_ocr_layout = True
                    logger.info(f"[search_job_text] {job_id} 저장된 OCR layout 사용: {len(ocr_elements)}개 요소")
            except Exception as e:
                logger.warning(f"[search_job_text] {job_id} 저장된 OCR layout 사용 실패: {e}")

        # 2) OCR layout이 없거나 실패하면 PaddleOCR 폴백
        if not ocr_elements:
            try:
                from ..core.pdf_annotate_converter import collect_elements_for_agent

                ocr_elements, _ocr_pdf_bytes, layout_by_page = collect_elements_for_agent(job_id, page_range=ocr_page_range)
                used_ocr_fallback = True
            except Exception as e:
                logger.warning(f"[search_job_text] {job_id} OCR 폴백 실패: {e}")
                ocr_elements, layout_by_page = [], {}

            # 다음 호출을 위해 OCR layout 저장
            if layout_by_page:
                _upload_ocr_layout(db, job, layout_by_page)

        try:
            pattern = _re.compile(query, _re.IGNORECASE)
        except _re.error:
            pattern = _re.compile(_re.escape(query), _re.IGNORECASE)
        for el in ocr_elements:
            text = el.get("text") or ""
            if not pattern.search(text):
                continue
            matches.append({
                "page_no": el["page_no"],
                "bbox_pdf": list(el["bbox_pdf"]),
                "text": text.strip(),
            })

    import time as _time
    total_elapsed = _time.monotonic() - start_time
    return Response(
        json.dumps({"matches": matches, "total": len(matches)}, ensure_ascii=False, default=str),
        media_type="application/json",
        headers={
            "X-Total-Elapsed": str(round(total_elapsed * 1000)),
            "X-Used-OCR-Layout": str(used_ocr_layout).lower(),
            "X-Used-OCR-Fallback": str(used_ocr_fallback).lower(),
            "X-OCR-Layout-Path": str(job.result_ocr_layout_storage_path or ""),
        },
    )


def _resolve_annotations_json_path(job: Job, source_index: int) -> str | None:
    """[Flow: Step 1 (annotated_pdf_files 확인) -> Step 2 (source_index 0이면 1로 매핑)
          -> Step 3 (source_index에 해당하는 entry 찾기) -> Step 4 (유효한 JSON 경로가 없으면 최신 완료 run으로 폴백)
          -> Step 5 (annotations_json_storage_path 반환) -> Step 6 (공유 경로 폴백)]

    AI 주석 run의 인덱스로부터 해당 run의 주석 JSON Storage 경로를 반환한다.
    source_index 0은 하위 호환을 위해 첫 번째 AI 주석 run(인덱스 1)으로 매핑된다.
    요청한 run이 아직 진행 중이거나 JSON 경로가 없으면, 완료된 가장 최근 run으로 폴백한다.
    """
    entries = list(job.annotated_pdf_files or [])
    if source_index == 0:
        source_index = 1
    if not entries and job.result_annotated_pdf_storage_path and source_index == 1:
        stem = Path(job.original_filename).stem if job.original_filename else "result"
        entries = [
            {
                "index": 1,
                "status": "done",
                "storage_path": job.result_annotated_pdf_storage_path,
                "annotations_json_storage_path": None,
                "filename": f"{stem}_annotation1.pdf",
            }
        ]

    entry = next((e for e in entries if e.get("index") == source_index), None)
    if entry is None or not entry.get("annotations_json_storage_path"):
        # 요청한 run이 없거나 JSON이 없으면, 완료된 최신 run으로 폴백
        fallback = next(
            (e for e in reversed(entries) if e.get("status") == "done" and e.get("annotations_json_storage_path")),
            None,
        )
        if fallback is not None:
            entry = fallback
            source_index = fallback.get("index", source_index)

    if entry is None:
        return None
    path = entry.get("annotations_json_storage_path")
    if not path:
        return f"{job.id}/annotated_{source_index}.annotations.json"
    return path


def _load_all_annotations(
    job: Job,
    source_index: int,
    page_no: int | None = None,
) -> list[dict]:
    """[Flow: Step 1 (AI 주석 JSON 경로 확보 — None이면 스킵) -> Step 2 (AI 주석 다운로드)
          -> Step 3 (사용자 주석 다운로드 및 ID 중복 제거 병합) -> Step 4 (page_no 필터링)
          -> Step 5 (병합된 주석 목록 반환)]

    AI 주석 JSON과 사용자 주석 JSON을 모두 로드하여 병합한다.
    _resolve_annotations_json_path가 None을 반환해도 에러를 발생시키지 않고
    사용자 주석만 로드한다. 주석이 전혀 없으면 빈 리스트를 반환한다.

    @param job Job 모델 인스턴스
    @param source_index 주석 파일 인덱스 (0=첫 번째 원본)
    @param page_no 1-based 페이지 번호. 생략 시 전체 페이지
    @returns 병합된 주석 목록 (EmbedPDF AnnotationTransferItem[] 형식)
    """
    client = supabase_client.get_service_client()
    all_annotations: list[dict] = []

    # AI 주석 로드 — 경로가 None이면 AI 주석이 아직 없으므로 스킵
    annotations_json_storage_path = _resolve_annotations_json_path(job, source_index)
    if annotations_json_storage_path:
        try:
            existing_bytes = client.storage.from_("results").download(annotations_json_storage_path)
            existing = json.loads(existing_bytes.decode("utf-8"))
            if isinstance(existing, list):
                all_annotations.extend(existing)
        except Exception:
            pass

    # 사용자 주석 로드 — 파일별 분리된 user_annotations_{source_index}.json 우선
    user_annotations_json_path = f"{job.id}/user_annotations_{source_index}.json"
    try:
        user_bytes = client.storage.from_("results").download(user_annotations_json_path)
        user_annotations = json.loads(user_bytes.decode("utf-8"))
        if isinstance(user_annotations, list):
            existing_ids = {_annotation_id(a) for a in all_annotations if _annotation_id(a)}
            for a in user_annotations:
                aid = _annotation_id(a)
                if aid and aid in existing_ids:
                    continue
                all_annotations.append(a)
    except Exception:
        # 파일별 주석 JSON이 없으면 공유 user_annotations.json으로 폴백 (하위 호환)
        user_annotations_json_path = f"{job.id}/user_annotations.json"
        try:
            user_bytes = client.storage.from_("results").download(user_annotations_json_path)
            user_annotations = json.loads(user_bytes.decode("utf-8"))
            if isinstance(user_annotations, list):
                existing_ids = {_annotation_id(a) for a in all_annotations if _annotation_id(a)}
                for a in user_annotations:
                    aid = _annotation_id(a)
                    if aid and aid in existing_ids:
                        continue
                    all_annotations.append(a)
        except Exception:
            pass

    # page_no 필터링 — EmbedPDF 주석의 pageIndex는 0-based이므로 page_no - 1과 비교
    if page_no is not None:
        filtered = []
        for a in all_annotations:
            inner = _annotation_inner(a)
            if inner.get("pageIndex") == page_no - 1:
                filtered.append(a)
        all_annotations = filtered

    return all_annotations


# [Flow: Step 1 (job 조회 및 권한 확인) -> Step 2 (source_index로 주석 JSON 경로 확보)
#       -> Step 3 (AI 주석 JSON + 사용자 주석 JSON 병합) -> Step 4 (page_no 필터링) -> Step 5 (주석 목록 반환)]
# Node.js AI 백엔드가 기존 주석을 조회하기 위한 전용 엔드포인트.
@router.get("/jobs/{job_id}/annotations")
def get_job_annotations(
    job_id: str,
    source_index: int = Query(0, description="주석 파일 인덱스"),
    page_no: int | None = Query(None, description="1-based 페이지 번호. 생략 시 모든 페이지"),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (job 조회) -> Step 2 (_load_all_annotations로 AI+사용자 주석 병합 로드)
          -> Step 3 (EmbedPDF 형식 주석 목록 반환)]

    AI 에이전트가 기존 주석 목록을 확인할 때 사용한다.
    AI 주석 PDF가 없어도 사용자 주석이 존재하면 반환하며, 주석이 전혀 없으면 빈 리스트를 반환한다.
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)

    all_annotations = _load_all_annotations(job, source_index, page_no)
    return {"annotations": all_annotations, "total": len(all_annotations)}


# [Flow: Step 1 (job 조회 및 권한 확인) -> Step 2 (source_index로 주석 JSON 경로 확보)
# -> Step 3 (annotation_id로 주석 찾기) -> Step 4 (색상/코멘트/투명도 수정)
# -> Step 5 (AI 주석이면 _userEdited 설정) -> Step 6 (Storage 저장 및 캐시 무효화)]
@router.patch("/jobs/{job_id}/annotations/{annotation_id}")
def update_job_annotation(
    job_id: str,
    annotation_id: str,
    source_index: int = Query(0, description="주석 파일 인덱스"),
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (job 조회) -> Step 2 (source_index로 주석 JSON 경로 확보 — None이면 AI 주석 스킵)
          -> Step 3 (annotation_id로 주석 찾기) -> Step 4 (color/comment/opacity 수정)
          -> Step 5 (AI 주석이면 _userEdited 설정) -> Step 6 (Storage 저장 및 preview 캐시 무효화)]

    AI 에이전트가 기존 주석의 색상/코멘트/투명도를 변경할 때 사용한다.
    AI 주석 PDF가 없어도 사용자 주석이 존재하면 수정할 수 있다.
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)

    # AI 주석 경로 — None이면 AI 주석이 없으므로 사용자 주석만 로드
    annotations_json_storage_path = _resolve_annotations_json_path(job, source_index)

    client = supabase_client.get_service_client()
    all_annotations: list[dict] = []
    if annotations_json_storage_path:
        try:
            existing_bytes = client.storage.from_("results").download(annotations_json_storage_path)
            existing = json.loads(existing_bytes.decode("utf-8"))
            if isinstance(existing, list):
                all_annotations = existing
        except Exception:
            pass

    # [Flow: 파일별 주석 분리 — source_index별로 분리된 user_annotations_{source_index}.json을 먼저 확인]
    user_annotations_json_path = f"{job.id}/user_annotations_{source_index}.json"
    user_annotations: list[dict] = []
    try:
        user_bytes = client.storage.from_("results").download(user_annotations_json_path)
        user_annotations = json.loads(user_bytes.decode("utf-8"))
        if not isinstance(user_annotations, list):
            user_annotations = []
    except Exception:
        # 파일별 주석 JSON이 없으면 공유 user_annotations.json으로 폴백 (하위 호환)
        user_annotations_json_path = f"{job.id}/user_annotations.json"
        try:
            user_bytes = client.storage.from_("results").download(user_annotations_json_path)
            user_annotations = json.loads(user_bytes.decode("utf-8"))
            if not isinstance(user_annotations, list):
                user_annotations = []
        except Exception:
            user_annotations = []

    target_index = -1
    target_list = all_annotations
    for i, a in enumerate(all_annotations):
        if _annotation_id(a) == annotation_id:
            target_index = i
            target_list = all_annotations
            break

    if target_index == -1:
        for i, a in enumerate(user_annotations):
            if _annotation_id(a) == annotation_id:
                target_index = i
                target_list = user_annotations
                break

    if target_index == -1:
        raise HTTPException(status_code=404, detail=f"Annotation {annotation_id} not found")

    annotation = target_list[target_index]
    inner = _annotation_inner(annotation)
    updated_fields: list[str] = []

    color = payload.get("color")
    if isinstance(color, str):
        inner["color"] = color
        inner["strokeColor"] = color
        updated_fields.append("color")

    comment = payload.get("comment")
    if isinstance(comment, str):
        inner["contents"] = comment
        updated_fields.append("comment")

    opacity = payload.get("opacity")
    if isinstance(opacity, (int, float)):
        inner["opacity"] = float(opacity)
        updated_fields.append("opacity")

    if not updated_fields:
        raise HTTPException(status_code=400, detail="No updatable fields provided")

    if annotation_id.startswith("backend-"):
        _mark_user_edited(annotation)

    target_storage_path = (
        annotations_json_storage_path
        if target_list is all_annotations and annotations_json_storage_path
        else user_annotations_json_path
    )
    client.storage.from_("results").upload(
        target_storage_path,
        json.dumps(target_list, ensure_ascii=False).encode("utf-8"),
        {"content-type": "application/json", "upsert": "true"},
    )

    cache.invalidate_pattern(f"preview:{job_id}:*")
    return {"ok": True, "annotation_id": annotation_id, "updated_fields": updated_fields}


def _estimate_page_image_dpi(page: "fitz.Page", doc: "fitz.Document") -> int:
    """[Flow: Step 1 (페이지 내 이미지 객체 추출) -> Step 2 (픽셀 크기 / 페이지 내 물리적 크기로 DPI 추정)
          -> Step 3 (최대 DPI 반환, 없으면 0)]

    페이지에 내장된 raster 이미지의 실제 해상도를 추정한다. 텍스트/벡터 위주 페이지는
    이미지가 없어 0을 반환하며, 이때는 기본 300dpi로 렌더링한다. 이미지가 포함된 페이지는
    원본 이미지의 DPI를 넘지 않도록 렌더링하여 토큰을 낭비하지 않는다.
    """
    max_dpi = 0
    try:
        img_list = page.get_images(full=True)
        for img in img_list:
            xref = img[0]
            base_image = doc.extract_image(xref)
            if not base_image:
                continue
            pix_width = base_image.get("width", 0)
            pix_height = base_image.get("height", 0)
            if pix_width <= 0 or pix_height <= 0:
                continue
            img_rects = page.get_image_rects(xref)
            if not img_rects:
                continue
            for rect in img_rects:
                if rect.width <= 0 or rect.height <= 0:
                    continue
                width_in = rect.width / 72.0
                height_in = rect.height / 72.0
                dpi_x = pix_width / width_in if width_in > 0 else 0
                dpi_y = pix_height / height_in if height_in > 0 else 0
                max_dpi = max(max_dpi, int(dpi_x), int(dpi_y))
    except Exception:
        pass
    return max_dpi


# [Flow: Step 1 (job 조회 및 권한 확인) -> Step 2 (searchable PDF 또는 원본 PDF 다운로드)
#       -> Step 3 (PyMuPDF로 페이지를 이미지로 렌더링) -> Step 4 (PNG로 Storage에 업로드)
#       -> Step 5 (signed URL 반환)]
# Node.js AI 백엔드의 VLLM이 PDF 특정 페이지를 시각적으로 볼 수 있도록 지원한다.
@router.get("/jobs/{job_id}/page-image")
def get_job_page_image(
    job_id: str,
    page_no: int = Query(..., description="1-based 페이지 번호", ge=1),
    dpi: int | None = Query(None, description="렌더링 DPI (생략 시 페이지 내 이미지 해상도에서 자동 추정, 150~300)", ge=150, le=300),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (job 조회) -> Step 2 (PDF 확보) -> Step 3 (페이지 이미지 렌더링)
          -> Step 4 (PNG 업로드) -> Step 5 (signed URL 반환)]

    VLLM/vision 모델이 PDF 특정 페이지를 직접 볼 수 있도록 페이지 이미지를 생성한다.
    """
    import fitz

    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)

    storage_path = job.searchable_pdf_storage_path
    bucket = "pdfs"
    if not storage_path:
        files = job.extracted_files or []
        for info in files:
            sp = info.get("searchable_pdf_storage_path")
            if sp:
                storage_path = sp
                break
    if not storage_path and job.pdf_storage_path:
        storage_path = job.pdf_storage_path
        bucket = "pdfs"

    if not storage_path:
        raise HTTPException(status_code=404, detail="No PDF available for this job")

    try:
        client = supabase_client.get_service_client()
        pdf_bytes = client.storage.from_(bucket).download(storage_path)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to download PDF: {e}")

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if page_no < 1 or page_no > doc.page_count:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid page_no {page_no}. PDF has {doc.page_count} pages.",
            )
        page = doc[page_no - 1]
        resolved_dpi = dpi
        if resolved_dpi is None:
            estimated = _estimate_page_image_dpi(page, doc)
            resolved_dpi = 300 if estimated <= 0 else max(150, min(300, estimated))
        pix = page.get_pixmap(dpi=resolved_dpi)
        img_bytes = pix.tobytes("png")
    finally:
        doc.close()

    output_path = f"{job_id}/page-images/page-{page_no}-{resolved_dpi}dpi.png"
    try:
        client.storage.from_("results").upload(
            output_path,
            img_bytes,
            {"content-type": "image/png", "upsert": "true"},
        )
        signed_url = supabase_client.get_signed_download_url(
            output_path, bucket="results", expires_in=3600
        )
        if not signed_url:
            raise HTTPException(status_code=500, detail="Failed to generate signed URL")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload page image: {e}")

    return {
        "page_no": page_no,
        "dpi": resolved_dpi,
        "width": pix.width,
        "height": pix.height,
        "image_url": signed_url,
    }


# [Flow: Step 1 (job 조회) -> Step 2 (kind에 따라 결과 JSON 소스 확보)
#       -> Step 3 (Storage에서 다운로드 또는 DB 필드 직접 반환) -> Step 4 (JSON 반환)]
# AI 에이전트의 read_job_json 도구가 호출하는 범용 결과 JSON 리더.
# 주석 JSON, OCR 레이아웃, extracted_files, annotated_pdf_files 등을 읽을 수 있다.
@router.get("/jobs/{job_id}/result-json")
def get_job_result_json(
    job_id: str,
    kind: str = Query(..., description="읽을 결과 JSON 종류: annotations|ocr_layout|extracted_files|annotated_pdf_files|job_meta"),
    source_index: int = Query(0, description="주석 파일 인덱스 (kind=annotations일 때만 사용)"),
    page_no: int | None = Query(None, description="1-based 페이지 번호. kind=annotations일 때만 필터링에 사용"),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (job 조회) -> Step 2 (kind별 결과 JSON 소스 확보)
          -> Step 3 (Storage 다운로드 또는 DB 필드 반환) -> Step 4 (JSON 반환)]

    AI 에이전트가 job의 다양한 결과 JSON을 읽을 때 사용한다.
    - annotations: AI/사용자 주석 JSON (EmbedPDF AnnotationTransferItem[] 형식)
    - ocr_layout: OCR 레이아웃 JSON (result_ocr_layout_storage_path)
    - extracted_files: extracted_files JSONB (DB)
    - annotated_pdf_files: annotated_pdf_files JSONB (DB)
    - job_meta: job 메타데이터 요약 (상태, 페이지 수, 파일 수 등)
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)

    if kind == "extracted_files":
        return {"kind": "extracted_files", "data": job.extracted_files or []}

    if kind == "annotated_pdf_files":
        return {"kind": "annotated_pdf_files", "data": job.annotated_pdf_files or []}

    if kind == "job_meta":
        return {
            "kind": "job_meta",
            "data": {
                "id": job.id,
                "status": job.status,
                "file_type": job.file_type,
                "original_filename": job.original_filename,
                "total_pages": job.total_pages,
                "total_files": job.total_files,
                "pipeline": job.pipeline,
                "ocr_model": job.ocr_model,
                "annotate_status": job.annotate_status,
                "annotate_mode": job.annotate_mode,
                "has_searchable_pdf": bool(job.searchable_pdf_storage_path),
                "has_pdf": bool(job.pdf_storage_path),
                "has_result_md": bool(job.result_md_storage_path),
                "has_result_csv": bool(job.result_csv_storage_path),
                "has_result_xlsx": bool(job.result_xlsx_storage_path),
                "has_ocr_layout": bool(job.result_ocr_layout_storage_path),
                "extracted_files_count": len(job.extracted_files or []),
                "annotated_pdf_files_count": len(job.annotated_pdf_files or []),
            },
        }

    if kind == "ocr_layout":
        storage_path = job.result_ocr_layout_storage_path
        if not storage_path:
            raise HTTPException(status_code=404, detail="OCR layout JSON not found")
        try:
            client = supabase_client.get_service_client()
            raw = client.storage.from_("results").download(storage_path)
            data = json.loads(raw.decode("utf-8"))
            return {"kind": "ocr_layout", "data": data}
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to download OCR layout: {e}")

    if kind == "annotations":
        all_annotations = _load_all_annotations(job, source_index, page_no)
        return {"kind": "annotations", "data": all_annotations, "total": len(all_annotations)}

    raise HTTPException(status_code=400, detail=f"Unknown kind: {kind}. Supported: annotations|ocr_layout|extracted_files|annotated_pdf_files|job_meta")


@router.get("/admin/jobs")
def admin_list_jobs(
    admin: CurrentUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
    limit: int = 100,
):
    rows = db.execute(select(Job).order_by(Job.created_at.desc()).limit(limit)).scalars().all()
    return [_job_summary(j) for j in rows]


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
        "file_size": job.file_size,
        "media_duration_seconds": job.media_duration_seconds,
        "total_work_units": job.total_work_units,
        "docling_refinement": job.use_docling_refinement,
        "docling_refinement_pages": job.total_pages if job.use_docling_refinement else 0,
        "ocr_model": job.ocr_model or "premium",
        "ocr_engine": job.ocr_engine or "easyocr",
        "cost_points": job.cost_points,
        "reserved_basic_pages": job.reserved_basic_pages,
        "reserved_premium_pages": job.reserved_premium_pages,
        "reserved_media_seconds": job.reserved_media_seconds,
        "reserved_period_start": job.reserved_period_start.isoformat() if job.reserved_period_start else None,
        "error_log": job.error_log,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "processing_started_at": job.processing_started_at.isoformat() if job.processing_started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "expires_at": job.expires_at.isoformat() if job.expires_at else None,
        "source_expires_at": _source_expires_at(job).isoformat(),
        "is_expired": _is_job_expired(job),
        "downloadable": job.status == "done" and not _is_job_expired(job),
        "xlsx_converted": bool(job.result_xlsx_storage_path),
        "xlsx_basic_converted": bool(job.result_xlsx_basic_storage_path),
        "xlsx_advanced_converted": bool(job.result_xlsx_advanced_storage_path),
        "xlsx_advanced_status": job.xlsx_advanced_status,
        "xlsx_advanced_job_id": job.result_xlsx_advanced_job_id,
        "xlsx_advanced_refundable": job.xlsx_advanced_refundable,
        "xlsx_advanced_recovery_notes": job.xlsx_advanced_recovery_notes,
        "refundable": job.refundable,
        "retry_count": job.retry_count,
        "annotated_pdf": bool(job.result_annotated_pdf_storage_path),
        "annotated_pdf_files": job.annotated_pdf_files or [],
        "annotate_status": job.annotate_status,
        "annotate_job_id": job.annotate_job_id,
        "annotate_refundable": job.annotate_refundable,
        "annotate_recovery_notes": job.annotate_recovery_notes,
        "annotate_instruction": job.annotate_instruction,
        "annotate_mode": job.annotate_mode,
        "annotate_comment_mode": job.annotate_comment_mode,
        "annotate_advanced": bool(job.annotate_advanced),
        "ediscovery_status": job.ediscovery_status,
        "ediscovery_job_id": job.ediscovery_job_id,
        "ediscovery_graphs": job.ediscovery_graphs,
        "ediscovery_metrics": job.ediscovery_metrics,
        "ediscovery_refundable": job.ediscovery_refundable,
    }


# 하위 호환: 기존 /download/{token} 엔드포인트는 Storage URL로 리디렉션
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
        base = Path(job.original_filename).stem or "result"
        ext = "md" if type == "md" else "csv"
        return FileResponse(local, media_type="text/csv" if type == "csv" else "text/markdown", filename=f"{base}.{ext}")

    try:
        url = supabase_client.get_signed_download_url(path, bucket="results", expires_in=3600)
        return {"download_url": url}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Failed to generate download URL: {e}")


# [Flow: Step 1 (token으로 job 조회) -> Step 2 (포맷별 Storage 경로 매핑) -> Step 2b (경로 없으면 on-demand 변환) -> Step 3 (signed URL 생성 후 302 redirect)]
@router.get("/dl/{token}")
def email_download_redirect(token: str, type: str = "xlsx_basic", db: Session = Depends(get_db)):
    """이메일 다운로드 버튼용 redirect 엔드포인트 (auth 없이 download_token으로 직접 다운로드)."""
    job = db.get(Job, token)
    if job is None or job.download_token != token:
        raise HTTPException(status_code=404, detail="Invalid download link")
    if job.status != "done":
        raise HTTPException(status_code=400, detail="Only completed jobs can be downloaded")

    fmt = _convert_format_alias(type)
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
