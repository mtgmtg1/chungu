// [Flow: Step 1 (job ID로 진입) -> Step 2 (작업 상태 폴링) -> Step 3 (완료 시 preview API 호출) -> Step 4 (100페이지 초과 시 페이지 단위 뷰어, 이하 시 PDF.js + 전체 에디터) -> Step 5 (마크다운/Office/CSV 다운로드)]
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  Check,
  Download,
  FileText,
  Loader2,
  PanelLeft,
  PanelLeftClose,
  Save,
  Table2,
  XCircle } from
"lucide-react";
import SourcePanel from "../components/SourcePanel.jsx";
import PoetryProgress from "../components/PoetryProgress.jsx";
import PagedResultViewer from "../components/PagedResultViewer.jsx";
import SimpleEditor from "../components/SimpleEditor.jsx";
import { api } from "../api.js";
import i18n from "../i18n.js";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { SkeletonPageResult } from "../components/Skeleton.jsx";

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
  const pollRef = useRef(null);
  const editorRef = useRef(null);

  const PAGE_THRESHOLD = 100;
  const needsPagedMode = (j) =>
  (j?.total_pages || 0) > PAGE_THRESHOLD ||
  (j?.total_files || 0) > PAGE_THRESHOLD;

  const hasFileMarkdowns = fileMarkdowns.length > 1;
  const displayMarkdown = hasFileMarkdowns ? fileMarkdowns[selectedFileIndex] : markdown;

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

  async function loadJob() {
    try {
      const data = await api.getJob(jobId);
      setJob(data);
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
      setError(e.message || t("page:errors.loadFailed"));
      setLoading(false);
    }
  }

  function startPolling() {
    clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const data = await api.getJob(jobId);
        setJob(data);
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
      if (needsPagedMode(job)) {
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
    if (!editorRef.current) return;
    const updated = editorRef.current.getMarkdown();
    setSaving(true);
    setSaveMessage("");
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
    const ext = type === "md" ? "md" : type;
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
      downloadByUrl(download_url, `${base}.${format}`);
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
    } finally {
      setConverting(false);
    }
  }

  const xlsxCost = job ? (job.total_pages || job.total_files || 1) * 3 : 0;

  const pct =
  job && (job.total_pages || job.total_files) ?
  Math.round(
    (job.done_pages || job.done_files || 0) / (
    job.total_pages || job.total_files || 1) *
    100
  ) :
  0;

  return (
    <div
      className="h-screen bg-background flex flex-col"
      data-oid="vl.tj_r">

      <header
        className="h-14 border-b border-outline-variant bg-surface flex items-center justify-between px-4 flex-shrink-0"
        data-oid="kxse7f.">

        <div className="flex items-center gap-4" data-oid="jz8kj2e">
          <Link
            to="/"
            className="flex items-center gap-2 text-on-surface-variant hover:text-primary transition-colors"
            data-oid="homj3ye">

            <ArrowLeft size={18} data-oid="pmqivjc" />
            <span className="font-medium" data-oid="efc.i4.">
              {t("page:result.newConversion")}
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
        </div>
        <div className="flex items-center gap-2" data-oid=":tdat.:">
          {job?.status === "done" && (sourceUrl || sourceFiles.length > 0) &&
          <button
            onClick={() => setSidebarOpen((v) => !v)}
            title={
            sidebarOpen ?
            t("page:result.hideSidebar") :
            t("page:result.showSidebar")
            }
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
              <button
              onClick={() => download("md")}
              className="flex items-center gap-1.5 px-3 py-2 bg-surface-container-high text-on-surface rounded-lg font-medium hover:bg-surface-container-high/80 transition-colors border border-outline-variant"
              data-oid="yirbet1">

                <FileText size={16} data-oid="go.4duu" />
                {t("page:result.md")}
              </button>
              <button
              onClick={() => {
                if (!job.xlsx_converted) {
                  if (
                  !window.confirm(
                    t("page:result.csvConfirm", {
                      cost: xlsxCost.toLocaleString()
                    })
                  ))

                  return;
                }
                download("csv");
              }}
              className="flex items-center gap-1.5 px-3 py-2 bg-surface-container-high text-on-surface rounded-lg font-medium hover:bg-surface-container-high/80 transition-colors border border-outline-variant"
              data-oid="00coi-x">

                <Table2 size={16} data-oid="0yo:c7a" />
                {job.xlsx_converted ?
              t("page:result.csv") :
              t("page:result.csvCost", {
                cost: xlsxCost.toLocaleString()
              })}
              </button>
              <div className="relative group" data-oid="e5fsbni">
                <button
                className="flex items-center gap-1.5 px-3 py-2 bg-primary text-white rounded-lg font-bold hover:opacity-90 transition-colors shadow-sm"
                data-oid="du_8s4p">

                  <Download size={16} data-oid="d46ozw7" />
                  {t("page:result.office")}
                </button>
                <div
                className="absolute right-0 top-full mt-1 w-48 bg-white rounded-lg shadow-lg border border-outline-variant hidden group-hover:flex flex-col z-50 py-1"
                data-oid="4ia:xlm">

                  <button
                  onClick={() => convertAndDownload("xlsx")}
                  disabled={converting}
                  className="text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
                  data-oid="e_iw.cl">

                    {job.xlsx_converted ?
                  t("page:result.excelDownload") :
                  t("page:result.excel", {
                    cost: xlsxCost.toLocaleString()
                  })}
                  </button>
                  <button
                  onClick={() => convertAndDownload("docx")}
                  disabled={converting}
                  className="text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
                  data-oid="s80vrqg">

                    {t("page:result.word")}
                  </button>
                  <button
                  onClick={() => convertAndDownload("pptx")}
                  disabled={converting}
                  className="text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
                  data-oid="8663wlk">

                    {t("page:result.ppt")}
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

      {loading && !job &&
      <SkeletonPageResult data-oid="bv9f2yo" />
      }

      {job && job.status !== "done" && job.status !== "error" &&
        <PoetryProgress
          pct={pct}
          statusLabel={statusLabel(job.status)}
          progressText={
            job.total_pages ?
              t("page:result.pageProgress", {
                done: job.done_pages || 0,
                total: job.total_pages,
                pct
              }) :
              t("page:result.fileProgress", {
                done: job.done_files || 0,
                total: job.total_files,
                pct
              })
          }
        />
      }

      {job?.status === "error" &&
      <div
        className="flex-1 flex items-center justify-center p-6"
        data-oid=".1e5ij:">

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
        jobId={jobId}
        pages={pages}
        sourceUrl={sourceUrl}
        sourceType={sourceType}
        sourceFiles={sourceFiles}
        imageUrls={imageUrls}
        sidebarOpen={sidebarOpen}
        data-oid="x.dznfp" />

      }

      {job?.status === "done" && !loading && !needsPagedMode(job) &&
      <div className="flex-1 flex overflow-hidden min-h-0" data-oid="ww-27ni">
          {sidebarOpen && (sourceUrl || sourceFiles.length > 0) ?
        <PanelGroup
          direction="horizontal"
          className="flex-1 flex"
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

                  <SimpleEditor
                ref={editorRef}
                markdown={displayMarkdown}
                editable
                data-oid="xzqyv5." />

                </div>
              </Panel>
            </PanelGroup> :

        <div
          className="flex-1 flex flex-col bg-white overflow-hidden min-h-0"
          data-oid="w605w2j">

              <SimpleEditor
            ref={editorRef}
            markdown={displayMarkdown}
            editable
            data-oid="r9i48wh" />

            </div>
        }
        </div>
      }
    </div>);

}