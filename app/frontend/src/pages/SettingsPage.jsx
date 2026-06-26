// [Flow: Step 1 (인증 확인) -> Step 2 (계정/키/결제 데이터 로드) -> Step 3 (탭별 UI 렌더링) -> Step 4 (API key 관리 및 비밀번호 변경)]
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { useAuth } from '../AuthContext.jsx'
import { supabase } from '../supabase.js'
import SidebarLayout from '../components/SidebarLayout.jsx'

const TABS = [
  { id: 'api', label: 'API Keys', icon: 'key' },
  { id: 'billing', label: 'Billing & Recharge', icon: 'payments' },
  { id: 'rate', label: 'Rate Limit', icon: 'speed' },
  { id: 'account', label: 'Account', icon: 'person' },
]

export default function SettingsPage() {
  const { user, loading, signOut } = useAuth()
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('api')
  const [account, setAccount] = useState(null)
  const [keys, setKeys] = useState([])
  const [payments, setPayments] = useState([])
  const [packages, setPackages] = useState([])
  const [newKeyName, setNewKeyName] = useState('')
  const [revealedKey, setRevealedKey] = useState(null)
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [pwForm, setPwForm] = useState({ current: '', new: '', confirm: '' })
  const [pwLoading, setPwLoading] = useState(false)

  useEffect(() => {
    if (loading) return
    if (!user) {
      navigate('/login')
      return
    }
    loadAll()
  }, [user, loading, navigate])

  const loadAll = async () => {
    try {
      setError('')
      const [acc, k, p, pkg] = await Promise.all([
        api.me(),
        api.listApiKeys(),
        api.paymentHistory(),
        api.getPackages(),
      ])
      setAccount(acc)
      setKeys(k)
      setPayments(p)
      setPackages(pkg?.packages || pkg || [])
    } catch (e) {
      setError(e.message || '설정 데이터를 불러오지 못했습니다')
    }
  }

  const createKey = async () => {
    if (!newKeyName.trim()) return
    try {
      setError('')
      const res = await api.createApiKey({ name: newKeyName.trim() })
      setKeys([res, ...keys])
      setRevealedKey(res)
      setNewKeyName('')
      setShowCreate(false)
      await loadAll()
    } catch (e) {
      setError(e.message || 'API key 생성 실패')
    }
  }

  const deleteKey = async (id) => {
    if (!confirm('이 API key를 삭제하시겠습니까?')) return
    try {
      await api.deleteApiKey(id)
      setKeys(keys.filter((k) => k.id !== id))
    } catch (e) {
      setError(e.message || 'API key 삭제 실패')
    }
  }

  const rotateKey = async (id) => {
    if (!confirm('기존 key를 비활성화하고 새 key를 발급하시겠습니까?')) return
    try {
      const res = await api.rotateApiKey(id)
      setKeys(keys.map((k) => (k.id === id ? { ...k, is_active: false } : k)))
      setRevealedKey(res)
      await loadAll()
    } catch (e) {
      setError(e.message || 'API key 재발급 실패')
    }
  }

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text)
    setMsg('클립보드에 복사했습니다')
    setTimeout(() => setMsg(''), 2000)
  }

  const changePassword = async (e) => {
    e.preventDefault()
    if (pwForm.new !== pwForm.confirm) {
      setError('새 비밀번호가 일치하지 않습니다')
      return
    }
    if (pwForm.new.length < 8) {
      setError('비밀번호는 8자 이상이어야 합니다')
      return
    }
    setPwLoading(true)
    setError('')
    try {
      const { error: signInError } = await supabase.auth.signInWithPassword({
        email: user.email,
        password: pwForm.current,
      })
      if (signInError) throw new Error('현재 비밀번호가 올바르지 않습니다')
      const { error: updateError } = await supabase.auth.updateUser({ password: pwForm.new })
      if (updateError) throw updateError
      setPwForm({ current: '', new: '', confirm: '' })
      setMsg('비밀번호가 변경되었습니다')
      setTimeout(() => setMsg(''), 3000)
    } catch (e) {
      setError(e.message || '비밀번호 변경 실패')
    } finally {
      setPwLoading(false)
    }
  }

  const handleLogout = async () => {
    await signOut()
    navigate('/login')
  }

  const formatDate = (iso) =>
    iso ? new Date(iso).toLocaleString('ko-KR', { dateStyle: 'short', timeStyle: 'short' }) : '-'

  if (loading || !user) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  const renderApiKeys = () => (
    <div className="space-y-gutter">
      <div className="glass-panel p-6 rounded-2xl">
        <div className="flex justify-between items-center mb-4">
          <h3 className="font-headline-md text-headline-md text-on-surface">API Keys</h3>
          <button
            onClick={() => setShowCreate(true)}
            className="bg-primary text-on-primary px-4 py-2 rounded-lg flex items-center gap-2 font-body-md hover:bg-primary/90 transition-all"
          >
            <span className="material-symbols-outlined">add</span>
            New Key
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead className="bg-surface-container-low text-on-surface-variant font-label-sm text-label-sm uppercase tracking-wider">
              <tr>
                <th className="px-4 py-3">Label</th>
                <th className="px-4 py-3">Prefix</th>
                <th className="px-4 py-3 text-right">Rate</th>
                <th className="px-4 py-3 text-right">Created</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant text-body-md">
              {keys.map((k) => (
                <tr key={k.id} className={k.is_active ? '' : 'opacity-50'}>
                  <td className="px-4 py-3">{k.name}</td>
                  <td className="px-4 py-3 font-mono text-xs">{k.prefix}</td>
                  <td className="px-4 py-3 text-right">{k.rate_limit_rpm} RPM</td>
                  <td className="px-4 py-3 text-right">{formatDate(k.created_at)}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => rotateKey(k.id)}
                      className="text-primary text-sm hover:underline mr-3"
                      disabled={!k.is_active}
                    >
                      Rotate
                    </button>
                    <button
                      onClick={() => deleteKey(k.id)}
                      className="text-error text-sm hover:underline"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
              {keys.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-outline">
                    API key가 없습니다. 새 key를 생성하세요.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {showCreate && (
        <div className="glass-panel p-6 rounded-2xl">
          <h3 className="font-headline-md text-headline-md text-on-surface mb-4">Create New API Key</h3>
          <div className="flex gap-3">
            <input
              type="text"
              placeholder="Key name"
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
              className="flex-1 bg-surface-container-low border border-outline-variant rounded-lg px-3 py-2 text-body-md focus:ring-1 focus:ring-primary focus:outline-none"
            />
            <button
              onClick={createKey}
              className="bg-primary text-on-primary px-4 py-2 rounded-lg font-body-md hover:bg-primary/90"
            >
              Create
            </button>
            <button
              onClick={() => setShowCreate(false)}
              className="border border-outline-variant px-4 py-2 rounded-lg font-body-md text-on-surface hover:bg-surface-container"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {revealedKey && (
        <div className="rounded-2xl border border-amber-300 bg-amber-50 p-6">
          <p className="text-xs font-semibold text-amber-800 mb-2">아래 키는 한 번만 표시됩니다. 저장해주세요.</p>
          <div className="flex gap-2">
            <pre className="flex-1 rounded bg-white p-3 text-xs break-all text-on-surface">{revealedKey.key}</pre>
            <button
              onClick={() => copyToClipboard(revealedKey.key)}
              className="bg-amber-700 text-white px-3 py-2 rounded-lg text-sm hover:bg-amber-800"
            >
              Copy
            </button>
            <button
              onClick={() => setRevealedKey(null)}
              className="bg-slate-200 text-slate-700 px-3 py-2 rounded-lg text-sm hover:bg-slate-300"
            >
              Hide
            </button>
          </div>
        </div>
      )}
    </div>
  )

  const renderBilling = () => (
    <div className="space-y-gutter">
      <div className="glass-panel p-6 rounded-2xl">
        <div className="flex items-center justify-between mb-6">
          <div>
            <p className="text-on-surface-variant text-body-md mb-1">Points Balance</p>
            <p className="font-headline-lg text-headline-lg text-on-surface">{(account?.points_balance || 0).toLocaleString()}P</p>
          </div>
          <button
            onClick={() => navigate('/payment')}
            className="bg-primary text-on-primary px-6 py-3 rounded-xl font-body-md hover:bg-primary/90 transition-all"
          >
            충전하기
          </button>
        </div>
        <div className="h-px bg-outline-variant/40 mb-6"></div>
        <h3 className="font-headline-md text-headline-md text-on-surface mb-4">Payment History</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead className="bg-surface-container-low text-on-surface-variant font-label-sm text-label-sm uppercase tracking-wider">
              <tr>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Provider</th>
                <th className="px-4 py-3">Amount</th>
                <th className="px-4 py-3">Points</th>
                <th className="px-4 py-3">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant text-body-md">
              {payments.map((p) => {
                const amount = Number(p.amount) || 0
                return (
                  <tr key={p.id}>
                    <td className="px-4 py-3">{formatDate(p.created_at)}</td>
                    <td className="px-4 py-3 uppercase">{p.provider}</td>
                    <td className="px-4 py-3">{amount.toLocaleString()} {p.currency}</td>
                    <td className="px-4 py-3">{p.points_added?.toLocaleString() || '-'}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-1 rounded text-xs ${p.status === 'paid' ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-600'}`}>
                        {p.status}
                      </span>
                    </td>
                  </tr>
                )
              })}
              {payments.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-outline">결제 내역이 없습니다</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="glass-panel p-6 rounded-2xl">
        <h3 className="font-headline-md text-headline-md text-on-surface mb-4">Recharge Packages</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-gutter">
          {packages.map((pkg) => {
            const points = pkg.points || 0
            const price = pkg.price || pkg.krw || 0
            const currency = pkg.currency || 'KRW'
            return (
              <div key={pkg.id || `${points}-${price}`} className="border border-outline-variant rounded-xl p-4 flex flex-col">
                <p className="font-headline-md text-headline-md text-on-surface">{points.toLocaleString()}P</p>
                <p className="text-on-surface-variant text-body-md mb-4">{price.toLocaleString()} {currency}</p>
                <button
                  onClick={() => navigate('/payment', { state: { selectedPackage: pkg } })}
                  className="mt-auto w-full bg-primary text-on-primary py-2 rounded-lg font-body-md hover:bg-primary/90"
                >
                  선택
                </button>
              </div>
            )
          })}
          {packages.length === 0 && (
            <p className="text-outline col-span-full">패키지 정보를 불러오지 못했습니다</p>
          )}
        </div>
      </div>
    </div>
  )

  const renderRateLimit = () => {
    const limit = account?.rate_limit_rpm || 60
    const quota = account?.daily_quota
    const spent = account?.daily_spent_points || 0
    return (
      <div className="space-y-gutter">
        <div className="glass-panel p-6 rounded-2xl">
          <h3 className="font-headline-md text-headline-md text-on-surface mb-6">Rate Limit</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-gutter">
            <div className="bg-surface-container-low rounded-xl p-4">
              <p className="text-on-surface-variant text-label-sm mb-1">Requests per minute</p>
              <p className="font-headline-md text-headline-md text-on-surface">{limit}</p>
            </div>
            <div className="bg-surface-container-low rounded-xl p-4">
              <p className="text-on-surface-variant text-label-sm mb-1">Daily quota</p>
              <p className="font-headline-md text-headline-md text-on-surface">{quota ? `${quota.toLocaleString()}P` : 'Unlimited'}</p>
            </div>
            <div className="bg-surface-container-low rounded-xl p-4">
              <p className="text-on-surface-variant text-label-sm mb-1">Daily spent</p>
              <p className="font-headline-md text-headline-md text-on-surface">{spent.toLocaleString()}P</p>
            </div>
          </div>
          {quota && (
            <div className="mt-6">
              <div className="flex justify-between text-body-md mb-2">
                <span className="text-on-surface-variant">Daily quota usage</span>
                <span className="text-on-surface">{Math.min(100, Math.round((spent / quota) * 100))}%</span>
              </div>
              <div className="h-2 bg-surface-container-low rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary rounded-full transition-all"
                  style={{ width: `${Math.min(100, Math.round((spent / quota) * 100))}%` }}
                ></div>
              </div>
            </div>
          )}
        </div>
      </div>
    )
  }

  const renderAccount = () => (
    <div className="space-y-gutter">
      <div className="glass-panel p-6 rounded-2xl">
        <h3 className="font-headline-md text-headline-md text-on-surface mb-4">Account</h3>
        <div className="mb-6">
          <p className="text-on-surface-variant text-label-sm mb-1">Email</p>
          <p className="text-on-surface text-body-md">{user.email}</p>
        </div>
        <button
          onClick={handleLogout}
          className="border border-outline-variant text-on-surface px-4 py-2 rounded-lg font-body-md hover:bg-surface-container transition-colors"
        >
          로그아웃
        </button>
      </div>

      <div className="glass-panel p-6 rounded-2xl">
        <h3 className="font-headline-md text-headline-md text-on-surface mb-4">Change Password</h3>
        <form onSubmit={changePassword} className="space-y-4 max-w-md">
          <div>
            <label className="block text-on-surface-variant text-label-sm mb-1">Current password</label>
            <input
              type="password"
              value={pwForm.current}
              onChange={(e) => setPwForm({ ...pwForm, current: e.target.value })}
              required
              className="w-full bg-surface-container-low border border-outline-variant rounded-lg px-3 py-2 text-body-md focus:ring-1 focus:ring-primary focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-on-surface-variant text-label-sm mb-1">New password</label>
            <input
              type="password"
              value={pwForm.new}
              onChange={(e) => setPwForm({ ...pwForm, new: e.target.value })}
              required
              minLength={8}
              className="w-full bg-surface-container-low border border-outline-variant rounded-lg px-3 py-2 text-body-md focus:ring-1 focus:ring-primary focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-on-surface-variant text-label-sm mb-1">Confirm new password</label>
            <input
              type="password"
              value={pwForm.confirm}
              onChange={(e) => setPwForm({ ...pwForm, confirm: e.target.value })}
              required
              minLength={8}
              className="w-full bg-surface-container-low border border-outline-variant rounded-lg px-3 py-2 text-body-md focus:ring-1 focus:ring-primary focus:outline-none"
            />
          </div>
          <button
            type="submit"
            disabled={pwLoading}
            className="bg-primary text-on-primary px-4 py-2 rounded-lg font-body-md hover:bg-primary/90 disabled:opacity-50"
          >
            {pwLoading ? '변경 중…' : '비밀번호 변경'}
          </button>
        </form>
      </div>
    </div>
  )

  const tabContent = {
    api: renderApiKeys,
    billing: renderBilling,
    rate: renderRateLimit,
    account: renderAccount,
  }

  return (
    <SidebarLayout title="Settings" subtitle="Manage your API keys, billing, rate limits, and account">
      {(error || msg) && (
        <div
          className={`px-4 py-3 rounded-xl text-sm border mb-8 ${
            error
              ? 'bg-error-container text-error border-error/10'
              : 'bg-green-50 text-green-700 border-green-200'
          }`}
        >
          {error || msg}
        </div>
      )}

      <div className="flex flex-col md:flex-row gap-gutter">
        <nav className="md:w-56 shrink-0 space-y-1">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg text-left font-body-md transition-colors ${
                activeTab === tab.id
                  ? 'bg-primary-container/10 text-primary font-bold border-r-2 border-primary'
                  : 'text-on-surface-variant hover:bg-primary-container/10'
              }`}
            >
              <span className="material-symbols-outlined text-xl">{tab.icon}</span>
              {tab.label}
            </button>
          ))}
        </nav>

        <div className="flex-1 min-w-0">
          {tabContent[activeTab]()}
        </div>
      </div>
    </SidebarLayout>
  )
}
