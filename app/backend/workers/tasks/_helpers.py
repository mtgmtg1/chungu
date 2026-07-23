"""workers/tasks 공유 헬퍼 — Celery 태스크 모듈에서 import하는 내부 함수.

이 모듈은 workers/tasks 패키지 분할 시 중복을 피하기 위해 모든 비-태스크 헬퍼를 한 곳에 둔다.
"""
from __future__ import annotations

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

import fitz
from pypdf import PdfReader
from sqlalchemy import text as sql_text

from ...celery_app import celery
from ...config import settings
from ...core import (
    archive_handler,
    converter,
    excel_writer,
    media_loader,
    merge,
    paddleocr_client,
    pdf_annotate_converter,
    pdf_text_layer,
    pipeline_ediscovery,
    points_service,
    subscription_service,
    supabase_client,
    xlsx_advanced_converter,
)
from ...core.job_helpers import upload_ocr_layout
from ...core.markdown_image_rewriter import rewrite_inline_images_to_storage
from ...core.ocr_client import has_pdf_text_layer
from ...core.pipeline_docling import run_docling, run_hwp
from ...core.pipeline_hybrid import run_hybrid
from ...core.pipeline_media import run_media
from ...core.pipeline_vision import run_vision
from ...db.models import Job, User
from ...db.session import SessionLocal
from ... import email_sender, settings_store

logger = logging.getLogger(__name__)


def _set_status(db, job: Job, status: str) -> None:
    job.status = status
    db.commit()



def _release_subscription_usage(db, job: Job) -> None:
    """최종 실패한 작업이 차감한 크레딧을 되돌린다.
    Job에 예약 기록이 있으면 해당 기록을 우선 사용하고, 없으면 extracted_files로부터 계산한다."""
    if not job.user_id:
        return
    db_user = db.get(User, job.user_id)
    if db_user is None:
        return

    # extracted_files로부터 미디어/Docling 세부값을 재계산한다.
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
    ocr_model = job.ocr_model or "premium"
    basic_pages = job.reserved_basic_pages if job.reserved_basic_pages else (pages + image_count if ocr_model == "basic" else 0)
    premium_pages = job.reserved_premium_pages if job.reserved_premium_pages else (pages + image_count if ocr_model != "basic" else 0)
    period_start = job.reserved_period_start

    try:
        subscription_service.release_usage(
            db,
            db_user,
            basic_pages=basic_pages,
            premium_pages=premium_pages,
            audio_seconds=audio_seconds,
            video_seconds=video_seconds,
            docling_refinement_pages=docling_refinement_pages,
            period_start=period_start,
        )
        logger.info(f"[run_job:{job.id}] 크레딧 환불 완료")
    except Exception as e:
        logger.warning(f"[run_job:{job.id}] 크레딧 환불 중 오류 (무시): {e}")
    except Exception as e:
        logger.warning(f"[run_job:{job.id}] 구독 사용량 환불 중 오류 (무시): {e}")



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
    force: bool = False,
    upload_name: str = "searchable.pdf",
) -> str | None:
    """[Flow: Step 1 (원본 PDF를 페이지별 이미지로 렌더링 + deskew 보정) -> Step 2 (보정된 이미지로 새 PDF 생성)
          -> Step 3 (layout_by_page에서 OCR 결과 추출) -> Step 4 (새 PDF에 투명 텍스트 레이어 추가)
          -> Step 5 (searchable PDF Storage 업로드) -> Step 6 (OCR layout Storage 업로드) -> Step 7 (Job DB 저장)]

    PaddleOCR이 반환한 페이지별 layout로부터 텍스트/bbox를 추출해 deskew 보정된 PDF에
    투명 텍스트 레이어를 입히고, 그 결과를 Storage에 업로드한다.
    원본 PDF가 아닌 deskew 보정된 페이지 이미지로 새 PDF를 만들어 기울어진 스캔 문서도
    수평으로 정렬된 searchable PDF를 제공한다.
    동시에 OCR layout을 Storage에 저장해 AI agent의 get_elements/search_text가 재사용할 수 있게 한다.

    매개변수:
        force: True면 job.searchable_pdf_storage_path가 이미 설정되어 있어도 강제로 새로 생성.
            멀티파일에서 각 PDF별로 개별 searchable PDF를 생성할 때 사용.
        upload_name: Storage에 업로드할 파일명. 멀티파일에서 파일별 고유 이름이 필요할 때 사용.

    반환값: 업로드된 Storage 경로 (실패 시 None). force=False일 때는 job.searchable_pdf_storage_path에도 저장.
    """
    # [Flow: 이미 원본 텍스트 레이어가 searchable PDF로 등록되어 있으면 OCR 재생성을 건너뛴다]
    if not force and job.searchable_pdf_storage_path:
        return None

    from ...core.image_deskew import deskew_image
    from ...core.ocr_client import render_pdf

    # [Flow: run_vision에서 layout이 비어 있을 경우(방어), PaddleOCR client를 직접 호출해 layout 복구]
    if not layout_by_page:
        try:
            doc = fitz.open(str(input_path))
            total_input_pages = len(doc)
            doc.close()
            if total_input_pages <= 10:
                pages = paddleocr_client.convert_pdf_with_layout(input_path)
                layout_pages = [p[1] for p in pages]
                layout_by_page = {i + 1: layout for i, layout in enumerate(layout_pages) if layout}
                logger.info(f"[run_job:{job.id}] searchable PDF 생성 직접 PaddleOCR layout 확보: {len(layout_by_page)}페이지")
        except Exception as e:
            logger.warning(f"[run_job:{job.id}] searchable PDF 생성 직접 PaddleOCR layout 확보 실패: {e}")

    # OCR layout을 먼저 Storage에 저장해 agent 도구가 재사용할 수 있게 한다.
    if layout_by_page:
        upload_ocr_layout(db, job, layout_by_page)

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
                searchable_pdf_bytes = pdf_text_layer.add_text_layer_from_ocr(pdf_bytes, page_ocr_results, dpi=dpi, language="ko", layout_by_page=layout_by_page)
                storage_path = supabase_client.upload_input(BytesIO(searchable_pdf_bytes), upload_name, job.id)
                if not force:
                    job.searchable_pdf_storage_path = storage_path
                    db.commit()
                logger.info(f"[run_job:{job.id}] searchable PDF 업로드 완료 (폴백 — deskew 미적용): {storage_path}")
                return storage_path

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
            searchable_pdf_bytes = pdf_text_layer.add_text_layer_from_ocr(deskewed_pdf_bytes, page_ocr_results, dpi=dpi, language="ko", layout_by_page=layout_by_page)

        storage_path = supabase_client.upload_input(BytesIO(searchable_pdf_bytes), upload_name, job.id)
        if not force:
            job.searchable_pdf_storage_path = storage_path
            db.commit()
        logger.info(f"[run_job:{job.id}] searchable PDF 업로드 완료 (deskew 적용): {storage_path}")
        return storage_path
    except Exception as e:
        logger.warning(f"[run_job:{job.id}] searchable PDF 생성/업로드 실패: {e}")
        return None



