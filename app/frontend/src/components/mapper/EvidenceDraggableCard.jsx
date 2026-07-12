// [Flow: Step 1 (useDraggable 훅으로 드래그 활성화) -> Step 2 (drag 시 transform 적용) -> Step 3 (증거 카드 시각적 피드백)]
// e-Discovery 그래프의 evidence 노드를 드래그 가능한 카드로 감싸는 컴포넌트.
// @dnd-kit/core의 useDraggable 훅 사용. 드래그 중 투명도/스케일 transform 적용.
import { useDraggable } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import { FileText } from "lucide-react";

/**
 * EvidenceDraggableCard — 단일 증거(evidence) 노드를 드래그 가능한 카드로 렌더링.
 *
 * @param {Object} props
 * @param {Object} props.evidence - 증거 노드 ({id, label, page, summary?})
 * @param {boolean} [props.disabled] - 드래그 비활성화 (이미 매핑된 증거 등)
 */
export default function EvidenceDraggableCard({ evidence, disabled = false }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: evidence.id,
    data: { type: "evidence", evidence },
    disabled,
  });

  const style = {
    transform: CSS.Translate.toString(transform),
    opacity: isDragging ? 0.5 : disabled ? 0.4 : 1,
    zIndex: isDragging ? 50 : "auto",
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      className={`select-none rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-2 cursor-grab active:cursor-grabbing transition-shadow hover:shadow-md ${
        disabled ? "cursor-not-allowed" : ""
      } ${isDragging ? "shadow-lg ring-2 ring-emerald-400" : ""}`}
      data-oid="evidence-draggable-card"
      title={evidence.summary || evidence.label}
    >
      <div className="flex items-start gap-2">
        <FileText size={14} className="text-emerald-600 flex-shrink-0 mt-0.5" />
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-emerald-800 line-clamp-2">{evidence.label}</p>
          {evidence.page ? (
            <p className="text-[10px] text-emerald-600 mt-0.5">P.{evidence.page}</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
