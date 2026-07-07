// [Flow: Step 1 (isOpen/context/onClose 수신) -> Step 2 (useAgentChat 초기화)
//       -> Step 3 (메시지/입력 UI 렌더링) -> Step 4 (사용자 메시지 전송)
//       -> Step 5 (tool call 상태 렌더링) -> Step 6 (닫기/초기화)]
// Vercel AI SDK의 useChat을 탑재한 팝업 채팅창. AgentInputBar에서 트리거되며,
// PDF 주석, 마크다운, 엑셀 조작 도구의 진행 상황을 표시한다.
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { X, Send, Loader2 } from "lucide-react";
import { useAgentChat } from "../hooks/useAgentChat.js";
import AgentToolRenderer from "./AgentToolRenderer.jsx";

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
  const { messages, input, setInput, status, sendContextualMessage } = useAgentChat(context);
  const inputRef = useRef(null);
  const messagesEndRef = useRef(null);
  const [sentInitial, setSentInitial] = useState("");

  // [Flow: Step 1 (isOpen이 true로 바뀌거나 initialText가 변경될 때)
  //       -> Step 2 (입력창 포커스) -> Step 3 (아직 전송되지 않은 initialText가 있으면 전송)]
  useEffect(() => {
    if (!isOpen) {
      setSentInitial("");
      return;
    }
    inputRef.current?.focus();
    if (initialText && initialText !== sentInitial) {
      setSentInitial(initialText);
      setInput(initialText);
      sendContextualMessage(initialText);
    }
  }, [isOpen, initialText, sentInitial, setInput, sendContextualMessage]);

  // [Flow: Step 1 (messages 변경 시) -> Step 2 (스크롤을 최하단으로 이동)]
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!input.trim() || status === "submitted" || status === "streaming") return;
    sendContextualMessage(input.trim());
    setInput("");
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" data-oid="agent-chat-modal">
      <div className="flex flex-col w-full max-w-2xl h-[80vh] max-h-[800px] bg-surface rounded-2xl shadow-2xl border border-outline-variant overflow-hidden">
        {/* 헤더 */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-outline-variant bg-surface-container-low flex-shrink-0">
          <div className="flex items-center gap-2">
            <h3 className="font-headline-md text-headline-md font-bold text-on-surface">
              {t("page:agent.chatTitle", "PROOF AI")}
            </h3>
            {(status === "submitted" || status === "streaming") && (
              <Loader2 size={16} className="animate-spin text-primary" />
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-full hover:bg-surface-container-high text-on-surface-variant"
            aria-label={t("common:close", "닫기")}
            data-oid="agent-chat-close"
          >
            <X size={20} />
          </button>
        </div>

        {/* 메시지 영역 */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4 bg-background">
          {messages.length === 0 && (
            <div className="text-center text-sm text-on-surface-variant py-8">
              {t("page:agent.emptyHint", "PDF 주석, 마크다운, 엑셀 작업을 자연어로 요청해보세요.")}
            </div>
          )}
          {messages.map((message) => (
            <div
              key={message.id}
              className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
              data-oid={`agent-message-${message.role}`}
            >
              <div
                className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm ${
                  message.role === "user"
                    ? "bg-primary text-white rounded-br-none"
                    : "bg-surface-container-low text-on-surface border border-outline-variant rounded-bl-none"
                }`}
              >
                {message.parts?.map((part, idx) => (
                  <AgentToolRenderer key={`${message.id}-${idx}`} part={part} messageId={message.id} />
                ))}
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* 입력 영역 */}
        <div className="border-t border-outline-variant p-4 bg-surface flex-shrink-0">
          <form onSubmit={handleSubmit} className="flex items-center gap-2">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={t("page:agent.inputPlaceholder", "AI에게 무엇을 도와드릴까요?")}
              disabled={status === "submitted" || status === "streaming"}
              className="flex-1 min-w-0 px-4 py-2.5 rounded-full bg-surface-container-low border border-outline-variant text-sm text-on-surface outline-none focus:ring-2 focus:ring-primary/40 disabled:opacity-60"
              data-oid="agent-chat-input"
            />
            <button
              type="submit"
              disabled={!input.trim() || status === "submitted" || status === "streaming"}
              className="p-2.5 rounded-full bg-primary text-white disabled:opacity-40 disabled:cursor-not-allowed hover:bg-primary/90 transition-colors"
              aria-label={t("common:send", "전송")}
              data-oid="agent-chat-send"
            >
              {status === "submitted" || status === "streaming" ? (
                <Loader2 size={18} className="animate-spin" />
              ) : (
                <Send size={18} />
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
