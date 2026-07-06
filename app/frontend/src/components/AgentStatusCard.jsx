// [Flow: Step 1 (run 상태 수신) -> Step 2 (running/processing이면 스피너 표시)
//       -> Step 3 (interrupted면 승인 요청 버튼 표시) -> Step 4 (done/error면 상태 메시지 표시)]
import { useTranslation } from "react-i18next";
import { Loader2, AlertCircle, CheckCircle, HelpCircle } from "lucide-react";

export default function AgentStatusCard({ run, onApprove, onReject, onCancel }) {
  const { t } = useTranslation();
  if (!run) return null;

  const status = run.status;
  const interrupt = run.pending_interrupt;

  return (
    <div className="bg-surface rounded-lg shadow border border-outline-variant p-3 mb-2 max-w-sm">
      <div className="flex items-center gap-2 mb-2">
        {status === "running" || status === "processing" ? (
          <Loader2 size={16} className="animate-spin text-primary" />
        ) : status === "interrupted" ? (
          <HelpCircle size={16} className="text-warning" />
        ) : status === "error" ? (
          <AlertCircle size={16} className="text-error" />
        ) : (
          <CheckCircle size={16} className="text-success" />
        )}
        <span className="text-sm font-medium text-on-surface">
          {t(`page:agent.status${status.charAt(0).toUpperCase() + status.slice(1)}`, status)}
        </span>
      </div>

      {interrupt && (
        <div className="text-xs text-on-surface-variant mb-2">
          {typeof interrupt === "string" ? interrupt : JSON.stringify(interrupt)}
        </div>
      )}

      <div className="flex gap-2 justify-end">
        {status === "interrupted" && (
          <>
            <button
              type="button"
              onClick={onReject}
              className="px-2 py-1 text-xs rounded border border-outline-variant text-on-surface-variant hover:bg-surface-container-high"
            >
              {t("common:reject")}
            </button>
            <button
              type="button"
              onClick={onApprove}
              className="px-2 py-1 text-xs rounded bg-primary text-white hover:bg-primary/90"
            >
              {t("common:approve")}
            </button>
          </>
        )}
        {(status === "running" || status === "processing" || status === "interrupted") && onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="px-2 py-1 text-xs rounded border border-outline-variant text-on-surface-variant hover:bg-surface-container-high"
          >
            {t("common:cancel")}
          </button>
        )}
      </div>
    </div>
  );
}
