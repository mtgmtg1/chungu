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
          data-oid="8kmamif"
        />
      );
    }
    if (sourceType === "images" && imageUrl) {
      return (
        <div
          className="flex-1 flex flex-col overflow-hidden bg-surface-container-low"
          data-oid="e61avxt"
        >
          <div
            className="h-12 border-b border-outline-variant bg-white flex items-center px-3 flex-shrink-0"
            data-oid="a2811yy"
          >
            <ImageIcon
              size={16}
              className="text-outline mr-2"
              data-oid="w386s-y"
            />

            <span
              className="text-sm font-medium text-on-surface truncate"
              data-oid="p7rhj4g"
            >
              {t("page:components.originalImage")}
            </span>
          </div>
          <div
            className="flex-1 overflow-auto custom-scrollbar p-4 flex items-center justify-center"
            data-oid="m8ac0yi"
          >
            <img
              src={imageUrl}
              alt={t("page:components.originalImage", { number: currentPage })}
              className="max-w-full max-h-full object-contain shadow-lg rounded border border-outline-variant bg-white"
              data-oid="p4ex51i"
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
          data-oid="74i0o79"
        />
      );
    }
    return (
      <div
        className="flex-1 flex items-center justify-center text-on-surface-variant text-sm p-4"
        data-oid="urt1nmx"
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
    <div className="flex-1 flex overflow-hidden" data-oid="9grrz:c">
      <PanelGroup direction="horizontal" data-oid="nx8cibg">
        {sidebarOpen && (
          <>
            <Panel
              defaultSize={20}
              minSize={15}
              maxSize={35}
              className="border-r border-outline-variant bg-surface flex flex-col"
              data-oid="m.s-c:w"
            >
              <div
                className="p-3 border-b border-outline-variant bg-surface-container-low"
                data-oid="7s2nrab"
              >
                <p
                  className="text-xs font-bold text-on-surface-variant uppercase tracking-wider"
                  data-oid="z:01:i6"
                >
                  {t("page:result.pageList")}
                </p>
                <p className="text-xs text-outline mt-1" data-oid="l0gjaer">
                  {t("page:result.totalPages", { total: totalPages })}
                </p>
              </div>
              <div className="flex-1 overflow-hidden" data-oid="wz65v:b">
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
                      data-oid="8zlp6vl"
                    >
                      <div
                        className="flex items-center gap-2"
                        data-oid="ahpbqa5"
                      >
                        <FileText
                          size={14}
                          className="text-outline flex-shrink-0"
                          data-oid="jgmib_."
                        />

                        <span className="truncate" data-oid="j0ixjt6">
                          {t("page:components.pdfPage", {
                            page: page.page_num,
                          })}
                        </span>
                      </div>
                      <p
                        className="text-xs text-outline truncate mt-0.5 pl-5"
                        data-oid="v.-k1:b"
                      >
                        {page.preview}
                      </p>
                    </button>
                  )}
                  data-oid="hfg:nky"
                />
              </div>
            </Panel>
            <PanelResizeHandle
              className="w-1 bg-outline-variant/50 hover:bg-primary/30 transition-colors"
              data-oid="6mz3vke"
            />
          </>
        )}

        <Panel
          className="flex-1 flex flex-col overflow-hidden"
          data-oid="ui_0qx3"
        >
          <div
            className="h-12 border-b border-outline-variant bg-white flex items-center justify-between px-4 flex-shrink-0"
            data-oid="j643u-y"
          >
            <div className="flex items-center gap-2" data-oid="ysluiny">
              <button
                onClick={() => goToPage(currentPage - 1)}
                className="p-1.5 rounded hover:bg-surface-container-high"
                data-oid="6s8-_0n"
              >
                <ChevronLeft size={18} data-oid="wrb3i01" />
              </button>
              <span
                className="text-sm font-medium text-on-surface"
                data-oid="n86uamj"
              >
                {currentPage} / {totalPages}
              </span>
              <button
                onClick={() => goToPage(currentPage + 1)}
                className="p-1.5 rounded hover:bg-surface-container-high"
                data-oid="ounzdw:"
              >
                <ChevronRight size={18} data-oid="xf50.:b" />
              </button>
            </div>
            <div className="flex items-center gap-2" data-oid="0opfhtl">
              {saveMessage && (
                <span
                  className="text-xs text-green-600 flex items-center gap-1"
                  data-oid="j5b.:l."
                >
                  <Check size={12} data-oid="iob5p09" />
                  {saveMessage}
                </span>
              )}
              <button
                onClick={saveCurrentPage}
                disabled={saving}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 text-white rounded-lg text-sm font-bold hover:opacity-90 disabled:opacity-50"
                data-oid="0s0s0bf"
              >
                {saving ? (
                  <Loader2
                    size={14}
                    className="animate-spin"
                    data-oid="jwkn1rb"
                  />
                ) : (
                  <Save size={14} data-oid="tlhbcof" />
                )}
                {t("page:result.save")}
              </button>
            </div>
          </div>

          {error && (
            <div
              className="bg-red-50 text-red-700 px-4 py-2 text-sm flex items-center gap-2 border-b border-red-200 flex-shrink-0"
              data-oid="fqpxu.n"
            >
              {error}
            </div>
          )}

          {hasSourcePanel ? (
            <PanelGroup
              direction="horizontal"
              className="flex-1 overflow-hidden"
              data-oid="wbpjin7"
            >
              <Panel
                defaultSize={45}
                minSize={25}
                maxSize={70}
                className="overflow-hidden"
                data-oid="_4r5fdj"
              >
                {renderSourcePanel()}
              </Panel>
              <PanelResizeHandle
                className="w-1 bg-outline-variant/50 hover:bg-primary/30 transition-colors"
                data-oid="rn4azy0"
              />

              <Panel
                defaultSize={55}
                minSize={30}
                maxSize={75}
                className="flex flex-col bg-white overflow-hidden"
                data-oid="ue-8gmm"
              >
                {loadingPage ? (
                  <div
                    className="flex-1 flex items-center justify-center"
                    data-oid="kti5mwj"
                  >
                    <Loader2
                      className="animate-spin text-primary"
                      size={24}
                      data-oid="2acty.6"
                    />
                  </div>
                ) : (
                  <SimpleEditor
                    ref={editorRef}
                    markdown={pageMarkdown}
                    editable
                    data-oid="-ocn9ti"
                  />
                )}
              </Panel>
            </PanelGroup>
          ) : (
            <div
              className="flex-1 flex flex-col bg-white overflow-hidden"
              data-oid="8m4s7e_"
            >
              {loadingPage ? (
                <div
                  className="flex-1 flex items-center justify-center"
                  data-oid="ms_jktn"
                >
                  <Loader2
                    className="animate-spin text-primary"
                    size={24}
                    data-oid="pxexur0"
                  />
                </div>
              ) : (
                <SimpleEditor
                  ref={editorRef}
                  markdown={pageMarkdown}
                  editable
                  data-oid="1bhay7t"
                />
              )}
            </div>
          )}
        </Panel>
      </PanelGroup>
    </div>
  );
}
