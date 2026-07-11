// [Flow: Step 1 (job ID로 진입) -> Step 2 (작업 상태 폴링) -> Step 3 (완료 시 preview API 호출) -> Step 4 (100페이지 초과 시 페이지 단위 뷰어, 이하 시 전체 에디터) -> Step 5 (마크다운/Office/CSV 다운로드)]
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  ArrowLeft,
  Box,
  ChevronDown,
  FileCode,
  FileDown,
  FileSpreadsheet,
  FileText,
  Loader2,
  PanelLeft,
  PanelLeftClose,
  PanelRight,
  PanelRightClose,
  RefreshCw,
  Trash2,
  Workflow,
  XCircle } from
"lucide-react";
import SourcePanel from "../components/SourcePanel.jsx";
import PoetryProgress from "../components/PoetryProgress.jsx";
import PagedResultViewer from "../components/PagedResultViewer.jsx";
import SimpleEditor from "../components/SimpleEditor.jsx";
import SpreadsheetEditor from "../components/SpreadsheetEditor.jsx";
import AgentInputBar from "../components/AgentInputBar.jsx";
import AgentChatModal from "../components/AgentChatModal.jsx";
import SandboxBrowser from "../components/SandboxBrowser.jsx";
import UploadPopup from "../components/UploadPopup.jsx";
import FlowViewer from "../components/FlowViewer.jsx";
import { api } from "../api.js";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { SkeletonPageResult } from "../components/Skeleton.jsx";
import { getDisplayProgress } from "../utils/progress.js";
import { useIsMobile } from "../hooks/useMediaQuery.js";

