#!/usr/bin/env python3
# [Flow: Step 1 (사용자 instruction과 job/page 정보 수신) -> Step 2 (LLM이 계획 수립)
#       -> Step 3 (도구 반복 호출: 검색, 요소 조회, 비교, 하이라이트/콜아웃 추가)
#       -> Step 4 (중간 검토 및 사용자 승인/거절) -> Step 5 (최종 주석 JSON 생성 및 업로드)]
# PDF AI 주석의 멀티스텝 에이전트. LangGraph StateGraph 기반으로, 복잡한 조건 분석과
# 다중 페이지/표 비교를 도구 호출과 반복 추론으로 처리한다.
import json
import logging
from typing import Annotated, Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from dataclasses import dataclass

from langgraph.types import interrupt
from typing_extensions import TypedDict

from .agent_engine import get_async_redis_checkpointer, setup_redis_checkpointer
from .agent_llm import build_agent_llm, parse_tool_calls_from_content

logger = logging.getLogger(__name__)


@dataclass
class AnnotationTarget:
    """PDF 주석 대상 하나 (pdf_annotator.AnnotationTarget와 동일한 구조)."""

    page_no: int  # 1-based
    bbox_pdf: tuple[float, float, float, float]  # (x0, y0, x1, y1)
    comment: str
    color: tuple[float, float, float] = (1.0, 0.92, 0.3)
    callout_color: tuple[float, float, float] | None = None
    opacity: float | None = None


class AnnotatorState(TypedDict, total=False):
    """PDF AI 주석 에이전트의 상태."""

    messages: Annotated[list[BaseMessage], add_messages]
    job_id: str
    instruction: str
    mode: str
    comment_mode: str
    page_range: list[int] | None
    language: str
    elements: list[dict]  # OCR/텍스트 레이어에서 추출한 요소 요약
    selected_targets: list[AnnotationTarget]
    pending_removals: list[str]
    recovery_notes: list[str]
    status: str
    final_annotations: list[dict] | None
    pending_interrupt: Any
    error: str


@tool
def search_text(query: str, page_no: int | None = None) -> str:
    """[Flow: Step 1 (검색어와 페이지 번호 수신) -> Step 2 (실제 검색은 _execute_node의 _do_search_text에서 수행)
          -> Step 3 (검색 결과 JSON 반환)]

    PDF 텍스트 레이어에서 키워드나 정규식으로 텍스트를 검색한다.

    Args:
        query: 검색할 문자열. 정규식을 지원한다.
        page_no: 1-based 페이지 번호. None이면 모든 페이지를 검색한다.

    Returns:
        검색된 요소의 요약 목록 JSON 문자열.
    """
    return json.dumps(
        {"matches": [], "query": query, "page_no": page_no},
        ensure_ascii=False,
    )


@tool
def get_elements(page_no: int | None = None) -> str:
    """OCR 또는 텍스트 레이어에서 추출한 페이지 요소 목록을 반환한다.

    Args:
        page_no: 1-based 페이지 번호. None이면 모든 페이지를 반환한다.

    Returns:
        요소 목록 JSON 문자열.
    """
    # TODO: pdf_annotate_converter의 elements 연동
    return json.dumps(
        {"elements": [], "page_no": page_no},
        ensure_ascii=False,
    )


@tool
def add_highlight(element_index: int, comment: str, color: str = "yellow") -> str:
    """선택한 요소에 하이라이트 주석을 추가한다.

    Args:
        element_index: elements 목록에서 선택한 인덱스.
        comment: 주석 코멘트.
        color: 색상 이름 (red, yellow, green, blue, orange, purple, pink, gray).

    Returns:
        추가 결과 JSON 문자열.
    """
    # TODO: AnnotateState.selected_targets에 추가
    return json.dumps(
        {"ok": True, "action": "highlight", "element_index": element_index, "comment": comment, "color": color},
        ensure_ascii=False,
    )


@tool
def add_callout(element_index: int, comment: str, color: str = "purple") -> str:
    """선택한 요소에 callout(텍스트 박스 + 화살표) 주석을 추가한다.

    Args:
        element_index: elements 목록에서 선택한 인덱스.
        comment: 주석 코멘트.
        color: 색상 이름.

    Returns:
        추가 결과 JSON 문자열.
    """
    # TODO: AnnotateState.selected_targets에 추가
    return json.dumps(
        {"ok": True, "action": "callout", "element_index": element_index, "comment": comment, "color": color},
        ensure_ascii=False,
    )


