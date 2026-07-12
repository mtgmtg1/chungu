#!/usr/bin/env python3
# [Flow: Step 1 (backend 패키지 경로 추가) -> Step 2 (필요한 모듈 import) -> Step 3 (legal_case_profile 파서/추출기 단위 테스트)]
# 자료 업로드 시 LLM이 법률 분야/쟁점/요건사실을 추출하는 legal_case_profile 모듈의 단위 테스트.
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

import unittest
from unittest.mock import patch

from backend.core.legal_case_profile import (
    _parse_legal_profile,
    extract_legal_profile,
    build_legal_profile_sample_text,
)


class TestLegalProfileParser(unittest.TestCase):
    """[Flow: Step 1 (정상 JSON 파싱) -> Step 2 (펜스/부분 필드/오류 fallback 검증)]"""

    def test_parse_valid_json(self):
        """전체 필드를 포함한 정상 JSON 응답을 파싱한다."""
        content = """```json
{
  "legal_domain": "민사",
  "claim_type": "대여금반환",
  "claim_summary": "원고가 피고에게 대여금을 반환받기 위해 소송을 제기함",
  "issues": ["대여금 변제기 도래", "피고의 변제 항변"],
  "legal_elements": [
    {"id": "element_1", "name": "금전 대여", "description": "원고가 피고에게 금전을 대여했음"},
    {"id": "element_2", "name": "변제기 도래", "description": "반환할 기한이 도래했음"}
  ],
  "confidence": 0.92
}
```"""
        result = _parse_legal_profile(content)
        self.assertEqual(result["legal_domain"], "민사")
        self.assertEqual(result["claim_type"], "대여금반환")
        self.assertEqual(len(result["issues"]), 2)
        self.assertEqual(len(result["legal_elements"]), 2)
        self.assertEqual(result["legal_elements"][0]["name"], "금전 대여")
        self.assertEqual(result["confidence"], 0.92)

    def test_parse_no_fence(self):
        """JSON 펜스가 없어도 파싱에 성공한다."""
        content = '{"legal_domain": "형사", "claim_type": "사기죄", "issues": ["기망행위", "재산적 처분"], "legal_elements": []}'
        result = _parse_legal_profile(content)
        self.assertEqual(result["legal_domain"], "형사")
        self.assertEqual(result["claim_type"], "사기죄")

    def test_parse_partial_fields(self):
        """일부 필드가 누락되면 기본값으로 채워 반환한다."""
        content = '{"legal_domain": "행정", "claim_type": "행정처분취소"}'
        result = _parse_legal_profile(content)
        self.assertEqual(result["legal_domain"], "행정")
        self.assertEqual(result["claim_type"], "행정처분취소")
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["legal_elements"], [])
        self.assertEqual(result["confidence"], 0.0)

    def test_parse_invalid_json(self):
        """JSON 파싱에 실패하면 빈 프로필을 반환한다."""
        result = _parse_legal_profile("이것은 JSON이 아님")
        self.assertEqual(result, {})

    def test_parse_legal_elements_validation(self):
        """legal_elements 항목 중 스키마에 맞지 않는 항목은 건너뛴다."""
        content = '{"legal_domain": "민사", "legal_elements": [{"name": "계약체결", "description": "계약을 맺었음"}, {"id": "x", "description": "name 누락"}, {"id": "y", "name": "", "description": "빈 이름"}]}'
        result = _parse_legal_profile(content)
        self.assertEqual(len(result["legal_elements"]), 1)
        self.assertEqual(result["legal_elements"][0]["id"], "element_1")


