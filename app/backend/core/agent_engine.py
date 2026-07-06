#!/usr/bin/env python3
# [Flow: Step 1 (Redis 체크포인터 생성) -> Step 2 (LangGraph 그래프 실행/재개/스트리밍)
#       -> Step 3 (interrupt 발생 시 클라이언트용 상태 변환) -> Step 4 (최종 결과 반환)]
# PDF AI 주석과 마크다운 에디터 AI가 공통으로 사용하는 LangGraph 실행 엔진.
# 각 에이전트 모듈은 StateGraph를 직접 정의하고, 이 모듈의 헬퍼로 실행/재개/스트리밍한다.
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from ..config import settings

logger = logging.getLogger(__name__)


def get_async_redis_checkpointer() -> AsyncRedisSaver:
    """Redis URL을 사용해 비동기 RedisSaver 체크포인터를 생성한다.

    Celery worker와 FastAPI 모두에서 settings.redis_url을 재사용한다.
    RedisSaver는 setup()으로 인덱스를 초기화해야 한다.
    """
    saver = AsyncRedisSaver(redis_url=settings.redis_url)
    return saver


async def setup_redis_checkpointer(saver: AsyncRedisSaver) -> None:
    """RedisSaver의 인덱스를 초기화한다."""
    await saver.asetup()


def make_thread_config(thread_id: str | None = None) -> dict[str, Any]:
    """LangGraph 실행에 필요한 config를 생성한다.

    thread_id가 없으면 UUID를 생성한다. config는 체크포인터가 상태를 저장할
    스레드를 식별하는 데 사용된다.
    """
    return {
        "configurable": {
            "thread_id": thread_id or str(uuid.uuid4()),
        },
    }


async def run_agent_graph(
    graph: CompiledStateGraph,
    inputs: dict[str, Any],
    thread_id: str | None = None,
) -> dict[str, Any]:
    """에이전트 그래프를 실행하고, interrupt 발생 시 상태를 반환한다.

    Args:
        graph: compile()된 StateGraph.
        inputs: 그래프 초기 입력 상태.
        thread_id: 재개/상태 조회를 위한 고정 스레드 ID. None이면 생성.

    Returns:
        {
            "thread_id": str,
            "status": "done" | "interrupted" | "error",
            "result": any,              # status=done일 때 최종 상태
            "pending_interrupt": any,   # status=interrupted일 때 interrupt 값
            "error": str,               # status=error일 때 메시지
        }
    """
    config = make_thread_config(thread_id)
    try:
        final_state = await graph.ainvoke(inputs, config)
        # LangGraph는 interrupt() 발생 시 예외를 던지지 않고 상태에 __interrupt__를 남긴다.
        if final_state.get("__interrupt__"):
            return {
                "thread_id": config["configurable"]["thread_id"],
                "status": "interrupted",
                "result": final_state,
                "pending_interrupt": final_state.get("pending_interrupt"),
                "error": None,
            }
        return {
            "thread_id": config["configurable"]["thread_id"],
            "status": "done",
            "result": final_state,
            "pending_interrupt": None,
            "error": None,
        }
    except Exception as exc:
        logger.exception("[agent_engine] 그래프 실행 중 예외: %s", exc)
        return {
            "thread_id": config["configurable"]["thread_id"],
            "status": "error",
            "result": None,
            "pending_interrupt": None,
            "error": str(exc),
        }


async def resume_agent_graph(
    graph: CompiledStateGraph,
    resume_value: Any,
    thread_id: str,
) -> dict[str, Any]:
    """interrupt가 발생한 그래프를 Command(resume=...)으로 재개한다.

    Args:
        graph: compile()된 StateGraph.
        resume_value: interrupt() 호출 지점으로 반환될 값.
        thread_id: 재개할 스레드 ID.

    Returns:
        run_agent_graph와 동일한 형식.
    """
    config = make_thread_config(thread_id)
    try:
        final_state = await graph.ainvoke(Command(resume=resume_value), config)
        if final_state.get("__interrupt__"):
            return {
                "thread_id": thread_id,
                "status": "interrupted",
                "result": final_state,
                "pending_interrupt": final_state.get("pending_interrupt"),
                "error": None,
            }
        return {
            "thread_id": thread_id,
            "status": "done",
            "result": final_state,
            "pending_interrupt": None,
            "error": None,
        }
    except Exception as exc:
        logger.exception("[agent_engine] 그래프 재개 중 예외: %s", exc)
        return {
            "thread_id": thread_id,
            "status": "error",
            "result": None,
            "pending_interrupt": None,
            "error": str(exc),
        }


