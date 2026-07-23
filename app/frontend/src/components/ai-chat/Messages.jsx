// [Flow: Step 1 (messages/status 수신) -> Step 2 (빈 상태면 Greeting 표시)
//       -> Step 3 (메시지 목록 렌더링)
//       -> Step 4 (submitted/streaming 상태면 대화 최하단에 ThinkingMessage 표시)
//       -> Step 5 (scroll-to-bottom 버튼) -> Step 6 (자동 스크롤)]
// Vercel ai-chatbot 템플릿의 messages.tsx + use-messages 훅 포팅.
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowDown } from "lucide-react";
import Greeting from "./Greeting.jsx";
import PreviewMessage, { ThinkingMessage } from "./Message.jsx";

/**
 * useMessages — 메시지 컨테이너 스크롤 상태를 관리하는 훅.
 * Vercel 템플릿의 hooks/use-messages.ts 포팅.
 *
 * @param {Object} opts
 * @param {string} opts.status - useChat status ("ready"|"submitted"|"streaming"|"error")
 * @returns {Object} { containerRef, endRef, isAtBottom, scrollToBottom, hasSentMessage, reset }
 */
function useMessages({ status }) {
  const containerRef = useRef(null);
  const endRef = useRef(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [hasSentMessage, setHasSentMessage] = useState(false);

  // [Flow: status가 submitted/streaming이면 사용자가 메시지를 보냈다고 간주]
  useEffect(() => {
    if (status === "submitted" || status === "streaming") {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- useChat status(외부 상태) 변화에 맞춰 hasSentMessage 래치 설정
      setHasSentMessage(true);
    }
  }, [status]);

  // [Flow: 컨테이너 스크롤 시 맨 아래 여부 갱신]
  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const threshold = 40;
    setIsAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < threshold);
  }, []);

  // [Flow: status가 streaming 중이고 맨 아래면 자동 스크롤 유지]
  useEffect(() => {
    if (status === "streaming" && isAtBottom) {
      endRef.current?.scrollIntoView({ behavior: "auto" });
    }
  }, [status, isAtBottom]);

  const scrollToBottom = useCallback((behavior = "smooth") => {
    endRef.current?.scrollIntoView({ behavior });
    setIsAtBottom(true);
  }, []);

  const reset = useCallback(() => {
    setHasSentMessage(false);
    setIsAtBottom(true);
  }, []);

  return { containerRef, endRef, isAtBottom, scrollToBottom, hasSentMessage, reset, handleScroll };
}

/**
 * Messages — 채팅 메시지 목록을 렌더링한다.
 *
 * @param {Object} props
 * @param {Array} props.messages - UIMessage 배열
 * @param {string} props.status - useChat status
 * @param {boolean} [props.isLoading] - 외부 로딩 상태
 * @param {() => void} [props.onRegenerate] - 마지막 어시스턴트 메시지 재생성 콜백
 * @param {boolean} [props.canRegenerate] - 재생성 가능 여부
 * @param {string} [props.approvalMode='ask'] - 도구 승인 모드 ("ask" | "always")
 * @param {boolean} [props.isAdmin=false] - 관리자 계정 여부 (도구 디버그 정보 표시)
 * @param {() => void} [props.onToolApprove] - 도구 승인 콜백
 * @param {() => void} [props.onToolDeny] - 도구 거부 콜백
 * @param {() => void} [props.onToolAlways] - 항상 승인 콜백
 * @param {string} [props.jobId] - Job ID (마크다운 diff 승인 시 저장 API 호출용)
 * @param {() => void} [props.onCopyPrompt] - 마지막 사용자 프롬프트 복사 콜백
 * @param {() => void} [props.onEditPrompt] - 마지막 사용자 프롬프트 수정 콜백
 */
export default function Messages({
  messages,
  status,
  isLoading,
  onRegenerate,
  canRegenerate,
  approvalMode = "ask",
  isAdmin = false,
  onToolApprove,
  onToolDeny,
  onToolAlways,
  jobId,
  onCopyPrompt,
  onEditPrompt,
}) {
  const { containerRef, endRef, isAtBottom, scrollToBottom, handleScroll } = useMessages({ status });

  // [Flow: 에이전트가 활동 중(submitted/streaming)이면 항상 대화 최하단에 인디케이터 표시]
  const isAgentActive = status === "submitted" || status === "streaming";

  const lastAssistantIndex = messages.map((m) => m.role).lastIndexOf("assistant");
  // [Flow: 마지막 사용자 메시지 인덱스 — 프롬프트 복사/수정 버튼 표시 대상]
  const lastUserIndex = messages.map((m) => m.role).lastIndexOf("user");
  // [Flow: 프롬프트 버튼은 에이전트가 활동 중이 아닐 때만 표시]
  const canShowPromptActions = !isAgentActive;

  return (
    <div className="relative flex-1 bg-background">
      {/* 빈 상태 Greeting */}
      {messages.length === 0 && !isLoading && (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center">
          <Greeting />
        </div>
      )}

      {/* 메시지 스크롤 컨테이너 */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className={`absolute inset-0 touch-pan-y overflow-y-auto custom-scrollbar ${
          messages.length > 0 ? "bg-background" : "bg-transparent"
        }`}
      >
        <div className="mx-auto flex min-h-full min-w-0 max-w-3xl flex-col gap-5 px-4 py-6 md:gap-7 md:px-6">
          {messages.map((message, index) => (
            <PreviewMessage
              key={message.id}
              message={message}
              isLoading={status === "streaming" && messages.length - 1 === index}
              isLastAssistant={index === lastAssistantIndex}
              isLastUser={index === lastUserIndex}
              canShowPromptActions={canShowPromptActions}
              onCopyPrompt={onCopyPrompt}
              onEditPrompt={onEditPrompt}
              onRegenerate={onRegenerate}
              canRegenerate={canRegenerate}
              approvalMode={approvalMode}
              isAdmin={isAdmin}
              onToolApprove={onToolApprove}
              onToolDeny={onToolDeny}
              onToolAlways={onToolAlways}
              jobId={jobId}
            />
          ))}

          {isAgentActive && <ThinkingMessage />}

          <div ref={endRef} className="min-h-[24px] min-w-[24px] shrink-0" />
        </div>
      </div>

      {/* Scroll-to-bottom 버튼 */}
      <button
        type="button"
        aria-label="Scroll to bottom"
        onClick={() => scrollToBottom("smooth")}
        className={`absolute bottom-4 left-1/2 z-10 flex h-7 -translate-x-1/2 items-center rounded-full border border-outline-variant/50 bg-surface/90 px-3.5 shadow-md backdrop-blur-lg transition-all duration-200 ${
          isAtBottom
            ? "pointer-events-none scale-90 opacity-0"
            : "pointer-events-auto scale-100 opacity-100"
        }`}
      >
        <ArrowDown size={12} className="text-on-surface-variant" />
      </button>
    </div>
  );
}
