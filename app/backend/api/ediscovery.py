#!/usr/bin/env python3
# [Flow: Step 1 (인증 + Job 접근 권한 확인) -> Step 2 (e-Discovery GraphRAG 상태 조회/추출/임계값 재조정)
#       -> Step 3 (pipeline_ediscovery.run 결과를 데이터 계약 형식으로 반환)]
# e-Discovery GraphRAG 파이프라인을 제어하는 REST API.
# 수천 장 법률 문서에서 쟁점/원고/피고/증거 노드와 관계를 추출해 React Flow 시각화용 그래프 JSON으로 반환.
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.api_key_auth import require_api_key_or_session
from ..auth.supabase_auth import CurrentUser
from .. import settings_store
from ..config import settings
from ..core import legal_case_profile, legal_elements, legal_issue_tree, pipeline_ediscovery
from ..db.models import Job, User
from ..db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["jobs"])

# stale "processing" 상태 판정 기준 — 이 시간(초) 이상 processing 상태가 지속되면 stale로 간주
EDISCOVERY_STALE_TIMEOUT_SECONDS = 3600  # 1시간


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


def _is_ediscovery_stale(job: Job, db: Session) -> bool:
    """[Flow: Step 1 (ediscovery_status != processing이면 False) -> Step 2 (ediscovery_job_id 비어있으면 stale)
          -> Step 3 (Celery AsyncResult 상태 확인: FAILURE/REVOKED/SUCCESS면 stale)
          -> Step 4 (ediscovery_params.started_at 기준 타임아웃 초과 시 stale)
          -> Step 5 (결과 백엔드 조회 불가 시 안전하게 stale로 간주)]

    "processing" 상태가 잠긴(deadlock) job을 감지한다.
    Celery 태스크가 크래시/재시작으로 소실되었거나, 타임아웃을 초과했으면 True를 반환한다.
    호출측에서 True 반환 시 ediscovery_status를 리셋하고 재추출을 허용한다.

    매개변수:
        job: Job 모델 인스턴스
        db: SQLAlchemy 세션 (상태 리셋 시 commit용)
    반환값:
        True면 stale (재추출 허용), False면 정상 processing (재추출 거부)
    """
    if job.ediscovery_status != "processing":
        return False

    # Step 2: Celery 태스크 ID가 없으면 추적 불가 → stale
    task_id = (job.ediscovery_job_id or "").strip()
    if not task_id:
        logger.warning(f"[ediscovery-api] stale job={job.id} — processing 상태지만 ediscovery_job_id가 비어 있음")
        return True

    # Step 3: Celery 결과 백엔드에서 태스크 상태 확인
    try:
        from ..celery_app import celery
        result = celery.AsyncResult(task_id)
        state = result.state
        # PENDING/STARTED/RETRY는 실행 중 → stale 아님
        # SUCCESS/FAILURE/REVOKED는 종료 → stale (status가 done/error로 갱신되지 않았으므로)
        if state in ("SUCCESS", "FAILURE", "REVOKED"):
            logger.warning(f"[ediscovery-api] stale job={job.id} — Celery 태스크 {task_id} 상태={state}")
            return True
    except Exception as e:  # noqa: BLE001
        # 결과 백엔드 조회 불가 → 안전하게 stale로 간주 (재추출 허용)
        logger.warning(f"[ediscovery-api] stale job={job.id} — Celery 결과 조회 실패: {e}")
        return True

    # Step 4: 타임아웃 기반 stale 판정 — started_at 기준 EDISCOVERY_STALE_TIMEOUT_SECONDS 초과 시 stale
    params = job.ediscovery_params or {}
    started_at_str = params.get("started_at")
    if started_at_str:
        try:
            started_at = datetime.fromisoformat(started_at_str)
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
            if elapsed > EDISCOVERY_STALE_TIMEOUT_SECONDS:
                logger.warning(
                    f"[ediscovery-api] stale job={job.id} — processing {elapsed:.0f}초 경과 "
                    f"(한도 {EDISCOVERY_STALE_TIMEOUT_SECONDS}초)"
                )
                return True
        except (ValueError, TypeError):
            pass  # started_at 파싱 실패 시 타임아웃 판정 스킵

    return False


