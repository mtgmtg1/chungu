#!/usr/bin/env python3
# [Flow: Step 1 (job 로드) -> Step 2 (Storage에서 입력 다운로드) -> Step 3 (PDF: vision|hybrid / 미디어: 파일별 처리) -> Step 4 (Excel/CSV/MD 저장) -> Step 5 (Storage 업로드) -> Step 6 (DB/이메일)]
import json
import logging
import tempfile
import time
import traceback
import zipfile
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from pypdf import PdfReader
from sqlalchemy import text as sql_text

from ..celery_app import celery
from celery.signals import worker_ready
from ..config import settings
from ..core import archive_handler, converter, excel_writer, media_loader, merge, pdf_annotate_converter, pdf_text_layer, subscription_service, supabase_client, xlsx_advanced_converter
from ..core.ocr_client import has_pdf_text_layer
from ..core.pipeline_docling import run_docling, run_hwp
from ..core.pipeline_hybrid import run_hybrid
from ..core.pipeline_media import run_media
from ..core.pipeline_vision import run_vision
from ..db.models import Job, User
from ..db.session import SessionLocal
from .. import email_sender, settings_store

logger = logging.getLogger(__name__)

MAX_PAGE_SIDE_MM = 350
MM_PER_PT = 0.3528
MAX_RETRY_COUNT = 3


def _upload_ocr_layout(db, job: Job, layout_by_page: dict[int, dict]) -> None:
    """[Flow: Step 1 (layout_by_page를 JSON 직렬화) -> Step 2 (results 버킷에 업로드)
          -> Step 3 (Job DB에 경로 저장)]

    PaddleOCR로 확보한 layout_by_page를 Storage에 저장해 AI agent의 get_elements/search_text가
    재실행하지 않도록 한다.
    """
    if not layout_by_page:
        return
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
        logger.info(f"[run_job:{job.id}] OCR layout 저장 완료: {storage_path}")
    except Exception as e:
        logger.warning(f"[run_job:{job.id}] OCR layout 저장 실패: {e}")

# [Flow: Step 1 (worker_ready 시그널 수신) -> Step 2 (DB에서 중단된 job 조회) -> Step 3 (retry_count < 3인 job 재시도) -> Step 4 (>= 3인 job error로 변경)]
@worker_ready.connect
def recover_stuck_jobs(sender=None, **kwargs):
    """Worker 시작 시 중단된 job(queued/rendering/ocr/merging)을 자동으로 재시도한다."""
    time.sleep(3)

    db = None
    for attempt in range(2):
        try:
            db = SessionLocal()
            break
        except Exception as e:
            logger.warning(f"[recover] DB 연결 실패 (attempt {attempt + 1}/2): {e}")
            if attempt == 0:
                time.sleep(5)

    if db is None:
        logger.error("[recover] DB 연결 실패, 중단된 job 복구를 건너뜁니다")
        return

    try:
        stuck_statuses = ("queued", "rendering", "ocr", "merging")
        jobs = db.query(Job).filter(Job.status.in_(stuck_statuses)).all()

        if not jobs:
            logger.info("[recover] 중단된 job 없음")
            return

        recovered = 0
        exhausted = 0

        for job in jobs:
            if job.retry_count < MAX_RETRY_COUNT:
                job.retry_count += 1
                job.status = "queued"
                db.commit()
                run_job.delay(job.id)
                recovered += 1
                logger.info(f"[recover] job {job.id} 재시도 ({job.retry_count}/{MAX_RETRY_COUNT})")
            else:
                _release_subscription_usage(db, job)
                job.status = "error"
                job.refundable = True
                job.error_log = (job.error_log + f"\nRetry limit exceeded (server restart, {MAX_RETRY_COUNT} attempts)").strip()
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
                exhausted += 1
                logger.warning(f"[recover] job {job.id} retry limit exceeded, transitioned to error with refundable=True")

        logger.info(f"[recover] 복구 완료: {recovered}개 재시도, {exhausted}개 error 전환")
    except Exception as e:
        logger.exception(f"[recover] 중단된 job 복구 중 오류: {e}")
    finally:
        db.close()


def _set_status(db, job: Job, status: str) -> None:
    job.status = status
    db.commit()


def _release_subscription_usage(db, job: Job) -> None:
    """최종 실패한 작업이 차감한 구독 사용량을 되돌린다.
    Job에 예약 기록이 있으면 해당 기록을 우선 사용하고, 없으면 extracted_files로부터 계산한다."""
    if not job.user_id:
        return
    db_user = db.get(User, job.user_id)
    if db_user is None:
        return

    # 예약 기록이 있으면 정확한 기간과 단위로 환불
    if job.reserved_period_start:
        try:
            subscription_service.release_usage(
                db,
                db_user,
                basic_pages=job.reserved_basic_pages,
                premium_pages=job.reserved_premium_pages,
                media_seconds=job.reserved_media_seconds,
                period_start=job.reserved_period_start,
            )
            logger.info(f"[run_job:{job.id}] 구독 사용량 환불 완료 (기록 기준)")
        except Exception as e:
            logger.warning(f"[run_job:{job.id}] 구독 사용량 환불 중 오류 (무시): {e}")
        return

    # fallback: extracted_files로부터 계산 (구식 job 지원)
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
    ocr_model = job.ocr_model or "premium"
    basic_pages = pages + image_count if ocr_model == "basic" else 0
    premium_pages = pages + image_count if ocr_model != "basic" else 0
    premium_pages += pages if job.use_docling_refinement else 0
    media_seconds = audio_seconds + video_seconds
    try:
        subscription_service.release_usage(
            db,
            db_user,
            basic_pages=basic_pages,
            premium_pages=premium_pages,
            media_seconds=media_seconds,
        )
    except Exception as e:
        logger.warning(f"[run_job:{job.id}] 구독 사용량 환불 중 오류 (무시): {e}")


# [Flow: Step 1 (retry_count 증가) -> Step 2 (3회 미만이면 retrying 상태로 재시도) -> Step 3 (3회 이상이면 error + refundable + 이메일)]
def _handle_job_failure(db, job: Job, error_detail: str) -> dict:
    """run_job 실행 실패 시 retry_count를 증가시키고 재시도 또는 최종 에러 상태로 전환한다."""
    job.retry_count += 1
    job.error_log = error_detail
    db.commit()

    if job.retry_count < MAX_RETRY_COUNT:
        job.status = "retrying"
        db.commit()
        run_job.delay(job.id)
        logger.info(f"[run_job:{job.id}] 재시도 예약 ({job.retry_count}/{MAX_RETRY_COUNT})")
        return {"job_id": job.id, "status": "retrying", "retry_count": job.retry_count}

    _release_subscription_usage(db, job)
    job.status = "error"
    job.refundable = True
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    logger.warning(f"[run_job:{job.id}] 재시도 한계 초과, error + refundable 전환")
    try:
        user_lang = "en"
        if job.user_id:
            user = db.get(User, job.user_id)
            if user and user.language:
                user_lang = user.language
        subject, html = email_sender.build_error_email(job.id, job.original_filename, error_detail, lang=user_lang)
        email_sender.send_email(db, job.email, subject, html)
    except Exception:  # noqa: BLE001
        pass
    return {"job_id": job.id, "error": error_detail, "retry_count": job.retry_count}


def count_oversized_pages(file_path: Path) -> tuple[int, int]:
    """PDF에서 350mm를 초과하는 페이지 수를 반환한다. (oversized_count, total_pages)"""
    try:
        reader = PdfReader(str(file_path))
        total = len(reader.pages)
        oversized = 0
        for page in reader.pages:
            w = float(page.mediabox.width) * MM_PER_PT
            h = float(page.mediabox.height) * MM_PER_PT
            if w > MAX_PAGE_SIDE_MM or h > MAX_PAGE_SIDE_MM:
                oversized += 1
        return oversized, total
    except Exception:
        return 0, 0


