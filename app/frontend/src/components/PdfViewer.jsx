// [Flow: Step 1 (URL과 page prop 수신) -> Step 2 (IntersectionObserver로 패널 가시성 감지)
//       -> Step 3 (보이면 FAPDFViewer를 dynamic import로 로드) -> Step 4 (문서 로드 완료 후 page prop에 해당하는 페이지로 이동)
//       -> Step 5 (page prop 변경 시 goToPage로 동기화)]
import { forwardRef, lazy, Suspense, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

/**
 * [Flow: Step 1 (FAPDFViewer와 스타일을 동적 import) -> Step 2 (Suspense로 지연 로딩)]
 * 초기 번들 크기를 줄이기 위해 PDF 뷰어는 실제로 보여질 때만 로드한다.
 */
const FAPDFViewer = lazy(() =>
  import("fresh-air-pdf").then(async (mod) => {
    await import("fresh-air-pdf/style.css");
    return { default: mod.FAPDFViewer };
  })
);

/**
 * [Flow: Step 1 (URL과 page prop 수신) -> Step 2 (IntersectionObserver로 패널 가시성 감지)
 *       -> Step 3 (보이면 FAPDFViewer에 document 전달) -> Step 4 (문서 로드 완료 후 page prop에 해당하는 페이지로 이동)
 *       -> Step 5 (page prop 변경 시 goToPage로 동기화)]
 * @param {string} url - PDF 서명 URL
 * @param {number} page - 초기 페이지 번호
 */
const PdfViewer = forwardRef(function PdfViewer({ url, page = 1, annotationsJson, onAnnotationChanged }, ref) {
  const { t, i18n } = useTranslation();
  const containerRef = useRef(null);
  const viewerRef = useRef(null);
  const [hasBeenVisible, setHasBeenVisible] = useState(false);
  const [isReady, setIsReady] = useState(false);
  const importedAnnotationsJsonRef = useRef(null);

  /**
   * [Flow: Step 1 (상위 ref로 노출할 API 정의) -> Step 2 (exportAnnotations 메서드 제공)]
   */
  useImperativeHandle(ref, () => ({
    exportAnnotations: () => viewerRef.current?.exportAnnotations?.(),
  }));

  // 상위에서 page prop이 변경되면 viewer API로 페이지 이동
  useEffect(() => {
    if (!isReady || !viewerRef.current) return;
    const currentPage = viewerRef.current.getCurrentPage?.();
    if (currentPage !== page) {
      viewerRef.current.goToPage(page);
    }
  }, [page, isReady]);

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

  const locale = (() => {
    const lang = i18n.language || "en";
    if (lang.startsWith("ko")) return "ko";
    if (lang.startsWith("ja")) return "ja";
    return "en";
  })();

  /**
   * [Flow: Step 1 (문서 로드 완료 이벤트 수신) -> Step 2 (isReady true)
   *       -> Step 3 (page prop 위치로 이동) -> Step 4 (annotationsJson이 있으면 import)]
   */
  const handleDocumentLoaded = () => {
    setIsReady(true);
    if (viewerRef.current && page > 1) {
      viewerRef.current.goToPage(page);
    }
    if (
      viewerRef.current &&
      annotationsJson &&
      annotationsJson.length > 0 &&
      JSON.stringify(annotationsJson) !== importedAnnotationsJsonRef.current
    ) {
      viewerRef.current.importAnnotations(JSON.stringify(annotationsJson));
      importedAnnotationsJsonRef.current = JSON.stringify(annotationsJson);
    }
  };

  /**
   * [Flow: Step 1 (주석 변경 이벤트 수신) -> Step 2 (상위 콜백에 전달)]
   */
  const handleAnnotationChanged = (event) => {
    if (onAnnotationChanged) {
      onAnnotationChanged(event);
    }
  };

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
            <FAPDFViewer
              ref={viewerRef}
              document={url}
              onDocumentLoaded={handleDocumentLoaded}
              onAnnotationChanged={handleAnnotationChanged}
              className="w-full h-full"
              config={{
                enableAnnotations: true,
                readOnly: false,
                virtualizePages: true,
                showToolbar: true,
                showThumbnails: true,
                showOutline: true,
                showSearch: true,
                enableTextSelection: true,
                locale,
                theme: "light",
              }}
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
