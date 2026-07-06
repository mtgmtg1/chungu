// [Flow: Step 1 (페이지 메타데이터 로드) -> Step 2 (현재 페이지 markdown/이미지/PDF 동기 로드) -> Step 3 (편집 모드: SimpleEditor) -> Step 4 (저장만 노출, 페이지네이션은 소스 뷰어에 위임)]
import { useEffect, useRef, useState, useCallback, forwardRef, useImperativeHandle, memo } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { api } from "../api.js";
import SourcePanel from "./SourcePanel.jsx";
import SimpleEditor from "./SimpleEditor.jsx";

const PagedResultViewer = memo(forwardRef(function PagedResultViewer({
  jobId,
  pages,
  sourceUrl,
  sourceType,
  sourceFiles,
  imageUrls,
  onSaveAnnotations
}, ref) {
  const { t } = useTranslation();
  const [currentPage, setCurrentPage] = useState(pages[0]?.page_num || 1);
  const [pageMarkdown, setPageMarkdown] = useState("");
  const [loadingPage, setLoadingPage] = useState(false);
  const [error, setError] = useState("");
  const editorRef = useRef(null);
  const pendingMarkdownRef = useRef(pageMarkdown);
  const autoSaveTimerRef = useRef(null);

  const loadPage = useCallback(
    async (pageNum) => {
      setLoadingPage(true);
      setError("");
      try {
        const preview = await api.previewJob(jobId, pageNum, pageNum);
        const md = preview.markdown || "";
        setPageMarkdown(md);
        pendingMarkdownRef.current = md;
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

  // [Flow: Step 1 (페이지 마크다운 변경 시 pendingRef 갱신) -> Step 2 (1.5초 debounce 타이머 설정) -> Step 3 (타이머 완료 시 서버에 페이지 저장)]
  const saveCurrentPage = async (updated) => {
    const markdownToSave = updated !== undefined ? updated : pendingMarkdownRef.current;
    setError("");
    try {
      await api.saveResultPage(jobId, currentPage, markdownToSave);
      pendingMarkdownRef.current = markdownToSave;
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
      throw e;
    }
  };

  const handleChange = (updated) => {
    pendingMarkdownRef.current = updated;
    clearTimeout(autoSaveTimerRef.current);
    autoSaveTimerRef.current = setTimeout(() => {
      saveCurrentPage(pendingMarkdownRef.current);
    }, 1500);
  };

  useImperativeHandle(ref, () => ({
    save: () => saveCurrentPage(pendingMarkdownRef.current)
  }));

  useEffect(() => {
    return () => {
      clearTimeout(autoSaveTimerRef.current);
      if (pendingMarkdownRef.current !== pageMarkdown) {
        saveCurrentPage(pendingMarkdownRef.current);
      }
    };
  }, [pageMarkdown]);

  const hasSourcePanel =
  sourceType === "pdf" ||
  sourceType === "docx" ||
  sourceType === "hwp" ||
  sourceType === "images" ||
  sourceType === "audio" ||
  sourceType === "video" ||
  (sourceFiles && sourceFiles.length > 0);

  const renderMarkdownArea = () => {
    if (loadingPage) {
      return (
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="animate-spin text-primary" size={24} />
        </div>
      );
    }
    return (
      <SimpleEditor
        key={currentPage}
        ref={editorRef}
        markdown={pageMarkdown}
        editable
        onChange={handleChange}
      />
    );
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden" data-oid="9grrz:c">
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
              onSaveAnnotations={onSaveAnnotations}
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

            {renderMarkdownArea()}

          </Panel>
        </PanelGroup> :

      <div
        className="flex-1 flex flex-col bg-white overflow-hidden"
        data-oid="8m4s7e_">

          {renderMarkdownArea()}

        </div>
      }
    </div>);

}));

export default PagedResultViewer;