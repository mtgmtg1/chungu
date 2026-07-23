// [Flow: Step 1 (모드 전환 버튼) -> Step 2 (도구별 옵션 패널) -> Step 3 (색상/굵기/도형 선택) -> Step 4 (undo/clear)]
// React Flow Panel 오버레이에 배치된 드로잉 도구 툴바 — koda-learn CardToolbar 패턴 참고.
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Panel } from "@xyflow/react";
import {
  MousePointer2,
  Pencil,
  Highlighter,
  Eraser,
  Type,
  Shapes,
  Undo2,
  Trash2,
  Minus,
  ArrowRight,
  Square,
  Circle,
} from "lucide-react";

/**
 * 라벨에 단축키를 병합해 툴팁/aria-label 문자열을 생성한다.
 *
 * @param {string} label - 원래 라벨
 * @param {string} [shortcut] - 단축키 문자열
 * @returns {string} 단축키가 있으면 "라벨 (단축키)", 없으면 라벨 그대로
 */
function formatShortcutTitle(label, shortcut) {
  if (!shortcut) return label;
  return `${label} (${shortcut})`;
}

// 색상 팔레트 — 다크모드용 흰색 포함 8색
const COLORS = [
  "#6366f1", // 인디고 (기본)
  "#000000", // 검정
  "#ffffff", // 흰색 (다크모드용)
  "#ef4444", // 빨강
  "#f97316", // 주황
  "#eab308", // 노랑
  "#22c55e", // 초록
  "#3b82f6", // 파랑
];

// 도형 서브메뉴 아이콘
const SHAPE_ICONS = {
  line: Minus,
  arrow: ArrowRight,
  rectangle: Square,
  circle: Circle,
};

/**
 * 드로잉 도구 툴바 — React Flow Panel에 배치.
 * 모드 전환(Select/Pen/Highlighter/Eraser/Text/Shape) + 색상/굵기/도형 선택 + Undo/Clear.
 *
 * [Flow: Step 1 (모드 버튼 클릭) -> Step 2 (도구별 옵션 토글) -> Step 3 (색상/굵기/도형 선택) -> Step 4 (undo/clear 액션)]
 *
 * @param {Object} props
 * @param {string} props.tool - 현재 도구 ("pen" | "highlighter" | "eraser" | "text" | "shape" | "select")
 * @param {Function} props.onToolChange - 도구 변경 콜백
 * @param {string} props.strokeColor - 현재 선 색상
 * @param {Function} props.onStrokeColorChange - 색상 변경 콜백
 * @param {number} props.strokeWidth - 현재 선 굵기
 * @param {Function} props.onStrokeWidthChange - 굵기 변경 콜백
 * @param {string} props.shapeType - 현재 도형 타입
 * @param {Function} props.onShapeTypeChange - 도형 타입 변경 콜백
 * @param {Function} props.onUndo - 실행 취소 콜백
 * @param {Function} props.onClear - 전체 지우기 콜백
 * @param {boolean} props.canUndo - undo 가능 여부
 * @param {Object<string, string>} [props.shortcuts] - 각 도구별 단축키 매핑 (선택)
 * @returns {JSX.Element} 드로잉 툴바 컴포넌트
 */
