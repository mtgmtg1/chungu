// [Flow: Step 1 (사용자 정보/잔액 로드) -> Step 2 (작업 내역 조회) -> Step 3 (목록 표시 + 다운로드 버튼)]
import { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Coins, History, Download, Loader2, LogOut, CreditCard, Eye } from 'lucide-react'
import { useAuth } from '../AuthContext.jsx'
import { api } from '../api.js'

const STATUS_LABEL = {
  pending: '결제 대기', queued: '대기 중', ocr: 'OCR 중', merging: '병합 중', done: '완료', error: '실패',
}

export default function DashboardPage() {
  const { user, loading: authLoading, signOut } = useAuth()
  const [profile, setProfile] = useState(null)
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const nav = useNavigate()

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
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function download(id, type) {
    const { download_url } = await api.downloadJob(id, type)
    const job = jobs.find((j) => j.job_id === id)
    const base = job?.filename ? job.filename.replace(/\.[^/.]+$/, '') : 'result'
    const ext = type === 'xlsx' ? 'xlsx' : type
    const filename = `${base}.${ext}`
    const a = document.createElement('a')
    a.href = download_url
    a.download = filename
    a.style.display = 'none'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }

  if (authLoading || (!user && !error)) {
    return <div className="min-h-screen flex items-center justify-center"><Loader2 className="animate-spin" /></div>
  }

  if (!user) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <p className="mb-4">로그인이 필요합니다</p>
          <button onClick={() => nav('/login')} className="bg-blue-600 text-white px-4 py-2 rounded-lg">로그인</button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b bg-white">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <h1 className="text-xl font-bold">Chungu · 내 작업</h1>
          <div className="flex items-center gap-4">
            <Link to="/payment" className="flex items-center gap-1 text-blue-600 hover:underline"><CreditCard size={18} /> 포인트 충전</Link>
            <Link to="/" className="text-slate-500 hover:text-slate-800">새 변환</Link>
            <button onClick={() => signOut()} className="text-slate-400 hover:text-slate-700"><LogOut size={20} /></button>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
          <div className="bg-white rounded-xl border p-5 flex items-center gap-4">
            <Coins className="text-yellow-500" size={28} />
            <div>
              <p className="text-sm text-slate-500">보유 포인트</p>
              <p className="text-2xl font-bold">{profile?.points_balance ?? '-'} P</p>
            </div>
          </div>
          <div className="bg-white rounded-xl border p-5 flex items-center gap-4">
            <History className="text-blue-500" size={28} />
            <div>
              <p className="text-sm text-slate-500">총 작업</p>
              <p className="text-2xl font-bold">{jobs.length}</p>
            </div>
          </div>
          <div className="bg-white rounded-xl border p-5 flex items-center justify-center">
            <Link to="/payment" className="bg-blue-600 text-white px-4 py-2 rounded-lg font-medium hover:bg-blue-700">포인트 충전하기</Link>
          </div>
        </div>

        {loading ? <div className="text-center py-12"><Loader2 className="animate-spin mx-auto" /></div> : (
          <div className="bg-white rounded-xl border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-100">
                <tr>
                  <th className="text-left px-4 py-3">파일명</th>
                  <th className="text-left px-4 py-3">상태</th>
                  <th className="text-left px-4 py-3">페이지</th>
                  <th className="text-left px-4 py-3">비용</th>
                  <th className="text-left px-4 py-3">날짜</th>
                  <th className="text-right px-4 py-3">다운로드</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.job_id} className="border-t">
                    <td className="px-4 py-3">{j.filename}</td>
                    <td className="px-4 py-3">{STATUS_LABEL[j.status] || j.status}</td>
                    <td className="px-4 py-3">{j.total_pages}</td>
                    <td className="px-4 py-3">{j.cost_points} P</td>
                    <td className="px-4 py-3">{new Date(j.created_at).toLocaleString('ko-KR')}</td>
                    <td className="px-4 py-3 text-right">
                      {j.status === 'done' ? (
                        <div className="flex justify-end gap-2">
                          <Link to={`/jobs/${j.job_id}`} className="text-primary hover:underline flex items-center gap-1"><Eye size={14} /> 보기</Link>
                          <button onClick={() => download(j.job_id, 'xlsx')} className="text-blue-600 hover:underline flex items-center gap-1"><Download size={14} /> Excel</button>
                        </div>
                      ) : (
                        <span className="text-slate-400">-</span>
                      )}
                    </td>
                  </tr>
                ))}
                {jobs.length === 0 && (
                  <tr><td colSpan={6} className="text-center py-8 text-slate-500">작업 내역이 없습니다. <Link to="/" className="text-blue-600 hover:underline">첫 파일 변환하기</Link></td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  )
}
