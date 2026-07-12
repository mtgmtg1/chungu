// [Flow: Step 1 (Bezier 패스 계산) -> Step 2 (빨간 점선 애니메이션 BaseEdge 렌더링)
//       -> Step 3 (EdgeLabelRenderer 포털로 중앙에 "모순 발생" 경고 뱃지 + conflict_reason 툴팁)]
// e-Discovery 타임라인에서 진술과 객관적 증거가 충돌하는 구간을 시각적으로 강조하는 커스텀 엣지.
// Tailwind CSS 애니메이션(animate-dash)으로 점선이 흘러가는 효과를 주어 모순을 직관적으로 전달.
import { useState } from "react";
import {
  BaseEdge,
  getBezierPath,
  EdgeLabelRenderer,
} from "@xyflow/react";
import { AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";

/**
 * AnomalyEdge — 모순(충돌) 엣지 컴포넌트.
 * BaseEdge + SVG path로 빨간 점선을 그리고, EdgeLabelRenderer 포털로
 * 엣지 중앙에 "모순 발생" 경고 뱃지를 렌더링한다.
 * 뱃지 호버 시 data.conflict_reason이 툴팁으로 표시된다.
 *
 * @param {Object} props - React Flow EdgeProps
 * @param {string} props.id - 엣지 ID
 * @param {number} props.sourceX - 출처 X 좌표
 * @param {number} props.sourceY - 출처 Y 좌표
 * @param {number} props.targetX - 대상 X 좌표
 * @param {number} props.targetY - 대상 Y 좌표
 * @param {string} props.sourcePosition - 출처 핸들 위치
 * @param {string} props.targetPosition - 대상 핸들 위치
 * @param {Object} [props.data] - 엣지 데이터 (conflict_reason 포함)
 * @param {boolean} [props.selected] - 선택 여부
 */
export default function AnomalyEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  selected,
}) {
  const { t } = useTranslation();
  const [showReason, setShowReason] = useState(false);

  // Step 1: Bezier 곡선 패스 + 중앙 좌표 계산
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  return (
    <>
      {/* Step 2: 빨간 점선 애니메이션 BaseEdge — 모순을 강렬하게 시각화 */}
      <BaseEdge
        id={id}
        path={edgePath}
        className="animate-dash"
        style={{
          stroke: selected ? "#dc2626" : "#ef4444",
          strokeWidth: selected ? 3.5 : 2.5,
        }}
      />
      {/* 호버 감지용 투명한 클릭 영역 — 툴팁 트리거 */}
      <BaseEdge
        id={`${id}-hit`}
        path={edgePath}
        style={{ strokeWidth: 20, stroke: "transparent", cursor: "pointer" }}
        onMouseEnter={() => setShowReason(true)}
        onMouseLeave={() => setShowReason(false)}
      />

      {/* Step 3: EdgeLabelRenderer 포털로 중앙에 "모순 발생" 경고 뱃지 렌더링 */}
      <EdgeLabelRenderer>
        <div
          style={{
            position: "absolute",
            transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            pointerEvents: "all",
          }}
          className="nodrag nopan"
          onMouseEnter={() => setShowReason(true)}
          onMouseLeave={() => setShowReason(false)}
        >
          <div className="flex items-center gap-1 px-2 py-1 rounded-full bg-red-600 text-white text-[10px] font-bold shadow-md whitespace-nowrap">
            <AlertTriangle size={11} className="flex-shrink-0" />
            {t("page:result.ediscoveryAnomalyBadge")}
          </div>
          {/* conflict_reason 툴팁 — 호버 시 표시 */}
          {showReason && data?.conflict_reason && (
            <div
              className="absolute left-1/2 top-full mt-1 -translate-x-1/2 z-[1000] max-w-[260px] bg-red-900 text-white text-xs rounded-lg px-3 py-2 shadow-lg pointer-events-none"
            >
              {data.conflict_reason}
            </div>
          )}
        </div>
      </EdgeLabelRenderer>
    </>
  );
}
