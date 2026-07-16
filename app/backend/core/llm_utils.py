#!/usr/bin/env python3
# [Flow: Step 1 (모델 이름이 Gemma-4 계열인지 확인) -> Step 2 (해당 경우 thinking 활성화 + 256 토큰 예산 제한) -> Step 3 (payload 반환)]
# Gemma-4 모델 추론 시 vLLM/chat_template_kwargs에 필요한 공통 처리.


GEMMA4_THINKING_BUDGET = 256


def is_gemma4(model: str) -> bool:
    """모델 이름이 Gemma-4 계열인지 확인한다."""
    return "gemma-4" in (model or "").lower()


def with_gemma4_kwargs(payload: dict, model: str) -> dict:
    """Gemma-4 모델일 경우 enable_thinking=True와 thinking_token_budget=256을 추가한다."""
    if is_gemma4(model):
        payload.setdefault("chat_template_kwargs", {})
        payload["chat_template_kwargs"]["enable_thinking"] = True
        payload["thinking_token_budget"] = GEMMA4_THINKING_BUDGET
    return payload
