#!/usr/bin/env python3
# [Flow: Step 1 (option에 따라 system/user 메시지 구성) -> Step 2 (OpenAI-compatible endpoint로 streaming POST) -> Step 3 (SSE chunk를 파싱하여 텍스트 토큰 yield) -> Step 4 (완료 시 generator 종료)]
# 마크다운 에디터의 선택 텍스트를 LLM으로 스트리밍 처리하는 클라이언트.
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from ..config import settings
from .llm_utils import with_gemma4_kwargs

logger = logging.getLogger(__name__)


def build_messages(option: str, prompt: str, command: str | None = None) -> list[dict[str, Any]]:
    """AI 명령(option)에 맞는 system/user 메시지 목록을 구성한다.

    Args:
        option: AI 명령 (improve, fix, shorter, longer, continue, zap).
        prompt: 사용자가 선택한 마크다운 텍스트.
        command: zap(custom) 명령일 때 사용자가 입력한 추가 지시.

    Returns:
        OpenAI chat messages 형식의 딕셔너리 목록.
    """
    base = "You are an AI writing assistant. Respond only in Markdown."

    system_by_option = {
        "improve": base + " Improve the writing quality of the given text while preserving its meaning.",
        "fix": base + " Fix grammar and spelling errors in the given text.",
        "shorter": base + " Make the given text shorter and more concise.",
        "longer": base + " Expand the given text with more details and explanation.",
        "continue": base + " Continue writing naturally from the given text. Limit to one or two sentences.",
        "zap": base + " Manipulate the given text according to the user's command.",
    }

    system = system_by_option.get(option, base)

    if option == "zap":
        user_content = f"Given this text:\n\n{prompt}\n\nCommand: {command or 'improve it'}"
    elif option == "continue":
        user_content = f"Continue writing from this text:\n\n{prompt}"
    else:
        user_content = f"{option.capitalize()} this text:\n\n{prompt}"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]


def _build_payload(model: str, messages: list[dict[str, Any]], temperature: float, max_tokens: int) -> dict[str, Any]:
    """OpenAI-compatible streaming chat completions 요청 페이로드를 구성한다."""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    return with_gemma4_kwargs(payload, model)


def _extract_token(line: str) -> str | None:
    """SSE data 라인에서 delta content 토큰을 추출한다.

    Args:
        line: SSE 한 줄 (예: 'data: {...}').

    Returns:
        추출된 텍스트 토큰. 완료/[DONE]이면 None.
    """
    if not line.startswith("data:"):
        return None

    data = line.removeprefix("data:").strip()
    if data == "[DONE]":
        return None

    try:
        chunk = json.loads(data)
    except json.JSONDecodeError:
        return None

    delta = chunk.get("choices", [{}])[0].get("delta", {})
    return delta.get("content")


async def stream_ai_text(
    option: str,
    prompt: str,
    command: str | None = None,
    endpoint: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> AsyncGenerator[str, None]:
    """선택된 마크다운 텍스트를 LLM으로 스트리밍 처리하여 토큰을 순차적으로 반환한다.

    Args:
        option: AI 명령.
        prompt: 선택된 마크다운 텍스트.
        command: zap 명령 시 사용자 지시.
        endpoint: OpenAI-compatible endpoint. 기본값은 settings.default_llm_endpoint.
        model: 사용할 모델 이름. 기본값은 settings.default_llm_model.
        api_key: API 키. 기본값은 settings.default_llm_api_key.
        temperature: 샘플링 온도.
        max_tokens: 최대 생성 토큰 수.

    Yields:
        생성된 텍스트 토큰 조각.
    """
    endpoint = endpoint or settings.default_llm_endpoint
    model = model or settings.default_llm_model
    api_key = api_key if api_key is not None else settings.default_llm_api_key

    messages = build_messages(option, prompt, command)
    url = f"{endpoint.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = _build_payload(model, messages, temperature, max_tokens)

    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                token = _extract_token(line)
                if token is None:
                    continue
                yield token
