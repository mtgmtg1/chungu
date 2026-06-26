// [Flow: Step 1 (사용자/프로필 + 작업 목록 로드) -> Step 2 (종합 통계 계산) -> Step 3 (요약 카드 + 상태 분포 + 최근 작업 렌더링)]
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Coins, Loader2, ArrowRight, Upload, FileText, Eye, CreditCard } from 'lucide-react'
import { useAuth } from '../AuthContext.jsx'
import { api } from '../api.js'
import SidebarLayout from '../components/SidebarLayout.jsx'

const STATUS_LABEL = {
  pending: '결제 대기', queued: '대기 중', ocr: 'OCR 중', merging: '병합 중', done: '완료', error: '실패',
}

const STATUS_COLOR = {
  done: 'bg-green-50 text-green-700 border-green-100',
  error: 'bg-red-50 text-red-700 border-red-100',
  pending: 'bg-surface-container-high text-on-surface-variant border-outline-variant',
  queued: 'bg-primary-container/10 text-primary border-primary/10',
  ocr: 'bg-primary-container/10 text-primary border-primary/10',
  merging: 'bg-primary-container/10 text-primary border-primary/10',
}

export default function DashboardPage() {
  const { user, loading: authLoading } = useAuth()
  const navigate = useNavigate()
  const [profile, setProfile] = useState(null)
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!user) return
    load()
  }, [user])

  async function load() {
    setLoading(true)
    try {
      const [me, list] = await Promise.all([api.me(), api.listJobs()])
      setProfile(me)
      setJobs(list)
    } catch (e) {
      setError(e.message || '데이터를 불러오지 못했습니다')
    } finally {
      setLoading(false)
    }
  }

  const stats = useMemo(() => {
    const total = jobs.length
    const done = jobs.filter((j) => j.status === 'done').length
    const active = jobs.filter((j) => j.status !== 'done' && j.status !== 'error').length
    const error = jobs.filter((j) => j.status === 'error').length
    const totalPages = jobs.reduce((sum, j) => sum + (j.total_pages || j.total_files || 0), 0)
    const recent = [...jobs].sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 5)
    return { total, done, active, error, totalPages, recent }
  }, [jobs])

  function formatDate(dateStr) {
    if (!dateStr) return '-'
    return new Date(dateStr).toLocaleString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  }

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
          <p className="mb-4 text-on-surface-variant">로그인이 필요합니다</p>
          <button onClick={() => navigate('/login')} className="bg-primary text-on-primary px-4 py-2 rounded-lg">로그인</button>
        </div>
      </div>
    )
  }

  return (
    <SidebarLayout title="Dashboard" subtitle="Overview of your account and conversion activity">
      {error && (
        <div className="bg-red-50 text-red-700 px-4 py-3 rounded-lg mb-6 flex items-center gap-2 border border-red-200">
          <span className="material-symbols-outlined">error</span>
          {error}
        </div>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-gutter mb-stack-lg">
        <div className="glass-panel p-6 rounded-2xl">
          <div className="flex items-center justify-between mb-4">
            <p className="font-label-sm text-label-sm text-on-surface-variant">보유 포인트</p>
            <div className="p-2 bg-yellow-50 rounded-lg text-yellow-600">
              <Coins size={20} />
            </div>
          </div>
          <p className="text-3xl font-bold text-on-surface">{profile?.points_balance?.toLocaleString() ?? '-'} P</p>
          <Link to="/payment" className="mt-3 inline-flex items-center gap-1 text-primary text-sm font-medium hover:underline">
            <CreditCard size={14} /> 충전하기
          </Link>
        </div>

        <div className="glass-panel p-6 rounded-2xl">
          <div className="flex items-center justify-between mb-4">
            <p className="font-label-sm text-label-sm text-on-surface-variant">총 작업</p>
            <div className="p-2 bg-primary/10 rounded-lg text-primary">
              <span className="material-symbols-outlined">task</span>
            </div>
          </div>
          <p className="text-3xl font-bold text-on-surface">{stats.total}</p>
          <p className="mt-3 text-sm text-on-surface-variant">전체 변환 작업</p>
        </div>

        <div className="glass-panel p-6 rounded-2xl">
          <div className="flex items-center justify-between mb-4">
            <p className="font-label-sm text-label-sm text-on-surface-variant">완료</p>
            <div className="p-2 bg-green-50 rounded-lg text-green-600">
              <span className="material-symbols-outlined">check_circle</span>
            </div>
          </div>
          <p className="text-3xl font-bold text-on-surface">{stats.done}</p>
          <p className="mt-3 text-sm text-on-surface-variant">성공적으로 변환됨</p>
        </div>

        <div className="glass-panel p-6 rounded-2xl">
          <div className="flex items-center justify-between mb-4">
            <p className="font-label-sm text-label-sm text-on-surface-variant">처리 페이지</p>
            <div className="p-2 bg-secondary-container rounded-lg text-secondary">
              <span className="material-symbols-outlined">description</span>
            </div>
          </div>
          <p className="text-3xl font-bold text-on-surface">{stats.totalPages.toLocaleString()}</p>
          <p className="mt-3 text-sm text-on-surface-variant">누적 처리량</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-gutter mb-stack-lg">
        {/* Status breakdown */}
        <div className="lg:col-span-2 glass-panel rounded-2xl p-6">
          <h3 className="font-headline-md text-headline-md text-on-surface mb-6">Status Breakdown</h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {[
              { key: 'active', label: 'Active', value: stats.active },
              { key: 'done', label: 'Completed', value: stats.done },
              { key: 'error', label: 'Failed', value: stats.error },
              { key: 'pending', label: 'Pending', value: jobs.filter((j) => j.status === 'pending').length },
            ].map((item) => (
              <div key={item.key} className="p-4 bg-surface-container-low rounded-xl border border-outline-variant">
                <p className="text-sm text-on-surface-variant mb-1">{item.label}</p>
                <p className="text-2xl font-bold text-on-surface">{item.value}</p>
              </div>
            ))}
          </div>

          <div className="mt-6 space-y-3">
            {['done', 'active', 'error', 'pending'].map((key) => {
              const value = key === 'active' ? stats.active : stats[key]
              const pct = stats.total ? Math.round((value / stats.total) * 100) : 0
              const barColor = key === 'done' ? 'bg-green-500' : key === 'error' ? 'bg-red-500' : key === 'pending' ? 'bg-slate-400' : 'bg-primary'
              return (
                <div key={key}>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="text-on-surface-variant capitalize">{key}</span>
                    <span className="font-medium text-on-surface">{pct}%</span>
                  </div>
                  <div className="w-full bg-outline-variant/30 rounded-full h-2 overflow-hidden">
                    <div className={`${barColor} h-full rounded-full transition-all duration-1000`} style={{ width: `${pct}%` }}></div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Quick actions */}
        <div className="glass-panel rounded-2xl p-6">
          <h3 className="font-headline-md text-headline-md text-on-surface mb-6">Quick Actions</h3>
          <div className="space-y-3">
            <Link
              to="/"
              className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-primary text-on-primary rounded-xl font-body-md text-body-md font-medium hover:opacity-90 transition-all shadow-sm"
            >
              <Upload size={18} />
              Upload New Files
            </Link>
            <Link
              to="/jobs"
              className="w-full flex items-center justify-between px-4 py-3 bg-surface-container-low rounded-xl border border-outline-variant font-body-md text-body-md text-on-surface hover:bg-surface-container-high transition-colors"
            >
              <span className="flex items-center gap-2">
                <span className="material-symbols-outlined text-on-surface-variant">list_alt</span>
                View All Jobs
              </span>
              <ArrowRight size={16} className="text-outline" />
            </Link>
            <Link
              to="/developer"
              className="w-full flex items-center justify-between px-4 py-3 bg-surface-container-low rounded-xl border border-outline-variant font-body-md text-body-md text-on-surface hover:bg-surface-container-high transition-colors"
            >
              <span className="flex items-center gap-2">
                <span className="material-symbols-outlined text-on-surface-variant">code</span>
                Developer Portal
              </span>
              <ArrowRight size={16} className="text-outline" />
            </Link>
            <Link
              to="/payment"
              className="w-full flex items-center justify-between px-4 py-3 bg-surface-container-low rounded-xl border border-outline-variant font-body-md text-body-md text-on-surface hover:bg-surface-container-high transition-colors"
            >
              <span className="flex items-center gap-2">
                <span className="material-symbols-outlined text-on-surface-variant">account_balance_wallet</span>
                Buy Points
              </span>
              <ArrowRight size={16} className="text-outline" />
            </Link>
          </div>
        </div>
      </div>

      {/* Recent jobs */}
      <div className="glass-panel rounded-2xl overflow-hidden">
        <div className="p-6 border-b border-outline-variant flex justify-between items-center">
          <h3 className="font-headline-md text-headline-md text-on-surface">Recent Jobs</h3>
          <Link to="/jobs" className="text-primary text-sm font-medium hover:underline flex items-center gap-1">
            View all <ArrowRight size={14} />
          </Link>
        </div>
        <div className="overflow-x-auto custom-scrollbar">
          <table className="w-full text-left">
            <thead className="bg-surface-container-low/50 text-on-surface-variant font-label-sm text-label-sm uppercase tracking-wider">
              <tr>
                <th className="px-gutter py-4">File Name</th>
                <th className="px-gutter py-4">Status</th>
                <th className="px-gutter py-4">Date</th>
                <th className="px-gutter py-4 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/50">
              {loading ? (
                <tr>
                  <td colSpan={4} className="text-center py-12">
                    <Loader2 className="animate-spin mx-auto text-primary" size={24} />
                  </td>
                </tr>
              ) : (
                stats.recent.map((j) => {
                  const chipClass = STATUS_COLOR[j.status] || STATUS_COLOR.pending
                  return (
                    <tr key={j.job_id} className="hover:bg-surface-container/30 transition-colors">
                      <td className="px-gutter py-4 font-body-md text-body-md text-on-surface">{j.filename}</td>
                      <td className="px-gutter py-4">
                        <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border ${chipClass}`}>
                          <span className="material-symbols-outlined text-[14px]">
                            {j.status === 'done' ? 'check_circle' : j.status === 'error' ? 'cancel' : 'refresh'}
                          </span>
                          {STATUS_LABEL[j.status] || j.status}
                        </span>
                      </td>
                      <td className="px-gutter py-4 font-body-md text-body-md text-on-surface-variant">{formatDate(j.created_at)}</td>
                      <td className="px-gutter py-4 text-right">
                        {j.status === 'done' ? (
                          <Link
                            to={`/jobs/${j.job_id}`}
                            className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-surface-container-high text-on-surface hover:text-primary hover:bg-surface-container transition-colors"
                          >
                            <Eye size={14} /> View
                          </Link>
                        ) : (
                          <span className="text-outline">-</span>
                        )}
                      </td>
                    </tr>
                  )
                })
              )}
              {!loading && stats.recent.length === 0 && (
                <tr>
                  <td colSpan={4} className="text-center py-12 text-on-surface-variant">
                    <p>최근 작업이 없습니다.</p>
                    <Link to="/" className="text-primary hover:underline mt-2 inline-flex items-center gap-1">
                      <Upload size={14} /> 첫 파일 업로드하기
                    </Link>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* API promo */}
      <div className="mt-stack-lg grid grid-cols-1 md:grid-cols-3 gap-gutter">
        <div className="col-span-1 md:col-span-2 glass-surface p-gutter rounded-2xl border border-primary/10 flex items-start gap-4">
          <div className="p-3 rounded-xl bg-primary/10 text-primary">
            <span className="material-symbols-outlined">lightbulb</span>
          </div>
          <div>
            <h4 className="font-headline-md text-headline-md text-primary mb-2">Automate with API</h4>
            <p className="font-body-md text-body-md text-on-surface-variant max-w-xl">
              Stop manual uploads. Connect your data pipeline directly to our API for seamless, real-time conversion and validation.
            </p>
            <Link to="/developer" className="mt-4 text-primary font-body-md text-body-md font-bold hover:underline inline-flex items-center gap-1">
              View API documentation <ArrowRight size={16} />
            </Link>
          </div>
        </div>
      </div>
    </SidebarLayout>
  )
}
