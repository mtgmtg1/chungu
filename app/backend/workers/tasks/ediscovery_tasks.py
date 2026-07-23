"""workers/tasks/ediscovery_tasks.py — eDiscovery Celery 태스크."""
from __future__ import annotations

import logging

from ...celery_app import celery
from ...core import pipeline_ediscovery, supabase_client
from ...db.models import Job
from ...db.session import SessionLocal

logger = logging.getLogger(__name__)


@celery.task(name="backend.workers.tasks.run_ediscovery")
def run_ediscovery(
    job_id: str,
    chunk_size: int | None = None,
    threshold: float | None = None,
    page_range: list[int] | None = None,
    max_chunks: int | None = None,
    max_docs: int | None = None,
    query: str | None = None,
    context: str | None = None,
) -> dict:
    """[Flow: Step 1 (pipeline_ediscovery.run 호출) -> Step 2 (결과 반환)]

    수천 장 법률 문서에서 쟁점/증거 노드를 추출해 그래프 JSON으로 저장한다.
    chunk_size/threshold/max_chunks/max_docs가 None이면 LLM이 문서 샘플을 보고 자동 추천한다.
    page_range는 처리할 1-based 페이지 번호 리스트. None이면 전체 페이지를 처리한다.
    query는 자연어 쿼리로, 지정 시 관련 청크만 처리 대상으로 한다.
    max_docs는 api/ediscovery.py extract 엔드포인트와의 호환성을 위한 max_chunks 별칭이다.
    context는 사용자가 입력한 프로젝트 주요/중요 사항으로, LLM 프롬프트에 포함된다.
    """
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        user_id = str(job.user_id) if job else None
        return pipeline_ediscovery.run(
            job_id,
            chunk_size=chunk_size,
            threshold=threshold,
            page_range=page_range,
            max_chunks=max_chunks,
            max_docs=max_docs,
            query=query,
            context=context,
            user_id=user_id,
        )
    finally:
        db.close()



