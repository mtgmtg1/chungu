// [Flow: Step 1 (sourceFiles/sourceUrl/sourceType/imageUrls/jobId 수신) -> Step 2 (단일/다중 파일에 따라 PdfViewer에 URL 전달) -> Step 3 (pdf/docx/hwp가 아니면 기존 미디어/이미지 프리뷰)]
// processing/error 상태의 주석 항목은 URL 없이 상태 정보만 표시한다.
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FileText, ImageIcon, Volume2, Film, Trash2, Loader2, AlertCircle, RotateCw, Sparkles, ChevronDown, ChevronUp, List, Check } from "lucide-react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import PdfViewer from "./PdfViewer.jsx";
import MediaPlayer from "./MediaPlayer.jsx";
import AnnotationListPanel from "./AnnotationListPanel.jsx";
import AgentStatusCard from "./AgentStatusCard.jsx";
import { api } from "../api.js";

function SourceIcon({ type }) {
  if (type === "pdf") return <FileText size={16} className="text-error flex-shrink-0" />;
  if (type === "docx") return <FileText size={16} className="text-primary flex-shrink-0" />;
  if (type === "hwp") return <FileText size={16} className="text-secondary flex-shrink-0" />;
  if (type === "image") return <ImageIcon size={16} className="text-primary flex-shrink-0" />;
  if (type === "audio") return <Volume2 size={16} className="text-secondary flex-shrink-0" />;
  if (type === "video") return <Film size={16} className="text-tertiary flex-shrink-0" />;
  return <FileText size={16} className="text-outline flex-shrink-0" />;
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
  agentRuns,
  currentPage = 1,
  totalPages = 1,
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState("create"); // "create" | "edit"
  const [instruction, setInstruction] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [pageRange, setPageRange] = useState("");
  const [localAgentRuns, setLocalAgentRuns] = useState(agentRuns || []);
  const containerRef = useRef(null);

  // [Flow: Step 1 (부모로부터 agentRuns prop 수신) -> Step 2 (로컬 상태 동기화)]
  useEffect(() => {
    setLocalAgentRuns(agentRuns || []);
  }, [agentRuns]);

  // [Flow: Step 1 (running/interrupted agent run 폴링) -> Step 2 (상태 갱신) -> Step 3 (done/error면 중단)]
  useEffect(() => {
    const active = localAgentRuns.filter((r) => ["running", "processing", "interrupted"].includes(r.status));
    if (active.length === 0) return;
    const timers = [];
    const poll = async (run) => {
      try {
        const status = await api.getAgentStatus(run.run_id);
        setLocalAgentRuns((prev) => prev.map((r) => (r.run_id === status.run_id ? status : r)));
        if (["running", "processing", "interrupted"].includes(status.status)) {
          timers.push(setTimeout(() => poll(status), 3000));
        }
      } catch (err) {
        console.error("[AgentStatus] poll error:", err);
      }
    };
    active.forEach((run) => timers.push(setTimeout(() => poll(run), 3000)));
    return () => timers.forEach(clearTimeout);
  }, [localAgentRuns]);

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
    console.log("[handleSubmit] mode=", mode, "onStartAnnotate=", typeof onStartAnnotate, "onStartAnnotateEdit=", typeof onStartAnnotateEdit);
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

  const handleApprove = async (run, value) => {
    const resumeValue = value !== undefined && value !== null ? value : { approved: true };
    try {
      const res = await api.resumeAgent(run.run_id, { resumeValue });
      setLocalAgentRuns((prev) => prev.map((r) => (r.run_id === res.run_id ? res : r)));
    } catch (err) {
      console.error("[AgentStatus] resume error:", err);
    }
  };

  const handleReject = async (run, value) => {
    const resumeValue = value !== undefined && value !== null ? value : { approved: false };
    await handleApprove(run, { approved: false, value: resumeValue });
  };

  const handleCancel = async (run) => {
    try {
      // TODO: cancel API 추가 시 연결
      setLocalAgentRuns((prev) => prev.filter((r) => r.run_id !== run.run_id));
    } catch (err) {
      console.error("[AgentStatus] cancel error:", err);
    }
  };

  // processing 개수 — FAB 배지에 표시 (legacy + agent)
  const processingCount = (annotationRuns || []).filter((r) => r.status === "processing").length +
    (localAgentRuns || []).filter((r) => ["running", "processing"].includes(r.status)).length;

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
      {/* Agent 실행 상태 카드 */}
      {(localAgentRuns || []).filter((r) => ["running", "processing", "interrupted"].includes(r.status)).map((run) => (
        <AgentStatusCard
          key={run.run_id}
          run={run}
          onApprove={(value) => handleApprove(run, value)}
          onReject={(value) => handleReject(run, value)}
          onCancel={() => handleCancel(run)}
        />
      ))}

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
  agentRuns,
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
          agentRuns={agentRuns}
          currentPage={page}
          totalPages={totalPages}
        />
      )}
    </div>
  );
}

