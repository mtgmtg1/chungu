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

from ..core.markdown_sanitizer import sanitize_markdown_for_llm
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


def _build_issue_tree_prompt(claim_type: str, user_language: str = "ko") -> str:
    """[Flow: Step 1 (청구 원인 삽입) -> Step 2 (3단계 트리 추출 지시) -> Step 3 (JSON 스키마 명시) -> Step 4 (주의사항)]

    입력된 청구 원인에서 쟁점-주장-근거 3단계 트리를 추출하는 LLM 프롬프트를 구성한다.
    양측(원고/피고, 검사/피고인 등)이 첨예하게 대립하는 쟁점을 중심으로 구성한다.
    """
    return f"""For the claim type below, derive {MIN_ISSUES}~{MAX_ISSUES} sharply disputed issues where two opposing sides (plaintiff/defendant, prosecutor/accused, etc.) confront each other under the relevant legal system. For each issue, construct a 3-level tree of the opposing sides' claims and the evidence supporting each claim.

Claim type: {claim_type}

Output JSON format:
{{
  "claim_type": "{claim_type}",
  "issues": [
    {{
      "id": "issue_1",
      "name": "Concise name of the issue in the user's configured language ({user_language})",
      "description": "1-2 sentence explanation of what the issue asks",
      "claims": [
        {{
          "id": "claim_1",
          "party": "plaintiff or prosecutor",
          "name": "Concise name of the claim in the user's configured language ({user_language})",
          "description": "1-2 sentence explanation of the claim's meaning and the key facts needed to prove it",
          "mapped_evidence": [
            {{
              "evidence_id": "evidence_node_id",
              "text_snippet": "Summary of evidence text",
              "source_doc": "P.5",
              "reason": "Specific factual/legal connection explaining how this evidence supports the claim"
            }}
          ]
        }},
        {{
          "id": "claim_2",
          "party": "defendant or accused",
          "name": "Concise name of the opposing claim in the user's configured language ({user_language})",
          "description": "1-2 sentence explanation of the opposing claim's meaning and the key facts needed to prove it",
          "mapped_evidence": []
        }}
      ]
    }}
  ]
}}

Notes:
- Write between {MIN_ISSUES} and {MAX_ISSUES} issues.
- Each issue must include 2 or more opposing claims (e.g., plaintiff claim vs defendant claim).
- Assign ids sequentially: "issue_1", "issue_2", "claim_1", "claim_2", etc.
- party should specify the actual opposing party, e.g., "plaintiff", "defendant", "prosecutor", "accused", "client", "opponent".
- mapped_evidence is filled automatically by the LLM when evidence nodes are provided. Each item must be in {{"evidence_id", "text_snippet", "source_doc", "reason"}} format.
- reason must describe both the factual connection and the legal meaning of how the evidence supports the claim.
- Derive based on the legal system (supreme court precedents/doctrines) of the relevant jurisdiction.
- No other explanation; return only the JSON object.
"""


def _build_cross_validation_prompt(
    claim_type: str,
    issues: list[dict],
    evidence_nodes: list[dict],
    page_texts: dict[int, str],
    user_language: str = "ko",
) -> str:
    """[Flow: Step 1 (트리/증거/텍스트 직렬화) -> Step 2 (교차검증 지시) -> Step 3 (JSON 스키마 명시) -> Step 4 (주의사항)]

    추출된 쟁점-주장-근거 트리가 문서 내용과 일치하는지, 주장-근거 연결이 사실적으로 타당한지
    교차검증하도록 유도하는 LLM 프롬프트를 구성한다.
    """
    page_texts = {k: sanitize_markdown_for_llm(v) for k, v in page_texts.items()}
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
    return f"""Cross-validate the claim type, issue-claim-evidence tree, evidence nodes, and document text sample below.

Claim type: {claim_type}

Tree:
{issues_summary}

Evidence:
{evidence_summary}

Document text sample:
{text_sample}

Output JSON format:
{{
  "validation": "passed" | "needs_correction",
  "corrections": [
    {{
      "target_issue_id": "issue_1",
      "target_claim_id": "claim_1",
      "action": "add_evidence" | "remove_evidence" | "update_reason" | "add_claim" | "remove_claim",
      "evidence_id": "evidence_node_id",
      "reason": "Specific reason for the correction based on the cross-validation result. Write in the user's configured language ({user_language})."
    }}
  ]
}}

Notes:
- validation is "passed" if the entire tree matches the document and the claim-evidence connections are factually valid.
- If there are inconsistencies, contradictions, unsupported claims, or weak connections, use "needs_correction".
- corrections must include specific issue_id, claim_id, action, and reason.
- If evidence is insufficient to support a claim, recommend remove_evidence or remove_claim.
- No other explanation; return only the JSON object.
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

    user_language = user.language if user and getattr(user, "language", None) else "ko"
    try:
        if db and user:
            spend_agent_step(db, user, "AI agent: issue tree extraction")
        tree_prompt = _build_issue_tree_prompt(claim_type, user_language=user_language)
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
            user_language=user_language,
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
