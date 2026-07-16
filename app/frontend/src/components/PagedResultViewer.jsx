// [Flow: Step 1 (페이지 메타데이터 로드) -> Step 2 (현재 페이지 markdown/이미지/PDF 동기 로드) -> Step 3 (파일탭에서 파일 선택) -> Step 4 (편집 모드: SimpleEditor) -> Step 5 (자동 저장)]
import { useEffect, useRef, useState, useCallback, useMemo, forwardRef, useImperativeHandle, memo } from "react";
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
  onSaveAnnotations,
  onUpload
}, ref) {
  const { t } = useTranslation();
  const [currentPage, setCurrentPage] = useState(pages[0]?.page_num || 1);
  const [pageMarkdown, setPageMarkdown] = useState("");
  const [loadingPage, setLoadingPage] = useState(false);
  const [error, setError] = useState("");
  const [saveMessage, setSaveMessage] = useState("");
  const editorRef = useRef(null);
  const pendingMarkdownRef = useRef(pageMarkdown);
  const autoSaveTimerRef = useRef(null);
  const saveMessageTimerRef = useRef(null);

  const pageNumbers = useMemo(() => pages.map((p) => p.page_num), [pages]);

  const loadPage = useCallback(
    async (pageNum) => {
      setLoadingPage(true);
      setError("");
      try {
        const preview = await api.previewJob(jobId, pageNum, pageNum);
        const md = preview.markdown || "";
        setPageMarkdown(md);
        pendingMarkdownRef.current = md;
      } catch (e) {
        setError(e.message || t("page:errors.loadFailed"));
      } finally {
        setLoadingPage(false);
      }
    },
    [jobId, t]
  );

  useEffect(() => {
    loadPage(currentPage);
  }, [currentPage, loadPage]);

  const goToPage = useCallback((pageNum) => {
    const target = pageNumbers.includes(pageNum) ? pageNum : pageNumbers[0];
    if (target && target !== currentPage) {
      setCurrentPage(target);
    }
  }, [pageNumbers, currentPage]);

  // [Flow: Step 1 (페이지 마크다운 변경 시 pendingRef 갱신) -> Step 2 (1초 debounce 타이머 설정) -> Step 3 (타이머 완료 시 서버에 페이지 저장)]
  const saveCurrentPage = useCallback(async (updated) => {
    const markdownToSave = updated !== undefined ? updated : pendingMarkdownRef.current;
    setError("");
    try {
      await api.saveResultPage(jobId, currentPage, markdownToSave);
      pendingMarkdownRef.current = markdownToSave;
      setSaveMessage(t("page:result.autoSaved"));
      if (saveMessageTimerRef.current) clearTimeout(saveMessageTimerRef.current);
      saveMessageTimerRef.current = setTimeout(() => setSaveMessage(""), 2000);
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
      throw e;
    }
  }, [currentPage, jobId, t]);

  const handleChange = useCallback((updated) => {
    pendingMarkdownRef.current = updated;
    clearTimeout(autoSaveTimerRef.current);
    autoSaveTimerRef.current = setTimeout(() => {
      saveCurrentPage(pendingMarkdownRef.current);
    }, 1000);
  }, [saveCurrentPage]);

  useImperativeHandle(ref, () => ({
    save: () => saveCurrentPage(pendingMarkdownRef.current)
  }), [saveCurrentPage]);

  useEffect(() => {
    return () => {
      clearTimeout(autoSaveTimerRef.current);
      if (pendingMarkdownRef.current !== pageMarkdown) {
        saveCurrentPage(pendingMarkdownRef.current);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

      {saveMessage &&
      <div className="px-4 py-1 text-sm text-on-surface-variant font-medium bg-surface border-b border-outline-variant flex-shrink-0" data-oid="paged-save-msg">
        {saveMessage}
      </div>
      }

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
            currentPage={1}
            selectedFileIndex={currentPage - 1}
            onFileSelect={(idx) => goToPage(idx + 1)}
            onSaveAnnotations={onSaveAnnotations}
            onUpload={onUpload}
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
      </PanelGroup>
    </div>);

}));

export default PagedResultViewer;
