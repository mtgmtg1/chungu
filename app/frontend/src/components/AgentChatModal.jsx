// [Flow: Step 1 (isOpen/context/onClose 수신) -> Step 2 (useAgentChatHistory로 대화 이력 로드)
//       -> Step 3 (스트리밍 중인 세션 + 현재 세션을 항상 마운트 유지)
//       -> Step 4 (isVisible인 세션만 모달 UI 렌더링) -> Step 5 (백그라운드 세션은 return null)]
// Vercel ai-chatbot 템플릿 구조를 따르면서 왼쪽에 대화 이력 사이드바를 추가한 에이전트 채팅 모달.
// 모달이 닫혀도 스트리밍 중인 세션은 백그라운드에서 계속 실행되며, 실행 중인 에이전트 수를
// onRunningCountChange 콜백으로 상위에 보고한다.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
 *       -> Step 3 (status 변화를 상위에 보고) -> Step 4 (isVisible일 때만 모달 UI 렌더링)
 *
 * ChatSession은 대화 ID가 변경될 때마다 remount되어 새로운 initialMessages를 받는다.
 * isVisible이 false여도 컴포넌트는 마운트 상태를 유지하므로 useChat의 스트리밍이 계속된다.
 * 이렇게 하면 모달을 닫아도 백그라운드에서 에이전트가 계속 실행된다.
 *
 * @param {Object} props
 * @param {import("../hooks/useAgentChat.ts").AgentContext} props.context - 현재 Job/페이지/에디터 컨텍스트
 * @param {string} props.chatId - 현재 대화 ID
 * @param {Array} props.initialMessages - 복원할 메시지 목록
 * @param {boolean} props.isVisible - 모달이 열려 있고 이 세션이 현재 선택된 대화인지 여부
 * @param {(messages: Array) => void} props.onMessagesChange - 메시지 변경 시 상위에 알림
 * @param {(status: string) => void} props.onStatusChange - useChat status 변경 시 상위에 알림
 * @param {() => void} props.onClose - 모달 닫기 콜백
 * @param {Object} [props.sidebarProps] - 사이드바에 전달할 props (isVisible일 때만 사용)
 */
function ChatSession({ context, chatId, initialMessages, isVisible, onMessagesChange, onStatusChange, onClose, sidebarProps }) {
  const { t } = useTranslation();
  const { messages, input, setInput, status, stop, sendContextualMessage, regenerate } = useAgentChat(
    context,
    { chatId, initialMessages },
  );

  // [Flow: 최신 messages와 콜백을 ref에 보관하여 effect 재실행 최소화]
  const messagesRef = useRef(messages);
  messagesRef.current = messages;
  const onMessagesChangeRef = useRef(onMessagesChange);
  onMessagesChangeRef.current = onMessagesChange;
  const onStatusChangeRef = useRef(onStatusChange);
  onStatusChangeRef.current = onStatusChange;

  // [Flow: status가 변경될 때마다 상위에 보고 — 백그라운드 세션 포함]
  useEffect(() => {
    onStatusChangeRef.current(status);
  }, [status]);

  // [Flow: 스트리밍이 끝났을 때(status가 ready/error로 전환)만 메시지 저장]
  useEffect(() => {
    if (status !== "ready" && status !== "error") return;
    onMessagesChangeRef.current(messagesRef.current);
  }, [status]);

  // [Flow: 컴포넌트 언마운트 시(대화 전환/완료) 최신 메시지 저장]
  useEffect(() => {
    return () => {
      onMessagesChangeRef.current(messagesRef.current);
    };
  }, []);

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

  // [Flow: 백그라운드 모드 — useChat은 계속 실행되지만 UI는 렌더링하지 않음]
  if (!isVisible) return null;

  // system 메시지를 제외한 사용자/어시스턴트 메시지만 표시
  const visibleMessages = messages.filter((m) => m.role !== "system");
  const showSuggestions = visibleMessages.length === 0 && status === "ready";
  const canRegenerate = status === "ready" || status === "error";

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
        {sidebarProps && <AgentChatSidebar {...sidebarProps} />}

        {/* 오른쪽 채팅 영역 */}
        <div className="flex min-w-0 flex-1 flex-col">
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
        </div>
      </div>
    </div>
  );
}