@tool
def remove_annotation(annotation_id: str) -> str:
    """기존 AI 주석을 제거한다. 삭제 전 사용자 승인이 필요하다.

    Args:
        annotation_id: 제거할 주석 ID.

    Returns:
        승인 대기 상태 JSON 문자열.
    """
    return json.dumps(
        {"requires_approval": True, "action": "remove_annotation", "annotation_id": annotation_id},
        ensure_ascii=False,
    )


@tool
def compare_elements(description: str, page_nos: list[int]) -> str:
    """여러 페이지의 요소를 비교 분석한다.

    Args:
        description: 비교할 기준이나 조건.
        page_nos: 비교할 1-based 페이지 번호 목록.

    Returns:
        비교 결과 요약 JSON 문자열.
    """
    # TODO: 다중 페이지 요소 비교 로직 연동
    return json.dumps(
        {"description": description, "page_nos": page_nos, "matches": []},
        ensure_ascii=False,
    )


@tool
def ask_user(question: str, options: list[str] | None = None) -> str:
    """사용자에게 질문을 던지거나 승인을 요청한다.

    Args:
        question: 사용자에게 표시할 질문/요청.
        options: 선택 가능한 옵션. None이면 자유 입력.

    Returns:
        승인/질문 요청 플래그. _execute_node에서 이를 감지해 interrupt를 발생시킨다.
    """
    return json.dumps(
        {"requires_approval": True, "question": question, "options": options},
        ensure_ascii=False,
    )


@tool
def finish(summary: str) -> str:
    """[Flow: Step 1 (요약 메시지 수신) -> Step 2 (완료 상태 JSON 반환)]

    작업을 완료하고 최종 요약을 반환한다.

    Args:
        summary: 사용자에게 표시할 요약 메시지.

    Returns:
        완료 결과 JSON 문자열.
    """
    return json.dumps({"ok": True, "action": "finish", "summary": summary}, ensure_ascii=False)


TOOLS = [
    search_text,
    get_elements,
    add_highlight,
    add_callout,
    remove_annotation,
    compare_elements,
    ask_user,
    finish,
]


PLAN_SYSTEM_PROMPT = """You are a PDF annotation agent. Your job is to analyze a user's instruction and decide which text elements in a PDF should be highlighted or annotated with callouts.

You have access to these tools:
- search_text: search the PDF text layer for keywords or regex.
- get_elements: retrieve OCR/text-layer elements for a page.
- add_highlight: add a highlight annotation to an element.
- add_callout: add a callout annotation (text box + arrow) to an element.
- remove_annotation: remove an existing AI annotation (requires approval).
- compare_elements: compare elements across multiple pages/tables.
- ask_user: ask the user a clarifying question or request approval.
- finish: complete the task and return a summary.

Workflow:
1. Plan: break the user's instruction into steps. If the instruction is ambiguous, ask the user first.
2. Gather: use search_text, get_elements, and compare_elements to find relevant elements.
3. Annotate: use add_highlight/add_callout for each relevant element.
4. Review: check if the result matches the instruction. If not, repeat steps 2-3.
5. Finish: when done, return a concise summary of the annotations created.

Important rules:
- For simple actions (adding highlights/callouts), proceed autonomously.
- For destructive actions (removing annotations) or ambiguous instructions, ask the user for approval.
- Write comments in the same language as the user's instruction.
- Always use the element_index returned by get_elements for add_highlight/add_callout.
- Do not just describe the plan; invoke the tools to gather and annotate.
- After gathering elements, you MUST call add_highlight/add_callout for every matching element.
- When the task is complete, return a concise summary.
"""