function downloadByUrl(url, filename) {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

export default function JobResultPage() {
  const { jobId } = useParams();
  const nav = useNavigate();
  const { t, i18n } = useTranslation();
  const isMobile = useIsMobile();
  const statusLabel = (status) => t(`common:status.${status}`) || status;
  const [job, setJob] = useState(null);
  const [markdown, setMarkdown] = useState("");
  const [sourceUrl, setSourceUrl] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [converting, setConverting] = useState(false);
  const [pages, setPages] = useState([]);
  const [sourceType, setSourceType] = useState(null);
  const [imageUrls, setImageUrls] = useState([]);
  const [sourceFiles, setSourceFiles] = useState([]);
  const [fileMarkdowns, setFileMarkdowns] = useState([]);
  const [selectedFileIndex, setSelectedFileIndex] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [rightPanelOpen, setRightPanelOpen] = useState(true);
  const [now, setNow] = useState(Date.now());
  const pollRef = useRef(null);
  const editorRef = useRef(null);
  const pagedViewerRef = useRef(null);
  const sourcePanelApiRef = useRef(null); // SourcePanel imperhandle (scrollToPage) 용
  const flowViewerApiRef = useRef(null); // FlowViewer imperative handle (updateFromAgent) 용
  const [sourcePanelHandle, setSourcePanelHandle] = useState(null);
  const sourcePanelRef = useCallback((node) => {
    if (node) setSourcePanelHandle(node);
  }, []);
  const [rightPanelHandle, setRightPanelHandle] = useState(null);
  const rightPanelRef = useCallback((node) => {
    if (node) setRightPanelHandle(node);
  }, []);

  const [previewMode, setPreviewMode] = useState("markdown"); // "markdown" | "xlsxBasic" | "xlsxAdvanced"
  const [basicUrl, setBasicUrl] = useState(null);
  const [advancedUrl, setAdvancedUrl] = useState(null);
  const [xlsxAdvancedPolling, setXlsxAdvancedPolling] = useState(false);
  const [jobActionModal, setJobActionModal] = useState(false);
  const [deleteSourceFileModal, setDeleteSourceFileModal] = useState(false);
  const [pendingDeleteFile, setPendingDeleteFile] = useState(null);
  const [markdownSaveMessage, setMarkdownSaveMessage] = useState("");
  const markdownSaveMessageTimerRef = useRef(null);

  // PDF 하이라이트/여백 주석 (원본 스캔 PDF에 형광펜 + 여백 코멘트 생성)
  const annotateMode = "both"; // highlight | margin_note | both
  const annotateCommentMode = "llm_summary"; // user_text | llm_summary
  const annotateAdvanced = false;
  const [annotatePolling, setAnnotatePolling] = useState(false);

  const [downloadDropdownOpen, setDownloadDropdownOpen] = useState(false);
  const downloadDropdownTimerRef = useRef(null);

  // 뷰 모드 드롭다운 (Markdown / Excel / Flow 전환)
  const [viewModeDropdownOpen, setViewModeDropdownOpen] = useState(false);
  const viewModeDropdownTimerRef = useRef(null);

  // AI 에이전트 채팅 모달 상태
  const [chatOpen, setChatOpen] = useState(false);
  // 백그라운드에서 실행 중인 에이전트 수 (모달을 닫아도 스트리밍이 계속되는 세션 개수)
  const [agentRunningCount, setAgentRunningCount] = useState(0);
  // Kata 샌드박스 상태 (에이전트 격리 실행 환경)
  const [sandboxId, setSandboxId] = useState(null);
  const [sandboxPanelOpen, setSandboxPanelOpen] = useState(false);
  // 새 파일 업로드 팝업 상태
  const [uploadPopupOpen, setUploadPopupOpen] = useState(false);
  // 업로드 진행률 (SourcePanel에 표시하기 위해 상위에서 관리)
  const [uploadProgress, setUploadProgress] = useState({ current: 0, total: 0, percent: 0, fileName: "" });
  // 추가 파일 증분 변환 폴링 (source_files 중 status=processing인 항목이 있을 때)
  const [addedFilesPolling, setAddedFilesPolling] = useState(false);
  // 모바일 탭 전환: SourcePanel과 결과 콘텐츠를 토글 ("source" | "result")
  const [mobileViewTab, setMobileViewTab] = useState("source");

  const openDropdown = (setter, timerRef) => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    setter(true);
  };

  const closeDropdown = (setter, timerRef) => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setter(false), 150);
  };

  const PAGE_THRESHOLD = 100;
  const needsPagedMode = (j) =>
  (j?.total_pages || 0) > PAGE_THRESHOLD ||
  (j?.total_files || 0) > PAGE_THRESHOLD;

  // [Flow: Step 1 (source_files가 2개 이상이고 실제 마크다운이 있는지 확인) -> Step 2 (선택한 파일의 마크다운이 비어 있으면 전체 결합 마크다운로 폴백)]
  const hasFileMarkdowns = fileMarkdowns.length > 1 && fileMarkdowns.some(Boolean);
  const selectedFileMarkdown = fileMarkdowns[selectedFileIndex] || "";
  const displayMarkdown = hasFileMarkdowns && selectedFileMarkdown.trim()
    ? selectedFileMarkdown
    : markdown;

  useEffect(() => {
    if (!jobId) return;
    loadJob();
    return () => {
      clearInterval(pollRef.current);
    };
  }, [jobId]);

  // [Flow: Step 1 (활성 작업 확인) -> Step 2 (1초 간격 now 갱신) -> Step 3 (시간진행바 리렌더링)]
  useEffect(() => {
    if (job?.status === "done" || job?.status === "error") return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [job?.status]);

  async function loadJob() {
    try {
      const data = await api.getJob(jobId);
      setJob(data);
      if (data.xlsx_advanced_status === "done" || data.xlsx_advanced_status === "error") {
        setXlsxAdvancedPolling(false);
      }
      const hasProcessingAnnotations = data.annotated_pdf_files?.some(
        (f) => f.status === "processing"
      );
      setAnnotatePolling(hasProcessingAnnotations);
      if (data.status === "done") {
        clearInterval(pollRef.current);
        await loadPreview();
      } else if (data.status === "error") {
        clearInterval(pollRef.current);
        setLoading(false);
      } else {
        startPolling();
      }
    } catch (e) {
      const msg = e.message || "";
      if (msg.includes("Job expired") || msg.includes("Job not found")) {
        setError(t("page:errors.jobExpired"));
      } else {
        setError(msg || t("page:errors.loadFailed"));
      }
      setLoading(false);
    }
  }

  function startPolling() {
    clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const data = await api.getJob(jobId);
        setJob(data);
        if (data.xlsx_advanced_status === "done" || data.xlsx_advanced_status === "error") {
          setXlsxAdvancedPolling(false);
        }
        const hasProcessingAnnotations = data.annotated_pdf_files?.some(
          (f) => f.status === "processing"
        );
        setAnnotatePolling(hasProcessingAnnotations);
        if (data.status === "done") {
          clearInterval(pollRef.current);
          await loadPreview();
        } else if (data.status === "error") {
          clearInterval(pollRef.current);
          setLoading(false);
        }
      } catch {

        /* 무시 */}
    }, 2000);
  }

  useEffect(() => {
    if (!xlsxAdvancedPolling) return;
    const interval = setInterval(() => {
      loadJob();
    }, 5000);
    return () => clearInterval(interval);
  }, [xlsxAdvancedPolling, jobId]);

  useEffect(() => {
    if (!annotatePolling) return;
    const interval = setInterval(() => {
      loadJob();
    }, 5000);
    return () => clearInterval(interval);
  }, [annotatePolling, jobId]);

  // [Flow: Step 1 (addedFilesPolling이 true면 5초 간격으로 job 폴링) -> Step 2 (source_files 중 processing인 항목이 없으면 폴링 중지)]
  useEffect(() => {
    if (!addedFilesPolling) return;
    const interval = setInterval(() => {
      loadJob();
    }, 5000);
    return () => clearInterval(interval);
  }, [addedFilesPolling, jobId]);

  // [Flow: Step 1 (사이드바 상태 변경 감지) -> Step 2 (접힌 상태면 왼쪽 원본 패널 collapse, 펼친 상태면 expand)]
  useEffect(() => {
    if (!sourcePanelHandle) return;
    if (sidebarOpen) {
      sourcePanelHandle.expand();
    } else {
      sourcePanelHandle.collapse();
    }
  }, [sourcePanelHandle, sidebarOpen]);

  // [Flow: Step 1 (우측 결과 패널 상태 변경 감지) -> Step 2 (접힌 상태면 우측 마크다운/엑셀 패널 collapse, 펼친 상태면 expand)]
  useEffect(() => {
    if (!rightPanelHandle) return;
    if (rightPanelOpen) {
      rightPanelHandle.expand();
    } else {
      rightPanelHandle.collapse();
    }
  }, [rightPanelHandle, rightPanelOpen]);

  async function loadPreview() {
    try {
      // [Flow: Step 1 (DB의 total_pages/total_files로 페이징 모드 여부를 먼저 판단) -> Step 2 (페이징 모드면 첫 페이지만 로드하여 소스/메타정보 획득) -> Step 3 (비페이징 모드면 전체 마크다운 로드)]
      const usePaged = needsPagedMode(job);
      const preview = usePaged
        ? await api.previewJob(jobId, 1, 1)
        : await api.previewJob(jobId);
      setSourceUrl(preview.source_url);
      setSourceType(preview.source_type);
      setImageUrls(preview.image_urls || []);
      setSourceFiles(preview.source_files || []);
      const fms = (preview.source_files || []).map((f) => f.result_markdown || "");
      setFileMarkdowns(fms);
      setSelectedFileIndex(0);
      // [Flow: 추가 파일 증분 변환 중인지 확인 — source_files 중 status=processing인 항목이 있으면 폴링]
      const hasProcessingFiles = (preview.source_files || []).some(
        (f) => f.status === "processing"
      );
      setAddedFilesPolling(hasProcessingFiles);
      // [Flow: Step 1 (DB의 total_pages/total_files 확인) -> Step 2 (폴백: 마크다운의 last_page 확인) -> Step 3 (둘 중 하나라도 임계값 초과 시 페이징 모드)]
      const finalUsePaged = usePaged || (preview.last_page || 0) > PAGE_THRESHOLD;
      if (finalUsePaged) {
        const meta = await api.previewJobPages(jobId);
        setPages(meta.pages || []);
        setMarkdown("");
      } else {
        setMarkdown(preview.markdown || "");
        setPages([]);
      }
    } catch (e) {
      setError(e.message || t("page:errors.loadFailed"));
    } finally {
      setLoading(false);
    }
  }

  // [Flow: Step 1 (페이징 모드면 PagedResultViewer에 flush 요청) -> Step 2 (파일별 마크다운 모드면 선택 파일 갱신 후 API 저장) -> Step 3 (단일 마크다운 모드면 API 저장) -> Step 4 (자동 저장 완료 메시지 표시)]
  async function autoSaveMarkdown(updated) {
    if (pages.length > 0 && pagedViewerRef.current) {
      try {
        await pagedViewerRef.current.save();
      } catch (e) {
        setError(e.message || t("page:errors.unknown"));
      }
      return;
    }
    if (updated === undefined) {
      if (!editorRef.current) return;
      updated = editorRef.current.getMarkdown();
    }
    try {
      if (hasFileMarkdowns) {
        const next = [...fileMarkdowns];
        next[selectedFileIndex] = updated;
        setFileMarkdowns(next);
        await api.saveResultFileMarkdowns(jobId, next);
      } else {
        await api.saveResultMarkdown(jobId, updated);
        setMarkdown(updated);
      }
      setMarkdownSaveMessage(t("page:result.autoSaved"));
      if (markdownSaveMessageTimerRef.current) clearTimeout(markdownSaveMessageTimerRef.current);
      markdownSaveMessageTimerRef.current = setTimeout(() => setMarkdownSaveMessage(""), 2000);
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
    }
  }

  const autoSaveMarkdownRef = useRef(autoSaveMarkdown);
  autoSaveMarkdownRef.current = autoSaveMarkdown;

  // [Flow: loadJob을 ref에 보관 — 에이전트 완료 콜백에서 항상 최신 클로저로 job/preview 재로드]
  const loadJobRef = useRef(loadJob);
  loadJobRef.current = loadJob;

  const handleMarkdownChange = useCallback((updated) => {
    autoSaveMarkdownRef.current(updated);
  }, []);

  const handleFileSelect = async (index) => {
    if (index === selectedFileIndex) return;
    await autoSaveMarkdown();
    setSelectedFileIndex(index);
  };

  async function download(type) {
    if (type === "md") await autoSaveMarkdown();
    const { download_url } = await api.downloadJob(jobId, type);
    const base = job?.filename ?
    job.filename.replace(/\.[^/.]+$/, "") :
    "result";
    const ext = type === "md" ? "md" : type.startsWith("xlsx") ? "xlsx" : type;
    downloadByUrl(download_url, `${base}.${ext}`);
  }

  async function convertAndDownload(format) {
    await autoSaveMarkdown();
    setConverting(true);
    setError("");
    try {
      const { download_url } = await api.convertJob(jobId, format);
      const base = job?.filename ?
      job.filename.replace(/\.[^/.]+$/, "") :
      "result";
      const ext = format.startsWith("xlsx") ? "xlsx" : format;
      downloadByUrl(download_url, `${base}.${ext}`);
      await loadJob();
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
    } finally {
      setConverting(false);
    }
  }

  // [Flow: Step 1 (변환 API 호출) -> Step 2 (job 상태 갱신) -> Step 3 (다운로드 없이 프리뷰만)]
  async function convertOnly(format) {
    await autoSaveMarkdown();
    setConverting(true);
    setError("");
    try {
      await api.convertJob(jobId, format);
      await loadJob();
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
    } finally {
      setConverting(false);
    }
  }

  async function startXlsxAdvanced() {
    await autoSaveMarkdown();
    setConverting(true);
    setError("");
    try {
      const res = await api.convertJob(jobId, "xlsx_advanced");
      if (res.status === "processing") {
        setXlsxAdvancedPolling(true);
        setPreviewMode("xlsxAdvanced");
      }
      await loadJob();
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
    } finally {
      setConverting(false);
    }
  }

  // [Flow: Step 1 (instruction, pageRange 수신) -> Step 2 (직주석 파이프라인 실행) -> Step 3 (job 상태 갱신)]
  // LangGraph 에이전트 대신 FastAPI의 직접 주석 파이프라인(/api/jobs/{id}/annotate)을 사용한다.
  async function startAnnotate(instruction, pageRange) {
    if (!instruction || !instruction.trim()) return;
    setConverting(true);
    setError("");
    try {
      await api.annotateJob(jobId, {
        instruction: instruction.trim(),
        mode: annotateMode,
        commentMode: annotateCommentMode,
        advanced: annotateAdvanced,
        pageRange: pageRange || null,
      });
      await loadJob();
      setAnnotatePolling(true);
    } catch (e) {
      const msg = e.message || t("page:errors.unknown");
      if (msg.includes("구독이 필요") || msg.includes("subscription")) {
        setError(t("page:errors.subscriptionRequired"));
        setTimeout(() => nav("/price"), 2000);
      } else {
        setError(msg);
      }
    } finally {
      setConverting(false);
    }
  }

  // [Flow: Step 1 (instruction, pageRange 수신) -> Step 2 (주석 편집 파이프라인 실행) -> Step 3 (job 상태 갱신)]
  async function startAnnotateEdit(instruction, pageRange) {
    if (!instruction || !instruction.trim()) return;
    setConverting(true);
    setError("");
    try {
      await api.annotateJobEdit(jobId, {
        instruction: instruction.trim(),
        pageRange: pageRange || null,
      });
      await loadJob();
      setAnnotatePolling(true);
    } catch (e) {
      const msg = e.message || t("page:errors.unknown");
      if (msg.includes("구독이 필요") || msg.includes("subscription")) {
        setError(t("page:errors.subscriptionRequired"));
        setTimeout(() => nav("/price"), 2000);
      } else {
        setError(msg);
      }
    } finally {
      setConverting(false);
    }
  }

  async function handleAnnotateAction(action, annotationIndex) {
    setConverting(true);
    setError("");
    try {
      await api.annotateAction(jobId, action, annotationIndex);
      await loadJob();
      if (action === "retry") {
        setAnnotatePolling(true);
      }
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
    } finally {
      setConverting(false);
    }
  }

  // [Flow: Step 1 (annotationIndex 수신) -> Step 2 (cancel API 호출) -> Step 3 (job 상태 갱신)]
  async function handleCancelAnnotation(annotationIndex) {
    setConverting(true);
    setError("");
    try {
      await api.cancelAnnotation(jobId, annotationIndex);
      await loadJob();
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
    } finally {
      setConverting(false);
    }
  }

  async function handleXlsxAdvancedAction(action) {
    setConverting(true);
    setError("");
    try {
      await api.xlsxAdvancedAction(jobId, action);
      await loadJob();
      if (action === "retry") {
        setXlsxAdvancedPolling(true);
      }
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
    } finally {
      setConverting(false);
    }
  }


  // [Flow: Step 1 (선택된 원본 PDF의 주석을 자동 저장) -> Step 2 (annotation PDF면 덮어쓰기, 원본 PDF면 새 annotation 파일 생성)]
  // 자동 저장이므로 converting 오버레이/에러 배너/새로고침 없이 조용히 처리한다.
  async function handleSaveAnnotations(annotations) {
    const selected = sourceFiles[selectedFileIndex];
    if (!selected || selected.type !== "pdf") return;
    try {
      // [Flow: 파일별 주석 분리 — source_index를 전송하여 각 파일의 주석이 별도로 저장되도록 함]
      // 기존에는 항상 source_index: -1로 전송하여 모든 주석이 user_annotations.json에 합쳐졌으나,
      // 파일 추가 시 주석이 섞이는 문제를 해결하기 위해 source_index를 파일별로 분리.
      const fileSourceIndex = selected.source_index ?? -1;
      await api.saveUserAnnotations(jobId, {
        source_index: fileSourceIndex,
        annotations,
      });
    } catch (e) {
      // 자동 저장 실패는 콘솔에만 기록하고 사용자에게 노출하지 않는다.
      console.error("[auto-save annotations] failed:", e);
    }
  }

  // [Flow: Step 1 (팝업에서 선택한 action 설정) -> Step 2 (jobAction API 호출) -> Step 3 (상태 갱신 및 폴링 재개)]
  async function handleJobAction(action) {
    setConverting(true);
    setError("");
    try {
      await api.jobAction(jobId, action);
      setJobActionModal(false);
      await loadJob();
      if (action === "retry") {
        startPolling();
      }
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
    } finally {
      setConverting(false);
    }
  }

  // [Flow: Step 1 (삭제할 파일의 source_index/source_kind 선택) -> Step 2 (파일명과 함께 확인 모달 열기) -> Step 3 (사용자 확인 후 API 호출) -> Step 4 (목록 갱신)]
  function openDeleteSourceFileModal(sourceIndex, sourceKind) {
    const file = sourceFiles.find(
      (f) => f.source_index === sourceIndex && f.source_kind === sourceKind,
    );
    setPendingDeleteFile({
      sourceIndex,
      sourceKind,
      name: file?.name || "",
      status: file?.status || "done",
    });
    setDeleteSourceFileModal(true);
  }

  function closeDeleteSourceFileModal() {
    setDeleteSourceFileModal(false);
    setPendingDeleteFile(null);
  }

  async function confirmDeleteSourceFile() {
    if (!pendingDeleteFile) return;
    setConverting(true);
    setError("");
    try {
      await api.deleteSourceFile(
        jobId,
        pendingDeleteFile.sourceKind,
        pendingDeleteFile.sourceIndex,
      );
      // [Flow: Step 1 (API 삭제 성공 후 즉시 UI에서 항목 제거) -> Step 2 (모달 닫기) -> Step 3 (서버 최신 상태로 동기화)]
      setSourceFiles((prev) =>
        prev.filter(
          (f) =>
            f.source_index !== pendingDeleteFile.sourceIndex ||
            f.source_kind !== pendingDeleteFile.sourceKind,
        ),
      );
      setDeleteSourceFileModal(false);
      setPendingDeleteFile(null);
      await loadJob();
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
    } finally {
      setConverting(false);
    }
  }

  useEffect(() => {
    if (previewMode === "xlsxBasic" && job?.xlsx_basic_converted && !basicUrl) {
      api.downloadJob(jobId, "xlsx_basic")
        .then(res => setBasicUrl(res.download_url))
        .catch(e => setError(e.message || t("page:errors.unknown")));
    }
  }, [previewMode, job?.xlsx_basic_converted, basicUrl, jobId]);

  useEffect(() => {
    if (previewMode === "xlsxAdvanced" && job?.xlsx_advanced_converted && !advancedUrl) {
      api.downloadJob(jobId, "xlsx_advanced")
        .then(res => setAdvancedUrl(res.download_url))
        .catch(e => setError(e.message || t("page:errors.unknown")));
    }
  }, [previewMode, job?.xlsx_advanced_converted, advancedUrl, jobId]);

  // 구독제: Excel 생성 시 실제로 차감되는 것은 달러가 아니라 구독 월간 페이지 한도(기본/프리미엄)이다.
  const xlsxBasicUnits = job ? (job.total_pages || job.total_files || 1) : 0;
  const xlsxAdvancedUnits = job ? (job.total_pages || job.total_files || 1) : 0;

  const pct = getDisplayProgress(job, 80, now);

  // [Flow: Step 1 (previewMode에 따라 우측 콘텐츠 선택) -> Step 2 (마크다운이면 SimpleEditor, 엑셀이면 SpreadsheetEditor, 플로우이면 FlowViewer 또는 로딩 스피너)]
  const renderRightContent = () => {
    if (previewMode === "markdown") {
      return (
        <SimpleEditor
          key={selectedFileIndex}
          ref={editorRef}
          markdown={displayMarkdown}
          editable
          onPageChange={setCurrentPage}
          onChange={handleMarkdownChange}
          data-oid="result-editor" />
      );
    }
    if (previewMode === "flow") {
      return (
        <FlowViewer
          ref={flowViewerApiRef}
          markdown={displayMarkdown}
          jobId={jobId}
          onNodeClick={(node) => {
            // [Flow: 노드 클릭 -> SourcePanel PDF 해당 페이지로 스크롤]
            const page = node.data?.page;
            if (page && sourcePanelApiRef.current) {
              sourcePanelApiRef.current.scrollToPage(page);
            }
          }}
        />
      );
    }
    if (previewMode === "xlsxBasic") {
      return basicUrl
        ? <SpreadsheetEditor downloadUrl={basicUrl} jobId={jobId} fileName={job?.original_filename || "result.xlsx"} />
        : <div className="h-full flex items-center justify-center" data-oid="xlsx-basic-loading"><Loader2 className="animate-spin text-primary" size={24} /></div>;
    }
    return advancedUrl
      ? <SpreadsheetEditor downloadUrl={advancedUrl} jobId={jobId} fileName={job?.original_filename || "result.xlsx"} />
      : <div className="h-full flex items-center justify-center" data-oid="xlsx-advanced-loading"><Loader2 className="animate-spin text-primary" size={24} /></div>;
  };

  // [Flow: Step 1 (SourcePanel에 전달할 공통 props 객체 생성 — DRY) -> Step 2 (모바일이면 탭 전환 렌더링, 데스크탑이면 PanelGroup 분할 렌더링)]
  const renderResultArea = () => {
    const rightContent = renderRightContent();

    const sourcePanelProps = {
      sourceFiles,
      sourceUrl,
      sourceType,
      imageUrls,
      filename: job?.filename,
      selectedFileIndex,
      onFileSelect: handleFileSelect,
      onDeleteFile: openDeleteSourceFileModal,
      onRetryAnnotation: () => handleAnnotateAction("retry", 0),
      currentPage,
      totalPages: job?.total_pages || 1,
      onSaveAnnotations: handleSaveAnnotations,
      onStartAnnotate: startAnnotate,
      onStartAnnotateEdit: startAnnotateEdit,
      onCancelAnnotation: handleCancelAnnotation,
      onUpload: () => setUploadPopupOpen(true),
      uploadProgress,
      converting,
      annotationRuns: job?.annotated_pdf_files || [],
    };

    // [Flow: 모바일 — 탭 바로 SourcePanel / 결과 콘텐츠 전환, 한 번에 하나만 표시]
    if (isMobile) {
      return (
        <div className="flex-1 flex flex-col min-h-0" data-oid="result-mobile">
          {/* 모바일 탭 바 */}
          <div className="flex border-b border-outline-variant bg-surface flex-shrink-0" data-oid="mobile-tab-bar">
            <button
              onClick={() => setMobileViewTab("source")}
              className={`flex-1 flex items-center justify-center gap-2 py-3 text-sm font-medium transition-colors ${mobileViewTab === "source" ? "text-primary border-b-2 border-primary" : "text-on-surface-variant"}`}
              data-oid="mobile-tab-source">
              <span className="material-symbols-outlined text-lg">description</span>
              {t("page:result.source") || "원본"}
            </button>
            <button
              onClick={() => setMobileViewTab("result")}
              className={`flex-1 flex items-center justify-center gap-2 py-3 text-sm font-medium transition-colors ${mobileViewTab === "result" ? "text-primary border-b-2 border-primary" : "text-on-surface-variant"}`}
              data-oid="mobile-tab-result">
              <span className="material-symbols-outlined text-lg">article</span>
              {t("page:result.result") || "결과"}
            </button>
          </div>
          {/* 탭 콘텐츠 — 활성 탭만 렌더링하여 모바일 성능 확보 */}
          <div className="flex-1 flex flex-col min-h-0 overflow-hidden" data-oid="mobile-tab-content">
            {mobileViewTab === "source" ? (
              <SourcePanel ref={sourcePanelApiRef} {...sourcePanelProps} data-oid="result-source-mobile" />
            ) : (
              rightContent
            )}
          </div>
        </div>
      );
    }

    // [Flow: 데스크탑 — 기존 PanelGroup 좌우 분할 유지]
    return (
      <PanelGroup direction="horizontal" className="flex-1 flex min-h-0" data-oid="result-split">
        <Panel
          ref={sourcePanelRef}
          defaultSize={30}
          minSize={20}
          maxSize={100}
          collapsible
          collapsedSize={0}
          className="flex flex-col h-full min-h-0 overflow-hidden"
          data-oid="result-source-panel">
          <SourcePanel ref={sourcePanelApiRef} {...sourcePanelProps} data-oid="result-source" />
        </Panel>
        <PanelResizeHandle
          className="w-2 bg-outline-variant/50 hover:bg-primary transition-colors cursor-col-resize"
          data-oid="result-resize-handle" />
        <Panel
          ref={rightPanelRef}
          defaultSize={70}
          minSize={0}
          maxSize={100}
          collapsible
          collapsedSize={0}
          className="flex flex-col h-full min-h-0 overflow-hidden"
          data-oid="result-content-panel">
          {rightContent}
        </Panel>
      </PanelGroup>
    );
  };

  return (
    <div
      className="h-screen bg-background flex flex-col"
      data-oid="vl.tj_r">

      <header
        className="relative h-14 border-b border-outline-variant bg-surface flex items-center px-4 flex-shrink-0"
        data-oid="kxse7f.">

        <div className="flex items-center gap-2 md:gap-4 min-w-0 flex-1" data-oid="jz8kj2e">
          <Link
            to="/jobs"
            className="flex items-center gap-2 text-on-surface-variant hover:text-primary transition-colors shrink-0"
            data-oid="homj3ye">

            <ArrowLeft size={18} data-oid="pmqivjc" />
            <span className="font-medium hidden sm:inline" data-oid="efc.i4.">
              {t("common:jobs")}
            </span>
          </Link>
          <div className="h-4 w-px bg-outline-variant hidden md:block" data-oid="-vnoo-."></div>
          <h1
            className="font-headline-md text-headline-md font-bold text-on-surface truncate min-w-0"
            data-oid="aaxa04a">

            {job?.filename || jobId}
          </h1>
          {job?.status === "done" &&
          <span
            className="px-3 py-1 bg-green-100 text-green-700 text-xs font-bold rounded-full flex items-center gap-1.5 border border-green-200 shrink-0"
            data-oid="lxd0:1l">

              <span
              className="w-1.5 h-1.5 bg-green-600 rounded-full"
              data-oid="4iq1gl9">
            </span>
              {t("page:result.done")}
            </span>
          }
          {job?.status === "error" &&
          <span
            className="px-3 py-1 bg-red-100 text-red-700 text-xs font-bold rounded-full flex items-center gap-1.5 border border-red-200 shrink-0"
            data-oid="uf3gdos">

              <XCircle size={12} data-oid="vcowgtj" />
              {t("page:result.error")}
            </span>
          }
          {job?.status === "retrying" &&
          <span
            className="px-3 py-1 bg-amber-100 text-amber-700 text-xs font-bold rounded-full flex items-center gap-1.5 border border-amber-200 shrink-0"
            data-oid="retrying-badge">

              <RefreshCw size={12} className="animate-spin" data-oid="retrying-icon" />
              {t("page:result.retrying")}
            </span>
          }
        </div>

        {/* 헤더 정중앙: AI 에이전트 트리거 (좌·우 영역이 flex-1로 균형을 맞춰 자동 중앙 정렬) */}
        <div className="flex-shrink-0" data-oid="header-center-agent">
          {job?.status === "done" && (
            <AgentInputBar
              onOpenChat={() => setChatOpen(true)}
              runningCount={agentRunningCount}
            />
          )}
        </div>

        <div className="flex items-center gap-2 md:gap-3 flex-1 justify-end" data-oid="header-actions">
          {/* [Flow: Step 1 (완료된 작업의 뷰 모드 드롭다운) -> Step 2 (Markdown / Excel / Excel Advanced / Flow 선택)] */}
          {job?.status === "done" && !needsPagedMode(job) &&
          <div
            className="relative shrink-0"
            onMouseEnter={() => openDropdown(setViewModeDropdownOpen, viewModeDropdownTimerRef)}
            onMouseLeave={() => closeDropdown(setViewModeDropdownOpen, viewModeDropdownTimerRef)}
            data-oid="view-mode-dropdown">
          <button
            className="flex items-center gap-2 px-3 md:px-4 py-1.5 bg-surface-container-high text-on-surface rounded-lg text-sm font-medium hover:bg-surface-container-high/80 transition-colors border border-outline-variant"
            data-oid="view-mode-btn">
            {previewMode === "markdown" && "Markdown"}
            {previewMode === "xlsxBasic" && t("page:result.excel")}
            {previewMode === "xlsxAdvanced" && "Excel Advanced"}
            {previewMode === "flow" && t("page:result.flow")}
            <ChevronDown size={14} />
          </button>
          <div
            className={`absolute left-0 top-full mt-1 w-48 bg-white rounded-lg shadow-lg border border-outline-variant flex-col z-50 py-1 ${viewModeDropdownOpen ? "flex" : "hidden"}`}
            data-oid="view-mode-menu">
            <button
              onClick={() => setPreviewMode("markdown")}
              className={`flex items-center gap-2 text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface ${previewMode === "markdown" ? "font-bold text-primary" : ""}`}
              data-oid="view-mode-markdown">
              <FileCode size={16} className="text-primary flex-shrink-0" />
              Markdown
            </button>
            <button
              onClick={() => {
                setPreviewMode("xlsxBasic");
                if (!job?.xlsx_basic_converted) {
                  convertOnly("xlsx_basic");
                }
              }}
              className={`flex items-center gap-2 text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface ${previewMode === "xlsxBasic" ? "font-bold text-primary" : ""}`}
              data-oid="view-mode-xlsx-basic">
              <FileSpreadsheet size={16} className="text-primary flex-shrink-0" />
              {t("page:result.excel")}
            </button>
            {(job?.xlsx_advanced_converted || xlsxAdvancedPolling) &&
            <button
              onClick={() => setPreviewMode("xlsxAdvanced")}
              className={`flex items-center gap-2 text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface ${previewMode === "xlsxAdvanced" ? "font-bold text-primary" : ""}`}
              data-oid="view-mode-xlsx-advanced">
              <FileSpreadsheet size={16} className="text-primary flex-shrink-0" />
              Excel Advanced
            </button>
            }
            <div className="h-px bg-outline-variant my-1" />
            <button
              onClick={() => setPreviewMode("flow")}
              className={`flex items-center gap-2 text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface ${previewMode === "flow" ? "font-bold text-primary" : ""}`}
              data-oid="view-mode-flow">
              <Workflow size={16} className="text-primary flex-shrink-0" />
              {t("page:result.flow")}
            </button>
          </div>
        </div>
        }

          <div className="flex items-center gap-2" data-oid=":tdat.:">
          {job?.status === "done" && previewMode === "markdown" && markdownSaveMessage &&
          <span className="text-sm text-on-surface-variant font-medium hidden sm:inline" data-oid="markdown-save-msg">
            {markdownSaveMessage}
          </span>
          }
          {/* [Flow: 모바일에서는 패널 토글 대신 탭 전환을 사용하므로 숨김] */}
          {job?.status === "done" && !isMobile &&
          <button
            onClick={() => setSidebarOpen((v) => !v)}
            title={sidebarOpen ? t("page:result.hideSidebar") : t("page:result.showSidebar")}
            className="flex items-center gap-1.5 px-3 py-2 bg-surface-container-high text-on-surface rounded-lg font-medium hover:bg-surface-container-high/80 transition-colors border border-outline-variant shrink-0"
            data-oid="g85z5vd">
              {sidebarOpen ?
            <PanelLeftClose size={16} data-oid="tn5ebf8" /> :
            <PanelLeft size={16} data-oid="iknpeoy" />
            }
            </button>
          }
          {job?.status === "done" && !needsPagedMode(job) && !isMobile &&
          <button
            onClick={() => setRightPanelOpen((v) => !v)}
            title={rightPanelOpen ? t("page:result.hideResultPanel") : t("page:result.showResultPanel")}
            className="flex items-center gap-1.5 px-3 py-2 bg-surface-container-high text-on-surface rounded-lg font-medium hover:bg-surface-container-high/80 transition-colors border border-outline-variant shrink-0"
            data-oid="result-right-panel-toggle">
              {rightPanelOpen ?
            <PanelRightClose size={16} data-oid="result-right-panel-close-icon" /> :
            <PanelRight size={16} data-oid="result-right-panel-open-icon" />
            }
            </button>
          }
          {job?.status === "done" &&
          <>
              <div
                className="relative group shrink-0"
                onMouseEnter={() => openDropdown(setDownloadDropdownOpen, downloadDropdownTimerRef)}
                onMouseLeave={() => closeDropdown(setDownloadDropdownOpen, downloadDropdownTimerRef)}
                data-oid="download-group">
                <button
                  className="flex items-center justify-center w-10 h-10 bg-primary text-white rounded-lg font-bold hover:opacity-90 transition-colors shadow-sm"
                  data-oid="download-group-btn"
                  aria-label={t("page:result.download")}>
                  <FileDown size={20} data-oid="download-icon" />
                </button>
                <div
                className={`absolute right-0 top-full mt-1 w-64 bg-white rounded-lg shadow-lg border border-outline-variant flex-col z-50 py-1 ${downloadDropdownOpen ? "flex" : "hidden"}`}
                data-oid="download-dropdown">

                  <button
                  onClick={() => convertAndDownload("xlsx_basic")}
                  disabled={converting}
                  className="flex items-center gap-2 text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
                  data-oid="xlsx-basic-btn">
                    <FileSpreadsheet size={16} className="text-primary flex-shrink-0" />
                    {job.xlsx_basic_converted ?
                  t("page:result.xlsxBasicDownload") :
                  t("page:result.xlsxBasic", { cost: xlsxBasicUnits.toLocaleString() })}
                  </button>
                  <button
                  onClick={() => startXlsxAdvanced()}
                  disabled={converting || xlsxAdvancedPolling}
                  className="flex items-center gap-2 text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
                  data-oid="xlsx-advanced-btn">
                    <FileSpreadsheet size={16} className="text-primary flex-shrink-0" />
                    {xlsxAdvancedPolling ?
                  t("page:result.xlsxAdvancedProcessing") :
                  job.xlsx_advanced_converted ?
                  t("page:result.xlsxAdvancedDownload") :
                  t("page:result.xlsxAdvanced", { cost: xlsxAdvancedUnits.toLocaleString() })}
                  </button>
                  <div className="h-px bg-outline-variant my-1" />
                  <button
                  onClick={() => convertAndDownload("docx")}
                  disabled={converting}
                  className="flex items-center gap-2 text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
                  data-oid="docx-btn">
                    <FileText size={16} className="text-primary flex-shrink-0" />
                    {t("page:result.word")}
                  </button>
                  <button
                  onClick={() => download("md")}
                  className="flex items-center gap-2 text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
                  data-oid="md-btn">
                    <FileCode size={16} className="text-primary flex-shrink-0" />
                    {t("page:result.md")}
                  </button>
                </div>
              </div>

              {job?.xlsx_advanced_status === "error" && job?.xlsx_advanced_refundable &&
              <div className="flex items-center gap-2 px-3 py-1.5 bg-red-50 text-red-700 rounded-lg text-sm border border-red-200" data-oid="xlsx-advanced-error">
                <AlertTriangle size={14} data-oid="alert-icon" />
                <span>{t("page:result.xlsxAdvancedFailed")}</span>
                <button
                  onClick={() => handleXlsxAdvancedAction("retry")}
                  disabled={converting}
                  className="flex items-center gap-1 px-2 py-1 bg-white rounded border border-red-200 hover:bg-red-100 transition-colors"
                  data-oid="retry-btn">
                  <RefreshCw size={14} data-oid="retry-icon" />
                  {t("page:result.retry")}
                </button>
                <button
                  onClick={() => handleXlsxAdvancedAction("refund")}
                  disabled={converting}
                  className="px-2 py-1 bg-white rounded border border-red-200 hover:bg-red-100 transition-colors"
                  data-oid="refund-btn">
                  {t("page:result.refund")}
                </button>
              </div>
              }
            </>
          }
        </div>
        </div>
      </header>

      {error &&
      <div
        className="bg-red-50 text-red-700 px-4 py-1.5 text-sm flex items-center gap-2 border-b border-red-200"
        data-oid="dj7ay27">

          <XCircle size={16} data-oid="872vq_g" />
          {error}
        </div>
      }

      {loading && (!job || job?.status === "done") &&
      <SkeletonPageResult data-oid="bv9f2yo" />
      }

      {job && job.status !== "done" && job.status !== "error" &&
        <PoetryProgress
          pct={pct}
          statusLabel={statusLabel(job.status)}
          progressText={`${pct}%`}
        />
      }

      {job?.status === "error" &&
      <div
        className="flex-1 flex flex-col items-center justify-center p-6 gap-4"
        data-oid=".1e5ij:">

          {job?.refundable &&
          <div className="flex items-center gap-2 px-4 py-2 bg-red-50 text-red-700 rounded-lg text-sm border border-red-200" data-oid="job-action-error">
            <AlertTriangle size={14} data-oid="job-alert-icon" />
            <span>{t("page:result.parseFailed")}</span>
            <button
              onClick={() => setJobActionModal(true)}
              disabled={converting}
              className="flex items-center gap-1 px-2 py-1 bg-white rounded border border-red-200 hover:bg-red-100 transition-colors"
              data-oid="job-action-btn">
              <RefreshCw size={14} data-oid="job-action-icon" />
              {t("page:result.retryOrRefund")}
            </button>
          </div>
          }
          <pre
          className="bg-red-50 text-red-700 text-xs p-4 rounded-lg whitespace-pre-wrap max-w-3xl"
          data-oid="vgn48fw">

            {job.error_log || t("page:result.unknownError")}
          </pre>
        </div>
      }

      {job?.status === "done" && job.error_log && job.error_log.includes("350mm") &&
      <div className="mx-4 mt-2 p-3 bg-amber-50 border border-amber-200 rounded-lg text-amber-800 text-sm" data-oid="unparsable-warn">
        {job.error_log}
      </div>
      }

      {job?.status === "done" && !loading && needsPagedMode(job) &&
      <PagedResultViewer
        ref={pagedViewerRef}
        jobId={jobId}
        pages={pages}
        sourceUrl={sourceUrl}
        sourceType={sourceType}
        sourceFiles={sourceFiles}
        imageUrls={imageUrls}
        onSaveAnnotations={handleSaveAnnotations}
        onUpload={() => setUploadPopupOpen(true)}
        data-oid="x.dznfp" />

      }

      {job?.status === "done" && !loading && !needsPagedMode(job) &&
      <div className="flex-1 flex flex-col overflow-hidden min-h-0" data-oid="ww-27ni">
          {previewMode !== "markdown" && xlsxAdvancedPolling &&
          <div className="px-4 py-2 bg-blue-50 text-blue-700 text-sm border-b border-blue-200 flex items-center gap-2 flex-shrink-0" data-oid="advanced-progress">
            <Loader2 className="animate-spin" size={16} data-oid="advanced-spinner" />
            {t("page:result.xlsxAdvancedProcessing")}
          </div>
          }

          {previewMode === "xlsxAdvanced" && (job?.xlsx_advanced_status === "done" || job?.xlsx_advanced_status === "error") && job?.xlsx_advanced_recovery_notes?.length > 0 &&
          <div className="px-4 py-2 bg-amber-50 text-amber-800 text-sm border-b border-amber-200 flex-shrink-0" data-oid="recovery-notes">
            <strong>{t("page:result.recoveryNotes")}</strong>
            <ul className="list-disc ml-5 mt-1">
              {job.xlsx_advanced_recovery_notes.map((note, idx) => (
                <li key={idx}>
                  {t("page:result.recoveryNotePage", { page: note.page })}: {note.reason} ({t("page:result.recoveryNoteCell", { cell: note.cell })})
                </li>
              ))}
            </ul>
          </div>
          }

          {renderResultArea()}
        </div>
      }

      {jobActionModal &&
      <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" data-oid="job-modal-overlay">
        <div className="bg-white rounded-lg shadow-lg border border-outline-variant p-6 w-full max-w-sm" data-oid="job-modal">
          <h3 className="font-headline-md text-headline-md font-bold text-on-surface mb-2" data-oid="job-modal-title">
            {t("page:result.retryOrRefund")}
          </h3>
          <p className="text-sm text-on-surface-variant mb-6" data-oid="job-modal-desc">
            {t("page:result.parseFailed")}
          </p>
          <div className="flex justify-end gap-2" data-oid="job-modal-actions">
            <button
              onClick={() => setJobActionModal(false)}
              disabled={converting}
              className="px-4 py-2 rounded-lg border border-outline-variant text-on-surface hover:bg-surface-container-high transition-colors"
              data-oid="job-modal-cancel">
              {t("common:actions.cancel")}
            </button>
            <button
              onClick={() => handleJobAction("refund")}
              disabled={converting}
              className="px-4 py-2 rounded-lg border border-red-200 text-red-700 bg-red-50 hover:bg-red-100 transition-colors"
              data-oid="job-modal-refund">
              {t("page:result.refund")}
            </button>
            <button
              onClick={() => handleJobAction("retry")}
              disabled={converting}
              className="flex items-center gap-1 px-4 py-2 rounded-lg bg-primary text-white hover:opacity-90 transition-colors"
              data-oid="job-modal-retry">
              {converting ?
              <Loader2 size={16} className="animate-spin" data-oid="job-modal-spinner" /> :
              <RefreshCw size={16} data-oid="job-modal-retry-icon" />}
              {t("page:result.retry")}
            </button>
          </div>
        </div>
      </div>
      }

      <UploadPopup
        open={uploadPopupOpen}
        onClose={() => setUploadPopupOpen(false)}
        jobId={jobId}
        onProgress={setUploadProgress}
        onComplete={() => {
          setUploadPopupOpen(false);
          setUploadProgress({ current: 0, total: 0, percent: 0, fileName: "" });
          // 업로드 완료 시 job을 새로고침하여 추가된 파일 + 증분 변환 폴링 시작
          loadJob();
        }}
        data-oid="result-upload-popup"
      />

      {deleteSourceFileModal &&
      <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" data-oid="delete-source-modal-overlay">
        <div className="bg-white rounded-lg shadow-lg border border-outline-variant p-6 w-full max-w-sm" data-oid="delete-source-modal">
          {(() => {
            const isCancellable = pendingDeleteFile?.status === "processing" || pendingDeleteFile?.status === "error";
            return (
              <>
                <h3 className="font-headline-md text-headline-md font-bold text-on-surface mb-2" data-oid="delete-source-modal-title">
                  {isCancellable
                    ? t("page:result.annotateCancelTitle")
                    : t("page:result.deleteSourceFileTitle")}
                </h3>
                <p className="text-sm text-on-surface-variant mb-6" data-oid="delete-source-modal-desc">
                  {isCancellable
                    ? t("page:result.annotateCancelDesc", { filename: pendingDeleteFile?.name || "" })
                    : t("page:result.deleteSourceFileDesc", { filename: pendingDeleteFile?.name || "" })}
                </p>
                <div className="flex justify-end gap-2" data-oid="delete-source-modal-actions">
                  <button
                    onClick={closeDeleteSourceFileModal}
                    disabled={converting}
                    className="px-4 py-2 rounded-lg border border-outline-variant text-on-surface hover:bg-surface-container-high transition-colors"
                    data-oid="delete-source-modal-cancel">
                    {t("common:actions.cancel")}
                  </button>
                  <button
                    onClick={confirmDeleteSourceFile}
                    disabled={converting}
                    className="flex items-center gap-1 px-4 py-2 rounded-lg bg-error text-white hover:opacity-90 transition-colors"
                    data-oid="delete-source-modal-confirm">
                    {converting ?
                    <Loader2 size={16} className="animate-spin" data-oid="delete-source-modal-spinner" /> :
                    <Trash2 size={16} data-oid="delete-source-modal-icon" />}
                    {isCancellable
                      ? t("page:result.annotateCancel")
                      : t("common:delete")}
                  </button>
                </div>
              </>
            );
          })()}
        </div>
      </div>
      }

      {job?.status === "done" && (
        <>
          <AgentChatModal
            isOpen={chatOpen}
            onClose={() => setChatOpen(false)}
            context={{
              jobId,
              sourceType,
              currentPage,
              selectedFileIndex,
              activeEditor: previewMode,
              sandboxId,
            }}
            onRunningCountChange={setAgentRunningCount}
            onAgentComplete={() => loadJobRef.current()}
            onFlowDrawingsUpdate={(data) => {
              // [Flow: 에이전트가 save_flow_drawings 완료 → FlowViewer에 즉시 반영]
              flowViewerApiRef.current?.updateFromAgent?.(data);
            }}
          />
          {/* 샌드박스 파일 브라우저 (에이전트가 sandbox 를 생성한 경우 표시) */}
          {sandboxId && sandboxPanelOpen && (
            <div className="fixed bottom-20 right-4 w-96 h-80 z-40 shadow-2xl">
              <SandboxBrowser sandboxId={sandboxId} />
              <button
                onClick={() => setSandboxPanelOpen(false)}
                className="absolute top-2 right-2 p-1 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700"
              >
                <XCircle className="w-4 h-4" />
              </button>
            </div>
          )}
          {/* 샌드박스 패널 토글 버튼 (sandbox 가 있을 때만 표시) */}
          {sandboxId && !sandboxPanelOpen && (
            <button
              onClick={() => setSandboxPanelOpen(true)}
              className="fixed bottom-20 right-4 z-40 px-3 py-2 rounded-lg bg-blue-600 text-white shadow-lg hover:bg-blue-700 flex items-center gap-2 text-sm"
            >
              <Box className="w-4 h-4" />
              {t("page:sandbox.fileBrowser")}
            </button>
          )}
        </>
      )}
    </div>);

}