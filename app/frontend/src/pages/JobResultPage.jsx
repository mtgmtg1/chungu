// [Flow: Step 1 (job ID로 진입) -> Step 2 (작업 상태 폴링) -> Step 3 (완료 시 preview API 호출) -> Step 4 (100페이지 초과 시 페이지 단위 뷰어, 이하 시 PDF.js + 전체 에디터) -> Step 5 (마크다운/Office/CSV 다운로드)]
import { memo, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  Download,
  FileSpreadsheet,
  Loader2,
  PanelLeft,
  PanelLeftClose,
  RefreshCw,
  Save,
  XCircle } from
"lucide-react";
import SourcePanel from "../components/SourcePanel.jsx";
import PoetryProgress from "../components/PoetryProgress.jsx";
import PagedResultViewer from "../components/PagedResultViewer.jsx";
import SimpleEditor from "../components/SimpleEditor.jsx";
import MarkdownPreview from "../components/MarkdownPreview.jsx";
import SpreadsheetEditor from "../components/SpreadsheetEditor.jsx";
import { api } from "../api.js";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { SkeletonPageResult } from "../components/Skeleton.jsx";
import { getDisplayProgress } from "../utils/progress.js";

function downloadByUrl(url, filename) {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

/**
 * [Flow: Step 1 (editMode 상태 확인) -> Step 2 (보기/편집 토글 버튼 렌더링) -> Step 3 (onToggle 콜백 호출)]
 * @param {object} props
 * @param {boolean} props.editMode
 * @param {function} props.onToggle
 * @param {function} props.t
 */
const MarkdownViewToolbar = memo(function MarkdownViewToolbar({ editMode, onToggle, t }) {
  return (
    <div className="flex items-center justify-end px-4 py-2 border-b border-outline-variant bg-surface flex-shrink-0 gap-2">
      <span className="text-xs text-on-surface-variant">
        {editMode ? t("page:result.editMode") : t("page:result.viewMode")}
      </span>
      <button
        onClick={onToggle}
        className={`text-xs px-3 py-1.5 rounded font-medium border transition-colors ${
          editMode
            ? "bg-primary text-white border-primary"
            : "bg-surface text-on-surface border-outline-variant hover:bg-surface-container-high"
        }`}
      >
        {editMode ? t("page:result.view") : t("page:result.edit")}
      </button>
    </div>
  );
});

export default function JobResultPage() {
  const { jobId } = useParams();
  const { t } = useTranslation();
  const statusLabel = (status) => t(`common:status.${status}`) || status;
  const [job, setJob] = useState(null);
  const [markdown, setMarkdown] = useState("");
  const [sourceUrl, setSourceUrl] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [converting, setConverting] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");
  const [pages, setPages] = useState([]);
  const [sourceType, setSourceType] = useState(null);
  const [imageUrls, setImageUrls] = useState([]);
  const [sourceFiles, setSourceFiles] = useState([]);
  const [fileMarkdowns, setFileMarkdowns] = useState([]);
  const [selectedFileIndex, setSelectedFileIndex] = useState(0);
  const [currentPdfPage, setCurrentPdfPage] = useState(1);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [now, setNow] = useState(Date.now());
  const pollRef = useRef(null);
  const editorRef = useRef(null);
  const previewRef = useRef(null);
  const pagedViewerRef = useRef(null);

  const [previewMode, setPreviewMode] = useState("markdown"); // "markdown" | "xlsxBasic" | "xlsxAdvanced"
  const [editMode, setEditMode] = useState(true);
  const [basicUrl, setBasicUrl] = useState(null);
  const [advancedUrl, setAdvancedUrl] = useState(null);
  const [xlsxAdvancedPolling, setXlsxAdvancedPolling] = useState(false);
  const [jobActionModal, setJobActionModal] = useState(false);

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

  useEffect(() => {
    setCurrentPdfPage(1);
  }, [selectedFileIndex]);

  // [Flow: Step 1 (currentPdfPage 변경 감지) -> Step 2 (에디터/프리뷰에 scrollToPage 호출) -> Step 3 (해당 페이지 마커로 스크롤)]
  useEffect(() => {
    if (needsPagedMode(job)) return;
    if (editMode && editorRef.current?.scrollToPage) {
      editorRef.current.scrollToPage(currentPdfPage);
    } else if (!editMode && previewRef.current?.scrollToPage) {
      previewRef.current.scrollToPage(currentPdfPage);
    }
  }, [currentPdfPage, editMode, job]);

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

  async function loadPreview() {
    try {
      const preview = await api.previewJob(jobId);
      setSourceUrl(preview.source_url);
      setSourceType(preview.source_type);
      setImageUrls(preview.image_urls || []);
      setSourceFiles(preview.source_files || []);
      const fms = (preview.source_files || []).map((f) => f.result_markdown || "");
      setFileMarkdowns(fms);
      setSelectedFileIndex(0);
      // [Flow: Step 1 (DB의 total_pages/total_files 확인) -> Step 2 (폴백: 마크다운의 last_page 확인) -> Step 3 (둘 중 하나라도 임계값 초과 시 페이징 모드)]
      const usePaged = needsPagedMode(job) || (preview.last_page || 0) > PAGE_THRESHOLD;
      if (usePaged) {
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

  async function saveMarkdown() {
    setSaving(true);
    setSaveMessage("");
    try {
      if (pages.length > 0 && pagedViewerRef.current) {
        // 100페이지 초과 페이징 모드: PagedResultViewer가 현재 페이지 저장
        await pagedViewerRef.current.save();
      } else {
        if (!editorRef.current) return;
        const updated = editorRef.current.getMarkdown();
        if (hasFileMarkdowns) {
          const next = [...fileMarkdowns];
          next[selectedFileIndex] = updated;
          setFileMarkdowns(next);
          await api.saveResultFileMarkdowns(jobId, next);
        } else {
          await api.saveResultMarkdown(jobId, updated);
          setMarkdown(updated);
        }
      }
      setSaveMessage(t("page:result.saved"));
      setTimeout(() => setSaveMessage(""), 2000);
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
    } finally {
      setSaving(false);
    }
  }

  async function download(type) {
    const { download_url } = await api.downloadJob(jobId, type);
    const base = job?.filename ?
    job.filename.replace(/\.[^/.]+$/, "") :
    "result";
    const ext = type === "md" ? "md" : type.startsWith("xlsx") ? "xlsx" : type;
    downloadByUrl(download_url, `${base}.${ext}`);
  }

  async function convertAndDownload(format) {
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

  const xlsxBasicCost = job ? (job.total_pages || job.total_files || 1) * 1 : 0;
  const xlsxAdvancedCost = job ? (job.total_pages || job.total_files || 1) * 3 : 0;

  // [Flow: Step 1 (마크다운 텍스트 확인) -> Step 2 (테이블 구분선 패턴 검색) -> Step 3 (표 존재 여부 반환)]
  function hasMarkdownTable(text) {
    if (!text) return false;
    const lines = text.split("\n");
    for (let i = 0; i < lines.length - 1; i++) {
      const current = lines[i].trim();
      const next = lines[i + 1].trim();
      if (current.startsWith("|") && current.endsWith("|") &&
          next.startsWith("|") && next.endsWith("|") && next.includes("-")) {
        return true;
      }
    }
    return false;
  }

  const showXlsxBasicTab = job?.xlsx_basic_converted || hasMarkdownTable(displayMarkdown);

  const pct = getDisplayProgress(job, 80, now);

  return (
    <div
      className="h-screen bg-background flex flex-col"
      data-oid="vl.tj_r">

      <header
        className="h-14 border-b border-outline-variant bg-surface flex items-center justify-between px-4 flex-shrink-0"
        data-oid="kxse7f.">

        <div className="flex items-center gap-4" data-oid="jz8kj2e">
          <Link
            to="/jobs"
            className="flex items-center gap-2 text-on-surface-variant hover:text-primary transition-colors"
            data-oid="homj3ye">

            <ArrowLeft size={18} data-oid="pmqivjc" />
            <span className="font-medium" data-oid="efc.i4.">
              {t("common:jobs")}
            </span>
          </Link>
          <div className="h-4 w-px bg-outline-variant" data-oid="-vnoo-."></div>
          <h1
            className="font-headline-md text-headline-md font-bold text-on-surface"
            data-oid="aaxa04a">

            {job?.filename || jobId}
          </h1>
          {job?.status === "done" &&
          <span
            className="px-3 py-1 bg-green-100 text-green-700 text-xs font-bold rounded-full flex items-center gap-1.5 border border-green-200"
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
            className="px-3 py-1 bg-red-100 text-red-700 text-xs font-bold rounded-full flex items-center gap-1.5 border border-red-200"
            data-oid="uf3gdos">

              <XCircle size={12} data-oid="vcowgtj" />
              {t("page:result.error")}
            </span>
          }
          {job?.status === "retrying" &&
          <span
            className="px-3 py-1 bg-amber-100 text-amber-700 text-xs font-bold rounded-full flex items-center gap-1.5 border border-amber-200"
            data-oid="retrying-badge">

              <RefreshCw size={12} className="animate-spin" data-oid="retrying-icon" />
              {t("page:result.retrying")}
            </span>
          }
        </div>
        <div className="flex items-center gap-2" data-oid=":tdat.:">
          {job?.status === "done" && (sourceUrl || sourceFiles.length > 0) &&
          <button
            onClick={() => setSidebarOpen((v) => !v)}
            className="flex items-center gap-1.5 px-3 py-2 bg-surface-container-high text-on-surface rounded-lg font-medium hover:bg-surface-container-high/80 transition-colors border border-outline-variant"
            data-oid="g85z5vd">
              {sidebarOpen ?
            <PanelLeftClose size={16} data-oid="tn5ebf8" /> :
            <PanelLeft size={16} data-oid="iknpeoy" />
            }
            </button>
          }
          {job?.status === "done" &&
          <>
              <div className="relative group" data-oid="excel-group">
                <button
                  className="flex items-center gap-1.5 px-3 py-2 bg-primary text-white rounded-lg font-bold hover:opacity-90 transition-colors shadow-sm"
                  data-oid="excel-group-btn">
                  <FileSpreadsheet size={16} data-oid="excel-icon" />
                  {t("page:result.excel")}
                </button>
                <div
                className="absolute right-0 top-full mt-1 w-56 bg-white rounded-lg shadow-lg border border-outline-variant hidden group-hover:flex flex-col z-50 py-1"
                data-oid="excel-dropdown">

                  <button
                  onClick={() => convertAndDownload("xlsx_basic")}
                  disabled={converting}
                  className="text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
                  data-oid="xlsx-basic-btn">

                    {job.xlsx_basic_converted ?
                  t("page:result.xlsxBasicDownload") :
                  t("page:result.xlsxBasic", { cost: xlsxBasicCost.toLocaleString() })}
                  </button>
                  <button
                  onClick={() => startXlsxAdvanced()}
                  disabled={converting || xlsxAdvancedPolling}
                  className="text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
                  data-oid="xlsx-advanced-btn">

                    {xlsxAdvancedPolling ?
                  t("page:result.xlsxAdvancedProcessing") :
                  job.xlsx_advanced_converted ?
                  t("page:result.xlsxAdvancedDownload") :
                  t("page:result.xlsxAdvanced", { cost: xlsxAdvancedCost.toLocaleString() })}
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

              <div className="relative group" data-oid="office-group">
                <button
                  className="flex items-center gap-1.5 px-3 py-2 bg-surface-container-high text-on-surface rounded-lg font-medium hover:bg-surface-container-high/80 transition-colors border border-outline-variant"
                  data-oid="office-group-btn">
                  <Download size={16} data-oid="office-icon" />
                  {t("page:result.office")}
                </button>
                <div
                className="absolute right-0 top-full mt-1 w-48 bg-white rounded-lg shadow-lg border border-outline-variant hidden group-hover:flex flex-col z-50 py-1"
                data-oid="office-dropdown">

                  <button
                  onClick={() => convertAndDownload("docx")}
                  disabled={converting}
                  className="text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
                  data-oid="docx-btn">

                    {t("page:result.word")}
                  </button>
                  <button
                  onClick={() => download("md")}
                  className="text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
                  data-oid="md-btn">

                    {t("page:result.md")}
                  </button>
                </div>
              </div>
              <button
                onClick={saveMarkdown}
                disabled={saving}
                className="flex items-center gap-1.5 px-3 py-2 bg-green-600 text-white rounded-lg font-bold hover:opacity-90 transition-colors shadow-sm disabled:opacity-50"
                data-oid="0y62kdm">
                {saving ?
              <Loader2
                size={16}
                className="animate-spin"
                data-oid="zubuhoj" /> :
              <Save size={16} data-oid="9q9sxwr" />
              }
                {t("page:result.save")}
              </button>
            </>
          }
        </div>
      </header>

      {saveMessage &&
      <div
        className="bg-green-50 text-green-700 px-4 py-1.5 text-sm flex items-center gap-2 border-b border-green-200"
        data-oid="uhtevhw">

          <Check size={16} data-oid="jze93xf" />
          {saveMessage}
        </div>
      }

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
        data-oid="x.dznfp" />

      }

      {job?.status === "done" && !loading && !needsPagedMode(job) &&
      <div className="flex-1 flex flex-col overflow-hidden min-h-0" data-oid="ww-27ni">
          {(showXlsxBasicTab || job?.xlsx_advanced_converted || xlsxAdvancedPolling) &&
          <div className="flex items-center gap-2 px-4 py-2 border-b border-outline-variant bg-surface flex-shrink-0" data-oid="preview-tabs">
            <button
              onClick={() => setPreviewMode("markdown")}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${previewMode === "markdown" ? "bg-primary text-white" : "text-on-surface hover:bg-surface-container-high"}`}
              data-oid="tab-markdown">
              Markdown
            </button>
            {showXlsxBasicTab &&
            <button
              onClick={() => {
                setPreviewMode("xlsxBasic");
                if (!job?.xlsx_basic_converted) {
                  convertOnly("xlsx_basic");
                }
              }}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${previewMode === "xlsxBasic" ? "bg-primary text-white" : "text-on-surface hover:bg-surface-container-high"}`}
              data-oid="tab-xlsx-basic">
              Excel Basic
            </button>
            }
            {(job?.xlsx_advanced_converted || xlsxAdvancedPolling) &&
            <button
              onClick={() => setPreviewMode("xlsxAdvanced")}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${previewMode === "xlsxAdvanced" ? "bg-primary text-white" : "text-on-surface hover:bg-surface-container-high"}`}
              data-oid="tab-xlsx-advanced">
              Excel Advanced
            </button>
            }
          </div>
          }

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

          {previewMode === "markdown" && (sidebarOpen && (sourceUrl || sourceFiles.length > 0) ?
        <PanelGroup
          direction="horizontal"
          className="flex-1 flex min-h-0"
          data-oid="wn6pn3w">

              <Panel
            defaultSize={30}
            minSize={20}
            maxSize={60}
            className="flex flex-col min-h-0 overflow-hidden"
            data-oid="8gj26he">

                <SourcePanel
                  sourceFiles={sourceFiles}
                  sourceUrl={sourceUrl}
                  sourceType={sourceType}
                  imageUrls={imageUrls}
                  filename={job?.filename}
                  currentPage={currentPdfPage}
                  onPageChange={setCurrentPdfPage}
                  selectedFileIndex={selectedFileIndex}
                  onFileSelect={setSelectedFileIndex}
                  data-oid="rp.07za" />

              </Panel>
              <PanelResizeHandle
            className="w-2 bg-outline-variant/50 hover:bg-primary transition-colors cursor-col-resize"
            data-oid="j-sm.n3" />


              <Panel className="flex flex-col min-h-0" data-oid="2xixpf2">
                <div
              className="flex flex-col h-full bg-white overflow-hidden"
              data-oid="1pwia81">

                  <MarkdownViewToolbar
                editMode={editMode}
                onToggle={() => setEditMode((v) => !v)}
                t={t}
                data-oid="markdown-view-toolbar" />

                  {editMode ? (
                <SimpleEditor
                  ref={editorRef}
                  markdown={displayMarkdown}
                  editable
                  data-oid="xzqyv5." />
              ) : (
                <MarkdownPreview
                  ref={previewRef}
                  markdown={displayMarkdown}
                  data-oid="markdown-preview" />
              )}

                </div>
              </Panel>
            </PanelGroup> :

        <div
          className="flex-1 flex flex-col bg-white overflow-hidden min-h-0"
          data-oid="w605w2j">

              <MarkdownViewToolbar
            editMode={editMode}
            onToggle={() => setEditMode((v) => !v)}
            t={t}
            data-oid="markdown-view-toolbar" />

              {editMode ? (
            <SimpleEditor
              ref={editorRef}
              markdown={displayMarkdown}
              editable
              data-oid="r9i48wh" />
          ) : (
            <MarkdownPreview
              ref={previewRef}
              markdown={displayMarkdown}
              data-oid="markdown-preview" />
          )}

            </div>
        )}

          {previewMode === "xlsxBasic" &&
          <div className="flex-1 min-h-0 overflow-hidden" data-oid="xlsx-basic-preview">
            <SpreadsheetEditor downloadUrl={basicUrl} jobId={jobId} fileName={job?.original_filename || "result.xlsx"} />
          </div>
          }
          {previewMode === "xlsxAdvanced" &&
          <div className="flex-1 min-h-0 overflow-hidden" data-oid="xlsx-advanced-preview">
            <SpreadsheetEditor downloadUrl={advancedUrl} jobId={jobId} fileName={job?.original_filename || "result.xlsx"} />
          </div>
          }
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
    </div>);

}