def _register_searchable_pdf_if_text_layer(
    db, job: Job, input_path: Path, force: bool = False, upload_name: str = "searchable.pdf"
) -> str | None:
    """[Flow: Step 1 (PDF 텍스트 레이어 검사) -> Step 2 (있으면 원본을 searchable PDF로 등록)]

    원본 PDF에 텍스트 레이어가 있으면 별도 OCR 텍스트 레이어 생성 없이 원본 PDF를
    주석 검색용 searchable PDF로 그대로 등록한다. 디지털 텍스트 PDF의 정확한 좌표를
    주석에 직접 활용할 수 있다.

    매개변수:
        force: True면 job.searchable_pdf_storage_path가 이미 설정되어 있어도 강제로 등록.
            멀티파일에서 각 PDF별로 개별 searchable PDF를 등록할 때 사용.
        upload_name: Storage에 업로드할 파일명.

    반환값: 업로드된 Storage 경로 (실패/스킵 시 None).
    """
    if not force and job.searchable_pdf_storage_path:
        return None  # 이미 등록되어 있으면 스킵
    try:
        if not has_pdf_text_layer(str(input_path)):
            return None
        # 원본 PDF를 Storage에 searchable PDF로 업로드
        pdf_bytes = input_path.read_bytes()
        storage_path = supabase_client.upload_input(BytesIO(pdf_bytes), upload_name, job.id)
        if not force:
            job.searchable_pdf_storage_path = storage_path
            db.commit()
        logger.info(f"[run_job:{job.id}] 원본 PDF에 텍스트 레이어 있음 → searchable PDF로 등록: {storage_path}")
        return storage_path
    except Exception as e:
        logger.warning(f"[run_job:{job.id}] 원본 PDF searchable 등록 실패: {e}")
        return None



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
    from ...core.image_deskew import deskew_image

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
        return pdf_text_layer.add_text_layer_from_ocr(pdf_bytes, page_ocr_results, dpi=dpi, language="ko", layout_by_page={1: layout_raw})
    return pdf_bytes



