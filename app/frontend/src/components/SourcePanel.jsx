// [Flow: Step 1 (sourceFiles/sourceUrl/sourceType/imageUrls/jobId 수신) -> Step 2 (선택한 pdf/docx/hwp 파일의 썸네일을 서버에서 로드) -> Step 3 (단일/다중 파일에 따라 PdfViewer에 썸네일 전달) -> Step 4 (pdf/docx/hwp가 아니면 기존 미디어/이미지 프리뷰)]
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FileText, ImageIcon, Volume2, Film } from "lucide-react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import PdfViewer from "./PdfViewer.jsx";
import MediaPlayer from "./MediaPlayer.jsx";
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

function SingleFilePreview({ file, filename }) {
  if (file.type === "pdf") return <PdfViewer url={file.url} />;
  if (file.type === "docx" || file.type === "hwp") {
    return file.preview_url ? <PdfViewer url={file.preview_url} /> : null;
  }
  if (file.type === "image") {
    return (
      <div className="flex-1 overflow-auto custom-scrollbar p-4 flex items-center justify-center">
        <img
          src={file.url}
          alt={filename || file.name}
          className="max-w-full max-h-full object-contain shadow-lg rounded border border-outline-variant bg-white"
        />
      </div>
    );
  }
  if (file.type === "audio" || file.type === "video") {
    return <MediaPlayer sourceType={file.type} url={file.url} filename={filename || file.name} />;
  }
  return null;
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
 * [Flow: Step 1 (jobId와 선택된 파일 인덱스 확인) -> Step 2 (pdf/docx/hwp 파일이면 첫 100개 썸네일 로드) -> Step 3 (스크롤/페이지 이동 시 다음 배치 추가 로드) -> Step 4 (썸네일 상태 반환)]
 * @param {string} jobId
 * @param {Array<{type: string, storage_path?: string}>} files
 * @param {number} selectedIndex
 */
function useThumbnails(jobId, files, selectedIndex) {
  const [thumbnails, setThumbnails] = useState([]);
  const [loading, setLoading] = useState(false);
  const [totalPages, setTotalPages] = useState(0);
  const loadedRef = useRef(new Set());
  const loadingRef = useRef(false);
  const fetchIdRef = useRef(0);
  const currentFetchIdRef = useRef(0);
  const BATCH_SIZE = 100;

  const loadBatch = useCallback(
    async (startPage, endPage) => {
      if (!jobId || !files || files.length === 0) return;
      const file = files[selectedIndex] || files[0];
      if (!file || !file.storage_path || !["pdf", "docx", "hwp"].includes(file.type)) return;
      if (loadingRef.current) return;

      const pagesToLoad = [];
      for (let p = startPage; p <= endPage; p++) {
        if (!loadedRef.current.has(p)) pagesToLoad.push(p);
      }
      if (pagesToLoad.length === 0) return;

      const fetchId = ++fetchIdRef.current;
      currentFetchIdRef.current = fetchId;
      loadingRef.current = true;
      setLoading(true);
      try {
        const res = await api.getThumbnails(jobId, selectedIndex, startPage, endPage);
        if (currentFetchIdRef.current !== fetchId) return;
        setTotalPages(res.total_pages || 0);
        for (const p of pagesToLoad) {
          loadedRef.current.add(p);
        }
        setThumbnails((prev) => {
          const map = new Map(prev.map((t) => [t.page, t]));
          for (const t of res.thumbnails || []) {
            map.set(t.page, t);
          }
          return Array.from(map.values()).sort((a, b) => a.page - b.page);
        });
      } catch {
        // 썸네일 로드 실패 시 기존 PDF.js 캔버스 렌더링으로 폴백
      } finally {
        if (currentFetchIdRef.current === fetchId) {
          loadingRef.current = false;
          setLoading(false);
        }
      }
    },
    [jobId, files, selectedIndex]
  );

  useEffect(() => {
    setThumbnails([]);
    loadedRef.current = new Set();
    loadingRef.current = false;
    fetchIdRef.current = 0;
    currentFetchIdRef.current = 0;
    setTotalPages(0);
    loadBatch(1, BATCH_SIZE);
  }, [loadBatch]);

  const loadMore = useCallback(() => {
    const maxLoaded = loadedRef.current.size > 0 ? Math.max(...loadedRef.current) : 0;
    if (maxLoaded < totalPages) {
      loadBatch(maxLoaded + 1, Math.min(totalPages, maxLoaded + BATCH_SIZE));
    }
  }, [totalPages, loadBatch]);

  return { thumbnails, loading, totalPages, loadMore };
}

export default function SourcePanel({
  jobId,
  sourceFiles,
  sourceUrl,
  sourceType,
  imageUrls,
  filename,
  currentPage,
  onPageChange,
  selectedFileIndex,
  onFileSelect,
}) {
  const { t } = useTranslation();
  const files = sourceFiles && sourceFiles.length > 0 ? sourceFiles : [];
  const [internalIndex, setInternalIndex] = useState(0);
  const isControlled = selectedFileIndex !== undefined && onFileSelect;
  const selectedIndex = isControlled ? selectedFileIndex : internalIndex;
  const setSelectedIndex = isControlled ? onFileSelect : setInternalIndex;
  const { thumbnails, loading: thumbnailsLoading, loadMore } = useThumbnails(jobId, files, selectedIndex);

  if (files.length === 1) {
    const file = files[0];
    if (file.type === "pdf") {
      return (
        <PdfViewer
          url={file.url}
          page={currentPage}
          onPageChange={onPageChange}
          thumbnails={thumbnails}
          thumbnailsLoading={thumbnailsLoading}
          onLoadMoreThumbnails={loadMore}
        />
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
                  onPageChange={onPageChange}
                  thumbnails={thumbnails}
                  thumbnailsLoading={thumbnailsLoading}
                  onLoadMoreThumbnails={loadMore}
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
    return <PdfViewer url={sourceUrl} page={currentPage} onPageChange={onPageChange} />;
  }
  if (sourceType === "images" && imageUrls?.length) {
    return <ImageList urls={imageUrls} t={t} />;
  }
  if ((sourceType === "audio" || sourceType === "video") && sourceUrl) {
    return <MediaPlayer sourceType={sourceType} url={sourceUrl} filename={filename} />;
  }
  return (
    <div className="flex-1 flex items-center justify-center text-on-surface-variant text-sm p-4">
      {t("page:components.cannotDisplaySource")}
    </div>
  );
}
