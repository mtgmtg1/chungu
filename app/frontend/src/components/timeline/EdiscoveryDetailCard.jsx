// [Flow: Step 1 (선택된 노드 + sourceFiles 수신)
//       -> Step 2 (노드 page에 해당하는 sourceFile 조회 -> result_markdown 추출)
//       -> Step 3 (marked로 마크다운 HTML 변환, 페이지 마커 제거)
//       -> Step 4 (좌우 분할 카드 렌더링: 왼쪽 미리보기, 오른쪽 원문)
//       -> Step 5 (드래그 핸들로 좌우 비율 조절, 원본 PDF 보기 버튼으로 상위 스크롤 연동)]
// e-Discovery 타임라인 노드 클릭 시 뜨는 상세 정보 팝업 카드.
// 노드 요약/원문 마크다운과 sourceFiles 기반 미리보기를 한 화면에 보여준다.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { marked } from "marked";
import { X, FileText, ExternalLink } from "lucide-react";
import TimelinePreviewCard from "./TimelinePreviewCard.jsx";
// [Flow: PdfViewer는 내부적으로 @embedpdf/react-pdf-viewer를 동적 import하므로 정적으로 불러도 메인 번들에 포함되지 않음]
import PdfViewer from "../PdfViewer.jsx";

/** 기본 좌우 비율 — 왼쪽 미리보기 45%, 오른쪽 원문 55%. */
const DEFAULT_LEFT_RATIO = 0.45;
/** 드래그 핸들 너비 — 픽셀. */
const HANDLE_WIDTH = 8;
/** 최소/최대 비율 — 너무 좁아지지 않도록 제한. */
const MIN_RATIO = 0.25;
const MAX_RATIO = 0.75;

/**
 * 노드가 가리키는 페이지 번호를 반환한다. 숫자가 아니면 1을 기본값으로 사용한다.
 *
 * @param {Object} node - e-Discovery graph 노드
 * @returns {number} 1-based 페이지 번호
 */
function getNodePage(node) {
  const page = node?.data?.page;
  return typeof page === "number" && page > 0 ? page : 1;
}

/**
 * page 번호에 맞는 sourceFile을 찾는다.
 * 정확히 일치하는 page_num이 없으면 PDF/문서 타입을 우선으로 폴백한다.
 *
 * @param {Object} node - e-Discovery graph 노드
 * @param {Array<Object>} sourceFiles - preview API에서 받은 source_files 배열
 * @returns {Object|null} sourceFile 객체 또는 null
 */
function findSourceFile(node, sourceFiles) {
  if (!sourceFiles?.length) return null;
  const page = getNodePage(node);
  const exact = sourceFiles.find((f) => f.page_num === page);
  if (exact) return exact;
  const docFallback = sourceFiles.find((f) => ["pdf", "docx", "hwp"].includes(f.type));
  if (docFallback) return docFallback;
  return sourceFiles[0] || null;
}

/**
 * 마크다운 원문에서 페이지 마커 주석을 제거한다.
 * 상세 카드는 단일 노드의 맥락만 보여주므로 페이지 구분자는 불필요하다.
 *
 * @param {string} markdown - 원문 마크다운
 * @returns {string} 페이지 마커가 제거된 마크다운
 */
function stripPageMarkers(markdown) {
  if (!markdown) return "";
  return markdown.replace(/<!--\s*(?:페이지|page)\s*\d+\s*-->/gi, "\n").trim();
}

/**
 * EdiscoveryDetailCard — e-Discovery 타임라인 노드 상세 정보 팝업 카드.
 *
 * @param {Object} props
 * @param {Object} props.node - e-Discovery graph 노드
 * @param {Array<Object>} [props.sourceFiles] - preview API에서 받은 source_files 배열
 * @param {Function} props.onClose - 팝업 닫기 콜백
 * @param {Function} props.onViewSource - "원본 PDF 보기" 클릭 시 호출될 콜백 (node) => void
 */
