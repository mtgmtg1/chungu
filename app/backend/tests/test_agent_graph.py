# [Flow: Step 1 (Mock LLM endpoint 설정) -> Step 2 (annotator/editor graph 생성) -> Step 3 (graph 실행)
#       -> Step 4 (add_highlight/replace_selection tool 결과 검증) -> Step 5 (HITL interrupt/resume 흐름 검증)]
import json

import pytest
import respx
from httpx import Response
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from backend.core.agent_annotator import AnnotationTarget, build_annotator_graph
from backend.core.agent_editor import build_editor_graph
from backend.core.agent_engine import get_agent_status, resume_agent_graph, run_agent_graph
from backend.core.agent_llm import build_agent_llm, parse_tool_calls_from_content


@pytest.fixture
def mock_llm():
    """[Flow: Step 1 (base_url를 localhost:18080/v1로 설정) -> Step 2 (api_key 더미 설정)]"""
    return build_agent_llm("http://localhost:18080/v1", "test-model")


def _tool_call(name: str, args: dict) -> dict:
    """[Flow: Step 1 (도구 이름과 인자 수신) -> Step 2 (OpenAI tool_calls 형식으로 변환)]"""
    return {
        "id": f"call-{name}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def test_parse_tool_calls_from_content():
    """[Flow: Step 1 (content에 call:tool_name{args} 형식이 있고 tool_calls args가 비어 있는 AIMessage 생성)
          -> Step 2 (parse_tool_calls_from_content 호출) -> Step 3 (병합된 args 검증)]"""
    message = AIMessage(
        content="call:replace_selection{new_text:Hello}",
        tool_calls=[{"id": "call-1", "name": "replace_selection", "args": {}, "type": "tool_call"}],
    )
    parsed = parse_tool_calls_from_content(message)
    assert len(parsed.tool_calls) == 1
    assert parsed.tool_calls[0]["name"] == "replace_selection"
    assert parsed.tool_calls[0]["args"] == {"new_text": "Hello"}


def test_parse_tool_calls_from_content_json_array():
    """[Flow: Step 1 (content에 JSON array tool call 형식이 있는 AIMessage 생성)
          -> Step 2 (parse_tool_calls_from_content 호출) -> Step 3 (args 검증)]"""
    message = AIMessage(content='[{"name": "replace_selection", "parameters": {"new_text": "Hello"}}]', tool_calls=[])
    parsed = parse_tool_calls_from_content(message)
    assert len(parsed.tool_calls) == 1
    assert parsed.tool_calls[0]["name"] == "replace_selection"
    assert parsed.tool_calls[0]["args"] == {"new_text": "Hello"}


def test_parse_tool_calls_from_content_no_fallback():
    """[Flow: Step 1 (content에 call: 패턴이 없는 AIMessage 생성)
          -> Step 2 (parse_tool_calls_from_content 호출) -> Step 3 (원본 메시지 그대로 반환 확인)]"""
    message = AIMessage(content="Just a summary.", tool_calls=[])
    parsed = parse_tool_calls_from_content(message)
    assert parsed.tool_calls == []
    assert parsed.content == "Just a summary."


def _chat_response(tool_calls: list[dict] | None = None, content: str = "") -> dict:
    """[Flow: Step 1 (tool_calls 또는 content 수신) -> Step 2 (chat.completion JSON 생성)]"""
    message: dict = {"role": "assistant", "content": content}
    finish_reason = "stop"
    if tool_calls:
        message["tool_calls"] = tool_calls
        finish_reason = "tool_calls"
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1,
        "model": "test-model",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
    }


