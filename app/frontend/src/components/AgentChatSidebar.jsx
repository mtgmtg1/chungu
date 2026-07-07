// [Flow: Step 1 (대화 목록 + 현재 ID + 콜백 수신) -> Step 2 (새 대화 버튼 렌더링)
//       -> Step 3 (대화 목록 렌더링) -> Step 4 (클릭 시 선택/생성 콜백 호출)]
// AI 채팅 팝업 왼쪽에 표시되는 사이드바.
// 현재 프로젝트의 이전 대화 제목 목록과 새 대화 버튼을 제공한다.
import { useTranslation } from "react-i18next";
import { MessageSquare, Plus } from "lucide-react";

/**
 * [Flow: Step 1 (타임스탬프 + 번역/로캘) -> Step 2 (간결한 상대 날짜 문자열 반환)]
 *
 * @param {number} timestamp - 밀리초 단위 타임스탬프
 * @param {Function} t - react-i18next 번역 함수
 * @param {string} [locale] - 브라우저/앱 로캘
 * @returns {string} "오늘/어제" 또는 날짜 문자열
 */
function formatRelativeDate(timestamp, t, locale) {
  const date = new Date(timestamp);
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const startOfMessageDay = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  const diffDays = Math.round((startOfToday - startOfMessageDay) / 86400000);

  if (diffDays === 0) return t("common:date.today", "오늘");
  if (diffDays === 1) return t("common:date.yesterday", "어제");
  return date.toLocaleDateString(locale || "ko-KR", { month: "short", day: "numeric" });
}

/**
 * [Flow: Step 1 (props 수신) -> Step 2 (새 대화 버튼 + 대화 목록 렌더링)]
 *
 * @param {Object} props
 * @param {Array} props.conversations - ChatConversation 배열
 * @param {string|null} props.currentId - 현재 선택된 대화 ID
 * @param {() => void} props.onNewChat - 새 대화 생성 콜백
 * @param {(id: string) => void} props.onSelect - 대화 선택 콜백
 * @param {(id: string) => void} [props.onDelete] - 대화 삭제 콜백(선택)
 */
export default function AgentChatSidebar({
  conversations,
  currentId,
  onNewChat,
  onSelect,
}) {
  const { t, i18n } = useTranslation();

  return (
    <div className="flex h-full w-[200px] flex-shrink-0 flex-col border-r border-outline-variant/30 bg-surface-container-lowest/60 md:w-[230px]">
      {/* 헤더 */}
      <div className="flex flex-shrink-0 items-center gap-2 border-b border-outline-variant/30 px-4 py-3.5">
        <div className="flex size-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3l1.9 5.8L20 10.7l-5.8 1.9L12 18.4l-1.9-5.8L4 10.7l5.8-1.9L12 3z" />
          </svg>
        </div>
        <span className="font-semibold text-sm text-on-surface">
          {t("page:agent.chatTitle", "PROOF AI")}
        </span>
      </div>

      {/* 새 대화 버튼 */}
      <div className="flex-shrink-0 p-3">
        <button
          type="button"
          onClick={onNewChat}
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-outline-variant/40 bg-surface px-3 py-2 text-sm font-medium text-on-surface shadow-sm transition-all hover:border-primary/30 hover:bg-surface-container-low active:scale-[0.98]"
          data-oid="agent-chat-new"
        >
          <Plus size={16} />
          {t("page:agent.newChat", "새 대화")}
        </button>
      </div>

      {/* 대화 목록 */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-3">
        {conversations.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-6 text-center text-xs text-on-surface-variant/60">
            <MessageSquare size={20} />
            {t("page:agent.noConversations", "이전 대화가 없습니다")}
          </div>
        ) : (
          <div className="flex flex-col gap-1">
            {conversations.map((conversation) => {
              const isActive = conversation.id === currentId;
              return (
                <button
                  key={conversation.id}
                  type="button"
                  onClick={() => onSelect(conversation.id)}
                  className={`flex flex-col items-start gap-0.5 rounded-lg px-3 py-2.5 text-left transition-colors ${
                    isActive
                      ? "bg-primary/10 text-primary"
                      : "text-on-surface hover:bg-surface-container-high"
                  }`}
                  data-oid={`agent-chat-item-${conversation.id}`}
                >
                  <span className="w-full truncate text-[13px] font-medium leading-snug">
                    {conversation.title || t("page:agent.untitled", "제목 없음")}
                  </span>
                  <span className={`text-[10px] ${isActive ? "text-primary/70" : "text-on-surface-variant/60"}`}>
                    {formatRelativeDate(conversation.updatedAt, t, i18n.language)}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
