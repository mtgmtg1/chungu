"""api/jobs 공유 헬퍼 — 모든 서브모듈에서 import하는 공통 함수/상수.

이 모듈은 api/jobs 패키지 분할 시 중복을 피하기 위해 모든 공유 헬퍼를 한 곳에 둔다.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import logging
import math
import re as _re
import tempfile
import unicodedata
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import fitz
from fastapi import Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...auth.api_key_auth import require_api_key_or_session
from ...auth.supabase_auth import CurrentUser
from ...celery_app import celery as celery_app
from ...config import settings
from ...core import (
    cache,
    converter,
    docling_client,
    hwp_converter,
    media_loader,
    office_converter,
    pdf_preview_converter,
    pdf_user_annotator,
    points_service,
    subscription_service,
    supabase_client,
)
from ...core.job_helpers import convert_format_alias, parse_columns, upload_ocr_layout
from ...core.markdown_image_rewriter import rewrite_inline_images_to_storage
from ...core.prompts import DEFAULT_COLUMNS
from ...db.models import Job, User

logger = logging.getLogger(__name__)


# --- get_current_user_or_api_key (dependency) ---
def get_current_user_or_api_key(
    auth: tuple[CurrentUser, Any] = Depends(require_api_key_or_session),
) -> CurrentUser:
    """[Flow: Step 1 (세션 또는 API key 인증) -> Step 2 (CurrentUser만 반환)]

    웹 포털 세션과 API key를 모두 허용하면서 기존 CurrentUser 의존성과 호환되는
    wrapper dependency.
    """
    return auth[0]



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
        {"basic_pages": int, "premium_pages": int, "audio_seconds": int, "video_seconds": int, "docling_refinement_pages": int}
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
    return {
        "basic_pages": basic_pages,
        "premium_pages": premium_pages,
        "audio_seconds": audio_seconds,
        "video_seconds": video_seconds,
        "docling_refinement_pages": docling_refinement_pages,
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

    check = subscription_service.check_enough(
        db,
        db_user,
        basic_pages=basic_pages,
        premium_pages=premium_pages,
        audio_seconds=audio_seconds,
        video_seconds=video_seconds,
        docling_refinement_pages=docling_refinement_pages,
    )
    return {"ok": check["ok"], "reason": check["reason"], "cost_points": check.get("cost_points", 0)}



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



def _normalize_display_name(name: str | None) -> str:
    """표시용 파일명을 Unicode 조합 정규형(NFC)으로 변환한다.

    macOS에서 생성된 압축 파일 등에 포함된 한글 파일명이 분해 정규형(NFD)으로
    저장되어 있으면 탭에서 자음/모음이 분리되어 보일 수 있다.

    [Flow: Step 1 (None/빈 문자열 처리) -> Step 2 (unicodedata.normalize('NFC'))
          -> Step 3 (예외 시 원본 반환)]
    """
    if not name:
        return ""
    try:
        return unicodedata.normalize("NFC", name)
    except Exception:
        return name



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
        elif ftype == "markdown":
            # markdown 파일은 페이지/미디어 비용 없이 total_files에만 카운트
            total_files += 1

    return pages, image_count, audio_seconds, video_seconds, total_files



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

    [Flow: Step 1 (annotated_pdf_files에서 대상 entry 찾기)
          -> Step 2 (공유 파일을 사용하는 모든 entry의 processing task 취소 및 환불)
          -> Step 3 (공유 annotations.json 삭제) -> Step 4 (AI 주석 entry 제거 + 상태 초기화)
          -> Step 5 (preview 캐시 무효화)]

    UI에서는 AI 주석 entry들이 하나의 파일로 축소되어 표시되므로, 삭제 시 job의 모든 AI 주석과
    공유 annotations.json을 한 번에 제거한다. searchable PDF는 원본 텍스트 레이어 파일이므로
    삭제하지 않는다. source_index는 annotated_pdf_files 내의 position이 아닌
    entry의 index 필드 값이다.
    """
    entries = list(job.annotated_pdf_files or [])
    if not entries:
        raise HTTPException(status_code=404, detail="Annotation file not found")

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

    # searchable PDF는 원본 텍스트 레이어 파일이므로 삭제하지 않고,
    # annotations.json만 제거한다.
    if shared_annotations_json_path:
        supabase_client.delete_storage_path("results", shared_annotations_json_path)

    job.annotated_pdf_files = kept_entries
    flag_modified(job, "annotated_pdf_files")
    if not kept_entries:
        job.annotate_status = ""
    else:
        job.annotate_status = _overall_annotation_status(kept_entries)
    job.annotate_refundable = False
    cache.invalidate_pattern(f"preview:{job.id}:*")
    db.commit()
    return {"deleted": True, "source_kind": "annotation", "source_index": source_index}



def _get_markdown_content(job: Job) -> str:
    """편집된 마크다운이 있으면 사용하고, 없으면 원본 마크다운을 다운로드한다.

    단, 편집본에 페이지 마커가 손실된 경우 원본 마크다운을 우선 사용하여
    페이지별 보기가 깨지지 않도록 한다.
    """
    client = supabase_client.get_service_client()
    candidates: list[str] = []
    if job.result_edited_md_storage_path:
        try:
            data = client.storage.from_("results").download(job.result_edited_md_storage_path)
            candidates.append(data.decode("utf-8"))
        except Exception as e:
            logger.warning(f"[get-markdown-content:{job.id}] edited_md 다운로드 실패: {e}")
    if job.result_md_storage_path:
        try:
            data = client.storage.from_("results").download(job.result_md_storage_path)
            candidates.append(data.decode("utf-8"))
        except Exception as e:
            logger.warning(f"[get-markdown-content:{job.id}] md 다운로드 실패: {e}")
    if job.result_edited_md_path and Path(job.result_edited_md_path).exists():
        candidates.append(Path(job.result_edited_md_path).read_text(encoding="utf-8"))
    if job.result_md_path and Path(job.result_md_path).exists():
        candidates.append(Path(job.result_md_path).read_text(encoding="utf-8"))

    if not candidates:
        return ""

    # 파일 마커(`<!-- 파일 N -->`)가 있는 후보를 우선 선택한다.
    # 파일 마커 수가 같으면 edited_md(후보 순서상 먼저 추가됨)를 우선한다.
    # page 마커(`<!-- Page N -->`) 수는 tie-breaker로 사용하지 않는다 —
    # save_result_page가 page 마커를 제거하므로, page 마커가 더 많은 원본이
    # 편집본보다 높은 점수를 받아 편집 내용이 무시되는 버그를 방지한다.
    def _file_marker_count(md: str) -> int:
        return len(_FILE_MARKER_RE.findall(md))

    best = max(candidates, key=_file_marker_count, default=candidates[0])
    return best



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



def _image_files(job: Job) -> list[tuple[int, dict]]:
    """extracted_files에서 이미지 파일만 순서대로 (page_num, info)로 반환한다."""
    files = job.extracted_files or []
    images: list[tuple[int, dict]] = []
    for idx, info in enumerate(files):
        if isinstance(info, dict) and info.get("type") == "image" and info.get("storage_path"):
            images.append((idx + 1, info))
    return images



