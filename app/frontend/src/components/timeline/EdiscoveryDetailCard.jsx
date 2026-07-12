// [Flow: Step 1 (선택 노드 + 미리보기 메타데이터 + 원문 텍스트 수신)
//       -> Step 2 (좌측 미리보기 카드 + 우측 정보/원문 패널로 구성)
//       -> Step 3 (원문이 markdown이면 marked로 렌더링, 페이지 마커 제거)
//       -> Step 4 (원본 PDF 보기 버튼 → onViewSource 호출)]
// e-Discovery Timeline의 중앙에 표시되는 노드 상세 카드.
// 오른쪽 슬라이드인 탭 대신 한 화면에서 미리보기 + 정보 + 원문을 같이 보여준다.

import { useTranslation } from "react-i18next";
import { marked } from "marked";
import { FileText, ChevronRight, AlertCircle } from "lucide-react";
import TimelinePreviewCard from "./TimelinePreviewCard.jsx";

/**
 * 원문 텍스트에서 페이지/파일 마커 주석을 제거하고 HTML로 변환한다.
 *
 * @param {string} text - 원본 markdown 텍스트
 * @returns {string} 마커가 제거된 HTML
 */
function renderOriginalText(text) {
  if (!text) return "";
  const cleaned = text.replace(/<!--\s*(페이지|파일)\s*\d+\s*-->/gi, "").trim();
  return marked.parse(cleaned, { breaks: true, gfm: true });
}

/**
 * EdiscoveryDetailCard — 중앙 상세 카드.
 *
 * @param {Object} props
 * @param {Object} props.node - 선택된 e-Discovery graph 노드
 * @param {Object} [props.previewData] - sourceFiles 등 미리보기 메타데이터
 * @param {string} props.originalText - 해당 노드/페이지의 원문 텍스트
 * @param {boolean} [props.originalLoading] - 원문 로딩 중 여부
 * @param {Function} props.onViewSource - 원본 PDF 페이지 보기 콜백
 */
export default function EdiscoveryDetailCard({ node, previewData, originalText, originalLoading, onViewSource }) {
  const { t } = useTranslation();

  if (!node) {
    return (
      <div className="h-full w-full flex items-center justify-center text-on-surface-variant gap-2 bg-surface-container-lowest">
        <AlertCircle size={20} />
        <span className="text-sm">{t("page:result.ediscoverySelectItem")}</span>
      </div>
    );
  }

  const data = node.data || {};
  const page = data.page;
  const html = renderOriginalText(originalText);

  return (
    <div className="h-full w-full flex flex-col md:flex-row bg-surface-container-lowest border border-outline-variant rounded-lg overflow-hidden">
      {/* 좌측 — 미리보기 */}
      <div className="w-full md:w-3/5 h-1/2 md:h-full flex flex-col border-b md:border-b-0 md:border-r border-outline-variant min-h-0">
        <div className="flex-1 min-h-0 p-2">
          <TimelinePreviewCard node={node} previewData={previewData} />
        </div>
      </div>

      {/* 우측 — 정보 + 원문 */}
      <div className="w-full md:w-2/5 h-1/2 md:h-full flex flex-col min-h-0">
        {/* 헤더 */}
        <div className="flex-shrink-0 px-4 py-3 border-b border-outline-variant bg-surface-container-low">
          <div className="text-[10px] font-bold uppercase tracking-wide text-on-surface-variant mb-1">
            {data.type || node.type}
          </div>
          <div className="text-base font-semibold text-on-surface line-clamp-2">{data.label || node.id}</div>
        </div>

        {/* 메타데이터 + 원문 (스크롤) */}
        <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3 flex flex-col gap-3">
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

          {/* 원문 */}
          <div className="flex flex-col gap-2 min-h-0">
            <div className="text-[10px] font-bold uppercase tracking-wide text-on-surface-variant">
              {t("page:result.ediscoveryOriginalText")}
            </div>
            {originalLoading ? (
              <div className="text-sm text-on-surface-variant animate-pulse">{t("page:result.ediscoveryPreviewLoading")}</div>
            ) : html ? (
              <div
                className="text-sm text-on-surface-variant leading-relaxed bg-surface-container-high rounded p-2 prose prose-sm max-w-none overflow-auto"
                dangerouslySetInnerHTML={{ __html: html }}
              />
            ) : (
              <div className="text-sm text-on-surface-variant/70 italic">
                {t("page:result.ediscoveryNoPreview")}
              </div>
            )}
          </div>
        </div>

        {/* 푸터 — 원본 PDF 보기 */}
        {page && (
          <div className="flex-shrink-0 px-4 py-3 border-t border-outline-variant">
            <button
              onClick={() => onViewSource(page)}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-primary text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity"
            >
              <FileText size={16} />
              {t("page:result.ediscoveryViewSource")}
              <ChevronRight size={16} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