def _plan_node(state: AnnotatorState) -> AnnotatorState:
    """[Flow: Step 1 (현재 상태와 메시지 확인) -> Step 2 (시스템 프롬프트 + 사용자 지시 추가)
          -> Step 3 (LLM에 계획 수립 요청) -> Step 4 (응답을 메시지에 추가)]

    에이전트의 첫 번째 노드. 사용자 instruction을 분석해 작업 계획을 세운다.
    """
    messages = state.get("messages", [])
    if not messages:
        instruction = state.get("instruction", "")
        mode = state.get("mode", "both")
        page_range = state.get("page_range")
        prompt = f"User instruction: {instruction}\n"
        prompt += f"Annotation mode: {mode}\n"
        if page_range:
            prompt += f"Target pages: {page_range}\n"
        prompt += "\nPlease perform the annotation task using the available tools."
        if mode in ("highlight", "both"):
            prompt += " For each matching element, call add_highlight with a clear comment."
        if mode in ("callout", "both"):
            prompt += " For each matching element, call add_callout with a clear comment."
        prompt += " Do not just summarize; invoke the tools to create the annotations."
        messages = [
            SystemMessage(content=PLAN_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]
    # LLM 호출은 agent_node에서 tool binding으로 처리하므로, 여기서는 메시지 구성만 한다.
    return {"messages": messages}


def _agent_node(state: AnnotatorState, llm) -> AnnotatorState:
    """[Flow: Step 1 (LLM에 도구 바인딩) -> Step 2 (메시지로부터 다음 행동 예측)
          -> Step 3 (tool call 또는 최종 응답 반환, content 기반 fallback 파싱)]

    ReAct 스타일의 추론 노드. LLM이 도구를 호출하거나 최종 답변을 생성한다.
    """
    messages = state.get("messages", [])
    model = llm.bind_tools(TOOLS, tool_choice="required")
    response = model.invoke(messages)
    response = parse_tool_calls_from_content(response)
    return {"messages": [response]}


def _execute_node(state: AnnotatorState, text_searcher: Any = None) -> AnnotatorState:
    """[Flow: Step 1 (마지막 AIMessage의 tool_calls 추출) -> Step 2 (도구 이름으로 함수 매핑)
          -> Step 3 (도구 실행 또는 state/text_searcher 기반 계산) -> Step 4 (ToolMessage 추가 및 상태 갱신/승인 요청 감지)]

    LLM이 요청한 도구를 실행하고 결과를 메시지로 추가한다.
    search_text는 text_searcher(있는 경우)와 state["elements"]를 모두 사용한다.
    get_elements/compare_elements는 state["elements"]를 기반으로 결과를 계산하고,
    add_highlight/add_callout 결과는 선택된 주석 대상으로 변환한다.
    삭제/질문 등 승인이 필요한 도구는 pending_interrupt에 저장한다.
    """
    messages = state.get("messages", [])
    last_message = messages[-1] if messages else None
    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return {"messages": []}

    tool_map = {t.name: t for t in TOOLS}
    tool_messages: list[ToolMessage] = []
    pending_interrupt: dict | None = None
    selected_targets: list[AnnotationTarget] = list(state.get("selected_targets", []))
    pending_removals: list[str] = list(state.get("pending_removals", []))
    elements: list[dict] = state.get("elements", [])

    for tool_call in last_message.tool_calls:
        name = tool_call.get("name")
        args = tool_call.get("args", {})
        tool_id = tool_call.get("id", "")
        if name not in tool_map:
            tool_messages.append(
                ToolMessage(content=json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False), tool_call_id=tool_id)
            )
            continue

        try:
            if name == "search_text":
                result = _do_search_text(elements, args.get("query", ""), args.get("page_no"), text_searcher)
            elif name == "get_elements":
                result = _do_get_elements(elements, args.get("page_no"))
            elif name == "compare_elements":
                result = _do_compare_elements(elements, args.get("description", ""), args.get("page_nos", []))
            else:
                result = tool_map[name].invoke(args)
        except Exception as exc:
            result = json.dumps({"error": str(exc)}, ensure_ascii=False)
        tool_messages.append(ToolMessage(content=str(result), tool_call_id=tool_id))

        try:
            parsed = json.loads(result)
        except Exception:
            parsed = {}
        if not isinstance(parsed, dict):
            continue

        if parsed.get("requires_approval"):
            pending_interrupt = parsed
        elif name in ("add_highlight", "add_callout"):
            target = _target_from_tool_result(parsed, elements)
            if target:
                selected_targets.append(target)
        elif name == "remove_annotation" and parsed.get("annotation_id"):
            pending_removals.append(parsed["annotation_id"])

    updates: AnnotatorState = {"messages": tool_messages}
    if selected_targets:
        updates["selected_targets"] = selected_targets
    if pending_removals:
        updates["pending_removals"] = pending_removals
    if pending_interrupt:
        updates["pending_interrupt"] = pending_interrupt
    return updates


