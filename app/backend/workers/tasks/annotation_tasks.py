"""workers/tasks/annotation_tasks.py — 주석 관련 Celery 태스크."""
from __future__ import annotations

import logging

from ...celery_app import celery
from ...core import pdf_annotate_converter, supabase_client
from ...db.models import Job
from ...db.session import SessionLocal

logger = logging.getLogger(__name__)


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