export default function SourcePanel({
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
  converting = false,
  annotationRuns = [],
  agentRuns = [],
  totalPages = 1,
}) {
  const { t } = useTranslation();
  const files = sourceFiles && sourceFiles.length > 0 ? sourceFiles : [];
  const [internalIndex, setInternalIndex] = useState(0);
  const isControlled = selectedFileIndex !== undefined && onFileSelect;
  const selectedIndex = isControlled ? selectedFileIndex : internalIndex;
  const setSelectedIndex = isControlled ? onFileSelect : setInternalIndex;
  const pdfViewerRef = useRef(null);
  const autoSaveRef = useRef(null);
  const [selectedAnnotationsJson, setSelectedAnnotationsJson] = useState(null);
  const [showAnnotationPanel, setShowAnnotationPanel] = useState(false);

  const selectedFile = files.length > 1 ? (files[selectedIndex] || files[0]) : files[0];

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
   * [Flow: Step 1 (선택된 파일의 annotations_json_url 확인) -> Step 2 (fetch로 JSON 로드)
   *       -> Step 3 (성공 시 selectedAnnotationsJson 설정, 실패 시 null)]
   */
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

  if (files.length === 1) {
    const file = files[0];
    if (file.type === "pdf") {
      return (
        <PdfViewerWithFab
          viewerRef={pdfViewerRef}
          url={file.url}
          page={currentPage}
          annotationsJson={selectedAnnotationsJson}
          onAnnotationChanged={handleAnnotationChanged}
          onStartAnnotate={onStartAnnotate}
          onStartAnnotateEdit={onStartAnnotateEdit}
          onCancelAnnotation={onCancelAnnotation}
          converting={converting}
          annotationRuns={annotationRuns}
          agentRuns={agentRuns}
          totalPages={totalPages}
          showAnnotationPanel={showAnnotationPanel}
          onToggleAnnotationPanel={() => setShowAnnotationPanel((v) => !v)}
        />
      );
    }
    return <SingleFilePreview file={file} filename={filename || file.name} annotationsJson={selectedAnnotationsJson} pdfViewerRef={pdfViewerRef} onAnnotationChanged={handleAnnotationChanged} />;
  }

  if (files.length > 1) {
    const selected = files[selectedIndex] || files[0];
    return (
      <div className="flex flex-col h-full overflow-hidden bg-surface-container-low">
        <div className="flex-1 overflow-hidden flex min-h-0">
          <PanelGroup
            direction="horizontal"
            className="flex-1 flex min-h-0"
          >
            <Panel
              defaultSize={35}
              minSize={20}
              maxSize={60}
              className="border-r border-outline-variant overflow-hidden flex flex-col"
            >
              <div className="overflow-y-auto custom-scrollbar p-2 space-y-1 h-full">
                {files.map((f, idx) => (
                  <div
                    key={idx}
                    className={`w-full flex items-center justify-between gap-2 p-2 rounded text-xs transition-colors group ${
                      selectedIndex === idx
                        ? "bg-primary-container/20 text-primary font-bold"
                        : "text-on-surface hover:bg-surface-container-high"
                    }`}
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
                        <span className="truncate">{f.name}</span>
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
              </div>
            </Panel>
            <PanelResizeHandle className="w-2 bg-outline-variant/50 hover:bg-primary transition-colors cursor-col-resize" />
            <Panel className="overflow-hidden min-h-0 flex flex-col">
              {selected.status === "processing" ? (
                <div className="flex-1 flex flex-col items-center justify-center h-full w-full text-on-surface-variant text-sm p-4 gap-3">
                  <Loader2 size={32} className="text-primary animate-spin" />
                  <span>{t("page:result.annotateProcessingItem", { instruction: selected.instruction || "" })}</span>
                </div>
              ) : selected.status === "error" ? (
                <div className="flex-1 flex flex-col items-center justify-center h-full w-full text-error text-sm p-4 gap-3">
                  <AlertCircle size={32} className="text-error" />
                  <span>{t("page:result.annotateErrorItem", { instruction: selected.instruction || "" })}</span>
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
                        onClick={() => onDeleteFile(selected.source_index, selected.source_kind)}
                        className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-error text-error hover:bg-error/10 transition-colors"
                      >
                        <Trash2 size={16} />
                        {t("page:result.annotateCancel")}
                      </button>
                    )}
                  </div>
                </div>
              ) : selected.type === "pdf" ? (
                <PdfViewerWithFab
                  viewerRef={pdfViewerRef}
                  url={selected.preview_url || selected.url}
                  page={currentPage}
                  annotationsJson={selectedAnnotationsJson}
                  onAnnotationChanged={handleAnnotationChanged}
                  onStartAnnotate={onStartAnnotate}
                  onStartAnnotateEdit={onStartAnnotateEdit}
                  onCancelAnnotation={onCancelAnnotation}
                  converting={converting}
                  annotationRuns={annotationRuns}
                  agentRuns={agentRuns}
                  totalPages={totalPages}
                  showAnnotationPanel={showAnnotationPanel}
                  onToggleAnnotationPanel={() => setShowAnnotationPanel((v) => !v)}
                />
              ) : selected.type === "docx" || selected.type === "hwp" ? (
                <PdfViewer
                  ref={pdfViewerRef}
                  url={selected.preview_url || selected.url}
                  page={currentPage}
                  annotationsJson={selectedAnnotationsJson}
                  onAnnotationChanged={handleAnnotationChanged}
                />
              ) : (
                <SingleFilePreview file={selected} filename={selected.name} annotationsJson={selectedAnnotationsJson} pdfViewerRef={pdfViewerRef} onAnnotationChanged={handleAnnotationChanged} />
              )}
            </Panel>
          </PanelGroup>
        </div>
      </div>
    );
  }

  if (sourceType === "pdf" && sourceUrl) {
    return (
      <PdfViewerWithFab
        viewerRef={pdfViewerRef}
        url={sourceUrl}
        page={currentPage}
        annotationsJson={selectedAnnotationsJson}
        onAnnotationChanged={handleAnnotationChanged}
        onStartAnnotate={onStartAnnotate}
        converting={converting}
        annotationRuns={annotationRuns}
        agentRuns={agentRuns}
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
    <div className="flex-1 flex items-center justify-center h-full w-full text-on-surface-variant text-sm p-4">
      {t("page:components.cannotDisplaySource")}
    </div>
  );
}
