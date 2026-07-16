// [Flow: Step 1 (isOpen/context/onClose 수신) -> Step 2 (useAgentChatHistory로 대화 이력 로드)
//       -> Step 3 (스트리밍 중인 세션 + 현재 세션을 항상 마운트 유지)
//       -> Step 4 (isVisible인 세션만 모달 UI 렌더링) -> Step 5 (백그라운드 세션은 return null)]
// Vercel ai-chatbot 템플릿 구조를 따르면서 왼쪽에 대화 이력 사이드바를 추가한 에이전트 채팅 모달.
// 모달이 닫혀도 스트리밍 중인 세션은 백그라운드에서 계속 실행되며, 실행 중인 에이전트 수를
// onRunningCountChange 콜백으로 상위에 보고한다.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { X, MessageSquare, Loader2, AlertCircle } from "lucide-react";
import { api } from "../api.js";
import { useAuth } from "../AuthContext.jsx";
import { useAgentChat } from "../hooks/useAgentChat.js";
import { useAgentChatHistory, makeConversationTitle } from "../hooks/useAgentChatHistory.js";
import { compactMessagesForStorage } from "../utils/chatMessageUtils.js";
import { useIsMobile } from "../hooks/useMediaQuery.js";
import Messages from "./ai-chat/Messages.jsx";
import PromptInput from "./ai-chat/PromptInput.jsx";
import SuggestedActions from "./ai-chat/SuggestedActions.jsx";
import AgentChatSidebar from "./AgentChatSidebar.jsx";

// [Flow: 관리자 이메일 — 디버깅용 도구 JSON 표시 대상]
const ADMIN_EMAIL = "mtgmtg@naver.com";

// [Flow: 개발 모드에서만 콘솔 로그 출력 — production 빌드 노이즈 방지]
const isDev = typeof import.meta !== "undefined" && import.meta.env?.DEV === true;
function debugLog(...args) {
  if (isDev) console.log(...args);
}
function debugError(...args) {
  if (isDev) console.error(...args);
}

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
 * @param {string} [props.approvalMode='ask'] - 도구 승인 모드 ("ask" | "always")
 * @param {(mode: 'ask' | 'always') => void} [props.onApprovalModeChange] - 승인 모드 변경 콜백
 */
