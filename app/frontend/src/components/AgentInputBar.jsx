// [Flow: Step 1 (onOpenChat 콜백 수신) -> Step 2 (중앙 하단에 좁은 AI 입력 트리거 렌더링)
//       -> Step 3 (클릭 시 onOpenChat 호출) -> Step 4 (채팅은 AgentChatModal 팝업에서 진행)]
// 화면 하단 중앙에 떠 있는 AI 에이전트 입력 트리거.
// 실제 입력은 채팅 팝업에서 이루어지므로 이 컴포넌트는 입력창 형태의 버튼 역할만 한다.
// 너비는 기존 입력창의 1/3 수준으로 축소한다.
import { useTranslation } from "react-i18next";
import { ArrowUp, Sparkles } from "lucide-react";

/**
 * [Flow: Step 1 (onOpenChat 콜백 수신) -> Step 2 (트리거 렌더링) -> Step 3 (클릭 시 팝업 오픈)]
 *
 * @param {Object} props
 * @param {() => void} props.onOpenChat - 트리거 클릭 시 호출
 */
export default function AgentInputBar({ onOpenChat }) {
  const { t } = useTranslation();

  const handleClick = () => {
    onOpenChat?.();
  };

  return (
    <div
      className="fixed bottom-6 left-1/2 z-40 w-full max-w-2xl -translate-x-1/2 px-4"
      data-oid="agent-input-bar"
    >
      <button
        type="button"
        onClick={handleClick}
        className="mx-auto flex w-1/3 min-w-[240px] cursor-pointer items-center gap-2.5 rounded-2xl border border-outline-variant/30 bg-surface/95 px-4 py-2.5 shadow-lg backdrop-blur-md transition-all duration-200 hover:border-primary/30 hover:bg-surface-container-lowest/80 hover:shadow-xl active:scale-[0.98]"
        aria-label={t("page:agent.inputPlaceholder", "AI에게 무엇을 도와드릴까요?")}
        data-oid="agent-input-trigger"
      >
        <div className="flex size-7 flex-shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Sparkles size={15} />
        </div>
        <span className="min-w-0 flex-1 truncate bg-transparent text-left text-sm text-on-surface-variant/70">
          {t("page:agent.inputPlaceholder", "AI에게 무엇을 도와드릴까요?")}
        </span>
        <div className="flex size-7 flex-shrink-0 items-center justify-center rounded-xl bg-primary text-white transition-all duration-200">
          <ArrowUp size={16} />
        </div>
      </button>
    </div>
  );
}
