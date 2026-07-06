// [Flow: Step 1 (interrupt 값 수신) -> Step 2 (승인/거절/수정 UI 렌더링)
//       -> Step 3 (사용자 응답을 resume_value로 onResume/onReject에 전달)]
import { useState } from "react";
import { useTranslation } from "react-i18next";

export default function AgentApprovalModal({ interrupt, onApprove, onReject, onClose }) {
  const { t } = useTranslation();
  const [comment, setComment] = useState("");
  if (!interrupt) return null;

  const question = typeof interrupt === "string" ? interrupt : interrupt.question || JSON.stringify(interrupt);
  const options = interrupt.options || [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-surface rounded-lg shadow-lg border border-outline-variant p-6 w-full max-w-md">
        <h3 className="font-headline-md text-headline-md font-bold text-on-surface mb-3">
          {t("page:agent.approvalTitle")}
        </h3>
        <p className="text-sm text-on-surface-variant mb-4 whitespace-pre-wrap">{question}</p>

        {options.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-4">
            {options.map((opt) => (
              <button
                key={opt}
                type="button"
                onClick={() => onApprove(opt)}
                className="px-3 py-1.5 text-sm rounded border border-outline-variant hover:bg-surface-container-high"
              >
                {opt}
              </button>
            ))}
          </div>
        )}

        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder={t("page:agent.approvalCommentPlaceholder")}
          className="w-full px-3 py-2 border border-outline-variant rounded-lg text-sm mb-4 focus:outline-none focus:ring-2 focus:ring-primary/40 resize-none"
          rows={3}
        />

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded border border-outline-variant text-on-surface-variant hover:bg-surface-container-high"
          >
            {t("common:close")}
          </button>
          <button
            type="button"
            onClick={() => onReject(comment)}
            className="px-3 py-1.5 text-sm rounded border border-error text-error hover:bg-error/10"
          >
            {t("common:reject")}
          </button>
          <button
            type="button"
            onClick={() => onApprove(comment || options[0] || "approved")}
            className="px-3 py-1.5 text-sm rounded bg-primary text-white hover:bg-primary/90"
          >
            {t("common:approve")}
          </button>
        </div>
      </div>
    </div>
  );
}
