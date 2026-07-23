from __future__ import annotations

import json
import logging
import math
import re as _re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ...auth.api_key_auth import require_api_key_or_session
from ...auth.supabase_auth import CurrentUser
from ...celery_app import celery as celery_app
from ...core import cache, pdf_user_annotator, points_service, subscription_service, supabase_client
from ...core.job_helpers import upload_ocr_layout
from ...db.models import Job, User
from ...db.session import get_db
from ...workers.tasks import annotate_edit_job, annotate_pdf_job
from ._shared import (
    _annotation_id,
    _annotation_inner,
    _compute_coordinate_validation,
    _cross_validate_matches_with_ocr_layout,
    _deduplicate_annotations,
    _expand_match_to_line,
    _ensure_clean_source_pdf,
    _initialize_user_annotations_json,
    _is_annotation_edited,
    _is_rect_plausible_for_page,
    _is_user_annotation,
    _job_summary,
    _load_all_annotations,
    _mark_user_edited,
    _merge_annotation_jsons,
    _normalize_annotation_json_to_list,
    _normalize_display_name,
    _overall_annotation_status,
    _parse_page_range,
    _require_job_access,
    _require_job_not_expired,
    _resolve_annotations_json_path,
    _source_files,
    get_current_user_or_api_key,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api', tags=['jobs'])

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
    mode = str(payload.get("mode", "both")).lower()
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
    if existing:
        try:
            shared_storage_path = job.searchable_pdf_storage_path or existing["storage_path"]
            url = supabase_client.get_signed_download_url(shared_storage_path, bucket="pdfs", expires_in=3600)
            return {"download_url": url, "status": "done", "storage_path": shared_storage_path, "filename": existing.get("filename")}
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
        job.annotate_cost_points = sub_result["cost_points"]

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

    shared_storage_path = job.searchable_pdf_storage_path or f"{job.id}/searchable.pdf"
    shared_annotations_json_path = f"{job.id}/annotated.annotations.json"

    # processing entry를 annotated_pdf_files에 추가한다.
    # storage_path는 searchable PDF 경로를 사용한다.
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
            existing_list = _normalize_annotation_json_to_list(existing)
            if existing_list:
                filtered = [
                    a for a in existing_list
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
            )
        except ValueError as e:
            raise HTTPException(status_code=402, detail=str(e))
        job.annotate_status = "processing"
        job.annotate_refundable = True
        job.annotate_reserved_pages = units
        job.annotate_reserved_period_start = datetime.fromisoformat(sub_result["period_start"])
        job.annotate_cost_points += sub_result["cost_points"]

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

    shared_storage_path = job.searchable_pdf_storage_path or f"{job.id}/searchable.pdf"
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



def save_user_annotations(
    job_id: str,
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (job 조회 및 권한 확인) -> Step 2 (주석 유효성 검사 및 removals 추출)
          -> Step 3 (source_index에 따른 JSON 경로 결정)
          -> Step 4 (input_space가 pdf_user이면 device-space로 변환)
          -> Step 5 (기존 주석 JSON 다운로드 및 ID 기반 누적 병합/삭제)
          -> Step 6 (JSON 오버레이 저장) -> Step 7 (preview 캐시 무효화 후 OK 반환)]

    사용자 및 AI 에이전트가 추가/편집/삭제한 주석을 JSON 오버레이로 누적 병합(Accumulate)하여 저장한다.
    기존 저장소의 주석을 ID 기준으로 보존하고, 신규 주석은 추가/업데이트하며, removals 목록에 지정된 주석만 삭제한다.
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)

    source_index = payload.get("source_index")
    annotations = payload.get("annotations")
    input_space = payload.get("input_space", "device")
    removals = payload.get("removals", [])
    if not isinstance(removals, list):
        removals = []
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
    logger.info(f"[save_user_annotations] {job_id} source_index={source_index} raw={len(annotations)} valid={valid_count} removals={len(removals)}")
    if valid_count == 0 and len(removals) == 0:
        return {"ok": True, "annotations_json_storage_path": None}

    # source_index >= 0: 파일별 사용자 주석 JSON(user_annotations_{source_index}.json)에 저장
    #                  AI 주석 entry가 있으면 병합 대상 경로로 함께 사용
    # source_index < 0: 하위 호환 — 공유 user_annotations.json에 저장
    entry = None
    if source_index >= 0:
        locked_job = db.execute(
            select(Job).where(Job.id == job_id).with_for_update()
        ).scalar_one()
        entries = list(locked_job.annotated_pdf_files or [])
        # AI annotate는 현재 단일 entry(index=1)를 사용한다.
        entry = next((e for e in entries if e.get("index") == 1), None)
        if entry is not None:
            annotations_json_storage_path = entry.get("annotations_json_storage_path") or f"{job_id}/annotated.annotations.json"
        else:
            annotations_json_storage_path = f"{job_id}/user_annotations_{source_index}.json"
    else:
        annotations_json_storage_path = f"{job_id}/user_annotations.json"

    try:
        client = supabase_client.get_service_client()

        # [Flow: AI 백엔드가 보내는 PDF user-space 좌표를 device-space로 변환]
        # 뷰어는 항상 device-space를 기대하므로, JSON 저장 전에 좌표계를 맞춘다.
        if input_space == "pdf_user" and valid_annotations:
            original_path = job.pdf_storage_path
            if original_path:
                try:
                    pdf_bytes = client.storage.from_("pdfs").download(original_path)
                    valid_annotations = pdf_user_annotator._convert_annotations_to_device_space(
                        valid_annotations, pdf_bytes
                    )
                except Exception as e:
                    logger.warning(f"[save_user_annotations] {job_id} PDF user-space 변환 실패: {e}")

        valid_annotations = _deduplicate_annotations(valid_annotations)

        # [Flow: 기존 주석 JSON 다운로드 및 ID 기반 병합]
        try:
            existing_bytes = client.storage.from_("results").download(annotations_json_storage_path)
            existing_list = json.loads(existing_bytes.decode("utf-8"))
            existing = _normalize_annotation_json_to_list(existing_list)
        except Exception:
            existing = []

        existing_by_id: dict[str, dict] = {}
        for a in existing:
            aid = _annotation_id(a)
            if aid:
                existing_by_id[aid] = a

        # removals 처리: 명시적으로 삭제 요청된 주석 제거
        for rid in removals:
            if isinstance(rid, str) and rid in existing_by_id:
                logger.info(f"[save_user_annotations] {job_id} 명시적 주석 삭제 처리: {rid}")
                del existing_by_id[rid]

        # valid_annotations 수신분 병합 (기존 ID가 있으면 편집 체크 후 업데이트, 없으면 추가)
        for a in valid_annotations:
            if not isinstance(a, dict):
                continue
            aid = _annotation_id(a)
            if not aid:
                continue
            orig = existing_by_id.get(aid)
            if orig is not None and _is_annotation_edited(a, orig):
                _mark_user_edited(a)
                logger.info(f"[save_user_annotations] {job_id} 주석 편집 감지: {aid}")
            existing_by_id[aid] = a

        merged = list(existing_by_id.values())
        merged = _deduplicate_annotations(merged)

        client.storage.from_("results").upload(
            annotations_json_storage_path,
            json.dumps(merged, ensure_ascii=False).encode("utf-8"),
            {"content-type": "application/json", "upsert": "true"},
        )
        if entry is not None and entry.get("annotations_json_storage_path") != annotations_json_storage_path:
            entry["annotations_json_storage_path"] = annotations_json_storage_path
            locked_job.annotated_pdf_files = entries
            flag_modified(locked_job, "annotated_pdf_files")
            db.commit()

        cache.invalidate_pattern(f"preview:{job_id}:*")
        return {
            "ok": True,
            "annotations_json_storage_path": annotations_json_storage_path,
        }
    except Exception as e:
        logger.exception(f"[save_user_annotations] {job_id} source_index={source_index} 실패: {e}")
        raise HTTPException(status_code=500, detail=f"주석 저장 실패: {e}")



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
                from ...core.pdf_annotate_converter import build_agent_elements_from_ocr_layout

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
                from ...core.pdf_annotate_converter import collect_elements_for_agent

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
                    upload_ocr_layout(db, job, layout_by_page)

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



