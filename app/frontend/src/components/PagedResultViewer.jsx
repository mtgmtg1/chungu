// [Flow: Step 1 (페이지 메타데이터 로드) -> Step 2 (현재 페이지 markdown/이미지/PDF 동기 로드) -> Step 3 (페이지 내비게이션: 이전/다음/페이지 목록) -> Step 4 (편집 모드: SimpleEditor) -> Step 5 (자동 저장)]
import { useEffect, useRef, useState, useCallback, useMemo, forwardRef, useImperativeHandle, memo } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { useTranslation } from "react-i18next";
import { Loader2, ChevronLeft, ChevronRight } from "lucide-react";
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
  const totalPages = pageNumbers.length;
  const currentIndex = pageNumbers.indexOf(currentPage);
  const canGoPrev = currentIndex > 0;
  const canGoNext = currentIndex >= 0 && currentIndex < totalPages - 1;

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

  const goToPrev = useCallback(() => {
    if (canGoPrev) goToPage(pageNumbers[currentIndex - 1]);
  }, [canGoPrev, currentIndex, pageNumbers, goToPage]);

  const goToNext = useCallback(() => {
    if (canGoNext) goToPage(pageNumbers[currentIndex + 1]);
  }, [canGoNext, currentIndex, pageNumbers, goToPage]);

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

  const handlePageInputChange = (e) => {
    const value = parseInt(e.target.value, 10);
    if (!isNaN(value)) goToPage(value);
  };

  const renderPageNav = () => (
    <div className="flex items-center justify-between px-4 py-2 bg-surface-container-low border-b border-outline-variant flex-shrink-0" data-oid="paged-nav">
      <div className="flex items-center gap-2">
        <button
          onClick={goToPrev}
          disabled={!canGoPrev}
          className="p-1.5 rounded-lg bg-white border border-outline-variant hover:bg-primary/10 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          title={t("common:previous")}
          data-oid="paged-prev">
          <ChevronLeft size={18} />
        </button>
        <div className="flex items-center gap-1.5 text-sm text-on-surface">
          <span className="text-on-surface-variant">{t("page:result.file")}</span>
          <input
            type="number"
            min={1}
            max={totalPages}
            value={currentPage}
            onChange={handlePageInputChange}
            className="w-14 px-2 py-1 text-center border border-outline-variant rounded-md bg-white text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
            data-oid="paged-input"
          />
          <span className="text-on-surface-variant">/ {totalPages}</span>
        </div>
        <button
          onClick={goToNext}
          disabled={!canGoNext}
          className="p-1.5 rounded-lg bg-white border border-outline-variant hover:bg-primary/10 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          title={t("common:next")}
          data-oid="paged-next">
          <ChevronRight size={18} />
        </button>
      </div>

      <div className="flex items-center gap-2">
        <select
          value={currentPage}
          onChange={(e) => goToPage(Number(e.target.value))}
          className="px-2 py-1.5 text-sm border border-outline-variant rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/40 max-w-[12rem]"
          data-oid="paged-select">
          {pages.map((p) => (
            <option key={p.page_num} value={p.page_num}>
              {p.page_num}{t("page:result.file")} — {p.filename || p.preview?.slice(0, 40) || ""}
              {p.filename ? "" : (p.preview?.length > 40 ? "..." : "")}
            </option>
          ))}
        </select>
      </div>
    </div>
  );

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

          {renderPageNav()}
          {renderMarkdownArea()}

        </Panel>
      </PanelGroup>
    </div>);

}));

export default PagedResultViewer;
