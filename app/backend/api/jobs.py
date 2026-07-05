#!/usr/bin/env python3
# [Flow: Step 1 (업로드 -> 파일 유형 감지/압축 해제/Storage 저장) -> Step 2 (비용 계산) -> Step 3 (승인 -> 포인트 차감 + Celery) -> Step 4 (상태 폴링/Storage 다운로드)]
import asyncio
import concurrent.futures
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
from typing import List

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import settings_store
from ..auth.supabase_auth import CurrentUser, get_current_admin, get_current_user
from ..core import archive_handler, cache, converter, docling_client, hwp_converter, media_loader, office_converter, pdf_preview_converter, points_service, subscription_service, supabase_client


logger = logging.getLogger(__name__)
from ..core.prompts import DEFAULT_COLUMNS
from ..db.models import Job, User
from ..db.session import get_db
from ..workers.tasks import run_job

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
    user: CurrentUser = Depends(get_current_user),
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
    user: CurrentUser = Depends(get_current_user),
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
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """TUS 업로드 완료 후 Storage의 파일을 분석하여 비용을 계산한다."""
    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
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


@router.put("/jobs/{job_id}")
def update_job(
    job_id: str,
    payload: dict,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
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
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
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
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 100,
):
    rows = db.execute(
        select(Job).where(Job.user_id == uuid.UUID(user.user_id)).order_by(Job.created_at.desc()).limit(limit)
    ).scalars().all()
    return [_job_summary(j) for j in rows]


@router.get("/jobs/{job_id}")
def get_job(job_id: str, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
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
def delete_job(job_id: str, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        supabase_client.delete_source_files(job)
    except Exception as e:
        logger.warning(f"[delete_job] {job_id} Storage 정리 중 오류 (무시): {e}")
    db.delete(job)
    db.commit()
    return {"deleted": True}


def _convert_format_alias(fmt: str) -> str:
    """구형 'xlsx'/'csv' 요청을 새 기본 변환 포맷으로 매핑한다."""
    return {"xlsx": "xlsx_basic", "csv": "csv_basic"}.get(fmt, fmt)


@router.get("/jobs/{job_id}/download")
def download_job(
    job_id: str,
    type: str = "xlsx",
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
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


_PAGE_MARKER_RE = _re.compile(r"<!--\s*페이지\s*(\d+)\s*-->", _re.IGNORECASE)


def _image_files(job: Job) -> list[tuple[int, dict]]:
    """extracted_files에서 이미지 파일만 순서대로 (page_num, info)로 반환한다."""
    files = job.extracted_files or []
    images: list[tuple[int, dict]] = []
    for idx, info in enumerate(files):
        if isinstance(info, dict) and info.get("type") == "image" and info.get("storage_path"):
            images.append((idx + 1, info))
    return images


def _build_source_file_item(info: dict, idx: int) -> dict | None:
    """단일 파일에 대한 source_files 항목을 생성한다."""
    if not isinstance(info, dict) or not info.get("storage_path"):
        return None
    ftype = info.get("type", "")
    if ftype not in ("pdf", "image", "audio", "video", "docx", "hwp"):
        return None
    try:
        storage_path = info["storage_path"]
        if ftype in ("pdf", "docx", "hwp"):
            preview_url = pdf_preview_converter.get_lowres_preview_pdf_url(storage_path, expires_in=3600)
            if not preview_url:
                # 저화질 생성 실패 시 원본 서명 URL로 폴백
                preview_url = supabase_client.get_signed_download_url(storage_path, bucket="pdfs", expires_in=3600)
            if not preview_url:
                return None
            item = {
                "name": info.get("path", info.get("storage_path", "")),
                "type": ftype,
                "url": preview_url,
                "storage_path": storage_path,
                "page_num": idx + 1,
                "result_markdown": info.get("result_markdown", ""),
                "preview_url": preview_url,
            }
            return item
        # image/audio/video는 원본 signed URL만 필요
        client = supabase_client.create_fresh_service_client()
        url = supabase_client.get_signed_download_url_with_client(client, storage_path, bucket="pdfs", expires_in=3600)
        return {
            "name": info.get("path", info.get("storage_path", "")),
            "type": ftype,
            "url": url,
            "storage_path": storage_path,
            "page_num": idx + 1,
            "result_markdown": info.get("result_markdown", ""),
        }
    except Exception:
        return None


def _source_files(job: Job) -> list[dict]:
    """extracted_files에서 미리보기 가능한 파일 목록과 파일별 파싱 결과를 반환한다.

    병렬 처리로 signed URL 생성 시간을 줄인다. max_workers=3으로 제한하여
    Supabase Storage rate limit과 스레드 안전 문제를 완화한다.
    """
    files = job.extracted_files or []
    if not files:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(_build_source_file_item, info, idx) for idx, info in enumerate(files)]
        results = [f.result() for f in futures]
    return [item for item in results if item is not None]


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
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """완료된 작업의 마크다운 결과를 페이지 단위로 조회한다."""
    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
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

    selected = [content for num, content in pages if start_page <= num <= effective_end]
    partial_markdown = "\n\n---\n\n".join(selected)

    source_url = None
    source_type = None
    image_urls: list[str] = []
    if job.pdf_storage_path:
        try:
            source_type = _detect_source_type(job)
            source_url = pdf_preview_converter.get_lowres_preview_pdf_url(job.pdf_storage_path, expires_in=3600)
            if not source_url:
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
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """완료된 작업의 페이지 목록 메타데이터를 반환한다."""
    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
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
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
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
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """특정 페이지의 마크다운만 갱신하고 전체 편집 마크다운을 다시 저장한다."""
    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
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
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
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
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """사용자가 편집한 xlsx 파일을 업로드하고 Storage 경로를 저장한다."""
    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
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
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """저장된 편집 xlsx의 signed download URL을 반환한다."""
    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
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
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Excel 고급 변환 완전 실패 시 재시도 또는 포인트 환불을 처리한다."""
    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
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


@router.post("/jobs/{job_id}/action")
def job_action(
    job_id: str,
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """문서 파싱 최종 실패 시 재시도 또는 포인트 환불을 처리한다."""
    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
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
