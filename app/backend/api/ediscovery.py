#!/usr/bin/env python3
# [Flow: Step 1 (인증 + Job 접근 권한 확인) -> Step 2 (e-Discovery GraphRAG 상태 조회/추출/임계값 재조정)
#       -> Step 3 (pipeline_ediscovery.run 결과를 데이터 계약 형식으로 반환)]
# e-Discovery GraphRAG 파이프라인을 제어하는 REST API.
# 수천 장 법률 문서에서 쟁점/원고/피고/증거 노드와 관계를 추출해 React Flow 시각화용 그래프 JSON으로 반환.
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.api_key_auth import require_api_key_or_session
from ..auth.supabase_auth import CurrentUser
from .. import settings_store
from ..config import settings
from ..core import legal_elements, pipeline_ediscovery
from ..db.models import Job
from ..db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["jobs"])


def _get_current_user(
    auth: tuple[CurrentUser, Any] = Depends(require_api_key_or_session),
) -> CurrentUser:
    """[Flow: Step 1 (API key 또는 세션 인증) -> Step 2 (CurrentUser만 반환)]"""
    return auth[0]


def _require_job_access(job: Job | None, user: CurrentUser) -> None:
    """[Flow: Step 1 (job 존재 여부 확인) -> Step 2 (개발 bypass 사용자면 통과) -> Step 3 (소유자 불일치 시 404)]"""
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if user.is_dev_bypass:
        return
    if str(job.user_id) != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")


def _require_job_not_expired(job: Job) -> None:
    """[Flow: Step 1 (만료 시각 확인) -> Step 2 (timezone-naive 처리) -> Step 3 (만료되었으면 404)]"""
    if job.expires_at:
        expires = job.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            raise HTTPException(status_code=404, detail="Job expired")


def _require_job_done(job: Job) -> None:
    """[Flow: Step 1 (job.status 확인) -> Step 2 (done이 아니면 400)]"""
    if job.status != "done":
        raise HTTPException(status_code=400, detail="Only completed jobs can use e-Discovery")


def _build_response(job: Job) -> dict:
    """[Flow: Step 1 (Job의 e-Discovery 필드 수집) -> Step 2 (데이터 계약 형식으로 반환)]"""
    return {
        "job_id": job.id,
        "ediscovery_status": job.ediscovery_status or "",
        "ediscovery_metrics": job.ediscovery_metrics or {
            "total_docs": 0,
            "processed_chunks": 0,
            "threshold": 0.0,
        },
        "graph_data": job.ediscovery_graphs or {"nodes": [], "edges": []},
        "ediscovery_error": (job.ediscovery_metrics or {}).get("error", ""),
    }


