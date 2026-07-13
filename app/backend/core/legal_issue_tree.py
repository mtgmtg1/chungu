#!/usr/bin/env python3
# [Flow: Step 1 (청구 원인 + 증거 노드 + 페이지 텍스트 수신) -> Step 2 (1차 LLM: 쟁점-주장-근거 트리 추출)
#       -> Step 3 (2차 LLM: 문서 교차검증) -> Step 4 (스키마 검증 + cross_validated 플래그 설정)
#       -> Step 5 (입증 달성도 계산) -> Step 6 (3단계 트리 데이터 계약 반환)]
# 쟁점(Issue) → 주장(Claim) → 근거(Evidence) 3단계 부모/자식 트리 추출 모듈.
# 양측(원고/피고, 검사/피고인 등)의 주장이 첨예하게 대립하는 쟁점을 도출하고,
# 각 주장에 대한 근거를 매핑하며, LLM이 문서를 교차검증하여 연결고리의 정확성을 확인한다.
# pipeline_ediscovery / legal_elements의 vLLM 호출/JSON 파싱 패턴을 재사용한다.
import json
import logging
import re

from sqlalchemy.orm import Session

from ..core.ocr_client import call_text
from ..core.points_service import spend_agent_step

logger = logging.getLogger(__name__)

# --- 튜닝 상수 ---------------------------------------------------------------
MIN_ISSUES = 3   # 최소 쟁점 개수
MAX_ISSUES = 5   # 최대 쟁점 개수
MIN_CLAIMS_PER_ISSUE = 2  # 각 쟁점당 최소 양측 주장 개수
MAX_CLAIMS_PER_ISSUE = 4  # 각 쟁점당 최대 주장 개수
MAX_EVIDENCE_PER_CLAIM = 5  # 각 주장당 최대 근거 개수
MAX_TOKENS = 4000  # LLM 응답 토큰 상한
MAX_CROSS_VALIDATION_TOKENS = 4000  # 교차검증용 토큰 상한
MAX_CROSS_VALIDATION_EVIDENCE = 50  # 교차검증에 사용할 최대 증거 노드 수


def _strip_json_fence(content: str) -> str:
    """LLM 응답에서 ```json ... ``` 펜스를 제거한다."""
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"```[a-zA-Z]*\n?|\n?```", "", content).strip()
    return content


def _build_issue_tree_prompt(claim_type: str) -> str:
    """[Flow: Step 1 (청구 원인 삽입) -> Step 2 (3단계 트리 추출 지시) -> Step 3 (JSON 스키마 명시) -> Step 4 (주의사항)]

    입력된 청구 원인에서 쟁점-주장-근거 3단계 트리를 추출하는 LLM 프롬프트를 구성한다.
    양측(원고/피고, 검사/피고인 등)이 첨예하게 대립하는 쟁점을 중심으로 구성한다.
    """
    return f"""아래 청구 원인(claim type)에 대해 한국 법률 체계상 양측(원고/피고, 검사/피고인 등)이 첨예하게 대립하는 쟁점을 {MIN_ISSUES}~{MAX_ISSUES}개 도출하고,
각 쟁점에 대해 양측의 주장과 각 주장을 지지하는 근거를 3단계 트리로 구성하라.

청구 원인: {claim_type}

출력 JSON 형식:
{{
  "claim_type": "{claim_type}",
  "issues": [
    {{
      "id": "issue_1",
      "name": "쟁점의 간결한 한국어 명칭",
      "description": "해당 쟁점이 무엇을 묻는지 1~2문장 설명",
      "claims": [
        {{
          "id": "claim_1",
          "party": "원고 또는 검사",
          "name": "주장의 간결한 한국어 명칭",
          "description": "해당 주장의 의미와 입증에 필요한 핵심 내용을 1~2문장 설명",
          "mapped_evidence": [
            {{
              "evidence_id": "evidence_node_id",
              "text_snippet": "근거 텍스트 요약",
              "source_doc": "P.5",
              "reason": "이 근거가 해당 주장을 뒷받침하는 구체적인 사실/법률적 연결"
            }}
          ]
        }},
        {{
          "id": "claim_2",
          "party": "피고 또는 피고인",
          "name": "반대 주장의 간결한 한국어 명칭",
          "description": "반대 주장의 의미와 입증에 필요한 핵심 내용을 1~2문장 설명",
          "mapped_evidence": []
        }}
      ]
    }}
  ]
}}

주의:
- issues는 {MIN_ISSUES}개 이상 {MAX_ISSUES}개 이하로 작성.
- 각 issue는 반드시 2개 이상의 상반된 주장(claims)을 포함 (예: 원고 주장 vs 피고 주장).
- id는 "issue_1", "issue_2", "claim_1", "claim_2" ... 순차적으로 부여.
- party는 "원고", "피고", "검사", "피고인", "의뢰인", "상대방" 등 실제 대립 주체를 명시.
- mapped_evidence는 증거 노드가 제공되면 LLM이 자동으로 채운다. 각 항목은 {{"evidence_id", "text_snippet", "source_doc", "reason"}} 형식.
- reason에는 해당 근거가 주장을 뒷받침하는 구체적인 사실적 연결과 법률적 의미를 모두 포함하여 기술.
- 한국 법률 체계(대법원 판례/통설)를 기준으로 도출.
- 다른 설명 금지, JSON 객체만 반환.
"""


