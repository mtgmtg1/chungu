// [Flow: Step 1 (입력값/상태 수신) -> Step 2 (textarea 자동 높이 조정)
//       -> Step 3 (Enter 시 전송, Shift+Enter 시 줄바꿈) -> Step 4 (전송/중지 버튼)]
// Vercel ai-chatbot 템플릿의 multimodal-input.tsx + ai-elements/prompt-input.tsx 포팅.
// shadcn/ui InputGroup 대신 자체 textarea + Tailwind로 구현한다.
import { useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { ArrowUp, Square } from "lucide-react";

/**
 * PromptInput — 채팅 입력 컴포저. textarea + 전송/중지 버튼으로 구성된다.
 *
 * @param {Object} props
 * @param {string} props.value - 입력값
 * @param {(v: string) => void} props.onChange - 입력값 변경 콜백
 * @param {() => void} props.onSubmit - 전송 콜백
 * @param {() => void} [props.onStop] - 스트리밍 중지 콜백
 * @param {string} props.status - useChat status ("ready"|"submitted"|"streaming"|"error")
 * @param {string} [props.placeholder] - 플레이스홀더
 * @param {boolean} [props.autoFocus] - 마운트 시 자동 포커스
 */
export default function PromptInput({
  value,
  onChange,
  onSubmit,
  onStop,
  status,
  placeholder,
  autoFocus = false,
}) {
  const { t } = useTranslation();
  const textareaRef = useRef(null);
  const isStreaming = status === "submitted" || status === "streaming";

  // [Flow: 마운트 시 자동 포커스]
  useEffect(() => {
    if (autoFocus) {
      const timer = setTimeout(() => textareaRef.current?.focus(), 100);
      return () => clearTimeout(timer);
    }
  }, [autoFocus]);

  // [Flow: 입력값에 맞춰 textarea 높이 자동 조정]
  const adjustHeight = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, []);

  useEffect(() => {
    adjustHeight();
  }, [value, adjustHeight]);

  // [Flow: Enter=전송, Shift+Enter=줄바꿈]
  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (!isStreaming && value.trim()) {
        onSubmit();
      }
    }
  };

  const handleSubmit = (e) => {
    e?.preventDefault();
    if (isStreaming) {
      onStop?.();
      return;
    }
    if (value.trim()) {
      onSubmit();
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="relative flex w-full flex-col rounded-2xl border border-outline-variant/30 bg-surface-container-lowest/80 shadow-sm transition-shadow duration-300 focus-within:border-primary/20 focus-within:shadow-md"
      data-oid="ai-chat-prompt-input"
    >
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder || t("page:agent.inputPlaceholder", "무엇을 도와드릴까요?")}
        rows={1}
        className="max-h-[200px] min-h-[24px] w-full resize-none bg-transparent px-4 pt-3.5 pb-2 text-[13px] leading-relaxed text-on-surface outline-none placeholder:text-on-surface-variant/40 custom-scrollbar"
        data-testid="ai-chat-textarea"
      />
      {/* 푸터: 좌측 힌트, 우측 전송/중지 버튼 */}
      <div className="flex items-center justify-between px-3 pb-2.5">
        <div className="flex items-center gap-2 text-[11px] text-on-surface-variant/60">
          <kbd className="rounded border border-outline-variant/40 px-1 py-0.5 font-mono text-[10px]">
            ↵
          </kbd>
          <span className="hidden sm:inline">{t("page:agent.sendHint", "전송")}</span>
          <span className="text-on-surface-variant/30">·</span>
          <kbd className="rounded border border-outline-variant/40 px-1 py-0.5 font-mono text-[10px]">
            ⇧↵
          </kbd>
          <span className="hidden sm:inline">{t("page:agent.newlineHint", "줄바꿈")}</span>
        </div>

        {isStreaming ? (
          // 중지 버튼
          <button
            type="button"
            onClick={onStop}
            className="flex h-7 w-7 items-center justify-center rounded-xl bg-surface-container-high text-on-surface-variant transition-all hover:bg-surface-container-highest active:scale-95"
            aria-label={t("page:agent.stop", "중지")}
            data-testid="ai-chat-stop"
          >
            <Square size={14} className="fill-current" />
          </button>
        ) : (
          // 전송 버튼
          <button
            type="submit"
            disabled={!value.trim()}
            className={`flex h-7 w-7 items-center justify-center rounded-xl transition-all duration-200 active:scale-95 ${
              value.trim()
                ? "bg-primary text-white hover:opacity-85"
                : "cursor-not-allowed bg-surface-container-high text-on-surface-variant/30"
            }`}
            aria-label={t("common:send", "전송")}
            data-testid="ai-chat-send"
          >
            <ArrowUp size={16} />
          </button>
        )}
      </div>
    </form>
  );
}