def _build_and_upload_searchable_pdf(
    db,
    job: Job,
    input_path: Path,
    layout_by_page: dict[int, dict],
    dpi: int,
) -> None:
    """[Flow: Step 1 (원본 PDF를 페이지별 이미지로 렌더링 + deskew 보정) -> Step 2 (보정된 이미지로 새 PDF 생성)
          -> Step 3 (layout_by_page에서 OCR 결과 추출) -> Step 4 (새 PDF에 투명 텍스트 레이어 추가)
          -> Step 5 (searchable PDF Storage 업로드) -> Step 6 (OCR layout Storage 업로드) -> Step 7 (Job DB 저장)]

    PaddleOCR이 반환한 페이지별 layout로부터 텍스트/bbox를 추출해 deskew 보정된 PDF에
    투명 텍스트 레이어를 입히고, 그 결과를 Storage에 업로드한다.
    원본 PDF가 아닌 deskew 보정된 페이지 이미지로 새 PDF를 만들어 기울어진 스캔 문서도
    수평으로 정렬된 searchable PDF를 제공한다.
    동시에 OCR layout을 Storage에 저장해 AI agent의 get_elements/search_text가 재사용할 수 있게 한다.
    """
    from ..core.image_deskew import deskew_image
    from ..core.ocr_client import render_pdf

    # OCR layout을 먼저 Storage에 저장해 agent 도구가 재사용할 수 있게 한다.
    if layout_by_page:
        _upload_ocr_layout(db, job, layout_by_page)

    page_ocr_results = pdf_text_layer.extract_page_ocr_results_from_layout(layout_by_page)
    if not page_ocr_results:
        logger.warning(
            f"[run_job:{job.id}] searchable PDF 생성 스킵: page_ocr_results 비어있음 "
            f"(layout_by_page keys={list(layout_by_page.keys())}, "
            f"첫 페이지 layout keys={list(layout_by_page[list(layout_by_page.keys())[0]].keys()) if layout_by_page else 'N/A'})"
        )
        return
    try:
        # Step 1: 원본 PDF를 페이지별 이미지로 렌더링
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_dir = Path(tmpdir)
            render_pdf(str(input_path), str(tmp_dir), dpi=dpi)

            # Step 2: 각 페이지 이미지에 deskew 적용
            deskewed_dir = tmp_dir / "deskewed"
            deskewed_paths: dict[int, Path] = {}
            for img_path in sorted(tmp_dir.glob("page-*.png")):
                try:
                    page_num = int(img_path.stem.split("-")[-1])
                except Exception:
                    continue
                deskewed_path, applied = deskew_image(img_path, output_dir=deskewed_dir)
                deskewed_paths[page_num] = deskewed_path

            if not deskewed_paths:
                # 렌더링 실패 시 원본 PDF에 텍스트 레이어만 추가 (폴백)
                pdf_bytes = input_path.read_bytes()
                searchable_pdf_bytes = pdf_text_layer.add_text_layer_from_ocr(pdf_bytes, page_ocr_results, dpi=dpi, language="ko")
                storage_path = supabase_client.upload_input(BytesIO(searchable_pdf_bytes), "searchable.pdf", job.id)
                job.searchable_pdf_storage_path = storage_path
                db.commit()
                logger.info(f"[run_job:{job.id}] searchable PDF 업로드 완료 (폴백 — deskew 미적용): {storage_path}")
                return

            # Step 3: deskew 적용된 이미지로 새 PDF 생성
            doc = fitz.open()
            for page_num in sorted(deskewed_paths.keys()):
                img_path = deskewed_paths[page_num]
                img = fitz.Pixmap(str(img_path))
                width_pt = img.width * 72.0 / dpi
                height_pt = img.height * 72.0 / dpi
                page = doc.new_page(width=width_pt, height=height_pt)
                page.insert_image(fitz.Rect(0, 0, width_pt, height_pt), filename=str(img_path))
            deskewed_pdf_bytes = doc.tobytes()
            doc.close()

            # Step 4: 새 PDF에 투명 텍스트 레이어 추가
            searchable_pdf_bytes = pdf_text_layer.add_text_layer_from_ocr(deskewed_pdf_bytes, page_ocr_results, dpi=dpi, language="ko")

        storage_path = supabase_client.upload_input(BytesIO(searchable_pdf_bytes), "searchable.pdf", job.id)
        job.searchable_pdf_storage_path = storage_path
        db.commit()
        logger.info(f"[run_job:{job.id}] searchable PDF 업로드 완료 (deskew 적용): {storage_path}")
    except Exception as e:
        logger.warning(f"[run_job:{job.id}] searchable PDF 생성/업로드 실패: {e}")


def _register_searchable_pdf_if_text_layer(db, job: Job, input_path: Path) -> None:
    """[Flow: Step 1 (PDF 텍스트 레이어 검사) -> Step 2 (있으면 원본을 searchable PDF로 등록)]

    원본 PDF에 텍스트 레이어가 있으면 별도 OCR 텍스트 레이어 생성 없이 원본 PDF를
    주석 검색용 searchable PDF로 그대로 등록한다. 디지털 텍스트 PDF의 정확한 좌표를
    주석에 직접 활용할 수 있다.
    """
    if job.searchable_pdf_storage_path:
        return  # 이미 등록되어 있으면 스킵
    try:
        if not has_pdf_text_layer(str(input_path)):
            return
        # 원본 PDF를 Storage에 searchable.pdf로 업로드
        pdf_bytes = input_path.read_bytes()
        storage_path = supabase_client.upload_input(BytesIO(pdf_bytes), "searchable.pdf", job.id)
        job.searchable_pdf_storage_path = storage_path
        db.commit()
        logger.info(f"[run_job:{job.id}] 원본 PDF에 텍스트 레이어 있음 → searchable PDF로 등록: {storage_path}")
    except Exception as e:
        logger.warning(f"[run_job:{job.id}] 원본 PDF searchable 등록 실패: {e}")


def _image_to_searchable_pdf(
    image_path: Path,
    layout_raw: dict,
    dpi: int = 300,
) -> bytes:
    """[Flow: Step 1 (이미지 deskew 보정) -> Step 2 (보정된 이미지로 1페이지 PDF 생성)
          -> Step 3 (OCR layout에서 텍스트/bbox 추출) -> Step 4 (투명 텍스트 레이어 추가)
          -> Step 5 (searchable PDF bytes 반환)]

    단일 이미지를 deskew 보정 후 1페이지 PDF로 변환하고, PaddleOCR layout의 텍스트/bbox를
    투명 텍스트 레이어로 추가해 searchable PDF를 만든다.
    """
    from ..core.image_deskew import deskew_image

    # Step 1: deskew 보정 적용
    deskewed_path, _applied = deskew_image(image_path)

    # Step 2: 보정된 이미지로 1페이지 PDF 생성
    img = fitz.Pixmap(str(deskewed_path))
    doc = fitz.open()
    try:
        width_pt = img.width * 72.0 / dpi
        height_pt = img.height * 72.0 / dpi
        page = doc.new_page(width=width_pt, height=height_pt)
        page.insert_image(fitz.Rect(0, 0, width_pt, height_pt), filename=str(deskewed_path))
        pdf_bytes = doc.tobytes()
    finally:
        doc.close()

    page_ocr_results = pdf_text_layer.extract_page_ocr_results_from_layout({1: layout_raw})
    if page_ocr_results:
        return pdf_text_layer.add_text_layer_from_ocr(pdf_bytes, page_ocr_results, dpi=dpi, language="ko")
    return pdf_bytes


