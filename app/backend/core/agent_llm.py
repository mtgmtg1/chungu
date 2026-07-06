#!/usr/bin/env python3
# [Flow: Step 1 (endpoint/model/api_key 수신) -> Step 2 (Gemma-4 모델일 경우 chat_template_kwargs 추가)
#       -> Step 3 (ChatOpenAI 인스턴스 생성) -> Step 4 (LLM 반환)]
# LangGraph/LangChain에서 OpenAI-compatible endpoint(vLLM/llama.cpp)를 사용하기 위한
# LLM 팩토리. Gemma-4 모델은 enable_thinking=false를 전달해 불필요한 추론 토큰을 줄인다.
from langchain_openai import ChatOpenAI

from .llm_utils import is_gemma4


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

    model_kwargs: dict = {}
    if is_gemma4(model):
        # vLLM이 chat_template_kwargs를 받을 수 있도록 model_kwargs에 전달한다.
        # LangChain의 ChatOpenAI는 model_kwargs를 OpenAI client payload에 포함한다.
        model_kwargs["chat_template_kwargs"] = {"enable_thinking": False}

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
        model_kwargs=model_kwargs,
    )