@router.get("/jobs/{job_id}/ediscovery")
def get_ediscovery(
    job_id: str,
    user: CurrentUser = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (Job 조회) -> Step 2 (권한/만료/완료 상태 검증) -> Step 3 (e-Discovery 상태/그래프 반환)]"""
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    _require_job_done(job)
    return _build_response(job)


def _parse_page_range(raw: str | list | int | None, total_pages: int) -> list[int] | None:
    """[Flow: Step 1 (빈 입력 → None) -> Step 2 (문자열/리스트/숫자 정규화) -> Step 3 (범위 파싱) -> Step 4 (1-based 페이지 리스트 반환)]"""
    if raw is None:
        return None
    if isinstance(raw, int):
        pages = [raw]
    elif isinstance(raw, list):
        pages = []
        for item in raw:
            try:
                pages.append(int(item))
            except (TypeError, ValueError):
                continue
    else:
        text = str(raw).strip()
        if not text:
            return None
        pages = []
        for token in text.split(","):
            token = token.strip()
            if "-" in token:
                try:
                    start, end = token.split("-", 1)
                    start = int(start.strip())
                    end = int(end.strip())
                    pages.extend(range(start, end + 1))
                except (ValueError, TypeError):
                    continue
            else:
                try:
                    pages.append(int(token))
                except (ValueError, TypeError):
                    continue
    valid = sorted({p for p in pages if 1 <= p <= total_pages})
    return valid if valid else None


@router.post("/jobs/{job_id}/ediscovery/extract")
def extract_ediscovery_graph(
    job_id: str,
    payload: dict = Body(...),
    wait: bool = True,
    user: CurrentUser = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (Job 조회 + 파라미터 파싱) -> Step 2 (wait=true면 pipeline_ediscovery.run 동기 실행)
          -> Step 3 (wait=false면 Celery task 큐잉 후 processing 반환) -> Step 4 (결과를 데이터 계약 형식으로 반환)]

    e-Discovery GraphRAG 추출을 실행한다. chunk_size, threshold, max_docs(또는 max_chunks), query, page_range를 조절할 수 있다.
    AI 백엔드 도구는 wait 기본값(true)로 즉시 결과를 받고, 프론트엔드는 wait=false로 비동기 폴링할 수 있다.
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    _require_job_done(job)

    chunk_size = int(payload.get("chunk_size", payload.get("chunkSize", pipeline_ediscovery.DEFAULT_CHUNK_SIZE)))
    threshold = float(payload.get("threshold", pipeline_ediscovery.DEFAULT_THRESHOLD))
    threshold = max(0.0, min(1.0, threshold))
    max_docs = payload.get("max_docs") or payload.get("max_chunks") or payload.get("maxDocs")
    if max_docs is not None:
        max_docs = int(max_docs)
    query = str(payload.get("query", "")).strip() or None

    total_pages = job.total_pages if job.total_pages else (job.total_files or 1)
    page_range = _parse_page_range(payload.get("page_range"), total_pages)

    # 요청 파라미터 저장
    job.ediscovery_params = {
        "chunk_size": chunk_size,
        "threshold": threshold,
        "max_docs": max_docs,
        "query": query,
        "page_range": page_range,
    }

    if job.ediscovery_status == "processing":
        return {
            "job_id": job.id,
            "status": "processing",
            "message": "e-Discovery extraction already in progress",
        }

    job.ediscovery_status = "processing"
    db.commit()

    logger.info(f"[ediscovery-api] extract job={job_id} chunk_size={chunk_size} threshold={threshold} max_docs={max_docs} query={query} page_range={page_range} wait={wait}")

    if not wait:
        from ..workers import tasks
        task = tasks.run_ediscovery.delay(
            job_id,
            chunk_size=chunk_size,
            threshold=threshold,
            page_range=page_range,
            max_docs=max_docs,
            query=query,
        )
        job.ediscovery_job_id = task.id
        db.commit()
        return {
            "job_id": job.id,
            "status": "processing",
            "task_id": task.id,
        }

    result = pipeline_ediscovery.run(
        job_id,
        chunk_size=chunk_size,
        threshold=threshold,
        max_docs=max_docs,
        query=query,
        page_range=page_range,
    )

    db.refresh(job)
    if result.get("status") != "done":
        detail = result.get("error", "e-Discovery extraction failed")
        logger.error(f"[ediscovery-api] extract failed job={job_id}: {detail}")
        raise HTTPException(status_code=502, detail=detail)

    return {
        "job_id": job.id,
        "ediscovery_metrics": job.ediscovery_metrics,
        "graph_data": job.ediscovery_graphs,
    }


@router.post("/jobs/{job_id}/ediscovery/threshold")
def adjust_graph_threshold(
    job_id: str,
    payload: dict = Body(...),
    user: CurrentUser = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (Job 조회 + threshold 파싱) -> Step 2 (저장된 그래프에서 confidence 기준 재필터링)
          -> Step 3 (필터링된 그래프를 데이터 계약 형식으로 반환)]

    e-Discovery 임계값을 변경해 이미 추출된 그래프를 재필터링한다.
    동일한 노드 집합에서 더 엄격하거나 느슨한 임계값을 적용할 때 사용하므로 LLM 재호출 없이 빠르게 동작.
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    _require_job_done(job)

    threshold = float(payload.get("threshold", pipeline_ediscovery.DEFAULT_THRESHOLD))
    threshold = max(0.0, min(1.0, threshold))

    if job.ediscovery_status == "processing":
        return {
            "job_id": job.id,
            "status": "processing",
            "message": "e-Discovery extraction already in progress",
        }

    if job.ediscovery_status != "done" or not job.ediscovery_graphs:
        raise HTTPException(
            status_code=400,
            detail="No e-Discovery graph available. Call /ediscovery/extract first.",
        )

    logger.info(f"[ediscovery-api] threshold job={job_id} threshold={threshold}")

    nodes = list(job.ediscovery_graphs.get("nodes", []))
    filtered_nodes = [
        n for n in nodes
        if float(n.get("data", {}).get("confidence", 1.0)) >= threshold
    ]
    node_ids = {n["id"] for n in filtered_nodes}
    filtered_edges = [
        e for e in job.ediscovery_graphs.get("edges", [])
        if e.get("source") in node_ids and e.get("target") in node_ids
    ]
    graph_data = {"nodes": filtered_nodes, "edges": filtered_edges}

    metrics = {
        "total_docs": job.ediscovery_metrics.get("total_docs", 0),
        "processed_chunks": job.ediscovery_metrics.get("processed_chunks", 0),
        "threshold": threshold,
        "graph_nodes": len(filtered_nodes),
        "graph_edges": len(filtered_edges),
    }

    return {
        "job_id": job.id,
        "ediscovery_metrics": metrics,
        "graph_data": graph_data,
    }


# ============================================================
# Evidence-to-Element Mapper — 요건사실 기반 증거 퍼즐 매퍼
# 청구 원인별 법적 요건사실 슬롯에 추출된 증거를 매핑하고 입증 달성도를 저장.
# ============================================================

def _resolve_llm_settings(job: Job, db: Session) -> tuple[str, str, str]:
    """[Flow: Step 1 (job.endpoint 우선) -> Step 2 (settings_store 폴백) -> Step 3 (settings 기본값) -> (endpoint, model, api_key) 반환)]

    요건사실 추출용 LLM 설정을 해석한다. pipeline_ediscovery.run 과 동일한 우선순위를 따른다.
    """
    endpoint = job.endpoint or settings_store.get_setting(db, "llm_endpoint") or settings.default_llm_endpoint
    model = job.model or settings_store.get_setting(db, "llm_model") or settings.default_llm_model
    api_key = settings_store.get_setting(db, "llm_api_key") or ""
    return endpoint, model, api_key


@router.get("/jobs/{job_id}/legal-elements")
def get_legal_elements(
    job_id: str,
    claim_type: str = "",
    user: CurrentUser = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (Job 조회 + 권한 검증) -> Step 2 (claim_type 파싱) -> Step 3 (캐시 확인: 같은 claim_type이면 저장된 element_mappings 반환)
          -> Step 4 (캐시 미스 시 vLLM으로 요건사실 추출) -> Step 5 (빈 슬롯 스키마 mapped_evidence:[] 포함 반환)]

    청구 원인(예: 사기죄)에 따른 법적 요건사실 3~5개를 도출한다.
    같은 claim_type으로 재요청 시 저장된 element_mappings를 캐시로 반환한다.
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    _require_job_done(job)

    claim_type = (claim_type or "").strip()
    if not claim_type:
        raise HTTPException(status_code=400, detail="claim_type query parameter is required")

    # 캐시 확인: 같은 claim_type의 저장된 매핑이 있으면 반환
    cached = job.element_mappings or {}
    if cached.get("claim_type") == claim_type and cached.get("elements"):
        return {"job_id": job.id, "element_mappings": cached}

    endpoint, model, api_key = _resolve_llm_settings(job, db)
    logger.info(f"[legal-elements-api] extract job={job_id} claim_type={claim_type}")

    mappings = legal_elements.extract_legal_elements(claim_type, endpoint, model, api_key)
    # 추출 결과를 저장 (빈 슬롯 상태로 영속화 — 이후 PUT /mappings로 갱신)
    job.element_mappings = mappings
    db.commit()

    return {"job_id": job.id, "element_mappings": mappings}


@router.put("/jobs/{job_id}/legal-elements/mappings")
def save_element_mappings(
    job_id: str,
    payload: dict = Body(...),
    user: CurrentUser = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (Job 조회 + 권한 검증) -> Step 2 (퍼즐 상태 payload 파싱) -> Step 3 (overall_progress_percent 서버 재계산)
          -> Step 4 (element_mappings JSONB에 영속화) -> Step 5 (저장된 상태 반환)]

    프론트엔드에서 완성된 퍼즐 상태(Data Contract)를 Supabase jobs 테이블의 element_mappings JSONB에 저장한다.
    overall_progress_percent는 서버에서 재계산하여 신뢰성을 보장한다.
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    _require_job_done(job)

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload: expected JSON object")

    mappings = {
        "claim_type": str(payload.get("claim_type", "")).strip(),
        "overall_progress_percent": 0,
        "elements": payload.get("elements", []) if isinstance(payload.get("elements"), list) else [],
    }
    mappings["overall_progress_percent"] = legal_elements.compute_overall_progress(mappings)

    job.element_mappings = mappings
    db.commit()
    logger.info(f"[legal-elements-api] save job={job_id} progress={mappings['overall_progress_percent']}%")

    return {"job_id": job.id, "element_mappings": mappings}


@router.get("/jobs/{job_id}/legal-elements/mappings")
def get_element_mappings(
    job_id: str,
    user: CurrentUser = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (Job 조회 + 권한 검증) -> Step 2 (저장된 element_mappings 반환)]

    저장된 요건사실 퍼즐 매핑 상태를 조회한다 (페이지 새로고침 후 복원용).
    저장된 상태가 없으면 빈 스키마를 반환한다.
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    _require_job_done(job)

    mappings = job.element_mappings or {}
    return {"job_id": job.id, "element_mappings": mappings}

