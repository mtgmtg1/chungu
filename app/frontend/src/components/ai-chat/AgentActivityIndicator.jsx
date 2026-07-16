// [Flow: Step 1 (에이전트 활동 상태 수신) -> Step 2 (3개 점 웨이브 애니메이션 렌더링)
//       -> Step 3 (data-testid로 테스트 지원)]
// 에이전트가 툴 콜을 실행하거나 답변을 생성하는 동안, 가장 최신 챗에
// 부드럽게 점등되는 웨이브 애니메이션을 표시하여 동작 중임을 직관적으로 전달한다.

/**
 * WaveAnimation — 부드럽게 점등되는 3개 점 웨이브 로딩 인디케이터.
 *
 * @returns {JSX.Element} 3개 점으로 구성된 웨이브 애니메이션
 */
function WaveAnimation() {
  return (
    <div
      className="flex items-center gap-1 text-primary"
      aria-label="AI thinking"
      role="status"
    >
      <span className="agent-wave-dot" />
      <span className="agent-wave-dot" />
      <span className="agent-wave-dot" />
    </div>
  );
}

/**
 * [Flow: Step 1 (컴포넌트 마운트) -> Step 2 (어시스턴트 아바타 대신 웨이브 렌더링)]
 *
 * AgentActivityIndicator — 에이전트 동작 중 상태를 가장 최신 챗에 표시하는 인디케이터.
 * 기존 아이콘 + "thinking... / investigating..." 텍스트를 제거하고,
 * 부드럽게 점등되는 웨이브 애니메이션만 남긴다.
 */
export default function AgentActivityIndicator() {
  return (
    <div
      className="group/message w-full"
      data-role="assistant"
      data-testid="message-assistant-loading"
    >
      <div className="flex h-[calc(13px*1.65)] items-center">
        <WaveAnimation />
      </div>
    </div>
  );
}
