"""workers/tasks/conversion.py — XLSX Advanced 변환 Celery 태스크."""
from __future__ import annotations

import logging

from ...celery_app import celery
from ...core import supabase_client, xlsx_advanced_converter
from ...db.models import Job
from ...db.session import SessionLocal

logger = logging.getLogger(__name__)


@celery.task(name="backend.workers.tasks.convert_xlsx_advanced")
def convert_xlsx_advanced(parent_job_id: str) -> dict:
    """마크다운 결과를 LLM 기반 고급 변환으로 xlsx로 변환한다."""
    return xlsx_advanced_converter.run(parent_job_id)



