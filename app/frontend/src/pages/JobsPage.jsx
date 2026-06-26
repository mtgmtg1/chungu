// [Flow: Step 1 (사용자 확인 + 작업 목록 로드) -> Step 2 (검색/필터 상태) -> Step 3 (테이블 렌더링 + Actions) -> Step 4 (페이지네이션)]
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Eye, Download, Trash2, Loader2, ChevronLeft, ChevronRight } from 'lucide-react'
import { useAuth } from '../AuthContext.jsx'
import { api } from '../api.js'
import i18n from '../i18n.js'
import SidebarLayout from '../components/SidebarLayout.jsx'

const STATUS_CHIP = {
  pending: { bg: 'bg-surface-container-high', text: 'text-on-surface-variant', icon: 'hourglass_empty' },
  queued: { bg: 'bg-primary-container/10', text: 'text-primary', icon: 'schedule' },
  ocr: { bg: 'bg-primary-container/10', text: 'text-primary', icon: 'refresh' },
  merging: { bg: 'bg-primary-container/10', text: 'text-primary', icon: 'refresh' },
  done: { bg: 'bg-green-50', text: 'text-green-700', icon: 'check_circle' },
  error: { bg: 'bg-red-50', text: 'text-red-700', icon: 'cancel' },
}

const PAGE_SIZE = 10