function ChatSession({
  context,
  chatId,
  initialMessages,
  isVisible,
  onMessagesChange,
  onStatusChange,
  onClose,
  sidebarProps,
  approvalMode = "ask",
  isAdmin = false,
  onApprovalModeChange,
  onFlowDrawingsUpdate,
  error,
  clearError,
}) {
  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const [showSidebarMobile, setShowSidebarMobile] = useState(false);
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

  // [Flow: 채팅 메시지에서 save_flow_drawings 도구 결과 감지 → 플로우뷰 즉시 동기화]
  const onFlowDrawingsUpdateRef = useRef(onFlowDrawingsUpdate);
  onFlowDrawingsUpdateRef.current = onFlowDrawingsUpdate;
  useEffect(() => {
    if (!onFlowDrawingsUpdateRef.current) return;
    for (const message of messages) {
      if (message.role !== "assistant") continue;
      const parts = message.parts || [];
      for (const part of parts) {
        const type = part.type;
        const isToolPart = type === "dynamic-tool" || (typeof type === "string" && type.startsWith("tool-"));
        if (!isToolPart) continue;
        const toolName = type === "dynamic-tool" ? part.toolName : type.slice("tool-".length);
        if (toolName !== "save_flow_drawings") continue;
        if (part.state !== "output-available") continue;
        const output = part.output;
        if (output && output.ok) {
          onFlowDrawingsUpdateRef.current(output);
        }
      }
    }
  }, [messages]);

  // [Flow: 스트리밍이 끝났을 때(status가 ready/error로 전환)만 메시지 저장]
  useEffect(() => {
    if (status !== "ready" && status !== "error") return;
    onMessagesChangeRef.current(messagesRef.current);
  }, [status]);

  // [Flow: 컴포넌트 언마운트 시(대화 전환/완료) 최신 메시지 저장]
  useEffect(() => {
    return () => {
      debugLog('[ChatSession] 언마운트 시 저장:', { chatId, messageCount: messagesRef.current?.length });
      onMessagesChangeRef.current(messagesRef.current);
    };
  }, []);

  // [Flow: messages 변경 시 debounce 백업 저장 — 탭 닫기/새로고침 등 언마운트 저장이 보장되지 않을 때 대비]
  useEffect(() => {
    if (messages.length === 0) return;
    const timer = setTimeout(() => {
      debugLog('[ChatSession] debounce 백업 저장:', { chatId, messageCount: messagesRef.current?.length });
      onMessagesChangeRef.current(messagesRef.current);
    }, 3000);
    return () => clearTimeout(timer);
  }, [messages]);

  // [Flow: 탭 닫기/새로고침 전 keepalive fetch로 최신 메시지 저장]
  useEffect(() => {
    const jobId = context?.jobId;
    if (!jobId || !chatId) return;

    const handleBeforeUnload = () => {
      const currentMessages = messagesRef.current;
      if (!currentMessages?.length) return;

      const title = makeConversationTitle(currentMessages);
      const compactedMessages = compactMessagesForStorage(currentMessages);
      fetch(`/api/jobs/${jobId}/chat-conversations/${chatId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, messages: compactedMessages }),
        keepalive: true,
      });
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [context?.jobId, chatId]);

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

  // [Flow: 도구 승인 콜백 — 승인 메시지를 에이전트에게 자동 전송]
  const handleToolApprove = useCallback(() => {
    if (status === "submitted" || status === "streaming") return;
    sendContextualMessage(t("page:agent.approveMessage", "승인했습니다. 계속 진행해주세요."));
  }, [status, sendContextualMessage, t]);

  // [Flow: 도구 거부 콜백 — 거부 메시지를 에이전트에게 자동 전송]
  const handleToolDeny = useCallback(() => {
    if (status === "submitted" || status === "streaming") return;
    sendContextualMessage(t("page:agent.denyMessage", "거부했습니다. 이 작업을 취소해주세요."));
  }, [status, sendContextualMessage, t]);

  // [Flow: 항상 승인 콜백 — 설정 저장 후 승인 메시지 전송]
  const handleToolAlways = useCallback(() => {
    if (status === "submitted" || status === "streaming") return;
    // 백엔드에 'always' 모드 저장
    api.updateAISettings({ approval_mode: "always" }).catch(() => {});
    // 상위 컴포넌트에 승인 모드 변경 알림
    onApprovalModeChange?.("always");
    // 에이전트에게 승인 메시지 전송
    sendContextualMessage(t("page:agent.approveMessage", "승인했습니다. 계속 진행해주세요."));
  }, [status, sendContextualMessage, t, onApprovalModeChange]);

  // [Flow: 백그라운드 모드 — useChat은 계속 실행되지만 UI는 렌더링하지 않음]
  if (!isVisible) return null;

  // system 메시지를 제외한 사용자/어시스턴트 메시지만 표시
  const visibleMessages = messages.filter((m) => m.role !== "system");
  const showSuggestions = visibleMessages.length === 0 && status === "ready";
  const canRegenerate = status === "ready" || status === "error";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-0 md:p-4"
      data-oid="agent-chat-modal"
      onClick={onClose}
    >
      <div
        className={`ai-chat-modal-in flex w-full flex-row overflow-hidden bg-surface shadow-2xl ${
          isMobile
            ? "h-[100vh] flex-col"
            : "h-[85vh] max-h-[900px] max-w-5xl rounded-2xl border border-outline-variant/40"
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        {/* [Flow: 모바일 — 사이드바를 오버레이 드로어로 표시, 데스크탑 — 인라인 사이드바] */}
        {sidebarProps && !isMobile && <AgentChatSidebar {...sidebarProps} />}

        {/* 모바일 사이드바 드로어 */}
        {sidebarProps && isMobile && showSidebarMobile && (
          <>
            <div
              className="fixed inset-0 z-50 bg-black/30"
              onClick={() => setShowSidebarMobile(false)}
              data-oid="mobile-sidebar-overlay"
            />
            <div
              className="fixed left-0 top-0 z-50 h-full w-[280px] bg-surface shadow-2xl"
              data-oid="mobile-sidebar-drawer"
            >
              <AgentChatSidebar
                {...sidebarProps}
                onSelect={(id) => {
                  sidebarProps.onSelect(id);
                  setShowSidebarMobile(false);
                }}
              />
            </div>
          </>
        )}

        {/* 오른쪽 채팅 영역 */}
        <div className="flex min-w-0 flex-1 flex-col">
          {/* 헤더 */}
          <div className="flex flex-shrink-0 items-center justify-between border-b border-outline-variant/30 px-4 md:px-5 py-3.5">
            <div className="flex items-center gap-2.5">
              {/* [Flow: 모바일 — 사이드바 토글 버튼 표시] */}
              {sidebarProps && isMobile && (
                <button
                  type="button"
                  onClick={() => setShowSidebarMobile(true)}
                  className="flex size-8 items-center justify-center rounded-lg text-on-surface-variant transition-colors hover:bg-surface-container-high"
                  aria-label={t("page:agent.chatHistory", "대화 이력")}
                  data-oid="mobile-sidebar-toggle"
                >
                  <MessageSquare size={18} />
                </button>
              )}
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
              <X size={20} />
            </button>
          </div>

          {/* [Flow: API 에러 배너 — 백엔드 요청 실패 시 사용자에게 상태 노출] */}
          {error && (
            <div className="flex flex-shrink-0 items-start gap-2 bg-error/10 px-4 py-2.5 text-xs text-on-surface">
              <AlertCircle size={16} className="mt-0.5 flex-shrink-0 text-error" />
              <div className="flex-1 leading-relaxed">
                {error.message}
              </div>
              <button
                type="button"
                onClick={clearError}
                className="ml-2 flex-shrink-0 text-on-surface-variant hover:text-on-surface underline"
              >
                {t("common:dismiss", "닫기")}
              </button>
            </div>
          )}

          {/* 메시지 영역 */}
          <Messages
            messages={visibleMessages}
            status={status}
            onRegenerate={regenerate}
            canRegenerate={canRegenerate}
            approvalMode={approvalMode}
            isAdmin={isAdmin}
            onToolApprove={handleToolApprove}
            onToolDeny={handleToolDeny}
            onToolAlways={handleToolAlways}
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
export default function AgentChatModal({ isOpen, onClose, context, onRunningCountChange, onAgentComplete, onFlowDrawingsUpdate }) {
  const { t } = useTranslation();
  const { user } = useAuth();
  // [Flow: 관리자 계정 여부 — 도구 이름·input·output JSON 표시 여부 결정]
  const isAdmin = user?.email === ADMIN_EMAIL;
  const jobId = context?.jobId;
  const {
    conversations,
    currentId,
    isLoadingList,
    isLoadingMessages,
    error,
    clearError,
    createConversation,
    selectConversation,
    saveConversation,
    isMessageLoaded,
  } = useAgentChatHistory(jobId);

  // [Flow: 디버깅 — 대화 상태 변화 추적]
  useEffect(() => {
    debugLog('[AgentChatModal] 상태 업데이트:', {
      jobId,
      isOpen,
      conversationsCount: conversations.length,
      currentId,
      isLoadingList,
      isLoadingMessages,
      ids: conversations.map((c) => ({ id: c.id, title: c.title, messageCount: c.messages?.length, updatedAt: c.updatedAt })),
    });
  }, [jobId, isOpen, conversations, currentId, isLoadingList, isLoadingMessages]);

  // [Flow: 사용자 승인 모드 로드 — api.me()에서 ai_tool_approval_mode 조회]
  const [approvalMode, setApprovalMode] = useState("ask");
  useEffect(() => {
    if (!isOpen) return;
    api.me().then((profile) => {
      if (profile?.ai_tool_approval_mode) {
        setApprovalMode(profile.ai_tool_approval_mode);
      }
    }).catch(() => {});
  }, [isOpen]);

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

  // [Flow: 마운트해야 할 세션 ID 목록 = 스트리밍 중인 세션 + 현재 열린 모달의 선택된 세션]
  // 모달이 닫혀 있고 스트리밍 중이 아닌 현재 세션은 언마운트한다.
  // ChatSession은 invisible 상태에서도 마운트되면 useChat의 초기 messages가
  // 빈 배열로 고정되므로, 이전 대화가 복원되지 않는 문제를 방지한다.
  const sessionIds = useMemo(() => {
    const ids = new Set(streamingIds);
    if (isOpen && currentId) ids.add(currentId);
    return [...ids];
  }, [streamingIds, isOpen, currentId]);

  // [Flow: 모달 열림 시 현재 대화 보장(없으면 최근 대화 선택, 최근 대화 없으면 새로 생성)
  //       — DB 목록 로딩 중에는 새 대화 생성을 지연하여 premature 생성 방지
  //       — API 에러 발생 시에는 자동 생성을 막아 사용자가 상태를 인지할 수 있게 함]
  useEffect(() => {
    if (!isOpen) return;
    debugLog('[AgentChatModal] 모달 열림/현재 대화 보장 effect:', { isOpen, currentId, conversationsCount: conversations.length, isLoadingList, hasError: !!error });
    if (error) return;
    if (!currentId) {
      if (conversations.length > 0) {
        debugLog('[AgentChatModal] 기존 대화 선택:', { selectedId: conversations[0].id });
        selectConversation(conversations[0].id);
      } else if (!isLoadingList) {
        // DB 목록 로딩이 완료된 후에만 새 대화 생성
        debugLog('[AgentChatModal] 새 대화 생성 (목록 비어있음)');
        createConversation();
      }
    }
  }, [isOpen, currentId, conversations, isLoadingList, error, createConversation, selectConversation]);

  // [Flow: 세션 status 변경 핸들러 — streaming/submitted이면 streamingIds에 추가, ready/error면 제거]
  // [Flow: ready/error 전환 시(에이전트 완료) onAgentComplete 호출하여 상위에서 데이터 재로드]
  const handleStatusChange = useCallback((id, status) => {
    debugLog('[AgentChatModal] 세션 status 변경:', { id, status });
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
      debugLog('[AgentChatModal] 메시지 저장 트리거:', { id, messageCount: messages?.length });
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
        // [Flow: 현재 대화의 messages가 DB에서 로딩 중이면 ChatSession 대신 spinner 표시
        //       — initialMessages가 빈 상태로 마운트되는 것을 방지]
        // loadedIdsRef에 없으면 아직 fetch가 시작되지 않았거나 진행 중이므로 spinner 표시.
        const hasLoaded = isMessageLoaded(id);
        const isCurrentLoading = isVisible && (!hasLoaded || isLoadingMessages);

        // [Flow: 로딩 중인 현재 세션은 spinner만 렌더링 (ChatSession 마운트 지연)]
        if (isCurrentLoading) {
          return (
            <div
              key={id}
              className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
              onClick={onClose}
            >
              <Loader2 className="h-8 w-8 animate-spin text-on-surface-variant" />
            </div>
          );
        }

        return (
          <ChatSession
            key={id}
            context={{ ...context, approvalMode }}
            chatId={id}
            initialMessages={conversation?.messages || []}
            isVisible={isVisible}
            onMessagesChange={handleMessagesChange(id)}
            onStatusChange={(status) => handleStatusChange(id, status)}
            onClose={onClose}
            sidebarProps={isVisible ? sidebarProps : undefined}
            approvalMode={approvalMode}
            isAdmin={isAdmin}
            onApprovalModeChange={setApprovalMode}
            onFlowDrawingsUpdate={onFlowDrawingsUpdate}
            error={isVisible ? error : null}
            clearError={isVisible ? clearError : () => {}}
          />
        );
      })}
    </>
  );
}
