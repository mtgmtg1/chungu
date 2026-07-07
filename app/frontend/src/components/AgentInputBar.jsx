// [Flow: Step 1 (onOpenChat 콜백 수신) -> Step 2 (중앙 하단 플로팅 입력창 렌더링)
//       -> Step 3 (Enter/버튼 클릭 시 onOpenChat 호출) -> Step 4 (입력값은 AgentChatModal에서 전송)]
// 화면 하단 중앙에 떠 있는 AI 에이전트 입력창.
// Vercel ai-chatbot 템플릿의 PromptInput 스타일을 차용하여 단일 행 composer로 구현한다.
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ArrowUp, Sparkles } from "lucide-react";

/**
 * [Flow: Step 1 (onOpenChat, initialText props 수신) -> Step 2 (입력 상태 관리)
 *       -> Step 3 (입력창 렌더링) -> Step 4 (이벤트 핸들러 등록)]
 *
 * @param {Object} props
 * @param {(text: string) => void} props.onOpenChat - 입력창 활성화 시 호출
 * @param {string} [props.initialText] - 외부에서 전달된 초기 텍스트
 */
export default function AgentInputBar({ onOpenChat, initialText = "" }) {
  const { t } = useTranslation();
  const [text, setText] = useState(initialText);
  const inputRef = useRef(null);

  // [Flow: initialText 변경 시 입력값 동기화]
  useEffect(() => {
    if (initialText) setText(initialText);
  }, [initialText]);

  const handleSubmit = (e) => {
    e?.preventDefault();
    const trimmed = text.trim();
    if (!trimmed) return;
    onOpenChat?.(trimmed);
    setText("");
  };

  // [Flow: Enter=전송, Shift+Enter=줄바꿈 (단일 행이므로 무시)]
  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <div
      className="fixed bottom-6 left-1/2 z-40 w-full max-w-2xl -translate-x-1/2 px-4"
      data-oid="agent-input-bar"
    >
      <form
        onSubmit={handleSubmit}
        className="flex items-center gap-2.5 rounded-2xl border border-outline-variant/30 bg-surface/95 px-4 py-2.5 shadow-lg backdrop-blur-md transition-all focus-within:border-primary/30 focus-within:shadow-xl"
      >
        <div className="flex size-7 flex-shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Sparkles size={15} />
        </div>
        <input
          ref={inputRef}
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={t("page:agent.inputPlaceholder", "AI에게 무엇을 도와드릴까요?")}
          className="min-w-0 flex-1 bg-transparent text-sm text-on-surface outline-none placeholder:text-on-surface-variant/40"
          data-oid="agent-input-field"
        />
        <button
          type="submit"
          disabled={!text.trim()}
          className={`flex size-7 flex-shrink-0 items-center justify-center rounded-xl transition-all duration-200 active:scale-95 ${
            text.trim()
              ? "bg-primary text-white hover:opacity-85"
              : "cursor-not-allowed bg-surface-container-high text-on-surface-variant/30"
          }`}
          aria-label={t("common:send", "전송")}
          data-oid="agent-input-send"
        >
          <ArrowUp size={16} />
        </button>
      </form>
    </div>
  );
}