def _build_cross_validation_prompt(
    claim_type: str,
    issues: list[dict],
    evidence_nodes: list[dict],
    page_texts: dict[int, str],
) -> str:
    """[Flow: Step 1 (트리/증거/텍스트 직렬화) -> Step 2 (교차검증 지시) -> Step 3 (JSON 스키마 명시) -> Step 4 (주의사항)]

    추출된 쟁점-주장-근거 트리가 문서 내용과 일치하는지, 주장-근거 연결이 사실적으로 타당한지
    교차검증하도록 유도하는 LLM 프롬프트를 구성한다.
    """
    issues_summary = json.dumps(
        [
            {
                "id": issue["id"],
                "name": issue["name"],
                "description": issue["description"],
                "claims": [
                    {
                        "id": c["id"],
                        "party": c["party"],
                        "name": c["name"],
                        "description": c["description"],
                        "mapped_evidence": c.get("mapped_evidence", []),
                    }
                    for c in issue.get("claims", [])
                ],
            }
            for issue in issues
        ],
        ensure_ascii=False,
        indent=2,
    )
    evidence_summary = json.dumps(
        [
            {
                "id": n.get("id"),
                "label": n.get("data", {}).get("label") or n.get("label") or "",
                "page": n.get("data", {}).get("page"),
            }
            for n in evidence_nodes[:MAX_CROSS_VALIDATION_EVIDENCE]
        ],
        ensure_ascii=False,
        indent=2,
    )
    text_sample = json.dumps(
        {k: v for k, v in list(page_texts.items())[:10]},
        ensure_ascii=False,
        indent=2,
    )
    return f"""아래 청구 원인과 쟁점-주장-근거 트리, 증거 노드, 문서 텍스트 샘플을 교차검증하라.

청구 원인: {claim_type}

트리:
{issues_summary}

증거:
{evidence_summary}

문서 텍스트 샘플:
{text_sample}

출력 JSON 형식:
{{
  "validation": "passed" | "needs_correction",
  "corrections": [
    {{
      "target_issue_id": "issue_1",
      "target_claim_id": "claim_1",
      "action": "add_evidence" | "remove_evidence" | "update_reason" | "add_claim" | "remove_claim",
      "evidence_id": "evidence_node_id",
      "reason": "교차검증 결과에 따른 구체적인 수정 사유"
    }}
  ]
}}

주의:
- validation은 전체 트리가 문서와 일치하고 주장-근거 연결이 타당하면 "passed".
- 불일치, 모순, 근거 없는 주장, 약한 연결고리가 있으면 "needs_correction".
- corrections는 반드시 구체적인 issue_id, claim_id, action, 사유를 포함.
- 증거가 부족하여 주장을 지지할 수 없으면 remove_evidence 또는 remove_claim 권장.
- 다른 설명 금지, JSON 객체만 반환.
"""