def _get_file_names(job: Job) -> list[str]:
    """Job에서 파일 순서대로 표시용 파일명을 추출한다.

    [Flow: Step 1 (extracted_files가 있으면 각 항목의 path/filename/원본명 사용)
          -> Step 2 (extracted_files가 없으면 job.original_filename 또는 pdf_storage_path 사용)
          -> Step 3 (파일명이 없으면 '파일 N' 형식으로 폴백)]

    매개변수:
        job: Job 객체

    반환값:
        파일명 문자열 리스트
    """
    files = job.extracted_files or []
    if not files and job.pdf_storage_path and job.file_type in _PREVIEW_DOCUMENT_TYPES:
        return [_normalize_display_name(job.original_filename or Path(job.pdf_storage_path).name)]
    names: list[str] = []
    for i, info in enumerate(files):
        if isinstance(info, dict):
            name = info.get("filename") or info.get("path") or info.get("original_name") or ""
        else:
            name = ""
        if not name:
            name = f"파일 {i + 1}"
        names.append(_normalize_display_name(name))
    return names



def _build_source_file_item(info: dict, idx: int, source_kind: str = "original") -> dict | None:
    """단일 파일에 대한 source_files 항목을 생성한다.

    [Flow: Step 1 (metadata 유효성 검사) -> Step 2 (signed URL 생성) -> Step 3 (source_files 항목 반환, source_kind/source_index 포함)]
    """
    if not isinstance(info, dict) or not info.get("storage_path"):
        return None
    ftype = info.get("type", "")
    if ftype not in (*_PREVIEW_DOCUMENT_TYPES, "image", "audio", "video", "file", "markdown"):
        return None
    bucket = info.get("bucket", "pdfs")
    try:
        storage_path = info["storage_path"]
        if ftype in _PREVIEW_DOCUMENT_TYPES:
            # [Flow: PDF 뷰어로 미리보기 가능한 문서는 원본 URL과 PDF 미리보기 URL을 분리]
            # pdf: url == preview_url (원본 또는 clean/searchable)
            # docx/hwp/pptx: url은 원본 다운로드, preview_url은 PDF 변환 URL
            try:
                url = supabase_client.get_signed_download_url(storage_path, bucket=bucket, expires_in=3600)
            except Exception:
                return None
            if not url:
                return None

            if ftype == "pdf":
                preview_url = url
            else:
                preview_url = pdf_preview_converter.get_preview_pdf_url(
                    storage_path, source_bucket=bucket, expires_in=3600
                )

            if not preview_url and ftype != "pdf":
                # [Flow: PDF 변환 실패 시 file 타입으로 폴백 (다운로드 링크만 제공)]
                return {
                    "name": _normalize_display_name(info.get("path", info.get("storage_path", ""))),
                    "type": "file",
                    "url": url,
                    "storage_path": storage_path,
                    "bucket": bucket,
                    "page_num": idx + 1,
                    "result_markdown": info.get("result_markdown", ""),
                    "source_index": idx,
                    "source_kind": source_kind,
                    "status": info.get("status", ""),
                }

            item = {
                "name": _normalize_display_name(info.get("path", info.get("storage_path", ""))),
                "type": ftype,
                "url": url,
                "storage_path": storage_path,
                "bucket": bucket,
                "page_num": idx + 1,
                "result_markdown": info.get("result_markdown", ""),
                "preview_url": preview_url,
                "source_index": idx,
                "source_kind": source_kind,
                "status": info.get("status", ""),
            }
            # [Flow: 개별 searchable PDF가 있으면 preview_url을 대체 — 텍스트 검색/선택 가능 (pdf만)]
            # 각 extracted_files 항목은 자체 searchable_pdf_storage_path를 가질 수 있다.
            # job.searchable_pdf_storage_path (Job 레벨)는 첫 번째 원본 PDF에만 해당하므로
            # 여기서는 개별 항목의 searchable_pdf_storage_path만 사용한다.
            if ftype == "pdf":
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
        # markdown 타입은 원본 type을 유지하여 프론트엔드에서 마크다운 전용 job 여부를 판단할 수 있게 함
        if ftype in ("file", "markdown"):
            try:
                download_url = supabase_client.get_signed_download_url(storage_path, bucket=bucket, expires_in=3600)
            except Exception:
                return None
            if not download_url:
                return None
            return {
                "name": _normalize_display_name(info.get("path", info.get("storage_path", ""))),
                "type": ftype,
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
            "name": _normalize_display_name(info.get("path", info.get("storage_path", ""))),
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
    if not files and job.pdf_storage_path and job.file_type in _PREVIEW_DOCUMENT_TYPES:
        # 단일 파일 업로드: extracted_files가 없으므로 원본 파일을 직접 표시
        original_item = _build_source_file_item(
            {
                "path": _normalize_display_name(job.original_filename or Path(job.pdf_storage_path).name),
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
    # clean PDF 존재 확인을 파일마다 하지 않도록, 버킷별 목록을 루프 밖에서 한 번씩만 받는다.
    _clean_listing_by_bucket: dict[str, set[str] | None] = {}

    for i, item in enumerate(source_files):
        if item.get("source_kind") != "original" or item.get("type") != "pdf":
            continue
        item_bucket = item.get("bucket", "pdfs")
        if item_bucket not in _clean_listing_by_bucket:
            _clean_listing_by_bucket[item_bucket] = _list_bucket_files(item_bucket, job.id)
        clean_url, extracted_annotations = _ensure_clean_source_pdf(
            job.id, item.get("storage_path"), item_bucket,
            existing_names=_clean_listing_by_bucket[item_bucket],
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
                    if item.get("source_kind") == "original" and item.get("type") in _PREVIEW_DOCUMENT_TYPES:
                        item["annotations_json_url"] = annotations_json_url
                        break

    # [Flow: 파일별 user_annotations_{source_index}.json이 존재하면 AI 주석과 병합하여 각 파일에 설정]
    # 사용자가 직접 추가/편집한 주석은 파일별로 분리된 user_annotations_{source_index}.json에 저장되며,
    # 여기서 AI 주석 JSON과 병합해 각 원본 탭에서 두 주석을 중복 없이 볼 수 있도록 한다.
    # 파일별 주석 JSON이 없으면 기존 공유 user_annotations.json으로 폴백 (하위 호환).
    # [Flow: Step 1 (results 폴더 1회 목록 조회) -> Step 2 (존재하는 주석 JSON 만 병합 대상으로 선별)
    #       -> Step 3 (파일별로 병렬 병합)]
    # 목록 조회가 실패하면 existing_result_names 가 None 이 되고, 아래 _has_result 가
    # 기존처럼 signed URL 탐색으로 폴백한다 — 느리지만 동작은 동일하다.
    existing_result_names = _list_result_files(job.id)

    def _has_result(name: str) -> bool:
        """results/{job_id}/{name} 이 존재하는지 확인한다."""
        if existing_result_names is not None:
            return name in existing_result_names
        try:
            return bool(
                supabase_client.get_signed_download_url(
                    f"{job.id}/{name}", bucket="results", expires_in=3600
                )
            )
        except Exception:
            return False

    merge_targets: list[tuple[dict, int, str]] = []
    for item in source_files:
        if item.get("source_kind") != "original" or item.get("type") not in _PREVIEW_DOCUMENT_TYPES:
            continue
        file_source_index = item.get("source_index", 0)
        # [Flow: 파일별 주석 JSON 경로 — source_index별로 분리]
        per_file_name = f"user_annotations_{file_source_index}.json"
        # 하위 호환: 파일별 주석 JSON이 없으면 공유 user_annotations.json 사용 (첫 번째 파일만)
        if _has_result(per_file_name):
            merge_targets.append((item, file_source_index, f"{job.id}/{per_file_name}"))
        elif file_source_index == 0 and _has_result("user_annotations.json"):
            merge_targets.append((item, file_source_index, f"{job.id}/user_annotations.json"))

    # 병합은 파일마다 다운로드 2회 + 업로드 1회 + 서명 1회로 왕복이 길다. 순차로 돌리면
    # 파일 수에 비례해 응답이 늘어나므로, 위쪽 signed URL 생성과 같은 폭으로 병렬화한다.
    # merged 경로가 source_index 별로 분리돼 있어 서로 덮어쓰지 않는다.
    if merge_targets:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                (
                    item,
                    executor.submit(
                        _merge_annotation_jsons,
                        job.id,
                        shared_annotations_json_path,
                        path,
                        idx,
                    ),
                )
                for item, idx, path in merge_targets
            ]
            for item, future in futures:
                try:
                    merged_url = future.result()
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[source_files:{job.id}] 주석 병합 실패: {e}")
                    continue
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



def _normalize_annotation_json_to_list(data) -> list[dict]:
    """[Flow: Step 1 (data가 list이면 그대로 반환)
          -> Step 2 (dict이면 canonical document로 간주하고 annotations 추출)
          -> Step 3 (canonical 좌표를 device-space로 변환하여 list 반환)]

    c9e3c9c 이후에 생성된 job의 주석 JSON이 canonical document 형식(dict with
    coordinate_system/page_dimensions/annotations)으로 저장되어 있을 수 있다.
    c9e3c9c 코드는 flat list(device-space)만 처리하므로, dict 형식을 만나면
    annotations 배열을 추출하고 canonical 좌표를 device-space로 변환한다.
    """
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    annotations = data.get("annotations")
    if not isinstance(annotations, list):
        return []
    page_dimensions = data.get("page_dimensions") or {}
    coordinate_system = data.get("coordinate_system") or "device"
    if coordinate_system != "canonical" or not page_dimensions:
        return annotations
    return [_convert_canonical_annotation_to_device(a, page_dimensions) for a in annotations]



def _convert_canonical_annotation_to_device(item: dict, page_dimensions: dict) -> dict:
    """[Flow: Step 1 (annotation 객체 추출) -> Step 2 (pageIndex로 page_dimensions 조회)
          -> Step 3 (rect/segmentRects/calloutLine/start/end/rectangleDifferences/inkList/paths를
              canonical [0,1]에서 device-space points로 변환) -> Step 4 (갱신된 item 반환)]"""
    if not isinstance(item, dict):
        return item
    ann = item.get("annotation") if isinstance(item.get("annotation"), dict) else item
    page_index = ann.get("pageIndex")
    if not isinstance(page_index, int):
        return item
    dims = page_dimensions.get(str(page_index + 1)) or page_dimensions.get(page_index + 1)
    if not isinstance(dims, dict):
        return item
    page_width = float(dims.get("width_pt", 0) or 0)
    page_height = float(dims.get("height_pt", 0) or 0)
    if page_width <= 0 or page_height <= 0:
        return item

    def _rect(r):
        if not isinstance(r, dict):
            return r
        origin = r.get("origin") or {}
        size = r.get("size") or {}
        ox = float(origin.get("x", r.get("x", 0)) or 0)
        oy = float(origin.get("y", r.get("y", 0)) or 0)
        w = float(size.get("width", r.get("width", 0)) or 0)
        h = float(size.get("height", r.get("height", 0)) or 0)
        return {"origin": {"x": ox * page_width, "y": oy * page_height}, "size": {"width": w * page_width, "height": h * page_height}}

    def _point(p):
        if not isinstance(p, dict):
            return p
        return {"x": float(p.get("x", 0) or 0) * page_width, "y": float(p.get("y", 0) or 0) * page_height}

    def _rd(rd):
        if not isinstance(rd, dict):
            return rd
        return {
            "left": float(rd.get("left", 0) or 0) * page_width,
            "right": float(rd.get("right", 0) or 0) * page_width,
            "top": float(rd.get("top", 0) or 0) * page_height,
            "bottom": float(rd.get("bottom", 0) or 0) * page_height,
        }

    new_ann = dict(ann)
    if isinstance(new_ann.get("rect"), dict):
        new_ann["rect"] = _rect(new_ann["rect"])
    if isinstance(new_ann.get("segmentRects"), list):
        new_ann["segmentRects"] = [_rect(r) for r in new_ann["segmentRects"] if isinstance(r, dict)]
    if isinstance(new_ann.get("calloutLine"), list):
        new_ann["calloutLine"] = [_point(p) for p in new_ann["calloutLine"] if isinstance(p, dict)]
    if isinstance(new_ann.get("start"), dict):
        new_ann["start"] = _point(new_ann["start"])
    if isinstance(new_ann.get("end"), dict):
        new_ann["end"] = _point(new_ann["end"])
    if isinstance(new_ann.get("rectangleDifferences"), dict):
        new_ann["rectangleDifferences"] = _rd(new_ann["rectangleDifferences"])
    if isinstance(new_ann.get("inkList"), list):
        new_ann["inkList"] = [
            {**ink, "points": [_point(p) for p in ink.get("points", []) if isinstance(p, dict)]}
            for ink in new_ann["inkList"] if isinstance(ink, dict)
        ]
    if isinstance(new_ann.get("paths"), list):
        new_ann["paths"] = [
            [_point(p) for p in stroke if isinstance(p, dict)]
            for stroke in new_ann["paths"] if isinstance(stroke, list)
        ]

    if isinstance(item.get("annotation"), dict):
        return {**item, "annotation": new_ann}
    return new_ann



def _annotation_id(item: dict) -> str:
    """[Flow: Step 1 (item이 dict인지 확인) -> Step 2 (annotation.id 추출) -> Step 3 (반환)]

    EmbedPDF AnnotationTransferItem에서 주석 ID를 추출한다.
    """
    if not isinstance(item, dict):
        return ""
    if "annotation" in item and isinstance(item["annotation"], dict):
        return item["annotation"].get("id", "")
    return item.get("id", "")



def _list_bucket_files(bucket: str, prefix: str) -> set[str] | None:
    """버킷의 prefix 폴더에 존재하는 파일 이름 집합을 1회 호출로 조회한다.

    [Flow: Step 1 ({bucket}/{prefix} 목록 조회) -> Step 2 (이름 집합 반환) -> Step 3 (실패 시 None)]

    이 함수가 없으면 호출부는 "signed URL 생성이 성공하는가" 또는 "download() 가 성공하는가"로
    파일 존재를 확인하게 된다. 전자는 없는 객체마다 404 왕복을 낭비하고, 후자는 존재 여부를
    알아내자고 파일 전체를 내려받는다. 목록 조회 한 번이 둘 다를 대체한다.

    Returns:
        존재하는 파일 이름 집합. 목록 조회 자체가 실패하면 None (호출부가 기존 탐색으로 폴백).
    """
    try:
        client = supabase_client.get_service_client()
        entries = client.storage.from_(bucket).list(prefix, {"limit": 1000})
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[_list_bucket_files] {bucket}/{prefix} 목록 조회 실패, 개별 탐색으로 폴백: {e}")
        return None
    if not isinstance(entries, list):
        return None
    return {e["name"] for e in entries if isinstance(e, dict) and e.get("name")}



def _list_result_files(job_id: str) -> set[str] | None:
    """results 버킷의 job 폴더에 존재하는 파일 이름 집합을 반환한다."""
    return _list_bucket_files("results", job_id)



def _merge_annotation_jsons(
    job_id: str,
    ai_annotations_path: str | None,
    user_annotations_path: str,
    source_index: int = 0,
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
            merged.extend(_normalize_annotation_json_to_list(ai_list))
        except Exception:
            pass
    try:
        user_bytes = client.storage.from_("results").download(user_annotations_path)
        user_list = json.loads(user_bytes.decode("utf-8"))
        merged.extend(_normalize_annotation_json_to_list(user_list))
    except Exception:
        pass
    merged = _deduplicate_annotations(merged)
    # 병합 결과는 원본 파일별로 분리한다. 단일 공유 경로에 쓰면 파일이 여러 개인 job 에서
    # 마지막 병합이 앞선 파일의 결과를 덮어써, 모든 탭이 같은 주석을 가리키게 된다.
    # 경로가 분리돼 있어야 아래 병렬 병합도 서로를 침범하지 않는다.
    merged_path = f"{job_id}/merged_annotations_{source_index}.json"
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



def _clean_pdf_verdict_key(job_id: str, path_hash: str) -> str:
    """clean PDF 판정 캐시 키.

    preview 캐시와 같은 `preview:{job_id}:` 네임스페이스를 쓴다. 이렇게 해야
    이미 열 군데에서 호출하는 `cache.invalidate_pattern(f"preview:{job_id}:*")` 가
    이 판정까지 함께 쓸어간다 — 무효화 지점을 새로 만들지 않아도 된다.
    """
    return f"preview:{job_id}:cleanpdf:{path_hash}"



def _ensure_clean_source_pdf(
    job_id: str,
    storage_path: str,
    bucket: str = "pdfs",
    existing_names: set[str] | None = None,
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
    clean_name = f"clean_{path_hash}.pdf"
    verdict_key = _clean_pdf_verdict_key(job_id, path_hash)

    # Step 0: 이전 판정이 남아 있으면 Storage 를 건드리지 않고 끝낸다.
    # "내장 주석 없음"은 예전에는 아무 데도 기록되지 않아, preview 캐시가 만료될 때마다
    # 원본 PDF 전체를 다시 내려받고 PyMuPDF 파싱을 다시 돌렸다 — 결과는 늘 같은데도.
    verdict = cache.get(verdict_key)
    if isinstance(verdict, dict):
        if verdict.get("state") == "none":
            return None, []
        if verdict.get("state") == "clean":
            try:
                url = supabase_client.get_signed_download_url(
                    clean_storage_path, bucket=bucket, expires_in=3600
                )
                if url:
                    return url, None
            except Exception:
                # 판정이 낡았다(파일이 사라졌다). 아래 정상 경로로 다시 판정한다.
                pass

    # Step 1: clean PDF가 이미 존재하는지 확인한다.
    # get_signed_download_url()은 존재하지 않는 객체라도 signed URL을 반환할 수 있으므로
    # 존재 확인에 쓸 수 없다. 예전에는 대신 download() 로 확인했는데, 존재 여부를 알자고
    # 파일 전체를 내려받아 버리는 낭비였다. 폴더 목록 조회로 이름만 확인한다.
    if existing_names is None:
        existing_names = _list_bucket_files(bucket, job_id)
    clean_exists: bool
    if existing_names is not None:
        clean_exists = clean_name in existing_names
    else:
        # 목록 조회가 불가능한 환경에서는 기존 download() 확인으로 폴백한다.
        try:
            supabase_client.get_service_client().storage.from_(bucket).download(clean_storage_path)
            clean_exists = True
        except Exception:
            clean_exists = False
    if clean_exists:
        try:
            url = supabase_client.get_signed_download_url(clean_storage_path, bucket=bucket, expires_in=3600)
        except Exception as e:
            logger.warning(f"[_ensure_clean_source_pdf] {job_id} clean PDF URL 생성 실패: {e}")
            url = None
        if url:
            cache.set(verdict_key, {"state": "clean"}, ttl_seconds=_CLEAN_PDF_VERDICT_TTL)
            return url, None

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
        # 내장 주석이 없다는 사실을 기록해 두어야 다음 preview 캐시 미스에서
        # 같은 원본을 또 내려받아 또 파싱하는 일이 없다.
        cache.set(verdict_key, {"state": "none"}, ttl_seconds=_CLEAN_PDF_VERDICT_TTL)
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
        # 판정 캐시도 같은 네임스페이스에 있어 함께 지워지므로, 아래에서 다시 심는다.
        cache.invalidate_pattern(f"preview:{job_id}:*")
        cache.set(verdict_key, {"state": "clean"}, ttl_seconds=_CLEAN_PDF_VERDICT_TTL)
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
            existing_list = _normalize_annotation_json_to_list(existing)
            if existing_list:
                annotations = existing_list + annotations
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
        if ftype in ("audio", "video", "docx", "hwp", "pptx"):
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
    if ext in (".pptx", ".ppt", ".ppsx", ".pps"):
        return "pptx"
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



def _split_markdown_by_pages(markdown: str, expected_pages: int | None = None) -> list[tuple[int, str]]:
    """페이지 마커를 기준으로 마크다운을 분할한다.

    [Flow: Step 1 (한/영 페이지 마커 매칭) -> Step 2 (마커 기준 분할) ->
          Step 3 (마커 부족 시 Horizontal Rule로 분할) -> Step 4 (그래도 부족 시 expected_pages 개로 길이 분할)]

    매개변수:
        markdown: 분할할 마크다운 문자열
        expected_pages: PDF 총 페이지 수 힌트 (미지정 시 1)

    반환값:
        [(page_num, content), ...] 튜플 리스트
    """
    matches = list(_PAGE_MARKER_RE.finditer(markdown))
    if matches:
        pages: list[tuple[int, str]] = []
        for idx, match in enumerate(matches):
            page_num = int(match.group(1))
            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown)
            content = markdown[start:end].strip()
            # 페이지 마커 사이에 삽입된 Horizontal Rule 구분자 제거
            content = _re.sub(r"(?:^|\n+)(?:\s*[-_*]\s*[-_*]\s*[-_*][-\s*_]*\s*)\s*$", "", content).strip()
            if content:
                pages.append((page_num, content))
        return pages

    content = markdown.strip()
    if not content:
        return []

    # 마커가 없으면 Horizontal Rule로 분할 시도
    parts = [p.strip() for p in _HR_SPLIT_RE.split(content) if p.strip()]
    if len(parts) >= 2:
        return [(i + 1, p) for i, p in enumerate(parts)]

    # 마커/구분자 모두 없으면 expected_pages 힌트로 균등 분할
    target = expected_pages if expected_pages and expected_pages > 1 else 1
    if target == 1:
        return [(1, content)]

    total_len = len(content)
    chunk_size = total_len // target
    chunks: list[tuple[int, str]] = []
    for i in range(target):
        start = i * chunk_size
        end = total_len if i == target - 1 else (i + 1) * chunk_size
        chunk = content[start:end].strip()
        if chunk:
            chunks.append((i + 1, chunk))
    return chunks if chunks else [(1, content)]



def _split_markdown_by_files(markdown: str) -> list[tuple[int, str]]:
    """파일 구분자(`<!-- 파일 N -->`)를 기준으로 마크다운을 분할한다.

    [Flow: Step 1 (파일 마커 매칭) -> Step 2 (마커 기준 분할) ->
          Step 3 (마커가 없으면 전체를 1개 파일로 반환)]

    매개변수:
        markdown: 분할할 마크다운 문자열

    반환값:
        [(file_num, content), ...] 튜플 리스트
    """
    matches = list(_FILE_MARKER_RE.finditer(markdown))
    if matches:
        files: list[tuple[int, str]] = []
        for idx, match in enumerate(matches):
            file_num = int(match.group(1))
            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown)
            content = markdown[start:end].strip()
            # 파일 마커 사이에 삽입된 Horizontal Rule 구분자 제거
            content = _re.sub(r"(?:^|\n+)(?:\s*[-_*]\s*[-_*]\s*[-_*][-\s*_]*\s*)\s*$", "", content).strip()
            if content:
                files.append((file_num, content))
        return files

    content = markdown.strip()
    if not content:
        return []
    return [(1, content)]



def _ensure_xlsx_basic_bundle(job: Job, db: Session) -> None:
    """CSV/XLSX 기본 변환 번들을 한 번 수행한다. 이미 변환된 경우 아무것도 하지 않는다.
    크레딧 시스템: basic_pages 단위로 사용량을 차감한다."""
    if job.result_xlsx_basic_storage_path and job.result_csv_storage_path:
        return
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



def _cross_validate_matches_with_ocr_layout(
    matches: list[dict],
    job,
    client,
    pdf_bytes: bytes,
    query: str,
    page_no_filter: int | None,
) -> list[dict]:
    """[Flow: Step 1 (저장된 OCR layout 다운로드) -> Step 2 (OCR 요소를 device-space로 변환)
          -> Step 3 (각 search_for 매치와 OCR 요소를 텍스트+페이지로 매칭)
          -> Step 4 (y 차이가 임계값 초과 시 OCR layout y로 보정)
          -> Step 5 (보정된 matches 반환)]

    search_for가 텍스트를 찾았더라도, 수정 전 코드로 생성된 searchable PDF의
    반전된 텍스트 레이어 때문에 y 좌표가 잘못될 수 있다.
    저장된 OCR layout의 시각적 위치(정답)와 비교하여 y 좌표를 보정한다.

    Args:
        matches: search_for가 반환한 매치 목록 (device-space 좌표)
        job: Job 모델 인스턴스 (result_ocr_layout_storage_path 필요)
        client: Supabase 서비스 클라이언트
        pdf_bytes: searchable PDF 바이트
        query: 검색어 문자열
        page_no_filter: 특정 페이지만 검색 중이면 페이지 번호, None이면 전체

    Returns:
        y 좌표가 보정된 matches 목록. OCR layout 로드 실패 시 원본 matches 그대로 반환.
    """
    import fitz as _fitz

    # Step 1: 저장된 OCR layout 다운로드
    try:
        from ...core.pdf_annotate_converter import build_agent_elements_from_ocr_layout

        layout_raw = client.storage.from_("results").download(job.result_ocr_layout_storage_path)
        layout_by_page = {int(k): v for k, v in json.loads(layout_raw.decode("utf-8")).items()}
        ocr_page_range = [page_no_filter] if page_no_filter is not None else None
        ocr_elements = build_agent_elements_from_ocr_layout(layout_by_page, pdf_bytes, page_range=ocr_page_range)
    except Exception as e:
        logger.warning(f"[search_job_text] OCR layout 교차 검증 로드 실패: {e}")
        return matches

    if not ocr_elements:
        return matches

    # Step 2: 페이지별 page_rect 구축
    # [주의] OCR 요소의 bbox_pdf는 _normalize_bbox(y축 1차 반전) +
    #       _normalized_bbox_to_pdf_user(y축 2차 반전)를 거쳐 device-space와
    #       동일한 좌표계가 된다. 따라서 추가 변환 없이 그대로 사용한다.
    page_rect_map: dict[int, _fitz.Rect] = {}
    try:
        _doc = _fitz.open(stream=pdf_bytes, filetype="pdf")
        for _page in _doc:
            page_rect_map[_page.number + 1] = _page.rect
        _doc.close()
    except Exception as e:
        logger.warning(f"[search_job_text] OCR layout 교차 검증 page rect 구축 실패: {e}")
        return matches

    # OCR 요소를 페이지별로 그룹화 (bbox_pdf는 이미 device-space)
    ocr_by_page: dict[int, list[dict]] = {}
    for el in ocr_elements:
        el_page_no = el.get("page_no", 1)
        el_bbox = list(el["bbox_pdf"])
        ocr_by_page.setdefault(el_page_no, []).append({
            "text": el.get("text", ""),
            "device_bbox": el_bbox,
            "kind": el.get("kind", ""),
        })

    # Step 3 + 4: 각 search_for 매치와 OCR 요소를 비교하여 y 보정
    try:
        pattern = _re.compile(query, _re.IGNORECASE)
    except _re.error:
        pattern = _re.compile(_re.escape(query), _re.IGNORECASE)

    corrected_count = 0
    for match in matches:
        match_page = match["page_no"]
        match_text = match.get("text", "")
        match_bbox = match["bbox_pdf"]
        match_y_center = (match_bbox[1] + match_bbox[3]) / 2.0

        page_rect = page_rect_map.get(match_page)
        if page_rect is None:
            continue
        # 임계값: 페이지 높이의 10% — 이 이상 차이나면 좌표계 오류로 간주
        y_threshold = page_rect.height * 0.1

        # 같은 페이지의 OCR 요소 중, query 텍스트를 포함하고 y 차이가 가장 작은 요소 찾기
        page_ocr_elements = ocr_by_page.get(match_page, [])
        best_ocr = None
        best_y_diff = float("inf")
        for ocr_el in page_ocr_elements:
            if not pattern.search(ocr_el["text"]):
                continue
            ocr_bbox = ocr_el["device_bbox"]
            ocr_y_center = (ocr_bbox[1] + ocr_bbox[3]) / 2.0
            y_diff = abs(match_y_center - ocr_y_center)
            if y_diff < best_y_diff:
                best_y_diff = y_diff
                best_ocr = ocr_el

        # y 차이가 임계값 초과 시 OCR layout y로 보정
        if best_ocr is not None and best_y_diff > y_threshold:
            ocr_bbox = best_ocr["device_bbox"]
            old_y0, old_y1 = match_bbox[1], match_bbox[3]
            # x 좌표는 search_for의 정밀한 위치를 유지, y 좌표만 OCR layout으로 보정
            match_bbox[1] = ocr_bbox[1]
            match_bbox[3] = ocr_bbox[3]
            corrected_count += 1
            logger.info(
                f"[search_job_text] OCR layout y 보정: page={match_page} "
                f"text='{match_text[:40]}' "
                f"y0 {old_y0:.1f}→{ocr_bbox[1]:.1f}, y1 {old_y1:.1f}→{ocr_bbox[3]:.1f} "
                f"(차이={best_y_diff:.1f} > 임계값={y_threshold:.1f})"
            )

    if corrected_count > 0:
        logger.info(
            f"[search_job_text] OCR layout 교차 검증: {corrected_count}개 매치 y 좌표 보정됨"
        )

    return matches



def _expand_match_to_line(
    match: dict,
    page_rect: Any,
    expand: bool = True,
) -> dict:
    """[Flow: Step 1 (match의 bbox와 page_rect 확인) -> Step 2 (expand=True면 x 범위를 페이지 전체로 확장)
          -> Step 3 (y 범위는 유지) -> Step 4 (확장된 match 반환)]

    스캔 PDF 출신 searchable PDF에서 하이라이트/주석을 해당 줄 전체에 표시하기 위해,
    match의 bbox x 범위를 페이지 전체 너비(좌우 5% 여백)로 확장한다.
    y 범위는 유지하여 줄 높이는 그대로 유지한다.

    Args:
        match: 검색 매치 딕셔너리 (page_no, bbox_pdf, text 포함)
        page_rect: PyMuPDF Page.rect 객체 (x0, y0, x1, y1)
        expand: True면 x 범위 확장, False면 원본 유지

    Returns:
        확장된 match 딕셔너리 (원본 변경 없이 새 딕셔너리 반환)
    """
    if not expand:
        return dict(match)

    bbox = list(match.get("bbox_pdf", []))
    if len(bbox) < 4:
        return dict(match)

    # 좌우 5% 여백을 둔 페이지 전체 너비로 x 범위 확장
    page_width = float(page_rect.x1 - page_rect.x0)
    margin = page_width * 0.05
    new_x0 = float(page_rect.x0) + margin
    new_x1 = float(page_rect.x1) - margin

    expanded = dict(match)
    expanded["bbox_pdf"] = [new_x0, bbox[1], new_x1, bbox[3]]
    return expanded



def _is_rect_plausible_for_page(rect: fitz.Rect, page_rect: fitz.Rect) -> bool:
    """검색된 텍스트 bbox가 페이지 크기 대비 비정상적으로 크거나 멀리 벗어나지 않는지 확인한다.

    손상된 텍스트 레이어(잘못된 좌표계로 삽입된 OCR 텍스트 등)에서 search_for가
    거대한 bbox를 반환할 경우 이를 걸러내어 OCR 폴백을 유도한다.
    """
    if not rect or not page_rect:
        return False
    tolerance = max(page_rect.width, page_rect.height) * 2.0
    if rect.width > tolerance or rect.height > tolerance:
        return False
    if (
        rect.x0 < page_rect.x0 - tolerance
        or rect.x1 > page_rect.x1 + tolerance
        or rect.y0 < page_rect.y0 - tolerance
        or rect.y1 > page_rect.y1 + tolerance
    ):
        return False
    return True



def _compute_coordinate_validation(
    search_for_rects: list[dict],
    text_blocks: list[dict],
    ocr_elements: list[dict],
    page_rect,
    query: str,
) -> dict:
    """[Flow: Step 1 (search_for ↔ text_blocks y 차이 계산)
          -> Step 2 (search_for ↔ ocr_elements y 차이 계산)
          -> Step 3 (표 행 순서 단조성 검사 — ocr_elements table_row의 y가 HTML 순서대로 증가?)
          -> Step 4 (PASS/FAIL 판정 + 상세 메시지)]

    디버그 페이지에서 비전 모델 없이도 좌표 정합 상태를 자동 판정하기 위한 검증 로직.
    세 가지 검사를 수행하여 PASS/FAIL과 상세 메시지를 반환한다.

    Args:
        search_for_rects: search_for 결과 (device-space)
        text_blocks: PDF 텍스트 레이어 블록 (device-space)
        ocr_elements: OCR layout 요소 (device-space)
        page_rect: 페이지 Rect
        query: 검색어

    Returns:
        {"status": "pass"|"fail"|"warn", "checks": [...], "summary": str}
    """
    import fitz as _fitz
    y_threshold = page_rect.height * 0.10  # 페이지 높이의 10%
    checks = []

    # Check 1: search_for ↔ text_blocks y 일치도
    if search_for_rects and text_blocks:
        max_y_diff = 0.0
        worst_pair = None
        for sf in search_for_rects:
            sf_y_center = (sf["device"][1] + sf["device"][3]) / 2.0
            sf_text = sf.get("text", "")
            # 가장 가까운 text_block 찾기 (텍스트 포함 또는 y 거리)
            best_diff = float("inf")
            best_tb = None
            for tb in text_blocks:
                tb_y_center = (tb["device"][1] + tb["device"][3]) / 2.0
                y_diff = abs(sf_y_center - tb_y_center)
                if y_diff < best_diff:
                    best_diff = y_diff
                    best_tb = tb
            if best_diff > max_y_diff:
                max_y_diff = best_diff
                worst_pair = (sf_text, best_tb.get("text", "") if best_tb else "")
        status_1 = "pass" if max_y_diff < y_threshold else "fail"
        checks.append({
            "name": "search_for ↔ text_blocks y 일치도",
            "status": status_1,
            "max_y_diff": round(max_y_diff, 1),
            "threshold": round(y_threshold, 1),
            "detail": (
                f"최대 y 차이: {max_y_diff:.1f}px (임계값: {y_threshold:.1f}px)"
                if worst_pair is None else
                f"최대 y 차이: {max_y_diff:.1f}px — '{worst_pair[0][:20]}' ↔ '{worst_pair[1][:20]}'"
            ),
        })

    # Check 2: search_for ↔ ocr_elements y 일치도
    if search_for_rects and ocr_elements:
        max_y_diff = 0.0
        worst_pair = None
        for sf in search_for_rects:
            sf_y_center = (sf["device"][1] + sf["device"][3]) / 2.0
            sf_text = sf.get("text", "")
            best_diff = float("inf")
            best_ocr = None
            for ocr in ocr_elements:
                ocr_y_center = (ocr["device"][1] + ocr["device"][3]) / 2.0
                y_diff = abs(sf_y_center - ocr_y_center)
                if y_diff < best_diff:
                    best_diff = y_diff
                    best_ocr = ocr
            if best_diff > max_y_diff:
                max_y_diff = best_diff
                worst_pair = (sf_text, best_ocr.get("text", "") if best_ocr else "")
        status_2 = "pass" if max_y_diff < y_threshold else "fail"
        checks.append({
            "name": "search_for ↔ ocr_elements y 일치도",
            "status": status_2,
            "max_y_diff": round(max_y_diff, 1),
            "threshold": round(y_threshold, 1),
            "detail": (
                f"최대 y 차이: {max_y_diff:.1f}px (임계값: {y_threshold:.1f}px)"
                if worst_pair is None else
                f"최대 y 차이: {max_y_diff:.1f}px — '{worst_pair[0][:20]}' ↔ '{worst_pair[1][:20]}'"
            ),
        })

    # Check 3: 표 행 순서 단조성 (ocr_elements table_row의 y가 순서대로 증가?)
    table_rows = [el for el in ocr_elements if el.get("kind") == "table_row"]
    if len(table_rows) >= 2:
        y_centers = [(el["device"][1] + el["device"][3]) / 2.0 for el in table_rows]
        is_monotonic = all(y_centers[i] < y_centers[i + 1] for i in range(len(y_centers) - 1))
        # 반전 검사: y가 단조 감소하면 반전된 것
        is_decreasing = all(y_centers[i] > y_centers[i + 1] for i in range(len(y_centers) - 1))
        if is_monotonic:
            status_3 = "pass"
            detail_3 = f"표 행 {len(table_rows)}개: y가 HTML 순서대로 단조 증가 (정상)"
        elif is_decreasing:
            status_3 = "fail"
            detail_3 = f"표 행 {len(table_rows)}개: y가 HTML 순서의 역순으로 단조 감소 (반전됨!)"
        else:
            status_3 = "warn"
            detail_3 = f"표 행 {len(table_rows)}개: y 순서가 불규칙 (부분 반전 가능성)"
        checks.append({
            "name": "표 행 순서 단조성 (ocr_elements table_row)",
            "status": status_3,
            "detail": detail_3,
        })

    # Check 4: text_blocks 표 행 순서 단조성
    # "|" 구분자가 포함된 블록을 표 행으로 간주
    table_text_blocks = [b for b in text_blocks if "|" in b.get("text", "") and b["device"][1] > 100]
    if len(table_text_blocks) >= 2:
        y_centers_tb = [(b["device"][1] + b["device"][3]) / 2.0 for b in table_text_blocks]
        is_monotonic_tb = all(y_centers_tb[i] < y_centers_tb[i + 1] for i in range(len(y_centers_tb) - 1))
        is_decreasing_tb = all(y_centers_tb[i] > y_centers_tb[i + 1] for i in range(len(y_centers_tb) - 1))
        if is_monotonic_tb:
            status_4 = "pass"
            detail_4 = f"text_blocks 표 행 {len(table_text_blocks)}개: y가 단조 증가 (정상)"
        elif is_decreasing_tb:
            status_4 = "fail"
            detail_4 = f"text_blocks 표 행 {len(table_text_blocks)}개: y가 단조 감소 (반전됨!)"
        else:
            status_4 = "warn"
            detail_4 = f"text_blocks 표 행 {len(table_text_blocks)}개: y 순서 불규칙"
        checks.append({
            "name": "표 행 순서 단조성 (text_blocks)",
            "status": status_4,
            "detail": detail_4,
        })

    # Check 5: 문단(비표 텍스트) search_for ↔ ocr_elements y 차이
    # 표 행이 아닌 ocr_elements(kind != table_row)와 search_for의 y 차이를 검사한다.
    # 문단이 여러 줄인데 text layer에서 한 줄로 배치되면 y 차이가 발생한다.
    # [주의] search_for 결과가 표 행(table_row) ocr_element의 y 범위 안에 있으면
    #        이 검사에서 제외한다. 표 행 텍스트는 비표 ocr_element와 비교하면
    #        당연히 y 차이가 크므로 잘못된 FAIL이 발생한다.
    paragraph_ocr = [el for el in ocr_elements if el.get("kind") != "table_row"]
    table_row_ocr = [el for el in ocr_elements if el.get("kind") == "table_row"]
    if search_for_rects and paragraph_ocr:
        max_para_y_diff = 0.0
        worst_para_pair = None
        checked_count = 0
        for sf in search_for_rects:
            sf_y_center = (sf["device"][1] + sf["device"][3]) / 2.0
            sf_text = sf.get("text", "")
            # search_for 결과가 표 행 ocr_element의 y 범위 안에 있으면 제외
            in_table_row = any(
                ocr["device"][1] <= sf_y_center <= ocr["device"][3]
                for ocr in table_row_ocr
            )
            if in_table_row:
                continue
            checked_count += 1
            # 가장 가까운 비표 ocr_element 찾기
            best_diff = float("inf")
            best_ocr = None
            for ocr in paragraph_ocr:
                ocr_y_center = (ocr["device"][1] + ocr["device"][3]) / 2.0
                y_diff = abs(sf_y_center - ocr_y_center)
                if y_diff < best_diff:
                    best_diff = y_diff
                    best_ocr = ocr
            if best_diff > max_para_y_diff:
                max_para_y_diff = best_diff
                worst_para_pair = (sf_text, best_ocr.get("text", "") if best_ocr else "")
        if checked_count > 0:
            status_5 = "pass" if max_para_y_diff < y_threshold else "fail"
            checks.append({
                "name": "문단 search_for ↔ ocr_elements y 일치도",
                "status": status_5,
                "max_y_diff": round(max_para_y_diff, 1),
                "threshold": round(y_threshold, 1),
                "detail": (
                    f"최대 y 차이: {max_para_y_diff:.1f}px (임계값: {y_threshold:.1f}px, {checked_count}개 비표 매치 검사)"
                    if worst_para_pair is None else
                    f"최대 y 차이: {max_para_y_diff:.1f}px — '{worst_para_pair[0][:20]}' ↔ '{worst_para_pair[1][:20]}' ({checked_count}개 비표 매치 검사)"
                ),
            })

    # Check 6: 문단 text_blocks y 범위 vs ocr_elements y 범위
    # 같은 문단에 속하는 text_blocks의 y 범위(최소 y0 ~ 최대 y1)가
    # ocr_elements의 y 범위와 비슷한지 검사한다.
    # text layer에서 문단이 한 줄로 배치되면 text_blocks y 범위가 ocr_elements보다 훨씬 작다.
    if text_blocks and paragraph_ocr:
        # 비표 text_blocks (| 구분자 없음, y > 100으로 표 행 제외, y < 700으로 푸터 제외)
        para_text_blocks = [b for b in text_blocks if "|" not in b.get("text", "") and b["text"].strip() and 100 < b["device"][1] < 700]
        if para_text_blocks and paragraph_ocr:
            # 각 ocr_element에 대해, 그 y 범위 안에 있는 text_blocks의 y 범위를 비교
            max_range_ratio = 0.0
            worst_range_pair = None
            for ocr in paragraph_ocr:
                ocr_y0 = ocr["device"][1]
                ocr_y1 = ocr["device"][3]
                ocr_height = ocr_y1 - ocr_y0
                if ocr_height <= 0:
                    continue
                # 이 ocr_element의 y 범위 안에 있는 text_blocks 찾기
                overlapping_tbs = [
                    b for b in para_text_blocks
                    if b["device"][1] >= ocr_y0 - 5 and b["device"][3] <= ocr_y1 + 5
                ]
                if not overlapping_tbs:
                    continue
                # text_blocks의 합산 y 범위
                tb_y0 = min(b["device"][1] for b in overlapping_tbs)
                tb_y1 = max(b["device"][3] for b in overlapping_tbs)
                tb_height = tb_y1 - tb_y0
                if tb_height <= 0:
                    continue
                # ocr_height 대비 tb_height 비율 (1.0에 가까울수록 정상)
                ratio = tb_height / ocr_height
                if ratio > max_range_ratio:
                    max_range_ratio = ratio
                    worst_range_pair = (
                        ocr.get("text", "")[:20],
                        len(overlapping_tbs),
                        tb_height,
                        ocr_height,
                    )
            # 비율이 0.5 이상이면 정상 (text_blocks가 ocr_elements y 범위의 50% 이상을 커버)
            if max_range_ratio < 0.3:
                status_6 = "fail"
                detail_6 = (
                    f"문단 y 범위 비율: {max_range_ratio:.2f} — "
                    f"text_blocks y 범위 {worst_range_pair[2]:.1f}px vs ocr_elements y 범위 {worst_range_pair[3]:.1f}px "
                    f"({worst_range_pair[1]}개 text_blocks, '{worst_range_pair[0]}')"
                )
            elif max_range_ratio < 0.5:
                status_6 = "warn"
                detail_6 = f"문단 y 범위 비율: {max_range_ratio:.2f} (text_blocks가 ocr_elements 범위의 절반 미만)"
            else:
                status_6 = "pass"
                detail_6 = f"문단 y 범위 비율: {max_range_ratio:.2f} (정상, {worst_range_pair[1]}개 text_blocks가 ocr_element 범위를 커버)"
            checks.append({
                "name": "문단 text_blocks y 범위 vs ocr_elements y 범위",
                "status": status_6,
                "detail": detail_6,
            })

    # Check 7: 문단 줄 순서 (text_blocks y 순서 vs OCR 텍스트 순서)
    # 같은 문단(ocr_element)에 속하는 text_blocks를 y 오름차순(상단→하단)으로 정렬했을 때,
    # 첫 text_block의 텍스트가 OCR 텍스트의 첫 부분과 일치해야 한다.
    # 반전된 경우: 첫 text_block(상단)이 OCR 텍스트의 마지막 부분을 포함하게 된다.
    if text_blocks and paragraph_ocr:
        para_text_blocks_all = [b for b in text_blocks if "|" not in b.get("text", "") and b["text"].strip() and 100 < b["device"][1] < 700]
        if para_text_blocks_all and paragraph_ocr:
            order_fail_count = 0
            order_checks = 0
            worst_order_mismatch = None
            for ocr in paragraph_ocr:
                ocr_y0 = ocr["device"][1]
                ocr_y1 = ocr["device"][3]
                ocr_text = ocr.get("text", "").strip()
                if not ocr_text:
                    continue
                # 이 ocr_element의 y 범위 안에 있는 text_blocks 찾기 (y 오름차순 정렬)
                overlapping_tbs = [
                    b for b in para_text_blocks_all
                    if b["device"][1] >= ocr_y0 - 5 and b["device"][3] <= ocr_y1 + 5
                ]
                if len(overlapping_tbs) < 2:
                    continue
                # y 오름차순 (상단→하단, device-space y=0 상단)
                overlapping_tbs_sorted = sorted(overlapping_tbs, key=lambda b: b["device"][1])
                # OCR 텍스트의 첫 단어
                ocr_first_word = ocr_text.split(" ")[0].strip() if ocr_text else ""
                if not ocr_first_word:
                    continue
                # 첫 text_block(상단)의 텍스트에 OCR 첫 단어가 포함되어야 함
                first_tb_text = overlapping_tbs_sorted[0].get("text", "").strip()
                order_checks += 1
                if ocr_first_word not in first_tb_text:
                    # 반대로 마지막 text_block(하단)에 OCR 첫 단어가 있으면 반전
                    last_tb_text = overlapping_tbs_sorted[-1].get("text", "").strip()
                    if ocr_first_word in last_tb_text:
                        order_fail_count += 1
                        worst_order_mismatch = (
                            ocr_first_word[:15],
                            first_tb_text[:20],
                            overlapping_tbs_sorted[0]["device"][1],
                            last_tb_text[:20],
                            overlapping_tbs_sorted[-1]["device"][1],
                        )
            if order_checks > 0 and order_fail_count > 0:
                status_7 = "fail"
                detail_7 = (
                    f"문단 줄 순서 반전: OCR 첫 단어 '{worst_order_mismatch[0]}'가 "
                    f"상단(y={worst_order_mismatch[2]:.1f}, '{worst_order_mismatch[1]}')이 아닌 "
                    f"하단(y={worst_order_mismatch[4]:.1f}, '{worst_order_mismatch[3]}')에 있음"
                )
            elif order_checks > 0:
                status_7 = "pass"
                detail_7 = f"문단 줄 순서: {order_checks}개 문단 검사, 모두 정상 (첫 단어가 상단에 위치)"
            else:
                status_7 = "warn"
                detail_7 = "문단 줄 순서: 검사할 다중 줄 문단이 없음"
            checks.append({
                "name": "문단 줄 순서 (text_blocks y 순서 vs OCR 텍스트 순서)",
                "status": status_7,
                "detail": detail_7,
            })

    # 종합 판정
    if not checks:
        return {"status": "warn", "checks": [], "summary": "검사할 데이터가 부족함"}
    fail_count = sum(1 for c in checks if c["status"] == "fail")
    warn_count = sum(1 for c in checks if c["status"] == "warn")
    if fail_count > 0:
        overall = "fail"
        summary = f"FAIL: {fail_count}개 검사 실패, {warn_count}개 경고"
    elif warn_count > 0:
        overall = "warn"
        summary = f"WARN: {warn_count}개 경고, 실패 없음"
    else:
        overall = "pass"
        summary = f"PASS: {len(checks)}개 검사 모두 통과"

    return {"status": overall, "checks": checks, "summary": summary}



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
            all_annotations.extend(_normalize_annotation_json_to_list(existing))
        except Exception:
            pass

    # 사용자 주석 로드 — 파일별 분리된 user_annotations_{source_index}.json 우선
    user_annotations_json_path = f"{job.id}/user_annotations_{source_index}.json"
    try:
        user_bytes = client.storage.from_("results").download(user_annotations_json_path)
        user_annotations = json.loads(user_bytes.decode("utf-8"))
        user_list = _normalize_annotation_json_to_list(user_annotations)
        if user_list:
            existing_ids = {_annotation_id(a) for a in all_annotations if _annotation_id(a)}
            for a in user_list:
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
            user_list = _normalize_annotation_json_to_list(user_annotations)
            if user_list:
                existing_ids = {_annotation_id(a) for a in all_annotations if _annotation_id(a)}
                for a in user_list:
                    aid = _annotation_id(a)
                    if aid and aid in existing_ids:
                        continue
                    all_annotations.append(a)
        except Exception:
            pass

    # page_no 필터링 — EmbedPDF 주석의 pageIndex는 0-based이므로 page_no - 1과 비교
    if page_no is not None and isinstance(page_no, int):
        filtered = []
        for a in all_annotations:
            inner = _annotation_inner(a)
            if inner.get("pageIndex") == page_no - 1:
                filtered.append(a)
        all_annotations = filtered

    return all_annotations



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



def _job_summary(job: Job) -> dict:
    return {
        "job_id": job.id,
        "status": job.status,
        "pipeline": job.pipeline,
        "file_type": job.file_type,
        "filename": _normalize_display_name(job.original_filename),
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
        "annotated_pdf": bool(job.annotated_pdf_files or job.annotate_status),
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
        "ediscovery_context": job.ediscovery_context,
        "ediscovery_refundable": job.ediscovery_refundable,
    }



RETENTION_DAYS = 30


# clean PDF 판정 캐시 TTL. preview 캐시(300초)보다 길어야 의미가 있다 — 판정은
# 원본이 바뀌지 않는 한 불변이고, 원본이 바뀌는 지점은 모두 preview 캐시를 무효화한다.
_CLEAN_PDF_VERDICT_TTL = 3600


_PREVIEW_DOCUMENT_TYPES = ("pdf", "docx", "hwp", "pptx")


MEDIA_EXTENSIONS = {
    ".pdf", ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif",
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma",
    ".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm", ".m4v",
    ".docx", ".doc", ".dotx", ".docm",
    ".pptx", ".ppt", ".potx", ".ppsx", ".pptm", ".potm", ".ppsm",
    ".xlsx", ".xls", ".xlsm",
    ".hwp", ".hwpx",
    ".md",
}


_FILE_MARKER_RE = _re.compile(r"<!--\s*파일\s+(\d+)\s*-->\s*\n*", _re.IGNORECASE)


_PAGE_MARKER_RE = _re.compile(r"<!--\s*(?:페이지|page)\s*(\d+)\s*-->", _re.IGNORECASE)


_HR_SPLIT_RE = _re.compile(r"\n(?:\s*[-_*]\s*[-_*]\s*[-_*][-\s*_]*\s*)\n")


