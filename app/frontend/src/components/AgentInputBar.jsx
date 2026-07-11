// [Flow: Step 1 (onOpenChat + runningCount 수신) -> Step 2 (헤더 중앙에 컴팩트 AI 트리거 렌더링)
//       -> Step 3 (runningCount > 0이면 배지 + 프로그레스 링 표시) -> Step 4 (클릭 시 onOpenChat 호출)]
// 헤더 메뉴바 정중앙에 배치되는 AI 에이전트 트리거 버튼.
// 실제 입력은 채팅 팝업에서 이루어지므로 이 컴포넌트는 버튼 역할만 한다.
// 백그라운드에서 실행 중인 에이전트 수를 배지로 표시하며, 프로그레스 링이 회전한다.
import { useTranslation } from "react-i18next";
import { ArrowUp, Sparkles } from "lucide-react";

/**
 * [Flow: Step 1 (props 수신) -> Step 2 (트리거 렌더링) -> Step 3 (실행 중이면 배지 표시)]
 *
 * @param {Object} props
 * @param {() => void} props.onOpenChat - 트리거 클릭 시 호출
 * @param {number} [props.runningCount=0] - 백그라운드에서 실행 중인 에이전트 수
 */
export default function AgentInputBar({ onOpenChat, runningCount = 0 }) {
  const { t } = useTranslation();
  const isRunning = runningCount > 0;

  const handleClick = () => {
    onOpenChat?.();
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      className="flex items-center gap-2 rounded-full border border-outline-variant/30 bg-surface-container-high px-3 md:px-4 py-1.5 text-sm font-medium shadow-sm transition-all duration-200 hover:border-primary/30 hover:bg-surface-container-high/80 hover:shadow-md active:scale-[0.98]"
      aria-label={t("page:agent.inputPlaceholder", "AI에게 무엇을 도와드릴까요?")}
      data-oid="agent-input-trigger"
    >
      {/* Sparkles 아이콘 + 실행 중 프로그레스 링 + 배지 */}
      <div className="relative flex-shrink-0">
        <div className="flex size-6 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Sparkles size={14} />
        </div>
        {/* 실행 중 프로그레스 링 — Sparkles 아이콘 주변을 회전 */}
        {isRunning && (
          <span
            className="agent-progress-ring pointer-events-none absolute -inset-[3px] rounded-[11px]"
            aria-hidden="true"
          />
        )}
        {/* 실행 중 에이전트 수 배지 */}
        {isRunning && (
          <span
            className="agent-running-badge absolute -right-2 -top-2 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-primary px-1 text-[10px] font-bold leading-none text-white shadow-md"
            aria-label={t("page:agent.runningCount", "{{count}}개 에이전트 실행 중", { count: runningCount })}
            data-oid="agent-running-badge"
          >
            {runningCount > 9 ? "9+" : runningCount}
          </span>
        )}
      </div>
      <span className="min-w-0 max-w-[140px] md:max-w-[200px] truncate bg-transparent text-left text-sm text-on-surface-variant/80">
        {isRunning
          ? t("page:agent.runningHint", "{{count}}개 에이전트 실행 중…", { count: runningCount })
          : t("page:agent.inputPlaceholder", "AI에게 무엇을 도와드릴까요?")}
      </span>
      <div className="flex size-6 flex-shrink-0 items-center justify-center rounded-full bg-primary text-white transition-all duration-200">
        <ArrowUp size={14} />
      </div>
    </button>
  );
}
