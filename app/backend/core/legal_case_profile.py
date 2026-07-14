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
    user_language: str = "ko",
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
        meta_parts.append(f"Original filename: {original_filename}")
    if total_pages:
        meta_parts.append(f"Total pages: {total_pages}")
    metadata_line = " | ".join(meta_parts) if meta_parts else "No metadata"

    hint_section = ""
    if claim_type_hint or additional_context:
        hint_lines: list[str] = []
        if claim_type_hint:
            hint_lines.append(f"- Claim type hint suggested by user/agent: {claim_type_hint}")
        if additional_context:
            hint_lines.append(f"- Additional context: {additional_context}")
        hint_section = "\nYou may refer to the hints below. If a hint conflicts with the document, prioritize the document.\n" + "\n".join(hint_lines) + "\n"

    return f"""Below is a text sample extracted from a legal-related document. Extract the following items based on this sample.

Important: If the document is long, the sample includes the beginning, middle, and end. You must judge based on the overall context. Even if the classification is ambiguous, do not replace it with "other" or "unknown"; write the most specific legal domain and claim type actually revealed in the document.

{metadata_line}{hint_section}
1. legal_domain: The legal domain the document covers. Choose the most appropriate one from the examples below, but use a specific term even if it is not in the examples.
   Examples: civil, criminal, administrative, family (divorce/custody/inheritance), constitutional, labor, intellectual property, commercial, damages (penalty/defect repair), real estate (lease/sale), debt, international, insurance, tax, criminal complaint
   (Use "other" only when the document content is completely impossible to classify legally)
2. claim_type: The specific claim cause or legal issue. Do not write "unknown" or "other"; write the actual claim/issue shown in the document.
   Examples: loan repayment, fraud, administrative disposition cancellation, contested divorce, constitutional petition, confirmation of non-debt, unjust enrichment return, damages (traffic accident/defect repair), lease deposit return, maintenance/termination of employment, industrial accident
3. claim_summary: Summarize the core factual relationship in 1-2 sentences.
4. issues: List 1-5 disputed issues (claims) as concise strings in the user's configured language ({user_language}).
5. legal_elements: Organize {MIN_ELEMENTS}~{MAX_ELEMENTS} legal elements required to prove the claim_type.
6. confidence: The model's confidence in the above classification/extraction (0.0~1.0).

Each legal_element must include the following keys:
- id: Sequential ID: "element_1", "element_2", ...
- name: Concise name of the legal element in the user's configured language ({user_language}) (e.g., "money loan", "fraudulent act", "due date")
- description: 1-2 sentence explanation of what the element means and what facts must be proven

Return only the JSON object. No other explanation, markdown, or code fences.

{json.dumps({
    "legal_domain": "e.g., civil",
    "claim_type": "e.g., loan repayment",
    "claim_summary": "Summary of facts",
    "issues": ["issue1", "issue2"],
    "legal_elements": [
        {"id": "element_1", "name": "element name", "description": "element description"}
    ],
    "confidence": 0.9
}, ensure_ascii=False, indent=2)}

--- Text sample ---
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
    fallback_domains = {"기타", "etc", "정보없음", "unknown", "other", "n/a", "notapplicable", "unspecified"}
    fallback_claims = {"기타", "etc", "정보부족", "정보없음", "unknown", "미정", "불명", "other", "n/a", "notapplicable", "unspecified", "insufficientinformation", "notenoughinformation"}
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
    user=None,
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

    user_language = user.language if user and getattr(user, "language", None) else "ko"
    prompt = _build_legal_profile_prompt(
        sample_text,
        original_filename=original_filename,
        total_pages=total_pages,
        claim_type_hint=claim_type_hint,
        additional_context=additional_context,
        user_language=user_language,
    )
    try:
        content, _ = call_text(prompt, endpoint, model, api_key, max_tokens=max_tokens)
        return _parse_legal_profile(content)
    except Exception as e:
        logger.warning(f"[legal-case-profile] vLLM 호출 실패: {e}")
        return {}