def _do_search_text(
    elements: list[dict],
    query: str,
    page_no: int | None = None,
    text_searcher: Any = None,
) -> str:
    """[Flow: Step 1 (query/page_no 정규화) -> Step 2 (text_searcher가 있으면 PDF 텍스트 레이어에서 검색)
          -> Step 3 (text_searcher 결과가 없으면 elements 기반 검색 폴백) -> Step 4 (JSON 결과 반환)]

    query를 포함하는 요소를 검색한다. PDF 텍스트 레이어 검색기가 있으면 더 정확한 PDF 좌표를 우선 사용한다.
    """
    q = str(query).lower()
    try:
        page_no = int(page_no) if page_no is not None else None
    except Exception:
        page_no = None

    if text_searcher is not None and page_no is not None and q:
        try:
            rects = text_searcher.search(page_no, query)
            if rects:
                matches = [
                    {"element_index": i, "page_no": page_no, "bbox_pdf": list(rect), "text": query}
                    for i, rect in enumerate(rects)
                ]
                return json.dumps({"matches": matches, "query": query, "page_no": page_no}, ensure_ascii=False)
        except Exception as exc:
            logger.warning("[search_text] TextLayerSearcher 검색 실패: %s", exc)

    matches = []
    for i, el in enumerate(elements):
        if page_no is not None and el.get("page_no") != page_no:
            continue
        text = str(el.get("text", "")).lower()
        if q in text:
            matches.append({"element_index": i, **el})
    return json.dumps({"matches": matches, "query": query, "page_no": page_no}, ensure_ascii=False)


def _do_get_elements(elements: list[dict], page_no: int | None = None) -> str:
    """elements 목록에서 지정 페이지의 요소를 반환한다."""
    try:
        page_no = int(page_no) if page_no is not None else None
    except Exception:
        page_no = None
    filtered = elements if page_no is None else [el for el in elements if el.get("page_no") == page_no]
    indexed = [{"element_index": i, **el} for i, el in enumerate(filtered)]
    return json.dumps({"elements": indexed, "page_no": page_no}, ensure_ascii=False)


def _do_compare_elements(elements: list[dict], description: str, page_nos: list[int]) -> str:
    """지정 페이지들의 요소를 모아 비교 분석용 목록으로 반환한다.

    TODO: LLM을 사용한 실제 비교 분석 추가.
    """
    page_set = set(page_nos) if page_nos else set()
    candidates = [el for el in elements if el.get("page_no") in page_set]
    return json.dumps(
        {"description": description, "page_nos": page_nos, "candidates": candidates},
        ensure_ascii=False,
    )


def _color_by_name(color_name: str) -> tuple[float, float, float]:
    """색상 이름을 RGB 튜플로 변환한다."""
    palette = {
        "red": (1.0, 0.25, 0.25),
        "yellow": (1.0, 0.92, 0.3),
        "green": (0.25, 0.85, 0.35),
        "blue": (0.25, 0.55, 1.0),
        "orange": (1.0, 0.6, 0.15),
        "purple": (0.65, 0.35, 0.95),
        "pink": (1.0, 0.55, 0.75),
        "gray": (0.7, 0.7, 0.7),
    }
    return palette.get((color_name or "").lower(), (1.0, 0.92, 0.3))


def _target_from_tool_result(parsed: dict, elements: list[dict]) -> AnnotationTarget | None:
    """add_highlight/add_callout 도구 결과와 elements 목록에서 AnnotationTarget을 생성한다."""
    element_index = parsed.get("element_index")
    if not isinstance(element_index, int) or element_index < 0 or element_index >= len(elements):
        return None
    el = elements[element_index]
    bbox = el.get("bbox_pdf") or el.get("bbox_px") or [0, 0, 0, 0]
    try:
        bbox_pdf = tuple(float(v) for v in bbox)
    except Exception:
        return None
    return AnnotationTarget(
        page_no=int(el.get("page_no", 1)),
        bbox_pdf=bbox_pdf,
        comment=parsed.get("comment", ""),
        color=_color_by_name(parsed.get("color", "yellow")),
        callout_color=_color_by_name(parsed.get("color", "purple")) if parsed.get("action") == "callout" else None,
        opacity=None,
    )


def _route_after_agent(state: AnnotatorState) -> str:
    """[Flow: Step 1 (마지막 메시지 확인) -> Step 2 (tool_calls 유무에 따라 분기)]

    agent 노드 이후의 조건부 라우팅. 마지막 메시지가 tool call을 포함하면 execute,
    finish tool만 있으면 finalize로 이동한다.
    """
    messages = state.get("messages", [])
    last_message = messages[-1] if messages else None
    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return "finalize"
    tool_names = {tc.get("name") for tc in last_message.tool_calls}
    if tool_names == {"finish"}:
        return "finalize"
    return "execute"


