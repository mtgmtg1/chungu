// [Flow: Step 1 (url/page prop 수신) -> Step 2 (iframe으로 브라우저 PDF 뷰어 로드) -> Step 3 (초기 페이지/줌 프래그먼트 적용)]
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

export default function PdfViewer({ url, page = 1 }) {
  const { t } = useTranslation();
  const [currentPage, setCurrentPage] = useState(page);
  const [scale] = useState(1.2);

  useEffect(() => {
    setCurrentPage(page);
  }, [page]);

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