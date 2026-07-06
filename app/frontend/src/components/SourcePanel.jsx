// [Flow: Step 1 (sourceFiles/sourceUrl/sourceType/imageUrls/jobId 수신) -> Step 2 (단일/다중 파일에 따라 PdfViewer에 URL 전달) -> Step 3 (pdf/docx/hwp가 아니면 기존 미디어/이미지 프리뷰)]
// processing/error 상태의 주석 항목은 URL 없이 상태 정보만 표시한다.
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FileText, ImageIcon, Volume2, Film, Trash2, Loader2, AlertCircle, RotateCw, Sparkles, Check } from "lucide-react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import PdfViewer from "./PdfViewer.jsx";
import MediaPlayer from "./MediaPlayer.jsx";

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
 * [Flow: Step 1 (FAB 클릭 또는 외부 클릭으로 open 상태 토글) -> Step 2 (instruction 입력 관리)
 *       -> Step 3 (제출 시 onStartAnnotate 콜백 호출) -> Step 4 (전송 후 팝업 닫기 및 초기화)]
 * PDF 패널 하단 중앙에 떠 있는 AI 주석 FAB입니다.
 * 클릭하면 입력 카드 팝업이 부드러운 애니메이션으로 펼쳐집니다.
 */
function AiAnnotationFab({ onStartAnnotate, disabled }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [instruction, setInstruction] = useState("");
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
    if (!instruction.trim() || !onStartAnnotate) return;
    await onStartAnnotate(instruction);
    setInstruction("");
    setOpen(false);
  };

  return (
    <div ref={containerRef} className="absolute bottom-4 left-1/2 -translate-x-1/2 z-40">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        className={`flex items-center justify-center w-10 h-10 rounded-full shadow-lg border transition-all duration-300 ${
          open ? "bg-primary text-white rotate-0" : "bg-surface-container-high text-primary hover:bg-surface border-outline-variant"
        } disabled:opacity-50`}
        aria-label={t("page:result.annotate")}
        data-oid="annotate-fab">
        <Sparkles size={18} />
      </button>

      <div
        className={`absolute bottom-full left-1/2 -translate-x-1/2 mb-3 w-72 bg-white rounded-lg shadow-xl border border-outline-variant p-4 transition-all duration-300 ease-out origin-bottom ${
          open ? "opacity-100 scale-100 translate-y-0 pointer-events-auto" : "opacity-0 scale-95 translate-y-2 pointer-events-none"
        }`}
        data-oid="annotate-popup">
        <h4 className="font-bold text-sm text-on-surface mb-1">
          {t("page:result.annotateTitle")}
        </h4>
        <p className="text-xs text-on-surface-variant mb-3">
          {t("page:result.annotateDesc")}
        </p>
        <textarea
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          placeholder={t("page:result.annotateInstructionPlaceholder")}
          rows={3}
          className="w-full px-3 py-2 border border-outline-variant rounded-lg text-sm mb-3 focus:outline-none focus:ring-2 focus:ring-primary/40 resize-none"
          data-oid="annotate-instruction-input" />
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
 * [Flow: Step 1 (PDF 뷰어를 상대 위치 컨테이너로 감싸기) -> Step 2 (onStartAnnotate가 있으면 하단 중앙에 FAB 배치)]
 */
function PdfViewerWithFab({
  url,
  page,
  annotationsJson,
  onAnnotationChanged,
  viewerRef,
  onStartAnnotate,
  converting,
}) {
  return (
    <div className="relative flex flex-col h-full w-full min-h-0 overflow-hidden">
      <PdfViewer
        ref={viewerRef}
        url={url}
        page={page}
        annotationsJson={annotationsJson}
        onAnnotationChanged={onAnnotationChanged}
      />
      {onStartAnnotate && (
        <AiAnnotationFab
          onStartAnnotate={onStartAnnotate}
          disabled={converting}
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
  converting = false,
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
          converting={converting}
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
                      <span className="truncate">{f.name}</span>
                    </button>
                    <div className="flex-shrink-0 flex items-center gap-1">
                      {f.status === "error" && onRetryAnnotation && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onRetryAnnotation(f.source_index);
                          }}
                          className="flex-shrink-0 p-1 rounded text-primary/70 hover:text-primary hover:bg-primary/10 transition-colors"
                          title={t("page:result.annotateRetry")}
                          aria-label={t("page:result.annotateRetry")}
                        >
                          <RotateCw size={14} />
                        </button>
                      )}
                      {onDeleteFile && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onDeleteFile(f.source_index, f.source_kind);
                          }}
                          className="flex-shrink-0 p-1 rounded text-error/70 hover:text-error hover:bg-error/10 transition-colors"
                          title={f.status === "processing" ? t("page:result.annotateCancel") : t("common:delete")}
                          aria-label={f.status === "processing" ? t("page:result.annotateCancel") : t("common:delete")}
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
                  {onRetryAnnotation && (
                    <button
                      onClick={() => onRetryAnnotation(selected.source_index)}
                      className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-primary text-white hover:opacity-90 transition-colors"
                    >
                      <RotateCw size={16} />
                      {t("page:result.annotateRetry")}
                    </button>
                  )}
                </div>
              ) : selected.type === "pdf" ? (
                <PdfViewerWithFab
                  viewerRef={pdfViewerRef}
                  url={selected.preview_url || selected.url}
                  page={currentPage}
                  annotationsJson={selectedAnnotationsJson}
                  onAnnotationChanged={handleAnnotationChanged}
                  onStartAnnotate={onStartAnnotate}
                  converting={converting}
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
