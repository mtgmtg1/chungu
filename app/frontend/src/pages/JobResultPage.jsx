// [Flow: Step 1 (job ID로 진입) -> Step 2 (작업 상태 폴링) -> Step 3 (완료 시 preview API 호출) -> Step 4 (시트 탭 + Excel 그리드 렌더링) -> Step 5 (XLSX 다운로드)]
import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Download, FileSpreadsheet, Loader2, XCircle } from 'lucide-react'
import { api } from '../api.js'

const STATUS_LABEL = {
  pending: '결제 대기', queued: '대기 중', rendering: 'PDF 렌더링', ocr: 'OCR 분석 중',
  merging: '표 병합 중', done: '완료', error: '실패',
}

export default function JobResultPage() {
  const { jobId } = useParams()
  const [job, setJob] = useState(null)
  const [sheets, setSheets] = useState({})
  const [activeSheet, setActiveSheet] = useState('')
  const [sourceUrl, setSourceUrl] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const pollRef = useRef(null)

  useEffect(() => {
    if (!jobId) return
    loadJob()
    return () => clearInterval(pollRef.current)
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
      setSheets(preview.sheets || {})
      setSourceUrl(preview.source_url)
      const first = Object.keys(preview.sheets || {})[0]
      if (first) setActiveSheet(first)
    } catch (e) {
      setError(e.message || '결과 미리보기를 불러오지 못했습니다')
    } finally {
      setLoading(false)
    }
  }

  async function downloadXlsx() {
    const { download_url } = await api.downloadJob(jobId, 'xlsx')
    window.open(download_url, '_blank')
  }

  const pct = job && (job.total_pages || job.total_files)
    ? Math.round(((job.done_pages || job.done_files || 0) / (job.total_pages || job.total_files || 1)) * 100)
    : 0

  const currentRows = sheets[activeSheet] || []
  const headers = currentRows[0] || []
  const rows = currentRows.slice(1)

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
        <div className="flex items-center gap-4">
          <button
            onClick={downloadXlsx}
            disabled={job?.status !== 'done'}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg font-bold hover:opacity-90 transition-all shadow-sm disabled:opacity-50"
          >
            <Download size={18} />
            .xlsx 다운로드
          </button>
        </div>
      </header>

      {loading && !job && (
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="animate-spin text-primary" size={32} />
        </div>
      )}

      {error && (
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="bg-red-50 text-red-700 px-6 py-4 rounded-lg border border-red-200 max-w-xl text-center">
            <p className="font-medium">{error}</p>
          </div>
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

      {job?.status === 'done' && !loading && (
        <>
          <div className="bg-surface-container-low border-b border-outline-variant px-6 flex items-end h-10 flex-shrink-0">
            <div className="flex gap-1">
              {Object.keys(sheets).map((name) => (
                <button
                  key={name}
                  onClick={() => setActiveSheet(name)}
                  className={`px-4 h-8 flex items-center gap-2 text-sm rounded-t-lg border-t border-x transition-colors ${
                    activeSheet === name
                      ? 'bg-white border-outline-variant text-primary font-bold'
                      : 'hover:bg-surface-container-high text-on-surface-variant font-medium border-transparent'
                  }`}
                >
                  <FileSpreadsheet size={14} />
                  {name}
                </button>
              ))}
            </div>
          </div>

          <div className="flex-1 flex overflow-hidden">
            {sourceUrl && (
              <div className="w-[420px] border-r border-outline-variant flex flex-col bg-surface-container-low flex-shrink-0">
                <div className="p-4 flex items-center justify-between border-b border-outline-variant bg-white">
                  <h3 className="font-bold text-sm text-on-surface flex items-center gap-2">
                    <span className="text-primary">원본 문서</span>
                  </h3>
                  <span className="text-[10px] text-outline font-mono bg-surface px-1.5 py-0.5 rounded border border-outline-variant truncate max-w-[200px]">
                    {job?.filename}
                  </span>
                </div>
                <div className="flex-1 p-4 overflow-auto custom-scrollbar">
                  <iframe src={sourceUrl} className="w-full h-full rounded-lg border border-outline-variant bg-white" title="source preview" />
                </div>
              </div>
            )}

            <div className="flex-1 flex flex-col bg-white overflow-hidden">
              <div className="flex-1 overflow-auto custom-scrollbar">
                <table className="w-full border-collapse table-fixed min-w-[800px]">
                  <thead className="sticky top-0 z-20">
                    <tr>
                      <th className="w-10 bg-slate-100 border-r border-b border-outline-variant text-[10px] text-outline font-bold text-center"></th>
                      {headers.map((h, i) => (
                        <th
                          key={i}
                          className="px-3 border-r border-b border-outline-variant text-xs font-bold text-on-surface text-left bg-slate-50 h-10 truncate"
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, rowIdx) => (
                      <tr key={rowIdx} className="h-10 hover:bg-primary-container/5">
                        <td className="bg-slate-50 border-r border-b border-outline-variant text-[10px] text-outline font-bold text-center">
                          {rowIdx + 1}
                        </td>
                        {row.map((cell, cellIdx) => (
                          <td
                            key={cellIdx}
                            className="px-3 border-r border-b border-outline-variant text-xs text-on-surface truncate font-mono"
                            title={cell}
                          >
                            {cell}
                          </td>
                        ))}
                      </tr>
                    ))}
                    {rows.length === 0 && (
                      <tr>
                        <td colSpan={headers.length + 1} className="text-center py-12 text-on-surface-variant">
                          데이터가 없습니다
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <div className="h-8 bg-primary border-t border-primary/20 flex items-center justify-between px-4 flex-shrink-0 text-white text-[11px]">
                <div className="flex gap-4 items-center">
                  <div className="flex items-center gap-1">
                    <span className="opacity-70">Rows:</span> <span className="font-bold">{rows.length}</span>
                  </div>
                  <div className="h-3 w-px bg-white/20"></div>
                  <div className="flex items-center gap-1">
                    <span className="opacity-70">Sheet:</span> <span className="font-bold">{activeSheet}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
