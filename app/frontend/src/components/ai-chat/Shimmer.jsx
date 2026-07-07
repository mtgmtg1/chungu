// [Flow: Step 1 (children 수신) -> Step 2 (shimmer 애니메이션 클래스 적용) -> Step 3 (렌더링)]
// Vercel ai-chatbot 템플릿의 Shimmer 컴포넌트 포팅.
// "Thinking..." 등 로딩 텍스트에 그라데이션 스윕 애니메이션을 적용한다.

/**
 * Shimmer — 텍스트에 좌→우 그라데이션 스윕 애니메이션을 적용하는 로딩 인디케이터.
 *
 * @param {Object} props
 * @param {React.ReactNode} props.children - shimmer 효과를 적용할 텍스트
 * @param {string} [props.className] - 추가 클래스
 * @param {number} [props.duration=1.5] - 애니메이션 주기 (초)
 */
export default function Shimmer({ children, className = "", duration = 1.5 }) {
  return (
    <span
      className={`ai-chat-shimmer ${className}`}
      style={{ animationDuration: `${duration}s` }}
    >
      {children}
    </span>
  );
}
