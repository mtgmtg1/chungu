// [Flow: Step 1 (페이지 메타데이터 로드) -> Step 2 (현재 페이지 markdown/이미지/PDF 동기 로드) -> Step 3 (SimpleEditor로 페이지 편집) -> Step 4 (저장만 노출, 페이지네이션은 소스 뷰어에 위임)]
import { useEffect, useRef, useState, useCallback } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { useTranslation } from "react-i18next";
import { Save, Loader2, Check } from "lucide-react";
import { api } from "../api.js";
import SourcePanel from "./SourcePanel.jsx";
import SimpleEditor from "./SimpleEditor.jsx";

export default function PagedResultViewer({
  jobId,
  pages,
  sourceUrl,
  sourceType,
  sourceFiles,
  imageUrls
}) {
  const { t } = useTranslation();
  const [currentPage, setCurrentPage] = useState(pages[0]?.page_num || 1);
  const [pageMarkdown, setPageMarkdown] = useState("");
  const [loadingPage, setLoadingPage] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");
  const [error, setError] = useState("");
  const editorRef = useRef(null);

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
    [jobId]
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

  const hasSourcePanel =
  sourceType === "pdf" ||
  sourceType === "docx" ||
  sourceType === "hwp" ||
  sourceType === "images" ||
  sourceType === "audio" ||
  sourceType === "video" ||
  (sourceFiles && sourceFiles.length > 0);

  return (
    <div className="flex-1 flex flex-col overflow-hidden" data-oid="9grrz:c">
      <div
        className="h-12 border-b border-outline-variant bg-white flex items-center justify-end px-4 flex-shrink-0"
        data-oid="j643u-y">

        <div className="flex items-center gap-2" data-oid="0opfhtl">
          {saveMessage &&
          <span
            className="text-xs text-green-600 flex items-center gap-1"
            data-oid="j5b.:l.">

              <Check size={12} data-oid="iob5p09" />
              {saveMessage}
            </span>
          }
          <button
            onClick={saveCurrentPage}
            disabled={saving}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 text-white rounded-lg text-sm font-bold hover:opacity-90 disabled:opacity-50"
            data-oid="0s0s0bf">

            {saving ?
            <Loader2
              size={14}
              className="animate-spin"
              data-oid="jwkn1rb" /> :
            <Save size={14} data-oid="tlhbcof" />
            }
            {t("page:result.save")}
          </button>
        </div>
      </div>

      {error &&
      <div
        className="bg-red-50 text-red-700 px-4 py-2 text-sm flex items-center gap-2 border-b border-red-200 flex-shrink-0"
        data-oid="fqpxu.n">

          {error}
        </div>
      }

      {hasSourcePanel ?
      <PanelGroup
        direction="horizontal"
        className="flex-1 overflow-hidden"
        data-oid="wbpjin7">

          <Panel
          defaultSize={45}
          minSize={25}
          maxSize={70}
          className="overflow-hidden"
          data-oid="_4r5fdj">

            <SourcePanel
              sourceFiles={sourceFiles}
              sourceUrl={sourceUrl}
              sourceType={sourceType}
              imageUrls={imageUrls}
              currentPage={currentPage}
              onPageChange={setCurrentPage}
              data-oid="8kmamif" />

          </Panel>
          <PanelResizeHandle
          className="w-1 bg-outline-variant/50 hover:bg-primary/30 transition-colors"
          data-oid="rn4azy0" />

          <Panel
          defaultSize={55}
          minSize={30}
          maxSize={75}
          className="flex flex-col bg-white overflow-hidden"
          data-oid="ue-8gmm">

            {loadingPage ?
          <div
            className="flex-1 flex items-center justify-center"
            data-oid="kti5mwj">

              <Loader2
              className="animate-spin text-primary"
              size={24}
              data-oid="2acty.6" />

            </div> :

          <SimpleEditor
            ref={editorRef}
            markdown={pageMarkdown}
            editable
            data-oid="-ocn9ti" />

          }
          </Panel>
        </PanelGroup> :

      <div
        className="flex-1 flex flex-col bg-white overflow-hidden"
        data-oid="8m4s7e_">

          {loadingPage ?
        <div
          className="flex-1 flex items-center justify-center"
          data-oid="ms_jktn">

              <Loader2
            className="animate-spin text-primary"
            size={24}
            data-oid="pxexur0" />

            </div> :

        <SimpleEditor
          ref={editorRef}
          markdown={pageMarkdown}
          editable
          data-oid="1bhay7t" />

        }
        </div>
      }
    </div>);

}