@celery.task(name="backend.workers.tasks.run_job")
def run_job(job_id: str) -> dict:
    """업로드된 파일(단일 PDF 또는 멀티미디어)을 변환하는 메인 워커 태스크."""
    db = SessionLocal()
    job = db.get(Job, job_id)
    if job is None:
        db.close()
        return {"error": "job not found"}

    # 중복 실행 방지: queued 또는 retrying이 아니면 스킵
    if job.status not in ("queued", "retrying"):
        db.close()
        return {"job_id": job_id, "skipped": True, "reason": f"status={job.status}"}

    # 재시도로 들어온 작업은 queued로 전환하여 정상 실행
    if job.status == "retrying":
        _set_status(db, job, "queued")

    # 실제 처리 시작 시점을 기록한다. 새로고침 후에도 시간진행바가 0%로 돌아가지 않도록 백엔드에서 관리.
    if not job.processing_started_at:
        job.processing_started_at = datetime.now(timezone.utc)
        db.commit()

    try:
        # Step 1: 런타임 설정 주입
        endpoint = job.endpoint or settings_store.get_setting(db, "llm_endpoint")
        model = job.model or settings_store.get_setting(db, "llm_model")
        api_key = settings_store.get_setting(db, "llm_api_key")
        columns = job.columns or []
        work_dir = Path(settings.data_dir) / "jobs" / job_id
        work_dir.mkdir(parents=True, exist_ok=True)
        out_dir = work_dir / "result"
        out_dir.mkdir(parents=True, exist_ok=True)

        errors: list[str] = []
        tabs: dict[str, list[dict]] = {}
        rows: list[dict] = []
        page_tables: list[tuple[int, str]] = []
        results: list[tuple[str, str, str]] = []
        all_page_contents: list[tuple[int, str]] = []
        extracted_info: list[dict] = []
        fmt = ""

        # media LLM 설정 (PDF vision 및 멀티미디어 공통 사용)
        media_ep = settings_store.get_setting(db, "media_llm_endpoint") or settings.media_llm_endpoint
        media_mdl = settings_store.get_setting(db, "media_llm_model") or settings.media_llm_model
        media_key = settings_store.get_setting(db, "media_llm_api_key") or settings.media_llm_api_key
        llm_workers = int(settings_store.get_setting(db, "llm_max_workers") or settings.llm_max_workers)
        media_workers = int(settings_store.get_setting(db, "media_max_workers") or settings.media_max_workers)

        # Docling 설정
        docling_enabled = settings_store.get_setting(db, "docling_enabled") == "1"
        ocr_model = job.ocr_model or "premium"
        ocr_engine = job.ocr_engine or "easyocr"
        # 기본모델은 refinement 비활성화
        use_refinement = docling_enabled and job.use_docling_refinement and (settings_store.get_setting(db, "docling_refinement_enabled") == "1") and (ocr_model == "premium")
        docling_workers = int(settings_store.get_setting(db, "docling_max_workers") or settings.docling_max_workers)

        # Step 2: 단일 PDF/오피스 문서 처리
        # [Flow: pipeline=vision -> 페이지별 PNG 렌더 후 Gemma4 직접 호출 / pipeline=docling -> Docling OCR + 선택적 LLM refinement]
        if job.file_type in media_loader.DOCLING_TYPES:
            input_ext = Path(job.original_filename).suffix or ".pdf"
            input_path = work_dir / f"input{input_ext}"
            if job.pdf_storage_path:
                input_bytes = supabase_client.download_pdf(job.pdf_storage_path)
                input_path.write_bytes(input_bytes.read())
            else:
                local_candidates = [p for p in work_dir.glob("*") if p.is_file()]
                if not local_candidates:
                    raise FileNotFoundError("Input file not found")
                input_path = local_candidates[0]

            def on_progress(done: int, total: int) -> None:
                job.done_pages = done
                job.total_pages = total
                db.commit()

            def on_error(page: int, msg: str) -> None:
                errors.append(f"p{page}: {msg}")

            # [Flow: Step 1 (페이지 크기 검사) -> Step 2 (전체 초과 시 스킵) -> Step 3 (기본변환: 텍스트 레이어 있음→Docling / 없음→run_vision / 고급변환: 무조건 run_vision) -> Step 4 (비-PDF: Docling)]
            oversized, total_pages = count_oversized_pages(input_path)
            if oversized > 0:
                errors.append(f"{input_path.name}: {oversized}페이지가 350mm를 초과하여 파싱할 수 없습니다")
            if oversized == total_pages and total_pages > 0:
                page_tables = []
                fmt = "markdown"
            elif input_path.suffix.lower() == ".pdf" and ocr_model == "basic" and has_pdf_text_layer(str(input_path)):
                _set_status(db, job, "ocr")
                page_tables = run_docling(
                    input_path,
                    str(work_dir),
                    columns,
                    endpoint,
                    model,
                    api_key,
                    extra_prompt=job.prompt,
                    use_refinement=use_refinement,
                    max_tokens=10000,
                    media_endpoint=media_ep,
                    media_model=media_mdl,
                    media_api_key=media_key,
                    on_progress=on_progress,
                    on_error=on_error,
                    ocr_engine=ocr_engine,
                )
                fmt = "markdown"
                # [Flow: 원본 PDF가 텍스트 레이어를 가지면 searchable PDF로 등록]
                # 별도 OCR 텍스트 레이어 생성 없이 원본 PDF를 그대로 주석 검색용으로 사용한다.
                _register_searchable_pdf_if_text_layer(db, job, input_path)
            elif input_path.suffix.lower() == ".pdf":
                _set_status(db, job, "ocr")
                page_tables, layout_by_page = run_vision(
                    str(input_path),
                    str(work_dir),
                    columns,
                    endpoint,
                    model,
                    api_key,
                    extra_prompt=job.prompt,
                    dpi=job.dpi,
                    max_tokens=10000,
                    media_endpoint=media_ep,
                    media_model=media_mdl,
                    media_api_key=media_key,
                    on_progress=on_progress,
                    on_error=on_error,
                )
                fmt = "markdown"

                # [Flow: PaddleOCR layout로 searchable PDF 생성]
                _build_and_upload_searchable_pdf(db, job, input_path, layout_by_page, job.dpi or 300)
                # [Flow: 원본 PDF가 텍스트 레이어를 가지면 searchable PDF로 등록 (premium 모드)]
                # run_vision으로 OCR을 수행했더라도 원본에 텍스트 레이어가 있으면 원본을 주석 검색용으로 우선 등록한다.
                _register_searchable_pdf_if_text_layer(db, job, input_path)
            else:
                _set_status(db, job, "ocr")
                page_tables = run_docling(
                    input_path,
                    str(work_dir),
                    columns,
                    endpoint,
                    model,
                    api_key,
                    extra_prompt=job.prompt,
                    use_refinement=use_refinement,
                    max_tokens=10000,
                    media_endpoint=media_ep,
                    media_model=media_mdl,
                    media_api_key=media_key,
                    on_progress=on_progress,
                    on_error=on_error,
                    ocr_engine=ocr_engine,
                )
                fmt = "markdown"

            _set_status(db, job, "merging")
            rows = merge.merge_pages(page_tables, columns, fmt=fmt)
            filename = Path(job.original_filename).name or "input.pdf"
            tabs[filename] = excel_writer.build_pdf_rows(filename, page_tables, columns)

            job.total_files = 1
            job.done_files = 1
            # [Flow: 업로드 시점의 페이지 수와 처리 결과 중 더 큰 값 유지 — 빈 페이지로 인해 total_pages가 감소하는 것 방지]
            job.total_pages = max(job.total_pages or 0, len(page_tables))
            job.done_pages = len(page_tables)
            db.commit()

        elif job.file_type in media_loader.HWP_TYPES:
            # Step 2b: 단일 HWP/HWPX 문서 처리 (pyhwp 기반)
            input_ext = Path(job.original_filename).suffix or ".hwp"
            input_path = work_dir / f"input{input_ext}"
            if job.pdf_storage_path:
                input_bytes = supabase_client.download_pdf(job.pdf_storage_path)
                input_path.write_bytes(input_bytes.read())
            else:
                local_candidates = [p for p in work_dir.glob("*") if p.is_file()]
                if not local_candidates:
                    raise FileNotFoundError("Input file not found")
                input_path = local_candidates[0]

            def on_progress(done: int, total: int) -> None:
                job.done_pages = done
                job.total_pages = total
                db.commit()

            def on_error(page: int, msg: str) -> None:
                errors.append(f"p{page}: {msg}")

            _set_status(db, job, "ocr")
            page_tables = run_hwp(
                input_path,
                str(work_dir),
                columns,
                endpoint,
                model,
                api_key,
                extra_prompt=job.prompt,
                use_refinement=use_refinement,
                max_tokens=10000,
                media_endpoint=media_ep,
                media_model=media_mdl,
                media_api_key=media_key,
                on_progress=on_progress,
                on_error=on_error,
            )
            fmt = "markdown"

            _set_status(db, job, "merging")
            rows = merge.merge_pages(page_tables, columns, fmt=fmt)
            filename = Path(job.original_filename).name or "input.hwp"
            tabs[filename] = excel_writer.build_pdf_rows(filename, page_tables, columns)

            job.total_files = 1
            job.done_files = 1
            # [Flow: 업로드 시점의 페이지 수와 처리 결과 중 더 큰 값 유지]
            job.total_pages = max(job.total_pages or 0, len(page_tables))
            job.done_pages = len(page_tables)
            db.commit()
        else:
            # Step 3: 멀티미디어 처리
            if job.pdf_storage_path:
                input_bytes = supabase_client.download_pdf(job.pdf_storage_path)
                input_data = input_bytes.read()
            else:
                local_candidates = list(work_dir.glob("*"))
                if not local_candidates:
                    raise FileNotFoundError("Input file not found")
                input_data = local_candidates[0].read_bytes()

            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                input_file = tmp_path / (job.original_filename or "input.zip")
                input_file.write_bytes(input_data)

                # 확장자가 없는 zip 파일도 인식할 수 있도록 보정
                if not archive_handler.is_archive(input_file.name) and media_loader.detect_file_type(input_file) == "archive":
                    input_file = input_file.with_suffix(".zip")
                    input_file.write_bytes(input_data)

                extracted: list[Path] = []
                if archive_handler.is_archive(input_file.name):
                    archive_dest = tmp_path / "extracted"
                    archive_dest.mkdir(parents=True, exist_ok=True)
                    extracted = archive_handler.extract_all_recursive(input_file.name, input_data, archive_dest)
                else:
                    # 단일 파일이면 다른 파일도 함께 있는지 확인; Storage에는 zip으로 업로드됨
                    if input_file.name.endswith(".zip"):
                        with zipfile.ZipFile(input_file, "r") as zf:
                            zf.extractall(tmp_path)
                        extracted = [p for p in tmp_path.rglob("*") if p.is_file()]
                    else:
                        extracted = [input_file]

                # 파일 유형별 분류
                media_files: list[tuple[str, Path]] = []
                file_markdowns_by_name: dict[str, str] = {}
                docling_files: list[Path] = []
                hwp_files: list[Path] = []
                for fp in extracted:
                    ftype = media_loader.detect_file_type(fp)
                    if ftype in ("image", "audio", "video"):
                        media_files.append((ftype, fp))
                    elif ftype in media_loader.DOCLING_TYPES:
                        docling_files.append(fp)
                    elif ftype in media_loader.HWP_TYPES:
                        hwp_files.append(fp)

                # [Flow: Step 1 (총 파일 수 설정 + 상태 ocr로 변경) -> Step 2 (Docling/HWP 파일 순차 처리하며 done_files 증가) -> Step 3 (미디어 파일 처리하며 done_files 증가)]
                total_to_process = len(docling_files) + len(hwp_files) + len(media_files)
                job.total_files = total_to_process
                job.done_files = 0
                _set_status(db, job, "ocr")
                db.commit()

                for fp in docling_files:
                    docling_errors: list[str] = []
                    # [Flow: Step 1 (페이지 크기 검사) -> Step 2 (전체 초과 시 스킵) -> Step 3 (Docling 처리)]
                    oversized, total_fp_pages = count_oversized_pages(fp)
                    if oversized > 0:
                        errors.append(f"{fp.name}: {oversized}페이지가 350mm를 초과하여 파싱할 수 없습니다")
                    if oversized == total_fp_pages and total_fp_pages > 0:
                        docling_tables = []
                    else:
                        docling_tables = run_docling(
                            fp,
                            str(work_dir),
                            columns,
                            endpoint,
                            model,
                            api_key,
                            extra_prompt=job.prompt,
                            use_refinement=use_refinement,
                            media_endpoint=media_ep,
                            media_model=media_mdl,
                            media_api_key=media_key,
                            on_progress=lambda done, total: None,
                            on_error=lambda page, msg: docling_errors.append(f"p{page}: {msg}"),
                            ocr_engine=ocr_engine,
                        )
                    for _, table in docling_tables:
                        all_page_contents.append((len(all_page_contents) + 1, table))
                    tabs[fp.name] = excel_writer.build_pdf_rows(fp.name, docling_tables, columns)
                    file_markdowns_by_name[fp.name] = converter.build_layout_markdown_string(docling_tables)
                    errors.extend(docling_errors)
                    job.done_files += 1
                    db.commit()

                for fp in hwp_files:
                    hwp_errors: list[str] = []
                    hwp_tables = run_hwp(
                        fp,
                        str(work_dir),
                        columns,
                        endpoint,
                        model,
                        api_key,
                        extra_prompt=job.prompt,
                        use_refinement=use_refinement,
                        media_endpoint=media_ep,
                        media_model=media_mdl,
                        media_api_key=media_key,
                        on_progress=lambda done, total: None,
                        on_error=lambda page, msg: hwp_errors.append(f"p{page}: {msg}"),
                        ocr_engine=ocr_engine,
                    )
                    for _, table in hwp_tables:
                        all_page_contents.append((len(all_page_contents) + 1, table))
                    tabs[fp.name] = excel_writer.build_pdf_rows(fp.name, hwp_tables, columns)
                    file_markdowns_by_name[fp.name] = converter.build_layout_markdown_string(hwp_tables)
                    errors.extend(hwp_errors)
                    job.done_files += 1
                    db.commit()

                def on_media_progress(done: int, total: int) -> None:
                    job.done_files = len(docling_files) + len(hwp_files) + done
                    job.total_files = total_to_process
                    db.commit()

                def on_media_error(filename: str, msg: str) -> None:
                    errors.append(f"{filename}: {msg}")

                results = run_media(
                    media_files,
                    str(work_dir),
                    columns,
                    endpoint,
                    model,
                    api_key,
                    extra_prompt=job.prompt,
                    media_endpoint=media_ep,
                    media_model=media_mdl,
                    media_api_key=media_key,
                    workers=llm_workers + media_workers,
                    on_progress=on_media_progress,
                    on_error=on_media_error,
                    ocr_model=ocr_model,
                    ocr_engine=ocr_engine,
                )

                for filename, position, table in results:
                    ftype = media_loader.detect_file_type(Path(filename))
                    all_page_contents.append((len(all_page_contents) + 1, table or ""))
                    tabs[filename] = excel_writer.build_media_rows(filename, ftype, position, table)
                    file_markdowns_by_name[filename] = converter.build_layout_markdown_string([(1, table or "")])

                # duration 정보 업데이트
                durations = {
                    "audio": 0,
                    "video": 0,
                }
                for ftype, fp in media_files:
                    if ftype in durations:
                        durations[ftype] += media_loader.get_media_duration_seconds(fp)
                job.media_duration_seconds = durations["audio"] + durations["video"]

                # [Flow: 이미지 파일 searchable PDF 생성]
                # run_media 내에서 이미 PaddleOCR이 호출되지만 layout은 반환하지 않으므로,
                # 여기서 convert_image_with_layout을 한 번 더 호출해 searchable PDF를 만든다.
                image_searchable_paths: dict[str, str] = {}
                for ftype, fp in media_files:
                    if ftype != "image":
                        continue
                    try:
                        md, layout_raw, _ = paddleocr_client.convert_image_with_layout(fp)
                        searchable_pdf_bytes = _image_to_searchable_pdf(fp, layout_raw, dpi=job.dpi or 300)
                        searchable_path = supabase_client.upload_input(
                            BytesIO(searchable_pdf_bytes),
                            f"searchable_{fp.name}",
                            job_id,
                        )
                        image_searchable_paths[fp.name] = searchable_path
                        logger.info(f"[run_job:{job_id}] 이미지 searchable PDF 업로드 완료: {fp.name}")
                    except Exception as e:
                        logger.warning(f"[run_job:{job_id}] 이미지 searchable PDF 생성 실패: {fp.name}: {e}")

                # 추출 파일 정보 업데이트 (이미지는 Storage에 개별 업로드)
                extracted_info = []
                for p in extracted:
                    ftype = media_loader.detect_file_type(p)
                    info = {
                        "path": str(p.name),
                        "type": ftype,
                        "size": p.stat().st_size,
                        "duration": media_loader.get_media_duration_seconds(p) if ftype in ("audio", "video") else 0,
                        "result_markdown": file_markdowns_by_name.get(p.name, ""),
                    }
                    if ftype == "image":
                        try:
                            info["storage_path"] = supabase_client.upload_image(job_id, p, p.name)
                        except Exception as e:
                            errors.append(f"{p.name}: 이미지 업로드 실패 {e}")
                        info["searchable_pdf_storage_path"] = image_searchable_paths.get(p.name, "")
                    elif ftype in media_loader.DOCLING_TYPES or ftype in media_loader.HWP_TYPES:
                        try:
                            info["storage_path"] = supabase_client.upload_input(BytesIO(p.read_bytes()), p.name, job_id)
                        except Exception as e:
                            errors.append(f"{p.name}: 문서 업로드 실패 {e}")
                    extracted_info.append(info)
                job.extracted_files = extracted_info
                job.total_files = len(extracted)
                job.done_files = len(extracted)
                # [Flow: 멀티미디어 작업의 total_pages를 처리된 페이지 수로 설정 — 업로드 시에는 0이었음]
                if not job.total_pages:
                    job.total_pages = len(all_page_contents)
                job.done_pages = len(all_page_contents)

        # Step 4: CSV + MD 저장 (xlsx는 별도 LLM 변환으로 제공)
        _set_status(db, job, "merging")
        csv_path = out_dir / "result.csv"
        md_path = out_dir / "result.md"
        if rows:
            converter.write_csv(rows, columns, csv_path)
        else:
            # 미디어 결과를 CSV로도 변환
            merged_rows: list[dict] = []
            for sheet_rows in tabs.values():
                merged_rows.extend(sheet_rows)
            if merged_rows:
                converter.write_csv(merged_rows, columns, csv_path)

        # MD는 원문서 레이아웃을 보존한 마크다운으로 출력 (vision PDF / 미디어)
        if extracted_info:
            converter.write_combined_file_markdowns(
                [info.get("result_markdown", "") for info in extracted_info], md_path
            )
        elif page_tables and fmt == "markdown":
            converter.write_layout_markdown(page_tables, md_path)
        elif rows:
            converter.write_markdown(rows, columns, md_path)
        elif all_page_contents:
            converter.write_layout_markdown(all_page_contents, md_path)
        elif results:
            # 미디어 결과를 페이지별 마크다운으로 변환
            media_page_tables = [(idx + 1, table or "") for idx, (_, _, table) in enumerate(results)]
            converter.write_layout_markdown(media_page_tables, md_path)
        else:
            merged_rows = []
            for sheet_rows in tabs.values():
                merged_rows.extend(sheet_rows)
            if merged_rows:
                converter.write_markdown(merged_rows, columns, md_path)

        # Step 5: 결과 파일 존재 여부 확인 — 결과가 없으면 error 처리
        has_md = md_path.exists() and md_path.stat().st_size > 0
        has_csv = csv_path.exists() and csv_path.stat().st_size > 0
        if not has_md and not has_csv:
            error_detail = "\n".join(errors) or "모든 페이지 처리 실패"
            logger.error(f"[run_job:{job_id}] 결과 파일 없음: {error_detail}")
            return _handle_job_failure(db, job, error_detail)

        # Step 6: Storage에 결과 업로드
        logger.info(f"[run_job:{job_id}] Step 6 시작: csv_path={csv_path}, md_path={md_path}, exists={csv_path.exists()}, {md_path.exists()}")
        try:
            storage_paths = supabase_client.upload_result(
                job_id, csv_path=csv_path if has_csv else None, md_path=md_path if has_md else None
            )
            logger.info(f"[run_job:{job_id}] Storage 업로드 결과: {storage_paths}")
        except Exception as upload_err:
            logger.exception(f"[run_job:{job_id}] Storage 업로드 실패: {upload_err}")
            raise

        # Step 7: DB 업데이트
        expire_days = int(settings_store.get_setting(db, "download_expire_days") or "7")
        job.result_csv_path = str(csv_path)
        job.result_md_path = str(md_path)
        job.result_csv_storage_path = storage_paths.get("csv", "")
        job.result_md_storage_path = storage_paths.get("md", "")
        job.download_token = job_id
        job.expires_at = datetime.now(timezone.utc) + timedelta(days=expire_days)
        job.error_log = "\n".join(errors)
        job.finished_at = datetime.now(timezone.utc)
        logger.info(f"[run_job:{job_id}] DB 업데이트 직전: md_storage={job.result_md_storage_path}, csv_storage={job.result_csv_storage_path}, status={job.status}")
        _set_status(db, job, "done")
        logger.info(f"[run_job:{job_id}] DB 업데이트 완료: status={job.status}")

        # Step 7: 완료 이메일
        try:
            user_lang = "en"
            if job.user_id:
                user = db.get(User, job.user_id)
                if user and user.language:
                    user_lang = user.language
            subject, html = email_sender.build_done_email(job_id, job.original_filename, expire_days, lang=user_lang)
            email_sender.send_email(db, job.email, subject, html)
        except Exception as e:  # noqa: BLE001
            job.error_log = (job.error_log + f"\n[email] {e}").strip()
            db.commit()

        return {"job_id": job_id, "rows": len(rows), "errors": len(errors)}

    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        error_detail = (job.error_log + f"\n{tb}").strip()
        return _handle_job_failure(db, job, error_detail)
    finally:
        db.close()


