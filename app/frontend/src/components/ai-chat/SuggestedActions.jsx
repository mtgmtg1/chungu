// [Flow: Step 1 (빈 상태에서 제안 액션 표시) -> Step 2 (사용자 클릭 시 메시지 전송)]
// Vercel ai-chatbot 템플릿의 suggested-actions.tsx 포팅.
// 메시지가 없을 때 입력창 위에 제안 칩을 표시한다.
import { useTranslation } from "react-i18next";

// [Flow: 컨텍스트별 제안 액션 정의]
function useSuggestedActions(context) {
  const { t } = useTranslation();
  const sourceType = context?.sourceType;
  const activeEditor = context?.activeEditor;

  // PDF 주석 컨텍스트
  if (sourceType === "pdf" || sourceType === "docx" || sourceType === "hwp") {
    return [
      {
        title: t("page:agent.suggestHighlightTitle", "현재 페이지 하이라이트"),
        label: t("page:agent.suggestHighlightLabel", "주요 항목 강조"),
        prompt: t("page:agent.suggestHighlightPrompt", "이 페이지의 주요 항목을 하이라이트해줘."),
      },
      {
        title: t("page:agent.suggestCalloutTitle", "코멘트 추가"),
        label: t("page:agent.suggestCalloutLabel", "중요 부분에 메모"),
        prompt: t("page:agent.suggestCalloutPrompt", "중요한 부분에 코멘트를 달아줘."),
      },
    ];
  }

  // 마크다운 에디터 컨텍스트
  if (activeEditor === "markdown") {
    return [
      {
        title: t("page:agent.suggestImproveTitle", "글 다듬기"),
        label: t("page:agent.suggestImproveLabel", "문장 개선"),
        prompt: t("page:agent.suggestImprovePrompt", "마크다운 텍스트를 더 읽기 쉽게 다듬어줘."),
      },
      {
        title: t("page:agent.suggestFormatTitle", "표 형식 정리"),
        label: t("page:agent.suggestFormatLabel", "구조화"),
        prompt: t("page:agent.suggestFormatPrompt", "마크다운 표 형식을 정리해줘."),
      },
    ];
  }

  // 스프레드시트 컨텍스트
  if (activeEditor === "xlsxBasic" || activeEditor === "xlsxAdvanced") {
    return [
      {
        title: t("page:agent.suggestCellTitle", "셀 업데이트"),
        label: t("page:agent.suggestCellLabel", "값 수정"),
        prompt: t("page:agent.suggestCellPrompt", "첫 번째 시트의 A1 셀 값을 확인해줘."),
      },
      {
        title: t("page:agent.suggestRowTitle", "행 추가"),
        label: t("page:agent.suggestRowLabel", "데이터 입력"),
        prompt: t("page:agent.suggestRowPrompt", "시트 맨 아래에 새 행을 추가해줘."),
      },
    ];
  }

  // 기본 제안
  return [
    {
      title: t("page:agent.suggestDefaultTitle1", "PDF 주석"),
      label: t("page:agent.suggestDefaultLabel1", "하이라이트/코멘트"),
      prompt: t("page:agent.suggestDefaultPrompt1", "현재 문서의 주요 항목을 하이라이트해줘."),
    },
    {
      title: t("page:agent.suggestDefaultTitle2", "마크다운 편집"),
      label: t("page:agent.suggestDefaultLabel2", "글 다듬기"),
      prompt: t("page:agent.suggestDefaultPrompt2", "마크다운 텍스트를 더 읽기 쉽게 다듬어줘."),
    },
  ];
}

/**
 * SuggestedActions — 메시지가 없을 때 입력창 위에 제안 칩을 표시한다.
 *
 * @param {Object} props
 * @param {Object} props.context - 에이전트 컨텍스트 (sourceType, activeEditor 등)
 * @param {(prompt: string) => void} props.onSelect - 제안 선택 시 호출될 콜백
 */
export default function SuggestedActions({ context, onSelect }) {
  const actions = useSuggestedActions(context);

  return (
    <div className="flex flex-wrap gap-2 sm:hidden md:flex">
      {actions.map((action, index) => (
        <button
          key={`${action.title}-${index}`}
          type="button"
          onClick={() => onSelect(action.prompt)}
          className="flex flex-col items-start gap-1 rounded-xl border border-outline-variant/40 bg-surface-container-lowest/60 p-3 text-left transition-all hover:border-primary/30 hover:bg-surface-container-low/60 hover:shadow-sm md:flex-1"
        >
          <span className="font-medium text-sm text-on-surface">{action.title}</span>
          <span className="text-xs text-on-surface-variant">{action.label}</span>
        </button>
      ))}
    </div>
  );
}
