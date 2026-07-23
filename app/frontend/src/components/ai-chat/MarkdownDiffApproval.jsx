// [Flow: Step 1 (original_markdown / edited_markdown 수신)
//       -> Step 2 (diff 라이브러리로 라인 단위 diff 생성)
//       -> Step 3 (추가/삭제/변경 라인을 색상으로 구분해 렌더링)
//       -> Step 4 (수락 시 api.saveResultPage 직접 호출 -> 승인 콜백)
//       -> Step 5 (거부 시 거부 콜백)]
// 마크다운 에디터 AI 편집 결과를 diff로 보여주고 사용자 승인 후에만 저장하는 컴포넌트.
// apply_edits 도구가 requires_approval: true 와 함께 반환한 original/edited 마크다운을
// 라인 단위로 비교하여 추가(녹색)/삭제(적색) 라인을 하이라이트한다.
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { diffLines } from "diff";
import {
  Check,
  X,
  Loader2,
  AlertCircle,
  FileText,
} from "lucide-react";
import { api } from "../../api.js";

/**
 * [Flow: Step 1 (diff 계산) -> Step 2 (추가/삭제 카운트 집계) -> Step 3 (라인별 색상 렌더링)]
 *
 * DiffView — original과 edited 마크다운의 라인 단위 diff를 렌더링한다.
 *
 * @param {Object} props
 * @param {string} props.original - 원본 마크다운
 * @param {string} props.edited - AI가 편집한 마크다운
 */
function DiffView({ original, edited }) {
  const parts = useMemo(
    () => diffLines(original || "", edited || ""),
    [original, edited],
  );

  // [Flow: 추가/삭제 라인 수 집계 — 요약 표시용]
  const { addedCount, removedCount } = useMemo(() => {
    let added = 0;
    let removed = 0;
    for (const part of parts) {
      const lineCount = part.value.split("\n").filter((_, i, arr) => i < arr.length - 1 || part.value.endsWith("\n")).length;
      if (part.added) added += lineCount;
      else if (part.removed) removed += lineCount;
    }
    return { addedCount: added, removedCount: removed };
  }, [parts]);

  return (
    <div className="rounded-md border border-outline-variant/40 overflow-hidden">
      {/* 요약 헤더 */}
      <div className="flex items-center gap-3 bg-surface-container-high/50 px-3 py-1.5 text-[11px] font-medium text-on-surface-variant border-b border-outline-variant/30">
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 rounded-sm bg-green-200" />
          +{addedCount}
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 rounded-sm bg-red-200" />
          -{removedCount}
        </span>
      </div>
      {/* diff 본문 — 최대 높이 제한 후 스크롤 */}
      <div className="overflow-auto max-h-80 bg-surface-container-lowest font-mono text-[11px] leading-relaxed">
        {parts.map((part, idx) => {
          const lines = part.value.replace(/\n$/, "").split("\n");
          const bgClass = part.added
            ? "bg-green-50"
            : part.removed
              ? "bg-red-50"
              : "";
          const textClass = part.added
            ? "text-green-800"
            : part.removed
              ? "text-red-800"
              : "text-on-surface-variant";
          const prefix = part.added ? "+" : part.removed ? "-" : " ";
          return lines.map((line, lineIdx) => (
            <div
              key={`${idx}-${lineIdx}`}
              className={`flex ${bgClass} ${textClass}`}
            >
              <span className="select-none w-5 flex-shrink-0 text-center text-on-surface-variant/40 border-r border-outline-variant/20">
                {prefix}
              </span>
              <pre className="whitespace-pre-wrap break-all pl-2 pr-2 flex-1">
                {line || " "}
              </pre>
            </div>
          ));
        })}
      </div>
    </div>
  );
}

