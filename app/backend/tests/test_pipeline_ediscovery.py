#!/usr/bin/env python3
"""[Flow: Step 1 (필요한 helper import) -> Step 2 (자동 파라미터 추천 관련 단위 테스트)
      -> Step 3 (경계값/파싱 오류 케이스 검증)]

e-Discovery 파이프라인의 LLM 자동 파라미터 추천 헬퍼 함수들을 검증한다.
DB나 외부 API를 필요로 하지 않는 순수 helper 위주로 테스트한다.
"""
import sys
import os

# [Flow: backend 패키지 루트를 sys.path에 추가]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

from unittest.mock import patch

from backend.core.pipeline_ediscovery import (
    _parse_param_suggestion,
    _clamp_suggested_params,
    _suggest_params,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_THRESHOLD,
)


def test_parse_param_suggestion_valid_json():
    """정상 JSON 응답에서 4개 필드를 모두 파싱한다."""
    content = """
    ```json
    {
      "chunk_size": 1024,
      "threshold": 0.55,
      "max_docs": 120,
      "reasoning": "복잡한 사실관계"
    }
    ```
    """
    result = _parse_param_suggestion(content)
    assert result["chunk_size"] == 1024
    assert result["threshold"] == 0.55
    assert result["max_docs"] == 120
    assert result["reasoning"] == "복잡한 사실관계"


def test_parse_param_suggestion_no_fence():
    """JSON 펜스 없이 순수 JSON만 오는 경우도 파싱한다."""
    content = '{"chunk_size": 512, "threshold": 0.4, "max_docs": 50}'
    result = _parse_param_suggestion(content)
    assert result["chunk_size"] == 512
    assert result["threshold"] == 0.4
    assert result["max_docs"] == 50
    assert result["reasoning"] == ""


def test_parse_param_suggestion_invalid_json():
    """JSON 파싱에 실패하면 빈 dict를 반환한다."""
    result = _parse_param_suggestion("이것은 JSON이 아님")
    assert result == {}


def test_parse_param_suggestion_partial_fields():
    """일부 필드만 있어도 나머지는 기본값으로 채워 반환한다."""
    content = '{"chunk_size": 300}'
    result = _parse_param_suggestion(content)
    assert result["chunk_size"] == 300
    assert result["threshold"] == DEFAULT_THRESHOLD
    assert result["max_docs"] is None
    assert result["reasoning"] == ""


def test_clamp_suggested_params_rounds_chunk_to_128():
    """chunk_size는 128 단위로 반올림되고 256~4096 범위로 clamp된다."""
    suggested = {"chunk_size": 1234, "threshold": 0.5, "max_docs": 100, "reasoning": "test"}
    result = _clamp_suggested_params(suggested, total_pages=200)
    assert result["chunk_size"] == 1152  # 128 * 9
    assert result["threshold"] == 0.5
    assert result["max_docs"] == 100


def test_clamp_suggested_params_chunk_bounds():
    """chunk_size가 범위를 벗어나면 경계값으로 clamp된다."""
    low = _clamp_suggested_params({"chunk_size": 100}, total_pages=10)
    assert low["chunk_size"] == 256
    high = _clamp_suggested_params({"chunk_size": 10000}, total_pages=10)
    assert high["chunk_size"] == 4096


def test_clamp_suggested_params_threshold_bounds():
    """threshold는 0.3~0.7 범위로 clamp된다."""
    low = _clamp_suggested_params({"threshold": 0.1}, total_pages=10)
    assert low["threshold"] == 0.3
    high = _clamp_suggested_params({"threshold": 0.9}, total_pages=10)
    assert high["threshold"] == 0.7


def test_clamp_suggested_params_max_docs_defaults_to_total_pages():
    """max_docs가 None이면 전체 페이지 수를 사용한다."""
    result = _clamp_suggested_params({}, total_pages=42)
    assert result["max_docs"] == 42


def test_clamp_suggested_params_max_docs_capped_by_total_pages():
    """max_docs는 전체 페이지 수를 초과할 수 없다."""
    result = _clamp_suggested_params({"max_docs": 9999}, total_pages=30)
    assert result["max_docs"] == 30


def test_clamp_suggested_params_max_docs_capped_at_5000():
    """max_docs는 5000을 초과할 수 없다."""
    result = _clamp_suggested_params({"max_docs": 99999}, total_pages=6000)
    assert result["max_docs"] == 5000


def test_suggest_params_uses_llm_response():
    """_suggest_params는 call_text 응답을 파싱해 clamp된 파라미터를 반환한다."""
    page_texts = {1: "원고 A는 2023년 4월 5일에 계약을 체결했다.", 2: "피고 B는 2023년 4월 6일에 대금을 지급하지 않았다."}
    with patch("backend.core.pipeline_ediscovery.call_text") as mock_call:
        mock_call.return_value = (
            '{"chunk_size": 1024, "threshold": 0.5, "max_docs": 2, "reasoning": "단순 문서"}',
            None,
        )
        result = _suggest_params(page_texts, endpoint="http://test", model="model", api_key="key")
    assert result["chunk_size"] == 1024
    assert result["threshold"] == 0.5
    assert result["max_docs"] == 2
    assert result["reasoning"] == "단순 문서"


def test_suggest_params_falls_back_on_llm_error():
    """call_text가 예외를 던지면 안전한 기본값으로 fallback한다."""
    page_texts = {1: "원고 A는 계약 위반을 주장한다."}
    with patch("backend.core.pipeline_ediscovery.call_text") as mock_call:
        mock_call.side_effect = RuntimeError("LLM unavailable")
        result = _suggest_params(page_texts, endpoint="http://test", model="model", api_key="key")
    assert 256 <= result["chunk_size"] <= 4096
    assert 0.3 <= result["threshold"] <= 0.7
    assert result["max_docs"] == 1
