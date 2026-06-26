// [Flow: Step 1 (페이지 메타데이터 로드) -> Step 2 (현재 페이지 markdown/이미지/PDF 동기 로드) -> Step 3 (SimpleEditor로 페이지 편집) -> Step 4 (페이지 선택/저장/이동)]
import { useEffect, useRef, useState, useCallback } from "react";
import { Virtuoso } from "react-virtuoso";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { useTranslation } from "react-i18next";
import {
  ChevronLeft,
  ChevronRight,
  Save,
  Loader2,
  Check,
  FileText,
  ImageIcon,
} from "lucide-react";
import { api } from "../api.js";
import PdfViewer from "./PdfViewer.jsx";
import MediaPlayer from "./MediaPlayer.jsx";
import SimpleEditor from "./SimpleEditor.jsx";

export default function PagedResultViewer({
  jobId,
  pages,
  sourceUrl,
  sourceType,
  sidebarOpen = true,
}) {
  const { t } = useTranslation();
  const [currentPage, setCurrentPage] = useState(pages[0]?.page_num || 1);
  const [pageMarkdown, setPageMarkdown] = useState("");
  const [loadingPage, setLoadingPage] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");
  const [error, setError] = useState("");
  const editorRef = useRef(null);

  const currentPageInfo = pages.find((p) => p.page_num === currentPage) || null;
  const imageUrl = sourceType === "images" ? currentPageInfo?.image_url : null;

  const loadPage = useCallback(
    async (pageNum) => {
      setLoadingPage(true);
      setError("");
      try {
        const preview = await api.previewJob(jobId, pageNum, pageNum);
        setPageMarkdown(preview.markdown || "");
        setCurrentPage(preview.start_page || pageNum);
      } catch (e) {
        setError(e.message || t("page:errors.loadFailed"));
      } finally {
        setLoadingPage(false);
      }
    },
    [jobId],
  );

  useEffect(() => {
    loadPage(currentPage);
  }, [currentPage, loadPage]);

  const saveCurrentPage = async () => {
    if (!editorRef.current) return;
    const updated = editorRef.current.getMarkdown();
    setSaving(true);
    setSaveMessage("");
    setError("");
    try {
      await api.saveResultPage(jobId, currentPage, updated);
      setSaveMessage(t("page:result.saved"));
      setTimeout(() => setSaveMessage(""), 2000);
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
    } finally {
      setSaving(false);
    }
  };

  const goToPage = (next) => {
    const nums = pages.map((p) => p.page_num);
    const min = Math.min(...nums);
    const max = Math.max(...nums);
    setCurrentPage(Math.min(Math.max(next, min), max));
  };

  const totalPages = pages.length;

  const renderSourcePanel = () => {
    if (sourceType === "pdf" && sourceUrl) {
      return (
        <PdfViewer
          url={sourceUrl}
          page={currentPage}
          onPageChange={setCurrentPage}
          data-oid="3w3hp.b"
        />
      );
    }
    if (sourceType === "images" && imageUrl) {
      return (
        <div
          className="flex-1 flex flex-col overflow-hidden bg-surface-container-low"
          data-oid="w:269q-"
        >
          <div
            className="h-12 border-b border-outline-variant bg-white flex items-center px-3 flex-shrink-0"
            data-oid="owpoh:2"
          >
            <ImageIcon
              size={16}
              className="text-outline mr-2"
              data-oid="064.d6d"
            />

            <span
              className="text-sm font-medium text-on-surface truncate"
              data-oid="3-b4oz."
            >
              {t("page:components.originalImage")}
            </span>
          </div>
          <div
            className="flex-1 overflow-auto custom-scrollbar p-4 flex items-center justify-center"
            data-oid="lh-fml0"
          >
            <img
              src={imageUrl}
              alt={t("page:components.originalImage", { number: currentPage })}
              className="max-w-full max-h-full object-contain shadow-lg rounded border border-outline-variant bg-white"
              data-oid="n5:nu:2"
            />
          </div>
        </div>
      );
    }
    if ((sourceType === "audio" || sourceType === "video") && sourceUrl) {
      return (
        <MediaPlayer
          sourceType={sourceType}
          url={sourceUrl}
          filename=""
          data-oid="cwoo06-"
        />
      );
    }
    return (
      <div
        className="flex-1 flex items-center justify-center text-on-surface-variant text-sm p-4"
        data-oid="ll9tkw_"
      >
        {t("page:components.cannotDisplaySource")}
      </div>
    );
  };

  const hasSourcePanel =
    sourceType === "pdf" ||
    sourceType === "images" ||
    sourceType === "audio" ||
    sourceType === "video";

  return (
    <div className="flex-1 flex overflow-hidden" data-oid="toiymro">
      <PanelGroup direction="horizontal" data-oid="0ger5sf">
        {sidebarOpen && (
          <>
            <Panel
              defaultSize={20}
              minSize={15}
              maxSize={35}
              className="border-r border-outline-variant bg-surface flex flex-col"
              data-oid="e-ge1co"
            >
              <div
                className="p-3 border-b border-outline-variant bg-surface-container-low"
                data-oid="q3:-w.n"
              >
                <p
                  className="text-xs font-bold text-on-surface-variant uppercase tracking-wider"
                  data-oid="tdq:0j3"
                >
                  {t("page:result.pageList")}
                </p>
                <p className="text-xs text-outline mt-1" data-oid="4zvlu18">
                  {t("page:result.totalPages", { total: totalPages })}
                </p>
              </div>
              <div className="flex-1 overflow-hidden" data-oid=".e8x.ya">
                <Virtuoso
                  data={pages}
                  itemContent={(idx, page) => (
                    <button
                      onClick={() => setCurrentPage(page.page_num)}
                      className={`w-full text-left px-3 py-2 border-b border-outline-variant/50 text-sm transition-colors ${
                        currentPage === page.page_num
                          ? "bg-primary-container/10 text-primary font-bold"
                          : "text-on-surface hover:bg-surface-container-high"
                      }`}
                      data-oid="j51o72a"
                    >
                      <div
                        className="flex items-center gap-2"
                        data-oid="gkd-306"
                      >
                        <FileText
                          size={14}
                          className="text-outline flex-shrink-0"
                          data-oid="q8g.b4i"
                        />

                        <span className="truncate" data-oid="9a_srlg">
                          {t("page:components.pdfPage", {
                            page: page.page_num,
                          })}
                        </span>
                      </div>
                      <p
                        className="text-xs text-outline truncate mt-0.5 pl-5"
                        data-oid="28ypv9q"
                      >
                        {page.preview}
                      </p>
                    </button>
                  )}
                  data-oid="rgykzk."
                />
              </div>
            </Panel>
            <PanelResizeHandle
              className="w-1 bg-outline-variant/50 hover:bg-primary/30 transition-colors"
              data-oid=":r-i5jt"
            />
          </>
        )}

        <Panel
          className="flex-1 flex flex-col overflow-hidden"
          data-oid="bopd6fy"
        >
          <div
            className="h-12 border-b border-outline-variant bg-white flex items-center justify-between px-4 flex-shrink-0"
            data-oid="rkc:9b-"
          >
            <div className="flex items-center gap-2" data-oid="haxz.hh">
              <button
                onClick={() => goToPage(currentPage - 1)}
                className="p-1.5 rounded hover:bg-surface-container-high"
                data-oid="dana1mz"
              >
                <ChevronLeft size={18} data-oid="f16wrv4" />
              </button>
              <span
                className="text-sm font-medium text-on-surface"
                data-oid="vp-b:0c"
              >
                {currentPage} / {totalPages}
              </span>
              <button
                onClick={() => goToPage(currentPage + 1)}
                className="p-1.5 rounded hover:bg-surface-container-high"
                data-oid="4dz5p:f"
              >
                <ChevronRight size={18} data-oid="3ahsoen" />
              </button>
            </div>
            <div className="flex items-center gap-2" data-oid="xu9q3cy">
              {saveMessage && (
                <span
                  className="text-xs text-green-600 flex items-center gap-1"
                  data-oid="btuwc-z"
                >
                  <Check size={12} data-oid="hhr5iu5" />
                  {saveMessage}
                </span>
              )}
              <button
                onClick={saveCurrentPage}
                disabled={saving}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 text-white rounded-lg text-sm font-bold hover:opacity-90 disabled:opacity-50"
                data-oid="04_fh4j"
              >
                {saving ? (
                  <Loader2
                    size={14}
                    className="animate-spin"
                    data-oid="cf_781n"
                  />
                ) : (
                  <Save size={14} data-oid="7klafvf" />
                )}
                {t("page:result.save")}
              </button>
            </div>
          </div>

          {error && (
            <div
              className="bg-red-50 text-red-700 px-4 py-2 text-sm flex items-center gap-2 border-b border-red-200 flex-shrink-0"
              data-oid="a5-cokn"
            >
              {error}
            </div>
          )}

          {hasSourcePanel ? (
            <PanelGroup
              direction="horizontal"
              className="flex-1 overflow-hidden"
              data-oid="uemc5gm"
            >
              <Panel
                defaultSize={45}
                minSize={25}
                maxSize={70}
                className="overflow-hidden"
                data-oid="ds-klot"
              >
                {renderSourcePanel()}
              </Panel>
              <PanelResizeHandle
                className="w-1 bg-outline-variant/50 hover:bg-primary/30 transition-colors"
                data-oid="7pzivus"
              />

              <Panel
                defaultSize={55}
                minSize={30}
                maxSize={75}
                className="flex flex-col bg-white overflow-hidden"
                data-oid="47s06uh"
              >
                {loadingPage ? (
                  <div
                    className="flex-1 flex items-center justify-center"
                    data-oid="-0w582c"
                  >
                    <Loader2
                      className="animate-spin text-primary"
                      size={24}
                      data-oid=":oyvjpd"
                    />
                  </div>
                ) : (
                  <SimpleEditor
                    ref={editorRef}
                    markdown={pageMarkdown}
                    editable
                    data-oid="2nok50_"
                  />
                )}
              </Panel>
            </PanelGroup>
          ) : (
            <div
              className="flex-1 flex flex-col bg-white overflow-hidden"
              data-oid="jc:9.e0"
            >
              {loadingPage ? (
                <div
                  className="flex-1 flex items-center justify-center"
                  data-oid=".vgs:ja"
                >
                  <Loader2
                    className="animate-spin text-primary"
                    size={24}
                    data-oid="7j68pwf"
                  />
                </div>
              ) : (
                <SimpleEditor
                  ref={editorRef}
                  markdown={pageMarkdown}
                  editable
                  data-oid="qcw.72_"
                />
              )}
            </div>
          )}
        </Panel>
      </PanelGroup>
    </div>
  );
}
