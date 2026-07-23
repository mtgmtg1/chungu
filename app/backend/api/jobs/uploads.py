from __future__ import annotations

import json
import logging
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, List

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile, status
from pypdf import PdfReader
from sqlalchemy.orm import Session

from ...auth.api_key_auth import require_api_key_or_session
from ...auth.supabase_auth import CurrentUser
from ...core import archive_handler, docling_client, hwp_converter, media_loader, points_service, subscription_service, supabase_client
from ...core.job_helpers import parse_columns
from ...db.models import Job, User
from ...db.session import get_db
from ... import settings_store
from ._shared import (
    _analyze_extracted_files,
    _calculate_media_info,
    _count_pages_with_docling,
    _job_summary,
    _normalize_display_name,
    _require_job_access,
    _require_job_not_expired,
    _subscription_would_exceed_for_model,
    get_current_user_or_api_key,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api', tags=['jobs'])

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

    original_filename = _normalize_display_name(files[0].filename if is_single_file else f"{len(files)}_files.zip")

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
                    {"path": _normalize_display_name(str(p.relative_to(tmp_path))), "type": media_loader.detect_file_type(p), "size": p.stat().st_size}
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
    cost_basic = points_service.calculate_cost(db, pages=pages, image_count=image_count, audio_seconds=audio_seconds, video_seconds=video_seconds, docling_refinement_pages=0, ocr_model="basic")
    cost_premium = points_service.calculate_cost(db, pages=pages, image_count=image_count, audio_seconds=audio_seconds, video_seconds=video_seconds, docling_refinement_pages=docling_refinement_pages, ocr_model="premium")
    cost = cost_premium if ocr_model == "premium" else cost_basic
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
        "balance": user.points_balance,
    }



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
    original_filename = _normalize_display_name(files[0]["name"] if is_single_file else f"{len(files)}_files.zip")

    job = Job(
        user_id=uuid.UUID(user.user_id),
        email=user.email,
        pipeline=pipeline,
        columns=parse_columns(payload.get("columns", "")),
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

    # 첫 업로드 시 사용자가 입력한 e-Discovery 컨텍스트(프로젝트 주요/중요 사항)를 저장한다.
    ediscovery_context = str(payload.get("ediscovery_context", "") or "").strip()
    if ediscovery_context:
        job.ediscovery_context = ediscovery_context

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
                        {"path": _normalize_display_name(str(p.relative_to(tmp_path))), "type": media_loader.detect_file_type(p), "size": p.stat().st_size}
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
                    {"path": _normalize_display_name(str(p.relative_to(tmp_path))), "type": media_loader.detect_file_type(p), "size": p.stat().st_size}
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
            "points_balance": status["points_balance"],
            "monthly_credits": status["monthly_credits"],
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
        "balance": 0,
    }



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
    if not existing_files and job.pdf_storage_path and job.file_type in _PREVIEW_DOCUMENT_TYPES:
        existing_markdown = _extract_single_file_markdown(job)
        existing_files = [{
            "path": _normalize_display_name(job.original_filename or Path(job.pdf_storage_path).name),
            "type": job.file_type,
            "size": job.file_size or 0,
            "duration": 0,
            "result_markdown": existing_markdown,
            "storage_path": job.pdf_storage_path,
        }]

    merged_files = existing_files + new_extracted_infos
    job.extracted_files = merged_files
    # 단일 파일 타입 Job에 새 파일이 추가되면 mixed로 전환
    if job.file_type in _PREVIEW_DOCUMENT_TYPES and len(merged_files) > 1:
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
        docling_refinement_pages = new_pages if job.use_docling_refinement else 0
        try:
            result = subscription_service.reserve_usage(
                db,
                db_user,
                basic_pages=basic_pages,
                premium_pages=premium_pages,
                audio_seconds=new_audio_seconds,
                video_seconds=new_video_seconds,
                docling_refinement_pages=docling_refinement_pages,
            )
            job.cost_points += result["cost_points"]
            db.commit()
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
        job.columns = parse_columns(payload["columns"])
    if "prompt" in payload:
        job.prompt = str(payload["prompt"]).strip()
    # [Flow: e-Discovery 분석 맥락 업데이트 — 비용 확인 팝업에서 입력된 맥락을 저장]
    if "ediscovery_context" in payload:
        ediscovery_context = str(payload.get("ediscovery_context", "") or "").strip()
        job.ediscovery_context = ediscovery_context

    # 오디오/비디오가 포함된 작업은 고급 모델로 강제
    has_media = job.media_duration_seconds > 0
    if has_media and job.ocr_model == "basic":
        job.ocr_model = "premium"

    db.commit()
    return _job_summary(job)



