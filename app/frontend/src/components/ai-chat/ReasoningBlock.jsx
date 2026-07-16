// [Flow: Step 1 (reasoning 텍스트 + streaming 상태 수신)
//       -> Step 2 (기본 접힘 상태로 초기화) -> Step 3 (토글 버튼 렌더링)
//       -> Step 4 (펼침 시 마크다운 HTML로 변환하여 표시)]
// 어시스턴트 메시지의 reasoning(사고) 부분을 접었다 폈다 할 수 있는 블록으로 렌더링한다.
// 기본적으로 접혀 있어, 사고 과정을 보고 싶지 않은 사용자에게 노이즈를 주지 않는다.
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { marked } from "marked";
import { ChevronDown, ChevronRight } from "lucide-react";

/**
 * [Flow: Step 1 (문자열 수신) -> Step 2 (제어 문자 제거) -> Step 3 (정제된 문자열 반환)]
 *
 * 마크다운 파싱 전 제어 문자를 제거하여 안전하게 렌더링한다.
 *
 * @param {string} text - 원본 텍스트
 * @returns {string} 제어 문자가 제거된 텍스트
 */
function sanitizeText(text) {
  return String(text || "").replace(/\u0000/g, "");
}

/**
 * [Flow: Step 1 (reasoning 텍스트를 정제) -> Step 2 (marked로 HTML 변환)
 *       -> Step 3 (실패 시 원본 텍스트 폴백) -> Step 4 (HTML 문자열 반환)]
 *
 * reasoning 텍스트를 마크다운으로 파싱하여 React의 dangerouslySetInnerHTML에 사용할
 * HTML 문자열로 변환한다.
 *
 * @param {string} text - reasoning 텍스트
 * @returns {string} 변환된 HTML
 */
function useReasoningHtml(text) {
  const safeText = sanitizeText(text);

  return useMemo(() => {
    try {
      return marked.parse(safeText, { breaks: true, gfm: true });
    } catch {
      return safeText;
    }
  }, [safeText]);
}

/**
 * [Flow: Step 1 (text, isStreaming props 수신)
 *       -> Step 2 (접힘 상태에 따른 버튼 라벨 결정)
 *       -> Step 3 (토글 클릭 시 상태 반전) -> Step 4 (버튼 + 펼쳐진 내용 렌더링)]
 *
 * ReasoningBlock — 어시스턴트 메시지의 사고 과정을 접을 수 있는 UI 블록.
 *
 * @param {Object} props
 * @param {string} props.text - reasoning 텍스트
 * @param {boolean} [props.isStreaming=false] - 스트리밍 중인지 여부
 */
export default function ReasoningBlock({ text, isStreaming = false }) {
  const { t } = useTranslation();
  const [isExpanded, setIsExpanded] = useState(false);
  const html = useReasoningHtml(text);

  // 텍스트가 비어 있으면 렌더링하지 않는다
  if (!text || !text.trim()) return null;

  /**
   * [Flow: Step 1 (토글 클릭) -> Step 2 (접힘/펼침 상태 반전)]
   */
  const toggleExpanded = () => setIsExpanded((prev) => !prev);

  const collapsedLabel = isStreaming
    ? t("page:agent.thinking", "생각 중…")
    : t("page:agent.showThinking", "생각 과정 보기");
  const buttonLabel = isExpanded
    ? t("page:agent.hideThinking", "생각 과정 숨기기")
    : collapsedLabel;

  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-outline-variant/30 bg-surface-container-low/50 p-2.5">
      <button
        type="button"
        onClick={toggleExpanded}
        className="flex items-center gap-1.5 self-start text-xs font-medium text-on-surface-variant transition-colors hover:text-on-surface"
        aria-expanded={isExpanded}
      >
        {isExpanded ? (
          <ChevronDown size={14} aria-hidden="true" />
        ) : (
          <ChevronRight size={14} aria-hidden="true" />
        )}
        <span>{buttonLabel}</span>
      </button>

      {isExpanded && (
        <div
          className="ai-chat-markdown max-w-full text-[13px] leading-[1.65] text-on-surface-variant"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      )}
    </div>
  );
}
