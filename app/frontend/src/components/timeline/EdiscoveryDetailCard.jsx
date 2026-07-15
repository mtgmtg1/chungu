// [Flow: Step 1 (선택 노드 + 원문 마크다운 수신)
//       -> Step 2 (헤더 + 메타데이터 + 원문 마크다운을 세로로 표시)
//       -> Step 3 (원문이 markdown이면 marked로 렌더링, 페이지 마커 제거)]
// e-Discovery Timeline 카드 "자세히 보기" 팝업.
// 원문/썸네일 미리보기 위젯은 제거하고, source_files의 result_markdown만 보여준다.

import { useTranslation } from "react-i18next";
import { marked } from "marked";
import { AlertCircle } from "lucide-react";

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
 * EdiscoveryDetailCard — "자세히 보기" 팝업 카드.
 *
 * @param {Object} props
 * @param {Object} props.node - 선택된 e-Discovery graph 노드
 * @param {string} props.originalText - 해당 노드/페이지의 원문 마크다운
 * @param {boolean} [props.originalLoading] - 원문 로딩 중 여부
 */
export default function EdiscoveryDetailCard({ node, originalText, originalLoading }) {
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
    <div className="h-full w-full flex flex-col bg-surface-container-lowest border border-outline-variant rounded-lg overflow-hidden">
      {/* 헤더 */}
      <div className="flex-shrink-0 px-4 py-3 border-b border-outline-variant bg-surface-container-low">
        <div className="text-[10px] font-bold uppercase tracking-wide text-on-surface-variant mb-1">
          {data.type || node.type}
        </div>
        <div className="text-base font-semibold text-on-surface line-clamp-2">{data.label || node.id}</div>
      </div>

      {/* 메타데이터 + 원문 (스크롤) */}
      <div className="flex-1 min-h-0 overflow-y-auto px-4 py-4 flex flex-col gap-3">
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

        {/* 원문 마크다운 */}
        <div className="flex flex-col gap-2 min-h-0">
          <div className="text-[10px] font-bold uppercase tracking-wide text-on-surface-variant">
            {t("page:result.ediscoveryOriginalText")}
          </div>
          {originalLoading ? (
            <div className="text-sm text-on-surface-variant animate-pulse">
              {t("page:result.ediscoveryPreviewLoading")}
            </div>
          ) : html ? (
            <div
              className="text-sm text-on-surface-variant leading-relaxed bg-surface-container-high rounded p-3 prose prose-sm max-w-none overflow-auto"
              dangerouslySetInnerHTML={{ __html: html }}
            />
          ) : (
            <div className="text-sm text-on-surface-variant/70 italic">
              {t("page:result.ediscoveryNoPreview")}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
