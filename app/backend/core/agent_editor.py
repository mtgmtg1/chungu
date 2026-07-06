#!/usr/bin/env python3
# [Flow: Step 1 (사용자 지시와 마크다운 문서 수신) -> Step 2 (LLM이 문서 구조 분석)
#       -> Step 3 (도구 반복 호출: 섹션/표 조회, 텍스트 교체/삽입, 질문)
#       -> Step 4 (중간 검토 및 사용자 승인) -> Step 5 (최종 마크다운 diff 생성)]
# 마크다운 에디터의 멀티스텝 AI 에이전트. LangGraph StateGraph 기반으로,
# 문서 구조 개선, 섹션 교차 검증, 장문 생성/편집을 반복 추론으로 처리한다.
import json
import logging
from typing import Annotated, Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from .agent_engine import get_async_redis_checkpointer, setup_redis_checkpointer
from .agent_llm import build_agent_llm

logger = logging.getLogger(__name__)


class EditorState(TypedDict, total=False):
    """마크다운 에디터 AI 에이전트의 상태."""

    messages: Annotated[list[BaseMessage], add_messages]
    instruction: str
    option: str
    command: str | None
    full_markdown: str
    selected_markdown: str
    edits: list[dict]  # {type: "replace" | "insert", range: {...}, content: str}
    questions: list[dict]
    final_markdown: str | None
    status: str
    pending_interrupt: Any
    error: str


@tool
def get_section(heading: str) -> str:
    """마크다운에서 지정한 제목의 섹션을 추출한다.

    Args:
        heading: 찾을 섹션 제목.

    Returns:
        섹션 내용 문자열.
    """
    # TODO: 실제 마크다운 파싱 연동
    return json.dumps({"heading": heading, "content": ""}, ensure_ascii=False)


@tool
def get_table(table_index: int) -> str:
    """마크다운에서 N번째 표를 추출한다.

    Args:
        table_index: 0-based 표 인덱스.

    Returns:
        표 내용 JSON 문자열.
    """
    # TODO: 실제 마크다운 파싱 연동
    return json.dumps({"table_index": table_index, "rows": []}, ensure_ascii=False)


@tool
def replace_selection(new_text: str) -> str:
    """사용자가 선택한 텍스트를 새로운 마크다운으로 교체한다.

    Args:
        new_text: 교체할 마크다운 문자열.

    Returns:
        교체 결과 JSON 문자열.
    """
    # TODO: EditorState.edits에 추가
    return json.dumps({"ok": True, "action": "replace_selection", "new_text": new_text}, ensure_ascii=False)


@tool
def insert_at(position: str, new_text: str) -> str:
    """지정한 위치에 마크다운을 삽입한다.

    Args:
        position: "cursor" | "end" | "beginning" | heading 제목.
        new_text: 삽입할 마크다운 문자열.

    Returns:
        삽입 결과 JSON 문자열.
    """
    # TODO: EditorState.edits에 추가
    return json.dumps({"ok": True, "action": "insert_at", "position": position, "new_text": new_text}, ensure_ascii=False)


@tool
def ask_user(question: str, options: list[str] | None = None) -> str:
    """사용자에게 질문을 던지거나 승인을 요청한다.

    Args:
        question: 사용자에게 표시할 질문/요청.
        options: 선택 가능한 옵션. None이면 자유 입력.

    Returns:
        승인/질문 요청 플래그. _execute_node에서 이를 감지해 interrupt를 발생시킨다.
    """
    return json.dumps({"requires_approval": True, "question": question, "options": options}, ensure_ascii=False)


TOOLS = [
    get_section,
    get_table,
    replace_selection,
    insert_at,
    ask_user,
]


PLAN_SYSTEM_PROMPT = """You are an AI writing assistant for a markdown editor. You can analyze the document structure, read sections and tables, and propose edits.

You have access to these tools:
- get_section: extract a section by heading.
- get_table: extract a table by index.
- replace_selection: replace the user's selected text with new markdown.
- insert_at: insert markdown at cursor, end, beginning, or a specific heading.
- ask_user: ask a clarifying question or request approval.

Workflow:
1. Analyze the user's request and the document context.
2. If needed, read relevant sections or tables.
3. Propose edits using replace_selection and insert_at.
4. For large changes or ambiguous instructions, ask the user for approval.
5. Finish with a concise summary of the changes.

Rules:
- For simple fixes (grammar, shorter, longer, small rewrites), proceed autonomously.
- For structural changes, large additions, or deletions, ask the user first.
- Always respond in Markdown.
"""


