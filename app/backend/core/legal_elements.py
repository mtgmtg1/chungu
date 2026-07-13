#!/usr/bin/env python3
# [Flow: Step 1 (청구 원인 입력) -> Step 2 (vLLM 프롬프트 구성) -> Step 3 (call_text 호출)
#       -> Step 4 (JSON 응답 파싱 + 스키마 검증) -> Step 5 (빈 슬롯 스키마 mapped_evidence:[] 포함 주장 목록 반환)
#       -> Step 6 (선택: evidence_nodes 기반 주장-증거 관계 분석)]
# 주장(Claim) 기반 증거 퍼즐 매퍼의 법적 주장 추출 모듈.
# 입력된 청구 원인(예: 사기죄, 대여금반환)에서 입증에 필수적인 법적 주장(요건사실) 3~5가지를 도출하고,
# 제공된 증거 노드가 있으면 2차 LLM 호출로 주장-증거 관계를 파악해 mapped_evidence에 기록한다.
# pipeline_ediscovery의 vLLM 호출/JSON 파싱 패턴을 재사용한다.
import json
import logging
import re

from ..core.ocr_client import call_text

logger = logging.getLogger(__name__)

# --- 튜닝 상수 ---------------------------------------------------------------
MIN_ELEMENTS = 3   # 최소 주장(요건사실) 개수
MAX_ELEMENTS = 5   # 최대 주장(요건사실) 개수
MAX_TOKENS = 2000  # LLM 응답 토큰 상한
MAX_RELATION_TOKENS = 4000  # 주장-증거 관계 분석용 토큰 상한
MAX_RELATION_EVIDENCE = 50  # 관계 분석에 사용할 최대 증거 노드 수


