// [Flow: Step 1 (sourceFiles/sourceUrl/sourceType/imageUrls/jobId 수신) -> Step 2 (단일/다중 파일에 따라 PdfViewer에 URL 전달) -> Step 3 (pdf/docx/hwp가 아니면 기존 미디어/이미지 프리뷰)]
// processing/error 상태의 주석 항목은 URL 없이 상태 정보만 표시한다.
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FileText, FileUp, FileDown, ImageIcon, Volume2, Film, Trash2, Loader2, AlertCircle, RotateCw, Sparkles, ChevronDown, ChevronUp, List, Check } from "lucide-react";
import { marked } from "marked";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import PdfViewer from "./PdfViewer.jsx";
import MediaPlayer from "./MediaPlayer.jsx";
import AnnotationListPanel from "./AnnotationListPanel.jsx";
import { api } from "../api.js";
import { useIsMobile } from "../hooks/useMediaQuery.js";

function SourceIcon({ type }) {
  if (type === "pdf") return <FileText size={16} className="text-error flex-shrink-0" />;
  if (type === "docx") return <FileText size={16} className="text-primary flex-shrink-0" />;
  if (type === "hwp") return <FileText size={16} className="text-secondary flex-shrink-0" />;
  if (type === "image") return <ImageIcon size={16} className="text-primary flex-shrink-0" />;
  if (type === "audio") return <Volume2 size={16} className="text-secondary flex-shrink-0" />;
  if (type === "video") return <Film size={16} className="text-tertiary flex-shrink-0" />;
  if (type === "file") return <FileDown size={16} className="text-tertiary flex-shrink-0" />;
  return <FileText size={16} className="text-outline flex-shrink-0" />;
}

/**
 * [Flow: Step 1 (파일 확장자 확인) -> Step 2 (텍스트 기반 파일이면 fetch로 내용 로드)
 *       -> Step 3 (마크다운은 marked로 렌더링, CSV는 표로 변환, 기타 텍스트는 pre로 표시)
 *       -> Step 4 (바이너리 파일은 다운로드 링크만 표시)]
 * file 타입 (csv, md, xlsx, txt, html, json 등) 의 미리보기를 제공한다.
 * 텍스트 기반 파일은 내용을 fetch하여 인라인 렌더링하고,
 * 바이너리 파일 (xlsx, zip 등) 은 다운로드 링크만 표시한다.
 */
