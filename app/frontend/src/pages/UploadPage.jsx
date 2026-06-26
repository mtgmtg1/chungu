// [Flow: Step 1 (로그인 확인) -> Step 2 (파일/옵션 입력) -> Step 3 (업로드 -> 비용 안내) -> Step 4 (승인 -> 포인트 차감 + OCR) -> Step 5 (상태 폴링) -> Step 6 (다운로드)]
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { FileUp, Loader2, CheckCircle2, XCircle, Download, Settings, LogIn, Coins, CreditCard } from 'lucide-react'
import { useAuth } from '../AuthContext.jsx'
import { api } from '../api.js'

const STATUS_LABEL = {
  pending: '결제 대기', queued: '대기 중', rendering: 'PDF 렌더링', ocr: 'OCR 분석 중',
  merging: '표 병합 중', done: '완료', error: '실패',
}

export default function UploadPage() {
  const { user, loading: authLoading } = useAuth()
  const nav = useNavigate()
  const [files, setFiles] = useState([])
  const [pipeline, setPipeline] = useState('vision')
  const [columns, setColumns] = useState('')
  const [prompt, setPrompt] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [job, setJob] = useState(null)
  const [profile, setProfile] = useState(null)
  const [error, setError] = useState('')
  const pollRef = useRef(null)

  useEffect(() => {
    if (!user) return
    api.me().then(setProfile).catch(() => {})
  }, [user])

  useEffect(() => () => clearInterval(pollRef.current), [])

  function startPolling(jobId) {
    clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const data = await api.getJob(jobId)
        setJob(data)
        if (data.status === 'done' || data.status === 'error') clearInterval(pollRef.current)
      } catch (e) { /* 무시 */ }
    }, 2000)
  }

  async function handleUpload(e) {
    e.preventDefault()
    setError('')
    if (!user) return nav('/login')
    if (!files.length) return setError('파일을 선택하세요')

    const fd = new FormData()
    files.forEach((f) => fd.append('files', f))
    fd.append('pipeline', pipeline)
    fd.append('columns', columns)
    fd.append('prompt', prompt)

    setSubmitting(true)
    try {
      const res = await api.uploadJob(fd)
      setJob({ ...res, status: 'pending' })
      setProfile((p) => p && { ...p, points_balance: res.balance })
    } catch (e) {
      setError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  async function confirmPayment() {
    if (!job) return
    setSubmitting(true)
    try {
      const res = await api.confirmJob(job.job_id)
      setJob((j) => ({ ...j, status: res.status }))
      setProfile((p) => p && { ...p, points_balance: res.remaining_points })
      startPolling(job.job_id)
    } catch (e) {
      setError(e.message)
      if (e.message.includes('포인트')) nav('/payment')
    } finally {
      setSubmitting(false)
    }
  }

  async function download(type) {
    const { download_url } = await api.downloadJob(job.job_id, type)
    window.open(download_url, '_blank')
  }

  const pct = job && (job.total_pages || job.total_files)
    ? Math.round(((job.done_pages || job.done_files || 0) / (job.total_pages || job.total_files || 1)) * 100)
    : 0

  if (authLoading) return <div className="min-h-screen flex items-center justify-center"><Loader2 className="animate-spin" /></div>

  return (
    <div className="min-h-screen">
      <header className="border-b bg-white">
        <div className="max-w-3xl mx-auto px-6 py-4 flex items-center justify-between">
          <h1 className="text-xl font-bold">Chungu · PDF → CSV/MD 변환</h1>
          <div className="flex items-center gap-4">
            {user ? (
              <>
                <Link to="/dashboard" className="text-sm text-slate-600 hover:text-slate-900">내 작업</Link>
                <Link to="/developer" className="text-sm text-slate-600 hover:text-slate-900">API</Link>
                <Link to="/payment" className="text-sm flex items-center gap-1 text-blue-600 hover:underline"><Coins size={16} /> {profile?.points_balance ?? '-'} P</Link>
              </>
            ) : (
              <Link to="/login" className="text-sm flex items-center gap-1 text-blue-600 hover:underline"><LogIn size={16} /> 로그인</Link>
            )}
            <a href="/admin" className="text-slate-400 hover:text-slate-700" title="관리자"><Settings size={20} /></a>
          </div>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-10">
        {!job && (
          <form onSubmit={handleUpload} className="bg-white rounded-xl shadow-sm border p-8 space-y-6">
            <label className="block border-2 border-dashed border-slate-300 rounded-lg p-8 text-center cursor-pointer hover:border-blue-400 transition">
              <FileUp className="mx-auto mb-3 text-slate-400" size={40} />
              <span className="text-slate-600">
                {files.length > 0 ? <b>{files.length}개 파일 선택됨</b> : 'PDF/이미지/오디오/비디오/압축 파일을 선택하거나 드래그하세요'}
              </span>
              <input type="file" multiple accept=".pdf,.zip,.rar,.7z,.tar.gz,.png,.jpg,.jpeg,.gif,.webp,.mp3,.wav,.mp4,.avi,.mov,.mkv,.webm" className="hidden"
                onChange={(e) => setFiles(Array.from(e.target.files || []))} />
            </label>
            {files.length > 0 && (
              <ul className="mt-3 text-sm text-slate-600 space-y-1">
                {files.map((f, i) => (
                  <li key={i} className="flex items-center gap-2">
                    <span className="bg-slate-100 px-2 py-0.5 rounded">{f.name}</span>
                    <span className="text-slate-400">({(f.size / 1024 / 1024).toFixed(2)} MB)</span>
                  </li>
                ))}
              </ul>
            )}

            <div>
              <label className="block text-sm font-medium mb-1">분석 방식</label>
              <div className="flex gap-3">
                {[['vision', 'Vision (이미지 직접 분석 · 표 정확도 높음)'], ['hybrid', 'Hybrid (Tesseract + LLM · 저렴)']].map(([v, label]) => (
                  <button type="button" key={v} onClick={() => setPipeline(v)}
                    className={`flex-1 border rounded-lg px-3 py-2 text-sm text-left ${pipeline === v ? 'border-blue-500 bg-blue-50' : 'border-slate-200'}`}>
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <details className="text-sm">
              <summary className="cursor-pointer text-slate-500">고급 옵션 (컬럼 · 추가 지시)</summary>
              <div className="mt-3 space-y-3">
                <div>
                  <label className="block text-sm font-medium mb-1">추출 컬럼 (콤마 구분, 비우면 기본값)</label>
                  <input value={columns} onChange={(e) => setColumns(e.target.value)}
                    placeholder="연번, 거래일자, 출금금액, 입금금액, 적요"
                    className="w-full border rounded-lg px-3 py-2" />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">추가 지시 (선택)</label>
                  <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={2}
                    placeholder="예: 합계 행은 제외하세요."
                    className="w-full border rounded-lg px-3 py-2" />
                </div>
              </div>
            </details>

            {error && <p className="text-red-600 text-sm">{error}</p>}

            <button type="submit" disabled={submitting}
              className="w-full bg-blue-600 text-white rounded-lg py-3 font-medium hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center gap-2">
              {submitting ? <><Loader2 className="animate-spin" size={18} /> 업로드 중…</> : '업로드 및 비용 확인'}
            </button>

            {!user && <p className="text-sm text-slate-500 text-center">업로드 전 <Link to="/login" className="text-blue-600 hover:underline">로그인</Link>이 필요합니다.</p>}
          </form>
        )}

        {job && job.status === 'pending' && (
          <div className="bg-white rounded-xl shadow-sm border p-8 space-y-5">
            <h2 className="text-lg font-semibold">변환 비용 확인</h2>
            <p className="text-sm text-slate-500">{job.filename}</p>
            <div className="bg-slate-50 rounded-lg p-4 space-y-1">
              <p className="text-sm">파일 유형: <b>{job.file_type}</b></p>
              {job.total_pages > 0 && <p className="text-sm">총 페이지: <b>{job.total_pages}</b></p>}
              {job.total_files > 0 && <p className="text-sm">총 파일 수: <b>{job.total_files}</b></p>}
              {job.media_duration_seconds > 0 && <p className="text-sm">미디어 길이: <b>{job.media_duration_seconds}초</b></p>}
              <p className="text-sm">필요 포인트: <b>{job.cost?.points} P</b></p>
              <p className="text-sm">내 잔액: <b>{profile?.points_balance ?? job.balance} P</b></p>
            </div>
            {(profile?.points_balance || job.balance) < job.cost?.points && (
              <p className="text-red-600 text-sm">포인트가 부족합니다. <Link to="/payment" className="underline flex items-center gap-1 inline-flex"><CreditCard size={14} /> 충전하기</Link></p>
            )}
            <div className="flex gap-3">
              <button onClick={() => setJob(null)} className="flex-1 border rounded-lg py-2.5">취소</button>
              <button onClick={confirmPayment} disabled={submitting || (profile?.points_balance || job.balance) < job.cost?.points}
                className="flex-1 bg-blue-600 text-white rounded-lg py-2.5 font-medium hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center gap-2">
                {submitting ? <Loader2 className="animate-spin" size={18} /> : `${job.cost?.points}P 차감하고 시작`}
              </button>
            </div>
          </div>
        )}

        {job && job.status !== 'pending' && (
          <div className="bg-white rounded-xl shadow-sm border p-8 space-y-5">
            <div className="flex items-center gap-2">
              {job.status === 'done' && <CheckCircle2 className="text-green-600" />}
              {job.status === 'error' && <XCircle className="text-red-600" />}
              {!['done', 'error'].includes(job.status) && <Loader2 className="animate-spin text-blue-600" />}
              <h2 className="text-lg font-semibold">{STATUS_LABEL[job.status] || job.status}</h2>
            </div>
            <p className="text-sm text-slate-500">{job.filename}</p>

            {!['done', 'error'].includes(job.status) && (
              <div>
                <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                  <div className="h-full bg-blue-500 transition-all" style={{ width: `${pct}%` }} />
                </div>
                <p className="text-sm text-slate-500 mt-2">
                  {job.total_pages
                    ? `${job.done_pages || 0} / ${job.total_pages} 페이지 (${pct}%)`
                    : `${job.done_files || 0} / ${job.total_files} 파일 (${pct}%)`}
                </p>
              </div>
            )}

            {job.status === 'done' && (
              <div className="flex flex-col gap-3">
                <button onClick={() => download('xlsx')}
                  className="w-full bg-blue-600 text-white rounded-lg py-2.5 text-center font-medium hover:bg-blue-700 flex items-center justify-center gap-2">
                  <Download size={18} /> Excel (.xlsx) 다운로드
                </button>
                <div className="flex gap-3">
                  <button onClick={() => download('csv')}
                    className="flex-1 bg-slate-700 text-white rounded-lg py-2.5 text-center font-medium hover:bg-slate-800 flex items-center justify-center gap-2">
                    <Download size={18} /> CSV
                  </button>
                  <button onClick={() => download('md')}
                    className="flex-1 bg-green-600 text-white rounded-lg py-2.5 text-center font-medium hover:bg-green-700 flex items-center justify-center gap-2">
                    <Download size={18} /> Markdown
                  </button>
                </div>
              </div>
            )}

            {job.status === 'error' && (
              <pre className="bg-red-50 text-red-700 text-xs p-3 rounded-lg whitespace-pre-wrap">{job.error_log || '알 수 없는 오류'}</pre>
            )}

            <button onClick={() => { setJob(null); setFiles([]) }} className="text-sm text-slate-500 hover:text-slate-800">
              ← 새 파일 변환하기
            </button>
          </div>
        )}
      </main>
    </div>
  )
}