def _build_legal_elements_prompt(claim_type: str) -> str:
    """[Flow: Step 1 (청구 원인 삽입) -> Step 2 (주장 추출 지시) -> Step 3 (JSON 스키마 명시) -> Step 4 (주의사항)]

    입력된 청구 원인에서 법적 주장(요건사실)을 추출하는 LLM 프롬프트를 구성한다.
    반환 JSON 스키마는 프론트엔드/AI 백엔드 데이터 계약(element_mappings)을 따른다.
    """
    return f"""아래 청구 원인(claim type)에 대해 한국 법률 체계상 입증에 필수적인 주장(법적 요건사실)을 {MIN_ELEMENTS}~{MAX_ELEMENTS}개 도출하라.

청구 원인: {claim_type}

각 주장은 다음 JSON 형식으로 반환하라. 결과는 JSON 객체만 반환한다 (다른 설명 금지).
{{
  "claim_type": "{claim_type}",
  "elements": [
    {{
      "id": "claim_1",
      "name": "주장의 간결한 한국어 명칭",
      "description": "해당 주장의 의미와 입증에 필요한 핵심 내용을 1~2문장으로 설명"
    }}
  ]
}}

주의:
- elements는 {MIN_ELEMENTS}개 이상 {MAX_ELEMENTS}개 이하로 작성.
- id는 "claim_1", "claim_2" ... 순차적으로 부여.
- name은 법률 용어 기반의 간결한 한국어 명칭 (예: "기망행위", "재산적 처분행위", "피해자의 착오").
- description은 해당 주장이 무엇을 의미하고 어떤 사실을 입증해야 하는지 1~2문장 설명.
- mapped_evidence는 증거 목록이 제공되면 LLM이 자동으로 채울 수 있다. 각 항목은 {{"evidence_id", "text_snippet", "source_doc", "reason"}} 형식이며, reason에는 해당 증거가 이 주장을 뒷받침하는 구체적인 관계(사실적 연결 + 법률적 의미)를 기록.
- 주장과 증거의 관계(reason)는 반드시 사실적 연결과 법률적 의미를 포함하여 구체적으로 기술.
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
        element_id = str(item.get("id", "")).strip() or f"claim_{idx}"

        raw_mapped = item.get("mapped_evidence", [])
        mapped_evidence = []
        if isinstance(raw_mapped, list):
            for ev in raw_mapped:
                if not isinstance(ev, dict):
                    continue
                evidence_id = str(ev.get("evidence_id", "")).strip()
                if not evidence_id:
                    continue
                mapped_evidence.append({
                    "evidence_id": evidence_id,
                    "text_snippet": str(ev.get("text_snippet", "")).strip(),
                    "source_doc": str(ev.get("source_doc", "")).strip(),
                    "reason": str(ev.get("reason", "")).strip(),
                })

        elements.append({
            "id": element_id,
            "name": name,
            "description": description,
            "mapped_evidence": mapped_evidence,
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
    """빈 주장 스키마 반환 (LLM 실패/파싱 실패 폴백용)."""
    return {
        "claim_type": claim_type,
        "overall_progress_percent": 0,
        "elements": [],
    }


def _build_claim_evidence_relations_prompt(claim_type: str, claims: list[dict], evidence_nodes: list[dict]) -> str:
    """[Flow: Step 1 (주장/증거 목록 직렬화) -> Step 2 (관계 분석 지시) -> Step 3 (JSON 스키마 명시) -> Step 4 (주의사항)]

    주장 목록과 e-Discovery 증거 노드 목록을 받아, 각 주장에 입증력이 있는 증거를 선택하고
    그 사실/법률적 관계를 reason 필드에 기록하도록 유도하는 LLM 프롬프트를 구성한다.
    """
    claims_summary = json.dumps(
        [{"id": c["id"], "name": c["name"], "description": c["description"]} for c in claims],
        ensure_ascii=False,
        indent=2,
    )
    evidence_summary = json.dumps(
        [
            {
                "id": n.get("id"),
                "label": n.get("data", {}).get("label") or n.get("label") or "",
                "page": n.get("data", {}).get("page"),
                "summary": n.get("data", {}).get("summary") or "",
            }
            for n in evidence_nodes[:MAX_RELATION_EVIDENCE]
        ],
        ensure_ascii=False,
        indent=2,
    )
    return f"""아래 주장(claims)과 증거(evidence) 목록을 보고, 각 주장에 입증력이 있는 증거를 선택하여 관계(reason)를 기록하라.

청구 원인: {claim_type}

주장:
{claims_summary}

증거:
{evidence_summary}

출력 형식:
{{
  "relations": [
    {{
      "claim_id": "claim_1",
      "evidence_id": "evidence_node_id",
      "reason": "이 증거가 해당 주장을 뒷받침하는 구체적인 사실/법률적 연결"
    }}
  ]
}}