def search_job_text(
    job_id: str,
    query: str = Query(..., description="검색어 또는 정규식"),
    page_no: int | None = None,
    mode: str = Query("text", description="text: 매치 단어만, line: 스캔 PDF 출신 시 해당 줄 전체로 확장"),
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
            # [TABLE_DEBUG] search_for 결과 좌표 로깅
            if rects:
                logger.info(
                    f"[TABLE_DEBUG] search_job_text: job={job_id} page={current_page_no} "
                    f"query='{query[:40]}' search_for 결과 {len(rects)}건, "
                    f"page.rect=({page.rect.x0:.1f}, {page.rect.y0:.1f}, {page.rect.x1:.1f}, {page.rect.y1:.1f})"
                )
                for ri, rect in enumerate(rects[:5]):
                    logger.info(
                        f"[TABLE_DEBUG]   search_for[{ri}]: "
                        f"rect=({rect.x0:.1f}, {rect.y0:.1f}, {rect.x1:.1f}, {rect.y1:.1f}), "
                        f"text='{page.get_textbox(rect).strip()[:40]}'"
                    )
            for rect in rects:
                if not _is_rect_plausible_for_page(rect, page.rect):
                    logger.warning(
                        f"[search_job_text] {job_id} page={current_page_no} 비정상 bbox 스킵: {rect}"
                    )
                    continue
                matches.append({
                    "page_no": current_page_no,
                    "bbox_pdf": [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)],
                    "text": page.get_textbox(rect).strip(),
                })
    finally:
        doc.close()

    # [Flow: search_for가 매치를 찾았더라도, 수정 전 코드로 생성된 searchable PDF의
    # 반전된 텍스트 레이어 때문에 y 좌표가 잘못될 수 있다.
    # 저장된 OCR layout이 있으면 search_for 결과와 교차 검증하여 y 좌표를 보정한다.]
    if matches and job.result_ocr_layout_storage_path:
        matches = _cross_validate_matches_with_ocr_layout(
            matches, job, client, pdf_bytes, query, page_no
        )

    # [Flow: 텍스트 레이어가 없는 스캔 PDF에서는 위 search_for가 항상 매치 0개를 반환한다.
    # 1) 저장된 OCR layout이 있으면 재사용하고, 2) 없으면 PaddleOCR 폴백으로
    # 요소 텍스트에 대해 대소문자 무관 정규식 매칭을 수행한다.]
    ocr_page_range = [page_no] if page_no is not None else None
    if not matches:
        logger.info(
            f"[TABLE_DEBUG] search_job_text: job={job_id} query='{query[:40]}' "
            f"search_for 매치 0건 → OCR 폴백 진입"
        )
        ocr_elements: list[dict] = []
        # 1) 저장된 OCR layout 재사용
        if job.result_ocr_layout_storage_path:
            try:
                from ...core.pdf_annotate_converter import build_agent_elements_from_ocr_layout

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
                from ...core.pdf_annotate_converter import collect_elements_for_agent

                ocr_elements, _ocr_pdf_bytes, layout_by_page = collect_elements_for_agent(job_id, page_range=ocr_page_range)
                used_ocr_fallback = True
            except Exception as e:
                logger.warning(f"[search_job_text] {job_id} OCR 폴백 실패: {e}")
                ocr_elements, layout_by_page = [], {}

            # 다음 호출을 위해 OCR layout 저장
            if layout_by_page:
                upload_ocr_layout(db, job, layout_by_page)

        try:
            pattern = _re.compile(query, _re.IGNORECASE)
        except _re.error:
            pattern = _re.compile(_re.escape(query), _re.IGNORECASE)

        # [Flow: OCR 폴백 요소의 bbox_pdf는 _normalize_bbox(y축 1차 반전) +
        #       _normalized_bbox_to_pdf_user(y축 2차 반전)를 거쳐 device-space와
        #       동일한 좌표계가 된다. 따라서 pdf_user_to_device(3차 반전)를
        #       추가로 적용하면 y가 반전되므로, 변환 없이 그대로 사용한다.
        #       search_for 경로도 device-space를 반환하므로 좌표계가 일치한다.]
        ocr_page_rect_map: dict[int, fitz.Rect] = {}
        try:
            _ocr_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            for _ocr_page in _ocr_doc:
                ocr_page_rect_map[_ocr_page.number + 1] = _ocr_page.rect
            _ocr_doc.close()
        except Exception as e:
            logger.warning(f"[search_job_text] {job_id} OCR 폴백 page rect 구축 실패: {e}")

        for el in ocr_elements:
            text = el.get("text") or ""
            if not pattern.search(text):
                continue
            el_page_no = el.get("page_no", 1)
            el_bbox = list(el["bbox_pdf"])
            # bbox_pdf는 _normalize_bbox + _normalized_bbox_to_pdf_user의
            # 이중 y반전을 거쳐 device-space와 동일하므로 추가 변환 없이 그대로 사용한다.
            # [TABLE_DEBUG] OCR 폴백 경로에서 표 행 좌표 로깅
            if el.get("kind") == "table_row" or "|" in text:
                logger.info(
                    f"[TABLE_DEBUG] search_job_text OCR 폴백 매치: "
                    f"kind={el.get('kind')} text='{text[:40]}' "
                    f"bbox_pdf(device-space)={[round(v, 1) for v in el_bbox]}"
                )
            matches.append({
                "page_no": el_page_no,
                "bbox_pdf": el_bbox,
                "text": text.strip(),
            })

    # [TABLE_DEBUG] 최종 결과 요약
    table_matches = [m for m in matches if "|" in m.get("text", "")]
    if table_matches:
        logger.info(
            f"[TABLE_DEBUG] search_job_text 최종: job={job_id} query='{query[:40]}' "
            f"total={len(matches)}건 (표 행 {len(table_matches)}건), "
            f"경로={'search_for' if not used_ocr_layout and not used_ocr_fallback else 'OCR 폴백'}"
        )

    # [Flow: mode=line이고 스캔 PDF 출신(OCR layout 있음)인 경우,
    #       각 match의 bbox를 해당 줄 전체로 확장하여 하이라이트/주석이 줄 전체에 표시되도록 한다.
    #       스캔 PDF의 텍스트 레이어는 OCR 기반이므로 단어 단위 위치가 부정확할 수 있어,
    #       줄 전체 확장이 시각적으로 더 안정적이다.]
    if mode == "line" and matches and job.result_ocr_layout_storage_path:
        try:
            _line_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            try:
                page_rect_map: dict[int, Any] = {}
                for _p in _line_doc:
                    page_rect_map[_p.number + 1] = _p.rect
            finally:
                _line_doc.close()
            matches = [
                _expand_match_to_line(m, page_rect_map.get(m["page_no"], page_rect_map.get(1)))
                if page_rect_map else m
                for m in matches
            ]
            logger.info(
                f"[search_job_text] {job_id} mode=line: {len(matches)}개 매치 bbox를 줄 전체로 확장"
            )
        except Exception as e:
            logger.warning(f"[search_job_text] {job_id} mode=line 확장 실패: {e}")

    import time as _time
    total_elapsed = _time.monotonic() - start_time
    # [Flow: 모든 matches의 bbox_pdf는 device-space(y=0 상단)로 통일되어 있다.
    #       search_for 경로와 OCR 폴백 경로 모두 device-space를 반환하므로,
    #       에이전트는 input_space='device'로 저장하면 된다.]
    return Response(
        json.dumps(
            {"matches": matches, "total": len(matches), "coordinate_space": "device"},
            ensure_ascii=False,
            default=str,
        ),
        media_type="application/json",
        headers={
            "X-Total-Elapsed": str(round(total_elapsed * 1000)),
            "X-Used-OCR-Layout": str(used_ocr_layout).lower(),
            "X-Used-OCR-Fallback": str(used_ocr_fallback).lower(),
            "X-OCR-Layout-Path": str(job.result_ocr_layout_storage_path or ""),
        },
    )



