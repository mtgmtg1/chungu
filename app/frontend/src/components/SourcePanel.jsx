// [Flow: Step 1 (sourceFiles/sourceUrl/sourceType/imageUrls/jobId 수신) -> Step 2 (단일/다중 파일에 따라 PdfViewer에 URL 전달) -> Step 3 (pdf/docx/hwp가 아니면 기존 미디어/이미지 프리뷰)]
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FileText, ImageIcon, Volume2, Film, Trash2 } from "lucide-react";
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

function SingleFilePreview({ file, filename, annotationsJson, onAnnotationChanged }) {
  // [Flow: Step 1 (파일 타입에 따라 콘텐츠 선택) -> Step 2 (항상 동일한 높이 컨테이너로 감싸서 반환)]
  let content = null;
  if (file.type === "pdf") {
    content = <PdfViewer url={file.url} annotationsJson={annotationsJson} onAnnotationChanged={onAnnotationChanged} />;
  } else if (file.type === "docx" || file.type === "hwp") {
    content = file.preview_url ? <PdfViewer url={file.preview_url} annotationsJson={annotationsJson} onAnnotationChanged={onAnnotationChanged} /> : null;
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
}) {
  const { t } = useTranslation();
  const files = sourceFiles && sourceFiles.length > 0 ? sourceFiles : [];
  const [internalIndex, setInternalIndex] = useState(0);
  const isControlled = selectedFileIndex !== undefined && onFileSelect;
  const selectedIndex = isControlled ? selectedFileIndex : internalIndex;
  const setSelectedIndex = isControlled ? onFileSelect : setInternalIndex;
  const pdfViewerRef = useRef(null);
  const [selectedAnnotationsJson, setSelectedAnnotationsJson] = useState(null);
  const [hasAnnotationChanges, setHasAnnotationChanges] = useState(false);

  const selectedFile = files.length > 1 ? (files[selectedIndex] || files[0]) : files[0];

  /**
   * [Flow: Step 1 (선택된 파일의 annotations_json_url 확인) -> Step 2 (fetch로 JSON 로드)
   *       -> Step 3 (성공 시 selectedAnnotationsJson 설정, 실패 시 null)]
   */
  useEffect(() => {
    const url = selectedFile?.annotations_json_url;
    if (!url) {
      setSelectedAnnotationsJson(null);
      setHasAnnotationChanges(false);
      return;
    }
    let cancelled = false;
    fetch(url)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        if (!cancelled) {
          setSelectedAnnotationsJson(Array.isArray(data) ? data : null);
          setHasAnnotationChanges(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSelectedAnnotationsJson(null);
          setHasAnnotationChanges(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedFile?.annotations_json_url]);

  /**
   * [Flow: Step 1 (주석 변경 이벤트 수신) -> Step 2 (변경 플래그 true)]
   */
  const handleAnnotationChanged = () => {
    setHasAnnotationChanges(true);
  };

  /**
   * [Flow: Step 1 (PdfViewer ref로 exportAnnotations 호출) -> Step 2 (JSON 파싱)
   *       -> Step 3 (상위 onSaveAnnotations 콜백에 전달) -> Step 4 (변경 플래그 false)]
   */
  const handleSaveAnnotations = async () => {
    if (!pdfViewerRef.current || !onSaveAnnotations) return;
    const jsonString = await pdfViewerRef.current.exportAnnotations();
    if (!jsonString) return;
    try {
      const annotations = JSON.parse(jsonString);
      onSaveAnnotations(annotations);
      setHasAnnotationChanges(false);
    } catch {
      // parse error 무시
    }
  };

  const showSaveButton =
    onSaveAnnotations && selectedFile?.source_kind === "annotation" && (selectedAnnotationsJson !== null || hasAnnotationChanges);

  if (files.length === 1) {
    const file = files[0];
    if (file.type === "pdf") {
      return (
        <div className="flex flex-col h-full w-full min-h-0 overflow-hidden">
          {showSaveButton && (
            <div className="flex-shrink-0 px-3 py-2 border-b border-outline-variant bg-white flex justify-end">
              <button
                onClick={handleSaveAnnotations}
                disabled={!hasAnnotationChanges}
                className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                  hasAnnotationChanges
                    ? "bg-primary text-white hover:bg-primary/90"
                    : "bg-surface-container-high text-on-surface-variant cursor-not-allowed"
                }`}
              >
                {t("page:result.saveAnnotations")}
              </button>
            </div>
          )}
          <PdfViewer
            ref={pdfViewerRef}
            url={file.url}
            page={currentPage}
            annotationsJson={selectedAnnotationsJson}
            onAnnotationChanged={handleAnnotationChanged}
          />
        </div>
      );
    }
    return <SingleFilePreview file={file} filename={filename || file.name} annotationsJson={selectedAnnotationsJson} onAnnotationChanged={handleAnnotationChanged} />;
  }

  if (files.length > 1) {
    const selected = files[selectedIndex] || files[0];
    return (
      <div className="flex flex-col h-full overflow-hidden bg-surface-container-low">
        <div className="p-3 border-b border-outline-variant bg-white flex-shrink-0 flex items-center justify-between">
          <h3 className="font-bold text-sm text-on-surface">{t("page:result.sourceFiles")}</h3>
          {showSaveButton && (
            <button
              onClick={handleSaveAnnotations}
              disabled={!hasAnnotationChanges}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                hasAnnotationChanges
                  ? "bg-primary text-white hover:bg-primary/90"
                  : "bg-surface-container-high text-on-surface-variant cursor-not-allowed"
              }`}
            >
              {t("page:result.saveAnnotations")}
            </button>
          )}
        </div>
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
                      <SourceIcon type={f.type} />
                      <span className="truncate">{f.name}</span>
                    </button>
                    {onDeleteFile && (
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
                ))}
              </div>
            </Panel>
            <PanelResizeHandle className="w-2 bg-outline-variant/50 hover:bg-primary transition-colors cursor-col-resize" />
            <Panel className="overflow-hidden min-h-0 flex flex-col">
              {selected.type === "pdf" || selected.type === "docx" || selected.type === "hwp" ? (
                <PdfViewer
                  ref={pdfViewerRef}
                  url={selected.preview_url || selected.url}
                  page={currentPage}
                  annotationsJson={selectedAnnotationsJson}
                  onAnnotationChanged={handleAnnotationChanged}
                />
              ) : (
                <SingleFilePreview file={selected} filename={selected.name} annotationsJson={selectedAnnotationsJson} onAnnotationChanged={handleAnnotationChanged} />
              )}
            </Panel>
          </PanelGroup>
        </div>
      </div>
    );
  }

  if ((sourceType === "pdf" || sourceType === "docx" || sourceType === "hwp") && sourceUrl) {
    return (
      <div className="flex flex-col h-full w-full min-h-0 overflow-hidden">
        {showSaveButton && (
          <div className="flex-shrink-0 px-3 py-2 border-b border-outline-variant bg-white flex justify-end">
            <button
              onClick={handleSaveAnnotations}
              disabled={!hasAnnotationChanges}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                hasAnnotationChanges
                  ? "bg-primary text-white hover:bg-primary/90"
                  : "bg-surface-container-high text-on-surface-variant cursor-not-allowed"
              }`}
            >
              {t("page:result.saveAnnotations")}
            </button>
          </div>
        )}
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
