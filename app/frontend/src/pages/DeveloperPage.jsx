// [Flow: Step 1 (로그인/개발자 권한 확인) -> Step 2 (계정/키/사용량 데이터 로드) -> Step 3 (키 발급/삭제/복사 UI) -> Step 4 (cURL 예시 제공)]
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { useAuth } from '../AuthContext.jsx'

function Section({ title, children }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm mb-6">
      <h2 className="text-lg font-semibold mb-4">{title}</h2>
      {children}
    </div>
  )
}

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
  const [activeTab, setActiveTab] = useState('keys')

  const baseUrl = window.location.origin

  useEffect(() => {
    if (loading) return
    if (!user) {
      navigate('/login')
      return
    }
    loadAll()
  }, [user, loading, navigate])

  const loadKeys = async () => {
    try {
      const k = await api.listApiKeys()
      setKeys(k)
    } catch (e) {
      console.error('API keys 로드 실패:', e)
      setError((prev) => prev || (e.message || 'API keys를 불러오지 못했습니다'))
    }
  }

  const loadAll = async () => {
    try {
      setError('')
      const [acc, prc, usg, tx] = await Promise.all([
        api.devAccount(),
        api.devPricing(),
        api.devUsage(30),
        api.devTransactions(20),
      ])
      setAccount(acc)
      setPricing(prc)
      setUsage(usg)
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
      await loadKeys()
    } catch (e) {
      setError(e.message || 'key 생성 실패')
    }
  }

  useEffect(() => {
    if (!user || activeTab !== 'keys') return
    loadKeys()
  }, [activeTab, user])

  const deleteKey = async (id) => {
    if (!confirm('이 API key를 비활성화하시겠습니까?')) return
    try {
      await api.deleteApiKey(id)
      setKeys(keys.map((k) => (k.id === id ? { ...k, is_active: false } : k)))
    } catch (e) {
      setError(e.message || 'key 삭제 실패')
    }
  }

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text)
  }

  const curlExample = account?.api_key?.prefix
    ? `curl -X POST ${baseUrl}/api/v1/jobs/upload \\\n  -H "X-API-Key: chu_live_..." \\\n  -F "files=@document.pdf" \\\n  -F "pipeline=vision"`
    : `curl -X POST ${baseUrl}/api/v1/keys \\\n  -H "Authorization: Bearer <your-jwt>" \\\n  -H "Content-Type: application/json" \\\n  -d '{"name":"my-app"}'`

  if (loading || !user) return <div className="max-w-5xl mx-auto p-6">로딩 중...</div>

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b bg-white">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <h1 className="text-xl font-bold">개발자 포털</h1>
          <Link to="/" className="text-sm text-slate-600 hover:text-slate-900">← 메인으로</Link>
        </div>
      </header>
      <main className="max-w-5xl mx-auto px-6 py-8">
        {error && <div className="mb-4 rounded-lg bg-red-50 text-red-700 px-4 py-3 text-sm">{error}</div>}

        <div className="flex gap-2 mb-6">
          {['keys', 'usage', 'billing', 'docs'].map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 rounded-lg text-sm font-medium ${
                activeTab === tab
                  ? 'bg-blue-600 text-white'
                  : 'bg-white text-slate-600 hover:bg-slate-100 border border-slate-200'
              }`}
            >
              {tab === 'keys' && 'API Keys'}
              {tab === 'usage' && '사용량'}
              {tab === 'billing' && '결제/잔액'}
              {tab === 'docs' && 'Docs'}
            </button>
          ))}
        </div>

        {activeTab === 'keys' && (
          <Section title="API Keys">
            <div className="flex gap-2 mb-4">
              <input
                type="text"
                placeholder="key 이름 (예: production)"
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value)}
                className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <button onClick={createKey} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">새 API key 발급</button>
              <button onClick={loadKeys} className="rounded-lg bg-white border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">새로고침</button>
            </div>
            {revealedKey && (
              <div className="mb-4 rounded-lg border border-amber-300 bg-amber-50 p-4">
                <p className="mb-2 text-sm font-semibold text-amber-800">아래 key는 다시 표시되지 않습니다. 복사해 저장하세요.</p>
                <pre className="mb-2 rounded bg-white p-2 text-xs break-all">{revealedKey.key}</pre>
                <div className="flex gap-2">
                  <button onClick={() => copyToClipboard(revealedKey.key)} className="rounded bg-amber-700 px-3 py-1 text-xs text-white hover:bg-amber-800">복사</button>
                  <button onClick={() => setRevealedKey(null)} className="rounded bg-slate-200 px-3 py-1 text-xs text-slate-700 hover:bg-slate-300">숨기기</button>
                </div>
              </div>
            )}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-100 text-slate-600">
                  <tr><th className="px-3 py-2 text-left">이름</th><th className="px-3 py-2 text-left">prefix</th><th className="px-3 py-2 text-left">scope</th><th className="px-3 py-2 text-left">rate limit</th><th className="px-3 py-2 text-left">마지막 사용</th><th className="px-3 py-2 text-left">상태</th><th className="px-3 py-2 text-left"></th></tr>
                </thead>
                <tbody>
                  {keys.map((k) => (
                    <tr key={k.id} className="border-b border-slate-100">
                      <td className="px-3 py-2">{k.name}</td>
                      <td className="px-3 py-2">{k.prefix}...</td>
                      <td className="px-3 py-2">{(k.scopes || []).join(', ')}</td>
                      <td className="px-3 py-2">{k.rate_limit_rpm}/min</td>
                      <td className="px-3 py-2">{k.last_used_at ? new Date(k.last_used_at).toLocaleString() : '-'}</td>
                      <td className="px-3 py-2">{k.is_active ? <span className="text-green-600">활성</span> : <span className="text-slate-400">비활성</span>}</td>
                      <td className="px-3 py-2">
                        {k.is_active && (
                          <button onClick={() => deleteKey(k.id)} className="text-xs text-red-600 hover:underline">비활성화</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        )}

        {activeTab === 'usage' && (
          <Section title="사용량">
            <div className="mb-4 grid grid-cols-2 gap-4">
              <div className="rounded-lg bg-slate-50 p-4">
                <div className="text-xs text-slate-500">잔액</div>
                <div className="text-xl font-bold">{account?.points_balance?.toLocaleString() || 0}P</div>
              </div>
              <div className="rounded-lg bg-slate-50 p-4">
                <div className="text-xs text-slate-500">오늘 사용</div>
                <div className="text-xl font-bold">{account?.today_usage?.points_spent || 0}P</div>
                <div className="text-xs text-slate-500">{account?.today_usage?.requests || 0}건</div>
              </div>
            </div>
            <h3 className="mb-2 font-medium">최근 30일 일별 사용량</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-100 text-slate-600"><tr><th className="px-3 py-2 text-left">날짜</th><th className="px-3 py-2 text-left">요청 수</th><th className="px-3 py-2 text-left">사용 포인트</th></tr></thead>
                <tbody>
                  {usage.map((u) => (
                    <tr key={u.day} className="border-b border-slate-100">
                      <td className="px-3 py-2">{u.day}</td>
                      <td className="px-3 py-2">{u.requests}</td>
                      <td className="px-3 py-2">{u.points_spent.toLocaleString()}P</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        )}

        {activeTab === 'billing' && (
          <Section title="결제 및 잔액">
            <p className="mb-4 text-sm">현재 잔액: <strong className="text-lg">{account?.points_balance?.toLocaleString() || 0}P</strong></p>
            <h3 className="mb-2 font-medium">단가</h3>
            <ul className="mb-4 list-disc pl-5 text-sm text-slate-700">
              <li>PDF 페이지: {pricing?.rates?.krw_per_page}P</li>
              <li>이미지: {pricing?.rates?.krw_per_image}P</li>
              <li>오디오 1초: {pricing?.rates?.krw_per_audio_second}P</li>
              <li>비디오 1초: {pricing?.rates?.krw_per_video_second}P</li>
            </ul>
            <h3 className="mb-2 font-medium">최근 거래 내역</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-100 text-slate-600"><tr><th className="px-3 py-2 text-left">일시</th><th className="px-3 py-2 text-left">유형</th><th className="px-3 py-2 text-left">금액</th><th className="px-3 py-2 text-left">설명</th></tr></thead>
                <tbody>
                  {transactions.map((t) => (
                    <tr key={t.id} className="border-b border-slate-100">
                      <td className="px-3 py-2">{new Date(t.created_at).toLocaleString()}</td>
                      <td className="px-3 py-2">{t.type}</td>
                      <td className="px-3 py-2">{t.amount.toLocaleString()}P</td>
                      <td className="px-3 py-2">{t.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button onClick={() => navigate('/payment')} className="mt-4 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">포인트 충전하기</button>
          </Section>
        )}

        {activeTab === 'docs' && (
          <Section title="API 사용 가이드">
            <p className="mb-4 text-sm text-slate-700">모든 API는 <code className="rounded bg-slate-100 px-1 py-0.5 text-xs">/api/v1</code> prefix를 사용하고, <code className="rounded bg-slate-100 px-1 py-0.5 text-xs">X-API-Key</code> 헤더로 인증합니다.</p>
            <h3 className="mb-2 font-medium">1. API key 발급</h3>
            <p className="mb-4 text-sm text-slate-700">위 <strong>API Keys</strong> 탭에서 key를 생성하세요.</p>
            <h3 className="mb-2 font-medium">2. 파일 업로드 (비용 미리보기)</h3>
            <pre className="mb-4 rounded-lg bg-slate-900 p-3 text-xs text-slate-50 overflow-x-auto">{curlExample}</pre>
            <h3 className="mb-2 font-medium">3. 작업 승인 및 차감</h3>
            <pre className="mb-4 rounded-lg bg-slate-900 p-3 text-xs text-slate-50 overflow-x-auto">{`curl -X POST ${baseUrl}/api/v1/jobs/<job_id>/confirm \\\n  -H "X-API-Key: <your-key>"`}</pre>
            <h3 className="mb-2 font-medium">4. 상태 조회</h3>
            <pre className="mb-4 rounded-lg bg-slate-900 p-3 text-xs text-slate-50 overflow-x-auto">{`curl ${baseUrl}/api/v1/jobs/<job_id> \\\n  -H "X-API-Key: <your-key>"`}</pre>
            <h3 className="mb-2 font-medium">5. 결과 다운로드</h3>
            <pre className="mb-4 rounded-lg bg-slate-900 p-3 text-xs text-slate-50 overflow-x-auto">{`curl -X GET "${baseUrl}/api/v1/jobs/<job_id>/download?type=xlsx" \\\n  -H "X-API-Key: <your-key>"`}</pre>
            <h3 className="mb-2 font-medium">OpenAPI 문서</h3>
            <a href={`${baseUrl}/api/v1/docs`} target="_blank" rel="noreferrer" className="text-sm text-blue-600 hover:underline">{baseUrl}/api/v1/docs</a>
          </Section>
        )}
      </main>
    </div>
  )
}