def _parse_issue_tree(content: str, claim_type: str) -> dict:
    """[Flow: Step 1 (JSON 펜스 제거) -> Step 2 (JSON 파싱) -> Step 3 (쟁점/주장/근거 스키마 검증)
          -> Step 4 (빈 슬롯 mapped_evidence:[] 주입) -> Step 5 (데이터 계약 형식 반환)]

    LLM 응답 문자열을 3단계 트리 데이터 계약 형식으로 변환한다.
    스키마에 맞지 않는 항목은 건너뛴다. overall_progress_percent는 0으로 초기화.
    """
    cleaned = _strip_json_fence(content)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning(f"[legal-issue-tree] JSON 파싱 실패 claim_type={claim_type}: {cleaned[:200]}")
        return _empty_schema(claim_type)

    if not isinstance(data, dict):
        return _empty_schema(claim_type)

    raw_issues = data.get("issues", [])
    if not isinstance(raw_issues, list):
        return _empty_schema(claim_type)

    issues = []
    for issue_idx, issue_item in enumerate(raw_issues, start=1):
        if not isinstance(issue_item, dict):
            continue
        issue_name = str(issue_item.get("name", "")).strip()
        if not issue_name:
            continue
        issue_id = str(issue_item.get("id", "")).strip() or f"issue_{issue_idx}"
        issue_description = str(issue_item.get("description", "")).strip()

        raw_claims = issue_item.get("claims", [])
        claims = []
        if isinstance(raw_claims, list):
            for claim_idx, claim_item in enumerate(raw_claims, start=1):
                if not isinstance(claim_item, dict):
                    continue
                claim_name = str(claim_item.get("name", "")).strip()
                if not claim_name:
                    continue
                claim_id = str(claim_item.get("id", "")).strip() or f"claim_{issue_idx}_{claim_idx}"
                party = str(claim_item.get("party", "")).strip() or "미상"
                claim_description = str(claim_item.get("description", "")).strip()

                raw_mapped = claim_item.get("mapped_evidence", [])
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

                claims.append({
                    "id": claim_id,
                    "party": party,
                    "name": claim_name,
                    "description": claim_description,
                    "mapped_evidence": mapped_evidence,
                })

        # 쟁점에 최소 2개의 상반된 주장이 없으면 스킵
        if len(claims) < MIN_CLAIMS_PER_ISSUE:
            logger.warning(
                f"[legal-issue-tree] issue={issue_id}에 주장 {len(claims)}개만 있어 스킵 (최소 {MIN_CLAIMS_PER_ISSUE}개 필요)"
            )
            continue

        issues.append({
            "id": issue_id,
            "name": issue_name,
            "description": issue_description,
            "claims": claims,
        })
        if len(issues) >= MAX_ISSUES:
            break

    if len(issues) < MIN_ISSUES:
        logger.warning(
            f"[legal-issue-tree] 쟁점 {len(issues)}개만 추출 (최소 {MIN_ISSUES}개 권장) claim_type={claim_type}"
        )

    return {
        "claim_type": claim_type,
        "overall_progress_percent": 0,
        "cross_validated": False,
        "issues": issues,
    }


def _apply_cross_validation_corrections(issues: list[dict], corrections: list[dict]) -> list[dict]:
    """[Flow: Step 1 (correction 항목 순회) -> Step 2 (target_issue_id/target_claim_id 매칭)
          -> Step 3 (action별 처리) -> Step 4 (수정된 트리 반환)]

    교차검증 결과에 따라 트리를 수정한다. remove_evidence, update_reason, remove_claim 등을 처리.
    """
    issue_map = {issue["id"]: issue for issue in issues}
    claim_map = {}
    for issue in issues:
        for claim in issue.get("claims", []):
            claim_map[claim["id"]] = claim

    for correction in corrections:
        if not isinstance(correction, dict):
            continue
        action = str(correction.get("action", "")).strip()
        target_issue_id = str(correction.get("target_issue_id", "")).strip()
        target_claim_id = str(correction.get("target_claim_id", "")).strip()
        evidence_id = str(correction.get("evidence_id", "")).strip()

        if not target_claim_id or not action:
            continue

        claim = claim_map.get(target_claim_id)
        if not claim:
            continue

        if action == "remove_evidence" and evidence_id:
            claim["mapped_evidence"] = [
                ev for ev in claim.get("mapped_evidence", []) if ev["evidence_id"] != evidence_id
            ]
        elif action == "update_reason" and evidence_id:
            new_reason = str(correction.get("reason", "")).strip()
            for ev in claim.get("mapped_evidence", []):
                if ev["evidence_id"] == evidence_id:
                    ev["reason"] = new_reason
        elif action == "remove_claim":
            issue = issue_map.get(target_issue_id)
            if issue:
                issue["claims"] = [c for c in issue.get("claims", []) if c["id"] != target_claim_id]

    return issues


