// [Flow: Step 1 (PDF.js worker 설정) -> Step 2 (부분 로드로 PDFDocument 열기) -> Step 3 (썸네일/페이지 캐싱) -> Step 4 (현재 페이지 렌더링) -> Step 5 (페이지 변경/줌 동기화)]
import { useCallback, useEffect, useRef, useState, memo } from "react";
import { useTranslation } from "react-i18next";
import * as pdfjsLib from "pdfjs-dist";
import pdfjsWorker from "pdfjs-dist/build/pdf.worker.mjs?url";
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut } from "lucide-react";

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfjsWorker;

const ZOOM_STEP = 1.2;
const MAX_SCALE = 3;
const MIN_SCALE = 0.4;
const THUMBNAIL_SCALE = 0.2;
const THUMBNAIL_THRESHOLD = 50;
const RESIZE_DEBOUNCE_MS = 100;

/**
 * [Flow: Step 1 (PDF URL 변경 감지) -> Step 2 (부분 로드로 PDFDocument 열기) -> Step 3 (총 페이지 수 저장) -> Step 4 (캐시 초기화)]
 * @param {string} url - PDF 서명 URL
 * @param {number} page - 초기 페이지 번호
 * @param {function} onPageChange - 페이지 변경 시 상위 컴포넌트에 알리는 콜백
 */
