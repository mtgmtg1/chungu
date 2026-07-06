#!/usr/bin/env python3
# [Flow: Step 1 (인증 및 요청 검증) -> Step 2 (AgentRun DB 생성) -> Step 3 (Celery task 시작)
#       -> Step 4 (run_id 반환) -> Step 5 (resume/status/stream API로 interrupt 처리 및 상태 조회)]
# LangGraph 에이전트 실행을 위한 API. PDF AI 주석과 마크다운 에디터 AI 모두 이 엔드포인트를 사용한다.
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...auth.api_key_auth import require_api_key_or_session
from ...auth.supabase_auth import CurrentUser
from ...celery_app import celery as celery_app
from ...config import settings
from ...core.agent_engine import (
    get_agent_status,
    get_async_redis_checkpointer,
    make_thread_config,
    resume_agent_graph,
    serialize_agent_state,
    serialize_interrupt,
    setup_redis_checkpointer,
    stream_agent_graph,
)
from ...core.agent_annotator import build_annotator_graph
from ...core.agent_editor import build_editor_graph
from ...core.agent_llm import build_agent_llm
from ...db.models import AgentRun, ApiKey, Job
from ...db.session import get_db
from ...workers.tasks import agent_run_task

router = APIRouter(prefix="/agent", tags=["agent"])


def _load_graph(graph_name: str, payload: dict[str, Any]) -> Any:
    """[Flow: Step 1 (payload에서 endpoint/model/api_key 추출) -> Step 2 (LLM 인스턴스 생성)
          -> Step 3 (Redis 체크포인터 생성) -> Step 4 (graph_name에 맞는 그래프 빌드)]

    API에서 재개/상태/스트리밍 시 동일한 LLM + 체크포인터로 그래프를 복원한다.
    """
    endpoint = payload.get("endpoint", settings.default_llm_endpoint)
    model = payload.get("model", settings.default_llm_model)
    api_key = payload.get("api_key", "")
    llm = build_agent_llm(endpoint, model, api_key)
    saver = get_async_redis_checkpointer()
    if graph_name == "annotator":
        return build_annotator_graph(llm, saver)
    if graph_name == "editor":
        return build_editor_graph(llm, saver)
    raise HTTPException(status_code=400, detail="Unknown graph_name")


class RunAgentRequest(BaseModel):
    """에이전트 실행 요청 본문."""

    graph_name: str = Field(..., pattern="^(annotator|editor)$")
    payload: dict[str, Any] = Field(default_factory=dict)
    thread_id: str | None = Field(None, description="재개/상태 조회용 고정 스레드 ID")


class ResumeAgentRequest(BaseModel):
    """interrupt 재개 요청 본문."""

    resume_value: Any


class AgentRunResponse(BaseModel):
    """에이전트 실행 응답."""

    run_id: str
    thread_id: str
    status: str
    pending_interrupt: Any | None
    result: Any | None
    error: str | None