export default function DrawingToolbar({
  tool,
  onToolChange,
  strokeColor,
  onStrokeColorChange,
  strokeWidth,
  onStrokeWidthChange,
  shapeType,
  onShapeTypeChange,
  onUndo,
  onClear,
  canUndo,
  shortcuts = {},
}) {
  const { t } = useTranslation();
  const [showColors, setShowColors] = useState(false);
  const [showWidth, setShowWidth] = useState(false);
  const [showShapes, setShowShapes] = useState(false);

  const btnClass = "flex items-center justify-center w-10 h-10 md:w-8 md:h-8 rounded-lg text-sm font-medium transition-colors border";
  const btnDefault = "border-outline-variant bg-surface-container-lowest text-on-surface hover:bg-surface-container-high";
  const btnActive = "border-primary bg-primary/10 text-primary";

  const isDrawingTool = tool !== "select";
  const showOptions = tool === "pen" || tool === "highlighter";

  return (
    <Panel position="bottom-center" className="!m-2">
      <div className="flex flex-wrap items-center gap-1 bg-surface-container-lowest rounded-lg shadow-md border border-outline-variant p-1 max-w-[calc(100vw-1rem)]">
        {/* 모드 전환: Select (기본 이동 모드) */}
        <button
          onClick={() => onToolChange("select")}
          title={formatShortcutTitle(t("page:result.flowSelectMode"), shortcuts.select)}
          className={`${btnClass} ${tool === "select" ? btnActive : btnDefault}`}
          aria-label={formatShortcutTitle(t("page:result.flowSelectMode"), shortcuts.select)}
        >
          <MousePointer2 size={16} />
        </button>

        <div className="w-px h-6 bg-outline-variant mx-0.5" />

        {/* 펜 */}
        <button
          onClick={() => onToolChange("pen")}
          title={formatShortcutTitle(t("page:result.flowDraw"), shortcuts.pen)}
          className={`${btnClass} ${tool === "pen" ? btnActive : btnDefault}`}
          aria-label={formatShortcutTitle(t("page:result.flowDraw"), shortcuts.pen)}
        >
          <Pencil size={16} />
        </button>

        {/* 형광펜 */}
        <button
          onClick={() => onToolChange("highlighter")}
          title={formatShortcutTitle(t("page:result.flowHighlight"), shortcuts.highlighter)}
          className={`${btnClass} ${tool === "highlighter" ? btnActive : btnDefault}`}
          aria-label={formatShortcutTitle(t("page:result.flowHighlight"), shortcuts.highlighter)}
        >
          <Highlighter size={16} />
        </button>

        {/* 도형 */}
        <button
          onClick={() => {
            onToolChange("shape");
            setShowShapes((v) => !v);
          }}
          title={formatShortcutTitle(t("page:result.flowShape"), shortcuts.shape)}
          className={`${btnClass} ${tool === "shape" ? btnActive : btnDefault}`}
          aria-label={formatShortcutTitle(t("page:result.flowShape"), shortcuts.shape)}
        >
          <Shapes size={16} />
        </button>

        {/* 텍스트 */}
        <button
          onClick={() => onToolChange("text")}
          title={formatShortcutTitle(t("page:result.flowText"), shortcuts.text)}
          className={`${btnClass} ${tool === "text" ? btnActive : btnDefault}`}
          aria-label={formatShortcutTitle(t("page:result.flowText"), shortcuts.text)}
        >
          <Type size={16} />
        </button>

        {/* 지우개 */}
        <button
          onClick={() => onToolChange("eraser")}
          title={formatShortcutTitle(t("page:result.flowEraser"), shortcuts.eraser)}
          className={`${btnClass} ${tool === "eraser" ? btnActive : btnDefault}`}
          aria-label={formatShortcutTitle(t("page:result.flowEraser"), shortcuts.eraser)}
        >
          <Eraser size={16} />
        </button>

        {/* 도형 서브메뉴 */}
        {tool === "shape" && showShapes && (
          <div className="flex items-center gap-1 ml-1 pl-1 border-l border-outline-variant">
            {Object.entries(SHAPE_ICONS).map(([key, Icon]) => (
              <button
                key={key}
                onClick={() => onShapeTypeChange(key)}
                title={t(`page:result.flowShape${key.charAt(0).toUpperCase() + key.slice(1)}`)}
                className={`${btnClass} ${shapeType === key ? btnActive : btnDefault}`}
                aria-label={t(`page:result.flowShape${key.charAt(0).toUpperCase() + key.slice(1)}`)}
              >
                <Icon size={14} />
              </button>
            ))}
          </div>
        )}

        {/* 색상 선택 (펜/형광펜 모드에서만) */}
        {showOptions && (
          <>
            <div className="w-px h-6 bg-outline-variant mx-0.5" />
            <button
              onClick={() => { setShowColors((v) => !v); setShowWidth(false); }}
              title={t("page:result.flowStrokeColor")}
              className={`${btnClass} ${btnDefault}`}
              aria-label={t("page:result.flowStrokeColor")}
            >
              <div
                className="w-4 h-4 rounded-full border border-outline-variant"
                style={{ backgroundColor: strokeColor }}
              />
            </button>

            {/* 색상 팝오버 */}
            {showColors && (
              <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 bg-surface-container-lowest rounded-lg shadow-lg border border-outline-variant p-2 z-50">
                <div className="grid grid-cols-4 gap-1">
                  {COLORS.map((color) => (
                    <button
                      key={color}
                      onClick={() => { onStrokeColorChange(color); setShowColors(false); }}
                      className={`w-6 h-6 rounded-full border-2 transition-transform hover:scale-110 ${
                        strokeColor === color ? "border-primary ring-2 ring-primary/50" : "border-transparent"
                      }`}
                      style={{ backgroundColor: color }}
                      aria-label={`색상 ${color}`}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* 굵기 선택 */}
            <button
              onClick={() => { setShowWidth((v) => !v); setShowColors(false); }}
              title={t("page:result.flowStrokeWidth")}
              className={`${btnClass} ${btnDefault}`}
              aria-label={t("page:result.flowStrokeWidth")}
            >
              <span className="text-xs font-bold">{strokeWidth}</span>
            </button>

            {/* 굵기 팝오버 — 형광펜은 더 큰 범위(max=40) 지원 */}
            {showWidth && (
              <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 bg-surface-container-lowest rounded-lg shadow-lg border border-outline-variant p-3 z-50">
                <div className="flex flex-col gap-2 w-32">
                  <span className="text-xs text-on-surface-variant">{strokeWidth}px</span>
                  <input
                    type="range"
                    min={tool === "highlighter" ? 4 : 1}
                    max={tool === "highlighter" ? 40 : 20}
                    step={1}
                    value={strokeWidth}
                    onChange={(e) => onStrokeWidthChange(Number(e.target.value))}
                    className="w-full accent-primary"
                  />
                </div>
              </div>
            )}
          </>
        )}

        {/* Undo / Clear (드로잉 도구 활성 시) */}
        {isDrawingTool && (
          <>
            <div className="w-px h-6 bg-outline-variant mx-0.5" />
            <button
              onClick={onUndo}
              disabled={!canUndo}
              title={formatShortcutTitle(t("page:result.flowUndo"), shortcuts.undo)}
              className={`${btnClass} ${btnDefault} ${!canUndo ? "opacity-40 cursor-not-allowed" : ""}`}
              aria-label={formatShortcutTitle(t("page:result.flowUndo"), shortcuts.undo)}
            >
              <Undo2 size={16} />
            </button>
            <button
              onClick={onClear}
              disabled={!canUndo}
              title={formatShortcutTitle(t("page:result.flowClear"), shortcuts.clear)}
              className={`${btnClass} ${btnDefault} ${!canUndo ? "opacity-40 cursor-not-allowed" : ""}`}
              aria-label={formatShortcutTitle(t("page:result.flowClear"), shortcuts.clear)}
            >
              <Trash2 size={16} />
            </button>
          </>
        )}
      </div>
    </Panel>
  );
}