function PdfViewer({ url, page = 1, onPageChange }) {
  const { t } = useTranslation();
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const renderTaskRef = useRef(null);
  const pdfRef = useRef(null);
  const pageCacheRef = useRef(new Map());
  const fitScaleRef = useRef(1);
  const containerSizeRef = useRef({ width: 0, height: 0 });
  const resizeTimerRef = useRef(null);
  const thumbnailObserverRef = useRef(null);

  const [currentPage, setCurrentPage] = useState(page);
  const [totalPages, setTotalPages] = useState(0);
  const [fitScale, setFitScale] = useState(1);
  const [zoomLevel, setZoomLevel] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showThumbnails, setShowThumbnails] = useState(false);
  const [thumbnailPages, setThumbnailPages] = useState([]);
  const [visibleThumbnails, setVisibleThumbnails] = useState(new Set());

  const scale = Math.min(Math.max(fitScale * zoomLevel, MIN_SCALE), MAX_SCALE);

  // 상위에서 page prop이 변경되면 내부 상태 동기화
  useEffect(() => {
    setCurrentPage(page);
  }, [page]);

  /**
   * [Flow: Step 1 (URL 변경 시) -> Step 2 (이전 PDF 정리) -> Step 3 (disableAutoFetch로 문서 열기) -> Step 4 (총 페이지 수 저장) -> Step 5 (캐시 초기화)]
   */
  useEffect(() => {
    if (!url) return;
    let canceled = false;
    setLoading(true);
    setError("");
    pageCacheRef.current.clear();
    setThumbnailPages([]);
    setVisibleThumbnails(new Set());

    // disableAutoFetch: 전체 PDF 바이트를 미리 다운로드하지 않음
    // disableStream: range request 기반 페이지 단위 로드 유도
    const loadingTask = pdfjsLib.getDocument({
      url,
      disableAutoFetch: true,
      disableStream: true,
    });

    loadingTask.promise
      .then((doc) => {
        if (canceled) return;
        pdfRef.current = doc;
        setTotalPages(doc.numPages);
        setLoading(false);
        if (doc.numPages >= THUMBNAIL_THRESHOLD) {
          setShowThumbnails(true);
          setThumbnailPages(Array.from({ length: doc.numPages }, (_, i) => i + 1));
        }
      })
      .catch((err) => {
        if (canceled) return;
        setError(err.message || t("page:errors.loadFailed"));
        setLoading(false);
      });

    return () => {
      canceled = true;
      loadingTask.destroy?.();
      pdfRef.current = null;
      pageCacheRef.current.clear();
      if (resizeTimerRef.current) {
        clearTimeout(resizeTimerRef.current);
      }
      if (thumbnailObserverRef.current) {
        thumbnailObserverRef.current.disconnect();
      }
    };
  }, [url, t]);

  /**
   * [Flow: Step 1 (페이지 번호로 캐시 조회) -> Step 2 (미스 시 pdf.getPage 호출) -> Step 3 (캐시 저장) -> Step 4 (PDFPageProxy 반환)]
   * @param {number} pageNum
   * @returns {Promise<PDFPageProxy>}
   */
  const getPdfPage = useCallback(async (pageNum) => {
    const cache = pageCacheRef.current;
    if (cache.has(pageNum)) {
      return cache.get(pageNum);
    }
    const pdf = pdfRef.current;
    if (!pdf) throw new Error("PDF not loaded");
    const page = await pdf.getPage(pageNum);
    cache.set(pageNum, page);
    return page;
  }, []);

  /**
   * [Flow: Step 1 (컨테이너 크기 측정) -> Step 2 (이전 크기와 비교) -> Step 3 (변화 있을 때만 fitScale 계산) -> Step 4 (페이지 캐시 활용)]
   */
  const measureFitScale = useCallback(async () => {
    const pdf = pdfRef.current;
    const container = containerRef.current;
    if (!pdf || !container) return;

    const rect = container.getBoundingClientRect();
    const newSize = {
      width: Math.floor(rect.width),
      height: Math.floor(rect.height),
    };
    const prev = containerSizeRef.current;
    if (newSize.width === prev.width && newSize.height === prev.height) return;
    containerSizeRef.current = newSize;

    try {
      const pdfPage = await getPdfPage(currentPage);
      const baseViewport = pdfPage.getViewport({ scale: 1 });
      const padding = 32;
      const availableWidth = Math.max(1, newSize.width - padding);
      const availableHeight = Math.max(1, newSize.height - padding);
      const fit = Math.min(
        availableWidth / baseViewport.width,
        availableHeight / baseViewport.height
      );
      const nextFit = Math.max(MIN_SCALE, fit);
      fitScaleRef.current = nextFit;
      setFitScale(nextFit);
    } catch {
      // 측정 실패 시 무시
    }
  }, [currentPage, getPdfPage]);

  /**
   * [Flow: Step 1 (현재 페이지 ±1 페이지를 비동기로 요청) -> Step 2 (캐시에 저장) -> Step 3 (실패 시 무시)]
   */
  const prefetchAdjacentPages = useCallback(() => {
    const pdf = pdfRef.current;
    if (!pdf) return;
    const targets = [currentPage - 1, currentPage + 1].filter(
      (p) => p >= 1 && p <= totalPages
    );
    targets.forEach((p) => {
      if (!pageCacheRef.current.has(p)) {
        getPdfPage(p).catch(() => {});
      }
    });
  }, [currentPage, totalPages, getPdfPage]);

  /**
   * [Flow: Step 1 (PDF 로드 또는 현재 페이지 변경) -> Step 2 (디바운스된 ResizeObserver 등록) -> Step 3 (fitScale 측정) -> Step 4 (주변 페이지 프리페치)]
   */
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const observer = new ResizeObserver(() => {
      if (resizeTimerRef.current) clearTimeout(resizeTimerRef.current);
      resizeTimerRef.current = setTimeout(() => {
        measureFitScale();
      }, RESIZE_DEBOUNCE_MS);
    });
    observer.observe(container);

    measureFitScale();
    prefetchAdjacentPages();

    return () => {
      observer.disconnect();
      if (resizeTimerRef.current) clearTimeout(resizeTimerRef.current);
    };
  }, [measureFitScale, prefetchAdjacentPages]);

  /**
   * [Flow: Step 1 (현재 페이지/scale 변경) -> Step 2 (이전 렌더링 작업 취소) -> Step 3 (캐시된 페이지 가져오기) -> Step 4 (캔버스 크기 설정) -> Step 5 (렌더링) -> Step 6 (페이지 cleanup)]
   */
  useEffect(() => {
    const pdf = pdfRef.current;
    if (!pdf || !canvasRef.current) return;
    if (currentPage < 1 || currentPage > totalPages) return;

    let active = true;
    const render = async () => {
      const canvas = canvasRef.current;
      const ctx = canvas.getContext("2d");
      if (renderTaskRef.current) {
        renderTaskRef.current.cancel();
      }
      const pdfPage = await getPdfPage(currentPage);
      const viewport = pdfPage.getViewport({ scale });
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.floor(viewport.width * dpr);
      canvas.height = Math.floor(viewport.height * dpr);
      canvas.style.width = `${Math.floor(viewport.width)}px`;
      canvas.style.height = `${Math.floor(viewport.height)}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      renderTaskRef.current = pdfPage.render({ canvasContext: ctx, viewport });
      try {
        await renderTaskRef.current.promise;
      } catch (err) {
        if (err.name !== "RenderingCancelledException") {
          throw err;
        }
      }
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
  }, [currentPage, scale, totalPages, t, getPdfPage]);

  /**
   * [Flow: Step 1 (썸네일 컨테이너가 생기면) -> Step 2 (IntersectionObserver 등록) -> Step 3 (보이는 썸네일 번호만 상태로 저장)]
   */
  useEffect(() => {
    if (!showThumbnails || thumbnailPages.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        setVisibleThumbnails((prev) => {
          const next = new Set(prev);
          entries.forEach((entry) => {
            const pageNum = Number(entry.target.dataset.page);
            if (entry.isIntersecting) {
              next.add(pageNum);
            } else {
              next.delete(pageNum);
            }
          });
          return next;
        });
      },
      { root: null, rootMargin: "100px", threshold: 0.1 }
    );
    thumbnailObserverRef.current = observer;

    const items = document.querySelectorAll("[data-thumbnail-item]");
    items.forEach((item) => observer.observe(item));

    return () => observer.disconnect();
  }, [showThumbnails, thumbnailPages.length]);

  /**
   * [Flow: Step 1 (페이지 번호 유효 범위로 제한) -> Step 2 (내부 상태 갱신) -> Step 3 (상위 콜백 호출)]
   * @param {number} next
   */
  const goToPage = (next) => {
    const target = Math.min(Math.max(1, next), totalPages || 1);
    setCurrentPage(target);
    if (onPageChange) onPageChange(target);
  };

  const zoomIn = () =>
    setZoomLevel((z) =>
      Math.min(z * ZOOM_STEP, MAX_SCALE / Math.max(fitScaleRef.current, 0.01))
    );
  const zoomOut = () =>
    setZoomLevel((z) =>
      Math.max(z / ZOOM_STEP, MIN_SCALE / Math.max(fitScaleRef.current, 0.01))
    );

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
      <div
        className="h-12 border-b border-outline-variant bg-surface flex items-center justify-between px-4 flex-shrink-0"
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
        <div className="flex items-center gap-2" data-oid="pdf-toolbar-extras">
          {totalPages >= THUMBNAIL_THRESHOLD && (
            <button
              onClick={() => setShowThumbnails((v) => !v)}
              className={`text-xs px-2 py-1 rounded border border-outline-variant ${
                showThumbnails ? "bg-primary text-white" : "text-on-surface hover:bg-surface-container-high"
              }`}
              data-oid="pdf-thumb-toggle"
            >
              {t("page:result.thumbnails")}
            </button>
          )}
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
      <div className="flex-1 flex overflow-hidden min-h-0" data-oid="pdf-main-area">
        {showThumbnails && (
          <ThumbnailPanel
            currentPage={currentPage}
            totalPages={totalPages}
            thumbnailPages={thumbnailPages}
            visibleThumbnails={visibleThumbnails}
            getPdfPage={getPdfPage}
            onPageClick={goToPage}
          />
        )}
        <div
          ref={containerRef}
          className="flex-1 overflow-auto custom-scrollbar flex items-start justify-center p-4"
          data-oid="pdf-canvas-wrap"
        >
          {loading ? (
            <span className="text-sm text-on-surface-variant" data-oid="pdf-loading">{t("page:result.saving")}</span>
          ) : (
            <canvas
              ref={canvasRef}
              className="shadow-lg rounded border border-outline-variant bg-white"
              data-oid="pdf-canvas"
            />
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * [Flow: Step 1 (보이는 썸네일 번호 확인) -> Step 2 (해당 페이지 canvas 렌더링) -> Step 3 (클릭 시 페이지 이동)]
 * @param {object} props
 * @param {number} props.currentPage
 * @param {number} props.totalPages
 * @param {number[]} props.thumbnailPages
 * @param {Set<number>} props.visibleThumbnails
 * @param {function} props.getPdfPage
 * @param {function} props.onPageClick
 */
function ThumbnailPanel({
  currentPage,
  totalPages,
  thumbnailPages,
  visibleThumbnails,
  getPdfPage,
  onPageClick,
}) {
  const { t } = useTranslation();
  const canvasRefs = useRef({});
  const renderedRef = useRef(new Set());
  const panelRef = useRef(null);

  const itemHeight = 120;
  const totalHeight = thumbnailPages.length * itemHeight;

  const renderThumbnail = useCallback(
    async (pageNum, canvas) => {
      if (renderedRef.current.has(pageNum)) return;
      renderedRef.current.add(pageNum);
      try {
        const page = await getPdfPage(pageNum);
        const viewport = page.getViewport({ scale: THUMBNAIL_SCALE });
        const dpr = window.devicePixelRatio || 1;
        canvas.width = Math.floor(viewport.width * dpr);
        canvas.height = Math.floor(viewport.height * dpr);
        canvas.style.width = `${Math.floor(viewport.width)}px`;
        canvas.style.height = `${Math.floor(viewport.height)}px`;
        const ctx = canvas.getContext("2d");
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        await page.render({ canvasContext: ctx, viewport }).promise;
      } catch {
        renderedRef.current.delete(pageNum);
      }
    },
    [getPdfPage]
  );

  useEffect(() => {
    visibleThumbnails.forEach((pageNum) => {
      const canvas = canvasRefs.current[pageNum];
      if (canvas) renderThumbnail(pageNum, canvas);
    });
  }, [visibleThumbnails, renderThumbnail]);

  // 현재 페이지 썸네일이 스크롤 영역 중앙에 보이도록 이동
  useEffect(() => {
    const scrollContainer = panelRef.current?.querySelector("[data-oid='pdf-thumbnail-scroll']");
    const activeItem = scrollContainer?.querySelector(`[data-page="${currentPage}"]`);
    if (scrollContainer && activeItem) {
      activeItem.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [currentPage]);

  return (
    <div
      ref={panelRef}
      className="w-36 flex-shrink-0 border-r border-outline-variant bg-surface flex flex-col overflow-hidden"
      data-oid="pdf-thumbnail-panel"
    >
      <div className="p-2 border-b border-outline-variant text-xs text-on-surface-variant text-center flex-shrink-0">
        {t("page:result.thumbnails")} ({totalPages})
      </div>
      <div
        className="flex-1 overflow-y-auto custom-scrollbar relative"
        data-oid="pdf-thumbnail-scroll"
      >
        <div style={{ height: totalHeight }} className="relative w-full">
          {thumbnailPages.map((pageNum) => {
            const top = (pageNum - 1) * itemHeight;
            const isVisible = visibleThumbnails.has(pageNum);
            const isActive = pageNum === currentPage;
            return (
              <div
                key={pageNum}
                data-thumbnail-item
                data-page={pageNum}
                onClick={() => onPageClick(pageNum)}
                className={`absolute left-0 right-0 px-2 py-1 cursor-pointer border-b border-outline-variant/50 flex flex-col items-center justify-center ${
                  isActive ? "bg-primary-container/30" : "hover:bg-surface-container-high"
                }`}
                style={{ top, height: itemHeight }}
              >
                <span className={`text-[10px] mb-1 ${isActive ? "text-primary font-bold" : "text-on-surface-variant"}`}>
                  {pageNum}
                </span>
                {isVisible ? (
                  <canvas
                    ref={(el) => {
                      canvasRefs.current[pageNum] = el;
                    }}
                    className="rounded border border-outline-variant bg-white max-w-full max-h-[80px]"
                  />
                ) : (
                  <div className="w-16 h-20 bg-surface-container-high rounded border border-outline-variant/50" />
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default memo(PdfViewer);