def debug_highlight_coords(
    job_id: str,
    query: str = Query(..., description="검색어"),
    page_no: int = Query(1, ge=1, description="페이지 번호 (1-based)"),
    dpi: int = Query(150, ge=72, le=300, description="렌더링 DPI"),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """[Flow: searchable PDF의 텍스트 레이어 좌표와 렌더링된 이미지 픽셀 좌표를 비교한다.

    반환:
      - page_rect: device-space 페이지 크기 (PDF user-space와 동일한 스케일, 원점 좌상단)
      - scale: device → pixel 변환 비율 (dpi / 72)
      - image_base64: 렌더링된 페이지 PNG
      - search_for_rects: PyMuPDF search_for 결과 (device + pixel)
      - text_blocks: get_text("blocks") 결과 (PDF 텍스트 레이어 실제 위치)
      - ocr_elements: 저장된 OCR layout bbox (있을 때)
      - is_likely_scan: 텍스트 레이어가 거의 없으면 true (스캔 PDF 추정)
    """
    import base64 as _b64

    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)

    # searchable PDF 경로 해석 (search_job_text와 동일 로직)
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

    if not storage_path:
        raise HTTPException(status_code=404, detail="No PDF available for this job")

    try:
        client = supabase_client.get_service_client()
        pdf_bytes = client.storage.from_(bucket).download(storage_path)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to download PDF: {e}")

    scale = dpi / 72.0
    matrix = fitz.Matrix(scale, scale)

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if page_no > doc.page_count:
            raise HTTPException(status_code=400, detail=f"page_no {page_no} > page_count {doc.page_count}")
        page = doc[page_no - 1]
        page_rect = page.rect

        # 1) 페이지를 PNG로 렌더링 (device-space 좌표계 기준)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        image_bytes = pix.tobytes("png")
        image_b64 = _b64.b64encode(image_bytes).decode("ascii")
        image_w, image_h = pix.width, pix.height

        # 2) search_for로 query 검색 (device-space rect)
        try:
            rects = page.search_for(query)
        except Exception:
            rects = page.search_for(query.replace("\\", ""))
        search_for_rects = []
        for rect in rects:
            text = page.get_textbox(rect).strip()
            search_for_rects.append({
                "device": [round(rect.x0, 2), round(rect.y0, 2), round(rect.x1, 2), round(rect.y1, 2)],
                "pixel": [round(rect.x0 * scale, 1), round(rect.y0 * scale, 1),
                          round(rect.x1 * scale, 1), round(rect.y1 * scale, 1)],
                "text": text,
            })

        # 3) 텍스트 레이어의 실제 블록 위치 (get_text("blocks"))
        #    스캔 PDF searchable 텍스트 레이어가 어디에 배치되어 있는지 확인
        blocks = page.get_text("blocks")
        text_blocks = []
        for b in blocks:
            # b = (x0, y0, x1, y1, text, block_no, block_type)
            bx0, by0, bx1, by1, btext = b[0], b[1], b[2], b[3], b[4]
            text_blocks.append({
                "device": [round(bx0, 2), round(by0, 2), round(bx1, 2), round(by1, 2)],
                "pixel": [round(bx0 * scale, 1), round(by0 * scale, 1),
                          round(bx1 * scale, 1), round(by1 * scale, 1)],
                "text": btext.strip()[:120],
                "type": b[6],
            })

        # 4) get_text("dict") 의 line/span 정밀 위치도 일부 수집 (첫 30개)
        detailed_spans = []
        try:
            td = page.get_text("dict")
            for block in td.get("blocks", []):
                if block.get("type") != 0:  # 0 = text
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        sbbox = span["bbox"]
                        detailed_spans.append({
                            "device": [round(sbbox[0], 2), round(sbbox[1], 2),
                                       round(sbbox[2], 2), round(sbbox[3], 2)],
                            "pixel": [round(sbbox[0] * scale, 1), round(sbbox[1] * scale, 1),
                                      round(sbbox[2] * scale, 1), round(sbbox[3] * scale, 1)],
                            "text": span.get("text", "").strip()[:80],
                            "font": span.get("font", ""),
                            "size": round(span.get("size", 0), 2),
                        })
                        if len(detailed_spans) >= 60:
                            break
                    if len(detailed_spans) >= 60:
                        break
                if len(detailed_spans) >= 60:
                    break
        except Exception as e:
            logger.warning(f"[debug_highlight_coords] dict 추출 실패: {e}")

        # 5) OCR layout bbox (있으면)
        # [주의] build_agent_elements_from_ocr_layout의 bbox_pdf는
        # _normalize_bbox(1차 y반전) + _normalized_bbox_to_pdf_user(2차 y반전)를
        # 거쳐 device-space와 동일한 좌표계가 된다. 추가 pdf_user_to_device(3차 y반전)를
        # 적용하면 y가 반전되므로 변환 없이 그대로 사용한다.
        ocr_elements = []
        if job.result_ocr_layout_storage_path:
            try:
                from ...core.pdf_annotate_converter import build_agent_elements_from_ocr_layout

                layout_raw = client.storage.from_("results").download(job.result_ocr_layout_storage_path)
                layout_by_page = {int(k): v for k, v in json.loads(layout_raw.decode("utf-8")).items()}
                elements = build_agent_elements_from_ocr_layout(layout_by_page, pdf_bytes, page_range=[page_no])
                for el in elements:
                    dev = list(el["bbox_pdf"])  # 이미 device-space
                    ocr_elements.append({
                        "device": [round(v, 2) for v in dev],
                        "pixel": [round(dev[0] * scale, 1), round(dev[1] * scale, 1),
                                  round(dev[2] * scale, 1), round(dev[3] * scale, 1)],
                        "text": (el.get("text") or "").strip()[:80],
                        "kind": el.get("kind", ""),
                    })
            except Exception as e:
                logger.warning(f"[debug_highlight_coords] OCR layout 추출 실패: {e}")

        # 6) 스캔 PDF 추정: 텍스트 레이어 블록이 1~2개이고 대부분 빈 텍스트면 스캔
        non_empty_blocks = [b for b in text_blocks if b["text"]]
        is_likely_scan = len(non_empty_blocks) <= 2 and len(text_blocks) <= 5

        # 7) 페이지 텍스트 전체 (디버그용)
        full_text = page.get_text().strip()

        # 8) 자동 검증: search_for ↔ text_blocks ↔ ocr_elements 좌표 일치도 평가
        # [Flow: Step 1 (search_for ↔ text_blocks y 차이 계산)
        #       -> Step 2 (search_for ↔ ocr_elements y 차이 계산)
        #       -> Step 3 (표 행 순서 단조성 검사 — ocr_elements table_row의 y가 HTML 순서대로 증가?)
        #       -> Step 4 (PASS/FAIL 판정 + 상세 메시지)]
        validation = _compute_coordinate_validation(
            search_for_rects, text_blocks, ocr_elements, page_rect, query
        )

        result = {
            "job_id": job_id,
            "page_no": page_no,
            "dpi": dpi,
            "scale": round(scale, 4),
            "page_rect": {
                "device": [round(page_rect.x0, 2), round(page_rect.y0, 2),
                           round(page_rect.x1, 2), round(page_rect.y1, 2)],
                "pixel": [round(page_rect.x0 * scale, 1), round(page_rect.y0 * scale, 1),
                          round(page_rect.x1 * scale, 1), round(page_rect.y1 * scale, 1)],
            },
            "image_base64": image_b64,
            "image_width": image_w,
            "image_height": image_h,
            "search_for_rects": search_for_rects,
            "text_blocks": text_blocks,
            "detailed_spans": detailed_spans,
            "ocr_elements": ocr_elements,
            "is_likely_scan": is_likely_scan,
            "validation": validation,
            "searchable_pdf_storage_path": storage_path,
            "result_ocr_layout_storage_path": job.result_ocr_layout_storage_path,
            "full_text_preview": full_text[:500],
            "full_text_length": len(full_text),
        }
        logger.info(
            f"[debug_highlight_coords] job={job_id} page={page_no} query='{query[:40]}' "
            f"search_for={len(search_for_rects)}건 blocks={len(text_blocks)} "
            f"spans={len(detailed_spans)} ocr={len(ocr_elements)} is_scan={is_likely_scan}"
        )
        return Response(
            json.dumps(result, ensure_ascii=False, default=str),
            media_type="application/json",
        )
    finally:
        doc.close()



