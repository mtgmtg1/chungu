#!/usr/bin/env python3
# [Flow: Step 1 (legal_issue_tree 모듈 import) -> Step 2 (쟁점-주장-근거 트리 파싱/추출 단위 테스트)
#       -> Step 3 (Mock LLM 응답) -> Step 4 (교차검증 결과 검증)]
# legal_issue_tree 모듈의 3단계 트리 추출, 양측 주장 분리, 주장-근거 교차검증을 검증한다.
import os
import sys
from unittest.mock import patch

# [Flow: backend 패키지 루트를 sys.path에 추가]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

from backend.core import legal_issue_tree


def test_build_issue_tree_prompt_uses_three_level_tree():
    """프롬프트가 쟁점-주장-근거 3단계 트리와 양측 대립을 포함해야 한다."""
    prompt = legal_issue_tree._build_issue_tree_prompt("사기죄")
    assert "쟁점" in prompt
    assert "주장" in prompt
    assert "근거" in prompt or "증거" in prompt
    assert "원고" in prompt or "피고" in prompt or "검사" in prompt or "피고인" in prompt


def test_parse_issue_tree_builds_three_level_tree():
    """LLM 응답에서 쟁점-주장-근거 3단계 트리를 파싱한다."""
    content = """{
        "claim_type": "사기죄",
        "issues": [
            {
                "id": "issue_1",
                "name": "기망행위의 존재 여부",
                "description": "피고가 원고를 현혹할 거짓말을 했는가",
                "claims": [
                    {
                        "id": "claim_1",
                        "party": "원고",
                        "name": "피고의 기망행위 존재",
                        "description": "피고가 원고에게 거짓 진술을 하여 원고를 현혹함",
                        "mapped_evidence": [
                            {"evidence_id": "ev_1", "text_snippet": "피고의 거짓 진술", "source_doc": "P.5", "reason": "직접적인 기망행위 증거"}
                        ]
                    },
                    {
                        "id": "claim_2",
                        "party": "피고",
                        "name": "기망행위 부존재",
                        "description": "피고의 진술은 과장일 뿐 거짓이 아님",
                        "mapped_evidence": []
                    }
                ]
            }
        ]
    }"""
    result = legal_issue_tree._parse_issue_tree(content, "사기죄")
    assert result["claim_type"] == "사기죄"
    assert len(result["issues"]) == 1
    issue = result["issues"][0]
    assert issue["id"] == "issue_1"
    assert len(issue["claims"]) == 2
    assert issue["claims"][0]["party"] == "원고"
    assert issue["claims"][1]["party"] == "피고"
    assert len(issue["claims"][0]["mapped_evidence"]) == 1
    assert issue["claims"][0]["mapped_evidence"][0]["reason"] == "직접적인 기망행위 증거"


def test_extract_issue_claim_tree_cross_validates():
    """extract_issue_claim_tree가 evidence_nodes와 page_texts를 받아 트리 추출 후 교차검증을 수행한다."""
    evidence_nodes = [
        {"id": "ev_1", "type": "evidence", "data": {"label": "피고의 거짓 진술", "page": 5}},
        {"id": "ev_2", "type": "evidence", "data": {"label": "원고의 송금 내역", "page": 10}},
    ]
    page_texts = {1: "피고는 원고에게 거짓말을 했다."}
    tree_response = """{
        "claim_type": "사기죄",
        "issues": [
            {
                "id": "issue_1",
                "name": "기망행위",
                "description": "기망행위가 있었는가",
                "claims": [
                    {
                        "id": "claim_1",
                        "party": "원고",
                        "name": "기망행위 존재",
                        "description": "피고가 거짓말을 했다",
                        "mapped_evidence": [
                            {"evidence_id": "ev_1", "text_snippet": "피고의 거짓 진술", "source_doc": "P.5", "reason": "직접 증거"}
                        ]
                    },
                    {
                        "id": "claim_2",
                        "party": "피고",
                        "name": "기망행위 부존재",
                        "description": "피고의 진술은 과장이지 거짓이 아니다",
                        "mapped_evidence": []
                    }
                ]
            }
        ]
    }"""
    validation_response = """{
        "validation": "passed",
        "corrections": []
    }"""

    with patch("backend.core.legal_issue_tree.call_text") as mock_call:
        mock_call.side_effect = [(tree_response, None), (validation_response, None)]
        result = legal_issue_tree.extract_issue_claim_tree(
            "사기죄",
            evidence_nodes,
            page_texts,
            "http://test",
            "model",
            "key",
        )

    assert len(result["issues"]) == 1
    assert result["cross_validated"] is True


def test_compute_overall_progress_from_issues():
    """issues 구조에서 1개 이상 근거가 매핑된 주장의 비율을 계산한다."""
    mappings = {
        "issues": [
            {
                "id": "issue_1",
                "claims": [
                    {"id": "c1", "mapped_evidence": [{"evidence_id": "e1"}]},
                    {"id": "c2", "mapped_evidence": []},
                ]
            }
        ]
    }
    assert legal_issue_tree.compute_overall_progress(mappings) == 50
