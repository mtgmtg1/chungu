#!/usr/bin/env python3
# [Flow: Step 1 (인증된 사용자 및 요청 검증) -> Step 2 (LLM 스트리밍 시작) -> Step 3 (Vercel AI SDK data protocol 형식으로 토큰 반환)]
# 마크다운 에디터의 선택 텍스트를 AI로 처리하는 API 엔드포인트.
import json
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...auth.api_key_auth import require_api_key_or_session
from ...auth.supabase_auth import CurrentUser
from ...core.ai_client import stream_ai_text
from ...db.models import ApiKey

router = APIRouter(prefix="/ai", tags=["ai"])


class GenerateRequest(BaseModel):
    """/ai/generate 요청 본문."""

    prompt: str = Field(..., min_length=1, description="선택된 마크다운 텍스트")
    option: str = Field(
        ...,
        pattern="^(improve|fix|shorter|longer|continue|zap)$",
        description="AI 명령",
    )
    command: str | None = Field(None, description="zap(커스텀) 명령일 때 사용자 지시")


async def _token_stream(prompt: str, option: str, command: str | None) -> None:
    """LLM 스트리밍 토큰을 Vercel AI SDK data protocol 라인으로 변환하여 반환한다.

    프론트의 `useCompletion`은 기본적으로 "data" protocol을 사용하며,
    텍스트 chunk는 `0: <JSON 문자열>\n` 형식으로 전달해야 한다.
    OpenAI SSE 형식(`data: {...}`)과 혼동하지 않도록 주의한다.

    Args:
        prompt: 선택된 마크다운 텍스트.
        option: AI 명령.
        command: zap 명령 시 추가 지시.

    Yields:
        Vercel AI SDK data protocol 포맷의 텍스트 라인.
    """
    async for token in stream_ai_text(option, prompt, command):
        yield f"0: {json.dumps(token, ensure_ascii=False)}\n"


@router.post("/generate")
async def generate(
    body: GenerateRequest,
    auth: tuple[CurrentUser, ApiKey | None] = Depends(require_api_key_or_session),
):
    """선택된 마크다운 텍스트를 AI로 스트리밍 처리한다.

    Args:
        body: AI 처리 요청 본문.
        auth: 인증된 사용자와 API key (선택).

    Returns:
        Vercel AI SDK data protocol 형식의 StreamingResponse.
    """
    user, api_key = auth

    if api_key:
        # API key 사용 시 rate limit/할당량 처리는 향후 추가
        pass

    return StreamingResponse(
        _token_stream(body.prompt, body.option, body.command),
        media_type="text/plain; charset=utf-8",
    )
