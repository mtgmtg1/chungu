#!/usr/bin/env python3
# [Flow: Step 1 (청구 원인 입력) -> Step 2 (vLLM 프롬프트 구성) -> Step 3 (call_text 호출)
#       -> Step 4 (JSON 응답 파싱 + 스키마 검증) -> Step 5 (빈 슬롯 스키마 mapped_evidence:[] 포함 요건사실 목록 반환)]
# 요건 사실 기반 증거 퍼즐 매퍼(Evidence-to-Element Mapper)의 법적 요건사실 추출 모듈.
# 입력된 청구 원인(예: 사기죄, 대여금반환)에서 입증에 필수적인 법적 요건사실 3~5가지를 도출한다.
# pipeline_ediscovery의 vLLM 호출/JSON 파싱 패턴을 재사용한다.
import json
import logging
import re

from ..core.ocr_client import call_text

logger = logging.getLogger(__name__)

# --- 튜닝 상수 ---------------------------------------------------------------
MIN_ELEMENTS = 3   # 최소 요건사실 개수
MAX_ELEMENTS = 5   # 최대 요건사실 개수
MAX_TOKENS = 2000  # LLM 응답 토큰 상한


def _build_legal_elements_prompt(claim_type: str) -> str:
    """[Flow: Step 1 (청구 원명 삽입) -> Step 2 (요건사실 추출 지시) -> Step 3 (JSON 스키마 명시) -> Step 4 (주의사항)]

    입력된 청구 원인에서 법적 요건사실을 추출하는 LLM 프롬프트를 구성한다.
    반환 JSON 스키마는 프론트엔드/AI 백엔드 데이터 계약(element_mappings)을 따른다.
    """
    return f"""아래 청구 원인(claim type)에 대해 한국 법률 체계상 입증에 필수적인 법적 요건사실을 {MIN_ELEMENTS}~{MAX_ELEMENTS}개 도출하라.

청구 원인: {claim_type}

각 요건사실은 다음 JSON 형식으로 반환하라. 결과는 JSON 객체만 반환한다 (다른 설명 금지).
{{
  "claim_type": "{claim_type}",
  "elements": [
    {{
      "id": "element_1",
      "name": "요건사실의 간결한 한국어 명칭",
      "description": "해당 요건사실의 의미와 입증에 필요한 핵심 내용을 1~2문장으로 설명"
    }}
  ]
}}

주의:
- elements는 {MIN_ELEMENTS}개 이상 {MAX_ELEMENTS}개 이하로 작성.
- id는 "element_1", "element_2" ... 순차적으로 부여.
- name은 법률 용어 기반의 간결한 한국어 명칭 (예: "기망행위", "재산적 처분행위", "피해자의 착오").
- description은 해당 요건사실이 무엇을 의미하고 어떤 사실을 입증해야 하는지 1~2문장 설명.
- mapped_evidence는 프론트엔드에서 채우는 필드이므로 LLM은 포함하지 않음.
- 한국 법률 체계(대법원 판례/통설)를 기준으로 도출.
"""


def _strip_json_fence(content: str) -> str:
    """LLM 응답에서 ```json ... ``` 펜스를 제거한다."""
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"```[a-zA-Z]*\n?|\n?```", "", content).strip()
    return content


def _parse_legal_elements(content: str, claim_type: str) -> dict:
    """[Flow: Step 1 (JSON 펜스 제거) -> Step 2 (JSON 파싱) -> Step 3 (요건사실 스키마 검증/변환)
          -> Step 4 (빈 슬롯 mapped_evidence:[] 주입) -> Step 5 (데이터 계약 형식 반환)]

    LLM 응답 문자열을 요건사실 퍼즐 매퍼 데이터 계약 형식으로 변환한다.
    스키마에 맞지 않는 항목은 건너뛴다. overall_progress_percent는 0으로 초기화.
    """
    cleaned = _strip_json_fence(content)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning(f"[legal-elements] JSON 파싱 실패 claim_type={claim_type}: {cleaned[:200]}")
        return _empty_schema(claim_type)

    if not isinstance(data, dict):
        return _empty_schema(claim_type)

    raw_elements = data.get("elements", [])
    if not isinstance(raw_elements, list):
        return _empty_schema(claim_type)

    elements = []
    for idx, item in enumerate(raw_elements, start=1):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        description = str(item.get("description", "")).strip()
        element_id = str(item.get("id", "")).strip() or f"element_{idx}"
        elements.append({
            "id": element_id,
            "name": name,
            "description": description,
            "mapped_evidence": [],
        })
        if len(elements) >= MAX_ELEMENTS:
            break

    if len(elements) < MIN_ELEMENTS:
        logger.warning(f"[legal-elements] 요건사실 {len(elements)}개만 추출 (최소 {MIN_ELEMENTS}개 권장) claim_type={claim_type}")

    return {
        "claim_type": claim_type,
        "overall_progress_percent": 0,
        "elements": elements,
    }


def _empty_schema(claim_type: str) -> dict:
    """빈 요건사실 스키마 반환 (LLM 실패/파싱 실패 폴백용)."""
    return {
        "claim_type": claim_type,
        "overall_progress_percent": 0,
        "elements": [],
    }


def extract_legal_elements(claim_type: str, endpoint: str, model: str, api_key: str) -> dict:
    """[Flow: Step 1 (프롬프트 구성) -> Step 2 (vLLM 호출) -> Step 3 (응답 파싱) -> Step 4 (데이터 계약 형식 반환)]

    입력된 청구 원인에서 vLLM Proxy를 호출해 법적 요건사실 3~5개를 추출한다.
    빈 슬롯(mapped_evidence:[])이 포함된 퍼즐 매퍼 데이터 계약 형식으로 반환한다.
    LLM 호출 실패 시 빈 스키마를 반환한다 (예외 전파하지 않음).
    """
    claim_type = (claim_type or "").strip()
    if not claim_type:
        return _empty_schema("")

    prompt = _build_legal_elements_prompt(claim_type)
    try:
        content, _ = call_text(prompt, endpoint, model, api_key, max_tokens=MAX_TOKENS)
        return _parse_legal_elements(content, claim_type)
    except Exception as e:
        logger.warning(f"[legal-elements] vLLM 호출 실패 claim_type={claim_type}: {e}")
        return _empty_schema(claim_type)


def compute_overall_progress(mappings: dict) -> int:
    """[Flow: Step 1 (요건사실 목록 순회) -> Step 2 (1개 이상 증거가 매핑된 요건 카운트) -> Step 3 (비율 % 계산)]

    퍼즐 매퍼 상태에서 전체 요건 중 1개 이상의 증거가 매핑된 요건의 비율(%)을 계산한다.
    요건이 없으면 0% 반환.
    """
    elements = mappings.get("elements", []) if isinstance(mappings, dict) else []
    if not elements:
        return 0
    filled = sum(1 for el in elements if el.get("mapped_evidence"))
    return round(filled / len(elements) * 100)
