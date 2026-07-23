from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth.supabase_auth import CurrentUser, get_current_admin
from ...db.models import Job
from ...db.session import get_db
from ._shared import _is_job_expired, _job_summary, _source_expires_at

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api', tags=['jobs'])

@router.get("/admin/jobs")
def admin_list_jobs(
    admin: CurrentUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
    limit: int = 100,
):
    rows = db.execute(select(Job).order_by(Job.created_at.desc()).limit(limit)).scalars().all()
    return [_job_summary(j) for j in rows]