# [Flow: Step 1 (is_new=true 파일 필터링) -> Step 2 (파일 타입별 파이프라인 실행) -> Step 3 (result_markdown 채우기) -> Step 4 (전체 extracted_files에서 combined markdown 재생성) -> Step 5 (Storage 재업로드 + 캐시 무효화)]
@celery.task(name="backend.workers.tasks.run_job_added_files")
def run_job_added_files(job_id: str) -> dict:
    """기존 완료된 Job에 새로 추가된 파일(is_new=true)만 변환하여 결과에 추가한다.

    기존 파일의 result_markdown은 유지되며, 새 파일의 변환 결과가 append된다.
    처리 완료 후 전체 extracted_files의 combined markdown을 재생성하여 Storage에 업로드한다.
    Job의 status는 "done"을 유지하며, 새 파일의 status 필드로 진행 상황을 추적한다.
    """
    from ..core import paddleocr_client
    from sqlalchemy.orm.attributes import flag_modified

    db = SessionLocal()
    job = db.get(Job, job_id)
    if job is None:
        db.close()
        return {"error": "job not found"}

    try:
        # [Flow: Step 1 (새 파일 필터링 — is_new=true인 항목만 처리)]
        all_files = job.extracted_files or []
        new_files = [f for f in all_files if f.get("is_new")]
        if not new_files:
            logger.info(f"[run_job_added_files:{job_id}] 처리할 새 파일 없음")
            return {"job_id": job_id, "skipped": True, "reason": "no new files"}

        # 런타임 설정 주입
        endpoint = job.endpoint or settings_store.get_setting(db, "llm_endpoint")
        model = job.model or settings_store.get_setting(db, "llm_model")
        api_key = settings_store.get_setting(db, "llm_api_key")
        columns = job.columns or []
        work_dir = Path(settings.data_dir) / "jobs" / job_id
        added_dir = work_dir / "added_files"

        media_ep = settings_store.get_setting(db, "media_llm_endpoint") or settings.media_llm_endpoint
        media_mdl = settings_store.get_setting(db, "media_llm_model") or settings.media_llm_model
        media_key = settings_store.get_setting(db, "media_llm_api_key") or settings.media_llm_api_key
        llm_workers = int(settings_store.get_setting(db, "llm_max_workers") or settings.llm_max_workers)
        media_workers = int(settings_store.get_setting(db, "media_max_workers") or settings.media_max_workers)

        docling_enabled = settings_store.get_setting(db, "docling_enabled") == "1"
        ocr_model = job.ocr_model or "premium"
        ocr_engine = job.ocr_engine or "easyocr"
        use_refinement = docling_enabled and job.use_docling_refinement and (settings_store.get_setting(db, "docling_refinement_enabled") == "1") and (ocr_model == "premium")

        errors: list[str] = []

        # [Flow: Step 2 (새 파일을 타입별로 분류하여 파이프라인 실행)]
        # 새 파일의 로컬 경로를 찾는다 (added_files 디렉토리 또는 Storage에서 다운로드)
        def resolve_local_path(info: dict) -> Path:
            """새 파일의 로컬 경로를 반환. 없으면 Storage에서 다운로드."""
            local_path = added_dir / info["path"]
            if local_path.exists():
                return local_path
            # Storage에서 다운로드
            storage_path = info.get("storage_path", "")
            if storage_path:
                data = supabase_client.download_pdf(storage_path).read()
                added_dir.mkdir(parents=True, exist_ok=True)
                local_path.write_bytes(data)
                return local_path
            raise FileNotFoundError(f"파일을 찾을 수 없음: {info['path']}")

        # 파일 타입별 분류
        docling_files: list[tuple[dict, Path]] = []
        hwp_files: list[tuple[dict, Path]] = []
        media_files: list[tuple[str, dict, Path]] = []
        for info in new_files:
            ftype = info.get("type", "")
            try:
                fp = resolve_local_path(info)
            except Exception as e:
                errors.append(f"{info.get('path', '?')}: {e}")
                info["status"] = "error"
                continue
            if ftype in media_loader.DOCLING_TYPES:
                docling_files.append((info, fp))
            elif ftype in media_loader.HWP_TYPES:
                hwp_files.append((info, fp))
            elif ftype in ("image", "audio", "video"):
                media_files.append((ftype, info, fp))
            else:
                errors.append(f"{info.get('path', '?')}: 지원하지 않는 파일 타입 ({ftype})")
                info["status"] = "error"

        # [Flow: Step 3a (Docling 타입 파일 처리 — PDF/DOCX/PPTX/XLSX/HTML)]
        for info, fp in docling_files:
            docling_errors: list[str] = []
            oversized, total_fp_pages = count_oversized_pages(fp)
            if oversized > 0:
                errors.append(f"{fp.name}: {oversized}페이지가 350mm를 초과하여 파싱할 수 없습니다")
            if oversized == total_fp_pages and total_fp_pages > 0:
                docling_tables = []
            else:
                docling_tables = run_docling(
                    fp,
                    str(work_dir),
                    columns,
                    endpoint,
                    model,
                    api_key,
                    extra_prompt=job.prompt,
                    use_refinement=use_refinement,
                    media_endpoint=media_ep,
                    media_model=media_mdl,
                    media_api_key=media_key,
                    on_progress=lambda done, total: None,
                    on_error=lambda page, msg: docling_errors.append(f"p{page}: {msg}"),
                    ocr_engine=ocr_engine,
                )
            info["result_markdown"] = converter.build_layout_markdown_string(docling_tables)
            info["status"] = "done"
            info["is_new"] = False
            errors.extend(docling_errors)

        # [Flow: Step 3b (HWP 파일 처리)]
        for info, fp in hwp_files:
            hwp_errors: list[str] = []
            hwp_tables = run_hwp(
                fp,
                str(work_dir),
                columns,
                endpoint,
                model,
                api_key,
                extra_prompt=job.prompt,
                use_refinement=use_refinement,
                media_endpoint=media_ep,
                media_model=media_mdl,
                media_api_key=media_key,
                on_progress=lambda done, total: None,
                on_error=lambda page, msg: hwp_errors.append(f"p{page}: {msg}"),
                ocr_engine=ocr_engine,
            )
            info["result_markdown"] = converter.build_layout_markdown_string(hwp_tables)
            info["status"] = "done"
            info["is_new"] = False
            errors.extend(hwp_errors)

        # [Flow: Step 3c (미디어 파일 처리 — 이미지/오디오/비디오)]
        if media_files:
            media_file_paths: list[tuple[str, Path]] = [(ftype, fp) for ftype, _, fp in media_files]
            media_results = run_media(
                media_file_paths,
                str(work_dir),
                columns,
                endpoint,
                model,
                api_key,
                extra_prompt=job.prompt,
                media_endpoint=media_ep,
                media_model=media_mdl,
                media_api_key=media_key,
                workers=llm_workers + media_workers,
                on_progress=lambda done, total: None,
                on_error=lambda filename, msg: errors.append(f"{filename}: {msg}"),
                ocr_model=ocr_model,
                ocr_engine=ocr_engine,
            )
            # run_media 결과를 파일명으로 매핑
            result_by_name: dict[str, str] = {}
            for filename, position, table in media_results:
                result_by_name[filename] = converter.build_layout_markdown_string([(1, table or "")])

            # 이미지 searchable PDF 생성
            for ftype, info, fp in media_files:
                info["result_markdown"] = result_by_name.get(fp.name, "")
                info["status"] = "done"
                info["is_new"] = False
                # 이미지 파일에 searchable PDF 생성
                if ftype == "image":
                    try:
                        md, layout_raw, _ = paddleocr_client.convert_image_with_layout(fp)
                        searchable_pdf_bytes = _image_to_searchable_pdf(fp, layout_raw, dpi=job.dpi or 300)
                        searchable_path = supabase_client.upload_input(
                            BytesIO(searchable_pdf_bytes),
                            f"searchable_{fp.name}",
                            job_id,
                        )
                        info["searchable_pdf_storage_path"] = searchable_path
                    except Exception as e:
                        logger.warning(f"[run_job_added_files:{job_id}] 이미지 searchable PDF 생성 실패: {fp.name}: {e}")

        # [Flow: Step 4 (전체 extracted_files에서 combined markdown 재생성)]
        flag_modified(job, "extracted_files")
        db.commit()

        # 모든 파일의 result_markdown을 결합
        all_file_markdowns = [f.get("result_markdown", "") for f in all_files]
        combined_markdown = converter.build_combined_file_markdowns(all_file_markdowns)

        # [Flow: Step 5 (combined markdown을 Storage에 재업로드 + CSV/XLSX Basic 재생성)]
        out_dir = work_dir / "result"
        out_dir.mkdir(parents=True, exist_ok=True)
        edited_path = out_dir / "result_edited.md"
        edited_path.write_text(combined_markdown, encoding="utf-8")
        try:
            storage_path = supabase_client.upload_result(
                job_id, edited_md_path=edited_path
            ).get("edited_md", "")
            job.result_edited_md_storage_path = storage_path
            job.result_edited_md_path = ""
        except Exception as e:
            logger.exception(f"[run_job_added_files:{job_id}] Storage 업로드 실패: {e}")
            raise

        # [Flow: Step 5b (CSV/XLSX Basic 재생성 — 마크다운과 결과 파일 불일치 방지)]
        # 새 파일이 추가되어 combined markdown이 변경되었으므로, 기존 CSV/XLSX Basic도 재생성한다.
        # XLSX Advanced는 별도 LLM 변환이므로 사용자가 수동으로 재실행해야 한다.
        if combined_markdown.strip():
            try:
                from ..core import office_converter
                with tempfile.TemporaryDirectory() as tmpdir:
                    xlsx_path = Path(tmpdir) / "result.xlsx"
                    csv_path = Path(tmpdir) / "result.csv"
                    office_converter.markdown_to_xlsx_basic(combined_markdown, xlsx_path)
                    office_converter.markdown_to_csv_basic(combined_markdown, csv_path)
                    xlsx_storage_path = supabase_client.upload_office_result(job_id, xlsx_path, "xlsx")
                    csv_storage_path = supabase_client.upload_office_result(job_id, csv_path, "csv")
                job.result_xlsx_basic_storage_path = xlsx_storage_path
                job.result_xlsx_storage_path = xlsx_storage_path  # 하위 호환
                job.result_csv_storage_path = csv_storage_path
                logger.info(f"[run_job_added_files:{job_id}] CSV/XLSX Basic 재생성 완료")
            except Exception as e:
                logger.warning(f"[run_job_added_files:{job_id}] CSV/XLSX Basic 재생성 실패 (무시됨): {e}")

        # total_pages, total_files 갱신
        total_pages = 0
        for f in all_files:
            ftype = f.get("type", "")
            if ftype in media_loader.DOCLING_TYPES or ftype in media_loader.HWP_TYPES:
                # 페이지 수는 result_markdown의 페이지 마커에서 추정
                page_markers = combined_markdown.count("<!-- 페이지 ")
                total_pages = max(total_pages, page_markers)
            elif ftype == "image":
                total_pages += 1
        job.total_pages = max(job.total_pages or 0, total_pages)
        job.total_files = len(all_files)
        job.error_log = "\n".join(errors) if errors else (job.error_log or "")
        flag_modified(job, "extracted_files")
        db.commit()

        # preview 캐시 무효화
        try:
            from ..core import cache
            cache.invalidate_pattern(f"preview:{job_id}:*")
        except Exception:
            pass

        logger.info(f"[run_job_added_files:{job_id}] 증분 변환 완료 — 새 파일 {len(new_files)}개 처리")
        return {"job_id": job_id, "processed": len(new_files), "errors": len(errors)}

    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        logger.exception(f"[run_job_added_files:{job_id}] 실패: {e}")
        # 실패한 새 파일들을 error 상태로 표시
        try:
            all_files = job.extracted_files or []
            for f in all_files:
                if f.get("is_new"):
                    f["status"] = "error"
            flag_modified(job, "extracted_files")
            job.error_log = (job.error_log + f"\n[added_files] {tb}").strip()
            db.commit()
        except Exception:
            pass
        return {"job_id": job_id, "error": str(e)}
    finally:
        db.close()


