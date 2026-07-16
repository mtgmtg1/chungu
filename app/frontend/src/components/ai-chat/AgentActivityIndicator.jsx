// [Flow: Step 1 (진행 중인 도구 라벨 수신) -> Step 2 (2초 주기로 investigating/thinking 전환)
//       -> Step 3 (Sparkles 아이콘 + 깜빡이는 텍스트 렌더링) -> Step 4 (가장 최신 챗 메시지로 표시)]
// 에이전트가 툴 콜을 실행하거나 답변을 생성하는 동안, 가장 최신 챗에
// "investigating..."과 "thinking..."을 번갈아 깜빡이며 보여주는 로딩 인디케이터.
// 툴 콜이 오래 걸릴 때에도 동작 중임을 직관적으로 전달한다.
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Sparkles } from "lucide-react";

// [Flow: 활동 단계 순환 — 0:investigating, 1:thinking]
const ACTIVITY_PHASES = ["investigating", "thinking"];

// [Flow: 단계 전환 주기 (ms) — 2초마다 investigating ↔ thinking]
const PHASE_INTERVAL_MS = 2000;

/**
 * [Flow: Step 1 (마지막 assistant 메시지의 진행 중인 tool part 수집)
 *       -> Step 2 (toolName → i18n 라벨 변환) -> Step 3 (중복 제거 후 라벨 목록 반환)]
 *
 * getActiveToolLabels — 메시지에서 현재 실행 중인 도구의 사용자 친화적 라벨을 추출한다.
 * "input-available" 또는 "input-streaming" 상태인 tool part만 활성으로 간주한다.
 *
 * @param {function} t - i18n translate 함수
 * @param {Object} message - UIMessage
 * @returns {string[]} 활성 도구 라벨 목록
 */
export function getActiveToolLabels(t, message) {
  if (!message?.parts?.length) return [];

  return message.parts
    .filter((part) => {
      const type = part.type;
      const isToolPart =
        type === "dynamic-tool" || (typeof type === "string" && type.startsWith("tool-"));
      if (!isToolPart) return false;
      return part.state === "input-available" || part.state === "input-streaming";
    })
    .map((part) => {
      const toolName = part.type === "dynamic-tool" ? part.toolName : part.type.slice("tool-".length);
      const i18nKey = `page:agent.toolLabels.${toolName}`;
      const label = t(i18nKey, "");
      return label && label !== i18nKey ? label : t("page:agent.toolLabelFallback", "작업 처리");
    })
    .filter((label, index, self) => self.indexOf(label) === index);
}

/**
 * [Flow: Step 1 (컴포넌트 마운트) -> Step 2 (2초 간격으로 phase 전환)
 *       -> Step 3 (언마운트 시 interval 정리)]
 *
 * useActivityPhase — "investigating"과 "thinking"을 번갈아 반환하는 상태 훅.
 *
 * @returns {"investigating"|"thinking"} 현재 활동 단계
 */
function useActivityPhase() {
  const [phaseIndex, setPhaseIndex] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setPhaseIndex((prev) => (prev + 1) % ACTIVITY_PHASES.length);
    }, PHASE_INTERVAL_MS);
    return () => clearInterval(timer);
  }, []);

  return ACTIVITY_PHASES[phaseIndex];
}

/**
 * [Flow: Step 1 (활동 단계 + 진행 중 도구 라벨 계산)
 *       -> Step 2 (아이콘 + 깜빡이는 텍스트 렌더링) -> Step 3 (data-testid로 테스트 지원)]
 *
 * AgentActivityIndicator — 에이전트 동작 중 상태를 가장 최신 챗에 표시하는 인디케이터.
 * "investigating..."과 "thinking..."을 2초 주기로 번갈아 깜빡이며,
 * 실행 중인 도구가 있을 경우 도구 라벨도 함께 표시한다.
 *
 * @param {Object} props
 * @param {string[]} [props.toolLabels] - 현재 실행 중인 도구의 사용자 친화적 라벨 목록
 */
export default function AgentActivityIndicator({ toolLabels = [] }) {
  const { t } = useTranslation();
  const phase = useActivityPhase();

  const displayText = useMemo(() => {
    return t(`page:agent.${phase}`, phase === "investigating" ? "investigating..." : "thinking...");
  }, [phase, t]);

  return (
    <div
      className="group/message w-full"
      data-role="assistant"
      data-testid="message-assistant-loading"
    >
      <div className="flex items-start gap-3">
        <div className="flex h-[calc(13px*1.65)] shrink-0 items-center">
          <div className="flex size-7 items-center justify-center rounded-lg bg-surface-container-high/80 text-primary ring-1 ring-outline-variant/40 animate-pulse">
            <Sparkles size={14} />
          </div>
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2 text-[13px] leading-[1.65]">
            <span
              key={phase}
              className="agent-activity-blink font-medium"
            >
              {displayText}
            </span>
            {toolLabels.length > 0 && (
              <span className="text-on-surface-variant/70">
                {toolLabels.join(", ")}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
