// [Flow: Step 1 (각 요건사실별 useDroppable 슬롯 생성) -> Step 2 (드래그 오버 시 시각적 하이라이트)
//       -> Step 3 (드롭 시 onDrop 콜백 호출) -> Step 4 (매핑된 증거 카드 목록 렌더링 + 제거 버튼)]
// 법적 요건사실별 빈 슬롯(점선 테두리)을 제공하고 드롭된 증거를 시각적으로 안착시키는 컴포넌트.
import { useDroppable } from "@dnd-kit/core";
import { useTranslation } from "react-i18next";
import { X, FileText } from "lucide-react";

/**
 * ElementSlot — 단일 법적 요건사실 슬롯. useDroppable로 드롭 영역 제공.
 *
 * @param {Object} props
 * @param {Object} props.element - 요건사실 ({id, name, description, mapped_evidence: []})
 * @param {Function} props.onRemoveEvidence - 증거 제거 콜백 (elementId, evidenceId) => void
 */
function ElementSlot({ element, onRemoveEvidence }) {
  const { t } = useTranslation();
  const { setNodeRef, isOver } = useDroppable({
    id: element.id,
    data: { type: "element-slot", elementId: element.id },
  });

  const mappedEvidence = element.mapped_evidence || [];

  return (
    <div
      ref={setNodeRef}
      className={`rounded-lg p-4 border-2 border-dashed transition-colors min-h-[120px] ${
        isOver
          ? "border-blue-500 bg-blue-50"
          : "border-gray-300 bg-surface-container-lowest"
      }`}
      data-oid="element-slot"
    >
      {/* 요건사실 헤더 */}
      <div className="mb-2">
        <div className="flex items-center justify-between gap-2">
          <h4 className="text-sm font-semibold text-on-surface">{element.name}</h4>
          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-surface-container-high text-on-surface-variant flex-shrink-0">
            {mappedEvidence.length}
          </span>
        </div>
        {element.description ? (
          <p className="text-xs text-on-surface-variant mt-1 line-clamp-2">{element.description}</p>
        ) : null}
      </div>

      {/* 매핑된 증거 카드 목록 */}
      <div className="flex flex-col gap-1.5">
        {mappedEvidence.length === 0 ? (
          <p className="text-xs text-on-surface-variant/60 text-center py-4">
            {t("page:result.mapperDropHere")}
          </p>
        ) : (
          mappedEvidence.map((ev) => (
            <div
              key={ev.evidence_id}
              className="flex items-start gap-2 rounded-md border border-emerald-200 bg-emerald-50/70 px-2 py-1.5 group"
              data-oid="mapped-evidence-card"
            >
              <FileText size={12} className="text-emerald-600 flex-shrink-0 mt-0.5" />
              <div className="min-w-0 flex-1">
                <p className="text-xs text-emerald-800 line-clamp-2">{ev.text_snippet}</p>
                {ev.source_doc ? (
                  <p className="text-[10px] text-emerald-600 mt-0.5">{ev.source_doc}</p>
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
          ))
        )}
      </div>
    </div>
  );
}

/**
 * ElementDroppableSlots — 모든 법적 요건사실 슬롯을 그리드로 렌더링.
 *
 * @param {Object} props
 * @param {Array} props.elements - 요건사실 목록
 * @param {Function} props.onRemoveEvidence - 증거 제거 콜백 (elementId, evidenceId) => void
 */
export default function ElementDroppableSlots({ elements, onRemoveEvidence }) {
  if (!elements || elements.length === 0) return null;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 overflow-y-auto pr-1" data-oid="element-slots-grid">
      {elements.map((el) => (
        <ElementSlot key={el.id} element={el} onRemoveEvidence={onRemoveEvidence} />
      ))}
    </div>
  );
}
