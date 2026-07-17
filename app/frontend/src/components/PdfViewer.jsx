// [Flow: Step 1 (URL, page, annotationsJson 수신) -> Step 2 (데이터 유효성 검증)
//       -> Step 3 (IntersectionObserver로 패널 가시성 감지) -> Step 4 (보이면 EmbedPDF PDFViewer를 dynamic import로 로드)
//       -> Step 5 (ErrorBoundary로 snippet preact crash 전파 차단) -> Step 6 (onReady에서 registry 획득)
//       -> Step 7 (annotation plugin으로 초기 주석 import) -> Step 8 (scroll plugin으로 page prop 위치로 이동)
//       -> Step 9 (page prop/annotationsJson 변경 시 동기화) -> Step 10 (상위 ref로 exportAnnotations 노출)]
import { Component, forwardRef, lazy, Suspense, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertCircle, RotateCw, FileText } from "lucide-react";

/**
 * [Flow: Step 1 (@embedpdf/react-pdf-viewer의 PDFViewer를 동적 import)
 *       -> Step 2 (Suspense로 지연 로딩)]
 * 초기 번들 크기를 줄이기 위해 PDF 뷰어는 실제로 보여질 때만 로드한다.
 */
const PDFViewer = lazy(() =>
  import("@embedpdf/react-pdf-viewer").then((mod) => ({ default: mod.PDFViewer }))
);

/**
 * [Flow: Step 1 (annotationsJson 항목 순회) -> Step 2 (rect/origin/size 등 필수 좌표 필드 존재 검사)
 *       -> Step 3 (잘못된 항목은 제거하고 유효한 항목만 반환)]
 * snippet 내부 preact 컴포넌트가 rect.origin.x 등에 접근할 때 undefined 로 crash 하는 것을 방지한다.
 * EmbedPDF AnnotationTransferItem 형식이 아닌 데이터를 사전에 필터링한다.
 *
 * @param {Array} items - annotationsJson 배열
 * @returns {Array} 유효한 항목만 포함된 배열
 */
function sanitizeAnnotationsJson(items) {
  if (!Array.isArray(items)) return [];
  return items.filter((item) => {
    if (!item || typeof item !== "object") return false;
    // annotation 객체에 rect 가 있으면 origin/size 검증
    const rect = item.rect ?? item.annotation?.rect;
    if (rect) {
      if (rect.origin && typeof rect.origin.x === "number" && rect.size) {
        // 정상 포맷: {origin: {x, y}, size: {width, height}}
      } else if (typeof rect.x === "number" && typeof rect.y === "number" && typeof rect.width === "number") {
        // 하위 호환: {x, y, width, height} 포맷를 {origin, size}로 정규화
        rect.origin = { x: rect.x, y: rect.y };
        rect.size = { width: rect.width, height: rect.height || 0 };
      } else {
        return false;
      }

      // [Flow: 좌표계 혼동 가능성 경고 — origin.y가 일반적인 device-space 범위를 벗어나면 로깅]
      // PDF 뷰어는 rect.origin.y를 페이지 상단에서 아래로 떨어진 device-space 픽셀로 해석한다.
      // AI가 PDF user-space 좌표를 그대로 넘기면 origin.y가 페이지 높이에 가까워 하단에 렌더링된다.
      if (typeof rect.origin.y === "number" && rect.origin.y > 2000) {
        console.warn(
          "[PdfViewer] 의심스러운 annotation rect.origin.y 감지:",
          rect,
          "pageIndex:",
          item.pageIndex ?? item.annotation?.pageIndex,
          "PDF user-space 좌표가 device-space로 잘못 전달되었을 가능성이 있습니다."
        );
      }
    }
    // page 인덱스가 음수면 제거
    if (typeof item.pageIndex === "number" && item.pageIndex < 0) return false;
    return true;
  });
}

/**
 * [Flow: Step 1 (snippet preact 렌더링 crash 감지) -> Step 2 (에러 상태 저장)
 *       -> Step 3 (fallback UI: 에러 메시지 + 재시도 버튼 + iframe PDF 폴백)]
 * @embedpdf/snippet 내부 preact 컴포넌트가 특정 데이터에서 crash 할 때
 * 에러가 React 트리로 전파되어 결과 페이지 전체가 망가지는 것을 차단한다.
 * crash 시 iframe 으로 최소한의 PDF 보기 기능을 제공한다.
 */
class PdfViewerErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error("[PdfViewer] snippet crash (ErrorBoundary):", error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      const { url, t } = this.props;
      return (
        <div className="flex flex-col h-full w-full min-h-0 items-center justify-center gap-3 p-4 bg-surface-container-low" data-oid="pdf-viewer-error">
          <AlertCircle size={32} className="text-error flex-shrink-0" />
          <div className="text-center text-sm text-on-surface-variant max-w-xs">
            {t("page:errors.loadFailed")}
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={this.handleRetry}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-white text-sm hover:opacity-90 transition-opacity"
              data-oid="pdf-viewer-retry">
              <RotateCw size={14} />
              {t("page:retry")}
            </button>
            {url && (
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-outline-variant text-on-surface text-sm hover:bg-surface-container-high transition-colors"
                data-oid="pdf-viewer-open-external">
                <FileText size={14} />
                {t("page:result.openInNewTab")}
              </a>
            )}
          </div>
          {/* iframe 폴백: 주석 편집은 불가하지만 최소한 PDF 내용 확인 가능 */}
          {url && (
            <iframe
              src={url}
              title="PDF fallback"
              className="flex-1 w-full min-h-0 mt-2 rounded border border-outline-variant bg-white"
              data-oid="pdf-viewer-fallback-iframe"
            />
          )}
        </div>
      );
    }
    return this.props.children;
  }
}

/**
 * [Flow: Step 1 (url, page, annotationsJson, onAnnotationChanged 수신)
 *       -> Step 2 (컨테이너 가시성 감시) -> Step 3 (EmbedPDF 뷰어 렌더링)
 *       -> Step 4 (registry에서 annotation/scroll plugin 획득)
 *       -> Step 5 (초기 주석 import 및 페이지 이동) -> Step 6 (상위 ref로 exportAnnotations 제공)]
 *
 * @param {string} url - PDF 서명 URL
 * @param {number} page - 초기 페이지 번호 (1-based)
 * @param {Array<object>} annotationsJson - EmbedPDF AnnotationTransferItem[] 형식의 초기 주석 목록
 * @param {Function} onAnnotationChanged - 주석 변경 이벤트 콜백
 */
