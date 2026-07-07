// [Flow: Step 1 (빈 채팅 상태 감지) -> Step 2 (중앙 정렬 환영 메시지 렌더링)]
// Vercel ai-chatbot 템플릿의 Greeting 컴포넌트 포팅.
// 메시지가 없을 때 중앙에 "What can I help with?" 스타일의 환영 메시지를 표시한다.
import { useTranslation } from "react-i18next";

/**
 * Greeting — 메시지가 없을 때 표시되는 환영 메시지.
 * framer-motion 대신 CSS 애니메이션(ai-chat-greeting)을 사용한다.
 */
export default function Greeting() {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col items-center px-4" key="greeting">
      <div
        className="ai-chat-greeting text-center font-semibold text-2xl tracking-tight text-on-surface md:text-3xl"
        style={{ animationDelay: "0.35s" }}
      >
        {t("page:agent.greetingTitle", "도와드릴까요?")}
      </div>
      <div
        className="ai-chat-greeting mt-3 text-center text-sm text-on-surface-variant/80"
        style={{ animationDelay: "0.5s" }}
      >
        {t("page:agent.greetingSubtitle", "PDF 주석, 마크다운, 엑셀 작업을 자연어로 요청해보세요.")}
      </div>
    </div>
  );
}
