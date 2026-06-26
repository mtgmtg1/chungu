// [Flow: Step 1 (url/page prop 수신) -> Step 2 (PDF.js로 문서 로드) -> Step 3 (현재 페이지를 canvas에 렌더링) -> Step 4 (페이지 변경/줌 UI 노출)]
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import * as pdfjs from "pdfjs-dist";
import pdfjsWorker from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut } from "lucide-react";

pdfjs.GlobalWorkerOptions.workerSrc = pdfjsWorker;

export default function PdfViewer({ url, page = 1, onPageChange }) {
  const { t } = useTranslation();
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const pdfRef = useRef(null);
  const [numPages, setNumPages] = useState(0);
  const [currentPage, setCurrentPage] = useState(page);
  const [scale, setScale] = useState(1.2);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setCurrentPage(page);
  }, [page]);

  useEffect(() => {
    if (!url) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    const task = pdfjs.getDocument(url);
    task.promise
      .then((doc) => {
        if (cancelled) {
          doc.destroy();
          return;
        }
        pdfRef.current = doc;
        setNumPages(doc.numPages);
        setLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(t("page:errors.loadFailed"));
        setLoading(false);
      });
    return () => {
      cancelled = true;
      if (pdfRef.current) {
        pdfRef.current.destroy();
        pdfRef.current = null;
      }
    };
  }, [url]);

  useEffect(() => {
    if (!pdfRef.current || !canvasRef.current) return;
    let renderTask = null;
    const render = async () => {
      const targetPage = Math.min(Math.max(1, currentPage), numPages || 1);
      try {
        const pageObj = await pdfRef.current.getPage(targetPage);
        const canvas = canvasRef.current;
        const ctx = canvas.getContext("2d");
        const viewport = pageObj.getViewport({ scale });
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;
        const task = pageObj.render({ canvasContext: ctx, viewport });
        renderTask = task;
        await task.promise;
      } catch (e) {
        setError(t("page:errors.unknown"));
      }
    };
    render();
    return () => {
      if (renderTask) renderTask.cancel();
    };
  }, [currentPage, numPages, scale]);

  const goToPage = (next) => {
    const target = Math.min(Math.max(1, next), numPages || 1);
    setCurrentPage(target);
    if (onPageChange) onPageChange(target);
  };

  const zoomIn = () => setScale((s) => Math.min(s + 0.2, 3));
  const zoomOut = () => setScale((s) => Math.max(s - 0.2, 0.4));

  if (!url) {
    return (
      <div
        className="flex-1 flex items-center justify-center text-on-surface-variant text-sm"
        data-oid="lcmgb00"
      >
        {t("page:errors.loadFailed")}
      </div>
    );
  }

  if (loading) {
    return (
      <div
        className="flex-1 flex items-center justify-center"
        data-oid="h_9m:e5"
      >
        <div
          className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"
          data-oid="u2zkybb"
        ></div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="flex-1 flex items-center justify-center text-error text-sm p-4"
        data-oid="pr:jjht"
      >
        {error}
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="flex-1 flex flex-col overflow-hidden bg-surface-container-low"
      data-oid="h:os9_v"
    >
      <div
        className="h-12 border-b border-outline-variant bg-white flex items-center justify-between px-3 flex-shrink-0"
        data-oid="cr8oc4f"
      >
        <div className="flex items-center gap-2" data-oid="_aw.:sc">
          <button
            onClick={() => goToPage(currentPage - 1)}
            disabled={currentPage <= 1}
            className="p-1.5 rounded hover:bg-surface-container-high disabled:opacity-40"
            data-oid="y0v2np9"
          >
            <ChevronLeft size={18} data-oid="k48jz_k" />
          </button>
          <span
            className="text-sm text-on-surface min-w-[80px] text-center"
            data-oid="0vuoknk"
          >
            {currentPage} / {numPages}
          </span>
          <button
            onClick={() => goToPage(currentPage + 1)}
            disabled={currentPage >= numPages}
            className="p-1.5 rounded hover:bg-surface-container-high disabled:opacity-40"
            data-oid="nfbbtfo"
          >
            <ChevronRight size={18} data-oid="w3a8_8r" />
          </button>
        </div>
        <div className="flex items-center gap-1" data-oid="aezqe2v">
          <button
            onClick={zoomOut}
            className="p-1.5 rounded hover:bg-surface-container-high"
            data-oid=".f70qfm"
          >
            <ZoomOut size={18} data-oid="ksx_.oj" />
          </button>
          <span
            className="text-xs text-on-surface-variant w-12 text-center"
            data-oid=":-ghkey"
          >
            {Math.round(scale * 100)}%
          </span>
          <button
            onClick={zoomIn}
            className="p-1.5 rounded hover:bg-surface-container-high"
            data-oid="f88-vx8"
          >
            <ZoomIn size={18} data-oid="9r--n_m" />
          </button>
        </div>
      </div>
      <div
        className="flex-1 overflow-auto custom-scrollbar p-4 flex justify-center"
        data-oid="-bnvbo7"
      >
        <canvas
          ref={canvasRef}
          className="shadow-lg rounded border border-outline-variant bg-white"
          data-oid="i156z73"
        />
      </div>
    </div>
  );
}
