// [Flow: Step 1 (job ID로 진입) -> Step 2 (작업 정보 로드) -> Step 3 (비용 확인 + 고급 옵션) -> Step 4 (승인 -> 결과 페이지 이동)]
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Loader2, CreditCard, Settings2 } from 'lucide-react'
import { api } from '../api.js'

export default function JobConfirmPage() {
  const { jobId } = useParams()
  const nav = useNavigate()
  const [job, setJob] = useState(null)
  const [profile, setProfile] = useState(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [pipeline, setPipeline] = useState('vision')
  const [columns, setColumns] = useState('')
  const [prompt, setPrompt] = useState('')

  useEffect(() => {
    if (!jobId) return
    load()
  }, [jobId])

  async function load() {
    try {
      const [jobData, me] = await Promise.all([api.getJob(jobId), api.me()])
      setJob(jobData)
      setProfile(me)
      setPipeline(jobData.pipeline || 'vision')
    } catch (e) {
      setError(e.message || '작업 정보를 불러오지 못했습니다')
    } finally {
      setLoading(false)
    }
  }

  async function confirm() {
    setSubmitting(true)
    setError('')
    try {
      await api.confirmJob(jobId)
      nav(`/jobs/${jobId}`)
    } catch (e) {
      setError(e.message || '승인 실패')
      if (e.message && e.message.includes('포인트')) nav('/payment')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <Loader2 className="animate-spin text-primary" size={32} />
      </div>
    )
  }

  if (!job) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-center">
          <p className="text-on-surface-variant mb-4">{error || '작업을 찾을 수 없습니다'}</p>
          <Link to="/" className="text-primary hover:underline">홈으로</Link>
        </div>
      </div>
    )
  }

  const balance = profile?.points_balance ?? job.balance ?? 0
  const cost = job.cost?.points ?? 0
  const insufficient = balance < cost

  return (
    <div className="min-h-screen bg-background text-on-background flex flex-col">
      <nav className="w-full bg-transparent">
        <div className="max-w-container-max mx-auto flex justify-between items-center h-20 px-gutter">
          <Link to="/" className="font-headline-md text-headline-md font-bold text-primary tracking-tight">Chungu</Link>
        </div>
      </nav>

      <main className="flex-grow flex items-center justify-center px-gutter py-12">
        <div className="w-full max-w-xl bg-white rounded-[32px] border border-outline-variant shadow-xl shadow-primary/5 p-8 md:p-10">
          <div className="flex items-center gap-2 mb-6">
            <Link to="/" className="text-on-surface-variant hover:text-primary transition-colors">
              <ArrowLeft size={20} />
            </Link>
            <h1 className="text-headline-lg font-bold text-on-surface">변환 비용 확인</h1>
          </div>

          <p className="text-body-md text-on-surface-variant mb-6">{job.filename}</p>

          <div className="bg-surface-container-low rounded-2xl p-6 space-y-3 mb-6">
            <div className="flex justify-between text-body-md">
              <span className="text-on-surface-variant">파일 유형</span>
              <span className="font-medium text-on-surface">{job.file_type}</span>
            </div>
            {job.total_pages > 0 && (
              <div className="flex justify-between text-body-md">
                <span className="text-on-surface-variant">총 페이지</span>
                <span className="font-medium text-on-surface">{job.total_pages}</span>
              </div>
            )}
            {job.total_files > 0 && (
              <div className="flex justify-between text-body-md">
                <span className="text-on-surface-variant">총 파일 수</span>
                <span className="font-medium text-on-surface">{job.total_files}</span>
              </div>
            )}
            {job.media_duration_seconds > 0 && (
              <div className="flex justify-between text-body-md">
                <span className="text-on-surface-variant">미디어 길이</span>
                <span className="font-medium text-on-surface">{job.media_duration_seconds}초</span>
              </div>
            )}
            <div className="h-px bg-outline-variant/40 my-2"></div>
            <div className="flex justify-between text-body-md">
              <span className="text-on-surface-variant">필요 포인트</span>
              <span className="font-bold text-primary">{cost} P</span>
            </div>
            <div className="flex justify-between text-body-md">
              <span className="text-on-surface-variant">내 잔액</span>
              <span className="font-medium text-on-surface">{balance} P</span>
            </div>
          </div>

          <details className="mb-6 group">
            <summary className="flex items-center gap-2 cursor-pointer text-body-md text-on-surface-variant hover:text-primary transition-colors">
              <Settings2 size={18} />
              <span>고급 옵션</span>
            </summary>
            <div className="mt-4 space-y-4 bg-surface-container-low rounded-2xl p-5">
              <div>
                <label className="block text-sm font-medium text-on-surface mb-2">분석 방식</label>
                <div className="flex gap-3">
                  {[['vision', 'Vision (정확도 높음)'], ['hybrid', 'Hybrid (저렴)']].map(([v, label]) => (
                    <button
                      key={v}
                      type="button"
                      onClick={() => setPipeline(v)}
                      className={`flex-1 border rounded-lg px-3 py-2 text-sm text-left transition-colors ${
                        pipeline === v ? 'border-primary bg-primary/5 text-primary' : 'border-outline-variant text-on-surface'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-on-surface mb-1">추출 컬럼 (콤마 구분)</label>
                <input
                  value={columns}
                  onChange={(e) => setColumns(e.target.value)}
                  placeholder="연번, 거래일자, 출금금액, 입금금액, 적요"
                  className="w-full border border-outline-variant rounded-lg px-3 py-2 bg-white"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-on-surface mb-1">추가 지시 (선택)</label>
                <textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  rows={2}
                  placeholder="예: 합계 행은 제외하세요."
                  className="w-full border border-outline-variant rounded-lg px-3 py-2 bg-white"
                />
              </div>
            </div>
          </details>

          {insufficient && (
            <div className="mb-6 p-4 bg-red-50 text-red-700 rounded-xl border border-red-200 text-sm">
              <p className="font-medium mb-2">포인트가 부족합니다</p>
              <Link to="/payment" className="inline-flex items-center gap-1 underline">
                <CreditCard size={14} /> 포인트 충전하기
              </Link>
            </div>
          )}

          {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

          <div className="flex gap-3">
            <Link to="/" className="flex-1 border border-outline-variant rounded-xl py-3 text-center font-medium text-on-surface hover:bg-surface-container transition-colors">
              취소
            </Link>
            <button
              onClick={confirm}
              disabled={submitting || insufficient}
              className="flex-1 bg-primary text-on-primary rounded-xl py-3 font-medium hover:bg-primary-container transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {submitting ? <><Loader2 className="animate-spin" size={18} /> 처리 중…</> : `${cost}P 차감하고 시작`}
            </button>
          </div>
        </div>
      </main>
    </div>
  )
}