def _route_after_execute(state: AnnotatorState) -> str:
    """[Flow: Step 1 (pending_interrupt 및 tool_calls 확인) -> Step 2 (hitl/agent/finalize 분기)]

    execute 노드 이후의 조건부 라우팅. 승인 요청이 있으면 hitl,
    tool call 결과(ToolMessage)를 받으면 agent로 재추론, finish tool만 있으면 finalize로 이동한다.
    """
    if state.get("pending_interrupt"):
        return "hitl"
    messages = state.get("messages", [])
    last_message = messages[-1] if messages else None
    if isinstance(last_message, ToolMessage):
        return "agent"
    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return "finalize"
    tool_names = {tc.get("name") for tc in last_message.tool_calls}
    if tool_names == {"finish"}:
        return "finalize"
    return "execute"


def _hitl_node(state: AnnotatorState) -> AnnotatorState:
    """[Flow: Step 1 (pending_interrupt 값 추출) -> Step 2 (interrupt()로 사용자 입력 대기)
          -> Step 3 (resume 시 응답을 메시지에 추가하고 pending_interrupt 초기화)]

    human-in-the-loop 노드. 사용자의 승인/거절/응답을 interrupt로 받는다.
    """
    pending = state.get("pending_interrupt")
    if not pending:
        return {"pending_interrupt": None}

    answer = interrupt(pending)
    # resume 시 answer로 들어온 사용자 응답을 처리
    content = json.dumps(
        {"approval_result": answer, "original_request": pending},
        ensure_ascii=False,
    )
    return {
        "messages": [ToolMessage(content=content, tool_call_id="hitl")],
        "pending_interrupt": None,
    }


def _finalize_node(state: AnnotatorState) -> AnnotatorState:
    """[Flow: Step 1 (선택된 target과 메시지 확인) -> Step 2 (최종 결과 요약)
          -> Step 3 (final_annotations 및 상태 설정)]

    에이전트의 마지막 노드. 선택된 주석 대상을 바탕으로 최종 결과를 생성한다.
    """
    targets = state.get("selected_targets", [])
    recovery_notes = state.get("recovery_notes", [])
    if not targets:
        recovery_notes.append("No elements were selected for annotation.")

    # TODO: selected_targets를 build_embedpdf_annotations()로 변환하여 Storage 업로드
    final_annotations = [
        {
            "page_no": t.page_no,
            "bbox_pdf": t.bbox_pdf,
            "comment": t.comment,
            "color": t.color,
            "callout_color": t.callout_color,
            "opacity": t.opacity,
        }
        for t in targets
    ]

    summary = f"Created {len(targets)} annotation(s)."
    return {
        "messages": [AIMessage(content=summary)],
        "status": "done",
        "final_annotations": final_annotations,
        "recovery_notes": recovery_notes,
    }


def build_annotator_graph(
    llm: Any,
    checkpointer: Any = None,
    text_searcher: Any = None,
) -> Any:
    """[Flow: Step 1 (LLM 인스턴스 및 text_searcher 수신) -> Step 2 (StateGraph 정의)
          -> Step 3 (노드/엣지 연결) -> Step 4 (체크포인터로 컴파일)]

    PDF AI 주석 에이전트 그래프를 생성한다.

    Args:
        llm: LangChain chat model 인스턴스 (build_agent_llm로 생성하거나 테스트용 FakeChatModel).
        checkpointer: LangGraph checkpointer. None이면 InMemorySaver를 사용한다.
        text_searcher: TextLayerSearcher 인스턴스. None이면 search_text tool은 elements 기반 검색만 수행한다.

    Returns:
        compile()된 StateGraph.
    """
    if checkpointer is None:
        from langgraph.checkpoint.memory import InMemorySaver
        checkpointer = InMemorySaver()

    builder = StateGraph(AnnotatorState)
    builder.add_node("plan", _plan_node)
    builder.add_node("agent", lambda state: _agent_node(state, llm))
    builder.add_node("execute", lambda state: _execute_node(state, text_searcher))
    builder.add_node("hitl", _hitl_node)
    builder.add_node("finalize", _finalize_node)

    builder.add_edge(START, "plan")
    builder.add_edge("plan", "agent")
    builder.add_conditional_edges(
        "agent",
        _route_after_agent,
        {"execute": "execute", "finalize": "finalize"},
    )
    builder.add_conditional_edges(
        "execute",
        _route_after_execute,
        {"hitl": "hitl", "agent": "agent", "finalize": "finalize"},
    )
    builder.add_edge("hitl", "agent")
    builder.add_edge("finalize", END)

    return builder.compile(checkpointer=checkpointer)