async def get_agent_status(
    graph: CompiledStateGraph,
    thread_id: str,
) -> dict[str, Any]:
    """지정 스레드의 현재 상태를 조회한다.

    Args:
        graph: compile()된 StateGraph.
        thread_id: 조회할 스레드 ID.

    Returns:
        {
            "thread_id": str,
            "status": "done" | "interrupted" | "running" | "not_found",
            "state": any,               # 저장된 상태
            "pending_interrupt": any,   # interrupt 값
        }
    """
    config = make_thread_config(thread_id)
    try:
        state = await graph.aget_state(config)
        pending = state.tasks if state else []
        # LangGraph의 상태에서 interrupt 정보를 추출한다.
        interrupt_value = None
        for task in pending:
            if task.interrupts:
                # interrupt 값은 JSON serializable해야 한다.
                interrupt_value = task.interrupts[0].value
                break
        if interrupt_value is not None:
            status = "interrupted"
        elif state and state.next:
            status = "running"
        else:
            status = "done"
        return {
            "thread_id": thread_id,
            "status": status,
            "state": state.values if state else None,
            "pending_interrupt": interrupt_value,
        }
    except Exception as exc:
        logger.warning("[agent_engine] 상태 조회 실패: %s", exc)
        return {
            "thread_id": thread_id,
            "status": "not_found",
            "state": None,
            "pending_interrupt": None,
        }


async def stream_agent_graph(
    graph: CompiledStateGraph,
    inputs: dict[str, Any] | Command,
    thread_id: str,
) -> AsyncIterator[dict[str, Any]]:
    """그래프 실행/재개를 스트리밍 이벤트로 반환한다.

    Args:
        graph: compile()된 StateGraph.
        inputs: 초기 상태 또는 Command(resume=...).
        thread_id: 스레드 ID.

    Yields:
        {
            "event": "message" | "tool" | "interrupt" | "error" | "done",
            "data": any,
        }
    """
    config = make_thread_config(thread_id)
    try:
        async for event in graph.astream_events(inputs, config, version="v2"):
            kind = event.get("event")
            name = event.get("name", "")
            data = event.get("data", {})

            if kind == "on_chat_model_stream":
                chunk = data.get("chunk")
                if chunk and chunk.content:
                    yield {"event": "message", "data": chunk.content}
            elif kind == "on_tool_start":
                yield {"event": "tool", "data": {"name": name, "input": data.get("input")}}
            elif kind == "on_tool_end":
                yield {"event": "tool", "data": {"name": name, "output": data.get("output")}}
            elif kind == "on_interrupt":
                # astream_events에서 interrupt는 별도 이벤트로 노출될 수 있다.
                yield {"event": "interrupt", "data": data}
        yield {"event": "done", "data": None}
    except Exception as exc:
        logger.exception("[agent_engine] 스트리밍 중 예외: %s", exc)
        yield {"event": "error", "data": str(exc)}


def serialize_interrupt(value: Any) -> Any:
    """interrupt 값을 클라이언트에 전달할 수 있도록 직렬화한다.

    Pydantic 모델 등은 dict로 변환하고, bytes는 문자열로 변환한다.
    """
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def serialize_agent_state(value: Any) -> Any:
    """[Flow: Step 1 (dict/list/dataclass/BaseMessage 판별) -> Step 2 (재귀적으로 JSON serializable 형태로 변환)]

    LangGraph agent의 최종 상태를 DB(JSONB)나 Celery backend에 저장할 수 있도록 직렬화한다.
    BaseMessage, dataclass(AnnotationTarget), bytes 등을 처리한다.
    """
    from dataclasses import asdict, is_dataclass

    from langchain_core.messages import BaseMessage

    if isinstance(value, dict):
        return {k: serialize_agent_state(v) for k, v in value.items()}
    if isinstance(value, list):
        return [serialize_agent_state(v) for v in value]
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, BaseMessage):
        return {"type": value.__class__.__name__, "content": getattr(value, "content", "")}
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
