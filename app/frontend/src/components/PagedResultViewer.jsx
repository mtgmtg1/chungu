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
  onUpload,
  // [Flow: 부모 JobResultPage의 좌·우 패널 보이기/숨기기 토글 상태를 전달받아
  //       내부 PanelGroup의 각 Panel을 expand/collapse 한다]
  leftPanelOpen = true,
  rightPanelOpen = true
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
  // [Flow: react-resizable-panels Panel의 imperative handle(expand/collapse) 보관]
  const leftPanelRef = useRef(null);
  const rightPanelRef = useRef(null);

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

  // [Flow: Step 1 (leftPanelOpen prop 변경 감지) -> Step 2 (왼쪽 원본 패널 expand/collapse)]
  // 마크다운 모드에서도 헤더의 왼쪽 탭 토글이 작동하도록 내부 Panel을 외부에서 제어한다.
  useEffect(() => {
    if (!leftPanelRef.current) return;
    if (leftPanelOpen) {
      leftPanelRef.current.expand();
    } else {
      leftPanelRef.current.collapse();
    }
  }, [leftPanelOpen]);

  // [Flow: Step 1 (rightPanelOpen prop 변경 감지) -> Step 2 (오른쪽 마크다운 패널 expand/collapse)]
  // 마크다운 모드에서도 헤더의 오른쪽 탭 토글이 작동하도록 내부 Panel을 외부에서 제어한다.
  useEffect(() => {
    if (!rightPanelRef.current) return;
    if (rightPanelOpen) {
      rightPanelRef.current.expand();
    } else {
      rightPanelRef.current.collapse();
    }
  }, [rightPanelOpen]);

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
          ref={leftPanelRef}
          defaultSize={45}
          minSize={25}
          // [Flow: 오른쪽 패널이 collapse되어 있으면 왼쪽이 100%까지 확장 가능해야 함]
          // 반대 패널의 maxSize가 collapse를 막지 않도록 동적 maxSize 적용
          maxSize={rightPanelOpen ? 70 : 100}
          collapsible
          collapsedSize={0}
          className="overflow-hidden"
          data-oid="_4r5fdj"
          data-panel-side="left">

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
          ref={rightPanelRef}
          defaultSize={55}
          minSize={30}
          // [Flow: 왼쪽 패널이 collapse되어 있으면 오른쪽이 100%까지 확장 가능해야 함]
          // 반대 패널의 maxSize가 collapse를 막지 않도록 동적 maxSize 적용
          maxSize={leftPanelOpen ? 75 : 100}
          collapsible
          collapsedSize={0}
          className="flex flex-col bg-white overflow-hidden"
          data-oid="ue-8gmm"
          data-panel-side="right">

          {renderMarkdownArea()}

        </Panel>
      </PanelGroup>
    </div>);

}));

export default PagedResultViewer;
