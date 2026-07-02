// [Flow: Step 1 (사용자 확인 + 작업 목록 로드) -> Step 2 (검색/필터 상태) -> Step 3 (테이블 렌더링 + Actions) -> Step 4 (페이지네이션)]
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Eye,
  Download,
  Trash2,
  Loader2,
  ChevronLeft,
  ChevronRight } from
"lucide-react";
import { useAuth } from "../AuthContext.jsx";
import { api } from "../api.js";
import i18n from "../i18n.js";
import SidebarLayout from "../components/SidebarLayout.jsx";
import { SkeletonTable } from "../components/Skeleton.jsx";
import { AnimatedRow } from "../components/AnimatedList.jsx";

function DownloadMenu({ job, fileTypeLabel, download, convertAndDownload, converting, xlsxCost, onMenuItemClick, children }) {
  // [Flow: Step 1 (버튼 위치 추적) -> Step 2 (호버 상태) -> Step 3 (document.body에 Portal로 메뉴 렌더링) -> Step 4 (위치 계산)]
  const { t } = useTranslation();
  const btnRef = useRef(null);
  const menuRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ top: 0, right: 0 });

  function updatePos() {
    if (!btnRef.current) return;
    const rect = btnRef.current.getBoundingClientRect();
    setPos({ top: rect.bottom + window.scrollY + 4, right: window.innerWidth - rect.right - window.scrollX });
  }

  const handleEnter = () => {
    updatePos();
    setOpen(true);
  };

  const handleLeave = () => {
    setOpen(false);
  };

  useEffect(() => {
    if (open) {
      updatePos();
      window.addEventListener("scroll", updatePos, true);
      window.addEventListener("resize", updatePos);
    }
    return () => {
      window.removeEventListener("scroll", updatePos, true);
      window.removeEventListener("resize", updatePos);
    };
  }, [open]);

  const menu = (
    <div
      ref={menuRef}
      className="fixed w-52 bg-white rounded-lg shadow-lg border border-outline-variant flex flex-col z-[99999] py-1"
      style={{ top: pos.top, right: pos.right }}
      onMouseEnter={handleEnter}
      onMouseLeave={handleLeave}
    >
      <button
        onClick={() => { download(job.job_id, "md"); onMenuItemClick?.(); }}
        className="text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
      >
        {t("page:jobs.markdownFree")}
      </button>
      <button
        onClick={() => { download(job.job_id, "csv"); onMenuItemClick?.(); }}
        className="text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
      >
        {t("page:jobs.csvExcel")}
      </button>
      <button
        onClick={() => { convertAndDownload(job.job_id, "xlsx"); onMenuItemClick?.(); }}
        disabled={converting[job.job_id]}
        className="text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
      >
        {t("page:jobs.excelCost", { cost: xlsxCost(job).toLocaleString() })}
      </button>
      <button
        onClick={() => { convertAndDownload(job.job_id, "docx"); onMenuItemClick?.(); }}
        disabled={converting[job.job_id]}
        className="text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
      >
        {t("page:jobs.wordFree")}
      </button>
      <button
        onClick={() => { convertAndDownload(job.job_id, "pptx"); onMenuItemClick?.(); }}
        disabled={converting[job.job_id]}
        className="text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
      >
        {t("page:jobs.pptFree")}
      </button>
    </div>
  );

  return (
    <>
      <button
        ref={btnRef}
        onMouseEnter={handleEnter}
        onMouseLeave={handleLeave}
        className="p-2 rounded-lg hover:bg-surface-container-high text-outline hover:text-primary transition-colors"
        title={`${fileTypeLabel(job.file_type)} ${t("page:jobs.download")}`}
      >
        {children}
      </button>
      {open && createPortal(menu, document.body)}
    </>
  );
}