/**
 * [Flow: Step 1 (수락 클릭 -> onAccept 콜백 또는 api.saveResultPage 호출)
 *       -> Step 2 (성공 시 onApprove 콜백) -> Step 3 (실패 시 에러 표시)
 *       -> Step 4 (거부 클릭 -> onDeny 콜백)]
 *
 * MarkdownDiffApproval — 마크다운 AI 편집 결과를 diff로 보여주고 승인/거절 버튼 제공.
 * onAccept가 제공된 경우 그것을 사용하고 (예: 에디터 삽입), 없으면 api.saveResultPage로 저장한다.
 *
 * @param {Object} props
 * @param {string} [props.jobId] - Job ID (onAccept가 없을 때 저장 API 호출용)
 * @param {number} [props.pageNum] - 1-based 페이지 번호 (onAccept가 없을 때 저장 API 호출용)
 * @param {string} props.originalMarkdown - 원본 마크다운
 * @param {string} props.editedMarkdown - AI가 편집한 마크다운
 * @param {() => Promise<void>|void} [props.onAccept] - 수락 시 실행할 커스텀 로직 (예: 에디터 삽입).
 *   제공되지 않으면 api.saveResultPage로 저장. 에러를 throw하면 에러 메시지 표시.
 * @param {() => void} [props.onApprove] - 수락 완료 후 콜백 (에이전트에게 승인 메시지 전송 등)
 * @param {() => void} [props.onDeny] - 거부 후 콜백 (에이전트에게 거부 메시지 전송 등)
 * @param {string} [props.title] - 헤더 제목 (기본값: "AI 편집 내용 확인")
 */
export default function MarkdownDiffApproval({
  jobId,
  pageNum,
  originalMarkdown,
  editedMarkdown,
  onAccept,
  onApprove,
  onDeny,
  title,
}) {
  const { t } = useTranslation();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [resolved, setResolved] = useState(null); // "approved" | "denied" | null

  // [Flow: 수락 핸들러 — onAccept가 있으면 호출, 없으면 api.saveResultPage로 저장]
  const handleAccept = async () => {
    if (saving || resolved) return;
    setSaving(true);
    setError("");
    try {
      if (typeof onAccept === "function") {
        await onAccept(editedMarkdown);
      } else {
        await api.saveResultPage(jobId, pageNum, editedMarkdown);
      }
      setResolved("approved");
      onApprove?.();
    } catch (e) {
      setError(e.message || t("page:agent.diffSaveFailed", "저장에 실패했습니다."));
    } finally {
      setSaving(false);
    }
  };

  // [Flow: 거부 핸들러 — 저장 없이 거부 콜백]
  const handleReject = () => {
    if (saving || resolved) return;
    setResolved("denied");
    onDeny?.();
  };

  // [Flow: 이미 해결된 경우 상태 메시지만 표시]
  if (resolved === "approved") {
    return (
      <div className="flex items-center gap-2 rounded-lg bg-green-50 px-3 py-2 text-xs text-green-700">
        <Check size={14} />
        {t("page:agent.diffAccepted", "변경사항을 적용했습니다.")}
      </div>
    );
  }
  if (resolved === "denied") {
    return (
      <div className="flex items-center gap-2 rounded-lg bg-orange-50 px-3 py-2 text-xs text-orange-700">
        <X size={14} />
        {t("page:agent.diffRejected", "변경사항을 거부했습니다.")}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* 헤더 — 파일 정보 */}
      <div className="flex items-center gap-2 text-xs font-medium text-on-surface-variant">
        <FileText size={13} />
        {title || t("page:agent.diffTitle", "AI 편집 내용 확인")}
        {pageNum !== undefined && (
          <span className="text-on-surface-variant/50">
            ({t("page:agent.diffPage", "페이지")} {pageNum})
          </span>
        )}
      </div>

      {/* diff 본문 */}
      <DiffView original={originalMarkdown} edited={editedMarkdown} />

      {/* 에러 메시지 */}
      {error && (
        <div className="flex items-start gap-2 rounded-md bg-error-container/30 p-2.5 text-xs text-error">
          <AlertCircle size={14} className="flex-shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* 수락/거부 버튼 */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={handleAccept}
          disabled={saving}
          className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-on-primary transition-colors hover:bg-primary/90 disabled:opacity-50"
          data-oid="markdown-diff-accept"
          data-testid="markdown-diff-accept"
        >
          {saving ? (
            <Loader2 size={13} className="animate-spin" />
          ) : (
            <Check size={13} />
          )}
          {t("page:agent.diffAccept", "수락")}
        </button>
        <button
          type="button"
          onClick={handleReject}
          disabled={saving}
          className="flex items-center gap-1.5 rounded-lg border border-outline-variant px-3 py-1.5 text-xs font-medium text-on-surface-variant transition-colors hover:bg-surface-container-high disabled:opacity-50"
          data-oid="markdown-diff-reject"
          data-testid="markdown-diff-reject"
        >
          <X size={13} />
          {t("page:agent.diffReject", "거부")}
        </button>
      </div>
    </div>
  );
}