class TestExtractLegalProfile(unittest.TestCase):
    """[Flow: Step 1 (call_text mock) -> Step 2 (extract_legal_profile 호출) -> Step 3 (결과 검증)]"""

    def test_extract_legal_profile_calls_llm(self):
        """page_texts가 주어지면 LLM에 샘플 텍스트를 포함한 프롬프트를 전송하고 결과를 파싱한다."""
        page_texts = {1: "원고 A는 2023년 4월 5일 피고 B에게 1천만 원을 대여했다.", 2: "피고 B는 2023년 5월 5일까지 갚기로 약속했다."}
        with patch("backend.core.legal_case_profile.call_text") as mock_call:
            mock_call.return_value = (
                '{"legal_domain": "민사", "claim_type": "대여금반환", "issues": ["변제기"], "legal_elements": [{"id": "e1", "name": "대여", "description": "x"}]}',
                None,
            )
            result = extract_legal_profile(page_texts, "http://test", "model", "key")
        self.assertEqual(result["legal_domain"], "민사")
        self.assertEqual(result["claim_type"], "대여금반환")
        self.assertEqual(len(result["legal_elements"]), 1)
        mock_call.assert_called_once()
        prompt = mock_call.call_args[0][0]
        self.assertIn("민사", prompt)
        self.assertIn("형사", prompt)
        self.assertIn("대여금반환", prompt)
        self.assertIn("원고 A는", prompt)

    def test_extract_legal_profile_empty_pages(self):
        """page_texts가 비어 있으면 LLM을 호출하지 않고 빈 dict를 반환한다."""
        result = extract_legal_profile({}, "http://test", "model", "key")
        self.assertEqual(result, {})

    def test_extract_legal_profile_llm_failure(self):
        """LLM 호출이 실패하면 예외를 전파하지 않고 빈 dict를 반환한다."""
        page_texts = {1: "원고 A는 계약 위반을 주장한다."}
        with patch("backend.core.legal_case_profile.call_text") as mock_call:
            mock_call.side_effect = RuntimeError("LLM unavailable")
            result = extract_legal_profile(page_texts, "http://test", "model", "key")
        self.assertEqual(result, {})

    def test_extract_legal_profile_uses_agent_hints(self):
        """claim_type_hint와 additional_context가 프롬프트에 포함된다."""
        page_texts = {1: "원고 A는 계약 위반을 주장한다."}
        with patch("backend.core.legal_case_profile.call_text") as mock_call:
            mock_call.return_value = (
                '{"legal_domain": "민사", "claim_type": "손해배상", "issues": [], "legal_elements": []}',
                None,
            )
            result = extract_legal_profile(
                page_texts,
                "http://test",
                "model",
                "key",
                original_filename="test.pdf",
                total_pages=1,
                claim_type_hint="손해배상",
                additional_context="사고로 인한 손해배상 청구",
            )
        self.assertEqual(result["claim_type"], "손해배상")
        prompt = mock_call.call_args[0][0]
        self.assertIn("손해배상", prompt)
        self.assertIn("사고로 인한 손해배상 청구", prompt)
        self.assertIn("test.pdf", prompt)


class TestSampleTextBuilder(unittest.TestCase):
    """[Flow: Step 1 (page_texts 입력) -> Step 2 (최대 글자수 내 샘플 구성) -> Step 3 (검증)]"""

    def test_build_sample_text(self):
        """페이지 텍스트를 페이지 번호 순서대로 결합하여 샘플 텍스트를 생성한다."""
        page_texts = {
            2: "두 번째 페이지",
            1: "첫 번째 페이지",
            3: "세 번째 페이지",
        }
        sample = build_legal_profile_sample_text(page_texts, max_chars=100)
        self.assertIn("첫 번째 페이지", sample)
        self.assertIn("두 번째 페이지", sample)
        self.assertIn("세 번째 페이지", sample)
        self.assertLessEqual(len(sample), 100)

    def test_build_sample_text_respects_max_chars(self):
        """max_chars를 초과하는 텍스트는 잘라낸다."""
        page_texts = {1: "a" * 1000, 2: "b" * 1000}
        sample = build_legal_profile_sample_text(page_texts, max_chars=1500)
        self.assertLessEqual(len(sample), 1500)
        self.assertIn("a" * 1000, sample)

    def test_build_sample_text_stratified_sampling(self):
        """페이지 수가 많을 때 시작/중간/끝 부분을 골고루 샘플링한다."""
        page_texts = {i: f"페이지 {i} 내용" for i in range(1, 11)}
        sample = build_legal_profile_sample_text(page_texts, max_chars=5000)
        self.assertIn("--- 페이지 1 ---", sample)
        self.assertIn("--- 페이지 10 ---", sample)
        # 중간 페이지(4~7) 중 하나는 포함되어 있어야 함
        middle_found = any(f"--- 페이지 {i} ---" in sample for i in range(4, 8))
        self.assertTrue(middle_found, "중간 부분 샘플이 포함되지 않음")


if __name__ == "__main__":
    unittest.main()
