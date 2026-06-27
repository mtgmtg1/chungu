// [Flow: Step 1 (url/page prop 수신) -> Step 2 (iframe으로 브라우저 PDF 뷰어 로드) -> Step 3 (페이지/줌 프래그먼트 적용) -> Step 4 (페이지 변경/줌 UI 노출)]
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut } from "lucide-react";

export default function PdfViewer({ url, page = 1, onPageChange }) {
  const { t } = useTranslation();
  const [currentPage, setCurrentPage] = useState(page);
  const [scale, setScale] = useState(1.2);

  useEffect(() => {
    setCurrentPage(page);
  }, [page]);

  const goToPage = (next) => {
    const target = Math.min(Math.max(1, next), 99999);
    setCurrentPage(target);
    if (onPageChange) onPageChange(target);
  };

  const zoomIn = () => setScale((s) => Math.min(s + 0.2, 3));
  const zoomOut = () => setScale((s) => Math.max(s - 0.2, 0.4));

  if (!url) {
    return (
      <div
        className="flex-1 flex items-center justify-center text-on-surface-variant text-sm"
        data-oid="2i1n0p3">

        {t("page:errors.loadFailed")}
      </div>);

  }

  const iframeUrl = `${url}#page=${currentPage}&zoom=${Math.round(scale * 100)}`;

  return (
    <div
      className="flex-1 flex flex-col overflow-hidden bg-surface-container-low"
      data-oid="9_o43iw">

      <div
        className="h-12 border-b border-outline-variant bg-white flex items-center justify-between px-3 flex-shrink-0"
        data-oid="x:l5d4z">

        <div className="flex items-center gap-2" data-oid="9e4pi1-">
          <button
            onClick={() => goToPage(currentPage - 1)}
            disabled={currentPage <= 1}
            className="p-1.5 rounded hover:bg-surface-container-high disabled:opacity-40"
            data-oid="_c2_3zz">

            <ChevronLeft size={18} data-oid="oyifpg:" />
          </button>
          <span
            className="text-sm text-on-surface min-w-[80px] text-center"
            data-oid="pnq-k0d">

            {currentPage}
          </span>
          <button
            onClick={() => goToPage(currentPage + 1)}
            className="p-1.5 rounded hover:bg-surface-container-high disabled:opacity-40"
            data-oid="6erhr-t">

            <ChevronRight size={18} data-oid="chclcfd" />
          </button>
        </div>
        <div className="flex items-center gap-1" data-oid="artizrf">
          <button
            onClick={zoomOut}
            className="p-1.5 rounded hover:bg-surface-container-high"
            data-oid="8yeef49">

            <ZoomOut size={18} data-oid="8l3n4fc" />
          </button>
          <span
            className="text-xs text-on-surface-variant w-12 text-center"
            data-oid="2e40pod">

            {Math.round(scale * 100)}%
          </span>
          <button
            onClick={zoomIn}
            className="p-1.5 rounded hover:bg-surface-container-high"
            data-oid="_:nbtjd">

            <ZoomIn size={18} data-oid="zd-kf8d" />
          </button>
        </div>
      </div>
      <div
        className="flex-1 overflow-hidden"
        data-oid="hifx79j">

        <iframe
          src={iframeUrl}
          title="PDF preview"
          className="w-full h-full border-0"
          data-oid="trrdy_l" />

      </div>
    </div>);

}