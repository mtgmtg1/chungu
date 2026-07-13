// [Flow: Step 1 (각 주장별 useDroppable 영역 생성) -> Step 2 (드래그 오버 시 시각적 하이라이트)
//       -> Step 3 (드롭 시 onDrop 콜백 호출) -> Step 4 (부모 주장 카드 + 자식 증거 리스트 렌더링 + 제거 버튼)]
// 법적 주장(Claim)별 드롭 영역을 제공하고, 드롭된 증거를 부모/자식 계층 구조로 시각화하는 컴포넌트.
// 매핑된 증거에는 LLM이 파악한 주장-증거 관계(reason)를 함께 표시한다.
import { useDroppable } from "@dnd-kit/core";
import { useTranslation } from "react-i18next";
import { X, FileText, MessageSquareQuote } from "lucide-react";

/**
 * ClaimSlot — 단일 주장 슬롯. 부모 카드와 자식 증거 리스트로 구성된 드롭 영역.
 *
 * @param {Object} props
 * @param {Object} props.element - 주장 ({id, name, description, mapped_evidence: []})
 * @param {Function} props.onRemoveEvidence - 증거 제거 콜백 (elementId, evidenceId) => void
 */
function ClaimSlot({ element, onRemoveEvidence }) {
  const { t } = useTranslation();
  const { setNodeRef, isOver } = useDroppable({
    id: element.id,
    data: { type: "element-slot", elementId: element.id },
  });

  const mappedEvidence = element.mapped_evidence || [];
  const hasEvidence = mappedEvidence.length > 0;

  return (
    <div
      ref={setNodeRef}
      className={`rounded-xl border transition-all duration-200 overflow-hidden ${
        isOver
          ? "border-blue-500 bg-blue-50/60 shadow-md"
          : "border-outline-variant bg-surface-container shadow-sm"
      }`}
      data-oid="claim-slot"
    >
      {/* 부모 주장 카드 헤더 */}
      <div className="px-4 py-3 border-l-4 border-primary bg-surface-container-high">
        <div className="flex items-center justify-between gap-2">
          <h4 className="text-sm font-bold text-on-surface">{element.name}</h4>
          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-primary/10 text-primary flex-shrink-0">
            {mappedEvidence.length}
          </span>
        </div>
        {element.description ? (
          <p className="text-xs text-on-surface-variant mt-1 line-clamp-2">{element.description}</p>
        ) : null}
      </div>

      {/* 자식 증거 리스트 */}
      <div className={`px-4 ${hasEvidence ? "py-3" : "py-2"}`}>
        {!hasEvidence ? (
          <p className="text-xs text-on-surface-variant/60 text-center py-4 border border-dashed border-outline-variant rounded-lg">
            {t("page:result.mapperDropHere")}
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {mappedEvidence.map((ev) => (
              <div
                key={ev.evidence_id}
                className="relative rounded-lg border border-emerald-200 bg-surface-container-lowest pl-3 pr-2 py-2 group"
                data-oid="mapped-evidence-card"
              >
                {/* 부모-자식 연결 가이드라인 */}
                <div className="absolute left-0 top-0 bottom-0 w-1 bg-emerald-400 rounded-l-lg" />
                <div className="flex items-start gap-2">
                  <FileText size={12} className="text-emerald-600 flex-shrink-0 mt-0.5" />
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium text-emerald-800 line-clamp-2">{ev.text_snippet}</p>
                    {ev.source_doc ? (
                      <p className="text-[10px] text-emerald-600 mt-0.5">{ev.source_doc}</p>
                    ) : null}
                    {ev.reason ? (
                      <div className="mt-1.5 flex items-start gap-1 text-[10px] text-on-surface-variant bg-surface-container-high/50 rounded-md px-1.5 py-1">
                        <MessageSquareQuote size={10} className="flex-shrink-0 mt-0.5 text-primary/70" />
                        <span className="line-clamp-3">
                          <span className="font-semibold text-on-surface-variant/80">{t("page:result.mapperReason")}: </span>
                          {ev.reason}
                        </span>
                      </div>
                    ) : null}
                  </div>
                  <button
                    onClick={() => onRemoveEvidence(element.id, ev.evidence_id)}
                    className="opacity-0 group-hover:opacity-100 p-0.5 hover:bg-error/10 rounded text-error flex-shrink-0"
                    title={t("page:result.mapperRemoveEvidence")}
                  >
                    <X size={12} />
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
 * ElementDroppableSlots — 모든 주장 슬롯을 단일 컬럼 리스트로 렌더링.
 * 부모(주장)와 자식(증거)의 계층 구조를 수직으로 명확히 구분한다.
 *
 * @param {Object} props
 * @param {Array} props.elements - 주장 목록
 * @param {Function} props.onRemoveEvidence - 증거 제거 콜백 (elementId, evidenceId) => void
 */
export default function ElementDroppableSlots({ elements, onRemoveEvidence }) {
  if (!elements || elements.length === 0) return null;

  return (
    <div className="flex flex-col gap-3 overflow-y-auto pr-1 pb-2" data-oid="element-slots-list">
      {elements.map((el) => (
        <ClaimSlot key={el.id} element={el} onRemoveEvidence={onRemoveEvidence} />
      ))}
    </div>
  );
}
