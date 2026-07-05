// [Flow: Step 1 (sourceFiles/sourceUrl/sourceType/imageUrls/jobId 수신) -> Step 2 (단일/다중 파일에 따라 PdfViewer에 URL 전달) -> Step 3 (pdf/docx/hwp가 아니면 기존 미디어/이미지 프리뷰)]
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { FileText, ImageIcon, Volume2, Film } from "lucide-react";
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

function SingleFilePreview({ file, filename }) {
  // [Flow: Step 1 (파일 타입에 따라 콘텐츠 선택) -> Step 2 (항상 동일한 높이 컨테이너로 감싸서 반환)]
  let content = null;
  if (file.type === "pdf") {
    content = <PdfViewer url={file.url} />;
  } else if (file.type === "docx" || file.type === "hwp") {
    content = file.preview_url ? <PdfViewer url={file.preview_url} /> : null;
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
}) {
  const { t } = useTranslation();
  const files = sourceFiles && sourceFiles.length > 0 ? sourceFiles : [];
  const [internalIndex, setInternalIndex] = useState(0);
  const isControlled = selectedFileIndex !== undefined && onFileSelect;
  const selectedIndex = isControlled ? selectedFileIndex : internalIndex;
  const setSelectedIndex = isControlled ? onFileSelect : setInternalIndex;

  if (files.length === 1) {
    const file = files[0];
    if (file.type === "pdf") {
      return (
        <div className="flex flex-col h-full w-full min-h-0 overflow-hidden">
          <PdfViewer
            url={file.url}
            page={currentPage}
          />
        </div>
      );
    }
    return <SingleFilePreview file={file} filename={filename || file.name} />;
  }

  if (files.length > 1) {
    const selected = files[selectedIndex] || files[0];
    return (
      <div className="flex flex-col h-full overflow-hidden bg-surface-container-low">
        <div className="p-3 border-b border-outline-variant bg-white flex-shrink-0">
          <h3 className="font-bold text-sm text-on-surface">{t("page:result.sourceFiles")}</h3>
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
                  <button
                    key={idx}
                    onClick={() => setSelectedIndex(idx)}
                    className={`w-full flex items-center gap-2 text-left p-2 rounded text-xs transition-colors ${
                      selectedIndex === idx
                        ? "bg-primary-container/20 text-primary font-bold"
                        : "text-on-surface hover:bg-surface-container-high"
                    }`}
                  >
                    <SourceIcon type={f.type} />
                    <span className="truncate">{f.name}</span>
                  </button>
                ))}
              </div>
            </Panel>
            <PanelResizeHandle className="w-2 bg-outline-variant/50 hover:bg-primary transition-colors cursor-col-resize" />
            <Panel className="overflow-hidden min-h-0 flex flex-col">
              {selected.type === "pdf" || selected.type === "docx" || selected.type === "hwp" ? (
                <PdfViewer
                  url={selected.preview_url || selected.url}
                  page={currentPage}
                />
              ) : (
                <SingleFilePreview file={selected} filename={selected.name} />
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
        <PdfViewer url={sourceUrl} page={currentPage} />
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
