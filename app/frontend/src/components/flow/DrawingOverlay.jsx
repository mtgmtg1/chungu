// [Flow: Step 1 (ViewportPortal로 flow 좌표계 SVG 렌더링) -> Step 2 (저장된 경로 + 현재 경로 + 텍스트 주석 표시) -> Step 3 (드로잉 모드일 때만 pointer 이벤트 활성)]
// React Flow 캔버스 위 드로잉 오버레이 — ViewportPortal로 pan/zoom 자동 따라감.
import { memo } from "react";
import { ViewportPortal } from "@xyflow/react";

/**
 * 드로잉 오버레이 — React Flow의 ViewportPortal 내부에 SVG를 렌더링.
 * 모든 path/텍스트는 flow 좌표계로 저장되어 pan/zoom 시 자동 이동.
 *
 * [Flow: Step 1 (드로잉 모드 확인) -> Step 2 (SVG path 렌더링) -> Step 3 (텍스트 주석 렌더링) -> Step 4 (pointer 이벤트 전달)]
 *
 * @param {Object} props
 * @param {boolean} props.isActive - 드로잉 모드 활성화 여부
 * @param {Array} props.paths - 저장된 드로잉 경로 배열
 * @param {string} props.currentPathD - 현재 그리는 중인 경로의 SVG path
 * @param {string} props.strokeColor - 현재 선 색상
 * @param {number} props.strokeWidth - 현재 선 굵기
 * @param {boolean} props.isShapeMode - 도형 모드 여부
 * @param {Array} props.textAnnotations - 텍스트 주석 배열
 * @param {Function} props.onPointerDown - 드로잉 시작 핸들러
 * @param {Function} props.onPointerMove - 드로잉 중 핸들러
 * @param {Function} props.onPointerUp - 드로잉 종료 핸들러
 * @param {Function} [props.onDeleteText] - 텍스트 주석 삭제 핸들러
 * @returns {JSX.Element} 드로잉 오버레이 컴포넌트
 */
function DrawingOverlay({
  isActive,
  paths,
  currentPathD,
  strokeColor,
  strokeWidth,
  isShapeMode,
  textAnnotations,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  onDeleteText,
}) {
  return (
    <ViewportPortal>
      {/* 드로잉 이벤트 수신용 투명 오버레이 — 드로잉 모드일 때만 pointer 활성.
          z-index를 노드(기본 1)보다 높여 캔버스 모든 영역에서 드로잉 이벤트를 수신.
          width/height를 100%가 아닌 매우 큰 값으로 설정하여, ViewportPortal 내부
          (flow 좌표계)에서 노드와 멀리 떨어진 빈 캔버스 영역까지 커버.
          top/left를 음수 오프셋으로 중앙 정렬하여 음수 flow 좌표도 커버. */}
      <div
        className="nopan nodrag"
        style={{
          position: "absolute",
          top: -50000,
          left: -50000,
          width: 100000,
          height: 100000,
          pointerEvents: isActive ? "auto" : "none",
          cursor: isActive ? "crosshair" : "default",
          touchAction: "none",
          zIndex: isActive ? 10 : 0,
        }}
        onPointerDown={isActive ? onPointerDown : undefined}
        onPointerMove={isActive ? onPointerMove : undefined}
        onPointerUp={isActive ? onPointerUp : undefined}
        onPointerLeave={isActive ? onPointerUp : undefined}
        onPointerCancel={isActive ? onPointerUp : undefined}
      >
        {/* SVG 드로잉 레이어 — flow 좌표계 기준.
            overflow: visible로 path가 SVG 밖이어도 렌더링. */}
        <svg
          className="absolute"
          style={{ top: 50000, left: 50000, width: 1, height: 1, pointerEvents: "none", overflow: "visible" }}
        >
          {/* 저장된 경로들 */}
          {paths.map((path, i) => {
            const isShape = path.type === "shape";
            // 형광펜 판별: subtype 필드 우선, 없으면 기존 폴백(strokeWidth >= 12)
            const isHighlighter = path.subtype === "highlighter" || (path.strokeWidth >= 12 && path.type === "path" && !path.subtype);
            return (
              <path
                key={path.id || i}
                d={path.d}
                fill={isShape ? "none" : path.stroke}
                stroke={isShape ? path.stroke : "none"}
                strokeWidth={isShape ? path.strokeWidth : undefined}
                strokeLinecap="round"
                strokeLinejoin="round"
                opacity={isHighlighter ? 0.35 : 1}
              />
            );
          })}

          {/* 현재 그리는 중인 경로 (실시간 미리보기) */}
          {currentPathD && (
            <path
              d={currentPathD}
              fill={isShapeMode ? "none" : strokeColor}
              stroke={isShapeMode ? strokeColor : "none"}
              strokeWidth={isShapeMode ? strokeWidth : undefined}
              strokeLinecap="round"
              strokeLinejoin="round"
              opacity={0.8}
            />
          )}

          {/* 텍스트 주석 */}
          {textAnnotations.map((ann) => (
            <text
              key={ann.id}
              x={ann.x}
              y={ann.y}
              fill={ann.color}
              fontSize={ann.fontSize}
              fontFamily="system-ui, sans-serif"
              dominantBaseline="hanging"
              style={{ pointerEvents: "auto", cursor: "default", userSelect: "none" }}
              onDoubleClick={() => onDeleteText?.(ann.id)}
            >
              {ann.text}
            </text>
          ))}
        </svg>
      </div>
    </ViewportPortal>
  );
}

export default memo(DrawingOverlay);
