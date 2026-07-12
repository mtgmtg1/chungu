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
MAX_SAMPLE_CHARS = 16000  # LLM 프롬프트에 전달할 문서 텍스트 샘플 상한


def _concat_pages_in_order(pages: list[tuple[int, str]], budget: int) -> str:
    """[Flow: Step 1 (페이지 순서대로 마커 추가) -> Step 2 (budget 초과 시 마지막 페이지에서 자름)
          -> Step 3 (결과 문자열 반환)]

    주어진 페이지 목록을 페이지 번호 순서대로 하나의 샘플 텍스트로 결합한다.
    budget(글자수)을 초과하면 마지막 페이지에서 잘라낸다.
    """
    if not pages or budget <= 0:
        return ""

    parts: list[str] = []
    total = 0

    for page_no, text in pages:
        marker = f"--- 페이지 {page_no} ---"
        chunk = f"{marker}\n{text.strip()}"
        if total + len(chunk) + 2 > budget:
            remaining = budget - total - len(marker) - 3
            if remaining > 0:
                parts.append(f"{marker}\n{text.strip()[:remaining]}")
            break
        parts.append(chunk)
        total += len(chunk) + 2

    return "\n\n".join(parts)


def build_legal_profile_sample_text(page_texts: dict[int, str], max_chars: int = MAX_SAMPLE_CHARS) -> str:
    """[Flow: Step 1 (비어 있지 않은 페이지 필터링 + 정렬)
          -> Step 2 (문서가 짧으면 전체 사용, 길면 시작/중간/끝 샘플링)
          -> Step 3 (예산별 페이지 텍스트 결합) -> Step 4 (샘플 문자열 반환)]

    페이지별 텍스트를 최대 글자수 내에서 하나의 샘플 텍스트로 결합한다.
    페이지 수가 많을 때는 문서의 시작, 중간, 끝 부분을 골고루 샘플링해
    전체적인 쟁점/분야 파악에 필요한 맥락이 누락되지 않도록 한다.
    """
    if not page_texts:
        return ""

    pages = sorted(
        ((page_no, text.strip()) for page_no, text in page_texts.items() if text and text.strip()),
        key=lambda item: item[0],
    )
    if not pages:
        return ""

    total_pages = len(pages)
    if total_pages <= 3 or max_chars <= 0:
        return _concat_pages_in_order(pages, max_chars)

    # 긴 문서: 시작 35%, 중간 35%, 끝 30% 예산으로 분할 샘플링
    begin_budget = int(max_chars * 0.35)
    middle_budget = int(max_chars * 0.35)
    end_budget = max_chars - begin_budget - middle_budget

    middle_window = max(1, total_pages // 3)
    middle_start = max(0, total_pages // 2 - middle_window // 2)
    end_window = max(1, total_pages // 3)

    begin_pages = pages
    middle_pages = pages[middle_start:middle_start + middle_window]
    end_pages = pages[-end_window:]

    parts: list[str] = []
    remaining = max_chars
    for budget, segment_pages in (
        (begin_budget, begin_pages),
        (middle_budget, middle_pages),
        (end_budget, end_pages),
    ):
        if not segment_pages:
            continue
        segment_text = _concat_pages_in_order(segment_pages, min(budget, remaining))
        if segment_text:
            parts.append(segment_text)
            remaining -= len(segment_text) + 2

    return "\n\n".join(parts)


def _build_legal_profile_prompt(
    sample_text: str,
    original_filename: str | None = None,
    total_pages: int | None = None,
    claim_type_hint: str | None = None,
    additional_context: str | None = None,
) -> str:
    """[Flow: Step 1 (문서 메타데이터/에이전트 힌트 수집) -> Step 2 (법률 분류/쟁점/요건사실 추출 지시)
          -> Step 3 (JSON 스키마 명시) -> Step 4 (맥락 활용 및 fallback 금지 주의사항 추가)
          -> Step 5 (샘플 텍스트 삽입)]

    문서 샘플, 파일 메타데이터, 그리고 에이전트가 제공한 추가 맥락을 바탕으로
    법률 분야, 청구 원인, 쟁점, 법적 요건사실을 추출하는 LLM 프롬프트를 구성한다.
    반환은 JSON 객체 하나만 한다.
    """
    meta_parts: list[str] = []
    if original_filename:
        meta_parts.append(f"원본 파일명: {original_filename}")
    if total_pages:
        meta_parts.append(f"총 페이지 수: {total_pages}")
    metadata_line = " | ".join(meta_parts) if meta_parts else "메타데이터 없음"

    hint_section = ""
    if claim_type_hint or additional_context:
        hint_lines: list[str] = []
        if claim_type_hint:
            hint_lines.append(f"- 사용자/에이전트가 제안한 청구 원인 힌트: {claim_type_hint}")
        if additional_context:
            hint_lines.append(f"- 추가 맥락: {additional_context}")
        hint_section = "\n아래 힌트를 참고할 수 있다. 힌트가 자료와 모순되면 자료 내용을 우선한다.\n" + "\n".join(hint_lines) + "\n"

    return f"""아래는 법률 관련 자료에서 추출한 텍스트 샘플이다. 이 자료를 보고 다음 항목을 추출하라.

중요: 문서가 길 경우 샘플은 시작/중간/끝 부분을 골고루 포함하고 있다. 전체 맥락을 종합해서 판단해야 한다.
분류가 애매하더라도 "기타"나 "정보부족"으로 대체하지 말고, 자료에 실제로 드러난 가장 구체적인 법률 분야와 청구 원인을 적어라.

{metadata_line}{hint_section}
1. legal_domain: 자료가 다루는 법률 분야. 다음 예시 중 가장 적절한 것을 선택하되, 예시에 없더라도 구체적 용어를 사용한다.
   예: 민사, 형사, 행정, 가사(이혼/양육/상속), 헌법, 노동, 지식재산권, 상사, 손해배상(위약금/하자보수), 부동산(임대차/매매), 채무, 국제, 보험, 세무, 형사고소
   (단, "기타"는 자료의 내용이 법률 분류 전혀 불가능할 때만 사용)
2. claim_type: 구체적인 청구 원인 또는 법적 쟁점. "정보부족"이나 "기타"로 쓰지 말고, 자료에 나타난 실제 청구/주장을 적어라.
   예: 대여금반환, 사기죄, 행정처분취소, 재판상 이혼, 헌법소원, 채무부존재확인, 부당이득반환, 손해배상(교통사고/하자보수), 임대차보증금반환, 근로관계유지/해지, 산업재해
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


def _is_generic_fallback(legal_domain: str, claim_type: str) -> bool:
    """[Flow: Step 1 (legal_domain/claim_type 소문자화) -> Step 2 (금지어 집합 비교) -> Step 3 (fallback 여부 반환)]

    모델이 판단을 회피하고 "기타" 또는 "정보부족" 같은 placeholder로 채웠는지 확인한다.
    한영/띄어쓰기 변형을 처리하기 위해 공백을 제거하고 소문자로 비교한다.
    """
    normalized_domain = legal_domain.lower().replace(" ", "")
    normalized_claim = claim_type.lower().replace(" ", "")
    fallback_domains = {"기타", "etc", "정보없음", "unknown"}
    fallback_claims = {"기타", "etc", "정보부족", "정보없음", "unknown", "미정", "불명"}
    return normalized_domain in fallback_domains or normalized_claim in fallback_claims


def _parse_legal_profile(content: str) -> dict:
    """[Flow: Step 1 (JSON 펜스 제거) -> Step 2 (JSON 파싱) -> Step 3 (필드 스키마 검증/보정)
          -> Step 4 (fallback placeholder 거부) -> Step 5 (legal_profile dict 반환)]

    LLM 응답 문자열을 법률 프로필 데이터 계약 형식으로 변환한다.
    JSON 파싱 실패하거나 "기타"/"정보부족" 같은 fallback이면 빈 dict를 반환한다.
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

    if _is_generic_fallback(legal_domain, claim_type):
        logger.warning(
            f"[legal-case-profile] fallback 결과 거부: legal_domain={legal_domain}, claim_type={claim_type}"
        )
        return {}

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
    original_filename: str | None = None,
    total_pages: int | None = None,
    claim_type_hint: str | None = None,
    additional_context: str | None = None,
    max_tokens: int = MAX_TOKENS,
) -> dict:
    """[Flow: Step 1 (페이지 텍스트 + 파일 메타데이터 + 에이전트 힌트 수집)
          -> Step 2 (프롬프트 구성) -> Step 3 (vLLM 호출) -> Step 4 (응답 파싱)
          -> Step 5 (legal_profile 반환 / 예외 시 빈 dict)]

    자료에서 LLM을 통해 법률 분야, 청구 원인, 쟁점, 법적 요건사실을 추출한다.
    문서가 길 경우 시작/중간/끝을 골고루 샘플링하고, 원본 파일명/총 페이지 수/
    에이전트가 제공한 claim_type_hint/additional_context를 함께 주입해
    "기타/정보부족"으로 빠지는 것을 방지한다.
    LLM 호출 실패나 파싱 실패 시 예외를 전파하지 않고 빈 dict를 반환한다.
    """
    sample_text = build_legal_profile_sample_text(page_texts)
    if not sample_text:
        return {}

    prompt = _build_legal_profile_prompt(
        sample_text,
        original_filename=original_filename,
        total_pages=total_pages,
        claim_type_hint=claim_type_hint,
        additional_context=additional_context,
    )
    try:
        content, _ = call_text(prompt, endpoint, model, api_key, max_tokens=max_tokens)
        return _parse_legal_profile(content)
    except Exception as e:
        logger.warning(f"[legal-case-profile] vLLM 호출 실패: {e}")
        return {}