def _reset_stale_processing(job: Job, db: Session) -> None:
    """[Flow: Step 1 (ediscovery_status를 빈값으로 리셋) -> Step 2 (ediscovery_job_id 제거) -> Step 3 (commit)]

    stale "processing" 상태를 리셋하여 재추출이 가능하게 한다.
    기존 그래프/메트릭은 유지한다 (재추출 시 덮어씀).
    """
    job.ediscovery_status = ""
    job.ediscovery_job_id = ""
    db.commit()
    logger.info(f"[ediscovery-api] stale processing 리셋 job={job.id}")


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
        "ediscovery_context": job.ediscovery_context or "",
        "ediscovery_error": (job.ediscovery_metrics or {}).get("error", ""),
    }


@router.get("/jobs/{job_id}/ediscovery")
def get_ediscovery(
    job_id: str,
    user: CurrentUser = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (Job 조회) -> Step 2 (권한/만료/완료 상태 검증)
          -> Step 3 (stale processing 감지 시 자동 리셋) -> Step 4 (e-Discovery 상태/그래프 반환)]"""
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    _require_job_done(job)

    # stale "processing" 자동 감지 — 폴링 중인 프론트엔드가 무한 대기하지 않도록 리셋
    if job.ediscovery_status == "processing" and _is_ediscovery_stale(job, db):
        _reset_stale_processing(job, db)

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

    e-Discovery GraphRAG 추출을 실행한다.
    payload.auto=true이거나 chunk_size/threshold/max_docs가 모두 누락되면 LLM이 문서를 보고 자동 파라미터를 결정한다.
    AI 백엔드 도구는 wait 기본값(true)로 즉시 결과를 받고, 프론트엔드는 wait=false로 비동기 폴링할 수 있다.
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    _require_job_done(job)

    auto = bool(payload.get("auto", False))
    if not auto:
        # chunk_size/threshold/max_docs 중 하나라도 명시되지 않으면 자동 모드로 전환
        has_chunk = payload.get("chunk_size") is not None or payload.get("chunkSize") is not None
        has_threshold = payload.get("threshold") is not None
        has_max_docs = (
            payload.get("max_docs") is not None
            or payload.get("max_chunks") is not None
            or payload.get("maxDocs") is not None
        )
        if not (has_chunk and has_threshold and has_max_docs):
            auto = True

    if auto:
        chunk_size = None
        threshold = None
        max_docs = None
    else:
        chunk_size = int(payload.get("chunk_size", payload.get("chunkSize", pipeline_ediscovery.DEFAULT_CHUNK_SIZE)))
        threshold = float(payload.get("threshold", pipeline_ediscovery.DEFAULT_THRESHOLD))
        threshold = max(0.0, min(1.0, threshold))
        max_docs = payload.get("max_docs") or payload.get("max_chunks") or payload.get("maxDocs")
        if max_docs is not None:
            max_docs = int(max_docs)
    query = str(payload.get("query", "")).strip() or None

    # 분석 시 사용자가 입력/수정한 e-Discovery 컨텍스트를 저장하고 LLM 프롬프트에 반영한다.
    ediscovery_context = str(payload.get("context", "") or "").strip()
    if ediscovery_context:
        job.ediscovery_context = ediscovery_context

    total_pages = job.total_pages if job.total_pages else (job.total_files or 1)
    page_range = _parse_page_range(payload.get("page_range"), total_pages)

    # 요청 파라미터 저장 — started_at은 stale 타임아웃 판정용
    job.ediscovery_params = {
        "auto": auto,
        "chunk_size": chunk_size,
        "threshold": threshold,
        "max_docs": max_docs,
        "query": query,
        "page_range": page_range,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    # stale "processing" 감지 — Celery 태스크가 소실/종료되었으면 상태 리셋 후 재추출 허용
    if job.ediscovery_status == "processing":
        if _is_ediscovery_stale(job, db):
            _reset_stale_processing(job, db)
        else:
            return {
                "job_id": job.id,
                "status": "processing",
                "message": "e-Discovery extraction already in progress",
            }

    job.ediscovery_status = "processing"
    db.commit()

    logger.info(f"[ediscovery-api] extract job={job_id} auto={auto} chunk_size={chunk_size} threshold={threshold} max_docs={max_docs} query={query} page_range={page_range} wait={wait}")

    if not wait:
        from ..workers import tasks
        task = tasks.run_ediscovery.delay(
            job_id,
            chunk_size=chunk_size,
            threshold=threshold,
            page_range=page_range,
            max_docs=max_docs,
            query=query,
            context=job.ediscovery_context,
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
        context=job.ediscovery_context,
        user_id=str(user.user_id),
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
        if _is_ediscovery_stale(job, db):
            _reset_stale_processing(job, db)
        else:
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
          -> Step 4 (캐시 미스 시 vLLM으로 주장 추출) -> Step 5 (evidence_nodes가 있으면 주장-증거 관계 분석) -> Step 6 (퍼즐 매퍼 스키마 반환)]

    청구 원인(예: 사기죄)에 따른 법적 주장(요건사실) 3~5개를 도출한다.
    e-Discovery 그래프에 evidence 노드가 있으면 2차 LLM 호출로 주장-증거 관계를 분석하여 매핑한다.
    같은 claim_type으로 재요청 시 저장된 element_mappings를 캐시로 반환한다.
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    _require_job_done(job)

    claim_type = (claim_type or "").strip()
    cached = job.element_mappings or {}

    # claim_type이 없으면 자동 추출된 element_mappings(저장된 매핑)을 우선 반환
    if not claim_type:
        if cached.get("elements"):
            return {"job_id": job.id, "element_mappings": cached}
        raise HTTPException(status_code=400, detail="claim_type query parameter is required")

    # 캐시 확인: 같은 claim_type의 저장된 매핑이 있으면 반환
    if cached.get("claim_type") == claim_type and cached.get("elements"):
        return {"job_id": job.id, "element_mappings": cached}

    endpoint, model, api_key = _resolve_llm_settings(job, db)
    logger.info(f"[legal-elements-api] extract job={job_id} claim_type={claim_type}")

    # e-Discovery 그래프에서 evidence 노드 추출 (주장-증거 관계 분석용)
    graph = job.ediscovery_graphs or {}
    evidence_nodes = [n for n in graph.get("nodes", []) if n.get("type") == "evidence"]

    mappings = legal_elements.extract_legal_elements(claim_type, endpoint, model, api_key, evidence_nodes=evidence_nodes)
    # 추출 결과를 저장 (빈 슬롯/자동 매핑 상태로 영속화 — 이후 PUT /mappings로 갱신)
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
    주장-증거 관계(reason) 필드를 포함한 mapped_evidence를 그대로 유지하며,
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

    저장된 주장-증거 퍼즐 매핑 상태를 조회한다 (페이지 새로고침 후 복원용).
    저장된 상태가 없으면 빈 스키마를 반환한다.
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    _require_job_done(job)

    mappings = job.element_mappings or {}
    return {"job_id": job.id, "element_mappings": mappings}


# ============================================================
# Issue-Claim-Evidence Tree — 쟁점 → 주장 → 근거 3단계 트리 매퍼
# 양측(원고/피고, 검사/피고인 등) 주장이 대립하는 쟁점을 부모로,
# 각 쟁점 아래에 양측 주장과 근거를 자식으로 배치한다.
# ============================================================

@router.get("/jobs/{job_id}/legal-issue-tree")
def get_legal_issue_tree(
    job_id: str,
    claim_type: str = "",
    user: CurrentUser = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (Job 조회 + 권한 검증) -> Step 2 (claim_type 파싱) -> Step 3 (캐시 확인)
          -> Step 4 (e-Discovery evidence 노드 추출) -> Step 5 (문서 페이지 텍스트 추출)
          -> Step 6 (1차 LLM: 쟁점-주장-근거 트리 추출) -> Step 7 (2차 LLM: 문서 교차검증)
          -> Step 8 (issue_tree JSONB에 영속화) -> Step 9 (3단계 트리 반환)]

    청구 원인(예: 사기죄)에 따른 쟁점 → 주장 → 근거 3단계 트리를 도출한다.
    e-Discovery 그래프의 evidence 노드와 문서 텍스트를 교차검증에 활용한다.
    같은 claim_type으로 재요청 시 저장된 issue_tree를 캐시로 반환한다.
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    _require_job_done(job)

    claim_type = (claim_type or "").strip()
    cached = job.issue_tree or {}

    if not claim_type:
        if cached.get("issues"):
            return {"job_id": job.id, "issue_tree": cached}
        raise HTTPException(status_code=400, detail="claim_type query parameter is required")

    if cached.get("claim_type") == claim_type and cached.get("issues"):
        return {"job_id": job.id, "issue_tree": cached}

    endpoint, model, api_key = _resolve_llm_settings(job, db)
    logger.info(f"[legal-issue-tree-api] extract job={job_id} claim_type={claim_type}")

    graph = job.ediscovery_graphs or {}
    evidence_nodes = [n for n in graph.get("nodes", []) if n.get("type") == "evidence"]

    try:
        page_texts, _page_meta = pipeline_ediscovery.extract_page_texts(job)
    except Exception as e:
        logger.warning(f"[legal-issue-tree-api] page_texts 추출 실패 job={job_id}: {e}")
        page_texts = {}

    db_user = db.get(User, uuid.UUID(user.user_id))
    tree = legal_issue_tree.extract_issue_claim_tree(
        claim_type, evidence_nodes, page_texts, endpoint, model, api_key, db=db, user=db_user
    )
    tree["overall_progress_percent"] = legal_issue_tree.compute_overall_progress(tree)
    job.issue_tree = tree
    db.commit()

    return {"job_id": job.id, "issue_tree": tree}


@router.put("/jobs/{job_id}/legal-issue-tree/mappings")
def save_issue_tree_mappings(
    job_id: str,
    payload: dict = Body(...),
    user: CurrentUser = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (Job 조회 + 권한 검증) -> Step 2 (3단계 트리 payload 파싱)
          -> Step 3 (overall_progress_percent 서버 재계산) -> Step 4 (issue_tree JSONB에 영속화)
          -> Step 5 (저장된 상태 반환)]

    프론트엔드에서 완성된 3단계 트리 상태를 Supabase jobs 테이블의 issue_tree JSONB에 저장한다.
    주장-근거 관계(reason) 필드를 포함한 mapped_evidence를 그대로 유지하며,
    overall_progress_percent는 서버에서 재계산한다.
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    _require_job_done(job)

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload: expected JSON object")

    tree = {
        "claim_type": str(payload.get("claim_type", "")).strip(),
        "overall_progress_percent": 0,
        "cross_validated": bool(payload.get("cross_validated", False)),
        "issues": payload.get("issues", []) if isinstance(payload.get("issues"), list) else [],
    }
    tree["overall_progress_percent"] = legal_issue_tree.compute_overall_progress(tree)

    job.issue_tree = tree
    db.commit()
    logger.info(f"[legal-issue-tree-api] save job={job_id} progress={tree['overall_progress_percent']}%")

    return {"job_id": job.id, "issue_tree": tree}


@router.get("/jobs/{job_id}/legal-issue-tree/mappings")
def get_issue_tree_mappings(
    job_id: str,
    user: CurrentUser = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (Job 조회 + 권한 검증) -> Step 2 (저장된 issue_tree 반환)]

    저장된 쟁점-주장-근거 3단계 트리 매핑 상태를 조회한다 (페이지 새로고침 후 복원용).
    저장된 상태가 없으면 빈 스키마를 반환한다.
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    _require_job_done(job)

    tree = job.issue_tree or {}
    return {"job_id": job.id, "issue_tree": tree}


# ============================================================
# Legal Case Profile — 에이전트가 판단한 법률 분야/청구 원인/쟁점 분석
# ============================================================

@router.post("/jobs/{job_id}/legal-profile/analyze")
def analyze_legal_profile(
    job_id: str,
    payload: dict = Body(default={}),
    user: CurrentUser = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (Job 조회 + 권한 검증) -> Step 2 (문서 텍스트 추출)
          -> Step 3 (LLM 설정 해결) -> Step 4 (legal_case_profile.extract_legal_profile 호출)
          -> Step 5 (분석 결과 반환)]

    에이전트가 법률 분야, 청구 원인, 쟁점, 요건사실을 판단할 수 있도록
    문서 텍스트와 선택적 힌트(claim_type_hint, additional_context)를 입력으로
    LLM 기반 법률 프로필 분석을 실행한다.
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    _require_job_done(job)

    page_texts, _page_meta = pipeline_ediscovery.extract_page_texts(job)
    if not page_texts:
        raise HTTPException(status_code=400, detail="문서에서 텍스트를 추출할 수 없습니다")

    endpoint, model, api_key = _resolve_llm_settings(job, db)

    claim_type_hint = str(payload.get("claim_type_hint", "")).strip() or None
    additional_context = str(payload.get("additional_context", "")).strip() or None

    profile = legal_case_profile.extract_legal_profile(
        page_texts,
        endpoint,
        model,
        api_key,
        original_filename=job.original_filename,
        total_pages=len(page_texts),
        claim_type_hint=claim_type_hint,
        additional_context=additional_context,
    )

    if not profile:
        raise HTTPException(status_code=502, detail="법률 프로필 분석에 실패했습니다")

    logger.info(f"[legal-profile-api] job={job_id} domain={profile.get('legal_domain')} claim={profile.get('claim_type')}")

    return {
        "job_id": job.id,
        "legal_profile": profile,
    }