function FilePreview({ file }) {
  const { t } = useTranslation();
  const filename = file.name || file.storage_path || "file";
  const sizeKb = file.size ? Math.round(file.size / 1024) : null;
  const ext = filename.split(".").pop()?.toLowerCase() || "";
  const [content, setContent] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // 텍스트 기반 파일 확장자 — fetch하여 내용을 표시
  const TEXT_EXTS = ["md", "csv", "txt", "json", "html", "svg"];
  const isTextFile = TEXT_EXTS.includes(ext);

  useEffect(() => {
    if (!isTextFile || !file.url) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch(file.url)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.text();
      })
      .then((text) => {
        if (!cancelled) {
          setContent(text);
          setLoading(false);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e.message);
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [file.url, isTextFile]);

  // [Flow: 바이너리 파일 (xlsx, zip, tar, gz 등) — 다운로드 링크만 표시]
  if (!isTextFile) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center h-full w-full text-on-surface-variant p-4 gap-4" data-oid="file-binary-preview">
        <FileDown size={48} className="text-tertiary" />
        <div className="text-center">
          <p className="font-medium text-on-surface text-sm break-all">{filename}</p>
          {sizeKb !== null && (
            <p className="text-xs text-on-surface-variant mt-1">{sizeKb} KB</p>
          )}
        </div>
        <a
          href={file.url}
          download={filename}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-white text-sm hover:opacity-90 transition-colors"
          data-oid="file-download-link"
        >
          <FileDown size={16} />
          {t("common:download") || "Download"}
        </a>
      </div>
    );
  }

  // [Flow: 로딩 중]
  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center h-full w-full text-on-surface-variant" data-oid="file-text-loading">
        <Loader2 size={24} className="animate-spin text-primary" />
      </div>
    );
  }

  // [Flow: fetch 에러 — 다운로드 링크로 폴백]
  if (error) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center h-full w-full text-on-surface-variant p-4 gap-4" data-oid="file-text-error">
        <AlertCircle size={32} className="text-error" />
        <p className="text-sm text-error">{error}</p>
        <a href={file.url} download={filename} className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-white text-sm hover:opacity-90 transition-colors">
          <FileDown size={16} />
          {t("common:download") || "Download"}
        </a>
      </div>
    );
  }

  // [Flow: 마크다운 — marked로 HTML 렌더링]
  if (ext === "md" && content) {
    const html = marked.parse(content, { breaks: true, gfm: true });
    return (
      <div className="flex-1 overflow-y-auto custom-scrollbar bg-white p-6" data-oid="file-md-preview">
        <div className="prose max-w-none focus:outline-none" dangerouslySetInnerHTML={{ __html: html }} />
      </div>
    );
  }

  // [Flow: HTML — iframe으로 렌더링]
  if (ext === "html" && content) {
    return (
      <iframe
        srcDoc={content}
        title={filename}
        className="flex-1 w-full h-full border-0 bg-white"
        sandbox=""
        data-oid="file-html-preview"
      />
    );
  }

  // [Flow: CSV — 표로 렌더링]
  if (ext === "csv" && content) {
    const rows = content.split("\n").map((row) => row.split(","));
    return (
      <div className="flex-1 overflow-auto custom-scrollbar bg-white p-4" data-oid="file-csv-preview">
        <table className="min-w-full text-xs border-collapse">
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri} className={ri === 0 ? "font-bold bg-surface-container-high" : ""}>
                {row.map((cell, ci) => (
                  <td key={ci} className="border border-outline-variant px-2 py-1 whitespace-nowrap">{cell.trim()}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  // [Flow: JSON — 포맷팅하여 표시]
  if (ext === "json" && content) {
    let formatted = content;
    try { formatted = JSON.stringify(JSON.parse(content), null, 2); } catch { /* 원본 유지 */ }
    return (
      <div className="flex-1 overflow-auto custom-scrollbar bg-surface-container-lowest p-4" data-oid="file-json-preview">
        <pre className="text-xs font-mono whitespace-pre-wrap break-words text-on-surface">{formatted}</pre>
      </div>
    );
  }

  // [Flow: SVG — 이미지로 렌더링]
  if (ext === "svg" && content) {
    return (
      <div className="flex-1 overflow-auto custom-scrollbar p-4 flex items-center justify-center bg-white" data-oid="file-svg-preview">
        <div dangerouslySetInnerHTML={{ __html: content }} />
      </div>
    );
  }

  // [Flow: 기타 텍스트 파일 (txt 등) — pre로 표시]
  return (
    <div className="flex-1 overflow-auto custom-scrollbar bg-surface-container-lowest p-4" data-oid="file-text-preview">
      <pre className="text-xs font-mono whitespace-pre-wrap break-words text-on-surface">{content || ""}</pre>
    </div>
  );
}

function SingleFilePreview({ file, filename, annotationsJson, pdfViewerRef, onAnnotationChanged }) {
  // [Flow: Step 1 (파일 타입에 따라 콘텐츠 선택) -> Step 2 (항상 동일한 높이 컨테이너로 감싸서 반환)]
  let content = null;
  if (file.type === "pdf") {
    content = <PdfViewer ref={pdfViewerRef} url={file.url} annotationsJson={annotationsJson} onAnnotationChanged={onAnnotationChanged} />;
  } else if (file.type === "docx" || file.type === "hwp") {
    content = file.preview_url ? <PdfViewer ref={pdfViewerRef} url={file.preview_url} annotationsJson={annotationsJson} onAnnotationChanged={onAnnotationChanged} /> : null;
  } else if (file.type === "image") {
    content = (
      <div className="flex-1 overflow-auto custom-scrollbar p-4 flex items-center justify-center">
        <img
          src={file.url}
          alt={filename || file.name}
          className="max-w-full max-h-full object-contain shadow-lg rounded border border-outline-variant bg-white"
        />
      </div>
    );
  } else if (file.type === "audio" || file.type === "video") {
    content = <MediaPlayer sourceType={file.type} url={file.url} filename={filename || file.name} />;
  }
  return <div className="flex flex-col h-full w-full min-h-0 overflow-hidden">{content}</div>;
}

function ImageList({ urls, t }) {
  return (
    <div className="flex flex-col h-full border-r border-outline-variant bg-surface-container-low overflow-hidden">
      <div className="p-4 border-b border-outline-variant bg-white flex-shrink-0">
        <h3 className="font-bold text-sm text-on-surface">{t("page:result.sourceImages")}</h3>
      </div>
      <div className="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-4">
        {urls.map((url, idx) => (
          <img
            key={idx}
            src={url}
            alt={t("page:result.originalImage", { number: idx + 1 })}
            className="w-full rounded border border-outline-variant bg-white shadow-sm"
            loading="lazy"
          />
        ))}
      </div>
    </div>
  );
}

/**
 * [Flow: Step 1 (annotationRuns에서 processing/error 항목만 필터링)
 *       -> Step 2 (processing이 있으면 스피너 + "N개 생성 중" 헤더 표시)
 *       -> Step 3 (각 run의 상태 아이콘 + instruction + 취소 버튼 렌더링)]
 * AI 주석 FAB 바로 위에 떠 있는 주석 생성 상태 카드입니다.
 * 완료된(done) run은 숨기고, processing 또는 error 상태의 run만 노출합니다.
 */
function AnnotationStatusCard({ runs, t, onCancelAnnotation }) {
  if (!runs || runs.length === 0) return null;
  const sorted = [...runs].sort((a, b) => (a.index ?? 0) - (b.index ?? 0));
  const visibleRuns = sorted.filter((r) => r.status === "processing" || r.status === "error");
  const processingCount = visibleRuns.filter((r) => r.status === "processing").length;
  const errorCount = visibleRuns.filter((r) => r.status === "error").length;
  // processing 또는 error가 있을 때만 표시 (done은 항상 숨김)
  if (processingCount === 0 && errorCount === 0) return null;

  const headerText = processingCount > 0
    ? t("page:result.annotateStatusProcessing", { count: processingCount })
    : t("page:result.annotateStatusError", { count: errorCount });

  return (
    <div
      className="absolute bottom-full right-0 mb-2 w-64 bg-white rounded-lg shadow-lg border border-outline-variant p-3 transition-all duration-300 origin-bottom-right"
      data-oid="annotate-status-card">
      <div className="flex items-center gap-2 mb-2 pb-2 border-b border-outline-variant">
        {processingCount > 0 ? (
          <Loader2 size={14} className="text-primary animate-spin flex-shrink-0" />
        ) : (
          <AlertCircle size={14} className="text-error flex-shrink-0" />
        )}
        <span className="text-xs font-bold text-on-surface truncate">{headerText}</span>
      </div>
      <ul className="space-y-1.5 max-h-40 overflow-y-auto custom-scrollbar">
        {visibleRuns.map((r) => (
          <li key={r.index ?? Math.random()} className="flex items-start gap-2 text-xs group">
            <span className="flex-shrink-0 mt-0.5">
              {r.status === "processing" ? (
                <Loader2 size={12} className="text-primary animate-spin" />
              ) : (
                <AlertCircle size={12} className="text-error" />
              )}
            </span>
            <span className={`min-w-0 flex-1 leading-tight ${
              r.status === "error" ? "text-error" : "text-on-surface-variant"
            }`}>
              {r.instruction
                ? r.instruction.length > 40
                  ? r.instruction.slice(0, 40) + "…"
                  : r.instruction
                : t("page:result.annotateStatusNoInstruction")}
            </span>
            {r.status === "processing" && onCancelAnnotation && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onCancelAnnotation(r.index);
                }}
                className="flex-shrink-0 p-1 rounded text-error/70 hover:text-error hover:bg-error/10 transition-colors"
                title={t("page:result.annotateCancel")}
                aria-label={t("page:result.annotateCancel")}
                data-oid="annotate-cancel-btn">
                <Trash2 size={12} />
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * [Flow: Step 1 (FAB 클릭 또는 외부 클릭으로 open 상태 토글) -> Step 2 (모드 토글: 생성/편집)
 *       -> Step 3 (instruction 입력 관리) -> Step 4 (고급 옵션 토글 시 페이지 범위 입력 표시)
 *       -> Step 5 (제출 시 모드에 따라 onStartAnnotate 또는 onStartAnnotateEdit 콜백 호출)
 *       -> Step 6 (전송 후 팝업 닫기 및 초기화) -> Step 7 (annotationRuns가 있으면 FAB 위에 상태 카드 렌더링)]
 * PDF 패널 하단 우측에 떠 있는 AI 주석 FAB입니다.
 * 클릭하면 입력 카드 팝업이 부드러운 애니메이션으로 펼쳐지며,
 * 주석 생성/편집 중에는 FAB 위에 현재 run들의 상태 리스트가 표시됩니다.
 * 상단의 세그먼트 토글로 "새 주석 생성"과 "기존 주석 편집" 모드를 전환합니다.
 * 고급 옵션을 펼치면 처리할 페이지 범위를 지정할 수 있습니다 (기본값: 현재 보고 있는 페이지).
 */
function AiAnnotationFab({
  onStartAnnotate,
  onStartAnnotateEdit,
  onCancelAnnotation,
  disabled,
  annotationRuns,
  currentPage = 1,
  totalPages = 1,
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState("create"); // "create" | "edit"
  const [instruction, setInstruction] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [pageRange, setPageRange] = useState("");
  const containerRef = useRef(null);

  // [Flow: Step 1 (팝업이 열린 경우에만 이벤트 등록) -> Step 2 (컨테이너 외부 클릭 시 팝업 닫기)]
  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  const handleSubmit = async () => {
    if (!instruction.trim()) return;
    // pageRange가 비어 있으면 현재 페이지를 기본값으로 전달
    const effectivePageRange = pageRange.trim() || String(currentPage);
    if (mode === "edit" && onStartAnnotateEdit) {
      await onStartAnnotateEdit(instruction, effectivePageRange);
    } else if (mode === "create" && onStartAnnotate) {
      await onStartAnnotate(instruction, effectivePageRange);
    } else {
      return;
    }
    setInstruction("");
    setPageRange("");
    setShowAdvanced(false);
    setOpen(false);
  };

  // processing 개수 — FAB 배지에 표시
  const processingCount = (annotationRuns || []).filter((r) => r.status === "processing").length;

  // 모드별 표시 텍스트
  const titleText = mode === "edit" ? t("page:result.annotateEditTitle") : t("page:result.annotateTitle");
  const descText = mode === "edit" ? t("page:result.annotateEditDesc") : t("page:result.annotateDesc");
  const placeholderText = mode === "edit"
    ? t("page:result.annotateEditPlaceholder")
    : t("page:result.annotateInstructionPlaceholder");

  return (
    <div ref={containerRef} className="absolute bottom-4 right-4 z-40">
      {/* 주석 생성 상태 카드 — FAB 바로 위 (작업 중일 때는 팝업 열려도 계속 표시) */}
      {processingCount > 0 && (
        <AnnotationStatusCard
          runs={annotationRuns}
          t={t}
          onCancelAnnotation={onCancelAnnotation}
        />
      )}

      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        className={`flex items-center justify-center w-10 h-10 rounded-full shadow-lg border transition-all duration-300 relative ${
          open ? "bg-primary text-white rotate-0" : "bg-surface-container-high text-primary hover:bg-surface border-outline-variant"
        } disabled:opacity-50`}
        aria-label={t("page:result.annotate")}
        data-oid="annotate-fab">
        <Sparkles size={18} />
        {processingCount > 0 && (
          <span
            className="absolute -top-1 -right-1 flex items-center justify-center min-w-[16px] h-4 px-1 rounded-full bg-primary text-white text-[9px] font-bold leading-none"
            data-oid="annotate-fab-badge">
            {processingCount}
          </span>
        )}
      </button>

      <div
        className={`absolute bottom-full right-0 mb-3 w-72 bg-white rounded-lg shadow-xl border border-outline-variant p-4 transition-all duration-300 ease-out origin-bottom-right ${
          open ? "opacity-100 scale-100 translate-y-0 pointer-events-auto" : "opacity-0 scale-95 translate-y-2 pointer-events-none"
        }`}
        data-oid="annotate-popup">
        {/* 모드 세그먼트 토글 */}
        <div className="flex items-center bg-surface-container-high rounded-lg p-1 mb-3">
          <button
            type="button"
            onClick={() => setMode("create")}
            className={`flex-1 text-xs font-bold py-1 rounded-md transition-colors ${
              mode === "create" ? "bg-white text-primary shadow-sm" : "text-on-surface-variant hover:text-on-surface"
            }`}
            data-oid="annotate-mode-create">
            {t("page:result.annotateModeCreate")}
          </button>
          <button
            type="button"
            onClick={() => setMode("edit")}
            className={`flex-1 text-xs font-bold py-1 rounded-md transition-colors ${
              mode === "edit" ? "bg-white text-primary shadow-sm" : "text-on-surface-variant hover:text-on-surface"
            }`}
            data-oid="annotate-mode-edit">
            {t("page:result.annotateModeEdit")}
          </button>
        </div>

        <h4 className="font-bold text-sm text-on-surface mb-1">
          {titleText}
        </h4>
        <p className="text-xs text-on-surface-variant mb-3">
          {descText}
        </p>
        <textarea
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          placeholder={placeholderText}
          rows={3}
          className="w-full px-3 py-2 border border-outline-variant rounded-lg text-sm mb-2 focus:outline-none focus:ring-2 focus:ring-primary/40 resize-none"
          data-oid="annotate-instruction-input" />

        {/* 고급 옵션 토글 — 페이지 범위 지정 */}
        <button
          type="button"
          onClick={() => setShowAdvanced((v) => !v)}
          className="flex items-center gap-1 text-xs text-on-surface-variant hover:text-on-surface mb-2 transition-colors"
          data-oid="annotate-advanced-toggle">
          {showAdvanced ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          {t("page:result.annotateAdvancedOptions")}
        </button>
        {showAdvanced && (
          <div className="mb-3">
            <label className="block text-xs text-on-surface-variant mb-1">
              {t("page:result.annotatePageRangeLabel")}
            </label>
            <input
              type="text"
              value={pageRange}
              onChange={(e) => setPageRange(e.target.value)}
              placeholder={t("page:result.annotatePageRangePlaceholder", { current: currentPage, total: totalPages })}
              className="w-full px-3 py-1.5 border border-outline-variant rounded-lg text-xs mb-1 focus:outline-none focus:ring-2 focus:ring-primary/40"
              data-oid="annotate-page-range-input" />
            <p className="text-[10px] text-on-surface-variant">
              {t("page:result.annotatePageRangeHint")}
            </p>
          </div>
        )}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={() => setOpen(false)}
            disabled={disabled}
            className="px-3 py-1.5 rounded-lg border border-outline-variant text-on-surface hover:bg-surface-container-high text-sm transition-colors"
            data-oid="annotate-popup-cancel">
            {t("common:actions.cancel")}
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={disabled || !instruction.trim()}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-primary text-white text-sm hover:opacity-90 transition-colors disabled:opacity-50"
            data-oid="annotate-popup-submit">
            <Check size={14} />
            {t("page:result.annotateSubmit")}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * [Flow: Step 1 (PDF 뷰어를 상대 위치 컨테이너로 감싸기) -> Step 2 (onStartAnnotate가 있으면 하단 우측에 FAB 배치)
 *       -> Step 3 (annotationRuns를 FAB에 전달해 생성 상태 카드 표시)]
 */
function PdfViewerWithFab({
  url,
  page,
  annotationsJson,
  onAnnotationChanged,
  viewerRef,
  onStartAnnotate,
  onStartAnnotateEdit,
  onCancelAnnotation,
  converting,
  annotationRuns,
  totalPages = 1,
  showAnnotationPanel = false,
  onToggleAnnotationPanel,
}) {
  const { t } = useTranslation();
  return (
    <div className="relative flex flex-col h-full w-full min-h-0 overflow-hidden">
      <PdfViewer
        ref={viewerRef}
        url={url}
        page={page}
        annotationsJson={annotationsJson}
        onAnnotationChanged={onAnnotationChanged}
      />
      {/* 주석 목록 패널 토글 버튼 — 우측 상단 */}
      {onToggleAnnotationPanel && (
        <button
          type="button"
          onClick={onToggleAnnotationPanel}
          className={`absolute top-2 right-2 z-30 flex items-center justify-center w-8 h-8 rounded-lg shadow border transition-colors ${
            showAnnotationPanel
              ? "bg-primary text-white border-primary"
              : "bg-white/90 text-on-surface-variant border-outline-variant hover:text-on-surface hover:bg-white"
          }`}
          aria-label={t("page:result.annotationListTitle")}
          data-oid="annotation-panel-toggle">
          <List size={16} />
        </button>
      )}
      {/* 주석 편집 패널 — 우측에서 슬라이드 인 */}
      {showAnnotationPanel && (
        <AnnotationListPanel
          viewerRef={viewerRef}
          annotationsJson={annotationsJson}
          onAnnotationChanged={onAnnotationChanged}
          onClose={onToggleAnnotationPanel}
        />
      )}
      {onStartAnnotate && (
        <AiAnnotationFab
          onStartAnnotate={onStartAnnotate}
          onStartAnnotateEdit={onStartAnnotateEdit}
          onCancelAnnotation={onCancelAnnotation}
          disabled={converting}
          annotationRuns={annotationRuns}
          currentPage={page}
          totalPages={totalPages}
        />
      )}
    </div>
  );
}

const SourcePanel = forwardRef(function SourcePanel(props, ref) {
  const {
    sourceFiles,
    sourceUrl,
    sourceType,
    imageUrls,
    filename,
    currentPage,
    selectedFileIndex,
    onFileSelect,
    onDeleteFile,
    onSaveAnnotations,
    onRetryAnnotation,
    onStartAnnotate,
    onStartAnnotateEdit,
    onCancelAnnotation,
    onUpload,
    uploadProgress,
    converting = false,
    annotationRuns = [],
    totalPages = 1,
  } = props;
  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const files = sourceFiles && sourceFiles.length > 0 ? sourceFiles : [];
  const [internalIndex, setInternalIndex] = useState(0);
  const isControlled = selectedFileIndex !== undefined && onFileSelect;
  const selectedIndex = isControlled ? selectedFileIndex : internalIndex;
  const setSelectedIndex = isControlled ? onFileSelect : setInternalIndex;
  const pdfViewerRef = useRef(null);
  const autoSaveRef = useRef(null);
  const pendingScrollRef = useRef(null);
  const [selectedAnnotationsJson, setSelectedAnnotationsJson] = useState(null);
  const [showAnnotationPanel, setShowAnnotationPanel] = useState(false);

  const selectedFile = files[selectedIndex] || files[0];

  // [Flow: 외부 ref로 scrollToPage 노출 — FlowViewer/e-Discovery 노드 클릭 시 원본 PDF 해당 페이지로 스크롤]
  // payload: number(기존 호환) 또는 { fileIndex, pageNum } — 다른 파일로의 전환도 지원한다.
  useImperativeHandle(ref, () => ({
    scrollToPage: (payload) => {
      const isObject = typeof payload === "object" && payload !== null && !Array.isArray(payload);
      const targetIndex = isObject ? payload.fileIndex : null;
      const pageNum = isObject ? payload.pageNum : payload;

      if (typeof targetIndex === "number" && targetIndex !== selectedIndex) {
        const clamped = Math.max(0, Math.min(files.length - 1, targetIndex));
        pendingScrollRef.current = pageNum;
        setSelectedIndex(clamped);
        return;
      }

      if (pdfViewerRef.current && typeof pdfViewerRef.current.scrollToPage === "function") {
        pdfViewerRef.current.scrollToPage(pageNum);
      }
    },
  }), [pdfViewerRef, selectedIndex, setSelectedIndex, files.length]);

  /**
   * [Flow: Step 1 (PdfViewer ref로 exportAnnotations 호출) -> Step 2 (JSON 파싱)
   *       -> Step 3 (상위 onSaveAnnotations 콜백에 전달)]
   * 주석 변경 이벤트 발생 시 1초 debounce 후 자동 저장한다.
   */
  const handleSaveAnnotations = useCallback(async () => {
    if (!pdfViewerRef.current || !onSaveAnnotations) return;
    if (autoSaveRef.current) {
      clearTimeout(autoSaveRef.current);
      autoSaveRef.current = null;
    }
    const jsonString = await pdfViewerRef.current.exportAnnotations();
    if (!jsonString) return;
    try {
      const annotations = JSON.parse(jsonString);
      onSaveAnnotations(annotations);
    } catch {
      // parse error 무시
    }
  }, [onSaveAnnotations]);

  /**
   * [Flow: Step 1 (주석 변경 이벤트 수신) -> Step 2 (1초 debounce 후 자동 저장 예약)]
   */
  const handleAnnotationChanged = useCallback(() => {
    if (autoSaveRef.current) {
      clearTimeout(autoSaveRef.current);
    }
    autoSaveRef.current = setTimeout(() => {
      handleSaveAnnotations();
    }, 1000);
  }, [handleSaveAnnotations]);

  /**
   * [Flow: Step 1 (컴포넌트 언마운트 시 진행 중인 자동 저장 타이머 정리 및 남은 변경 사항 flush)]
   */
  useEffect(() => {
    return () => {
      if (autoSaveRef.current) {
        clearTimeout(autoSaveRef.current);
        autoSaveRef.current = null;
        handleSaveAnnotations();
      }
    };
  }, [handleSaveAnnotations]);

  /**
   * [Flow: Step 1 (선택된 파일이 변경되면 pending scroll 요청 처리)
   *       -> Step 2 (선택된 파일의 annotations_json_url 확인) -> Step 3 (fetch로 JSON 로드)
   *       -> Step 4 (성공 시 selectedAnnotationsJson 설정, 실패 시 null)]
   */
  useEffect(() => {
    // 다른 파일로 전환 후 예약된 페이지 스크롤이 있으면 PdfViewer 준비 후 실행한다.
    if (pendingScrollRef.current && pdfViewerRef.current && typeof pdfViewerRef.current.scrollToPage === "function") {
      const pageNum = pendingScrollRef.current;
      pendingScrollRef.current = null;
      const timer = setTimeout(() => {
        if (pdfViewerRef.current && typeof pdfViewerRef.current.scrollToPage === "function") {
          pdfViewerRef.current.scrollToPage(pageNum);
        }
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [selectedFile]);

  useEffect(() => {
    const url = selectedFile?.annotations_json_url;
    if (!url) {
      setSelectedAnnotationsJson(null);
      return;
    }
    let cancelled = false;
    fetch(url, { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        if (!cancelled) {
          setSelectedAnnotationsJson(Array.isArray(data) ? data : null);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSelectedAnnotationsJson(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedFile?.annotations_json_url]);

  // [Flow: Step 1 (파일이 0개면 안내 문구) -> Step 2 (파일이 있으면 목록 항목 렌더링) -> Step 3 (업로드 버튼이 있으면 하단에 추가)]
  function renderFileList() {
    return (
      <div className="overflow-y-auto custom-scrollbar p-2 space-y-1 h-full">
        {files.length === 0 && (
          <div className="p-4 text-center text-sm text-on-surface-variant" data-oid="source-panel-empty">
            {t("page:result.emptySourceFiles")}
          </div>
        )}
        {files.map((f, idx) => (
          <div
            key={idx}
            className={`w-full flex items-center justify-between gap-2 p-2 rounded text-xs transition-colors group ${
              selectedIndex === idx
                ? "bg-primary-container/20 text-primary font-bold"
                : "text-on-surface hover:bg-surface-container-high"
            }`}
            data-oid={`source-file-item-${idx}`}
          >
            <button
              onClick={() => setSelectedIndex(idx)}
              className="flex items-center gap-2 text-left flex-1 min-w-0"
            >
              {f.status === "processing" ? (
                <Loader2 size={16} className="text-primary animate-spin flex-shrink-0" />
              ) : f.status === "error" ? (
                <AlertCircle size={16} className="text-error flex-shrink-0" />
              ) : (
                <SourceIcon type={f.type} />
              )}
              <span className="flex flex-col items-start min-w-0">
                <span className="truncate min-w-0">{f.name}</span>
                {f.status === "error" && (
                  <span className="text-error text-[10px] leading-none mt-0.5">
                    {t("page:result.annotateFailed")}
                  </span>
                )}
              </span>
            </button>
            <div className="flex-shrink-0 flex items-center gap-1">
              {f.status === "error" && onRetryAnnotation && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    // AI 주석은 하나의 공유 파일로 축소되므로 0을 전달해
                    // 모든 error run을 한 번에 재시도한다.
                    onRetryAnnotation(0);
                  }}
                  className="flex-shrink-0 flex items-center gap-1 px-1.5 py-1 rounded text-primary/70 hover:text-primary hover:bg-primary/10 transition-colors text-[10px]"
                  title={t("page:result.annotateRetry")}
                  aria-label={t("page:result.annotateRetry")}
                >
                  <RotateCw size={14} />
                  <span>{t("page:result.annotateRetry")}</span>
                </button>
              )}
              {f.status === "error" && onDeleteFile && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteFile(f.source_index, f.source_kind);
                  }}
                  className="flex-shrink-0 flex items-center gap-1 px-1.5 py-1 rounded text-error/70 hover:text-error hover:bg-error/10 transition-colors text-[10px]"
                  title={t("page:result.annotateCancel")}
                  aria-label={t("page:result.annotateCancel")}
                >
                  <Trash2 size={14} />
                  <span>{t("page:result.annotateCancel")}</span>
                </button>
              )}
              {f.status === "processing" && onDeleteFile && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteFile(f.source_index, f.source_kind);
                  }}
                  className="flex-shrink-0 p-1 rounded text-error/70 hover:text-error hover:bg-error/10 transition-colors"
                  title={t("page:result.annotateCancel")}
                  aria-label={t("page:result.annotateCancel")}
                >
                  <Trash2 size={14} />
                </button>
              )}
              {f.status !== "error" && f.status !== "processing" && onDeleteFile && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteFile(f.source_index, f.source_kind);
                  }}
                  className="flex-shrink-0 p-1 rounded text-error/70 hover:text-error hover:bg-error/10 transition-colors"
                  title={t("common:delete")}
                  aria-label={t("common:delete")}
                >
                  <Trash2 size={14} />
                </button>
              )}
            </div>
          </div>
        ))}
        {onUpload && (
          <div className="p-2" data-oid="source-panel-upload-btn-wrap">
            <button
              type="button"
              onClick={onUpload}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg border border-dashed border-outline-variant text-on-surface-variant hover:text-primary hover:border-primary hover:bg-primary/5 transition-colors text-xs"
              data-oid="source-panel-upload-btn"
            >
              <FileUp size={16} />
              {t("page:result.uploadNewFiles")}
            </button>
          </div>
        )}
        {/* [Flow: 업로드 진행률 바 — uploadProgress.total > 0일 때 표시] */}
        {uploadProgress && uploadProgress.total > 0 && (
          <div className="p-2 border-t border-outline-variant/40" data-oid="source-panel-upload-progress">
            <div className="flex items-center gap-2 text-xs text-on-surface-variant mb-1">
              <Loader2 size={14} className="text-primary animate-spin flex-shrink-0" />
              <span className="truncate flex-1" data-oid="source-panel-prog-file">
                {uploadProgress.fileName}
              </span>
              <span className="flex-shrink-0" data-oid="source-panel-prog-count">
                {uploadProgress.current + 1}/{uploadProgress.total} ({uploadProgress.percent}%)
              </span>
            </div>
            <div className="w-full bg-surface-container h-1.5 overflow-hidden rounded-full" data-oid="source-panel-prog-bg">
              <div
                className="bg-primary h-full transition-all duration-300 rounded-full"
                style={{ width: `${uploadProgress.percent}%` }}
                data-oid="source-panel-prog-fill"
              />
            </div>
          </div>
        )}
      </div>
    );
  }

  // [Flow: Step 1 (선택된 파일이 없으면 sourceUrl/sourceType 기반 원본 확인) -> Step 2 (sourceUrl도 없으면 업로드 안내) -> Step 3 (PDF/docx/hwp면 PdfViewerWithFab) -> Step 4 (그 외 미디어는 SingleFilePreview)]
  function renderPreview() {
    if (!selectedFile) {
      if (sourceType === "pdf" && sourceUrl) {
        return (
          <PdfViewerWithFab
            viewerRef={pdfViewerRef}
            url={sourceUrl}
            page={currentPage}
            annotationsJson={selectedAnnotationsJson}
            onAnnotationChanged={handleAnnotationChanged}
            onStartAnnotate={onStartAnnotate}
            onStartAnnotateEdit={onStartAnnotateEdit}
            onCancelAnnotation={onCancelAnnotation}
            converting={converting}
            annotationRuns={annotationRuns}
            totalPages={totalPages}
            showAnnotationPanel={showAnnotationPanel}
            onToggleAnnotationPanel={() => setShowAnnotationPanel((v) => !v)}
          />
        );
      }
      if ((sourceType === "docx" || sourceType === "hwp") && sourceUrl) {
        return (
          <div className="flex flex-col h-full w-full min-h-0 overflow-hidden">
            <PdfViewer
              ref={pdfViewerRef}
              url={sourceUrl}
              page={currentPage}
              annotationsJson={selectedAnnotationsJson}
              onAnnotationChanged={handleAnnotationChanged}
            />
          </div>
        );
      }
      if (sourceType === "images" && imageUrls?.length) {
        return <ImageList urls={imageUrls} t={t} />;
      }
      if ((sourceType === "audio" || sourceType === "video") && sourceUrl) {
        return <MediaPlayer sourceType={sourceType} url={sourceUrl} filename={filename} />;
      }

      return (
        <div className="flex-1 flex flex-col items-center justify-center h-full w-full text-on-surface-variant text-sm p-4 gap-3" data-oid="source-panel-empty-preview">
          <FileText size={32} className="text-outline" />
          <span>{t("page:result.emptySourceFiles")}</span>
          {onUpload && (
            <button
              type="button"
              onClick={onUpload}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-white hover:opacity-90 transition-colors"
              data-oid="source-panel-empty-upload-btn"
            >
              <FileUp size={16} />
              {t("page:result.uploadNewFiles")}
            </button>
          )}
          {uploadProgress && uploadProgress.total > 0 && (
            <div className="w-full max-w-xs" data-oid="source-panel-empty-prog">
              <div className="flex items-center gap-2 text-xs text-on-surface-variant mb-1">
                <Loader2 size={14} className="text-primary animate-spin flex-shrink-0" />
                <span className="truncate flex-1">{uploadProgress.fileName}</span>
                <span className="flex-shrink-0">
                  {uploadProgress.current + 1}/{uploadProgress.total} ({uploadProgress.percent}%)
                </span>
              </div>
              <div className="w-full bg-surface-container h-1.5 overflow-hidden rounded-full">
                <div
                  className="bg-primary h-full transition-all duration-300 rounded-full"
                  style={{ width: `${uploadProgress.percent}%` }}
                />
              </div>
            </div>
          )}
        </div>
      );
    }

    if (selectedFile.status === "processing") {
      return (
        <div className="flex-1 flex flex-col items-center justify-center h-full w-full text-on-surface-variant text-sm p-4 gap-3" data-oid="source-panel-processing-preview">
          <Loader2 size={32} className="text-primary animate-spin" />
          <span>{t("page:result.annotateProcessingItem", { instruction: selectedFile.instruction || "" })}</span>
        </div>
      );
    }

    if (selectedFile.status === "error") {
      return (
        <div className="flex-1 flex flex-col items-center justify-center h-full w-full text-error text-sm p-4 gap-3" data-oid="source-panel-error-preview">
          <AlertCircle size={32} className="text-error" />
          <span>{t("page:result.annotateErrorItem", { instruction: selectedFile.instruction || "" })}</span>
          <div className="flex items-center gap-2">
            {onRetryAnnotation && (
              <button
                onClick={() => {
                  // AI 주석은 공유 파일로 축소되어 있으므로 0을 전달해
                  // 모든 error run을 한 번에 재시도한다.
                  onRetryAnnotation(0);
                }}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-primary text-white hover:opacity-90 transition-colors"
              >
                <RotateCw size={16} />
                {t("page:result.annotateRetry")}
              </button>
            )}
            {onDeleteFile && (
              <button
                onClick={() => onDeleteFile(selectedFile.source_index, selectedFile.source_kind)}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-error text-error hover:bg-error/10 transition-colors"
              >
                <Trash2 size={16} />
                {t("page:result.annotateCancel")}
              </button>
            )}
          </div>
        </div>
      );
    }

    if (selectedFile.type === "pdf") {
      return (
        <PdfViewerWithFab
          key={selectedFile.url}
          viewerRef={pdfViewerRef}
          url={selectedFile.url}
          page={currentPage}
          annotationsJson={selectedAnnotationsJson}
          onAnnotationChanged={handleAnnotationChanged}
          onStartAnnotate={onStartAnnotate}
          onStartAnnotateEdit={onStartAnnotateEdit}
          onCancelAnnotation={onCancelAnnotation}
          converting={converting}
          annotationRuns={annotationRuns}
          totalPages={totalPages}
          showAnnotationPanel={showAnnotationPanel}
          onToggleAnnotationPanel={() => setShowAnnotationPanel((v) => !v)}
        />
      );
    }

    if (selectedFile.type === "docx" || selectedFile.type === "hwp") {
      return (
        <PdfViewerWithFab
          viewerRef={pdfViewerRef}
          url={selectedFile.preview_url || selectedFile.url}
          page={currentPage}
          annotationsJson={selectedAnnotationsJson}
          onAnnotationChanged={handleAnnotationChanged}
          onStartAnnotate={onStartAnnotate}
          onStartAnnotateEdit={onStartAnnotateEdit}
          onCancelAnnotation={onCancelAnnotation}
          converting={converting}
          annotationRuns={annotationRuns}
          totalPages={totalPages}
          showAnnotationPanel={showAnnotationPanel}
          onToggleAnnotationPanel={() => setShowAnnotationPanel((v) => !v)}
        />
      );
    }

    if (selectedFile.type === "file") {
      return <FilePreview file={selectedFile} />;
    }

    return <SingleFilePreview file={selectedFile} filename={filename || selectedFile.name} annotationsJson={selectedAnnotationsJson} pdfViewerRef={pdfViewerRef} onAnnotationChanged={handleAnnotationChanged} />;
  }

  // [Flow: Step 1 (원본 파일 목록 패널을 항상 렌더링) -> Step 2 (선택된 파일 미리보기를 우측에 렌더링) — 모바일에서는 세로 방향으로 전환]
  return (
    <div className="flex flex-col h-full overflow-hidden bg-surface-container-low" data-oid="source-panel">
      <div className="flex-1 overflow-hidden flex min-h-0">
        <PanelGroup direction={isMobile ? "vertical" : "horizontal"} className="flex-1 flex min-h-0">
          <Panel
            defaultSize={files.length > 1 ? 35 : 25}
            minSize={15}
            maxSize={60}
            className={`overflow-hidden flex flex-col ${isMobile ? "border-b" : "border-r"} border-outline-variant`}
          >
            {renderFileList()}
          </Panel>
          <PanelResizeHandle className={`${isMobile ? "h-2 w-full cursor-row-resize" : "w-2 h-full cursor-col-resize"} bg-outline-variant/50 hover:bg-primary transition-colors`} />
          <Panel className="overflow-hidden min-h-0 flex flex-col">
            {renderPreview()}
          </Panel>
        </PanelGroup>
      </div>
    </div>
  );
});

export default SourcePanel;
