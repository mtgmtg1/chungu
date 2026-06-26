// [Flow: Step 1 (로그인/개발자 권한 확인) -> Step 2 (계정/키/사용량 데이터 로드) -> Step 3 (키 발급/삭제/복사 UI) -> Step 4 (사용량 차트 + Docs 렌더링)]
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { useAuth } from '../AuthContext.jsx'
import SidebarLayout from '../components/SidebarLayout.jsx'

const baseUrl = typeof window !== 'undefined' ? window.location.origin : ''

const curlExample = `curl -X POST ${baseUrl}/api/v1/jobs/upload \\
  -H "X-API-Key: <YOUR_API_KEY>" \\
  -F "files=@document.pdf" \\
  -F "pipeline=vision"`

export default function DeveloperPage() {
  const { user, loading } = useAuth()
  const navigate = useNavigate()
  const [account, setAccount] = useState(null)
  const [keys, setKeys] = useState([])
  const [pricing, setPricing] = useState(null)
  const [usage, setUsage] = useState([])
  const [transactions, setTransactions] = useState([])
  const [newKeyName, setNewKeyName] = useState('')
  const [revealedKey, setRevealedKey] = useState(null)
  const [error, setError] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [period, setPeriod] = useState('7')

  useEffect(() => {
    if (loading) return
    if (!user) {
      navigate('/login')
      return
    }
    loadAll()
  }, [user, loading, navigate])

  useEffect(() => {
    if (!user) return
    loadUsage()
  }, [user, period])

  const loadKeys = async () => {
    try {
      const k = await api.listApiKeys()
      setKeys(k)
    } catch (e) {
      console.error('API keys 로드 실패:', e)
      setError((prev) => prev || (e.message || 'API keys를 불러오지 못했습니다'))
    }
  }

  const loadUsage = async () => {
    try {
      const usg = await api.devUsage(parseInt(period, 10))
      setUsage(usg)
    } catch (e) {
      console.error('Usage 로드 실패:', e)
    }
  }

  const loadAll = async () => {
    try {
      setError('')
      const [acc, prc, tx] = await Promise.all([
        api.devAccount(),
        api.devPricing(),
        api.devTransactions(20),
      ])
      setAccount(acc)
      setPricing(prc)
      setTransactions(tx)
    } catch (e) {
      setError(e.message || '데이터를 불러오지 못했습니다')
    }
    await loadKeys()
  }

  const createKey = async () => {
    try {
      setError('')
      const res = await api.createApiKey({ name: newKeyName || 'default' })
      setKeys([res, ...keys])
      setRevealedKey(res)
      setNewKeyName('')
      setShowCreate(false)
      await loadKeys()
    } catch (e) {
      setError(e.message || 'key 생성 실패')
    }
  }

  const deleteKey = async (id) => {
    if (!confirm('이 API key를 삭제하시겠습니까?')) return
    try {
      await api.deleteApiKey(id)
      setKeys(keys.filter((k) => k.id !== id))
    } catch (e) {
      setError(e.message || 'key 삭제 실패')
    }
  }

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text)
  }

  const maxPoints = Math.max(1, ...usage.map((u) => u.points_spent || 0))
  const totalUsage = account?.today_usage?.points_spent || 0
  const balance = account?.points_balance || 0
  const limit = 12500
  const usagePct = Math.min(100, Math.round((totalUsage / limit) * 100))

  if (loading || !user) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  return (
    <SidebarLayout title="Developer Portal" subtitle="Manage your API keys, track usage, and explore the documentation">
      {error && (
        <div className="bg-error-container text-error px-4 py-3 rounded-xl text-sm border border-error/10 mb-8">
          {error}
        </div>
      )}

      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
        <div></div>
        <button
          onClick={() => setShowCreate(true)}
          className="bg-primary text-white px-6 py-2.5 rounded-lg flex items-center gap-2 font-body-md hover:bg-primary/90 transition-all shadow-sm"
        >
          <span className="material-symbols-outlined text-xl">add</span>
          Create New Key
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-gutter">
        <div className="lg:col-span-8 space-y-gutter">
          <div className="glass-panel p-6 rounded-2xl">
            <div className="flex justify-between items-center mb-6">
              <h3 className="font-headline-md text-headline-md text-on-surface">Usage Analytics</h3>
              <select
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
                className="bg-surface-container-low border-none rounded-lg text-label-sm py-1 pl-2 pr-8 focus:ring-1 focus:ring-primary focus:outline-none"
              >
                <option value="7">Last 7 Days</option>
                <option value="30">Last 30 Days</option>
              </select>
            </div>
            <div className="h-64 flex items-end gap-1 px-2 relative">
              <div className="absolute inset-0 flex items-center justify-center opacity-10 pointer-events-none">
                <span className="material-symbols-outlined text-9xl">monitoring</span>
              </div>
              {usage.map((u, i) => {
                const pct = Math.round(((u.points_spent || 0) / maxPoints) * 100)
                return (
                  <div key={u.day || i} className="flex-1 flex flex-col justify-end items-center group h-full">
                    <div
                      className="w-full bg-primary/20 rounded-t hover:bg-primary/40 transition-all cursor-pointer relative"
                      style={{ height: `${Math.max(4, pct)}%` }}
                    >
                      <div className="hidden group-hover:block absolute -top-8 left-1/2 -translate-x-1/2 bg-on-surface text-white text-[10px] py-1 px-2 rounded whitespace-nowrap">
                        {(u.points_spent || 0).toLocaleString()}P
                      </div>
                    </div>
                    <span className="text-[10px] text-outline mt-2">
                      {u.day ? new Date(u.day).toLocaleDateString('ko-KR', { weekday: 'short' }) : '-'}
                    </span>
                  </div>
                )
              })}
              {usage.length === 0 && (
                <div className="absolute inset-0 flex items-center justify-center text-outline text-sm">
                  No usage data yet
                </div>
              )}
            </div>
          </div>

          <div className="glass-panel rounded-2xl overflow-hidden">
            <div className="p-6 border-b border-outline-variant flex justify-between items-center">
              <h3 className="font-headline-md text-headline-md text-on-surface">API Keys</h3>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead className="bg-surface-container-low text-on-surface-variant font-label-sm text-label-sm uppercase tracking-wider">
                  <tr>
                    <th className="px-6 py-4">Label</th>
                    <th className="px-6 py-4">API Key</th>
                    <th className="px-6 py-4 text-right">Rate</th>
                    <th className="px-6 py-4 text-right">Created</th>
                    <th className="px-6 py-4 w-10"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-outline-variant text-body-md">
                  {keys.map((k) => (
                    <tr key={k.id} className="hover:bg-primary-container/5 transition-colors">
                      <td className="px-6 py-4 font-medium text-on-surface">{k.name}</td>
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-2">
                          <code className="bg-surface-container-high px-2 py-1 rounded text-primary-container font-mono text-sm">
                            {k.prefix}••••••••••••••••
                          </code>
                          <button
                            onClick={() => copyToClipboard(k.prefix + '••••••••••••••••')}
                            className="text-outline hover:text-primary transition-colors"
                            title="Copy"
                          >
                            <span className="material-symbols-outlined text-lg">content_copy</span>
                          </button>
                        </div>
                      </td>
                      <td className="px-6 py-4 text-right text-on-surface-variant">{k.rate_limit_rpm}/min</td>
                      <td className="px-6 py-4 text-right text-on-surface-variant">
                        {k.created_at ? new Date(k.created_at).toLocaleDateString('ko-KR') : '-'}
                      </td>
                      <td className="px-6 py-4">
                        <button
                          onClick={() => deleteKey(k.id)}
                          className="text-outline hover:text-error transition-colors"
                          title="Delete"
                        >
                          <span className="material-symbols-outlined text-lg">delete</span>
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="lg:col-span-4 space-y-gutter">
          <div className="glass-panel p-6 rounded-2xl">
            <div className="flex items-center gap-3 mb-6">
              <span className="material-symbols-outlined text-primary bg-primary/10 p-2 rounded-lg">speed</span>
              <h3 className="font-headline-md text-headline-md text-on-surface">Rate Limit</h3>
            </div>
            <div className="space-y-4">
              <div className="flex justify-between items-end">
                <div>
                  <p className="text-3xl font-bold text-on-surface">{totalUsage.toLocaleString()}</p>
                  <p className="text-on-surface-variant text-label-sm">Monthly API Calls</p>
                </div>
                <p className="text-outline text-label-sm">Limit: {limit.toLocaleString()}</p>
              </div>
              <div className="w-full bg-outline-variant/30 rounded-full h-3 overflow-hidden">
                <div className="bg-primary h-full rounded-full transition-all duration-1000 ease-out" style={{ width: `${usagePct}%` }}></div>
              </div>
              <div className="p-3 bg-secondary-container/30 border border-secondary/10 rounded-lg flex items-start gap-2">
                <span className="material-symbols-outlined text-secondary text-sm mt-0.5">info</span>
                <p className="text-[12px] text-on-secondary-fixed-variant leading-relaxed">
                  Your usage resets daily. Points balance: {balance.toLocaleString()}P.
                </p>
              </div>
            </div>
          </div>

          <div className="glass-panel rounded-2xl overflow-hidden">
            <div className="p-6 border-b border-outline-variant">
              <h3 className="font-headline-md text-headline-md text-on-surface">Quick Start</h3>
            </div>
            <div className="p-6 space-y-6">
              <div className="space-y-3">
                <div className="flex justify-between items-center">
                  <span className="text-label-sm font-bold text-outline">ENDPOINT</span>
                  <span className="text-label-sm px-2 py-0.5 bg-primary-container text-white rounded uppercase">POST</span>
                </div>
                <code className="block bg-surface-container-low p-2 rounded font-mono text-sm text-primary">/api/v1/jobs/upload</code>
              </div>
              <div className="space-y-4">
                <div className="flex border-b border-outline-variant">
                  <button className="px-4 py-2 text-primary border-b-2 border-primary font-label-sm">cURL</button>
                </div>
                <div className="code-block p-4 rounded-xl text-sm overflow-x-auto">
                  <pre><code>{curlExample}</code></pre>
                </div>
              </div>
              <a href={`${baseUrl}/api/v1/docs`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary font-body-md hover:underline">
                View full API reference
                <span className="material-symbols-outlined text-sm">arrow_forward</span>
              </a>
            </div>
          </div>

          <div className="glass-panel p-6 rounded-2xl">
            <div className="flex items-center gap-3 mb-4">
              <span className="material-symbols-outlined text-primary bg-primary/10 p-2 rounded-lg">payments</span>
              <h3 className="font-headline-md text-headline-md text-on-surface">Billing</h3>
            </div>
            <div className="space-y-3">
              <div className="flex justify-between text-body-md">
                <span className="text-on-surface-variant">Points balance</span>
                <span className="font-bold text-on-surface">{balance.toLocaleString()}P</span>
              </div>
              <div className="flex justify-between text-body-md">
                <span className="text-on-surface-variant">Today usage</span>
                <span className="font-bold text-on-surface">{account?.today_usage?.points_spent?.toLocaleString() || 0}P</span>
              </div>
              <div className="h-px bg-outline-variant/40 my-2"></div>
              <div className="space-y-1 text-[12px] text-on-surface-variant">
                <p>PDF page: {pricing?.rates?.krw_per_page || '-'}P</p>
                <p>Image: {pricing?.rates?.krw_per_image || '-'}P</p>
                <p>Audio/sec: {pricing?.rates?.krw_per_audio_second || '-'}P</p>
                <p>Video/sec: {pricing?.rates?.krw_per_video_second || '-'}P</p>
              </div>
              <button
                onClick={() => navigate('/payment')}
                className="w-full mt-2 bg-primary text-white rounded-lg py-2.5 font-body-md hover:bg-primary/90 transition-colors"
              >
                충전하기
              </button>
            </div>
          </div>
        </div>
      </div>

      {showCreate && (
        <div className="fixed inset-0 z-[60] bg-on-surface/30 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl border border-outline-variant shadow-2xl w-full max-w-md p-6">
            <h3 className="font-headline-md text-headline-md text-on-surface mb-4">Create New API Key</h3>
            <input
              type="text"
              placeholder="Key name (e.g., production)"
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
              className="w-full border border-outline-variant rounded-lg px-3 py-2.5 text-body-md mb-4 focus:ring-1 focus:ring-primary focus:outline-none"
            />
            {revealedKey && (
              <div className="mb-4 rounded-lg border border-amber-300 bg-amber-50 p-3">
                <p className="text-xs font-semibold text-amber-800 mb-2">Save this key now. It will not be shown again.</p>
                <pre className="rounded bg-white p-2 text-xs break-all text-on-surface">{revealedKey.key}</pre>
                <div className="flex gap-2 mt-2">
                  <button onClick={() => copyToClipboard(revealedKey.key)} className="rounded bg-amber-700 px-3 py-1 text-xs text-white hover:bg-amber-800">Copy</button>
                  <button onClick={() => setRevealedKey(null)} className="rounded bg-slate-200 px-3 py-1 text-xs text-slate-700 hover:bg-slate-300">Hide</button>
                </div>
              </div>
            )}
            <div className="flex gap-3">
              <button onClick={() => setShowCreate(false)} className="flex-1 border border-outline-variant rounded-lg py-2.5 font-body-md text-on-surface hover:bg-surface-container transition-colors">
                Cancel
              </button>
              <button onClick={createKey} className="flex-1 bg-primary text-white rounded-lg py-2.5 font-body-md hover:bg-primary/90 transition-colors">
                Create
              </button>
            </div>
          </div>
        </div>
      )}
    </SidebarLayout>
  )
}