export default function EdiscoveryDetailCard({ node, sourceFiles, onClose, onViewSource }) {
  const { t } = useTranslation();
  const containerRef = useRef(null);
  const [leftRatio, setLeftRatio] = useState(DEFAULT_LEFT_RATIO);
  const [isDragging, setIsDragging] = useState(false);

  const data = node?.data || {};
  const label = data.label || node?.id || "";
  const summary = data.summary || "";
  const entity = data.entity || (node?.type === "evidence" ? "third_party" : node?.type);
  const page = getNodePage(node);
  const sourceFile = useMemo(() => findSourceFile(node, sourceFiles), [node, sourceFiles]);

  /**
   * [Flow: Step 1 (sourceFile에서 preview_url/url 선택)
   *       -> Step 2 (HTTP를 HTTPS로 강제 변환하여 Mixed Content 방지)]
   */
  const sourceFileUrl = useMemo(() => {
    if (!sourceFile) return "";
    return (sourceFile.preview_url || sourceFile.url || "").replace(/^http:/, "https:");
  }, [sourceFile]);

  /**
   * [Flow: Step 1 (sourceFile.result_markdown 수신)
   *       -> Step 2 (페이지 마커 제거)
   *       -> Step 3 (marked로 HTML 변환, 실패 시 plain text 폴백)]
   */
  const markdownHtml = useMemo(() => {
    const raw = sourceFile?.result_markdown || "";
    const cleaned = stripPageMarkers(raw);
    if (!cleaned) return "";
    try {
      return marked.parse(cleaned, { breaks: true, gfm: true });
    } catch {
      return cleaned;
    }
  }, [sourceFile?.result_markdown]);

  /**
   * [Flow: Step 1 (드래그 시작) -> Step 2 (전역 mousemove/mouseup 이벤트 등록)
   *       -> Step 3 (컨테이너 너비 기준으로 leftRatio 재계산)]
   */
  const handleMouseDown = useCallback((e) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e) => {
      const container = containerRef.current;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const ratio = Math.min(MAX_RATIO, Math.max(MIN_RATIO, x / rect.width));
      setLeftRatio(ratio);
    };

    const handleMouseUp = () => {
      setIsDragging(false);
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isDragging]);

  /**
   * [Flow: Step 1 (ESC 키 감지) -> Step 2 (팝업 닫기)]
   */
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const handleViewSource = useCallback(() => {
    onViewSource?.(node);
  }, [node, onViewSource]);

  const previewData = useMemo(() => ({ sourceFiles }), [sourceFiles]);

  return (
    <div
      className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
      onClick={onClose}
      data-oid="ediscovery-detail-overlay"
    >
      <div
        ref={containerRef}
        className="w-full max-w-5xl h-[80vh] bg-surface rounded-xl shadow-2xl border border-outline-variant flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
        data-oid="ediscovery-detail-card"
      >
        {/* 헤더 */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-outline-variant bg-surface-container-lowest flex-shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <FileText size={18} className="text-primary flex-shrink-0" />
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-on-surface truncate">{label}</h3>
              <p className="text-xs text-on-surface-variant truncate">
                {entity && <span className="capitalize mr-2">{entity}</span>}
                {page > 0 && <span>p.{page}</span>}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              type="button"
              onClick={handleViewSource}
              className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-primary hover:bg-primary/10 rounded-lg transition-colors"
              data-oid="ediscovery-detail-view-source"
            >
              <ExternalLink size={14} />
              {t("page:result.ediscoveryViewSource")}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 text-on-surface-variant hover:bg-surface-container-high rounded-lg transition-colors"
              aria-label={t("page:result.ediscoveryClose")}
              data-oid="ediscovery-detail-close"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* 본문 — 좌우 분할 */}
        <div className="flex-1 min-h-0 flex relative">
          {/* 왼쪽: 미리보기 — PDF이면 EmbedPDF PdfViewer, 그 외에는 TimelinePreviewCard */}
          <div
            className="h-full overflow-hidden flex flex-col border-r border-outline-variant"
            style={{ width: `calc(${leftRatio * 100}% - ${HANDLE_WIDTH / 2}px)` }}
          >
            <div className="flex-1 min-h-0 p-3">
              {sourceFile?.type === "pdf" && sourceFileUrl ? (
                <div className="h-full w-full rounded border border-outline-variant overflow-hidden bg-surface-container-lowest">
                  <PdfViewer url={sourceFileUrl} page={page} />
                </div>
              ) : (
                <TimelinePreviewCard node={node} previewData={previewData} />
              )}
            </div>
          </div>

          {/* 드래그 핸들 */}
          <div
            className="absolute top-0 bottom-0 z-10 flex items-center justify-center cursor-col-resize hover:bg-primary/10 transition-colors"
            style={{
              left: `calc(${leftRatio * 100}% - ${HANDLE_WIDTH / 2}px)`,
              width: HANDLE_WIDTH,
            }}
            onMouseDown={handleMouseDown}
            data-oid="ediscovery-detail-resize-handle"
          >
            <div className="w-1 h-8 rounded-full bg-outline-variant" />
          </div>

          {/* 오른쪽: 원문 마크다운 */}
          <div
            className="h-full overflow-y-auto custom-scrollbar bg-surface-container-lowest"
            style={{ width: `calc(${(1 - leftRatio) * 100}% - ${HANDLE_WIDTH / 2}px)` }}
          >
            <div className="p-4">
              <h4 className="text-xs font-semibold text-on-surface-variant uppercase tracking-wider mb-3">
                {t("page:result.ediscoveryDetailTitle")}
              </h4>
              {/* 요약 블록은 result_markdown 원문이 없을 때만 별도로 표시
                  -> result_markdown이 있으면 요약 내용이 이미 원문에 포함되므로 중복 방지 */}
              {summary && !sourceFile?.result_markdown && (
                <div className="mb-4 p-3 bg-surface rounded-lg border border-outline-variant">
                  <p className="text-sm text-on-surface leading-relaxed">{summary}</p>
                </div>
              )}
              {markdownHtml ? (
                <div
                  className="prose prose-sm max-w-none text-on-surface"
                  dangerouslySetInnerHTML={{ __html: markdownHtml }}
                  data-oid="ediscovery-detail-markdown"
                />
              ) : (
                !summary && (
                  <p className="text-sm text-on-surface-variant italic">
                    {t("page:result.ediscoveryNoPreview")}
                  </p>
                )
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
