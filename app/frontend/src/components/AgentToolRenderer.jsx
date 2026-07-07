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

  // Vercel AI SDK 5.x의 tool part 타입은 `tool-${toolName}` (정적 도구) 또는
  // `dynamic-tool` (동적 도구) 형태이며, state/input/output/errorText가 part에 직접 존재한다.
  const isToolPart = part.type === "dynamic-tool" || part.type?.startsWith("tool-");
  if (isToolPart) {
    const toolName = part.type === "dynamic-tool" ? part.toolName : part.type.slice("tool-".length);
    const { state, input, output, errorText } = part;
    const isLoading = state === "input-streaming" || state === "input-available";
    const isError = state === "output-error";
    const isSuccess = state === "output-available";

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
        {input && Object.keys(input).length > 0 && (
          <div className="text-xs text-on-surface-variant mb-1.5 font-mono">
            {JSON.stringify(input)}
          </div>
        )}
        {isLoading && (
          <div className="text-xs text-on-surface-variant">{t("page:agent.toolRunning", "도구 실행 중...")}</div>
        )}
        {isSuccess && output !== undefined && (
          <div className="text-xs text-on-surface-variant font-mono truncate">
            {JSON.stringify(output)}
          </div>
        )}
        {isError && (
          <div className="text-xs text-error">{errorText}</div>
        )}
      </div>
    );
  }

  return null;
}