주의:
- 주장마다 0개 이상의 증거를 연결 가능.
- reason은 반드시 구체적이며, 증거의 어떤 내용이 주장의 성립에 기여하는지 사실적 연결과 법률적 의미를 모두 포함하여 설명.
- 연결할 증거가 없는 주장은 relations에서 생략 가능.
- 다른 설명 금지, JSON 객체만 반환.
"""


def _parse_claim_evidence_relations(content: str, claims: list[dict], evidence_nodes: list[dict]) -> list[dict]:
    """[Flow: Step 1 (JSON 펜스 제거) -> Step 2 (JSON 파싱) -> Step 3 (relations 스키마 검증)
          -> Step 4 (증거 노드 메타데이터 보강) -> Step 5 (주장별 mapped_evidence 재구성) -> Step 6 (업데이트된 주장 목록 반환)]

    LLM이 반환한 주장-증거 관계 JSON을 파싱하여, 각 주장의 mapped_evidence를 채운다.
    존재하지 않는 evidence_id나 claim_id는 무시한다.
    """
    cleaned = _strip_json_fence(content)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning(f"[legal-elements-relations] JSON 파싱 실패: {cleaned[:200]}")
        return claims

    if not isinstance(data, dict):
        return claims

    relations = data.get("relations", [])
    if not isinstance(relations, list):
        return claims

    evidence_map = {n.get("id"): n for n in evidence_nodes if isinstance(n, dict)}
    claim_by_id = {c["id"]: c for c in claims}

    # 기존 mapped_evidence를 유지하면서 관계 분석 결과를 추가 (중복 방지)
    for c in claims:
        c["mapped_evidence"] = list(c.get("mapped_evidence", []))

    for rel in relations:
        if not isinstance(rel, dict):
            continue
        claim_id = str(rel.get("claim_id", "")).strip()
        evidence_id = str(rel.get("evidence_id", "")).strip()
        reason = str(rel.get("reason", "")).strip()
        if not claim_id or not evidence_id or not reason:
            continue

        claim = claim_by_id.get(claim_id)
        ev_node = evidence_map.get(evidence_id)
        if not claim or not ev_node:
            continue

        existing = next((ev for ev in claim["mapped_evidence"] if ev["evidence_id"] == evidence_id), None)
        if existing:
            existing["reason"] = reason
            continue

        text_snippet = ev_node.get("data", {}).get("label") or ev_node.get("label") or ""
        page = ev_node.get("data", {}).get("page")
        source_doc = f"P.{page}" if page else ""
        claim["mapped_evidence"].append({
            "evidence_id": evidence_id,
            "text_snippet": text_snippet,
            "source_doc": source_doc,
            "reason": reason,
        })

    return claims


def extract_legal_elements(claim_type: str, endpoint: str, model: str, api_key: str, evidence_nodes: list[dict] | None = None) -> dict:
    """[Flow: Step 1 (프롬프트 구성) -> Step 2 (vLLM 호출) -> Step 3 (응답 파싱)
          -> Step 4 (evidence_nodes 제공 시 주장-증거 관계 분석) -> Step 5 (데이터 계약 형식 반환)]

    입력된 청구 원인에서 vLLM Proxy를 호출해 법적 주장(요건사실) 3~5개를 추출한다.
    evidence_nodes가 제공되면 2차 LLM 호출로 각 주장과 증거의 관계(reason)를 분석하여 매핑한다.
    LLM 호출 실패 시 빈 스키마를 반환한다 (예외 전파하지 않음).
    """
    claim_type = (claim_type or "").strip()
    if not claim_type:
        return _empty_schema("")

    prompt = _build_legal_elements_prompt(claim_type)
    try:
        content, _ = call_text(prompt, endpoint, model, api_key, max_tokens=MAX_TOKENS)
        mappings = _parse_legal_elements(content, claim_type)
    except Exception as e:
        logger.warning(f"[legal-elements] vLLM 호출 실패 claim_type={claim_type}: {e}")
        return _empty_schema(claim_type)

    if evidence_nodes and mappings.get("elements"):
        relations_prompt = _build_claim_evidence_relations_prompt(claim_type, mappings["elements"], evidence_nodes)
        try:
            rel_content, _ = call_text(relations_prompt, endpoint, model, api_key, max_tokens=MAX_RELATION_TOKENS)
            mappings["elements"] = _parse_claim_evidence_relations(rel_content, mappings["elements"], evidence_nodes)
        except Exception as e:
            logger.warning(f"[legal-elements-relations] 관계 분석 실패 claim_type={claim_type}: {e}")

    return mappings


def compute_overall_progress(mappings: dict) -> int:
    """[Flow: Step 1 (주장 목록 순회) -> Step 2 (1개 이상 증거가 매핑된 주장 카운트) -> Step 3 (비율 % 계산)]

    퍼즐 매퍼 상태에서 전체 주장 중 1개 이상의 증거가 매핑된 주장의 비율(%)을 계산한다.
    주장이 없으면 0% 반환.
    """
    elements = mappings.get("elements", []) if isinstance(mappings, dict) else []
    if not elements:
        return 0
    filled = sum(1 for el in elements if el.get("mapped_evidence"))
    return round(filled / len(elements) * 100)