def get_job_annotations(
    job_id: str,
    source_index: int = Query(0, description="주석 파일 인덱스"),
    page_no: int | None = Query(None, description="1-based 페이지 번호. 생략 시 모든 페이지"),
    space: str = Query("device", description="좌표계 (device | pdf_user)"),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (job 조회) -> Step 2 (_load_all_annotations로 AI+사용자 주석 병합 로드)
          -> Step 3 (space="pdf_user" 요청 시에만 PDF user-space 변환 수행 후 반환)]

    AI 에이전트 또는 프론트엔드 뷰어가 기존 주석 목록을 확인할 때 사용한다.
    뷰어는 device-space(원점 좌상단)를 기대하며, space="pdf_user" 요청 시에만 PDF user-space로 역변환한다.
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)

    all_annotations = _load_all_annotations(job, source_index, page_no)
    if space == "pdf_user" and all_annotations and job.pdf_storage_path:
        try:
            client = supabase_client.get_service_client()
            pdf_bytes = client.storage.from_("pdfs").download(job.pdf_storage_path)
            all_annotations = pdf_user_annotator._convert_annotations_to_pdf_user(
                all_annotations, pdf_bytes
            )
        except Exception as e:
            logger.warning(f"[get_job_annotations] {job_id} device→pdf_user 변환 실패: {e}")
    return {"annotations": all_annotations, "total": len(all_annotations)}



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
            all_annotations = _normalize_annotation_json_to_list(existing)
        except Exception:
            pass

    # [Flow: 파일별 주석 분리 — source_index별로 분리된 user_annotations_{source_index}.json을 먼저 확인]
    user_annotations_json_path = f"{job.id}/user_annotations_{source_index}.json"
    user_annotations: list[dict] = []
    try:
        user_bytes = client.storage.from_("results").download(user_annotations_json_path)
        user_raw = json.loads(user_bytes.decode("utf-8"))
        user_annotations = _normalize_annotation_json_to_list(user_raw)
    except Exception:
        # 파일별 주석 JSON이 없으면 공유 user_annotations.json으로 폴백 (하위 호환)
        user_annotations_json_path = f"{job.id}/user_annotations.json"
        try:
            user_bytes = client.storage.from_("results").download(user_annotations_json_path)
            user_raw = json.loads(user_bytes.decode("utf-8"))
            user_annotations = _normalize_annotation_json_to_list(user_raw)
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
                "original_filename": _normalize_display_name(job.original_filename),
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