const STATUS_CHIP = {
  pending: {
    bg: "bg-surface-container-high",
    text: "text-on-surface-variant",
    icon: "hourglass_empty"
  },
  queued: {
    bg: "bg-primary-container/10",
    text: "text-primary",
    icon: "schedule"
  },
  ocr: { bg: "bg-primary-container/10", text: "text-primary", icon: "refresh" },
  merging: {
    bg: "bg-primary-container/10",
    text: "text-primary",
    icon: "refresh"
  },
  done: { bg: "bg-green-50", text: "text-green-700", icon: "check_circle" },
  error: { bg: "bg-red-50", text: "text-red-700", icon: "cancel" }
};

const PAGE_SIZE = 10;

const MOCK_JOBS = import.meta.env.DEV ? [
  { job_id: "mock-1", filename: "샘플_문서_2024.pdf", file_type: "pdf", file_size: 2456789, status: "done", created_at: "2024-06-15T10:30:00", total_pages: 12, done_pages: 12, source_expires_at: new Date(Date.now() + 36 * 3600 * 1000).toISOString() },
  { job_id: "mock-2", filename: "재무제표_1분기.xlsx", file_type: "xlsx", file_size: 523456, status: "ocr", created_at: "2024-06-15T09:15:00", total_pages: 8, done_pages: 3, source_expires_at: new Date(Date.now() + 12 * 3600 * 1000).toISOString() },
  { job_id: "mock-3", filename: "회의록_20240601.hwp", file_type: "hwp", file_size: 1023456, status: "pending", created_at: "2024-06-14T14:20:00", total_pages: 0, done_pages: 0, source_expires_at: new Date(Date.now() + 2 * 3600 * 1000).toISOString() },
  { job_id: "mock-4", filename: "프레젠테이션_발표자료.pptx", file_type: "pptx", file_size: 3890123, status: "error", created_at: "2024-06-13T16:45:00", total_pages: 15, done_pages: 0, source_expires_at: null },
  { job_id: "mock-5", filename: "계약서_원본.pdf", file_type: "pdf", file_size: 892345, status: "done", created_at: "2024-06-12T11:00:00", total_pages: 5, done_pages: 5, source_expires_at: null },
  { job_id: "mock-6", filename: "영수증_스캔_이미지.png", file_type: "image", file_size: 234567, status: "done", created_at: "2024-06-11T08:30:00", total_files: 3, done_files: 3, source_expires_at: null },
  { job_id: "mock-7", filename: "매출보고서_2024.docx", file_type: "docx", file_size: 1456789, status: "merging", created_at: "2024-06-10T13:15:00", total_pages: 20, done_pages: 18, source_expires_at: new Date(Date.now() + 48 * 3600 * 1000).toISOString() },
] : [];