@pytest.mark.asyncio
async def test_editor_replace_selection(mock_llm):
    """[Flow: Step 1 (replace_selection tool 호출) -> Step 2 (edits에 old_text 기록)
          -> Step 3 (finalize에서 final_markdown에 적용) -> Step 4 (결과 검증)]"""
    graph = build_editor_graph(mock_llm, InMemorySaver())
    inputs = {
        "messages": [],
        "instruction": "replace hello",
        "option": "zap",
        "command": None,
        "full_markdown": "hello world",
        "selected_markdown": "hello",
        "edits": [],
        "questions": [],
        "final_markdown": None,
        "status": "running",
        "pending_interrupt": None,
        "error": "",
    }

    with respx.mock(assert_all_mocked=False) as routes:
        route = routes.post("http://localhost:18080/v1/chat/completions")
        route.side_effect = [
            Response(200, json=_chat_response([_tool_call("replace_selection", {"new_text": "replaced"})])),
            Response(200, json=_chat_response(content="Done")),
        ]
        result = await run_agent_graph(graph, inputs, "test-editor-replace")

    assert result["status"] == "done"
    final_state = result["result"]
    assert final_state["final_markdown"] == "replaced world"
    assert len(final_state["edits"]) == 1
    assert final_state["edits"][0]["type"] == "replace"
    assert final_state["edits"][0]["old_text"] == "hello"
    assert final_state["edits"][0]["content"] == "replaced"


@pytest.mark.asyncio
async def test_annotator_add_highlight(mock_llm):
    """[Flow: Step 1 (add_highlight tool 호출) -> Step 2 (state["elements"]에서 bbox_pdf 조회)
          -> Step 3 (AnnotationTarget 생성) -> Step 4 (finalize에서 final_annotations dict 목록 반환)]"""
    graph = build_annotator_graph(mock_llm, InMemorySaver())
    inputs = {
        "messages": [],
        "job_id": "job-1",
        "instruction": "highlight hello",
        "mode": "highlight",
        "comment_mode": "user_text",
        "page_range": [1],
        "language": "en",
        "elements": [
            {"page_no": 1, "bbox_pdf": [10.0, 10.0, 100.0, 50.0], "text": "hello world"}
        ],
        "selected_targets": [],
        "pending_removals": [],
        "recovery_notes": [],
        "status": "running",
        "final_annotations": None,
        "pending_interrupt": None,
        "error": "",
    }

    with respx.mock(assert_all_mocked=False) as routes:
        route = routes.post("http://localhost:18080/v1/chat/completions")
        route.side_effect = [
            Response(
                200,
                json=_chat_response(
                    [_tool_call("add_highlight", {"element_index": 0, "comment": "important", "color": "yellow"})]
                ),
            ),
            Response(200, json=_chat_response(content="Done")),
        ]
        result = await run_agent_graph(graph, inputs, "test-annotator-highlight")

    assert result["status"] == "done"
    final_state = result["result"]
    targets = final_state["selected_targets"]
    assert len(targets) == 1
    assert isinstance(targets[0], AnnotationTarget)
    assert targets[0].page_no == 1
    assert targets[0].comment == "important"
    assert targets[0].bbox_pdf == (10.0, 10.0, 100.0, 50.0)


@pytest.mark.asyncio
async def test_editor_hitl_resume(mock_llm):
    """[Flow: Step 1 (ask_user tool 호출) -> Step 2 (run_agent_graph가 interrupted 반환)
          -> Step 3 (get_agent_status로 체크포인터 상태 확인) -> Step 4 (resume_agent_graph로 재개)
          -> Step 5 (done 상태 확인)]"""
    graph = build_editor_graph(mock_llm, InMemorySaver())
    inputs = {
        "messages": [],
        "instruction": "ask user",
        "option": "zap",
        "command": None,
        "full_markdown": "hello world",
        "selected_markdown": "hello",
        "edits": [],
        "questions": [],
        "final_markdown": None,
        "status": "running",
        "pending_interrupt": None,
        "error": "",
    }

    with respx.mock(assert_all_mocked=False) as routes:
        route = routes.post("http://localhost:18080/v1/chat/completions")
        route.side_effect = [
            Response(
                200,
                json=_chat_response(
                    [_tool_call("ask_user", {"question": "OK?", "options": ["yes", "no"]})]
                ),
            ),
            Response(200, json=_chat_response(content="Done")),
        ]
        result = await run_agent_graph(graph, inputs, "test-editor-hitl")

        assert result["status"] == "interrupted"
        assert result["pending_interrupt"]["question"] == "OK?"

        status = await get_agent_status(graph, result["thread_id"])
        assert status["status"] == "interrupted"
        assert status["pending_interrupt"]["question"] == "OK?"

        resumed = await resume_agent_graph(graph, {"approved": True, "value": "yes"}, result["thread_id"])
        assert resumed["status"] == "done"
