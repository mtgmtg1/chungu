// [Flow: Step 1 (onOpenChat 콜백 수신) -> Step 2 (중앙 하단 플로팅 입력창 렌더링)
//       -> Step 3 (포커스/Enter/버튼 클릭 시 onOpenChat 호출) -> Step 4 (입력값은 AgentChatModal에서 전송)]
// 화면 정가운데 하단에 떠 있는 AI 에이전트 입력창. 검색창과 유사한 시각 스타일로,
// 클릭하면 팝업 채팅창을 트리거한다.
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Send, Sparkles } from "lucide-react";

/**
 * [Flow: Step 1 (onOpenChat, initialText props 수신) -> Step 2 (입력 상태 관리)
 *       -> Step 3 (입력창 렌더링) -> Step 4 (이벤트 핸들러 등록)]
 *
 * @param {Object} props
 * @param {() => void} props.onOpenChat - 입력창 활성화 시 호출
 * @param {string} [props.initialText] - 외부에서 전달된 초기 텍스트
 */
export default function AgentInputBar({ onOpenChat, initialText = "" }) {
  const { t } = useTranslation();
  const [text, setText] = useState(initialText);

  const handleSubmit = (e) => {
    e.preventDefault();
    onOpenChat?.(text.trim());
    setText("");
  };

  const handleFocus = () => {
    onOpenChat?.(text.trim());
  };

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 w-full max-w-xl px-4" data-oid="agent-input-bar">
      <form
        onSubmit={handleSubmit}
        className="flex items-center gap-2 px-4 py-2.5 rounded-full bg-surface shadow-lg border border-outline-variant focus-within:ring-2 focus-within:ring-primary/40 transition-all"
      >
        <Sparkles size={18} className="text-primary flex-shrink-0" />
        <input
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onFocus={handleFocus}
          placeholder={t("page:agent.inputPlaceholder", "AI에게 무엇을 도와드릴까요?")}
          className="flex-1 min-w-0 bg-transparent outline-none text-sm text-on-surface placeholder:text-on-surface-variant"
          data-oid="agent-input-field"
        />
        <button
          type="submit"
          disabled={!text.trim()}
          className="p-1.5 rounded-full bg-primary text-white disabled:opacity-40 disabled:cursor-not-allowed hover:bg-primary/90 transition-colors flex-shrink-0"
          aria-label={t("common:send", "전송")}
          data-oid="agent-input-send"
        >
          <Send size={16} />
        </button>
      </form>
    </div>
  );
}
