#!/usr/bin/env python3
# [Flow: Step 1 (업로드 -> 파일 유형 감지/압축 해제/Storage 저장) -> Step 2 (비용 계산) -> Step 3 (승인 -> 포인트 차감 + Celery) -> Step 4 (상태 폴링/Storage 다운로드)]
import asyncio
import json
import logging
import re as _re
import tempfile
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import List

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import settings_store
from ..auth.supabase_auth import CurrentUser, get_current_admin, get_current_user
from ..core import archive_handler, converter, docling_client, hwp_converter, media_loader, office_converter, pdf_preview_converter, points_service, supabase_client


logger = logging.getLogger(__name__)
from ..core.prompts import DEFAULT_COLUMNS
from ..db.models import Job
from ..db.session import get_db
from ..workers.tasks import run_job

router = APIRouter(prefix="/api", tags=["jobs"])

# OCR 업로드 원본 파일의 Supabase Storage 보관 기간 (시간)
UPLOAD_RETENTION_HOURS = 48


def _source_expires_at(job: Job) -> datetime:
    """작업 생성 시점으로부터 48시간 후의 원본 업로드 만료 시각을 계산한다."""
    created = job.created_at or datetime.now(timezone.utc)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created + timedelta(hours=UPLOAD_RETENTION_HOURS)


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
        raise HTTPException(status_code=400, detail="파일을 선택하세요")
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
            storage_path = supabase_client.upload_pdf(job.id, data, files[0].filename)
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
            storage_path = supabase_client.upload_pdf(job.id, data, files[0].filename)
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
        raise HTTPException(status_code=400, detail="파일을 선택하세요")

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
            raise HTTPException(status_code=400, detail=f"지원하지 않는 파일 형식입니다: {f['name']}")

    max_mb = int(settings_store.get_setting(db, "max_file_mb") or "200")
    total_size = sum(f.get("size", 0) for f in files)
    if total_size > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"전체 파일이 너무 큽니다 (최대 {max_mb}MB)")

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
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    if job.status != "uploading":
        raise HTTPException(status_code=400, detail="업로드 중인 작업만 처리할 수 있습니다")

    files_info = payload.get("files", [])
    if not files_info:
        raise HTTPException(status_code=400, detail="파일 정보가 없습니다")

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
                storage_path = supabase_client.upload_input(job.id, zip_path.read_bytes(), zip_path.name, "application/zip")
                job.pdf_storage_path = storage_path
                job.file_type = "mixed"

        max_pages = int(settings_store.get_setting(db, "max_pages") or "2000")
        if pages > max_pages:
            db.delete(job)
            db.commit()
            raise HTTPException(status_code=413, detail=f"페이지가 너무 많습니다 (최대 {max_pages})")

        job.total_pages = pages
        job.status = "pending"
        db.commit()
    except HTTPException:
        raise
    except Exception as e:
        job.status = "error"
        job.error_log = str(e)
        db.commit()
        raise HTTPException(status_code=502, detail=f"파일 처리 실패: {e}")

    has_media = audio_seconds > 0 or video_seconds > 0
    if has_media and job.ocr_model == "basic":
        job.ocr_model = "premium"
        db.commit()

    docling_refinement_pages = pages if job.use_docling_refinement else 0
    user_id = uuid.UUID(user.user_id)
    cost_basic = points_service.calculate_cost(db, pages=pages, image_count=image_count, audio_seconds=audio_seconds, video_seconds=video_seconds, docling_refinement_pages=0, ocr_model="basic", user_id=user_id)
    cost_premium = points_service.calculate_cost(db, pages=pages, image_count=image_count, audio_seconds=audio_seconds, video_seconds=video_seconds, docling_refinement_pages=docling_refinement_pages, ocr_model="premium", user_id=user_id)
    ocr_model = job.ocr_model or "premium"
    cost = cost_premium if ocr_model == "premium" else cost_basic
    free_remaining = points_service.get_daily_free_remaining(db, user_id)

    return {
        "job_id": job.id,
        "status": job.status,
        "file_type": job.file_type,
        "total_pages": pages,
        "total_files": total_files,
        "media_duration_seconds": audio_seconds + video_seconds,
        "docling_refinement": job.use_docling_refinement,
        "docling_refinement_pages": docling_refinement_pages,
        "ocr_model": ocr_model,
        "ocr_engine": job.ocr_engine,
        "has_media": has_media,
        "cost": cost,
        "cost_basic": cost_basic,
        "cost_premium": cost_premium,
        "free_pages_remaining": free_remaining,
        "balance": user.points_balance,
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
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    if job.status != "pending":
        raise HTTPException(status_code=400, detail="대기 중인 작업만 수정할 수 있습니다")

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
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    if job.status != "pending":
        raise HTTPException(status_code=400, detail="이미 처리되었거나 취소된 작업입니다")

    from ..db.models import User

    db_user = db.get(User, job.user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    # 작업 정보에서 비용 재계산
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
    if job.file_type in media_loader.DOCLING_TYPES or job.file_type in media_loader.HWP_TYPES:
        image_count = 0
        audio_seconds = 0
        video_seconds = 0

    docling_refinement_pages = job.total_pages if job.use_docling_refinement else 0
    ocr_model = job.ocr_model or "premium"
    cost = points_service.calculate_cost(db, pages=pages, image_count=image_count, audio_seconds=audio_seconds, video_seconds=video_seconds, docling_refinement_pages=docling_refinement_pages, ocr_model=ocr_model, user_id=job.user_id)
    if ocr_model == "basic":
        points_service.record_daily_usage(db, job.user_id, pages + image_count)
    try:
        points_service.spend_points(db, db_user, cost["points"], f"미디어 작업: {job.original_filename}")
    except ValueError as e:
        raise HTTPException(status_code=402, detail=str(e))

    job.cost_points = cost["points"]
    job.status = "queued"
    db.commit()

    run_job.delay(job.id)
    return {"job_id": job.id, "status": job.status, "remaining_points": db_user.points_balance}


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
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
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
        summary["cost_basic"] = points_service.calculate_cost(db, pages=pages, image_count=image_count, audio_seconds=audio_seconds, video_seconds=video_seconds, docling_refinement_pages=0, ocr_model="basic", user_id=user_id)
        summary["cost_premium"] = points_service.calculate_cost(db, pages=pages, image_count=image_count, audio_seconds=audio_seconds, video_seconds=video_seconds, docling_refinement_pages=docling_refinement_pages, ocr_model="premium", user_id=user_id)
        summary["free_pages_remaining"] = points_service.get_daily_free_remaining(db, user_id)
        summary["cost"] = summary["cost_basic"] if (job.ocr_model or "premium") == "basic" else summary["cost_premium"]
    return summary


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    try:
        supabase_client.delete_source_files(job)
    except Exception as e:
        logger.warning(f"[delete_job] {job_id} Storage 정리 중 오류 (무시): {e}")
    db.delete(job)
    db.commit()
    return {"deleted": True}


@router.get("/jobs/{job_id}/download")
def download_job(
    job_id: str,
    type: str = "xlsx",
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    if job.status != "done":
        raise HTTPException(status_code=400, detail="완료된 작업만 다운로드할 수 있습니다")

    # csv와 xlsx는 번들: xlsx 변환 완료 시에만 다운로드, 미변환 시 동일 요금으로 변환 후 제공
    if type in ("csv", "xlsx"):
        _ensure_xlsx_bundle(job, db)

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
        return {"download_url": url}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"다운로드 링크 생성 실패: {e}")


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


def _source_files(job: Job) -> list[dict]:
    """extracted_files에서 미리보기 가능한 파일 목록과 파일별 파싱 결과를 반환한다."""
    files = job.extracted_files or []
    out: list[dict] = []
    for idx, info in enumerate(files):
        if not isinstance(info, dict) or not info.get("storage_path"):
            continue
        ftype = info.get("type", "")
        if ftype not in ("pdf", "image", "audio", "video", "docx", "hwp"):
            continue
        try:
            url = supabase_client.get_signed_download_url(info["storage_path"], bucket="pdfs", expires_in=3600)
            item = {
                "name": info.get("path", info.get("storage_path", "")),
                "type": ftype,
                "url": url,
                "page_num": idx + 1,
                "result_markdown": info.get("result_markdown", ""),
            }
            if ftype in ("docx", "hwp"):
                item["preview_url"] = pdf_preview_converter.get_preview_pdf_url(info["storage_path"], expires_in=3600)
            out.append(item)
        except Exception:
            pass
    return out


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


def _ensure_xlsx_bundle(job: Job, db: Session) -> None:
    """CSV/XLSX 다운로드가 가능하도록 xlsx 변환을 한 번 수행한다. 이미 변환된 경우 아무것도 하지 않는다."""
    if job.result_xlsx_storage_path:
        return
    from ..db.models import User
    db_user = db.get(User, job.user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
    units = job.total_pages if job.total_pages else (job.total_files or 1)
    cost = units * 3
    try:
        points_service.spend_points(db, db_user, cost, f"xlsx 변환: {job.original_filename}")
    except ValueError as e:
        raise HTTPException(status_code=402, detail=str(e))
    markdown = _get_markdown_content(job)
    if not markdown.strip():
        raise HTTPException(status_code=400, detail="변환할 마크다운 결과가 없습니다")
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "result.xlsx"
        office_converter.markdown_to_xlsx(markdown, out_path)
        storage_path = supabase_client.upload_office_result(job.id, out_path, "xlsx")
    job.result_xlsx_storage_path = storage_path
    db.commit()


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
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    if not job.result_md_storage_path and not job.result_edited_md_storage_path:
        raise HTTPException(status_code=400, detail="결과 파일이 준비되지 않았습니다")

    try:
        markdown = _get_markdown_content(job)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"결과 미리보기 생성 실패: {e}")

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
            if source_type in ("docx", "hwp"):
                source_url = pdf_preview_converter.get_preview_pdf_url(job.pdf_storage_path, expires_in=3600)
            else:
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
    return {
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


@router.get("/jobs/{job_id}/preview/pages")
def preview_job_pages(
    job_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """완료된 작업의 페이지 목록 메타데이터를 반환한다."""
    job = db.get(Job, job_id)
    if job is None or str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    if not job.result_md_storage_path and not job.result_edited_md_storage_path:
        raise HTTPException(status_code=400, detail="결과 파일이 준비되지 않았습니다")

    try:
        markdown = _get_markdown_content(job)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"결과 미리보기 생성 실패: {e}")

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
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    if job.status != "done":
        raise HTTPException(status_code=400, detail="완료된 작업만 수정할 수 있습니다")

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
            raise HTTPException(status_code=502, detail=f"편집 마크다운 저장 실패: {e}")
    job.result_edited_md_storage_path = storage_path
    job.result_edited_md_path = ""
    db.commit()
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
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    if job.status != "done":
        raise HTTPException(status_code=400, detail="완료된 작업만 수정할 수 있습니다")

    new_content = str(payload.get("markdown", "")).strip()
    try:
        markdown = _get_markdown_content(job)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"마크다운 로드 실패: {e}")

    pages = _split_markdown_by_pages(markdown)
    if not pages:
        raise HTTPException(status_code=400, detail="페이지가 없습니다")
    target_idx = next((idx for idx, (num, _) in enumerate(pages) if num == page_num), None)
    if target_idx is None:
        raise HTTPException(status_code=404, detail="해당 페이지를 찾을 수 없습니다")

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
            raise HTTPException(status_code=502, detail=f"편집 마크다운 저장 실패: {e}")
    job.result_edited_md_storage_path = storage_path
    job.result_edited_md_path = ""
    db.commit()
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
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    if job.status != "done":
        raise HTTPException(status_code=400, detail="완료된 작업만 변환할 수 있습니다")

    fmt = str(payload.get("format", "")).lower()
    if fmt not in ("xlsx", "docx", "pptx"):
        raise HTTPException(status_code=400, detail="지원하지 않는 변환 형식입니다")

    from ..db.models import User

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
            return {"download_url": url, "format": fmt, "storage_path": existing_path}
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"다운로드 링크 생성 실패: {e}")

    # xlsx 변환은 페이지/파일당 3원 차감
    if fmt == "xlsx":
        units = job.total_pages if job.total_pages else (job.total_files or 1)
        cost = units * 3
        try:
            points_service.spend_points(db, db_user, cost, f"xlsx 변환: {job.original_filename}")
        except ValueError as e:
            raise HTTPException(status_code=402, detail=str(e))

    try:
        markdown = _get_markdown_content(job)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / f"result.{fmt}"
            if fmt == "xlsx":
                office_converter.markdown_to_xlsx(markdown, out_path)
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

    return {"download_url": url, "format": fmt, "storage_path": storage_path}


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
        "docling_refinement": job.use_docling_refinement,
        "docling_refinement_pages": job.total_pages if job.use_docling_refinement else 0,
        "ocr_model": job.ocr_model or "premium",
        "ocr_engine": job.ocr_engine or "easyocr",
        "cost_points": job.cost_points,
        "error_log": job.error_log,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "expires_at": job.expires_at.isoformat() if job.expires_at else None,
        "source_expires_at": _source_expires_at(job).isoformat(),
        "downloadable": job.status == "done",
        "xlsx_converted": bool(job.result_xlsx_storage_path),
    }