@router.post("/run")
async def run_agent(
    body: RunAgentRequest,
    auth: tuple[CurrentUser, ApiKey | None] = Depends(require_api_key_or_session),
    db: Session = Depends(get_db),
) -> AgentRunResponse:
    """새로운 에이전트 실행을 시작한다.

    Args:
        body: graph_name과 payload.
        auth: 인증된 사용자와 API key.
        db: DB 세션.

    Returns:
        생성된 run_id, thread_id, 초기 상태.
    """
    user, api_key = auth
    user_id = user.user_id if user else None

    thread_id = body.thread_id or make_thread_config()["configurable"]["thread_id"]

    # LLM endpoint 결정
    payload = dict(body.payload)
    payload.setdefault("endpoint", settings.default_llm_endpoint)
    payload.setdefault("model", settings.default_llm_model)
    payload.setdefault("api_key", "")

    # job_id가 있으면 존재/권한 확인
    job_id = payload.get("job_id")
    if job_id:
        job = db.get(Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if user and not user.is_admin and job.user_id and job.user_id != user.user_id:
            raise HTTPException(status_code=403, detail="Not authorized for this job")

    run = AgentRun(
        job_id=job_id,
        user_id=user_id,
        graph_name=body.graph_name,
        thread_id=thread_id,
        status="running",
        payload=payload,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Celery task 시작
    agent_run_task.delay(run.id)

    return AgentRunResponse(
        run_id=run.id,
        thread_id=thread_id,
        status="running",
        pending_interrupt=None,
        result=None,
        error=None,
    )


@router.post("/resume/{run_id}")
async def resume_agent(
    run_id: str,
    body: ResumeAgentRequest,
    auth: tuple[CurrentUser, ApiKey | None] = Depends(require_api_key_or_session),
    db: Session = Depends(get_db),
) -> AgentRunResponse:
    """interrupt 상태인 에이전트 실행을 재개한다.

    Args:
        run_id: 재개할 AgentRun ID.
        body: interrupt()에 전달할 값.
        auth: 인증된 사용자.
        db: DB 세션.

    Returns:
        재개 후 상태.
    """
    user, api_key = auth
    run = db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="AgentRun not found")
    if user and not user.is_admin and run.user_id and run.user_id != user.user_id:
        raise HTTPException(status_code=403, detail="Not authorized for this run")

    graph = _load_graph(run.graph_name, run.payload)
    await setup_redis_checkpointer(graph.checkpointer)
    result = await resume_agent_graph(graph, body.resume_value, run.thread_id)

    run.status = result.get("status", "error")
    run.result = serialize_agent_state(result.get("result") or {})
    run.pending_interrupt = serialize_agent_state(result.get("pending_interrupt"))
    run.error = result.get("error") or ""
    db.commit()

    return AgentRunResponse(
        run_id=run.id,
        thread_id=run.thread_id,
        status=run.status,
        pending_interrupt=serialize_interrupt(run.pending_interrupt) if run.pending_interrupt else None,
        result=run.result,
        error=run.error,
    )


@router.get("/status/{run_id}")
async def get_agent_run_status(
    run_id: str,
    auth: tuple[CurrentUser, ApiKey | None] = Depends(require_api_key_or_session),
    db: Session = Depends(get_db),
) -> AgentRunResponse:
    """AgentRun의 현재 상태를 조회한다."""
    user, api_key = auth
    run = db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="AgentRun not found")
    if user and not user.is_admin and run.user_id and run.user_id != user.user_id:
        raise HTTPException(status_code=403, detail="Not authorized for this run")

    # 체크포인터 기반 상태도 함께 조회
    try:
        graph = _load_graph(run.graph_name, run.payload)
        await setup_redis_checkpointer(graph.checkpointer)
        checkpoint_status = await get_agent_status(graph, run.thread_id)
        if checkpoint_status.get("status") == "interrupted":
            run.status = "interrupted"
            run.pending_interrupt = checkpoint_status.get("pending_interrupt")
        db.commit()
    except Exception as exc:
        # 체크포인터 조회 실패 시 DB 상태만 반환
        pass

    return AgentRunResponse(
        run_id=run.id,
        thread_id=run.thread_id,
        status=run.status,
        pending_interrupt=serialize_interrupt(run.pending_interrupt) if run.pending_interrupt else None,
        result=run.result,
        error=run.error,
    )


@router.get("/stream/{run_id}")
async def stream_agent_run(
    run_id: str,
    auth: tuple[CurrentUser, ApiKey | None] = Depends(require_api_key_or_session),
    db: Session = Depends(get_db),
):
    """에이전트 실행 이벤트를 SSE로 스트리밍한다.

    현재 실행이 완료된 후에도 체크포인터에서 최종 상태를 스트리밍할 수 있다.
    """
    user, api_key = auth
    run = db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="AgentRun not found")
    if user and not user.is_admin and run.user_id and run.user_id != user.user_id:
        raise HTTPException(status_code=403, detail="Not authorized for this run")

    graph = _load_graph(run.graph_name, run.payload)
    await setup_redis_checkpointer(graph.checkpointer)

    # TODO: 현재는 체크포인터 상태를 재실행하는 것이 아니라, 이벤트를 스트리밍하는 형태.
    # 실제 구현에서는 astream_events로 재실행하거나, 중간 이벤트를 Redis pub/sub에 저장해야 한다.
    async def event_stream() -> AsyncIterator[str]:
        import json

        status = await get_agent_status(graph, run.thread_id)
        yield f"data: {json.dumps({'event': 'status', 'data': status}, ensure_ascii=False, default=str)}\n\n"
        yield f"data: {json.dumps({'event': 'done', 'data': None}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
