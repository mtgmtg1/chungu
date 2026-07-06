#!/usr/bin/env python3
# [Flow: Step 1 (endpoint/model/api_key 수신) -> Step 2 (Gemma-4 모델일 경우 chat_template_kwargs 추가)
#       -> Step 3 (ChatOpenAI 인스턴스 생성) -> Step 4 (LLM 반환)]
# LangGraph/LangChain에서 OpenAI-compatible endpoint(vLLM/llama.cpp)를 사용하기 위한
# LLM 팩토리. Gemma-4 모델은 enable_thinking=false를 전달해 불필요한 추론 토큰을 줄인다.
import json
import re

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from .llm_utils import is_gemma4


def parse_tool_calls_from_content(message: AIMessage) -> AIMessage:
    """[Flow: Step 1 (content에서 call:tool_name{args} 패턴 추출)
          -> Step 2 (기존 tool_calls와 병합하여 누락된 args를 보강)
          -> Step 3 (보강된 tool_calls를 가진 새 AIMessage 반환)]

    Gemma-4 등 일부 모델은 OpenAI tool_calls 필드의 args를 비워두고,
    텍스트 내에 call:tool_name{args} 형식으로 인자를 삽입하는 경우가 있다.
    예: call:replace_selection{new_text:Hello}

    Args:
        message: LLM이 생성한 AIMessage. tool_calls가 있거나 없을 수 있다.

    Returns:
        content에서 추출한 인자를 병합한 AIMessage.
    """
    if not isinstance(message.content, str):
        return message

    parsed_calls: dict[str, dict] = {}

    # [Step 1] OpenAI tool_calls 형식이 있으면 병합 대상으로 사용한다.
    if message.tool_calls:
        for tc in message.tool_calls:
            parsed_calls[tc.get("name")] = {**parsed_calls.get(tc.get("name"), {}), **(tc.get("args") or {})}

    # [Step 2] JSON array 형식을 파싱한다. 예: [{"name": "replace_selection", "parameters": {"new_text": "Hello"}}]
    if not parsed_calls:
        try:
            parsed_json = json.loads(message.content)
            if isinstance(parsed_json, list):
                for item in parsed_json:
                    if isinstance(item, dict) and "name" in item:
                        name = item["name"]
                        args = item.get("parameters") or item.get("args") or {}
                        parsed_calls[name] = {**parsed_calls.get(name, {}), **args}
        except Exception:
            pass

    # [Step 3] call:tool_name{args} 형식을 파싱한다. 예: call:replace_selection{new_text:Hello}
    if "call:" in message.content:
        for match in re.finditer(r"call:(\w+)\{([^}]*)\}", message.content):
            name = match.group(1)
            args_str = match.group(2)
            try:
                args = json.loads("{" + args_str + "}") if args_str else {}
            except Exception:
                args = {}
                for key, value in re.findall(r"(\w+):([^,]+)", args_str):
                    args[key] = value.strip().strip('"').strip("'")
            parsed_calls[name] = {**parsed_calls.get(name, {}), **args}

    if not parsed_calls:
        return message

    existing_by_name: dict[str, dict] = {tc.get("name"): tc for tc in (message.tool_calls or [])}
    merged: list[dict] = []
    for name, args in parsed_calls.items():
        existing = existing_by_name.get(name, {})
        merged.append({
            "id": existing.get("id") or f"call-{name}",
            "name": name,
            "args": {**(existing.get("args") or {}), **args},
            "type": "tool_call",
        })
    for tc in (message.tool_calls or []):
        if tc.get("name") not in parsed_calls:
            merged.append(tc)

    return AIMessage(
        content=message.content,
        tool_calls=merged,
        additional_kwargs=message.additional_kwargs,
        id=message.id,
    )


def build_agent_llm(
    endpoint: str,
    model: str,
    api_key: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    streaming: bool = False,
    timeout: float = 300.0,
) -> ChatOpenAI:
    """OpenAI-compatible endpoint에 연결된 ChatOpenAI 인스턴스를 생성한다.

    Args:
        endpoint: OpenAI-compatible endpoint URL (예: http://192.168.1.69:18080/v1).
            base_url로 사용되며, trailing slash가 있어도 langchain이 처리한다.
        model: 사용할 모델 이름. vLLM proxy는 요청 model을 실제 모델로 재작성한다.
        api_key: API 키. endpoint가 인증을 요구하지 않으면 None 또는 빈 문자열.
        temperature: 샘플링 온도.
        max_tokens: 최대 생성 토큰 수.
        streaming: 스트리밍 활성화 여부.
        timeout: 요청 타임아웃(초).

    Returns:
        LangChain ChatOpenAI 인스턴스.
    """
    base_url = endpoint.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"

    extra_body: dict | None = None
    if is_gemma4(model):
        # vLLM이 chat_template_kwargs를 받을 수 있도록 OpenAI client의 extra_body를 통해 전달한다.
        # ChatOpenAI는 extra_body를 인자로 직접 받아 HTTP 요청 body에 추가 필드로 포함한다.
        extra_body = {"chat_template_kwargs": {"enable_thinking": False}}

    # OpenAI client는 빈 api_key를 허용하지 않으므로, 비어 있으면 더미 키를 사용한다.
    # vLLM/llama.cpp 등 인증이 없는 endpoint는 Authorization 헤더를 무시한다.
    effective_api_key = api_key if api_key else "not-needed"

    return ChatOpenAI(
        base_url=base_url,
        model=model,
        api_key=effective_api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=streaming,
        timeout=timeout,
        extra_body=extra_body,
    )