async def run_annotator_agent(
    job_id: str,
    instruction: str,
    mode: str,
    comment_mode: str,
    page_range: list[int] | None,
    language: str,
    endpoint: str,
    model: str,
    api_key: str | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """PDF AI 주석 에이전트를 실행한다.

    Returns:
        run_agent_graph와 동일한 형식의 결과.
    """
    from .agent_engine import run_agent_graph

    # [Flow: Step 1 (job_id로 PDF/이미지에서 elements 및 pdf_bytes 추출) -> Step 2 (page_range 필터링)
    #       -> Step 3 (TextLayerSearcher 생성) -> Step 4 (에이전트 state에 주입 및 그래프 실행)]
    # NOTE: pdf_annotate_converter는 PyMuPDF/OCR/SQLAlchemy 등 무거운 의존성을 가지므로 함수 내부에서 lazy import한다.
    from .pdf_annotate_converter import collect_elements_for_agent
    from .pdf_text_layer import TextLayerSearcher

    try:
        elements, pdf_bytes = collect_elements_for_agent(job_id, page_range=page_range)
    except Exception as exc:
        logger.exception("[run_annotator_agent] elements 추출 실패")
        return {"status": "error", "error": f"elements 추출 실패: {exc}", "result": None}

    text_searcher = None
    if pdf_bytes:
        text_searcher = TextLayerSearcher(pdf_bytes)

    llm = build_agent_llm(endpoint, model, api_key)
    graph = build_annotator_graph(llm, get_async_redis_checkpointer(), text_searcher)
    await setup_redis_checkpointer(get_async_redis_checkpointer())

    try:
        inputs: AnnotatorState = {
            "messages": [],
            "job_id": job_id,
            "instruction": instruction,
            "mode": mode,
            "comment_mode": comment_mode,
            "page_range": page_range,
            "language": language,
            "elements": elements,
            "selected_targets": [],
            "pending_removals": [],
            "recovery_notes": [],
            "status": "running",
            "final_annotations": None,
            "pending_interrupt": None,
            "error": "",
        }
        result = await run_agent_graph(graph, inputs, thread_id)

        # [Flow: Step 1 (agent가 선택한 selected_targets 확인) -> Step 2 (pdf_bytes 기준으로 EmbedPDF AnnotationTransferItem 생성)
        #       -> Step 3 (final_annotations에 JSON 결과 저장)]
        if result.get("status") == "done" and pdf_bytes:
            from .pdf_annotator import build_embedpdf_annotations

            raw_targets = (result.get("result") or {}).get("final_annotations") or []
            targets = []
            for t in raw_targets:
                try:
                    targets.append(
                        AnnotationTarget(
                            page_no=int(t["page_no"]),
                            bbox_pdf=tuple(t["bbox_pdf"]),
                            comment=t.get("comment", ""),
                            color=tuple(t["color"]) if t.get("color") else (1.0, 0.92, 0.3),
                            callout_color=tuple(t["callout_color"]) if t.get("callout_color") else None,
                            opacity=t.get("opacity"),
                        )
                    )
                except Exception as te:
                    logger.warning(f"[run_annotator_agent] target 변환 실패: {te} (target={t})")
            if targets:
                page_elements_bboxes: dict[int, list[tuple[float, float, float, float]]] = {}
                for el in elements:
                    page_elements_bboxes.setdefault(el.get("page_no", 1), []).append(el.get("bbox_pdf", (0, 0, 0, 0)))
                try:
                    annotations = build_embedpdf_annotations(
                        pdf_bytes, targets, mode, page_elements_bboxes=page_elements_bboxes
                    )
                    result["result"]["final_annotations"] = annotations
                except Exception as be:
                    logger.exception("[run_annotator_agent] build_embedpdf_annotations 실패")
                    result["result"]["final_annotations"] = raw_targets
            else:
                result["result"]["final_annotations"] = []
        return result
    finally:
        if text_searcher is not None:
            text_searcher.close()
