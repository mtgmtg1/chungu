#!/usr/bin/env python3
# [Flow: Step 1 (페이지 텍스트 샘플링) -> Step 2 (LLM 프롬프트 구성)
#       -> Step 3 (call_text 호출) -> Step 4 (JSON 응답 파싱 + 스키마 검증)
#       -> Step 5 (legal_profile dict 반환 / 예외 시 빈 dict)]
# 자료 업로드(변환 완료) 시 LLM이 문서를 보고
# 법률 분야(민사/형사/행정/이혼/헌법 등), 청구 원인, 쟁점, 법적 요건사실을 추출하는 모듈.
# pipeline_ediscovery.run 내부에서 e-Discovery GraphRAG 추출 이전에 한 차례 호출된다.
import json
import logging
import re

from .ocr_client import call_text

logger = logging.getLogger(__name__)

# --- 튜닝 상수 ---------------------------------------------------------------
MIN_ELEMENTS = 3   # 최소 요건사실 개수
MAX_ELEMENTS = 5   # 최대 요건사실 개수
MAX_TOKENS = 2000  # LLM 응답 토큰 상한
MAX_SAMPLE_CHARS = 8000  # LLM 프롬프트에 전달할 문서 텍스트 샘플 상한


def build_legal_profile_sample_text(page_texts: dict[int, str], max_chars: int = MAX_SAMPLE_CHARS) -> str:
    """[Flow: Step 1 (페이지 번호 오름차순 정렬) -> Step 2 (페이지별 텍스트 연결)
          -> Step 3 (max_chars 초과 시 마지막 페이지에서 자름) -> Step 4 (샘플 문자열 반환)]

    페이지별 텍스트를 최대 글자수 내에서 하나의 샘플 텍스트로 결합한다.
    페이지 번호가 불연속적이거나 순서가 뒤바뀐 입력도 안전하게 처리한다.
    """
    if not page_texts:
        return ""

    sorted_pages = sorted(page_texts.items(), key=lambda item: item[0])
    parts: list[str] = []
    total = 0

    for page_no, text in sorted_pages:
        if not text or not text.strip():
            continue
        marker = f"--- 페이지 {page_no} ---"
        chunk = f"{marker}\n{text.strip()}"
        if total + len(chunk) + 1 > max_chars:
            remaining = max_chars - total - len(marker) - 2
            if remaining > 0:
                parts.append(f"{marker}\n{text.strip()[:remaining]}")
            break
        parts.append(chunk)
        total += len(chunk) + 1

    return "\n\n".join(parts)


def _build_legal_profile_prompt(sample_text: str) -> str:
    """[Flow: Step 1 (법률 분류/쟁점/요건사실 추출 지시) -> Step 2 (JSON 스키마 명시)
          -> Step 3 (주의사항) -> Step 4 (샘플 텍스트 삽입)]

    문서 샘플을 보고 법률 분야, 청구 원인, 쟁점, 법적 요건사실을 추출하는 LLM 프롬프트를 구성한다.
    반환은 JSON 객체 하나만 한다.
    """
    return f"""아래는 법률 관련 자료에서 추출한 텍스트 샘플이다. 이 자료를 보고 다음 항목을 추출하라.

1. legal_domain: 자료가 다루는 법률 분야. 다음 중 가장 적절한 것을 선택하거나, "기타"를 사용할 수 있다.
   예: 민사, 형사, 행정, 이혼, 헌법, 노동, 지식재산권, 상사, 손해배상, 국제, 기타
2. claim_type: 구체적인 청구 원인 또는 법적 쟁점. 예: 대여금반환, 사기죄, 행정처분취소, 재판상 이혼, 헌법소원
3. claim_summary: 1~2문장으로 자료의 핵심 사실관계를 요약
4. issues: 다투어지는 쟁점(주장)을 1~5개의 간결한 한국어 문자열로 나열
5. legal_elements: claim_type을 입증하기 위해 필요한 법적 요건사실을 {MIN_ELEMENTS}~{MAX_ELEMENTS}개로 정리
6. confidence: 위 분류/추출에 대한 모델의 확신 정도 (0.0~1.0)

각 legal_element는 다음 키를 포함해야 한다:
- id: "element_1", "element_2" ... 순차적 ID
- name: 요건사실의 간결한 한국어 명칭 (예: "금전 대여", "기망행위", "변제기 도래")
- description: 해당 요건사실의 의미와 입증에 필요한 핵심 내용을 1~2문장으로 설명

결과는 JSON 객체로만 반환한다. 다른 설명, 마크다운, 코드 펜스는 사용하지 않는다.

{json.dumps({
    "legal_domain": "예: 민사",
    "claim_type": "예: 대여금반환",
    "claim_summary": "사실관계 요약",
    "issues": ["쟁점1", "쟁점2"],
    "legal_elements": [
        {"id": "element_1", "name": "요건 이름", "description": "요건 설명"}
    ],
    "confidence": 0.9
}, ensure_ascii=False, indent=2)}

--- 텍스트 샘플 ---
{sample_text}
"""


