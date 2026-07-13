// [Flow: Step 1 (쟁점 목록 순회) -> Step 2 (각 쟁점 아래 양측 주장 렌더링) -> Step 3 (각 주장 아래 매핑된 근거 렌더링)
//       -> Step 4 (useDroppable로 주장 슬롯에 드롭 영역 제공) -> Step 5 (근거 제거 버튼)]
// 쟁점 → 주장 → 근거 3단계 트리를 부모/자식/손자 계층으로 시각화하는 컴포넌트.
// 쟁점은 최상위 부모, 주장은 중간 자식, 근거는 최하위 손자로 들여쓰기와 색상으로 구분한다.
import { useDroppable } from "@dnd-kit/core";
import { useTranslation } from "react-i18next";
import { X, FileText, Scale, MessageSquareQuote, User } from "lucide-react";

/**
 * ClaimNode — 단일 주장 슬롯. useDroppable로 드롭 영역 제공.
 *
 * @param {Object} props
 * @param {Object} props.claim - 주장 ({id, party, name, description, mapped_evidence: []})
 * @param {Function} props.onRemoveEvidence - 근거 제거 콜백 (claimId, evidenceId) => void
 */
function ClaimNode({ claim, onRemoveEvidence }) {
  const { t } = useTranslation();
  const { setNodeRef, isOver } = useDroppable({
    id: claim.id,
    data: { type: "claim-slot", claimId: claim.id },
  });

  const mappedEvidence = claim.mapped_evidence || [];
  const partyColor =
    claim.party === "원고" || claim.party === "검사" || claim.party === "의뢰인"
      ? "border-blue-400 bg-blue-50/50"
      : "border-orange-400 bg-orange-50/50";

  return (
    <div
      ref={setNodeRef}
      className={`rounded-lg border-l-4 ${partyColor} transition-all duration-200 ${
        isOver ? "ring-2 ring-emerald-400 bg-emerald-50/50" : ""
      }`}
      data-oid="claim-node"
    >
      {/* 주장 헤더 */}
      <div className="px-3 py-2 border-b border-outline-variant/50">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <User size={12} className="text-on-surface-variant flex-shrink-0" />
            <span className="text-[10px] font-semibold uppercase tracking-wide text-on-surface-variant">
              {claim.party}
            </span>
          </div>
          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-surface-container-high text-on-surface-variant">
            {mappedEvidence.length}
          </span>
        </div>
        <h5 className="text-xs font-semibold text-on-surface mt-1">{claim.name}</h5>
        {claim.description ? (
          <p className="text-[10px] text-on-surface-variant mt-0.5 line-clamp-2">{claim.description}</p>
        ) : null}
      </div>

      {/* 매핑된 근거 리스트 (손자) */}
      <div className="px-3 py-2">
        {mappedEvidence.length === 0 ? (
          <p className="text-[10px] text-on-surface-variant/60 text-center py-3 border border-dashed border-outline-variant rounded-md">
            {t("page:result.mapperDropHere")}
          </p>
        ) : (
          <div className="flex flex-col gap-1.5">
            {mappedEvidence.map((ev) => (
              <div
                key={ev.evidence_id}
                className="relative rounded-md border border-emerald-200 bg-surface-container-lowest pl-2 pr-1.5 py-1.5 group"
                data-oid="evidence-node"
              >
                <div className="absolute left-0 top-0 bottom-0 w-0.5 bg-emerald-400 rounded-l-md" />
                <div className="flex items-start gap-1.5">
                  <FileText size={10} className="text-emerald-600 flex-shrink-0 mt-0.5" />
                  <div className="min-w-0 flex-1">
                    <p className="text-[11px] text-emerald-800 line-clamp-2">{ev.text_snippet}</p>
                    {ev.source_doc ? (
                      <p className="text-[9px] text-emerald-600 mt-0.5">{ev.source_doc}</p>
                    ) : null}
                    {ev.reason ? (
                      <div className="mt-1 flex items-start gap-1 text-[9px] text-on-surface-variant bg-surface-container-high/50 rounded px-1 py-0.5">
                        <MessageSquareQuote size={8} className="flex-shrink-0 mt-0.5 text-primary/70" />
                        <span className="line-clamp-3">
                          <span className="font-semibold text-on-surface-variant/80">
                            {t("page:result.mapperReason")}: 
                          </span>
                          {ev.reason}
                        </span>
                      </div>
                    ) : null}
                  </div>
                  <button
                    onClick={() => onRemoveEvidence(claim.id, ev.evidence_id)}
                    className="opacity-0 group-hover:opacity-100 p-0.5 hover:bg-error/10 rounded text-error flex-shrink-0"
                    title={t("page:result.mapperRemoveEvidence")}
                  >
                    <X size={10} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * IssueNode — 단일 쟁점 카드 (부모). 아래에 양측 주장(자식)을 포함.
 *
 * @param {Object} props
 * @param {Object} props.issue - 쟁점 ({id, name, description, claims: []})
 * @param {Function} props.onRemoveEvidence - 근거 제거 콜백
 */
function IssueNode({ issue, onRemoveEvidence }) {
  const claims = issue.claims || [];

  return (
    <div
      className="rounded-xl border border-outline-variant bg-surface-container shadow-sm overflow-hidden"
      data-oid="issue-node"
    >
      {/* 쟁점 헤더 (부모) */}
      <div className="px-4 py-3 border-l-4 border-red-400 bg-surface-container-high">
        <div className="flex items-center gap-1.5">
          <Scale size={14} className="text-red-500 flex-shrink-0" />
          <h4 className="text-sm font-bold text-on-surface">{issue.name}</h4>
        </div>
        {issue.description ? (
          <p className="text-xs text-on-surface-variant mt-1 line-clamp-2">{issue.description}</p>
        ) : null}
      </div>

      {/* 주장 리스트 (자식) */}
      <div className="px-4 py-3 flex flex-col gap-2">
        {claims.map((claim) => (
          <ClaimNode key={claim.id} claim={claim} onRemoveEvidence={onRemoveEvidence} />
        ))}
      </div>
    </div>
  );
}

/**
 * IssueTreeView — 모든 쟁점을 단일 컬럼 리스트로 렌더링.
 * 쟁점(부모) → 주장(자식) → 근거(손자)의 계층 구조를 수직으로 명확히 구분한다.
 *
 * @param {Object} props
 * @param {Array} props.issues - 쟁점 목록
 * @param {Function} props.onRemoveEvidence - 근거 제거 콜백 (claimId, evidenceId) => void
 */
export default function IssueTreeView({ issues, onRemoveEvidence }) {
  if (!issues || issues.length === 0) return null;

  return (
    <div className="flex flex-col gap-3 overflow-y-auto pr-1 pb-2" data-oid="issue-tree-list">
      {issues.map((issue) => (
        <IssueNode key={issue.id} issue={issue} onRemoveEvidence={onRemoveEvidence} />
      ))}
    </div>
  );
}