# OCR 업로드 원본 파일 및 변환 결과의 Supabase Storage 보관 기간 (일)
# 실제 Storage 삭제는 별도 아카이빙 스토리지 구성 전까지 수행하지 않는다.
RETENTION_DAYS = 30


# [Flow: Step 1 (30일 이전 생성된 job 조회) -> Step 2 (실제 삭제는 보류, 아카이빙 스토리지 구성 후 활성화) -> Step 3 (현재는 로그만 기록)]
@celery.task(name="backend.workers.tasks.cleanup_expired_uploads")
def cleanup_expired_uploads() -> dict:
    """created_at 기준 30일이 지난 job의 원본 업로드 파일 삭제를 보류한다. (아카이빙 스토리지 구성 전까지)"""
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
        jobs = (
            db.query(Job)
            .filter(Job.created_at < cutoff)
            .filter((Job.pdf_storage_path != "") | (Job.extracted_files.isnot(None)))
            .all()
        )

        pending = 0
        skipped = 0
        for job in jobs:
            has_source = bool(job.pdf_storage_path) or any(
                isinstance(info, dict) and info.get("storage_path")
                for info in job.extracted_files or []
            )
            if not has_source:
                skipped += 1
                continue

            pending += 1
            logger.info(f"[cleanup_expired_uploads] {job.id} 원본 파일 삭제 보류 (아카이빙 스토리지 미구성)")

        return {"pending": pending, "skipped": skipped}
    except Exception as e:
        logger.exception(f"[cleanup_expired_uploads] 태스크 오류: {e}")
        return {"error": str(e)}
    finally:
        db.close()


