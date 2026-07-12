// [Flow: Step 1 (선택된 노드/아이템 데이터 수신) -> Step 2 (우측 슬라이드인 패널 렌더링)
//       -> Step 3 (원본 PDF 보기 버튼 → onScrollToPage 콜백 호출)]
// e-Discovery 뷰에서 노드/아이템 클릭 시 우측에 상세 정보를 보여주는 오버레이 패널.
// GraphCanvas와 EdiscoveryTimelinePanel에서 공유한다.

import { useTranslation } from "react-i18next";
import { X, FileText, ChevronRight } from "lucide-react";

/**
 * DetailOverlayPanel — 노드/아이템 클릭 시 우측에서 부드럽게 등장하는 상세 정보 오버레이.
 *
 * @param {Object} props
 * @param {Object|null} props.node - 선택된 노드/아이템 데이터 (null이면 닫힘)
 * @param {Function} props.onClose - 패널 닫기 콜백
 * @param {Function} props.onScrollToPage - 원본 PDF 페이지 스크롤 콜백 (pageNum) => void
 */
export default function DetailOverlayPanel({ node, onClose, onScrollToPage }) {
  const { t } = useTranslation();
  if (!node) return null;

  const data = node.data || {};
  const page = data.page;

  return (
    <div
      className="absolute top-0 right-0 h-full w-[300px] md:w-[340px] z-30 bg-surface-container-lowest border-l border-outline-variant shadow-xl flex flex-col animate-stagger-enter"
      data-oid="ediscovery-detail-panel"
    >
      {/* 헤더 — 닫기 버튼 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-outline-variant">
        <span className="text-sm font-semibold text-on-surface">{t("page:result.ediscoveryDetailTitle")}</span>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-surface-container-high text-on-surface-variant"
          title={t("page:result.ediscoveryClose")}
        >
          <X size={16} />
        </button>
      </div>

      {/* 본문 — 상세 정보 */}
      <div className="flex-1 overflow-y-auto px-4 py-3 flex flex-col gap-3">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-wide text-on-surface-variant mb-1">
            {data.type || node.type}
          </div>
          <div className="text-base font-semibold text-on-surface">{data.label}</div>
        </div>
        {data.summary && (
          <div>
            <div className="text-[10px] font-bold uppercase tracking-wide text-on-surface-variant mb-1">
              {t("page:result.ediscoverySummary")}
            </div>
            <div className="text-sm text-on-surface-variant leading-relaxed">{data.summary}</div>
          </div>
        )}
        <div className="flex flex-wrap gap-2 text-xs">
          {page && (
            <span className="px-2 py-1 rounded bg-surface-container-high text-on-surface">
              {t("page:result.ediscoveryPage")}: {page}
            </span>
          )}
          {data.confidence != null && (
            <span className="px-2 py-1 rounded bg-surface-container-high text-on-surface">
              {t("page:result.ediscoveryConfidence")}: {data.confidence.toFixed(2)}
            </span>
          )}
          {data.date && (
            <span className="px-2 py-1 rounded bg-surface-container-high text-on-surface">{data.date}</span>
          )}
        </div>
      </div>

      {/* 푸터 — 원본 PDF 보기 버튼 */}
      {page && (
        <div className="px-4 py-3 border-t border-outline-variant">
          <button
            onClick={() => onScrollToPage(page)}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-primary text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity"
          >
            <FileText size={16} />
            {t("page:result.ediscoveryViewSource")}
            <ChevronRight size={16} />
          </button>
        </div>
      )}
    </div>
  );
}
