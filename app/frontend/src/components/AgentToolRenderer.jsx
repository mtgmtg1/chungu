// [Flow: Step 1 (message.parts를 순회) -> Step 2 (text/tool part 분기)
//       -> Step 3 (tool call 상태에 따라 UI 렌더링)]
// AgentChatModal에서 AI 메시지의 tool call 진행 상태를 시각화한다.
import { useTranslation } from "react-i18next";
import { Loader2, CheckCircle2, AlertCircle, Wrench } from "lucide-react";

/**
 * [Flow: Step 1 (part 객체 수신) -> Step 2 (type에 따라 렌더링) -> Step 3 (JSX 반환)]
 *
 * @param {Object} props
 * @param {any} props.part - UIMessagePart
 * @param {string} props.messageId - 부모 메시지 ID
 */
export default function AgentToolRenderer({ part, messageId }) {
  const { t } = useTranslation();

  if (part.type === "text") {
    return (
      <div key={`${messageId}-text`} className="whitespace-pre-wrap text-sm text-on-surface">
        {part.text}
      </div>
    );
  }

  if (part.type === "tool-invocation") {
    const { state, toolName, args, result, error } = part.toolInvocation || {};
    const isLoading = state === "call" || state === "partial-call";
    const isSuccess = state === "result" && !error;
    const isError = state === "result" && error;

    return (
      <div
        key={`${messageId}-tool-${toolName}`}
        className="my-2 rounded-lg border border-outline-variant bg-surface-container-low p-3 text-sm"
        data-oid="agent-tool-card"
      >
        <div className="flex items-center gap-2 mb-1.5">
          {isLoading ? (
            <Loader2 size={14} className="animate-spin text-primary" />
          ) : isError ? (
            <AlertCircle size={14} className="text-error" />
          ) : (
            <CheckCircle2 size={14} className="text-success" />
          )}
          <span className="font-medium text-on-surface flex items-center gap-1">
            <Wrench size={12} className="text-on-surface-variant" />
            {toolName}
          </span>
        </div>
        {args && Object.keys(args).length > 0 && (
          <div className="text-xs text-on-surface-variant mb-1.5 font-mono">
            {JSON.stringify(args)}
          </div>
        )}
        {isLoading && (
          <div className="text-xs text-on-surface-variant">{t("page:agent.toolRunning", "도구 실행 중...")}</div>
        )}
        {isSuccess && result !== undefined && (
          <div className="text-xs text-on-surface-variant font-mono truncate">
            {JSON.stringify(result)}
          </div>
        )}
        {isError && (
          <div className="text-xs text-error">{error}</div>
        )}
      </div>
    );
  }

  return null;
}
