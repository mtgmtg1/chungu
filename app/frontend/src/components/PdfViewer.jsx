// [Flow: Step 1 (URL과 page prop 수신) -> Step 2 (IntersectionObserver로 패널 가시성 감지) -> Step 3 (보이면 iframe src에 #page fragment 적용) -> Step 4 (브라우저 네이티브 뷰어에게 페이지 탐색을 위임)]
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

/**
 * [Flow: Step 1 (URL과 page prop 수신) -> Step 2 (IntersectionObserver로 패널 가시성 감지) -> Step 3 (보이면 iframe src에 #page fragment 적용) -> Step 4 (브라우저 네이티브 뷰어에게 페이지 탐색을 위임)]
 * @param {string} url - PDF 서명 URL
 * @param {number} page - 초기 페이지 번호
 */
function PdfViewer({ url, page = 1 }) {
  const { t } = useTranslation();
  const containerRef = useRef(null);
  const [currentPage, setCurrentPage] = useState(page);
  const [hasBeenVisible, setHasBeenVisible] = useState(false);

  // 상위에서 page prop이 변경되면 iframe fragment 갱신
  useEffect(() => {
    setCurrentPage(page);
  }, [page]);

  /**
   * [Flow: Step 1 (컨테이너 ref가 있으면 Observer 생성) -> Step 2 (교차 상태 변경 시 가시성 플래그 갱신) -> Step 3 (한 번이라도 보이면 hasBeenVisible 유지)]
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
      <div className="flex-1 flex items-center justify-center text-on-surface-variant text-sm" data-oid="pdf-empty">
        {t("page:errors.loadFailed")}
      </div>
    );
  }

  const iframeSrc = hasBeenVisible ? `${url}#page=${currentPage}` : "";

  return (
    <div ref={containerRef} className="flex-1 flex flex-col overflow-hidden bg-surface-container-low" data-oid="pdf-viewer">
      <div className="flex-1 overflow-hidden min-h-0 relative" data-oid="pdf-iframe-wrap">
        {hasBeenVisible ? (
          <iframe
            src={iframeSrc}
            title={t("page:result.preview")}
            className="w-full h-full border-0"
            data-oid="pdf-iframe"
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-on-surface-variant text-sm" data-oid="pdf-placeholder">
            {t("page:result.preview")}
          </div>
        )}
      </div>
    </div>
  );
}

export default PdfViewer;
