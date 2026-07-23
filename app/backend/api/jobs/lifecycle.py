from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...auth.api_key_auth import require_api_key_or_session
from ...auth.supabase_auth import CurrentUser, get_current_admin
from ...core import media_loader, points_service, subscription_service, supabase_client
from ...core.job_helpers import parse_columns
from ...db.models import Job, User
from ...db.session import get_db
from ...workers.tasks import run_job, run_job_added_files
from ._shared import (
    _calculate_media_info,
    _delete_annotation_file,
    _delete_original_file,
    _is_job_expired,
    _job_expires_at,
    _job_summary,
    _require_job_access,
    _require_job_not_expired,
    _source_expires_at,
    _subscription_units_from_job,
    _subscription_would_exceed_for_model,
    get_current_user_or_api_key,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api', tags=['jobs'])

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

    # 크레딧 시스템: 사용량을 포인트로 환산해 차감 (멱등성 위해 Job에 예약 기록 저장)
    units = _subscription_units_from_job(job)
    try:
        result = subscription_service.reserve_usage(
            db,
            db_user,
            basic_pages=units["basic_pages"],
            premium_pages=units["premium_pages"],
            audio_seconds=units["audio_seconds"],
            video_seconds=units["video_seconds"],
            docling_refinement_pages=units["docling_refinement_pages"],
        )
    except ValueError as e:
        raise HTTPException(status_code=402, detail=str(e))

    job.reserved_basic_pages = units["basic_pages"]
    job.reserved_premium_pages = units["premium_pages"]
    job.reserved_media_seconds = units["audio_seconds"] + units["video_seconds"]
    job.reserved_period_start = datetime.fromisoformat(result["period_start"])
    job.cost_points = result["cost_points"]
    job.status = "queued"
    db.commit()

    run_job.delay(job.id)
    return {"job_id": job.id, "status": job.status, "cost_points": result["cost_points"], "subscription": result}



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
        summary["cost_basic"] = points_service.calculate_cost(
            db, pages=pages, image_count=image_count, audio_seconds=audio_seconds, video_seconds=video_seconds, ocr_model="basic"
        )
        summary["cost_premium"] = points_service.calculate_cost(
            db, pages=pages, image_count=image_count, audio_seconds=audio_seconds, video_seconds=video_seconds, docling_refinement_pages=docling_refinement_pages, ocr_model="premium"
        )
        summary["cost"] = summary["cost_premium"] if (job.ocr_model or "premium") != "basic" else summary["cost_basic"]

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
            "points_balance": status["points_balance"],
            "monthly_credits": status["monthly_credits"],
            "remaining": status["remaining"],
            "would_exceed": not check_current["ok"],
            "would_exceed_basic": not check_basic["ok"],
            "would_exceed_premium": not check_premium["ok"],
            "reason": check_current["reason"],
            "reason_basic": check_basic["reason"],
            "reason_premium": check_premium["reason"],
        }
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