/**
 * [Flow: Step 1 (props에서 isOpen, context, onClose, onRunningCountChange 추출)
 *       -> Step 2 (useAgentChatHistory로 대화 이력 관리)
 *       -> Step 3 (streamingIds 추적 — 백그라운드에서 실행 중인 세션 ID 집합)
 *       -> Step 4 (sessionIds = streamingIds ∪ {currentId} — 마운트해야 할 모든 세션)
 *       -> Step 5 (각 세션 렌더링 — isVisible인 것만 모달 UI 표시, 나머지는 return null)]
 *
 * @param {Object} props
 * @param {boolean} props.isOpen - 모달 열림 상태
 * @param {() => void} props.onClose - 모달 닫기 콜백
 * @param {import("../hooks/useAgentChat.ts").AgentContext} props.context - 현재 Job/페이지/에디터 컨텍스트
 * @param {(count: number) => void} [props.onRunningCountChange] - 실행 중 에이전트 수 변경 시 호출
 * @param {() => void} [props.onAgentComplete] - 에이전트 세션이 streaming → ready/error로 전환될 때 호출 (상위에서 job/preview 재로드 용)
 */
export default function AgentChatModal({ isOpen, onClose, context, onRunningCountChange, onAgentComplete }) {
  const { t } = useTranslation();
  const jobId = context?.jobId;
  const {
    conversations,
    currentId,
    createConversation,
    selectConversation,
    saveConversation,
  } = useAgentChatHistory(jobId);

  // [Flow: streamingIds — 현재 스트리밍 중(submitted/streaming)인 세션 ID 집합]
  // 이 세션들은 모달이 닫혀도 백그라운드에서 계속 실행된다.
  const [streamingIds, setStreamingIds] = useState(() => new Set());

  // [Flow: onRunningCountChange를 ref에 보관하여 effect 안정화]
  const onRunningCountChangeRef = useRef(onRunningCountChange);
  onRunningCountChangeRef.current = onRunningCountChange;

  // [Flow: onAgentComplete를 ref에 보관 — 에이전트 완료 시 상위에서 job/preview 재로드]
  const onAgentCompleteRef = useRef(onAgentComplete);
  onAgentCompleteRef.current = onAgentComplete;

  // [Flow: 실행 중 에이전트 수를 상위에 보고]
  useEffect(() => {
    onRunningCountChangeRef.current?.(streamingIds.size);
  }, [streamingIds.size]);

  // [Flow: 마운트해야 할 세션 ID 목록 = 스트리밍 중인 세션 + 현재 선택된 세션]
  // 스트리밍 중이 아닌 비활성 세션은 언마운트하여 메모리를 절약한다.
  const sessionIds = useMemo(() => {
    const ids = new Set(streamingIds);
    if (currentId) ids.add(currentId);
    return [...ids];
  }, [streamingIds, currentId]);

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

  // [Flow: 세션 status 변경 핸들러 — streaming/submitted이면 streamingIds에 추가, ready/error면 제거]
  // [Flow: ready/error 전환 시(에이전트 완료) onAgentComplete 호출하여 상위에서 데이터 재로드]
  const handleStatusChange = useCallback((id, status) => {
    const isStreaming = status === "streaming" || status === "submitted";
    setStreamingIds((prev) => {
      const has = prev.has(id);
      if (isStreaming && !has) {
        const next = new Set(prev);
        next.add(id);
        return next;
      }
      if (!isStreaming && has) {
        const next = new Set(prev);
        next.delete(id);
        // 에이전트가 스트리밍을 마치고 ready/error로 전환되면 상위에 완료 알림
        onAgentCompleteRef.current?.();
        return next;
      }
      return prev;
    });
  }, []);

  // [Flow: 메시지 저장 핸들러 — 안정화하여 ChatSession의 effect 재실행 방지]
  const handleMessagesChange = useCallback(
    (id) => (messages) => {
      saveConversation(id, messages);
    },
    [saveConversation],
  );

  // [Flow: 사이드바 props — isVisible인 세션에만 전달]
  const sidebarProps = useMemo(
    () => ({
      conversations,
      currentId,
      onNewChat: createConversation,
      onSelect: selectConversation,
    }),
    [conversations, currentId, createConversation, selectConversation],
  );

  return (
    <>
      {sessionIds.map((id) => {
        const isVisible = isOpen && id === currentId;
        const conversation = conversations.find((c) => c.id === id);
        return (
          <ChatSession
            key={id}
            context={context}
            chatId={id}
            initialMessages={conversation?.messages || []}
            isVisible={isVisible}
            onMessagesChange={handleMessagesChange(id)}
            onStatusChange={(status) => handleStatusChange(id, status)}
            onClose={onClose}
            sidebarProps={isVisible ? sidebarProps : undefined}
          />
        );
      })}
    </>
  );
}