const PdfViewer = forwardRef(function PdfViewer({ url, page = 1, annotationsJson, onAnnotationChanged }, ref) {
  const { t, i18n } = useTranslation();
  const containerRef = useRef(null);
  const viewerRef = useRef(null);
  const annotationApiRef = useRef(null);
  const scrollApiRef = useRef(null);
  const unsubscribeEventRef = useRef(null);
  const [hasBeenVisible, setHasBeenVisible] = useState(false);
  const [isReady, setIsReady] = useState(false);
  const importedAnnotationsJsonRef = useRef(null);

  // [Flow: Step 1 (데이터 유효성 정규화) — url 빈 문자열/undefined 처리, page 1 이상 보장, annotationsJson 형식 검증]
  const validUrl = url && typeof url === "string" && url.trim() ? url : null;
  const normalizedPage = Math.max(1, Number(page) || 1);
  const safeAnnotationsJson = sanitizeAnnotationsJson(annotationsJson);

  /**
   * [Flow: Step 1 (상위 ref로 노출할 API 정의) -> Step 2 (annotation plugin 메서드 래핑)]
   * exportAnnotations: 모든 주석을 JSON 문자열로 반환
   * getAnnotations: 모든 주석을 배열로 반환 (TrackedAnnotation[])
   * selectAnnotation: 특정 페이지의 주석을 선택 (해당 페이지로 스크롤 + 하이라이트)
   * updateAnnotation: 기존 주석의 속성을 부분 업데이트 (색상/코멘트/투명도 등)
   * deleteAnnotation: 특정 페이지의 주석을 삭제
   * scrollToPage: 지정 페이지로 스크롤
   */
  useImperativeHandle(ref, () => ({
    exportAnnotations: async () => {
      const api = annotationApiRef.current;
      if (!api) return null;
      try {
        const task = api.exportAnnotations();
        if (!task) return null;
        if (typeof task.toPromise === "function") {
          const items = await task.toPromise();
          return JSON.stringify(items ?? []);
        }
        if (typeof task.wait === "function") {
          const items = await new Promise((resolve, reject) => {
            task.wait((result) => resolve(result ?? []), (error) => reject(error));
          });
          return JSON.stringify(items);
        }
        // 이미 Promise-like이거나 배열인 경우
        const items = await task;
        return JSON.stringify(items ?? []);
      } catch (e) {
        console.error("[PdfViewer] exportAnnotations failed:", e);
        return null;
      }
    },
    getAnnotations: () => {
      const api = annotationApiRef.current;
      if (!api || typeof api.getAnnotations !== "function") return [];
      try {
        return api.getAnnotations() ?? [];
      } catch (e) {
        console.error("[PdfViewer] getAnnotations failed:", e);
        return [];
      }
    },
    selectAnnotation: (pageIndex, annotationId) => {
      const api = annotationApiRef.current;
      const scrollApi = scrollApiRef.current;
      if (!api) return;
      try {
        // 해당 페이지로 스크롤한 뒤 주석 선택
        if (scrollApi && typeof scrollApi.scrollToPage === "function") {
          scrollApi.scrollToPage({ pageNumber: pageIndex + 1 });
        }
        if (typeof api.selectAnnotation === "function") {
          api.selectAnnotation(pageIndex, annotationId);
        }
      } catch (e) {
        console.error("[PdfViewer] selectAnnotation failed:", e);
      }
    },
    updateAnnotation: (pageIndex, annotationId, patch) => {
      const api = annotationApiRef.current;
      if (!api || typeof api.updateAnnotation !== "function") return;
      try {
        api.updateAnnotation(pageIndex, annotationId, patch);
      } catch (e) {
        console.error("[PdfViewer] updateAnnotation failed:", e);
      }
    },
    deleteAnnotation: (pageIndex, annotationId) => {
      const api = annotationApiRef.current;
      if (!api || typeof api.deleteAnnotation !== "function") return;
      try {
        api.deleteAnnotation(pageIndex, annotationId);
      } catch (e) {
        console.error("[PdfViewer] deleteAnnotation failed:", e);
      }
    },
    scrollToPage: (pageNumber) => {
      const scrollApi = scrollApiRef.current;
      if (!scrollApi || typeof scrollApi.scrollToPage !== "function") return;
      try {
        scrollApi.scrollToPage({ pageNumber });
      } catch (e) {
        console.error("[PdfViewer] scrollToPage failed:", e);
      }
    },
  }));

  /**
   * [Flow: Step 1 (page prop 변경 감지) -> Step 2 (scroll plugin이 준비되면 scrollToPage 호출)]
   */
  useEffect(() => {
    if (!isReady || !scrollApiRef.current) return;
    scrollApiRef.current.scrollToPage({ pageNumber: normalizedPage });
  }, [normalizedPage, isReady]);

  /**
   * [Flow: Step 1 (api.importAnnotations(items) 호출) -> Step 2 (반환값 종류 판별)
   *       -> Step 3 (Task/Promise면 await, void면 즉시 완료)]
   */
  const importAnnotationsAsPromise = async (api, items) => {
    const task = api.importAnnotations(items);
    console.log("[PdfViewer] importAnnotations returned:", typeof task, task ? Object.keys(task) : null);
    if (!task) return;
    if (typeof task.toPromise === "function") {
      await task.toPromise();
    } else if (typeof task.wait === "function") {
      await new Promise((resolve, reject) => {
        task.wait(resolve, reject);
      });
    } else if (typeof task.then === "function") {
      await task;
    }
  };

  /**
   * [Flow: Step 1 (annotationsJson 변경 감지) -> Step 2 (annotation plugin이 준비되면 importAnnotations 호출)
   *       -> Step 3 (중복 import 방지를 위해 마지막 import 문자열 기록)]
   */
  useEffect(() => {
    const api = annotationApiRef.current;
    console.log("[PdfViewer] annotation import effect:", { isReady, hasApi: !!api, count: safeAnnotationsJson?.length });
    if (!isReady || !api) return;
    if (!safeAnnotationsJson || safeAnnotationsJson.length === 0) return;
    const currentJson = JSON.stringify(safeAnnotationsJson);
    if (currentJson === importedAnnotationsJsonRef.current) {
      console.log("[PdfViewer] annotations already imported, skipping");
      return;
    }
    const runImport = async () => {
      try {
        console.log("[PdfViewer] importing annotations (effect):", safeAnnotationsJson.length);
        await importAnnotationsAsPromise(api, safeAnnotationsJson);
        importedAnnotationsJsonRef.current = currentJson;
        console.log("[PdfViewer] annotations imported (effect)");
      } catch (e) {
        console.error("[PdfViewer] importAnnotations failed (effect):", e);
      }
    };
    runImport();
  }, [safeAnnotationsJson, isReady]);

  /**
   * [Flow: Step 1 (컨테이너 ref가 있으면 Observer 생성) -> Step 2 (교차 상태 변경 시 가시성 플래그 갱신)
   *       -> Step 3 (한 번이라도 보이면 hasBeenVisible 유지)]
   */
  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setHasBeenVisible(true);
        }
      },
      { threshold: 0.1, rootMargin: "100px" }
    );
    observer.observe(element);

    return () => {
      observer.disconnect();
    };
  }, []);

  if (!validUrl) {
    return (
      <div className="flex-1 flex items-center justify-center h-full w-full min-h-0 text-on-surface-variant text-sm" data-oid="pdf-empty">
        {t("page:errors.loadFailed")}
      </div>
    );
  }

  /**
   * [Flow: Step 1 (EmbedPDF 뷰어 준비 완료) -> Step 2 (registry에서 annotation/scroll plugin 획득)
   *       -> Step 3 (isReady true 설정) -> Step 4 (page 위치로 이동) -> Step 5 (주석 import)
   *       -> Step 6 (주석 변경 이벤트 구독)]
   */
  const handleReady = (registry) => {
    annotationApiRef.current = registry?.getPlugin("annotation")?.provides() ?? null;
    scrollApiRef.current = registry?.getPlugin("scroll")?.provides() ?? null;
    console.log("[PdfViewer] onReady:", {
      hasAnnotationApi: !!annotationApiRef.current,
      hasScrollApi: !!scrollApiRef.current,
      annotationCount: safeAnnotationsJson?.length,
    });
    setIsReady(true);

    if (scrollApiRef.current && normalizedPage > 1) {
      scrollApiRef.current.scrollToPage({ pageNumber: normalizedPage });
    }

    const api = annotationApiRef.current;
    if (api) {
      if (safeAnnotationsJson && safeAnnotationsJson.length > 0) {
        const currentJson = JSON.stringify(safeAnnotationsJson);
        if (currentJson !== importedAnnotationsJsonRef.current) {
          console.log("[PdfViewer] importing annotations (onReady):", safeAnnotationsJson.length);
          importAnnotationsAsPromise(api, safeAnnotationsJson)
            .then(() => {
              importedAnnotationsJsonRef.current = currentJson;
              console.log("[PdfViewer] annotations imported (onReady)");
            })
            .catch((e) => {
              console.error("[PdfViewer] initial importAnnotations failed:", e);
            });
        }
      }
      if (api.onAnnotationEvent) {
        unsubscribeEventRef.current = api.onAnnotationEvent((event) => {
          if (onAnnotationChanged) {
            onAnnotationChanged(event);
          }
        });
      }
    } else {
      console.warn("[PdfViewer] annotation plugin API not available in registry");
    }
  };

  /**
   * [Flow: Step 1 (언어에 따라 EmbedPDF locale 선택) -> Step 2 (ko/ja/en 중 하나 반환)]
   */
  const locale = (() => {
    const lang = i18n.language || "en";
    if (lang.startsWith("ko")) return "ko";
    if (lang.startsWith("ja")) return "ja";
    return "en";
  })();

  return (
    <div ref={containerRef} className="flex-1 flex flex-col h-full w-full min-h-0 overflow-hidden bg-surface-container-low" data-oid="pdf-viewer">
      <div className="flex-1 overflow-hidden min-h-0 relative" data-oid="pdf-viewer-wrap">
        {hasBeenVisible ? (
          <PdfViewerErrorBoundary url={validUrl} t={t}>
            <Suspense
              fallback={(
                <div className="absolute inset-0 flex items-center justify-center text-on-surface-variant text-sm" data-oid="pdf-loading">
                  {t("page:result.preview")}
                </div>
              )}
            >
              <PDFViewer
                ref={viewerRef}
                config={{
                  src: validUrl,
                  documentId: "source-doc",
                  i18n: { locale },
                }}
                style={{ width: "100%", height: "100%" }}
                onReady={handleReady}
              />
            </Suspense>
          </PdfViewerErrorBoundary>
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-on-surface-variant text-sm" data-oid="pdf-placeholder">
            {t("page:result.preview")}
          </div>
        )}
      </div>
    </div>
  );
});

export default PdfViewer;