def _plan_node(state: EditorState) -> EditorState:
    """에이전트의 첫 번째 노드. 사용자 지시를 분석해 작업 계획을 세운다."""
    messages = state.get("messages", [])
    if not messages:
        instruction = state.get("instruction", "")
        option = state.get("option", "")
        command = state.get("command")
        prompt = f"User request option: {option}\n"
        if command:
            prompt += f"Custom command: {command}\n"
        prompt += f"User instruction/text: {instruction}\n\nPlease create a step-by-step plan."
        messages = [
            SystemMessage(content=PLAN_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]
    return {"messages": messages}


def _agent_node(state: EditorState, llm) -> EditorState:
    """ReAct 스타일 추론 노드. LLM이 도구를 호출하거나 최종 답변을 생성한다."""
    messages = state.get("messages", [])
    model = llm.bind_tools(TOOLS)
    response = model.invoke(messages)
    return {"messages": [response]}


def _execute_node(state: EditorState) -> EditorState:
    """LLM이 요청한 도구를 실행하고 결과를 메시지로 추가한다.
    get_section/get_table/replace_selection/insert_at은 state의 full_markdown 기반으로 처리되고,
    ask_user 등 승인이 필요한 도구는 pending_interrupt에 저장한다."""
    messages = state.get("messages", [])
    last_message = messages[-1] if messages else None
    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return {"messages": []}

    tool_map = {t.name: t for t in TOOLS}
    tool_messages: list[ToolMessage] = []
    pending_interrupt: dict | None = None
    edits: list[dict] = list(state.get("edits", []))
    full_markdown: str = state.get("full_markdown", "")

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
            if name == "get_section":
                result = _do_get_section(full_markdown, args.get("heading", ""))
            elif name == "get_table":
                result = _do_get_table(full_markdown, args.get("table_index", 0))
            elif name in ("replace_selection", "insert_at"):
                result = tool_map[name].invoke(args)
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
        elif name == "replace_selection":
            edits.append({"type": "replace", "content": parsed.get("new_text", "")})
        elif name == "insert_at":
            edits.append({
                "type": "insert",
                "position": parsed.get("position", "cursor"),
                "content": parsed.get("new_text", ""),
            })

    updates: EditorState = {"messages": tool_messages}
    if edits:
        updates["edits"] = edits
    if pending_interrupt:
        updates["pending_interrupt"] = pending_interrupt
    return updates


def _do_get_section(markdown: str, heading: str) -> str:
    """마크다운에서 지정한 제목의 섹션을 추출한다."""
    import re

    if not heading:
        return json.dumps({"heading": heading, "content": ""}, ensure_ascii=False)
    pattern = re.compile(
        rf"(^|\n)(#+\s*{re.escape(heading)}\s*\n)(.*?)(?=\n#+\s|\Z)",
        re.DOTALL,
    )
    match = pattern.search(markdown)
    content = match.group(3) if match else ""
    return json.dumps({"heading": heading, "content": content.strip()}, ensure_ascii=False)


def _do_get_table(markdown: str, table_index: int) -> str:
    """마크다운에서 N번째 표를 추출한다."""
    import re

    table_pattern = re.compile(r"((?:\|[^\n]*\|\n)+)(?:\|[-:\s|]+\|\n)((?:\|[^\n]*\|\n?)+)")
    matches = list(table_pattern.finditer(markdown))
    if table_index < 0 or table_index >= len(matches):
        return json.dumps({"table_index": table_index, "rows": []}, ensure_ascii=False)
    match = matches[table_index]
    table_text = match.group(0)
    return json.dumps({"table_index": table_index, "markdown": table_text}, ensure_ascii=False)


def _route_after_agent(state: EditorState) -> str:
    """agent 노드 이후: tool call이 있으면 execute, 없으면 finalize."""
    messages = state.get("messages", [])
    last_message = messages[-1] if messages else None
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "execute"
    return "finalize"


def _route_after_execute(state: EditorState) -> str:
    """execute 노드 이후: 승인 요청이 있으면 hitl, 추가 tool call이 있으면 agent, 없으면 finalize."""
    if state.get("pending_interrupt"):
        return "hitl"
    messages = state.get("messages", [])
    last_message = messages[-1] if messages else None
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "execute"
    return "finalize"


def _hitl_node(state: EditorState) -> EditorState:
    """human-in-the-loop 노드. 사용자의 승인/거절/응답을 interrupt로 받는다."""
    pending = state.get("pending_interrupt")
    if not pending:
        return {"pending_interrupt": None}

    answer = interrupt(pending)
    content = json.dumps(
        {"approval_result": answer, "original_request": pending},
        ensure_ascii=False,
    )
    return {
        "messages": [ToolMessage(content=content, tool_call_id="hitl")],
        "pending_interrupt": None,
    }


def _finalize_node(state: EditorState) -> EditorState:
    """에이전트의 마지막 노드. 적용된 edits를 바탕으로 최종 결과를 생성한다."""
    edits = state.get("edits", [])
    summary = f"Applied {len(edits)} edit(s)."
    return {
        "messages": [AIMessage(content=summary)],
        "status": "done",
        "final_markdown": state.get("full_markdown", ""),
    }


def build_editor_graph(
    endpoint: str,
    model: str,
    api_key: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> Any:
    """마크다운 에디터 AI 에이전트 그래프를 생성한다."""
    llm = build_agent_llm(
        endpoint=endpoint,
        model=model,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=True,
    )

    builder = StateGraph(EditorState)
    builder.add_node("plan", _plan_node)
    builder.add_node("agent", lambda state: _agent_node(state, llm))
    builder.add_node("execute", _execute_node)
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

    saver = get_async_redis_checkpointer()
    return builder.compile(checkpointer=saver)


async def run_editor_agent(
    instruction: str,
    option: str,
    command: str | None,
    full_markdown: str,
    selected_markdown: str,
    endpoint: str,
    model: str,
    api_key: str | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """마크다운 에디터 AI 에이전트를 실행한다."""
    from .agent_engine import run_agent_graph

    graph = build_editor_graph(endpoint, model, api_key)
    await setup_redis_checkpointer(get_async_redis_checkpointer())
    inputs: EditorState = {
        "messages": [],
        "instruction": instruction,
        "option": option,
        "command": command,
        "full_markdown": full_markdown,
        "selected_markdown": selected_markdown,
        "edits": [],
        "questions": [],
        "final_markdown": None,
        "status": "running",
        "pending_interrupt": None,
        "error": "",
    }
    return await run_agent_graph(graph, inputs, thread_id)
