// [Flow: Step 1 (고유 쟁점 라벨 목록 수신) -> Step 2 (선택 집합과 비교) -> Step 3 (토글 칩 렌더링)]
// e-Discovery 뷰에서 사용하는 쟁점 필터 바.
// 선택되지 않은 쟁점의 노드/아이템은 hidden 대신 디밍(opacity-20 grayscale) 처리된다.
// EDiscoveryViewer와 EdiscoveryTimelinePanel에서 공유한다.

import { useTranslation } from "react-i18next";
import { Filter } from "lucide-react";

/**
 * IssueFilterBar — 그래프/타임라인에서 추출한 고유 쟁점(issue) 라벨을 토글 칩으로 표시.
 *
 * @param {Object} props
 * @param {Array<string>} props.issues - 고유 쟁점 라벨 목록
 * @param {Set<string>} props.selectedIssues - 선택된 쟁점 집합
 * @param {Function} props.onToggle - 쟁점 토글 콜백 (issueLabel) => void
 */
export default function IssueFilterBar({ issues, selectedIssues, onToggle }) {
  const { t } = useTranslation();
  if (!issues.length) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5" data-oid="ediscovery-issue-filter">
      <div className="flex items-center gap-1 text-xs text-on-surface-variant mr-1">
        <Filter size={12} />
        {t("page:result.ediscoveryIssueFilter")}
      </div>
      {issues.map((issue) => {
        const active = selectedIssues.has(issue);
        return (
          <button
            key={issue}
            onClick={() => onToggle(issue)}
            className={`px-2.5 py-1 rounded-full text-[11px] font-medium border transition-all ${
              active
                ? "bg-red-600 text-white border-red-600"
                : "bg-surface-container-low text-on-surface-variant border-outline-variant hover:border-red-400"
            }`}
          >
            {issue}
          </button>
        );
      })}
    </div>
  );
}