@celery.task(name="backend.workers.tasks.convert_xlsx_advanced")
def convert_xlsx_advanced(parent_job_id: str) -> dict:
    """마크다운 결과를 LLM 기반 고급 변환으로 xlsx로 변환한다."""
    return xlsx_advanced_converter.run(parent_job_id)


@celery.task(name="backend.workers.tasks.annotate_pdf_job")
def annotate_pdf_job(
    job_id: str, instruction: str, mode: str, comment_mode: str, advanced: bool = False,
    annotation_index: int = 0, page_range: list[int] | None = None,
) -> dict:
    """원본 PDF/이미지에서 조건에 맞는 텍스트 요소를 하이라이트/여백 주석으로 표시한다.

    advanced=True이면 Vision LLM을 사용해 정밀 bbox + 색상을 직접 검출한다.
    주석 코멘트는 사용자가 instruction에 사용한 언어로 작성된다 (프롬프트가 LLM에 지시).
    annotation_index는 API 수준에서 원자적으로 할당된 고유 인덱스로, 파일명 충돌을 방지한다.
    page_range는 처리할 1-based 페이지 번호 리스트. None이면 전체 페이지를 처리한다.
    """
    return pdf_annotate_converter.run(
        job_id, instruction, mode, comment_mode, advanced=advanced,
        annotation_index=annotation_index, page_range=page_range,
    )