export default function JobsPage() {
  const { user, loading: authLoading } = useAuth();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [converting, setConverting] = useState({});
  const [filterOpen, setFilterOpen] = useState(false);
  const [dateOpen, setDateOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState("all");
  const [fileTypeFilter, setFileTypeFilter] = useState("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [deleteModal, setDeleteModal] = useState({ open: false, job: null });
  const [deleting, setDeleting] = useState({});
  const pollRef = useRef(null);

  const statusLabel = (status) => t(`common:status.${status}`) || status;
  const fileTypeLabel = (type) => t(`common:fileType.${type}`) || type;

  useEffect(() => {
    if (!user) {
      if (import.meta.env.DEV) {
        setJobs(MOCK_JOBS);
        setLoading(false);
      }
      return;
    }
    load();
  }, [user]);

  // [Flow: Step 1 (활성 작업 존재 확인) -> Step 2 (5초 간격 폴링) -> Step 3 (완료 시 폴링 중지)]
  useEffect(() => {
    const hasActive = jobs.some((j) => j.status !== "done" && j.status !== "error");
    if (!hasActive) {
      clearInterval(pollRef.current);
      pollRef.current = null;
      return;
    }
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      try {
        const list = await api.listJobs();
        setJobs(list);
      } catch {
        // 폴링 에러는 무시
      }
    }, 5000);
    return () => {
      clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [jobs]);

  async function load() {
    setLoading(true);
    try {
      const list = await api.listJobs();
      setJobs(list);
    } catch (e) {
      setError(e.message || t("page:errors.loadFailed"));
    } finally {
      setLoading(false);
    }
  }

  function formatDate(dateStr) {
    if (!dateStr) return "-";
    const d = new Date(dateStr);
    return d.toLocaleString(i18n.language, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    });
  }

  function timeLeft(expiresAt) {
    if (!expiresAt) return t("page:jobs.noExpiry");
    const diffMs = new Date(expiresAt) - new Date();
    if (diffMs <= 0) return t("page:jobs.expired");
    const totalMinutes = Math.ceil(diffMs / (1000 * 60));
    const days = Math.floor(totalMinutes / (60 * 24));
    const hours = Math.floor((totalMinutes % (60 * 24)) / 60);
    const minutes = totalMinutes % 60;
    if (days > 0) return t("page:jobs.daysLeft", { days });
    if (hours > 0) return t("page:jobs.hoursLeft", { hours });
    return t("page:jobs.minutesLeft", { minutes });
  }

  function fileSize(bytes) {
    if (!bytes) return "-";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  async function download(id, type) {
    const { download_url } = await api.downloadJob(id, type);
    const job = jobs.find((j) => j.job_id === id);
    const base = job?.filename ?
    job.filename.replace(/\.[^/.]+$/, "") :
    "result";
    const ext = type === "md" ? "md" : type;
    const a = document.createElement("a");
    a.href = download_url;
    a.download = `${base}.${ext}`;
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  async function convertAndDownload(id, format) {
    setConverting((prev) => ({ ...prev, [id]: true }));
    try {
      const { download_url } = await api.convertJob(id, format);
      const job = jobs.find((j) => j.job_id === id);
      const base = job?.filename ?
      job.filename.replace(/\.[^/.]+$/, "") :
      "result";
      const a = document.createElement("a");
      a.href = download_url;
      a.download = `${base}.${format}`;
      a.style.display = "none";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
    } finally {
      setConverting((prev) => ({ ...prev, [id]: false }));
    }
  }

  function openDeleteModal(job) {
    setDeleteModal({ open: true, job });
  }

  function closeDeleteModal() {
    setDeleteModal({ open: false, job: null });
  }

  async function confirmDelete() {
    const job = deleteModal.job;
    if (!job) return;
    setDeleting((prev) => ({ ...prev, [job.job_id]: true }));
    try {
      await api.deleteJob(job.job_id);
      setJobs((prev) => prev.filter((j) => j.job_id !== job.job_id));
      closeDeleteModal();
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
    } finally {
      setDeleting((prev) => ({ ...prev, [job.job_id]: false }));
    }
  }

  function xlsxCost(job) {
    return (job.total_pages || job.total_files || 1) * 3;
  }

  const activeCount = useMemo(
    () =>
    jobs.filter((j) => j.status !== "done" && j.status !== "error").length,
    [jobs]
  );
  const completedCount = useMemo(
    () => jobs.filter((j) => j.status === "done").length,
    [jobs]
  );

  const filtered = useMemo(() => {
    return jobs.filter((j) => {
      if (statusFilter !== "all" && j.status !== statusFilter) return false;
      if (fileTypeFilter !== "all" && j.file_type !== fileTypeFilter)
      return false;
      if (dateFrom) {
        const d = new Date(j.created_at);
        const from = new Date(dateFrom);
        from.setHours(0, 0, 0, 0);
        if (d < from) return false;
      }
      if (dateTo) {
        const d = new Date(j.created_at);
        const to = new Date(dateTo);
        to.setHours(23, 59, 59, 999);
        if (d > to) return false;
      }
      return true;
    });
  }, [jobs, statusFilter, fileTypeFilter, dateFrom, dateTo]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageJobs = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  if (authLoading || (!user && !import.meta.env.DEV && !error)) {
    return (
      <div
        className="min-h-screen flex items-center justify-center bg-background"
        data-oid="kq5:r74">

        <Loader2
          className="animate-spin text-primary"
          size={32}
          data-oid="-7zx915" />

      </div>);

  }

  if (!user && !import.meta.env.DEV) {
    return (
      <div
        className="min-h-screen flex items-center justify-center bg-background"
        data-oid="__j1q4x">

        <div className="text-center" data-oid="2ha4jhb">
          <p className="mb-4 text-on-surface-variant" data-oid="6.h-jmz">
            {t("common:auth.loginRequired")}
          </p>
          <button
            onClick={() => navigate("/login")}
            className="bg-primary text-on-primary px-4 py-2 rounded-lg"
            data-oid="nguyl5s">

            {t("page:auth.loginButton")}
          </button>
        </div>
      </div>);

  }

  return (
    <SidebarLayout
      title={t("page:jobs.title")}
      subtitle={t("page:jobs.subtitle")}
      data-oid="oyq:fv1">

      {/* Header chips */}
      <div
        className="flex flex-col md:flex-row md:items-end justify-between gap-gutter mb-stack-lg"
        data-oid="7dzkh55">

        <div className="flex gap-4" data-oid="1:wslj4">
          <div
            className="flex items-center gap-2 px-3 py-1 bg-surface-container rounded-full"
            data-oid="w_ck6a4">

            <span
              className="w-2 h-2 rounded-full bg-primary status-pulse"
              data-oid="q..80g:">
            </span>
            <span
              className="font-label-sm text-label-sm text-on-surface-variant"
              data-oid="dl_:.64">

              {activeCount} {t("page:jobs.activeTasks")}
            </span>
          </div>
          <div
            className="flex items-center gap-2 px-3 py-1 bg-surface-container rounded-full"
            data-oid="po64m:1">

            <span
              className="material-symbols-outlined text-green-600 text-[14px]"
              data-oid="q9x4_9l">

              check_circle
            </span>
            <span
              className="font-label-sm text-label-sm text-on-surface-variant"
              data-oid="52d7owg">

              {completedCount} {t("page:jobs.completedTasks")}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-3 relative" data-oid="5h44.7o">
          <Link
            to="/"
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-primary text-on-primary font-body-md text-body-md font-medium hover:opacity-90 transition-all shadow-sm"
            data-oid="mv6xpjv">

            <span className="material-symbols-outlined" data-oid="6-myl-e">
              upload
            </span>
            {t("page:jobs.uploadFiles")}
          </Link>
          <div className="relative" data-oid="-1o8i-:">
            <button
              onClick={() => setFilterOpen((v) => !v)}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl border border-outline-variant font-body-md text-body-md transition-all ${filterOpen ? "bg-surface-container text-primary" : "text-on-surface-variant hover:bg-surface-container-low"}`}
              data-oid="y5qdhnz">

              <span className="material-symbols-outlined" data-oid="jy5vm6w">
                filter_list
              </span>
              {t("page:jobs.filters")}
            </button>
            {filterOpen &&
            <div
              className="absolute right-0 top-full mt-2 w-56 bg-surface rounded-xl shadow-lg border border-outline-variant z-50 p-4"
              data-oid="qdf9680">

                <div className="mb-4" data-oid="j0zh63q">
                  <label
                  className="block font-label-sm text-label-sm text-on-surface-variant mb-1.5"
                  data-oid="k5qzle:">

                    {t("page:jobs.status")}
                  </label>
                  <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  className="w-full bg-surface-container-low border border-outline-variant rounded-lg px-3 py-2 text-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
                  data-oid="wbzeg6w">

                    <option value="all" data-oid="1t5th8f">
                      {t("page:jobs.all")}
                    </option>
                    {[
                  "pending",
                  "queued",
                  "ocr",
                  "merging",
                  "done",
                  "error"].
                  map((k) =>
                  <option key={k} value={k} data-oid="_z6irio">
                        {statusLabel(k)}
                      </option>
                  )}
                  </select>
                </div>
                <div data-oid="l3xzzt9">
                  <label
                  className="block font-label-sm text-label-sm text-on-surface-variant mb-1.5"
                  data-oid="fnu-t.h">

                    {t("page:jobs.fileType")}
                  </label>
                  <select
                  value={fileTypeFilter}
                  onChange={(e) => setFileTypeFilter(e.target.value)}
                  className="w-full bg-surface-container-low border border-outline-variant rounded-lg px-3 py-2 text-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
                  data-oid="g4qu7g1">

                    <option value="all" data-oid="sohw2ag">
                      {t("page:jobs.all")}
                    </option>
                    {["pdf", "image", "audio", "video", "mixed", "archive"].map(
                    (k) =>
                    <option key={k} value={k} data-oid="b9-4wen">
                          {fileTypeLabel(k)}
                        </option>

                  )}
                  </select>
                </div>
                <button
                onClick={() => {
                  setStatusFilter("all");
                  setFileTypeFilter("all");
                }}
                className="mt-4 w-full text-left text-sm text-outline hover:text-primary transition-colors"
                data-oid="y_sw1ei">

                  {t("page:jobs.resetFilters")}
                </button>
              </div>
            }
          </div>
          <div className="relative" data-oid="3ma2oqk">
            <button
              onClick={() => setDateOpen((v) => !v)}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl border border-outline-variant font-body-md text-body-md transition-all ${dateOpen ? "bg-surface-container text-primary" : "text-on-surface-variant hover:bg-surface-container-low"}`}
              data-oid="cwu7skk">

              <span className="material-symbols-outlined" data-oid="iv9hri8">
                calendar_today
              </span>
              {t("page:jobs.dateRange")}
            </button>
            {dateOpen &&
            <div
              className="absolute right-0 top-full mt-2 w-64 bg-surface rounded-xl shadow-lg border border-outline-variant z-50 p-4"
              data-oid="zob5p1c">

                <div className="mb-3" data-oid="70..9mk">
                  <label
                  className="block font-label-sm text-label-sm text-on-surface-variant mb-1.5"
                  data-oid="qb6ko-1">

                    {t("page:jobs.startDate")}
                  </label>
                  <input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  className="w-full bg-surface-container-low border border-outline-variant rounded-lg px-3 py-2 text-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
                  data-oid="011i7kp" />

                </div>
                <div className="mb-3" data-oid="-hyu564">
                  <label
                  className="block font-label-sm text-label-sm text-on-surface-variant mb-1.5"
                  data-oid="rkxml3z">

                    {t("page:jobs.endDate")}
                  </label>
                  <input
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  className="w-full bg-surface-container-low border border-outline-variant rounded-lg px-3 py-2 text-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
                  data-oid="ql3-f2o" />

                </div>
                <button
                onClick={() => {
                  setDateFrom("");
                  setDateTo("");
                }}
                className="w-full text-left text-sm text-outline hover:text-primary transition-colors"
                data-oid="0os-1hx">

                  {t("page:jobs.resetDate")}
                </button>
              </div>
            }
          </div>
        </div>
      </div>

      {error &&
      <div
        className="bg-red-50 text-red-700 px-4 py-3 rounded-lg mb-6 flex items-center gap-2 border border-red-200"
        data-oid="kt2vw9a">

          <span className="material-symbols-outlined" data-oid="q-nfw9f">
            error
          </span>
          {error}
        </div>
      }

      {/* Jobs table */}
      <div
        className="bg-surface-container-lowest rounded-xl border border-outline-variant shadow-sm overflow-hidden"
        data-oid="3f8sszo">

        <div className="overflow-x-auto custom-scrollbar" data-oid="gz-rlzc">
          <table
            className="w-full text-left border-collapse table-fixed"
            data-oid="6k4gubk">

            <colgroup>
              <col className="w-auto" />
              <col className="w-[150px]" />
              <col className="w-[150px]" />
              <col className="w-[130px]" />
              <col className="w-[110px]" />
            </colgroup>

            <thead data-oid="ho01sek">
              <tr
                className="bg-surface-container-low/50 border-b border-outline-variant"
                data-oid="uzfp9p7">

                <th
                  className="px-gutter py-3 font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider"
                  data-oid="0q7xa_:">

                  {t("page:jobs.fileName")}
                </th>
                <th
                  className="px-gutter py-3 font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider"
                  data-oid="d9qbk69">

                  {t("page:jobs.status")}
                </th>
                <th
                  className="px-gutter py-3 font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider"
                  data-oid="hxlgn4f">

                  {t("page:jobs.dateCreated")}
                </th>
                <th
                  className="px-gutter py-3 font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider"
                  data-oid="0i551g5">

                  <div className="flex items-center gap-1" data-oid="e4eiju5">
                    {t("page:jobs.expiresIn")}
                    <span
                      className="material-symbols-outlined text-[14px] cursor-help"
                      title={t("page:jobs.expiresInfo")}
                      data-oid="eeloa-0">

                      info
                    </span>
                  </div>
                </th>
                <th
                  className="px-gutter py-3 font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider text-right"
                  data-oid="k8a17n2">

                  {t("page:jobs.actions")}
                </th>
              </tr>
            </thead>
            <tbody
              className="divide-y divide-outline-variant/50"
              data-oid="kas6s2w">

              {loading ?
              <tr data-oid="2a4vwvg">
                  <td
                  colSpan={5}
                  className="px-gutter py-4"
                  data-oid="2eowq3q">

                    <SkeletonTable columns={5} rows={10} />

                  </td>
                </tr> :

              pageJobs.map((j, idx) => {
                const chip = STATUS_CHIP[j.status] || STATUS_CHIP.pending;
                const isDone = j.status === "done";
                return (
                  <AnimatedRow key={j.job_id} index={idx}>
                  <tr
                    className="hover:bg-surface-container/30 transition-colors group [&_td]:align-middle"
                    data-oid="7iv7mrp">

                      <td className="px-gutter py-4" data-oid="onovb9s">
                        <div
                        className="flex items-center gap-3"
                        data-oid="y2ftyte">

                          <div
                          className="w-10 h-10 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center shrink-0"
                          data-oid="k4j15nw">

                            <span
                            className="material-symbols-outlined"
                            data-oid="r6tajuj">

                              {isDone ? "table_chart" : "description"}
                            </span>
                          </div>
                          <div data-oid="ats28o7">
                            <p
                            className="font-body-md text-body-md font-medium text-on-surface truncate"
                            data-oid="7sy3qzp"
                            title={j.filename}>

                              {j.filename}
                            </p>
                            <p
                            className="font-label-sm text-label-sm text-outline"
                            data-oid="i0y1sq2">

                              {fileSize(j.file_size)}
                            </p>
                          </div>
                        </div>
                      </td>
                      <td className="px-gutter py-4" data-oid="ge54lqm">
                        <div
                        className={`inline-flex items-center gap-2 px-3 py-1 rounded-full border border-inherit ${chip.bg} ${chip.text}`}
                        data-oid="1uiycel">

                          <span
                          className={`material-symbols-outlined text-[16px] ${j.status === "ocr" || j.status === "merging" || j.status === "queued" ? "animate-spin" : ""}`}
                          data-oid="_iw_vfh">

                            {chip.icon}
                          </span>
                          <span
                          className="font-label-sm text-label-sm font-semibold"
                          data-oid="596fbly">

                            {statusLabel(j.status)}
                          </span>
                        </div>
                        {j.status !== "done" && j.status !== "error" && (j.total_pages > 0 || j.total_files > 0) && (
                          (() => {
                            const usePages = j.total_pages > 0 && j.done_pages > 0;
                            const done = usePages ? j.done_pages : j.done_files;
                            const total = usePages ? j.total_pages : j.total_files;
                            const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
                            return (
                              <div className="mt-1.5 flex items-center gap-2 min-w-0">
                                <div className="flex-1 h-1.5 bg-surface-container-high rounded-full overflow-hidden min-w-[40px]">
                                  <div
                                    className="h-full bg-primary rounded-full transition-all duration-500"
                                    style={{ width: `${pct}%` }}
                                  />
                                </div>
                                <span className="font-label-sm text-label-sm text-on-surface-variant whitespace-nowrap">
                                  {usePages
                                    ? t("page:jobs.progressPages", { done: done || 0, total: total })
                                    : t("page:jobs.progressFiles", { done: done || 0, total: total })}
                                </span>
                              </div>
                            );
                          })()
                        )}
                      </td>
                      <td
                      className="px-gutter py-4 font-body-md text-body-md text-on-surface-variant whitespace-nowrap"
                      data-oid="n_ue8pe">

                        {formatDate(j.created_at)}
                      </td>
                      <td
                      className="px-gutter py-4 font-body-md text-body-md text-on-surface-variant whitespace-nowrap"
                      data-oid="zmn711w">

                        {timeLeft(j.source_expires_at)}
                      </td>
                      <td
                      className="px-gutter py-4 text-right"
                      data-oid="jo2op4c">

                        <div
                        className="flex justify-end gap-2"
                        data-oid="nj:056g">

                          {isDone ?
                        <>
                              <Link
                            to={`/jobs/${j.job_id}`}
                            className="p-2 rounded-lg hover:bg-surface-container-high text-outline hover:text-primary transition-colors"
                            title={`${fileTypeLabel(j.file_type)} ${t("page:jobs.view")}`}
                            data-oid="czg0jxq">

                                <Eye size={18} data-oid="yxvpdkc" />
                              </Link>
                              <button
                            onClick={() => openDeleteModal(j)}
                            className="p-2 rounded-lg hover:bg-surface-container-high text-outline hover:text-red-600 transition-colors"
                            title={`${fileTypeLabel(j.file_type)} ${t("page:jobs.delete")}`}
                            data-oid="3nnh9iw">

                                <Trash2 size={18} data-oid="fp7w_cf" />
                              </button>
                              <DownloadMenu
                                job={j}
                                fileTypeLabel={fileTypeLabel}
                                download={download}
                                convertAndDownload={convertAndDownload}
                                converting={converting}
                                xlsxCost={xlsxCost}
                                onMenuItemClick={() => {}}
                              >
                                <Download size={18} data-oid="x4fihqx" />
                              </DownloadMenu>
                            </> :

                        <button
                          onClick={() => openDeleteModal(j)}
                          className="p-2 rounded-lg hover:bg-surface-container-high text-outline hover:text-red-600 transition-colors"
                          title={`${fileTypeLabel(j.file_type)} ${t("page:jobs.delete")}`}
                          data-oid="ida:p:-">

                              <Trash2 size={18} data-oid="t.hqgua" />
                            </button>
                        }
                        </div>
                      </td>
                    </tr>
                  </AnimatedRow>);

              })
              }
              {!loading && pageJobs.length === 0 &&
              <tr data-oid="ocs1v4i">
                  <td
                  colSpan={5}
                  className="text-center py-12 text-on-surface-variant"
                  data-oid="rv:rftt">

                    <p data-oid="er1dbhj">{t("page:jobs.noJobs")}</p>
                    <Link
                    to="/"
                    className="text-primary hover:underline mt-2 inline-block"
                    data-oid="hhynqec">

                      {t("page:jobs.firstUpload")}
                    </Link>
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div
          className="px-gutter py-4 border-t border-outline-variant flex flex-col md:flex-row items-center justify-between gap-3 bg-surface-container-lowest"
          data-oid="r34v:p9">

          <p
            className="font-label-sm text-label-sm text-on-surface-variant"
            data-oid="50ampsj">

            {t("page:jobs.showing", {
              from: (page - 1) * PAGE_SIZE + 1,
              to: Math.min(page * PAGE_SIZE, filtered.length),
              total: filtered.length
            })}
          </p>
          <div className="flex items-center gap-1" data-oid="f45bbfe">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-surface-container transition-colors disabled:opacity-30"
              data-oid="_.es66e">

              <ChevronLeft size={18} data-oid="_mm52sr" />
            </button>
            {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) =>
            <button
              key={p}
              onClick={() => setPage(p)}
              className={`w-8 h-8 flex items-center justify-center rounded-lg font-label-sm text-label-sm ${page === p ? "bg-primary text-on-primary" : "hover:bg-surface-container"}`}
              data-oid="7n:1hmb">

                {p}
              </button>
            )}
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-surface-container transition-colors disabled:opacity-30"
              data-oid="i3yu82j">

              <ChevronRight size={18} data-oid="6mnqyin" />
            </button>
          </div>
        </div>
      </div>

      {/* API promo card */}
      <div
        className="mt-stack-lg grid grid-cols-1 md:grid-cols-3 gap-gutter"
        data-oid="b2uerpz">

        <div
          className="col-span-1 md:col-span-2 glass-surface p-gutter rounded-2xl border border-primary/10 flex items-start gap-4"
          data-oid="0pkucux">

          <div
            className="p-3 rounded-xl bg-primary/10 text-primary"
            data-oid="j8ymdn.">

            <span className="material-symbols-outlined" data-oid="7sz9cgc">
              lightbulb
            </span>
          </div>
          <div data-oid=".71qi7m">
            <h4
              className="font-headline-md text-headline-md text-primary mb-2"
              data-oid="3l2ilm-">

              {t("page:jobs.apiPromoTitle")}
            </h4>
            <p
              className="font-body-md text-body-md text-on-surface-variant max-w-xl"
              data-oid="tz77vay">

              {t("page:jobs.apiPromoDesc")}
            </p>
            <Link
              to="/developer"
              className="mt-4 text-primary font-body-md text-body-md font-bold hover:underline inline-block"
              data-oid="9legvww">

              {t("page:jobs.apiPromoLink")} →
            </Link>
          </div>
        </div>
      </div>

      {/* Delete confirmation modal */}
      {deleteModal.open &&
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
        data-oid="yo3s1wu">

          <div
          className="w-full max-w-sm bg-surface-container rounded-2xl shadow-xl border border-outline-variant p-6"
          data-oid="8g..5yq">

            <h3
            className="font-headline-sm text-headline-sm text-on-surface mb-2"
            data-oid="7z_576e">

              {t("page:jobs.deleteConfirmTitle")}
            </h3>
            <p
            className="font-body-md text-body-md text-on-surface-variant mb-6"
            data-oid="_c.1psc">

              {t("page:jobs.deleteConfirmDesc", {
              filename: deleteModal.job?.filename
            })}
            </p>
            <div className="flex justify-end gap-3" data-oid="ef9ppi0">
              <button
              onClick={closeDeleteModal}
              className="px-4 py-2 rounded-xl border border-outline-variant font-body-md text-body-md text-on-surface-variant hover:bg-surface-container-high transition-colors"
              data-oid="blrh66x">

                {t("page:jobs.cancel")}
              </button>
              <button
              onClick={confirmDelete}
              disabled={deleting[deleteModal.job?.job_id]}
              className="px-4 py-2 rounded-xl bg-red-600 text-white font-body-md text-body-md font-medium hover:bg-red-700 transition-colors disabled:opacity-50"
              data-oid="czziy-v">

                {deleting[deleteModal.job?.job_id] ?
              t("page:jobs.deleting") :
              t("page:jobs.delete")}
              </button>
            </div>
          </div>
        </div>
      }
    </SidebarLayout>);

}