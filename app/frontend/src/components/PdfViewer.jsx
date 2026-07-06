// [Flow: Step 1 (URL, page, annotationsJson 수신) -> Step 2 (IntersectionObserver로 패널 가시성 감지)
//       -> Step 3 (보이면 EmbedPDF PDFViewer를 dynamic import로 로드) -> Step 4 (onReady에서 registry 획득)
//       -> Step 5 (annotation plugin으로 초기 주석 import) -> Step 6 (scroll plugin으로 page prop 위치로 이동)
//       -> Step 7 (page prop/annotationsJson 변경 시 동기화) -> Step 8 (상위 ref로 exportAnnotations 노출)]
import { forwardRef, lazy, Suspense, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

/**
 * [Flow: Step 1 (@embedpdf/react-pdf-viewer의 PDFViewer를 동적 import)
 *       -> Step 2 (Suspense로 지연 로딩)]
 * 초기 번들 크기를 줄이기 위해 PDF 뷰어는 실제로 보여질 때만 로드한다.
 */
const PDFViewer = lazy(() =>
  import("@embedpdf/react-pdf-viewer").then((mod) => ({ default: mod.PDFViewer }))
);

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
    scrollApiRef.current.scrollToPage({ pageNumber: page });
  }, [page, isReady]);

  /**
   * [Flow: Step 1 (annotation plugin이 있으면 importAnnotations Task를 Promise로 변환)
   *       -> Step 2 (toPromise/wait 중 사용 가능한 메서드로 await)]
   */
  const importAnnotationsAsPromise = async (api, items) => {
    const task = api.importAnnotations(items);
    if (!task) return;
    if (typeof task.toPromise === "function") {
      await task.toPromise();
    } else if (typeof task.wait === "function") {
      await new Promise((resolve, reject) => {
        task.wait(resolve, reject);
      });
    }
  };

  /**
   * [Flow: Step 1 (기존 주석을 모두 삭제) -> Step 2 (새 주석 JSON을 importAnnotations로 로드)]
   * importAnnotations가 기존 주석을 업데이트하지 않고 추가만 하므로,
   * 편집 후 재import 시 기존 주석을 먼저 삭제하여 중복/미갱신을 방지한다.
   * annotationsJson은 서버의 단일 진실원(AI + 사용자 주석 모두 포함)이므로
   * 삭제 후 재import해도 데이터 손실이 없다.
   */
  const replaceAnnotations = async (api, items) => {
    try {
      if (typeof api.deleteAllAnnotations === "function") {
        api.deleteAllAnnotations();
      }
    } catch (e) {
      console.warn("[PdfViewer] deleteAllAnnotations failed:", e);
    }
    await importAnnotationsAsPromise(api, items);
  };

  /**
   * [Flow: Step 1 (annotationsJson 변경 감지) -> Step 2 (annotation plugin이 준비되면 기존 주석 삭제 후 재import)
   *       -> Step 3 (중복 import 방지를 위해 마지막 import 문자열 기록)]
   */
  useEffect(() => {
    const api = annotationApiRef.current;
    if (!isReady || !api) return;
    if (!annotationsJson || annotationsJson.length === 0) return;
    const currentJson = JSON.stringify(annotationsJson);
    if (currentJson === importedAnnotationsJsonRef.current) return;
    const runImport = async () => {
      try {
        await replaceAnnotations(api, annotationsJson);
        importedAnnotationsJsonRef.current = currentJson;
      } catch (e) {
        console.error("[PdfViewer] importAnnotations failed:", e);
      }
    };
    runImport();
  }, [annotationsJson, isReady]);

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

  if (!url) {
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
    setIsReady(true);

    if (scrollApiRef.current && page > 1) {
      scrollApiRef.current.scrollToPage({ pageNumber: page });
    }

    const api = annotationApiRef.current;
    if (api) {
      if (annotationsJson && annotationsJson.length > 0) {
        const currentJson = JSON.stringify(annotationsJson);
        if (currentJson !== importedAnnotationsJsonRef.current) {
          importAnnotationsAsPromise(api, annotationsJson)
            .then(() => {
              importedAnnotationsJsonRef.current = currentJson;
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
                src: url,
                documentId: "source-doc",
                i18n: { locale },
              }}
              style={{ width: "100%", height: "100%" }}
              onReady={handleReady}
            />
          </Suspense>
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
