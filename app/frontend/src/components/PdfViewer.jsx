// [Flow: Step 1 (PDF.js worker 설정) -> Step 2 (url로 PDFDocument 로드) -> Step 3 (현재 페이지만 canvas에 렌더링) -> Step 4 (페이지 변경/줌 동기화)]
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import * as pdfjsLib from "pdfjs-dist";
import pdfjsWorker from "pdfjs-dist/build/pdf.worker.mjs?url";
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut } from "lucide-react";

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfjsWorker;

export default function PdfViewer({ url, page = 1, onPageChange }) {
  const { t } = useTranslation();
  const canvasRef = useRef(null);
  const renderTaskRef = useRef(null);
  const [pdf, setPdf] = useState(null);
  const [currentPage, setCurrentPage] = useState(page);
  const [totalPages, setTotalPages] = useState(0);
  const [scale, setScale] = useState(1.2);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setCurrentPage(page);
  }, [page]);

  useEffect(() => {
    if (!url) return;
    let canceled = false;
    setLoading(true);
    setError("");
    const loadingTask = pdfjsLib.getDocument(url);
    loadingTask.promise
      .then((doc) => {
        if (canceled) return;
        setPdf(doc);
        setTotalPages(doc.numPages);
        setLoading(false);
      })
      .catch((err) => {
        if (canceled) return;
        setError(err.message || t("page:errors.loadFailed"));
        setLoading(false);
      });
    return () => {
      canceled = true;
      loadingTask.destroy?.();
    };
  }, [url, t]);

  useEffect(() => {
    if (!pdf || !canvasRef.current) return;
    if (currentPage < 1 || currentPage > totalPages) return;

    let active = true;
    const render = async () => {
      const canvas = canvasRef.current;
      const ctx = canvas.getContext("2d");
      if (renderTaskRef.current) {
        renderTaskRef.current.cancel();
      }
      const pdfPage = await pdf.getPage(currentPage);
      const viewport = pdfPage.getViewport({ scale });
      const dpr = window.devicePixelRatio || 1;
      canvas.width = viewport.width * dpr;
      canvas.height = viewport.height * dpr;
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      renderTaskRef.current = pdfPage.render({ canvasContext: ctx, viewport });
      try {
        await renderTaskRef.current.promise;
      } catch (err) {
        if (err.name !== "RenderingCancelledException") {
          throw err;
        }
      }
      pdfPage.cleanup();
    };
    render().catch((err) => {
      if (!active) return;
      setError(err.message || t("page:errors.loadFailed"));
    });
    return () => {
      active = false;
      if (renderTaskRef.current) {
        renderTaskRef.current.cancel();
      }
    };
  }, [pdf, currentPage, scale, totalPages, t]);

  const goToPage = (next) => {
    const target = Math.min(Math.max(1, next), totalPages || 1);
    setCurrentPage(target);
    if (onPageChange) onPageChange(target);
  };

  const zoomIn = () => setScale((s) => Math.min(s + 0.2, 3));
  const zoomOut = () => setScale((s) => Math.max(s - 0.2, 0.4));

  if (!url) {
    return (
      <div className="flex-1 flex items-center justify-center text-on-surface-variant text-sm" data-oid="2i1n0p3">
        {t("page:errors.loadFailed")}
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center text-on-surface-variant text-sm p-4" data-oid="pdf-error">
        {error}
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-surface-container-low" data-oid="pdfjs-viewer">
      <div className="flex-1 overflow-auto custom-scrollbar flex items-center justify-center p-4" data-oid="pdf-canvas-wrap">
        {loading ? (
          <span className="text-sm text-on-surface-variant" data-oid="pdf-loading">{t("page:result.saving")}</span>
        ) : (
          <canvas ref={canvasRef} className="shadow-lg rounded border border-outline-variant bg-white" data-oid="pdf-canvas" />
        )}
      </div>
      <div
        className="h-12 border-t border-outline-variant bg-surface flex items-center justify-between px-4 flex-shrink-0"
        data-oid="pdf-toolbar"
      >
        <div className="flex items-center gap-2" data-oid="pdf-page-nav">
          <button
            onClick={() => goToPage(currentPage - 1)}
            disabled={currentPage <= 1 || loading}
            className="p-1.5 rounded hover:bg-surface-container-high disabled:opacity-40"
            data-oid="pdf-prev"
          >
            <ChevronLeft size={18} />
          </button>
          <span className="text-sm text-on-surface min-w-[80px] text-center" data-oid="pdf-page-label">
            {currentPage} / {totalPages}
          </span>
          <button
            onClick={() => goToPage(currentPage + 1)}
            disabled={currentPage >= totalPages || loading}
            className="p-1.5 rounded hover:bg-surface-container-high disabled:opacity-40"
            data-oid="pdf-next"
          >
            <ChevronRight size={18} />
          </button>
        </div>
        <div className="flex items-center gap-1" data-oid="pdf-zoom">
          <button
            onClick={zoomOut}
            disabled={loading}
            className="p-1.5 rounded hover:bg-surface-container-high disabled:opacity-40"
            data-oid="pdf-zoom-out"
          >
            <ZoomOut size={18} />
          </button>
          <span className="text-xs text-on-surface-variant w-12 text-center" data-oid="pdf-zoom-label">
            {Math.round(scale * 100)}%
          </span>
          <button
            onClick={zoomIn}
            disabled={loading}
            className="p-1.5 rounded hover:bg-surface-container-high disabled:opacity-40"
            data-oid="pdf-zoom-in"
          >
            <ZoomIn size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}