@celery.task(name="backend.workers.tasks.annotate_edit_job")
def annotate_edit_job(
    job_id: str, instruction: str, page_range: list[int] | None, annotation_index: int,
) -> dict:
    """[Flow: Step 1 (기존 AI 주석 추출) -> Step 2 (LLM으로 색상/코멘트 재편집) -> Step 3 (병합 업로드)]

    기존 AI 주석의 색상/코멘트를 사용자 instruction에 맞게 LLM으로 재편집한다.
    지정한 페이지 범위의 기존 AI 주석만 편집 대상으로 삼고, 사용자 수동 편집 주석과
    다른 페이지의 주석은 건드리지 않는다. 기존 주석의 id/rect는 유지하고 속성만 갱신한다.
    annotation_index는 API 수준에서 원자적으로 할당된 고유 인덱스로, entry 추적에 사용한다.
    """
    return pdf_annotate_converter.run_edit(
        job_id, instruction, page_range, annotation_index,
    )


@celery.task(name="backend.workers.tasks.auto_recharge_retry")
def auto_recharge_retry() -> dict:
    """자동 충전 실패 사용자를 찾아 1일 간격으로 재시도한다.
    auto_recharge_retries > 0 && < 3 && auto_recharge_enabled == True인 사용자 대상."""
    # [Flow: Step 1 (재시도 대상 조회) -> Step 2 (각 사용자에 대해 trigger_auto_recharge 호출) -> Step 3 (결과 집계)]
    from sqlalchemy import select as sa_select
    from ..db.models import User
    from ..api.payments import trigger_auto_recharge

    db = SessionLocal()
    try:
        users = db.execute(
            sa_select(User).where(
                User.auto_recharge_enabled == True,  # noqa: E712
                User.auto_recharge_retries > 0,
                User.auto_recharge_retries < 3,
            )
        ).scalars().all()

        retried = 0
        succeeded = 0
        for user in users:
            try:
                result = trigger_auto_recharge(db, user)
                retried += 1
                if result.get("ok"):
                    succeeded += 1
                    logger.info(f"[auto_recharge_retry] {user.id} 재시도 성공")
                else:
                    logger.warning(f"[auto_recharge_retry] {user.id} 재시도 실패: {result.get('reason')}")
            except Exception as e:
                logger.error(f"[auto_recharge_retry] {user.id} 예외: {e}")

        return {"retried": retried, "succeeded": succeeded}
    except Exception as e:
        logger.exception(f"[auto_recharge_retry] 태스크 오류: {e}")
        return {"error": str(e)}
    finally:
        db.close()


