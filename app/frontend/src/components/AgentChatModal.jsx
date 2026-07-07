// [Flow: Step 1 (isOpen/context/onClose 수신) -> Step 2 (useAgentChat 초기화)
//       -> Step 3 (Messages + PromptInput 조합) -> Step 4 (초기 메시지 자동 전송)
//       -> Step 5 (SuggestedActions 표시) -> Step 6 (닫기)]
// Vercel ai-chatbot 템플릿 구조를 따른 에이전트 채팅 모달.
// Messages, PromptInput, SuggestedActions 컴포넌트를 조합하여 렌더링한다.
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import { useAgentChat } from "../hooks/useAgentChat.js";
import Messages from "./ai-chat/Messages.jsx";
import PromptInput from "./ai-chat/PromptInput.jsx";
import SuggestedActions from "./ai-chat/SuggestedActions.jsx";

/**
 * [Flow: Step 1 (props에서 isOpen, context, onClose, initialText 추출)
 *       -> Step 2 (useAgentChat 훅 초기화) -> Step 3 (모달 UI 렌더링)
 *       -> Step 4 (isOpen 변경 시 포커스/초기 메시지 처리)]
 *
 * @param {Object} props
 * @param {boolean} props.isOpen - 모달 열림 상태
 * @param {() => void} props.onClose - 모달 닫기 콜백
 * @param {import("../hooks/useAgentChat.ts").AgentContext} props.context - 현재 Job/페이지/에디터 컨텍스트
 * @param {string} [props.initialText] - 모달 열림과 동시에 전송할 초기 텍스트
 */
export default function AgentChatModal({ isOpen, onClose, context, initialText }) {
  const { t } = useTranslation();
  const { messages, input, setInput, status, stop, sendContextualMessage } = useAgentChat(context);
  const [sentInitial, setSentInitial] = useState("");

  // [Flow: isOpen이 true로 바뀌거나 initialText가 변경될 때 초기 메시지 전송]
  useEffect(() => {
    if (!isOpen) {
      setSentInitial("");
      return;
    }
    if (initialText && initialText !== sentInitial) {
      setSentInitial(initialText);
      setInput(initialText);
      sendContextualMessage(initialText);
    }
  }, [isOpen, initialText, sentInitial, setInput, sendContextualMessage]);

  // [Flow: 전송 핸들러]
  const handleSubmit = () => {
    const trimmed = input.trim();
    if (!trimmed || status === "submitted" || status === "streaming") return;
    sendContextualMessage(trimmed);
    setInput("");
  };

  // [Flow: 제안 액션 선택 시 즉시 전송]
  const handleSuggestion = (prompt) => {
    if (status === "submitted" || status === "streaming") return;
    setInput(prompt);
    sendContextualMessage(prompt);
  };

  if (!isOpen) return null;

  // system 메시지를 제외한 사용자/어시스턴트 메시지만 표시
  const visibleMessages = messages.filter((m) => m.role !== "system");
  const showSuggestions = visibleMessages.length === 0 && status === "ready";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      data-oid="agent-chat-modal"
      onClick={onClose}
    >
      <div
        className="flex h-[85vh] max-h-[900px] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-outline-variant/40 bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 헤더 */}
        <div className="flex flex-shrink-0 items-center justify-between border-b border-outline-variant/30 px-5 py-3.5">
          <div className="flex items-center gap-2.5">
            <div className="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 3l1.9 5.8L20 10.7l-5.8 1.9L12 18.4l-1.9-5.8L4 10.7l5.8-1.9L12 3z" />
              </svg>
            </div>
            <div className="flex flex-col">
              <h3 className="font-semibold text-sm text-on-surface">
                {t("page:agent.chatTitle", "PROOF AI")}
              </h3>
              <span className="text-[11px] text-on-surface-variant/70">
                {context?.sourceType ? `${context.sourceType}` : ""}
                {context?.activeEditor ? ` · ${context.activeEditor}` : ""}
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex size-8 items-center justify-center rounded-lg text-on-surface-variant transition-colors hover:bg-surface-container-high hover:text-on-surface"
            aria-label={t("common:close", "닫기")}
            data-oid="agent-chat-close"
          >
            <X size={18} />
          </button>
        </div>

        {/* 메시지 영역 */}
        <Messages messages={visibleMessages} status={status} />

        {/* 입력 영역 */}
        <div className="flex flex-shrink-0 flex-col gap-3 border-t border-outline-variant/30 bg-surface p-4">
          {showSuggestions && (
            <SuggestedActions context={context} onSelect={handleSuggestion} />
          )}
          <PromptInput
            value={input}
            onChange={setInput}
            onSubmit={handleSubmit}
            onStop={stop}
            status={status}
            autoFocus
          />
        </div>
      </div>
    </div>
  );
}
