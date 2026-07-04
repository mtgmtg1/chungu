// [Flow: Step 1 (URL과 page prop 수신) -> Step 2 (iframe src에 #page fragment 적용) -> Step 3 (툴바 페이지 이동 시 src 갱신) -> Step 4 (Markdown 동기화를 위해 onPageChange 호출)]
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronLeft, ChevronRight } from "lucide-react";

/**
 * [Flow: Step 1 (URL과 page prop 수신) -> Step 2 (iframe src에 #page fragment 적용) -> Step 3 (툴바 페이지 이동 시 src 갱신) -> Step 4 (Markdown 동기화를 위해 onPageChange 호출)]
 * @param {string} url - PDF 서명 URL
 * @param {number} page - 초기 페이지 번호
 * @param {function} onPageChange - 페이지 변경 시 상위 컴포넌트에 알리는 콜백
 */
function PdfViewer({ url, page = 1, onPageChange }) {
  const { t } = useTranslation();
  const inputRef = useRef(null);
  const [currentPage, setCurrentPage] = useState(page);

  // 상위에서 page prop이 변경되면 내부 상태 동기화
  useEffect(() => {
    setCurrentPage(page);
  }, [page]);

  /**
   * [Flow: Step 1 (목표 페이지 번호를 1 이상으로 제한) -> Step 2 (내부 상태 갱신) -> Step 3 (상위 콜백 호출)]
   * @param {number} targetPage
   */
  const goToPage = (targetPage) => {
    const next = Math.max(1, targetPage);
    setCurrentPage(next);
    if (onPageChange) onPageChange(next);
  };

  /**
   * [Flow: Step 1 (페이지 입력값 파싱) -> Step 2 (유효한 숫자면 이동)]
   * @param {React.FormEvent<HTMLFormElement>} event
   */
  const handlePageSubmit = (event) => {
    event.preventDefault();
    const value = Number(inputRef.current?.value);
    if (!Number.isNaN(value) && value >= 1) {
      goToPage(value);
    }
  };

  if (!url) {
    return (
      <div className="flex-1 flex items-center justify-center text-on-surface-variant text-sm" data-oid="pdf-empty">
        {t("page:errors.loadFailed")}
      </div>
    );
  }

  const iframeSrc = `${url}#page=${currentPage}`;

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-surface-container-low" data-oid="pdf-viewer">
      <div
        className="h-12 border-b border-outline-variant bg-surface flex items-center justify-between px-4 flex-shrink-0"
        data-oid="pdf-toolbar"
      >
        <div className="flex items-center gap-2" data-oid="pdf-page-nav">
          <button
            onClick={() => goToPage(currentPage - 1)}
            disabled={currentPage <= 1}
            className="p-1.5 rounded hover:bg-surface-container-high disabled:opacity-40"
            data-oid="pdf-prev"
          >
            <ChevronLeft size={18} />
          </button>
          <form onSubmit={handlePageSubmit} className="flex items-center gap-1">
            <input
              ref={inputRef}
              type="number"
              min={1}
              defaultValue={currentPage}
              key={currentPage}
              className="w-16 text-sm text-center border border-outline-variant rounded px-1 py-0.5 bg-surface"
              data-oid="pdf-page-input"
            />
            <span className="text-sm text-on-surface-variant" data-oid="pdf-page-label">
              {t("page:result.page")}
            </span>
          </form>
          <button
            onClick={() => goToPage(currentPage + 1)}
            className="p-1.5 rounded hover:bg-surface-container-high disabled:opacity-40"
            data-oid="pdf-next"
          >
            <ChevronRight size={18} />
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-hidden min-h-0" data-oid="pdf-iframe-wrap">
        <iframe
          src={iframeSrc}
          title={t("page:result.preview")}
          className="w-full h-full border-0"
          data-oid="pdf-iframe"
        />
      </div>
    </div>
  );
}

export default PdfViewer;