# 하위 호환: 기존 /download/{token} 엔드포인트는 Storage URL로 리디렉션
@router.get("/download/{token}")
def legacy_download(token: str, type: str = "csv", db: Session = Depends(get_db)):
    job = db.get(Job, token)
    if job is None or job.download_token != token:
        raise HTTPException(status_code=404, detail="유효하지 않은 다운로드 링크입니다")
    if job.expires_at and job.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="다운로드 링크가 만료되었습니다")

    if type == "csv":
        if not job.result_xlsx_storage_path:
            raise HTTPException(status_code=402, detail="CSV는 xlsx 변환 후에 다운로드할 수 있습니다")
        path = job.result_csv_storage_path
    else:
        path = job.result_md_storage_path
    if not path:
        # Storage로 이전되지 않은 예전 파일은 로컬 경로 사용
        local = job.result_csv_path if type == "csv" else job.result_md_path
        if not local or not Path(local).exists():
            raise HTTPException(status_code=404, detail="결과 파일이 없습니다")
        base = Path(job.original_filename).stem or "result"
        ext = "md" if type == "md" else "csv"
        return FileResponse(local, media_type="text/csv" if type == "csv" else "text/markdown", filename=f"{base}.{ext}")

    try:
        url = supabase_client.get_signed_download_url(path, bucket="results", expires_in=3600)
        return {"download_url": url}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"다운로드 링크 생성 실패: {e}")