@celery.task(name="backend.workers.tasks.cleanup_expired_sandboxes")
def cleanup_expired_sandboxes() -> dict:
    """[Flow: Step 1 (만료된 sandbox 조회·종료) -> Step 2 (결과 수집) -> Step 3 (오래된 workspace 디스크 정리)]

    만료된 Kata 샌드박스를 자동으로 종료하고 결과 파일을 수집한다.
    또한 이미 종료된 sandbox 의 workspace 디스크를 보존 기간(7일) 경과 후 삭제한다.
    Celery beat 에 의해 주기적으로 실행된다 (기본 10분 간격).
    """
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    from sqlalchemy import select as sa_select, update as sa_update
    from ..db.models import Sandbox
    from ..core.sandbox import ResultCollector, SandboxManager, WorkspaceManager

    # [Flow: Step 1 (만료된 sandbox 조회·종료) -> Step 2 (결과 수집) -> Step 3 (workspace 정리)]
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        timeout_seconds = settings.sandbox_default_timeout
        cutoff = now - timedelta(seconds=timeout_seconds)

        manager = SandboxManager()
        collector = ResultCollector()
        workspace_mgr = WorkspaceManager()

        # supabase_client 지연 import (순환 참조 방지)
        try:
            from ..core.supabase_client import get_supabase_client
            supabase = get_supabase_client()
        except Exception:
            supabase = None

        # ========================================
        # Step 1: 만료된 sandbox 종료 + 결과 수집
        # ========================================
        expired = db.execute(
            sa_select(Sandbox).where(
                Sandbox.status.in_(["creating", "running"]),
                Sandbox.created_at < cutoff,
            )
        ).scalars().all()

        destroyed_count = 0
        destroy_errors = 0

        for sandbox in expired:
            try:
                logger.info(f"[cleanup_expired_sandboxes] sandbox {sandbox.id} 만료, 종료 시도")
                workspace_path = Path(sandbox.workspace_path) if sandbox.workspace_path else None

                # 결과 수집 시도 (실패해도 종료는 진행)
                if workspace_path and workspace_path.exists():
                    try:
                        collector.collect_and_upload(
                            workspace_path=workspace_path,
                            job_id=sandbox.job_id or "",
                            supabase_client=supabase,
                        )
                    except Exception as collect_err:
                        logger.warning(f"[cleanup_expired_sandboxes] {sandbox.id} 결과 수집 실패: {collect_err}")

                # sandbox 종료 — destroy_sandbox(container_name, workspace_path)
                manager.destroy_sandbox(sandbox.container_name, workspace_path)

                # DB 상태 업데이트
                db.execute(
                    sa_update(Sandbox)
                    .where(Sandbox.id == sandbox.id)
                    .values(status="expired", updated_at=now)
                )
                destroyed_count += 1
            except Exception as e:
                logger.error(f"[cleanup_expired_sandboxes] sandbox {sandbox.id} 종료 실패: {e}")
                destroy_errors += 1

        # ========================================
        # Step 2: 오래된 workspace 디스크 정리 (보존 기간 7일 경과)
        # ========================================
        # 이미 destroyed/expired 상태이고 workspace_path 가 비어있지 않은 sandbox 조회
        stale = db.execute(
            sa_select(Sandbox).where(
                Sandbox.status.in_(["destroyed", "expired"]),
                Sandbox.workspace_path != "",
            )
        ).scalars().all()

        workspace_cleaned = 0
        workspace_errors = 0

        for sandbox in stale:
            workspace_path = Path(sandbox.workspace_path) if sandbox.workspace_path else None
            if not workspace_path or not workspace_path.exists():
                # 이미 디스크에 없으면 DB 의 workspace_path 만 비우기
                db.execute(
                    sa_update(Sandbox)
                    .where(Sandbox.id == sandbox.id)
                    .values(workspace_path="", updated_at=now)
                )
                continue

            try:
                # cleanup_workspace: mtime 기준 preserve_days(7일) 경과 시 rmtree 실행
                removed = workspace_mgr.cleanup_workspace(workspace_path, preserve_days=7)
                if removed:
                    db.execute(
                        sa_update(Sandbox)
                        .where(Sandbox.id == sandbox.id)
                        .values(workspace_path="", updated_at=now)
                    )
                    workspace_cleaned += 1
                    logger.info(f"[cleanup_expired_sandboxes] workspace 정리 완료: {workspace_path}")
            except Exception as e:
                logger.error(f"[cleanup_expired_sandboxes] workspace 정리 실패 {sandbox.id}: {e}")
                workspace_errors += 1

        db.commit()
        logger.info(
            f"[cleanup_expired_sandboxes] 완료: destroyed={destroyed_count}, destroy_errors={destroy_errors}, "
            f"workspace_cleaned={workspace_cleaned}, workspace_errors={workspace_errors}"
        )
        return {
            "destroyed": destroyed_count,
            "destroy_errors": destroy_errors,
            "workspace_cleaned": workspace_cleaned,
            "workspace_errors": workspace_errors,
        }
    except Exception as e:
        logger.exception(f"[cleanup_expired_sandboxes] 태스크 오류: {e}")
        return {"error": str(e)}
    finally:
        db.close()
