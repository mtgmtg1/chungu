// [Flow: Step 1 (자식 요소를 감쌀 wrapper 렌더링) -> Step 2 (hover/focus 상태에 따라 tooltip 표시/숨김) -> Step 3 (position prop에 따라 툴팁 위치 결정)]
import { useState } from "react";

/**
 * @description
 * 마우스를 올리거나 포커스하면 작은 설명 말풍선을 표시하는 재사용 가능한 툴팁 컴포넌트입니다.
 * 버튼/아이콘 hover 시 사용자에게 기능을 설명하기 위해 사용합니다.
 *
 * @param {Object} props
 * @param {React.ReactNode} props.children - 툴팁을 적용할 대상 요소
 * @param {string} props.content - 툴팁에 표시할 텍스트
 * @param {string} [props.position="bottom"] - 툴팁 위치 ("top" | "bottom" | "left" | "right")
 * @param {string} [props.className=""] - wrapper에 추가할 클래스
 */
export default function Tooltip({ children, content, position = "bottom", className = "" }) {
  const [visible, setVisible] = useState(false);

  if (!content) return children;

  const positionClasses = {
    top: "bottom-full left-1/2 -translate-x-1/2 mb-2",
    bottom: "top-full left-1/2 -translate-x-1/2 mt-2",
    left: "right-full top-1/2 -translate-y-1/2 mr-2",
    right: "left-full top-1/2 -translate-y-1/2 ml-2",
  };

  const arrowClasses = {
    top: "top-full left-1/2 -translate-x-1/2 -mt-1 border-l-transparent border-r-transparent border-b-0 border-t-on-surface/90",
    bottom: "bottom-full left-1/2 -translate-x-1/2 -mb-1 border-l-transparent border-r-transparent border-t-0 border-b-on-surface/90",
    left: "left-full top-1/2 -translate-y-1/2 -ml-1 border-t-transparent border-b-transparent border-r-0 border-l-on-surface/90",
    right: "right-full top-1/2 -translate-y-1/2 -mr-1 border-t-transparent border-b-transparent border-l-0 border-r-on-surface/90",
  };

  return (
    <div
      className={`relative inline-flex items-center justify-center group ${className}`}
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
      onFocus={() => setVisible(true)}
      onBlur={() => setVisible(false)}
      data-oid="tooltip-wrapper"
    >
      {children}
      {visible && (
        <div
          role="tooltip"
          className={`absolute z-50 pointer-events-none ${positionClasses[position]}`}
          data-oid="tooltip-content"
        >
          <div className="relative">
            <div className="max-w-xs px-2 py-1.5 rounded-md bg-on-surface/90 text-white text-xs font-medium shadow-lg whitespace-nowrap">
              {content}
            </div>
            <div
              className={`absolute w-0 h-0 border-4 ${arrowClasses[position]}`}
              data-oid="tooltip-arrow"
            />
          </div>
        </div>
      )}
    </div>
  );
}
