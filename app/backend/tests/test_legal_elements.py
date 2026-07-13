#!/usr/bin/env python3
# [Flow: Step 1 (legal_elements 모듈 import) -> Step 2 (주장-증거 관계 파싱/추출 단위 테스트)
#       -> Step 3 (Mock LLM 응답) -> Step 4 (스키마 검증)]
# legal_elements 모듈의 주장(Claim) 추출, 주장-증거 관계 분석, 매핑 파싱을 검증한다.
import os
import sys
from unittest.mock import patch

# [Flow: backend 패키지 루트를 sys.path에 추가]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

from backend.core import legal_elements


def test_build_legal_elements_prompt_uses_claim_terminology():
    """프롬프트가 '주장' 용어를 사용하고 관계 기록 가이드를 포함해야 한다."""
    prompt = legal_elements._build_legal_elements_prompt("사기죄")
    assert "주장" in prompt
    assert "증거" in prompt
    assert "관계" in prompt or "reason" in prompt


def test_parse_legal_elements_preserves_evidence_reason():
    """매핑된 증거의 reason 필드를 파싱/보존한다."""
    content = """{
        "claim_type": "사기죄",
        "elements": [
            {
                "id": "claim_1",
                "name": "기망행위",
                "description": "피고의 기망행위",
                "mapped_evidence": [
                    {"evidence_id": "ev_1", "text_snippet": "증거1", "source_doc": "P.5", "reason": "거짓말이 기망행위에 해당"}
                ]
            }
        ]
    }"""
    result = legal_elements._parse_legal_elements(content, "사기죄")
    assert result["claim_type"] == "사기죄"
    assert len(result["elements"]) == 1
    mapped = result["elements"][0]["mapped_evidence"]
    assert len(mapped) == 1
    assert mapped[0]["reason"] == "거짓말이 기망행위에 해당"


def test_extract_legal_elements_analyzes_relationships():
    """extract_legal_elements가 evidence_nodes가 주어지면 주장-증거 관계를 분석한다."""
    evidence_nodes = [
        {"id": "ev_1", "data": {"label": "피고의 거짓 진술", "page": 5}},
        {"id": "ev_2", "data": {"label": "원고의 송금 내역", "page": 10}},
    ]
    claim_response = """{
        "claim_type": "사기죄",
        "elements": [
            {
                "id": "claim_1",
                "name": "기망행위",
                "description": "피고가 거짓말로 원고를 현혹"
            }
        ]
    }"""
    relation_response = """{
        "relations": [
            {
                "claim_id": "claim_1",
                "evidence_id": "ev_1",
                "reason": "기망행위의 직접 증거"
            }
        ]
    }"""

    with patch("backend.core.legal_elements.call_text") as mock_call:
        mock_call.side_effect = [(claim_response, None), (relation_response, None)]
        result = legal_elements.extract_legal_elements(
            "사기죄",
            "http://test",
            "model",
            "key",
            evidence_nodes=evidence_nodes,
        )

    assert len(result["elements"]) == 1
    mapped = result["elements"][0]["mapped_evidence"]
    assert len(mapped) == 1
    assert mapped[0]["evidence_id"] == "ev_1"
    assert mapped[0]["text_snippet"] == "피고의 거짓 진술"
    assert mapped[0]["source_doc"] == "P.5"
    assert mapped[0]["reason"] == "기망행위의 직접 증거"


def test_compute_overall_progress_with_reason():
    """reason 필드가 있어도 progress 계산이 정상 동작한다."""
    mappings = {
        "elements": [
            {"id": "c1", "mapped_evidence": [{"evidence_id": "e1", "reason": "r1"}]},
            {"id": "c2", "mapped_evidence": []},
        ]
    }
    assert legal_elements.compute_overall_progress(mappings) == 50
