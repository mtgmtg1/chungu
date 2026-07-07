// [Flow: Step 1 (isOpen/context/onClose 수신) -> Step 2 (useAgentChatHistory로 대화 이력 로드)
//       -> Step 3 (현재 대화 선택/생성) -> Step 4 (ChatSession 렌더링)
//       -> Step 5 (사이드바 + 채팅 영역 조합) -> Step 6 (닫기)]
// Vercel ai-chatbot 템플릿 구조를 따르면서 왼쪽에 대화 이력 사이드바를 추가한 에이전트 채팅 모달.
// Messages, PromptInput, SuggestedActions 컴포넌트를 조합하여 렌더링한다.
import { useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import { useAgentChat } from "../hooks/useAgentChat.js";
import { useAgentChatHistory } from "../hooks/useAgentChatHistory.js";
import Messages from "./ai-chat/Messages.jsx";
import PromptInput from "./ai-chat/PromptInput.jsx";
import SuggestedActions from "./ai-chat/SuggestedActions.jsx";
import AgentChatSidebar from "./AgentChatSidebar.jsx";

/**
 * [Flow: Step 1 (단일 대화 세션 초기화) -> Step 2 (useAgentChat로 메시지/상태 관리)
 *       -> Step 3 (메시지 변경 시 상위로 저장) -> Step 4 (헤더/메시지/입력 UI 렌더링)]
 *
 * ChatSession은 대화 ID가 변경될 때마다 remount되어 새로운 initialMessages를 받는다.
 *
 * @param {Object} props
 * @param {import("../hooks/useAgentChat.ts").AgentContext} props.context - 현재 Job/페이지/에디터 컨텍스트
 * @param {string} props.chatId - 현재 대화 ID
 * @param {Array} props.initialMessages - 복원할 메시지 목록
 * @param {(messages: Array) => void} props.onMessagesChange - 메시지 변경 시 상위에 알림
 * @param {() => void} props.onClose - 모달 닫기 콜백
 */
function ChatSession({ context, chatId, initialMessages, onMessagesChange, onClose }) {
  const { t } = useTranslation();
  const { messages, input, setInput, status, stop, sendContextualMessage, regenerate } = useAgentChat(
    context,
    { chatId, initialMessages },
  );

  // [Flow: messages ref를 보관해서 언마운트 시 최신 메시지를 저장할 수 있게 한다]
  const messagesRef = useRef(messages);
  messagesRef.current = messages;

  // [Flow: 스트리밍이 끝났을 때(status가 ready/error로 전환)만 상위에 저장 요청]
  // 스트리밍 중 매 토큰마다 저장하면 localStorage 쓰기가 과도하게 발생하므로
  // status가 "ready" 또는 "error"로 바뀐 시점에만 저장한다.
  useEffect(() => {
    if (status !== "ready" && status !== "error") return;
    onMessagesChange(messagesRef.current);
  }, [status, onMessagesChange]);

  // [Flow: 컴포넌트 언마운트 시(대화 전환/모달 닫기) 최신 메시지 저장]
  useEffect(() => {
    return () => {
      onMessagesChange(messagesRef.current);
    };
  }, [onMessagesChange]);

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

  // system 메시지를 제외한 사용자/어시스턴트 메시지만 표시
  const visibleMessages = messages.filter((m) => m.role !== "system");
  const showSuggestions = visibleMessages.length === 0 && status === "ready";
  const canRegenerate = status === "ready" || status === "error";

  return (
    <>
      {/* 헤더 */}
      <div className="flex flex-shrink-0 items-center justify-between border-b border-outline-variant/30 px-5 py-3.5">
        <div className="flex items-center gap-2.5">
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
      <Messages
        messages={visibleMessages}
        status={status}
        onRegenerate={regenerate}
        canRegenerate={canRegenerate}
      />

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
    </>
  );
}

/**
 * [Flow: Step 1 (props에서 isOpen, context, onClose 추출)
 *       -> Step 2 (useAgentChatHistory로 대화 이력 관리) -> Step 3 (모달 열림 시 현재 대화 보장)
 *       -> Step 4 (사이드바 + ChatSession 조합)]
 *
 * @param {Object} props
 * @param {boolean} props.isOpen - 모달 열림 상태
 * @param {() => void} props.onClose - 모달 닫기 콜백
 * @param {import("../hooks/useAgentChat.ts").AgentContext} props.context - 현재 Job/페이지/에디터 컨텍스트
 */
export default function AgentChatModal({ isOpen, onClose, context }) {
  const { t } = useTranslation();
  const jobId = context?.jobId;
  const {
    conversations,
    currentConversation,
    currentId,
    createConversation,
    selectConversation,
    saveConversation,
  } = useAgentChatHistory(jobId);

  // [Flow: saveConversation을 useCallback으로 안정화하여 ChatSession의 useEffect가 불필요하게 재실행되지 않도록 함]
  const handleMessagesChange = useCallback(
    (messages) => {
      if (currentId) saveConversation(currentId, messages);
    },
    [currentId, saveConversation],
  );

  // [Flow: 모달 열림 시 현재 대화 보장(없으면 최근 대화 선택, 최근 대화 없으면 새로 생성)]
  useEffect(() => {
    if (!isOpen) return;
    if (!currentId) {
      if (conversations.length > 0) {
        selectConversation(conversations[0].id);
      } else {
        createConversation();
      }
    }
  }, [isOpen, currentId, conversations, createConversation, selectConversation]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      data-oid="agent-chat-modal"
      onClick={onClose}
    >
      <div
        className="ai-chat-modal-in flex h-[85vh] max-h-[900px] w-full max-w-5xl flex-row overflow-hidden rounded-2xl border border-outline-variant/40 bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 왼쪽 사이드바: 대화 이력 */}
        <AgentChatSidebar
          conversations={conversations}
          currentId={currentId}
          onNewChat={createConversation}
          onSelect={selectConversation}
        />

        {/* 오른쪽 채팅 영역 */}
        <div className="flex min-w-0 flex-1 flex-col">
          {currentId ? (
            <ChatSession
              key={currentId}
              context={context}
              chatId={currentId}
              initialMessages={currentConversation?.messages || []}
              onMessagesChange={handleMessagesChange}
              onClose={onClose}
            />
          ) : (
            // 대화가 준비되지 않은 임시 상태
            <div className="flex flex-1 items-center justify-center text-sm text-on-surface-variant">
              {t("common:loading", "로딩 중...")}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
