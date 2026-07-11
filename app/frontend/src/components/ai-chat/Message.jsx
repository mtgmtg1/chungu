// [Flow: Step 1 (UIMessage 수신) -> Step 2 (role에 따라 user/assistant 레이아웃 분기)
//       -> Step 3 (parts 순회: text/tool/reasoning) -> Step 4 (어시스턴트 아바타 + 콘텐츠 렌더링)]
// Vercel ai-chatbot 템플릿의 message.tsx 포팅.
// 어시스턴트 메시지는 좌측 Sparkles 아바타 + 전체 폭 콘텐츠,
// 사용자 메시지는 우측 정렬 풍선으로 렌더링한다.
import { memo, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { marked } from "marked";
import { RefreshCw, Sparkles } from "lucide-react";
import Shimmer from "./Shimmer.jsx";
import Tool from "./Tool.jsx";

// [Flow: 마크다운 텍스트 -> HTML 변환 (XSS 방지를 위해 marked 옵션 설정)]
marked.setOptions({ breaks: true, gfm: true });

function sanitizeText(text) {
  // Vercel 템플릿의 sanitizeText와 동일 — 제어 문자 제거
  return text.replace(/\u0000/g, "");
}

/**
 * MessageContent — 마크다운을 HTML로 렌더링하는 메시지 본문.
 *
 * @param {Object} props
 * @param {string} props.text - 마크다운 텍스트
 * @param {string} [props.className] - 추가 클래스
 * @param {"user"|"assistant"} [props.role] - 메시지 역할 (풍선 스타일 결정)
 */
const MessageContent = memo(function MessageContent({ text, className = "", role }) {
  const html = useMemo(() => {
    try {
      return marked.parse(sanitizeText(text || ""));
    } catch {
      return sanitizeText(text || "");
    }
  }, [text]);

  return (
    <div
      className={
        role === "user"
          ? `w-fit max-w-[min(80%,56ch)] overflow-hidden break-words rounded-2xl rounded-br-md border border-outline-variant/30 bg-gradient-to-br from-surface-container-high to-surface-container-low px-3.5 py-2 shadow-sm ${className}`
          : `min-w-0 max-w-full ${className}`
      }
      data-testid="message-content"
    >
      <div
        className="ai-chat-markdown text-on-surface"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
});

/**
 * PreviewMessage — 개별 메시지를 렌더링한다.
 * 어시스턴트: 좌측 Sparkles 아바타 + 전체 폭 콘텐츠 (풍선 없음)
 * 사용자: 우측 정렬 풍선
 *
 * @param {Object} props
 * @param {Object} props.message - UIMessage (role, parts, id)
 * @param {boolean} props.isLoading - 스트리밍 중인지 여부
 * @param {boolean} [props.isLastAssistant] - 마지막 어시스턴트 메시지인지 여부
 * @param {() => void} [props.onRegenerate] - 마지막 어시스턴트 메시지 재생성 콜백
 * @param {boolean} [props.canRegenerate] - 재생성 가능 여부
 * @param {string} [props.approvalMode='ask'] - 도구 승인 모드 ("ask" | "always")
 * @param {boolean} [props.isAdmin=false] - 관리자 계정 여부 (도구 디버그 정보 표시)
 * @param {() => void} [props.onToolApprove] - 도구 승인 콜백
 * @param {() => void} [props.onToolDeny] - 도구 거부 콜백
 * @param {() => void} [props.onToolAlways] - 항상 승인 콜백
 */
function PreviewMessage({
  message,
  isLoading,
  isLastAssistant,
  onRegenerate,
  canRegenerate,
  approvalMode = "ask",
  isAdmin = false,
  onToolApprove,
  onToolDeny,
  onToolAlways,
}) {
  const { t } = useTranslation();
  const isUser = message.role === "user";
  const isAssistant = message.role === "assistant";

  // [Flow: parts 순회 -> text/tool/reasoning 분기 -> 렌더링]
  const parts = message.parts?.map((part, index) => {
    const type = part.type;
    const key = `message-${message.id}-part-${index}`;

    if (type === "text") {
      return (
        <MessageContent
          key={key}
          text={part.text}
          role={message.role}
        />
      );
    }

    // Vercel AI SDK 5.x tool part: type이 "tool-${name}" 또는 "dynamic-tool"
    const isToolPart = type === "dynamic-tool" || (typeof type === "string" && type.startsWith("tool-"));
    if (isToolPart) {
      const toolName = type === "dynamic-tool" ? part.toolName : type.slice("tool-".length);
      return (
        <Tool
          key={key}
          toolName={toolName}
          state={part.state}
          input={part.input}
          output={part.output}
          errorText={part.errorText}
          defaultOpen={part.state === "output-error"}
          approvalMode={approvalMode}
          isAdmin={isAdmin}
          onApprove={onToolApprove}
          onDeny={onToolDeny}
          onAlways={onToolAlways}
        />
      );
    }

    // reasoning part (아직 사용하지 않지만 안전하게 무시)
    if (type === "reasoning") return null;

    return null;
  });

  // [Flow: 어시스턴트 + 로딩 중 + 콘텐츠 없음 -> Thinking shimmer]
  const hasAnyContent = message.parts?.some(
    (part) =>
      (part.type === "text" && part.text?.trim().length > 0) ||
      (typeof part.type === "string" && part.type.startsWith("tool-"))
  );
  const isThinking = isAssistant && isLoading && !hasAnyContent;

  const content = isThinking ? (
    <div className="flex items-center text-[13px] leading-[1.65]">
      <Shimmer className="font-medium" duration={1.5}>
        Thinking...
      </Shimmer>
    </div>
  ) : (
    parts
  );

  return (
    <div
      className={`group/message w-full ${!isAssistant ? "ai-chat-fade-up" : ""}`}
      data-role={message.role}
      data-testid={`message-${message.role}`}
    >
      {isUser ? (
        // 사용자 메시지: 우측 정렬 풍선
        <div className="flex flex-col items-end gap-2">{content}</div>
      ) : (
        // 어시스턴트 메시지: 좌측 아바타 + 전체 폭 콘텐츠
        <div className="flex items-start gap-3">
          <div className="flex h-[calc(13px*1.65)] shrink-0 items-center">
            <div className="flex size-7 items-center justify-center rounded-lg bg-surface-container-high/80 text-primary ring-1 ring-outline-variant/40">
              <Sparkles size={14} />
            </div>
          </div>
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            {content}
            {/* 마지막 어시스턴트 메시지 아래에 재생성 버튼 표시 */}
            {isLastAssistant && onRegenerate && (
              <div className="flex items-center">
                <button
                  type="button"
                  onClick={onRegenerate}
                  disabled={!canRegenerate}
                  className={`flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] font-medium transition-colors ${
                    canRegenerate
                      ? "text-on-surface-variant hover:bg-surface-container-high"
                      : "cursor-not-allowed text-on-surface-variant/30"
                  }`}
                  aria-label={t("page:agent.regenerate", "재생성")}
                  data-oid="agent-message-regenerate"
                >
                  <RefreshCw size={12} />
                  {t("page:agent.regenerate", "재생성")}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * ThinkingMessage — 어시스턴트 응답 대기 중 표시하는 로딩 메시지.
 * Sparkles 아바타 + "Thinking..." shimmer.
 */
export const ThinkingMessage = () => {
  return (
    <div className="group/message w-full" data-role="assistant" data-testid="message-assistant-loading">
      <div className="flex items-start gap-3">
        <div className="flex h-[calc(13px*1.65)] shrink-0 items-center">
          <div className="flex size-7 items-center justify-center rounded-lg bg-surface-container-high/80 text-primary ring-1 ring-outline-variant/40">
            <Sparkles size={14} />
          </div>
        </div>
        <div className="flex items-center text-[13px] leading-[1.65]">
          <Shimmer className="font-medium" duration={1.5}>
            Thinking...
          </Shimmer>
        </div>
      </div>
    </div>
  );
};

export default memo(PreviewMessage);
