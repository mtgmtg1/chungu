// [Flow: Step 1 (EDiscoveryViewer 마운트) -> Step 2 (Timeline/Mapper 탭 전환)
//       -> Step 3 (Timeline 탭: EdiscoveryTimelinePanel 렌더링)
//       -> Step 4 (Mapper 탭: IssueTreeMapperPanel 렌더링)]
// e-Discovery GraphRAG 결과를 탭으로 전환하며 보여주는 뷰어.
// Graph 탭은 react-calendar-timeline 기반 수평 타임라인으로 대체되었다.

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { CalendarDays, Puzzle } from "lucide-react";
import EdiscoveryTimelinePanel from "./timeline/EdiscoveryTimelinePanel.jsx";
import IssueTreeMapperPanel from "./mapper/IssueTreeMapperPanel.jsx";

/**
 * EDiscoveryViewer — e-Discovery GraphRAG 결과를 탭으로 전환하며 시각화.
 *
 * @param {Object} props
 * @param {string} props.jobId - Job ID
 * @param {Object} props.job - Job 객체 (ediscovery_* 필드 포함)
 * @param {Function} [props.onNodeClick] - 노드/아이템 클릭 시 호출될 콜백 (node) => void
 * @param {string} [props.defaultTab="timeline"] - 초기 활성 탭 ("timeline" | "mapper")
 */
export default function EDiscoveryViewer({ jobId, job, onNodeClick, defaultTab = "timeline" }) {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState(defaultTab); // "timeline" | "mapper"
  const legalProfile = job?.ediscovery_metrics?.legal_profile;

  return (
    <div className="h-full flex flex-col" data-oid="ediscovery-viewer">
      {/* 헤더 */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-outline-variant bg-surface-container-lowest">
        <CalendarDays size={16} className="text-primary" />
        <span className="text-sm font-medium text-on-surface">{t("page:result.ediscoveryView")}</span>
        <span className="text-xs text-on-surface-variant ml-2 hidden sm:inline">{t("page:result.ediscoveryHint")}</span>
        {/* LLM 자동 추출된 법률 분야/청구 원인 */}
        {legalProfile?.legal_domain && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium whitespace-nowrap hidden sm:inline">
            {legalProfile.legal_domain}
            {legalProfile.claim_type ? ` · ${legalProfile.claim_type}` : ""}
          </span>
        )}
        {/* 탭 전환 */}
        <div className="ml-auto flex items-center gap-1 bg-surface-container-high rounded-lg p-0.5">
          <button
            onClick={() => setActiveTab("timeline")}
            className={`flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md transition-colors ${
              activeTab === "timeline"
                ? "bg-surface text-on-surface shadow-sm"
                : "text-on-surface-variant hover:text-on-surface"
            }`}
            data-oid="ediscovery-tab-timeline"
          >
            <CalendarDays size={12} />
            {t("page:result.ediscoveryTabTimeline")}
          </button>
          <button
            onClick={() => setActiveTab("mapper")}
            className={`flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md transition-colors ${
              activeTab === "mapper"
                ? "bg-surface text-on-surface shadow-sm"
                : "text-on-surface-variant hover:text-on-surface"
            }`}
            data-oid="ediscovery-tab-mapper"
          >
            <Puzzle size={12} />
            {t("page:result.mapperTabMapper")}
          </button>
        </div>
      </div>

      {/* 캔버스 — 탭에 따라 Timeline 또는 Mapper 패널 렌더링 */}
      <div className="flex-1 min-h-0 relative">
        {activeTab === "timeline" ? (
          <EdiscoveryTimelinePanel jobId={jobId} job={job} onNodeClick={onNodeClick} />
        ) : (
          <IssueTreeMapperPanel jobId={jobId} job={job} />
        )}
      </div>
    </div>
  );
}