export default function JobsPage() {
  const { user, loading: authLoading } = useAuth()
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [page, setPage] = useState(1)
  const [converting, setConverting] = useState({})
  const [filterOpen, setFilterOpen] = useState(false)
  const [dateOpen, setDateOpen] = useState(false)
  const [statusFilter, setStatusFilter] = useState('all')
  const [fileTypeFilter, setFileTypeFilter] = useState('all')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [deleteModal, setDeleteModal] = useState({ open: false, job: null })
  const [deleting, setDeleting] = useState({})

  const statusLabel = (status) => t(`common:status.${status}`) || status
  const fileTypeLabel = (type) => t(`common:fileType.${type}`) || type

  useEffect(() => {
    if (!user) return
    load()
  }, [user])

  async function load() {
    setLoading(true)
    try {
      const list = await api.listJobs()
      setJobs(list)
    } catch (e) {
      setError(e.message || t('page:errors.loadFailed'))
    } finally {
      setLoading(false)
    }
  }

  function formatDate(dateStr) {
    if (!dateStr) return '-'
    const d = new Date(dateStr)
    return d.toLocaleString(i18n.language, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  }

  function daysLeft(expiresAt) {
    if (!expiresAt) return t('page:jobs.noExpiry')
    const diff = Math.ceil((new Date(expiresAt) - new Date()) / (1000 * 60 * 60 * 24))
    if (diff <= 0) return t('page:jobs.expired')
    return t('page:jobs.daysLeft', { days: diff })
  }

  function fileSize(bytes) {
    if (!bytes) return '-'
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  async function download(id, type) {
    const { download_url } = await api.downloadJob(id, type)
    const job = jobs.find((j) => j.job_id === id)
    const base = job?.filename ? job.filename.replace(/\.[^/.]+$/, '') : 'result'
    const ext = type === 'md' ? 'md' : type
    const a = document.createElement('a')
    a.href = download_url
    a.download = `${base}.${ext}`
    a.style.display = 'none'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }

  async function convertAndDownload(id, format) {
    setConverting((prev) => ({ ...prev, [id]: true }))
    try {
      const { download_url } = await api.convertJob(id, format)
      const job = jobs.find((j) => j.job_id === id)
      const base = job?.filename ? job.filename.replace(/\.[^/.]+$/, '') : 'result'
      const a = document.createElement('a')
      a.href = download_url
      a.download = `${base}.${format}`
      a.style.display = 'none'
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
    } catch (e) {
      setError(e.message || t('page:errors.unknown'))
    } finally {
      setConverting((prev) => ({ ...prev, [id]: false }))
    }
  }

  function openDeleteModal(job) {
    setDeleteModal({ open: true, job })
  }

  function closeDeleteModal() {
    setDeleteModal({ open: false, job: null })
  }

  async function confirmDelete() {
    const job = deleteModal.job
    if (!job) return
    setDeleting((prev) => ({ ...prev, [job.job_id]: true }))
    try {
      await api.deleteJob(job.job_id)
      setJobs((prev) => prev.filter((j) => j.job_id !== job.job_id))
      closeDeleteModal()
    } catch (e) {
      setError(e.message || t('page:errors.unknown'))
    } finally {
      setDeleting((prev) => ({ ...prev, [job.job_id]: false }))
    }
  }

  function xlsxCost(job) {
    return (job.total_pages || job.total_files || 1) * 3
  }

  const activeCount = useMemo(() => jobs.filter((j) => j.status !== 'done' && j.status !== 'error').length, [jobs])
  const completedCount = useMemo(() => jobs.filter((j) => j.status === 'done').length, [jobs])

  const filtered = useMemo(() => {
    return jobs.filter((j) => {
      if (statusFilter !== 'all' && j.status !== statusFilter) return false
      if (fileTypeFilter !== 'all' && j.file_type !== fileTypeFilter) return false
      if (dateFrom) {
        const d = new Date(j.created_at)
        const from = new Date(dateFrom)
        from.setHours(0, 0, 0, 0)
        if (d < from) return false
      }
      if (dateTo) {
        const d = new Date(j.created_at)
        const to = new Date(dateTo)
        to.setHours(23, 59, 59, 999)
        if (d > to) return false
      }
      return true
    })
  }, [jobs, statusFilter, fileTypeFilter, dateFrom, dateTo])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const pageJobs = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  if (authLoading || (!user && !error)) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <Loader2 className="animate-spin text-primary" size={32} />
      </div>
    )
  }

  if (!user) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="text-center">
          <p className="mb-4 text-on-surface-variant">{t('common:auth.loginRequired')}</p>
          <button onClick={() => navigate('/login')} className="bg-primary text-on-primary px-4 py-2 rounded-lg">{t('page:auth.loginButton')}</button>
        </div>
      </div>
    )
  }

  return (
    <SidebarLayout title={t('page:jobs.title')} subtitle={t('page:jobs.subtitle')}>
      {/* Header chips */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-gutter mb-stack-lg">
        <div className="flex gap-4">
          <div className="flex items-center gap-2 px-3 py-1 bg-surface-container rounded-full">
            <span className="w-2 h-2 rounded-full bg-primary status-pulse"></span>
            <span className="font-label-sm text-label-sm text-on-surface-variant">{activeCount} {t('page:jobs.activeTasks')}</span>
          </div>
          <div className="flex items-center gap-2 px-3 py-1 bg-surface-container rounded-full">
            <span className="material-symbols-outlined text-green-600 text-[14px]">check_circle</span>
            <span className="font-label-sm text-label-sm text-on-surface-variant">{completedCount} {t('page:jobs.completedTasks')}</span>
          </div>
        </div>
        <div className="flex items-center gap-3 relative">
          <Link
            to="/"
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-primary text-on-primary font-body-md text-body-md font-medium hover:opacity-90 transition-all shadow-sm"
          >
            <span className="material-symbols-outlined">upload</span>
            {t('page:jobs.uploadFiles')}
          </Link>
          <div className="relative">
            <button
              onClick={() => setFilterOpen((v) => !v)}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl border border-outline-variant font-body-md text-body-md transition-all ${filterOpen ? 'bg-surface-container text-primary' : 'text-on-surface-variant hover:bg-surface-container-low'}`}
            >
              <span className="material-symbols-outlined">filter_list</span>
              {t('page:jobs.filters')}
            </button>
            {filterOpen && (
              <div className="absolute right-0 top-full mt-2 w-56 bg-surface rounded-xl shadow-lg border border-outline-variant z-50 p-4">
                <div className="mb-4">
                  <label className="block font-label-sm text-label-sm text-on-surface-variant mb-1.5">{t('page:jobs.status')}</label>
                  <select
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                    className="w-full bg-surface-container-low border border-outline-variant rounded-lg px-3 py-2 text-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
                  >
                    <option value="all">{t('page:jobs.all')}</option>
                    {['pending', 'queued', 'ocr', 'merging', 'done', 'error'].map((k) => (
                      <option key={k} value={k}>{statusLabel(k)}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block font-label-sm text-label-sm text-on-surface-variant mb-1.5">{t('page:jobs.fileType')}</label>
                  <select
                    value={fileTypeFilter}
                    onChange={(e) => setFileTypeFilter(e.target.value)}
                    className="w-full bg-surface-container-low border border-outline-variant rounded-lg px-3 py-2 text-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
                  >
                    <option value="all">{t('page:jobs.all')}</option>
                    {['pdf', 'image', 'audio', 'video', 'mixed', 'archive'].map((k) => (
                      <option key={k} value={k}>{fileTypeLabel(k)}</option>
                    ))}
                  </select>
                </div>
                <button
                  onClick={() => { setStatusFilter('all'); setFileTypeFilter('all'); }}
                  className="mt-4 w-full text-left text-sm text-outline hover:text-primary transition-colors"
                >
                  {t('page:jobs.resetFilters')}
                </button>
              </div>
            )}
          </div>
          <div className="relative">
            <button
              onClick={() => setDateOpen((v) => !v)}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl border border-outline-variant font-body-md text-body-md transition-all ${dateOpen ? 'bg-surface-container text-primary' : 'text-on-surface-variant hover:bg-surface-container-low'}`}
            >
              <span className="material-symbols-outlined">calendar_today</span>
              {t('page:jobs.dateRange')}
            </button>
            {dateOpen && (
              <div className="absolute right-0 top-full mt-2 w-64 bg-surface rounded-xl shadow-lg border border-outline-variant z-50 p-4">
                <div className="mb-3">
                  <label className="block font-label-sm text-label-sm text-on-surface-variant mb-1.5">{t('page:jobs.startDate')}</label>
                  <input
                    type="date"
                    value={dateFrom}
                    onChange={(e) => setDateFrom(e.target.value)}
                    className="w-full bg-surface-container-low border border-outline-variant rounded-lg px-3 py-2 text-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
                  />
                </div>
                <div className="mb-3">
                  <label className="block font-label-sm text-label-sm text-on-surface-variant mb-1.5">{t('page:jobs.endDate')}</label>
                  <input
                    type="date"
                    value={dateTo}
                    onChange={(e) => setDateTo(e.target.value)}
                    className="w-full bg-surface-container-low border border-outline-variant rounded-lg px-3 py-2 text-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
                  />
                </div>
                <button
                  onClick={() => { setDateFrom(''); setDateTo(''); }}
                  className="w-full text-left text-sm text-outline hover:text-primary transition-colors"
                >
                  {t('page:jobs.resetDate')}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 text-red-700 px-4 py-3 rounded-lg mb-6 flex items-center gap-2 border border-red-200">
          <span className="material-symbols-outlined">error</span>
          {error}
        </div>
      )}

      {/* Jobs table */}
      <div className="bg-surface-container-lowest rounded-xl border border-outline-variant shadow-sm overflow-hidden">
        <div className="overflow-x-auto custom-scrollbar">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-surface-container-low/50 border-b border-outline-variant">
                <th className="px-gutter py-4 font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider">{t('page:jobs.fileName')}</th>
                <th className="px-gutter py-4 font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider">{t('page:jobs.status')}</th>
                <th className="px-gutter py-4 font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider">{t('page:jobs.dateCreated')}</th>
                <th className="px-gutter py-4 font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider">
                  <div className="flex items-center gap-1">
                    {t('page:jobs.expiresIn')}
                    <span className="material-symbols-outlined text-[14px] cursor-help" title={t('page:jobs.expiresInfo')}>info</span>
                  </div>
                </th>
                <th className="px-gutter py-4 font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider text-right">{t('page:jobs.actions')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/50">
              {loading ? (
                <tr>
                  <td colSpan={5} className="text-center py-12">
                    <Loader2 className="animate-spin mx-auto text-primary" size={24} />
                  </td>
                </tr>
              ) : (
                pageJobs.map((j) => {
                  const chip = STATUS_CHIP[j.status] || STATUS_CHIP.pending
                  const isDone = j.status === 'done'
                  return (
                    <tr key={j.job_id} className="hover:bg-surface-container/30 transition-colors group">
                      <td className="px-gutter py-5">
                        <div className="flex items-center gap-3">
                          <div className="w-10 h-10 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center shrink-0">
                            <span className="material-symbols-outlined">{isDone ? 'table_chart' : 'description'}</span>
                          </div>
                          <div>
                            <p className="font-body-md text-body-md font-medium text-on-surface">{j.filename}</p>
                            <p className="font-label-sm text-label-sm text-outline">{fileSize(j.file_size)}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-gutter py-5">
                        <div className={`inline-flex items-center gap-2 px-3 py-1 rounded-full border border-inherit ${chip.bg} ${chip.text}`}>
                          <span className={`material-symbols-outlined text-[16px] ${j.status === 'ocr' || j.status === 'merging' || j.status === 'queued' ? 'animate-spin' : ''}`}>{chip.icon}</span>
                          <span className="font-label-sm text-label-sm font-semibold">{statusLabel(j.status)}</span>
                        </div>
                      </td>
                      <td className="px-gutter py-5 font-body-md text-body-md text-on-surface-variant">{formatDate(j.created_at)}</td>
                      <td className="px-gutter py-5 font-body-md text-body-md text-on-surface-variant">{daysLeft(j.expires_at)}</td>
                      <td className="px-gutter py-5 text-right">
                        <div className="flex justify-end gap-2">
                          {isDone ? (
                            <>
                              <Link
                                to={`/jobs/${j.job_id}`}
                                className="p-2 rounded-lg hover:bg-surface-container-high text-outline hover:text-primary transition-colors"
                                title={`${fileTypeLabel(j.file_type)} ${t('page:jobs.view')}`}
                              >
                                <Eye size={18} />
                              </Link>
                              <button
                                onClick={() => openDeleteModal(j)}
                                className="p-2 rounded-lg hover:bg-surface-container-high text-outline hover:text-red-600 transition-colors"
                                title={`${fileTypeLabel(j.file_type)} ${t('page:jobs.delete')}`}
                              >
                                <Trash2 size={18} />
                              </button>
                              <div className="relative group">
                                <button
                                  className="p-2 rounded-lg hover:bg-surface-container-high text-outline hover:text-primary transition-colors"
                                  title={`${fileTypeLabel(j.file_type)} ${t('page:jobs.download')}`}
                                >
                                  <Download size={18} />
                                </button>
                                <div className="absolute right-0 top-full mt-1 w-52 bg-white rounded-lg shadow-lg border border-outline-variant hidden group-hover:flex flex-col z-50 py-1">
                                  <button
                                    onClick={() => download(j.job_id, 'md')}
                                    className="text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
                                  >
                                    {t('page:jobs.markdownFree')}
                                  </button>
                                  <button
                                    onClick={() => download(j.job_id, 'csv')}
                                    className="text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
                                  >
                                    {t('page:jobs.csvExcel')}
                                  </button>
                                  <button
                                    onClick={() => convertAndDownload(j.job_id, 'xlsx')}
                                    disabled={converting[j.job_id]}
                                    className="text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
                                  >
                                    {t('page:jobs.excelCost', { cost: xlsxCost(j).toLocaleString() })}
                                  </button>
                                  <button
                                    onClick={() => convertAndDownload(j.job_id, 'docx')}
                                    disabled={converting[j.job_id]}
                                    className="text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
                                  >
                                    {t('page:jobs.wordFree')}
                                  </button>
                                  <button
                                    onClick={() => convertAndDownload(j.job_id, 'pptx')}
                                    disabled={converting[j.job_id]}
                                    className="text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
                                  >
                                    {t('page:jobs.pptFree')}
                                  </button>
                                </div>
                              </div>
                            </>
                          ) : (
                            <button
                              onClick={() => openDeleteModal(j)}
                              className="p-2 rounded-lg hover:bg-surface-container-high text-outline hover:text-red-600 transition-colors"
                              title={`${fileTypeLabel(j.file_type)} ${t('page:jobs.delete')}`}
                            >
                              <Trash2 size={18} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })
              )}
              {!loading && pageJobs.length === 0 && (
                <tr>
                  <td colSpan={5} className="text-center py-12 text-on-surface-variant">
                    <p>{t('page:jobs.noJobs')}</p>
                    <Link to="/" className="text-primary hover:underline mt-2 inline-block">{t('page:jobs.firstUpload')}</Link>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="px-gutter py-4 border-t border-outline-variant flex flex-col md:flex-row items-center justify-between gap-3 bg-surface-container-lowest">
          <p className="font-label-sm text-label-sm text-on-surface-variant">
            {t('page:jobs.showing', { from: (page - 1) * PAGE_SIZE + 1, to: Math.min(page * PAGE_SIZE, filtered.length), total: filtered.length })}
          </p>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-surface-container transition-colors disabled:opacity-30"
            >
              <ChevronLeft size={18} />
            </button>
            {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
              <button
                key={p}
                onClick={() => setPage(p)}
                className={`w-8 h-8 flex items-center justify-center rounded-lg font-label-sm text-label-sm ${page === p ? 'bg-primary text-on-primary' : 'hover:bg-surface-container'}`}
              >
                {p}
              </button>
            ))}
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-surface-container transition-colors disabled:opacity-30"
            >
              <ChevronRight size={18} />
            </button>
          </div>
        </div>
      </div>

      {/* API promo card */}
      <div className="mt-stack-lg grid grid-cols-1 md:grid-cols-3 gap-gutter">
        <div className="col-span-1 md:col-span-2 glass-surface p-gutter rounded-2xl border border-primary/10 flex items-start gap-4">
          <div className="p-3 rounded-xl bg-primary/10 text-primary">
            <span className="material-symbols-outlined">lightbulb</span>
          </div>
          <div>
            <h4 className="font-headline-md text-headline-md text-primary mb-2">{t('page:jobs.apiPromoTitle')}</h4>
            <p className="font-body-md text-body-md text-on-surface-variant max-w-xl">
              {t('page:jobs.apiPromoDesc')}
            </p>
            <Link to="/developer" className="mt-4 text-primary font-body-md text-body-md font-bold hover:underline inline-block">
              {t('page:jobs.apiPromoLink')} →
            </Link>
          </div>
        </div>
      </div>

      {/* Delete confirmation modal */}
      {deleteModal.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm bg-surface-container rounded-2xl shadow-xl border border-outline-variant p-6">
            <h3 className="font-headline-sm text-headline-sm text-on-surface mb-2">{t('page:jobs.deleteConfirmTitle')}</h3>
            <p className="font-body-md text-body-md text-on-surface-variant mb-6">
              {t('page:jobs.deleteConfirmDesc', { filename: deleteModal.job?.filename })}
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={closeDeleteModal}
                className="px-4 py-2 rounded-xl border border-outline-variant font-body-md text-body-md text-on-surface-variant hover:bg-surface-container-high transition-colors"
              >
                {t('page:jobs.cancel')}
              </button>
              <button
                onClick={confirmDelete}
                disabled={deleting[deleteModal.job?.job_id]}
                className="px-4 py-2 rounded-xl bg-red-600 text-white font-body-md text-body-md font-medium hover:bg-red-700 transition-colors disabled:opacity-50"
              >
                {deleting[deleteModal.job?.job_id] ? t('page:jobs.deleting') : t('page:jobs.delete')}
              </button>
            </div>
          </div>
        </div>
      )}
    </SidebarLayout>
  )
}
