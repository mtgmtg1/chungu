// [Flow: Step 1 (tool part 수신: toolName/state/input/output) -> Step 2 (i18n 라벨로 사용자 친화적 액션 표시)
//       -> Step 3 (상태 아이콘+배지 렌더링) -> Step 4 (승인 필요 시 ApprovalButtons 표시)
//       -> Step 5 (에러 시 간결 메시지만 표시, JSON 노출 금지)]
// Vercel ai-chatbot 템플릿의 Tool 컴포넌트(ai-elements/tool.tsx) 포팅.
// shadcn/ui Collapsible 대신 useState + CSS로 자체 구현한다.
// 도구 출력에 requires_approval: true가 포함된 경우 승인 버튼을 표시한다.
// 보안·가독성을 위해 원본 도구 이름·input·output JSON은 화면에 노출하지 않는다.
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
  ShieldCheck,
  ShieldAlert,
} from "lucide-react";

// [Flow: tool state -> i18n 키 매핑 (STATUS_LABELS 하드코딩 대체)]
const STATUS_I18N_KEYS = {
  "approval-requested": "page:agent.toolStatusApprovalWaiting",
  "approval-responded": "page:agent.toolStatusResponded",
  "input-available": "page:agent.toolStatusRunning",
  "input-streaming": "page:agent.toolStatusPending",
  "output-available": "page:agent.toolStatusDone",
  "output-denied": "page:agent.toolStatusDenied",
  "output-error": "page:agent.toolStatusError",
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
 * [Flow: Step 1 (도구 출력에서 requires_approval 확인) -> Step 2 (승인 상태: pending/approved/denied)
 *       -> Step 3 (버튼 클릭 시 콜백 호출) -> Step 4 (승인 후 버튼 숨김)]
 *
 * ApprovalButtons — 도구 승인이 필요할 때 표시되는 승인/거부/항상승인 버튼.
 * approvalMode가 'always'인 경우 버튼을 표시하지 않는다.
 *
 * @param {Object} props
 * @param {() => void} props.onApprove - 1회 승인 콜백
 * @param {() => void} props.onDeny - 거부 콜백
 * @param {() => void} props.onAlways - 항상 승인 콜백 (설정 저장 + 승인)
 * @param {string} props.approvalState - 현재 승인 상태 ("pending" | "approved" | "denied")
 */
function ApprovalButtons({ onApprove, onDeny, onAlways, approvalState }) {
  const { t } = useTranslation();

  // [Flow: 이미 승인/거부된 경우 상태 메시지만 표시]
  if (approvalState === "approved") {
    return (
      <div className="flex items-center gap-2 rounded-lg bg-green-50 px-3 py-2 text-xs text-green-700">
        <ShieldCheck size={14} />
        {t("page:agent.approved", "승인됨")}
      </div>
    );
  }
  if (approvalState === "denied") {
    return (
      <div className="flex items-center gap-2 rounded-lg bg-orange-50 px-3 py-2 text-xs text-orange-700">
        <ShieldAlert size={14} />
        {t("page:agent.denied", "거부됨")}
      </div>
    );
  }

  // [Flow: pending 상태 — 승인/항상 승인/거부 버튼 표시]
  return (
    <div className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        onClick={onApprove}
        className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-on-primary transition-colors hover:bg-primary/90"
        data-oid="tool-approve"
      >
        <ShieldCheck size={13} />
        {t("page:agent.approve", "승인")}
      </button>
      <button
        type="button"
        onClick={onAlways}
        className="flex items-center gap-1.5 rounded-lg border border-primary/40 bg-primary-container/20 px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary-container/40"
        data-oid="tool-always-approve"
      >
        <CheckCircle2 size={13} />
        {t("page:agent.alwaysApprove", "항상 승인")}
      </button>
      <button
        type="button"
        onClick={onDeny}
        className="flex items-center gap-1.5 rounded-lg border border-outline-variant px-3 py-1.5 text-xs font-medium text-on-surface-variant transition-colors hover:bg-surface-container-high"
        data-oid="tool-deny"
      >
        <ShieldAlert size={13} />
        {t("page:agent.deny", "거부")}
      </button>
    </div>
  );
}

/**
 * [Flow: Step 1 (toolName → i18n 라벨 조회) -> Step 2 (미정의 도구는 폴백 라벨 사용)]
 *
 * getToolLabel — 도구 원본 이름을 사용자 친화적 액션 라벨로 변환한다.
 * i18n 키: `page:agent.toolLabels.<toolName>`
 * 미정의 도구는 범용 폴백 "도구 실행" 을 반환한다.
 *
 * @param {function} t - i18n translate 함수
 * @param {string} toolName - 도구 원본 이름 (예: "search_text")
 * @returns {string} 사용자 친화적 액션 라벨
 */
function getToolLabel(t, toolName) {
  const i18nKey = `page:agent.toolLabels.${toolName}`;
  const label = t(i18nKey, "");
  // [Flow: 빈 문자열 반환 시 폴백 — 원본 이름이 아닌 범용 라벨 사용]
  if (!label || label === i18nKey) {
    return t("page:agent.toolLabelFallback", "도구 실행");
  }
  return label;
}

/**
 * [Flow: Step 1 (state + toolLabel → 표시 텍스트 결정) -> Step 2 (실행 중: "{action}하는 중...")
 *       -> Step 3 (완료: "{action} 완료") -> Step 4 (기타: 상태 라벨만)]
 *
 * getDisplayMessage — 도구 상태에 따라 사용자에게 표시할 메시지를 생성한다.
 * 진행 중일 때 접미사("하는 중...")를 붙이고, 완료 시 "완료" 접미사를 붙인다.
 *
 * @param {function} t - i18n translate 함수
 * @param {string} state - 도구 상태
 * @param {string} toolLabel - 사용자 친화적 도구 라벨
 * @returns {string} 표시 메시지
 */
function getDisplayMessage(t, state, toolLabel) {
  // [Flow: 실행 중 — "{action}하는 중..." 형태]
  if (state === "input-available" || state === "input-streaming") {
    return t("page:agent.toolInProgress", "{{action}}하는 중…", { action: toolLabel });
  }
  // [Flow: 완료 — "{action} 완료" 형태]
  if (state === "output-available") {
    return t("page:agent.toolDone", "{{action}} 완료", { action: toolLabel });
  }
  // [Flow: 거부됨]
  if (state === "output-denied") {
    return t("page:agent.toolDenied", "{{action}} 거부됨", { action: toolLabel });
  }
  // [Flow: 승인 대기 — "{action} — 승인 대기" 형태]
  if (state === "approval-requested") {
    return t("page:agent.toolApprovalWaiting", "{{action}} — 승인 대기", { action: toolLabel });
  }
  // [Flow: 응답됨]
  if (state === "approval-responded") {
    return t("page:agent.toolResponded", "{{action}} — 응답됨", { action: toolLabel });
  }
  // [Flow: 기타 상태 — 라벨만 표시]
  return toolLabel;
}

/**
 * [Flow: Step 1 (input/output JSON을 안전하게 직렬화) -> Step 2 (순환 참조/함수는 생략) -> Step 3 (문자열 반환)]
 *
 * safeJsonStringify — 도구 input/output을 읽기 쉬운 JSON으로 직렬화한다.
 * 순환 참조나 직렬화 불가능한 값이 있어도 에러를 발생시키지 않는다.
 *
 * @param {any} obj - 직렬화할 객체
 * @returns {string} 들여쓰기된 JSON 문자열
 */
function safeJsonStringify(obj) {
  if (obj === undefined || obj === null) return "";
  try {
    return JSON.stringify(obj, null, 2);
  } catch {
    return String(obj);
  }
}

/**
 * Tool — 도구 호출의 진행 상태를 사용자 친화적 카드로 표시한다.
 * 원본 도구 이름·input·output JSON은 보안·가독성을 위해 화면에 노출하지 않는다.
 * 단, isAdmin이 true인 경우(관리자 계정) 디버깅을 위해 원본 도구 이름과 input/output JSON을 표시한다.
 * 승인이 필요한 도구는 ApprovalButtons를 표시하고, 에러는 간결한 메시지만 표시한다.
 *
 * @param {Object} props
 * @param {string} props.toolName - 도구 이름 (예: "search_text") — i18n 라벨로 변환됨
 * @param {string} props.state - 도구 상태 ("input-available" | "output-available" | ...)
 * @param {any} [props.input] - 도구 입력 파라미터 (관리자 모드에서 표시, 승인 감지용)
 * @param {any} [props.output] - 도구 출력 결과 (관리자 모드에서 표시, requires_approval 감지용)
 * @param {string} [props.errorText] - 에러 텍스트 (간결 메시지로 표시)
 * @param {boolean} [props.defaultOpen=false] - 기본 펼침 여부
 * @param {string} [props.approvalMode='ask'] - 승인 모드 ("ask" | "always")
 * @param {boolean} [props.isAdmin=false] - 관리자 계정 여부 (true 시 도구 이름·JSON 표시)
 * @param {() => void} [props.onApprove] - 도구 승인 콜백
 * @param {() => void} [props.onDeny] - 도구 거부 콜백
 * @param {() => void} [props.onAlways] - 항상 승인 콜백 (설정 저장 + 승인)
 */
export default function Tool({
  toolName,
  state,
  input,
  output,
  errorText,
  defaultOpen = false,
  approvalMode = "ask",
  isAdmin = false,
  onApprove,
  onDeny,
  onAlways,
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(defaultOpen);
  // [Flow: 승인 상태 — pending(대기) | approved(승인) | denied(거부)]
  const [approvalState, setApprovalState] = useState("pending");

  const hasOutput = output !== undefined && output !== null;
  const hasError = errorText || state === "output-error";

  // [Flow: 도구 출력에서 requires_approval 감지 — output 객체는 표시하지 않고 감지에만 사용]
  const requiresApproval =
    hasOutput && !hasError && typeof output === "object" && output?.requires_approval === true;

  // [Flow: 승인 모드가 'always'이거나 이미 승인/거부된 경우 버튼 미표시]
  const showApprovalButtons =
    requiresApproval && approvalMode === "ask" && approvalState === "pending";

  // [Flow: 사용자 친화적 라벨 + 표시 메시지 생성]
  const toolLabel = getToolLabel(t, toolName);
  const displayMessage = getDisplayMessage(t, state, toolLabel);
  const statusLabel = t(STATUS_I18N_KEYS[state] || "page:agent.toolStatusPending", state);

  // [Flow: 승인 버튼 클릭 핸들러 — 상태 업데이트 후 콜백 호출]
  const handleApprove = () => {
    setApprovalState("approved");
    onApprove?.();
  };
  const handleDeny = () => {
    setApprovalState("denied");
    onDeny?.();
  };
  const handleAlways = () => {
    setApprovalState("approved");
    onAlways?.();
  };

  // [Flow: 펼침 가능 여부 — 승인 버튼, 에러, 또는 관리자 디버그 모드일 때 펼침 가능]
  const canExpand = showApprovalButtons || hasError || isAdmin;

  return (
    <div
      className="ai-chat-tool-open group mb-3 w-full rounded-lg border border-outline-variant/60 bg-surface-container-lowest/80"
      data-oid="ai-chat-tool"
    >
      {/* 헤더 (승인/에러가 있을 때만 토글 가능) */}
      <div
        className={`flex w-full items-center justify-between gap-3 p-3 text-left ${
          canExpand ? "cursor-pointer" : "cursor-default"
        }`}
        onClick={canExpand ? () => setOpen((v) => !v) : undefined}
        role={canExpand ? "button" : undefined}
      >
        <div className="flex items-center gap-2 min-w-0">
          <Wrench size={14} className="text-on-surface-variant flex-shrink-0" />
          <span className="font-medium text-sm text-on-surface truncate">
            {displayMessage}
          </span>
          {/* [Flow: 관리자 모드 — 원본 도구 이름 표시] */}
          {isAdmin && (
            <span className="font-mono text-[11px] text-on-surface-variant/60 flex-shrink-0">
              {toolName}
            </span>
          )}
          <span className="flex items-center gap-1.5 rounded-full bg-surface-container-high px-2 py-0.5 text-xs text-on-surface-variant flex-shrink-0">
            <StatusIcon state={state} />
            {statusLabel}
          </span>
          {requiresApproval && approvalState === "pending" && approvalMode === "ask" && (
            <span className="flex items-center gap-1 rounded-full bg-yellow-100 px-2 py-0.5 text-xs font-medium text-yellow-700 flex-shrink-0">
              <ShieldAlert size={11} />
              {t("page:agent.approvalRequired", "승인 필요")}
            </span>
          )}
        </div>
        {canExpand && (
          <ChevronDown
            size={14}
            className={`text-on-surface-variant flex-shrink-0 transition-transform duration-200 ${
              open ? "rotate-180" : ""
            }`}
          />
        )}
      </div>

      {/* 본문 (펼침 시) — 승인 버튼, 에러 메시지, 또는 관리자 디버그 JSON 표시 */}
      {open && canExpand && (
        <div className="space-y-3 px-3 pb-3">
          {/* 에러 메시지 — errorText만 표시, output JSON은 노출하지 않음 */}
          {hasError && (
            <div className="flex items-start gap-2 rounded-md bg-error-container/30 p-2.5 text-xs text-error">
              <AlertCircle size={14} className="flex-shrink-0 mt-0.5" />
              <span>{errorText || t("page:agent.toolGenericError", "도구 실행 중 오류가 발생했습니다.")}</span>
            </div>
          )}
          {/* 승인 버튼 영역 */}
          {requiresApproval && (
            <ApprovalButtons
              onApprove={handleApprove}
              onDeny={handleDeny}
              onAlways={handleAlways}
              approvalState={approvalState}
            />
          )}
          {/* [Flow: 관리자 디버그 모드 — input/output JSON 표시] */}
          {isAdmin && (
            <div className="space-y-2 rounded-md bg-surface-container-high/40 p-2.5">
              {input && Object.keys(input).length > 0 && (
                <div>
                  <div className="mb-1 text-[11px] font-semibold text-on-surface-variant">
                    {t("page:agent.toolDebugInput", "요청")}
                  </div>
                  <pre className="overflow-x-auto rounded bg-surface-container-lowest p-2 text-[11px] font-mono text-on-surface-variant max-h-48">
                    {safeJsonStringify(input)}
                  </pre>
                </div>
              )}
              {hasOutput && (
                <div>
                  <div className="mb-1 text-[11px] font-semibold text-on-surface-variant">
                    {t("page:agent.toolDebugOutput", "결과")}
                  </div>
                  <pre className="overflow-x-auto rounded bg-surface-container-lowest p-2 text-[11px] font-mono text-on-surface-variant max-h-64">
                    {safeJsonStringify(output)}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