def _empty_schema(claim_type: str) -> dict:
    """빈 3단계 트리 스키마 반환 (LLM 실패/파싱 실패 폴백용)."""
    return {
        "claim_type": claim_type,
        "overall_progress_percent": 0,
        "cross_validated": False,
        "issues": [],
    }


def extract_issue_claim_tree(
    claim_type: str,
    evidence_nodes: list[dict],
    page_texts: dict[int, str],
    endpoint: str,
    model: str,
    api_key: str,
    db: Session | None = None,
    user=None,
) -> dict:
    """[Flow: Step 1 (프롬프트 구성) -> Step 2 (1차 LLM: 쟁점-주장-근거 트리 추출 + step 크레딧 차감)
          -> Step 3 (2차 LLM: 문서 교차검증 + step 크레딧 차감) -> Step 4 (교차검증 결과 적용)
          -> Step 5 (데이터 계약 형식 반환)]

    입력된 청구 원인과 증거/문서 텍스트를 바탕으로 3단계 트리를 추출하고 교차검증한다.
    db와 user가 제공되면 각 LLM 호출 직전에 1 step = 1 credit(1000 milli-USD)를 차감한다.
    LLM 호출 실패 시 빈 스키마를 반환한다 (예외 전파하지 않음).
    """
    claim_type = (claim_type or "").strip()
    if not claim_type:
        return _empty_schema("")

    try:
        if db and user:
            spend_agent_step(db, user, "AI agent: issue tree extraction")
        tree_prompt = _build_issue_tree_prompt(claim_type)
        tree_content, _ = call_text(tree_prompt, endpoint, model, api_key, max_tokens=MAX_TOKENS)
        mappings = _parse_issue_tree(tree_content, claim_type)
    except Exception as e:
        logger.warning(f"[legal-issue-tree] 트리 추출 실패 claim_type={claim_type}: {e}")
        return _empty_schema(claim_type)

    if not mappings.get("issues"):
        return mappings

    try:
        if db and user:
            spend_agent_step(db, user, "AI agent: issue tree cross validation")
        validation_prompt = _build_cross_validation_prompt(
            claim_type,
            mappings["issues"],
            evidence_nodes,
            page_texts,
        )
        validation_content, _ = call_text(
            validation_prompt, endpoint, model, api_key, max_tokens=MAX_CROSS_VALIDATION_TOKENS
        )
        cleaned = _strip_json_fence(validation_content)
        validation_data = json.loads(cleaned)
        if isinstance(validation_data, dict):
            corrections = validation_data.get("corrections", [])
            if isinstance(corrections, list) and corrections:
                mappings["issues"] = _apply_cross_validation_corrections(
                    mappings["issues"], corrections
                )
            mappings["cross_validated"] = validation_data.get("validation") == "passed"
        else:
            mappings["cross_validated"] = False
    except Exception as e:
        logger.warning(f"[legal-issue-tree] 교차검증 실패 claim_type={claim_type}: {e}")
        mappings["cross_validated"] = False

    return mappings


def compute_overall_progress(mappings: dict) -> int:
    """[Flow: Step 1 (쟁점/주장 목록 순회) -> Step 2 (1개 이상 근거가 매핑된 주장 카운트)
          -> Step 3 (비율 % 계산)]

    3단계 트리 상태에서 전체 주장 중 1개 이상의 근거가 매핑된 주장의 비율(%)을 계산한다.
    주장이 없으면 0% 반환.
    """
    issues = mappings.get("issues", []) if isinstance(mappings, dict) else []
    total_claims = 0
    filled_claims = 0
    for issue in issues:
        for claim in issue.get("claims", []):
            total_claims += 1
            if claim.get("mapped_evidence"):
                filled_claims += 1
    if total_claims == 0:
        return 0
    return round(filled_claims / total_claims * 100)
