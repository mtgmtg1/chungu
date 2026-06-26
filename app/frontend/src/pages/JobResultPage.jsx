// [Flow: Step 1 (job ID로 진입) -> Step 2 (작업 상태 폴링) -> Step 3 (완료 시 preview API 호출) -> Step 4 (100페이지 초과 시 페이지 단위 뷰어, 이하 시 PDF.js + 전체 에디터) -> Step 5 (마크다운/Office/CSV 다운로드)]
import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Check, Download, FileText, Loader2, PanelLeft, PanelLeftClose, Save, Table2, XCircle } from 'lucide-react'
import PdfViewer from '../components/PdfViewer.jsx'
import MediaPlayer from '../components/MediaPlayer.jsx'
import PagedResultViewer from '../components/PagedResultViewer.jsx'
import SimpleEditor from '../components/SimpleEditor.jsx'
import { api } from '../api.js'
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels'

const STATUS_LABEL = {
  pending: '결제 대기', queued: '대기 중', rendering: 'PDF 렌더링', ocr: 'OCR 분석 중',
  merging: '표 병합 중', done: '완료', error: '실패',
}

function downloadByUrl(url, filename) {
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

export default function JobResultPage() {
  const { jobId } = useParams()
  const [job, setJob] = useState(null)
  const [markdown, setMarkdown] = useState('')
  const [sourceUrl, setSourceUrl] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [converting, setConverting] = useState(false)
  const [saveMessage, setSaveMessage] = useState('')
  const [pages, setPages] = useState([])
  const [sourceType, setSourceType] = useState(null)
  const [imageUrls, setImageUrls] = useState([])
  const [currentPdfPage, setCurrentPdfPage] = useState(1)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const pollRef = useRef(null)
  const editorRef = useRef(null)

  const PAGE_THRESHOLD = 100
  const needsPagedMode = (j) => (j?.total_pages || 0) > PAGE_THRESHOLD || (j?.total_files || 0) > PAGE_THRESHOLD

  useEffect(() => {
    if (!jobId) return
    loadJob()
    return () => {
      clearInterval(pollRef.current)
    }
  }, [jobId])

  async function loadJob() {
    try {
      const data = await api.getJob(jobId)
      setJob(data)
      if (data.status === 'done') {
        clearInterval(pollRef.current)
        await loadPreview()
      } else if (data.status === 'error') {
        clearInterval(pollRef.current)
        setLoading(false)
      } else {
        startPolling()
      }
    } catch (e) {
      setError(e.message || '작업 정보를 불러오지 못했습니다')
      setLoading(false)
    }
  }

  function startPolling() {
    clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const data = await api.getJob(jobId)
        setJob(data)
        if (data.status === 'done') {
          clearInterval(pollRef.current)
          await loadPreview()
        } else if (data.status === 'error') {
          clearInterval(pollRef.current)
          setLoading(false)
        }
      } catch { /* 무시 */ }
    }, 2000)
  }

  async function loadPreview() {
    try {
      const preview = await api.previewJob(jobId)
      setSourceUrl(preview.source_url)
      setSourceType(preview.source_type)
      setImageUrls(preview.image_urls || [])
      if (needsPagedMode(job)) {
        const meta = await api.previewJobPages(jobId)
        setPages(meta.pages || [])
        setMarkdown('')
      } else {
        setMarkdown(preview.markdown || '')
        setPages([])
      }
    } catch (e) {
      setError(e.message || '결과 미리보기를 불러오지 못했습니다')
    } finally {
      setLoading(false)
    }
  }

  async function saveMarkdown() {
    if (!editorRef.current) return
    const updated = editorRef.current.getMarkdown()
    setSaving(true)
    setSaveMessage('')
    try {
      await api.saveResultMarkdown(jobId, updated)
      setMarkdown(updated)
      setSaveMessage('저장되었습니다')
      setTimeout(() => setSaveMessage(''), 2000)
    } catch (e) {
      setError(e.message || '저장에 실패했습니다')
    } finally {
      setSaving(false)
    }
  }

  async function download(type) {
    const { download_url } = await api.downloadJob(jobId, type)
    const base = job?.filename ? job.filename.replace(/\.[^/.]+$/, '') : 'result'
    const ext = type === 'md' ? 'md' : type
    downloadByUrl(download_url, `${base}.${ext}`)
  }

  async function convertAndDownload(format) {
    setConverting(true)
    setError('')
    try {
      const { download_url } = await api.convertJob(jobId, format)
      const base = job?.filename ? job.filename.replace(/\.[^/.]+$/, '') : 'result'
      downloadByUrl(download_url, `${base}.${format}`)
    } catch (e) {
      setError(e.message || '변환에 실패했습니다')
    } finally {
      setConverting(false)
    }
  }

  const xlsxCost = job ? (job.total_pages || job.total_files || 1) * 3 : 0

  const pct = job && (job.total_pages || job.total_files)
    ? Math.round(((job.done_pages || job.done_files || 0) / (job.total_pages || job.total_files || 1)) * 100)
    : 0

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <header className="h-16 border-b border-outline-variant bg-surface flex items-center justify-between px-6 flex-shrink-0">
        <div className="flex items-center gap-4">
          <Link to="/" className="flex items-center gap-2 text-on-surface-variant hover:text-primary transition-colors">
            <ArrowLeft size={18} />
            <span className="font-medium">새 변환</span>
          </Link>
          <div className="h-4 w-px bg-outline-variant"></div>
          <h1 className="font-headline-md text-headline-md font-bold text-on-surface">{job?.filename || jobId}</h1>
          {job?.status === 'done' && (
            <span className="px-3 py-1 bg-green-100 text-green-700 text-xs font-bold rounded-full flex items-center gap-1.5 border border-green-200">
              <span className="w-1.5 h-1.5 bg-green-600 rounded-full"></span>
              완료
            </span>
          )}
          {job?.status === 'error' && (
            <span className="px-3 py-1 bg-red-100 text-red-700 text-xs font-bold rounded-full flex items-center gap-1.5 border border-red-200">
              <XCircle size={12} />
              실패
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {job?.status === 'done' && sourceUrl && (
            <button
              onClick={() => setSidebarOpen((v) => !v)}
              title={sidebarOpen ? '원본/페이지 목록 숨기기' : '원본/페이지 목록 보이기'}
              className="flex items-center gap-1.5 px-3 py-2 bg-surface-container-high text-on-surface rounded-lg font-medium hover:bg-surface-container-high/80 transition-colors border border-outline-variant"
            >
              {sidebarOpen ? <PanelLeftClose size={16} /> : <PanelLeft size={16} />}
            </button>
          )}
          {job?.status === 'done' && (
            <>
              <button
                onClick={() => download('md')}
                className="flex items-center gap-1.5 px-3 py-2 bg-surface-container-high text-on-surface rounded-lg font-medium hover:bg-surface-container-high/80 transition-colors border border-outline-variant"
              >
                <FileText size={16} />
                .md
              </button>
              <button
                onClick={() => {
                  if (!job.xlsx_converted) {
                    if (!window.confirm(`CSV/XLSX 다운로드는 ${xlsxCost.toLocaleString()}P가 차감됩니다. 계속하시겠습니까?`)) return
                  }
                  download('csv')
                }}
                className="flex items-center gap-1.5 px-3 py-2 bg-surface-container-high text-on-surface rounded-lg font-medium hover:bg-surface-container-high/80 transition-colors border border-outline-variant"
              >
                <Table2 size={16} />
                {job.xlsx_converted ? '.csv' : `.csv - ${xlsxCost.toLocaleString()}P`}
              </button>
              <div className="relative group">
                <button className="flex items-center gap-1.5 px-3 py-2 bg-primary text-white rounded-lg font-bold hover:opacity-90 transition-colors shadow-sm">
                  <Download size={16} />
                  Office
                </button>
                <div className="absolute right-0 top-full mt-1 w-48 bg-white rounded-lg shadow-lg border border-outline-variant hidden group-hover:flex flex-col z-50 py-1">
                  <button
                    onClick={() => convertAndDownload('xlsx')}
                    disabled={converting}
                    className="text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
                  >
                    Excel (.xlsx) {job.xlsx_converted ? '(다운로드)' : `- ${xlsxCost.toLocaleString()}P`}
                  </button>
                  <button
                    onClick={() => convertAndDownload('docx')}
                    disabled={converting}
                    className="text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
                  >
                    Word (.docx) - 무료
                  </button>
                  <button
                    onClick={() => convertAndDownload('pptx')}
                    disabled={converting}
                    className="text-left px-4 py-2 text-sm hover:bg-surface-container-high text-on-surface"
                  >
                    PowerPoint (.pptx) - 무료
                  </button>
                </div>
              </div>
              <button
                onClick={saveMarkdown}
                disabled={saving}
                className="flex items-center gap-1.5 px-3 py-2 bg-green-600 text-white rounded-lg font-bold hover:opacity-90 transition-colors shadow-sm disabled:opacity-50"
              >
                {saving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                저장
              </button>
            </>
          )}
        </div>
      </header>

      {saveMessage && (
        <div className="bg-green-50 text-green-700 px-4 py-2 text-sm flex items-center gap-2 border-b border-green-200">
          <Check size={16} />
          {saveMessage}
        </div>
      )}

      {error && (
        <div className="bg-red-50 text-red-700 px-4 py-2 text-sm flex items-center gap-2 border-b border-red-200">
          <XCircle size={16} />
          {error}
        </div>
      )}

      {loading && !job && (
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="animate-spin text-primary" size={32} />
        </div>
      )}

      {job && job.status !== 'done' && job.status !== 'error' && (
        <div className="flex-1 flex flex-col items-center justify-center p-6">
          <Loader2 className="animate-spin text-primary mb-4" size={32} />
          <h2 className="text-lg font-semibold text-on-surface mb-2">{STATUS_LABEL[job.status] || job.status}</h2>
          <div className="w-full max-w-md h-2 bg-surface-container-high rounded-full overflow-hidden">
            <div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} />
          </div>
          <p className="text-sm text-on-surface-variant mt-2">
            {job.total_pages
              ? `${job.done_pages || 0} / ${job.total_pages} 페이지 (${pct}%)`
              : `${job.done_files || 0} / ${job.total_files} 파일 (${pct}%)`}
          </p>
        </div>
      )}

      {job?.status === 'error' && (
        <div className="flex-1 flex items-center justify-center p-6">
          <pre className="bg-red-50 text-red-700 text-xs p-4 rounded-lg whitespace-pre-wrap max-w-3xl">{job.error_log || '알 수 없는 오류'}</pre>
        </div>
      )}

      {job?.status === 'done' && !loading && needsPagedMode(job) && (
        <PagedResultViewer jobId={jobId} pages={pages} sourceUrl={sourceUrl} sourceType={sourceType} sidebarOpen={sidebarOpen} />
      )}

      {job?.status === 'done' && !loading && !needsPagedMode(job) && (
        <div className="flex-1 flex overflow-hidden min-h-0">
          {sidebarOpen && sourceUrl ? (
            <PanelGroup direction="horizontal" className="flex-1 flex">
              <Panel defaultSize={30} minSize={20} maxSize={60} className="flex flex-col min-h-0">
                {sourceType === 'pdf' ? (
                  <div className="flex flex-col h-full border-r border-outline-variant bg-surface-container-low">
                    <div className="p-4 flex items-center justify-between border-b border-outline-variant bg-white flex-shrink-0">
                      <h3 className="font-bold text-sm text-on-surface">원본 문서</h3>
                      <span className="text-[10px] text-outline font-mono bg-surface px-1.5 py-0.5 rounded border border-outline-variant truncate max-w-[200px]">
                        {job?.filename}
                      </span>
                    </div>
                    <div className="flex-1 min-h-0">
                      <PdfViewer url={sourceUrl} page={currentPdfPage} onPageChange={setCurrentPdfPage} />
                    </div>
                  </div>
                ) : sourceType === 'images' ? (
                  <div className="flex flex-col h-full border-r border-outline-variant bg-surface-container-low overflow-hidden">
                    <div className="p-4 border-b border-outline-variant bg-white flex-shrink-0">
                      <h3 className="font-bold text-sm text-on-surface">원본 이미지</h3>
                    </div>
                    <div className="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-4">
                      {imageUrls.map((url, idx) => (
                        <img
                          key={idx}
                          src={url}
                          alt={`원본 이미지 ${idx + 1}`}
                          className="w-full rounded border border-outline-variant bg-white shadow-sm"
                          loading="lazy"
                        />
                      ))}
                    </div>
                  </div>
                ) : sourceType === 'audio' || sourceType === 'video' ? (
                  <MediaPlayer sourceType={sourceType} url={sourceUrl} filename={job?.filename} />
                ) : (
                  <div className="flex flex-col h-full border-r border-outline-variant bg-surface-container-low p-4">
                    <h3 className="font-bold text-sm text-on-surface mb-2">원본 파일</h3>
                    <a
                      href={sourceUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="text-sm text-primary hover:underline truncate"
                    >
                      {job?.filename}
                    </a>
                    <p className="text-xs text-on-surface-variant mt-2">아카이브 파일은 다운로드 후 확인할 수 있습니다.</p>
                  </div>
                )}
              </Panel>
              <PanelResizeHandle className="w-2 bg-outline-variant/50 hover:bg-primary transition-colors cursor-col-resize" />
              <Panel className="flex flex-col min-h-0">
                <div className="flex flex-col h-full bg-white overflow-hidden">
                  <SimpleEditor ref={editorRef} markdown={markdown} editable />
                </div>
              </Panel>
            </PanelGroup>
          ) : (
            <div className="flex-1 flex flex-col bg-white overflow-hidden min-h-0">
              <SimpleEditor ref={editorRef} markdown={markdown} editable />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
