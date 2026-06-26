// [Flow: Step 1 (인증 확인) -> Step 2 (계정/키/결제 데이터 로드) -> Step 3 (탭별 UI 렌더링) -> Step 4 (API key 관리 및 비밀번호 변경)]
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '../api.js'
import { useAuth } from '../AuthContext.jsx'
import { supabase } from '../supabase.js'
import i18n from '../i18n.js'
import SidebarLayout from '../components/SidebarLayout.jsx'

export default function SettingsPage() {
  const { user, loading, signOut } = useAuth()
  const { t } = useTranslation()
  const navigate = useNavigate()

  const tabs = [
    { id: 'api', label: t('page:settings.apiKeys'), icon: 'key' },
    { id: 'billing', label: t('page:settings.billing'), icon: 'payments' },
    { id: 'rate', label: t('page:settings.rateLimit'), icon: 'speed' },
    { id: 'account', label: t('page:settings.account'), icon: 'person' },
  ]
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
      setError(e.message || t('page:errors.loadFailed'))
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
      setError(e.message || t('page:errors.unknown'))
    }
  }

  const deleteKey = async (id) => {
    if (!confirm(t('page:settings.deleteConfirm', 'Delete this API key?'))) return
    try {
      await api.deleteApiKey(id)
      setKeys(keys.filter((k) => k.id !== id))
    } catch (e) {
      setError(e.message || t('page:errors.unknown'))
    }
  }

  const rotateKey = async (id) => {
    if (!confirm(t('page:settings.rotateConfirm', 'Rotate this API key?'))) return
    try {
      const res = await api.rotateApiKey(id)
      setKeys(keys.map((k) => (k.id === id ? { ...k, is_active: false } : k)))
      setRevealedKey(res)
      await loadAll()
    } catch (e) {
      setError(e.message || t('page:errors.unknown'))
    }
  }

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text)
    setMsg(t('page:settings.copied'))
    setTimeout(() => setMsg(''), 2000)
  }

  const changePassword = async (e) => {
    e.preventDefault()
    if (pwForm.new !== pwForm.confirm) {
      setError(t('page:settings.passwordMismatch'))
      return
    }
    if (pwForm.new.length < 8) {
      setError(t('page:settings.passwordLength'))
      return
    }
    setPwLoading(true)
    setError('')
    try {
      const { error: signInError } = await supabase.auth.signInWithPassword({
        email: user.email,
        password: pwForm.current,
      })
      if (signInError) throw new Error(t('page:settings.currentPasswordWrong'))
      const { error: updateError } = await supabase.auth.updateUser({ password: pwForm.new })
      if (updateError) throw updateError
      setPwForm({ current: '', new: '', confirm: '' })
      setMsg(t('page:settings.passwordChanged'))
      setTimeout(() => setMsg(''), 3000)
    } catch (e) {
      setError(e.message || t('page:settings.passwordChangeFailed'))
    } finally {
      setPwLoading(false)
    }
  }

  const handleLogout = async () => {
    await signOut()
    navigate('/login')
  }

  const formatDate = (iso) =>
    iso ? new Date(iso).toLocaleString(i18n.language, { dateStyle: 'short', timeStyle: 'short' }) : '-'

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
          <h3 className="font-headline-md text-headline-md text-on-surface">{t('page:settings.apiKeys')}</h3>
          <button
            onClick={() => setShowCreate(true)}
            className="bg-primary text-on-primary px-4 py-2 rounded-lg flex items-center gap-2 font-body-md hover:bg-primary/90 transition-all"
          >
            <span className="material-symbols-outlined">add</span>
            {t('page:settings.newKey')}
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead className="bg-surface-container-low text-on-surface-variant font-label-sm text-label-sm uppercase tracking-wider">
              <tr>
                <th className="px-4 py-3">{t('page:settings.label')}</th>
                <th className="px-4 py-3">{t('page:settings.prefix')}</th>
                <th className="px-4 py-3 text-right">{t('page:settings.rate')}</th>
                <th className="px-4 py-3 text-right">{t('page:settings.created')}</th>
                <th className="px-4 py-3 text-right">{t('page:settings.actions')}</th>
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
                      {t('page:settings.rotate')}
                    </button>
                    <button
                      onClick={() => deleteKey(k.id)}
                      className="text-error text-sm hover:underline"
                    >
                      {t('page:settings.delete')}
                    </button>
                  </td>
                </tr>
              ))}
              {keys.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-outline">
                    {t('page:settings.noKeys')}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {showCreate && (
        <div className="glass-panel p-6 rounded-2xl">
          <h3 className="font-headline-md text-headline-md text-on-surface mb-4">{t('page:settings.createKey')}</h3>
          <div className="flex gap-3">
            <input
              type="text"
              placeholder={t('page:settings.keyName')}
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
              className="flex-1 bg-surface-container-low border border-outline-variant rounded-lg px-3 py-2 text-body-md focus:ring-1 focus:ring-primary focus:outline-none"
            />
            <button
              onClick={createKey}
              className="bg-primary text-on-primary px-4 py-2 rounded-lg font-body-md hover:bg-primary/90"
            >
              {t('page:settings.create')}
            </button>
            <button
              onClick={() => setShowCreate(false)}
              className="border border-outline-variant px-4 py-2 rounded-lg font-body-md text-on-surface hover:bg-surface-container"
            >
              {t('page:settings.cancel')}
            </button>
          </div>
        </div>
      )}

      {revealedKey && (
        <div className="rounded-2xl border border-amber-300 bg-amber-50 p-6">
          <p className="text-xs font-semibold text-amber-800 mb-2">{t('page:settings.saveKey')}</p>
          <div className="flex gap-2">
            <pre className="flex-1 rounded bg-white p-3 text-xs break-all text-on-surface">{revealedKey.key}</pre>
            <button
              onClick={() => copyToClipboard(revealedKey.key)}
              className="bg-amber-700 text-white px-3 py-2 rounded-lg text-sm hover:bg-amber-800"
            >
              {t('page:settings.copy')}
            </button>
            <button
              onClick={() => setRevealedKey(null)}
              className="bg-slate-200 text-slate-700 px-3 py-2 rounded-lg text-sm hover:bg-slate-300"
            >
              {t('page:settings.hide')}
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
            <p className="text-on-surface-variant text-body-md mb-1">{t('page:settings.pointsBalance')}</p>
            <p className="font-headline-lg text-headline-lg text-on-surface">{(account?.points_balance || 0).toLocaleString()}{t('common:points.point')}</p>
          </div>
          <button
            onClick={() => navigate('/payment')}
            className="bg-primary text-on-primary px-6 py-3 rounded-xl font-body-md hover:bg-primary/90 transition-all"
          >
            {t('page:settings.recharge')}
          </button>
        </div>
        <div className="h-px bg-outline-variant/40 mb-6"></div>
        <h3 className="font-headline-md text-headline-md text-on-surface mb-4">{t('page:settings.paymentHistory')}</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead className="bg-surface-container-low text-on-surface-variant font-label-sm text-label-sm uppercase tracking-wider">
              <tr>
                <th className="px-4 py-3">{t('page:settings.date')}</th>
                <th className="px-4 py-3">{t('page:settings.provider')}</th>
                <th className="px-4 py-3">{t('page:settings.amount')}</th>
                <th className="px-4 py-3">{t('page:settings.points')}</th>
                <th className="px-4 py-3">{t('page:settings.status')}</th>
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
                  <td colSpan={5} className="px-4 py-8 text-center text-outline">{t('page:settings.noPayments')}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="glass-panel p-6 rounded-2xl">
        <h3 className="font-headline-md text-headline-md text-on-surface mb-4">{t('page:settings.rechargePackages')}</h3>
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
                  {t('page:settings.select')}
                </button>
              </div>
            )
          })}
          {packages.length === 0 && (
            <p className="text-outline col-span-full">{t('page:settings.noPackages')}</p>
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
          <h3 className="font-headline-md text-headline-md text-on-surface mb-6">{t('page:settings.rateLimit')}</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-gutter">
            <div className="bg-surface-container-low rounded-xl p-4">
              <p className="text-on-surface-variant text-label-sm mb-1">{t('page:settings.requestsPerMinute')}</p>
              <p className="font-headline-md text-headline-md text-on-surface">{limit}</p>
            </div>
            <div className="bg-surface-container-low rounded-xl p-4">
              <p className="text-on-surface-variant text-label-sm mb-1">{t('page:settings.dailyQuota')}</p>
              <p className="font-headline-md text-headline-md text-on-surface">{quota ? `${quota.toLocaleString()}${t('common:points.point')}` : t('page:settings.unlimited')}</p>
            </div>
            <div className="bg-surface-container-low rounded-xl p-4">
              <p className="text-on-surface-variant text-label-sm mb-1">{t('page:settings.dailySpent')}</p>
              <p className="font-headline-md text-headline-md text-on-surface">{spent.toLocaleString()}{t('common:points.point')}</p>
            </div>
          </div>
          {quota && (
            <div className="mt-6">
              <div className="flex justify-between text-body-md mb-2">
                <span className="text-on-surface-variant">{t('page:settings.dailyQuotaUsage')}</span>
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
        <h3 className="font-headline-md text-headline-md text-on-surface mb-4">{t('page:settings.account')}</h3>
        <div className="mb-6">
          <p className="text-on-surface-variant text-label-sm mb-1">{t('page:settings.email')}</p>
          <p className="text-on-surface text-body-md">{user.email}</p>
        </div>
        <button
          onClick={handleLogout}
          className="border border-outline-variant text-on-surface px-4 py-2 rounded-lg font-body-md hover:bg-surface-container transition-colors"
        >
          {t('page:settings.logout')}
        </button>
      </div>

      <div className="glass-panel p-6 rounded-2xl">
        <h3 className="font-headline-md text-headline-md text-on-surface mb-4">{t('page:settings.changePassword')}</h3>
        <form onSubmit={changePassword} className="space-y-4 max-w-md">
          <div>
            <label className="block text-on-surface-variant text-label-sm mb-1">{t('page:settings.currentPassword')}</label>
            <input
              type="password"
              value={pwForm.current}
              onChange={(e) => setPwForm({ ...pwForm, current: e.target.value })}
              required
              className="w-full bg-surface-container-low border border-outline-variant rounded-lg px-3 py-2 text-body-md focus:ring-1 focus:ring-primary focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-on-surface-variant text-label-sm mb-1">{t('page:settings.newPassword')}</label>
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
            <label className="block text-on-surface-variant text-label-sm mb-1">{t('page:settings.confirmPassword')}</label>
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
            {pwLoading ? t('page:settings.changing') : t('page:settings.change')}
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
    <SidebarLayout title={t('page:settings.title')} subtitle={t('page:settings.subtitle')}>
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
          {tabs.map((tab) => (
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
