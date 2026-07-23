from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from ...auth.api_key_auth import require_api_key_or_session
from ...auth.supabase_auth import CurrentUser
from ...core import cache, converter, subscription_service, supabase_client
from ...db.models import Job
from ...db.session import get_db
from ...workers.tasks import run_job
from ._shared import (
    _calculate_media_info,
    _FILE_MARKER_RE,
    _get_markdown_content,
    _job_summary,
    _PAGE_MARKER_RE,
    _require_job_access,
    _require_job_not_expired,
    _split_markdown_by_files,
    _split_markdown_by_pages,
    get_current_user_or_api_key,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api', tags=['jobs'])

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
                info["result_markdown"] = rewrite_inline_images_to_storage(str(file_markdowns[idx]), job_id)
        job.extracted_files = files
        markdown = converter.build_combined_file_markdowns(
            [info.get("result_markdown", "") for info in files]
        )
    else:
        markdown = rewrite_inline_images_to_storage(str(payload.get("markdown", "")), job_id)

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

    # [Flow: 파일 마커 기준으로 분할 -> page_num은 파일 번호로 해석 -> 해당 파일 내용만 갱신]
    files = _split_markdown_by_files(markdown)
    if not files:
        raise HTTPException(status_code=400, detail="No files found")
    target_idx = next((idx for idx, (num, _) in enumerate(files) if num == page_num), None)
    if target_idx is None:
        raise HTTPException(status_code=404, detail="File not found")

    # [Flow: 편집기에서 저장된 `<!-- Page N -->` 파일 마커 제거 -> base64 이미지 외부화 -> 파일 구분자로 재조합]
    cleaned_content = _PAGE_MARKER_RE.sub("", new_content).strip()
    cleaned_content = _FILE_MARKER_RE.sub("", cleaned_content).strip()
    cleaned_content = rewrite_inline_images_to_storage(cleaned_content, job_id)
    files[target_idx] = (page_num, cleaned_content)
    updated = "\n\n---\n\n".join([f"<!-- 파일 {num} -->\n\n{content}" for num, content in files])

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
        # 크레딧 환불: 예약 시 기록한 단위를 기반으로 media/Docling 세부값을 재계산
        refunded_basic = job.reserved_basic_pages
        refunded_premium = job.reserved_premium_pages
        media_info = _calculate_media_info(job)
        subscription_service.release_usage(
            db,
            db_user,
            basic_pages=refunded_basic,
            premium_pages=refunded_premium,
            audio_seconds=media_info["audio_seconds"],
            video_seconds=media_info["video_seconds"],
            docling_refinement_pages=media_info["docling_refinement_pages"],
            period_start=job.reserved_period_start,
        )
        refunded_points = job.cost_points
        job.reserved_basic_pages = 0
        job.reserved_premium_pages = 0
        job.reserved_media_seconds = 0
        job.reserved_period_start = None
        job.cost_points = 0
        job.refundable = False
        db.commit()
        return {"refunded": True, "basic_pages": refunded_basic, "premium_pages": refunded_premium, "refunded_points": refunded_points}

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



