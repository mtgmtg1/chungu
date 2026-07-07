// [Flow: Step 1 (tool part 수신: type/state/input/output) -> Step 2 (상태 아이콘+배지 렌더링)
//       -> Step 3 (펼침/접힘 토글) -> Step 4 (input/output JSON 표시)]
// Vercel ai-chatbot 템플릿의 Tool 컴포넌트(ai-elements/tool.tsx) 포팅.
// shadcn/ui Collapsible 대신 useState + CSS로 자체 구현한다.
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  CheckCircle2,
  ChevronDown,
  Clock,
  Circle,
  Wrench,
  XCircle,
  AlertCircle,
} from "lucide-react";

// [Flow: tool state -> 한국어 상태 라벨 매핑]
const STATUS_LABELS = {
  "approval-requested": "승인 대기",
  "approval-responded": "응답됨",
  "input-available": "실행 중",
  "input-streaming": "대기 중",
  "output-available": "완료",
  "output-denied": "거부됨",
  "output-error": "오류",
};

// [Flow: tool state -> 상태 아이콘 + 색상 매핑]
function StatusIcon({ state }) {
  if (state === "input-available")
    return <Clock size={14} className="animate-pulse text-primary" />;
  if (state === "input-streaming")
    return <Circle size={14} className="text-on-surface-variant" />;
  if (state === "output-available")
    return <CheckCircle2 size={14} className="text-green-600" />;
  if (state === "output-error")
    return <XCircle size={14} className="text-red-600" />;
  if (state === "output-denied")
    return <XCircle size={14} className="text-orange-600" />;
  if (state === "approval-requested")
    return <Clock size={14} className="text-yellow-600" />;
  if (state === "approval-responded")
    return <CheckCircle2 size={14} className="text-blue-600" />;
  return <Circle size={14} className="text-on-surface-variant" />;
}

/**
 * Tool — 도구 호출의 진행 상태를 collapsible 카드로 표시한다.
 *
 * @param {Object} props
 * @param {string} props.toolName - 도구 이름 (예: "search_text")
 * @param {string} props.state - 도구 상태 ("input-available" | "output-available" | ...)
 * @param {any} [props.input] - 도구 입력 파라미터
 * @param {any} [props.output] - 도구 출력 결과
 * @param {string} [props.errorText] - 에러 텍스트
 * @param {boolean} [props.defaultOpen=false] - 기본 펼침 여부
 */
export default function Tool({ toolName, state, input, output, errorText, defaultOpen = false }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(defaultOpen);

  const hasInput = input && Object.keys(input).length > 0;
  const hasOutput = output !== undefined && output !== null;
  const hasError = errorText || state === "output-error";

  return (
    <div
      className="ai-chat-tool-open group mb-3 w-full rounded-lg border border-outline-variant/60 bg-surface-container-lowest/80"
      data-oid="ai-chat-tool"
    >
      {/* 헤더 (토글) */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 p-3 text-left"
      >
        <div className="flex items-center gap-2 min-w-0">
          <Wrench size={14} className="text-on-surface-variant flex-shrink-0" />
          <span className="font-medium text-sm text-on-surface truncate">{toolName}</span>
          <span className="flex items-center gap-1.5 rounded-full bg-surface-container-high px-2 py-0.5 text-xs text-on-surface-variant flex-shrink-0">
            <StatusIcon state={state} />
            {STATUS_LABELS[state] || state}
          </span>
        </div>
        <ChevronDown
          size={14}
          className={`text-on-surface-variant flex-shrink-0 transition-transform duration-200 ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {/* 본문 (펼침 시) */}
      {open && (hasInput || hasOutput || hasError) && (
        <div className="space-y-3 px-3 pb-3">
          {hasInput && (
            <div className="space-y-1.5">
              <h4 className="font-medium text-on-surface-variant text-xs uppercase tracking-wide">
                {t("page:agent.toolParameters", "매개변수")}
              </h4>
              <pre className="overflow-x-auto rounded-md bg-surface-container-high/60 p-2.5 font-mono text-xs text-on-surface-variant">
                {JSON.stringify(input, null, 2)}
              </pre>
            </div>
          )}
          {hasError && (
            <div className="space-y-1.5">
              <h4 className="font-medium text-xs uppercase tracking-wide text-error">
                {t("page:agent.toolError", "오류")}
              </h4>
              <div className="flex items-start gap-2 rounded-md bg-error-container/30 p-2.5 text-xs text-error">
                <AlertCircle size={14} className="flex-shrink-0 mt-0.5" />
                <span className="font-mono">{errorText || JSON.stringify(output)}</span>
              </div>
            </div>
          )}
          {hasOutput && !hasError && (
            <div className="space-y-1.5">
              <h4 className="font-medium text-on-surface-variant text-xs uppercase tracking-wide">
                {t("page:agent.toolResult", "결과")}
              </h4>
              <pre className="overflow-x-auto rounded-md bg-surface-container-high/60 p-2.5 font-mono text-xs text-on-surface-variant max-h-48 overflow-y-auto">
                {typeof output === "string" ? output : JSON.stringify(output, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