def _strip_json_fence(content: str) -> str:
    """LLM 응답에서 ```json ... ``` 펜스를 제거한다."""
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"```[a-zA-Z]*\n?|\n?```", "", content).strip()
    return content


def _parse_legal_profile(content: str) -> dict:
    """[Flow: Step 1 (JSON 펜스 제거) -> Step 2 (JSON 파싱) -> Step 3 (필드 스키마 검증/보정)
          -> Step 4 (legal_profile dict 반환)]

    LLM 응답 문자열을 법률 프로필 데이터 계약 형식으로 변환한다.
    JSON 파싱 실패 시 빈 dict를 반환한다.
    """
    cleaned = _strip_json_fence(content)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning(f"[legal-case-profile] JSON 파싱 실패: {cleaned[:200]}")
        return {}

    if not isinstance(data, dict):
        return {}

    def _str(value, default: str = "") -> str:
        if value is None:
            return default
        return str(value).strip()

    def _clamp_confidence(value) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            confidence = 0.0
        return max(0.0, min(1.0, confidence))

    def _list_of_strings(raw) -> list[str]:
        if not isinstance(raw, list):
            return []
        return [str(item).strip() for item in raw if item is not None and str(item).strip()]

    def _elements(raw) -> list[dict]:
        if not isinstance(raw, list):
            return []
        parsed: list[dict] = []
        for idx, item in enumerate(raw, start=1):
            if not isinstance(item, dict):
                continue
            name = _str(item.get("name"))
            if not name:
                continue
            element_id = _str(item.get("id"), f"element_{idx}")
            description = _str(item.get("description"))
            parsed.append({
                "id": element_id,
                "name": name,
                "description": description,
                "mapped_evidence": [],
            })
            if len(parsed) >= MAX_ELEMENTS:
                break
        return parsed

    legal_domain = _str(data.get("legal_domain"))
    claim_type = _str(data.get("claim_type"))
    claim_summary = _str(data.get("claim_summary"))
    issues = _list_of_strings(data.get("issues"))
    legal_elements = _elements(data.get("legal_elements"))
    confidence = _clamp_confidence(data.get("confidence"))

    if len(legal_elements) < MIN_ELEMENTS:
        logger.warning(
            f"[legal-case-profile] 요건사실 {len(legal_elements)}개만 추출 (최소 {MIN_ELEMENTS}개 권장)"
        )

    return {
        "legal_domain": legal_domain,
        "claim_type": claim_type,
        "claim_summary": claim_summary,
        "issues": issues,
        "legal_elements": legal_elements,
        "confidence": confidence,
    }


def extract_legal_profile(
    page_texts: dict[int, str],
    endpoint: str,
    model: str,
    api_key: str,
    max_tokens: int = MAX_TOKENS,
) -> dict:
    """[Flow: Step 1 (페이지 텍스트 샘플링) -> Step 2 (프롬프트 구성) -> Step 3 (vLLM 호출)
          -> Step 4 (응답 파싱) -> Step 5 (legal_profile 반환 / 예외 시 빈 dict)]

    자료에서 LLM을 통해 법률 분야, 청구 원인, 쟁점, 법적 요건사실을 추출한다.
    LLM 호출 실패나 파싱 실패 시 예외를 전파하지 않고 빈 dict를 반환한다.
    """
    sample_text = build_legal_profile_sample_text(page_texts)
    if not sample_text:
        return {}

    prompt = _build_legal_profile_prompt(sample_text)
    try:
        content, _ = call_text(prompt, endpoint, model, api_key, max_tokens=max_tokens)
        return _parse_legal_profile(content)
    except Exception as e:
        logger.warning(f"[legal-case-profile] vLLM 호출 실패: {e}")
        return {}
