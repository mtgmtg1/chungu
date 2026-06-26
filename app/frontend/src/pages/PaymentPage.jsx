// [Flow: Step 1 (패키지 조회) -> Step 2 (Toss/Paddle 선택) -> Step 3 (결제 진행) -> Step 4 (검증/포인트 충전)]
import { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Coins, CreditCard, ArrowLeft, Loader2, CheckCircle2 } from 'lucide-react'
import { api } from '../api.js'
import { useAuth } from '../AuthContext.jsx'

export default function PaymentPage() {
  const { user } = useAuth()
  const [packages, setPackages] = useState([])
  const [profile, setProfile] = useState(null)
  const [loading, setLoading] = useState(true)
  const [paying, setPaying] = useState(false)
  const [success, setSuccess] = useState(false)
  const [error, setError] = useState('')
  const nav = useNavigate()

  useEffect(() => {
    if (!user) return
    load()
  }, [user])

  async function load() {
    try {
      const [pkg, me] = await Promise.all([api.getPackages(), api.me()])
      setPackages(pkg.packages || [])
      setProfile(me)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function payWithToss(pkg) {
    setPaying(true)
    setError('')
    try {
      const order = await api.createTossOrder({ package_id: pkg.name })
      // Toss SDK가 로드되어 있지 않으면 테스트용 수동 결제창은 대체로 처리합니다.
      if (window.TossPayments) {
        const toss = window.TossPayments(order.client_key || '')
        toss.requestPayment('카드', {
          amount: order.amount,
          orderId: order.order_id,
          orderName: `${pkg.points}P 충전`,
          customerEmail: profile?.email || '',
          successUrl: `${window.location.origin}/payment?toss=success&orderId=${order.order_id}`,
          failUrl: `${window.location.origin}/payment?toss=fail&orderId=${order.order_id}`,
        })
      } else {
        // SDK가 없으면 백엔드 검증만 수동 시뮬레이션 (개발/테스트용)
        await api.verifyToss({ paymentKey: 'test-' + order.order_id, orderId: order.order_id, amount: order.amount })
        setSuccess(true)
        await load()
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setPaying(false)
    }
  }

  async function payWithPaddle(pkg) {
    setPaying(true)
    setError('')
    try {
      const checkout = await api.createPaddleCheckout({ package_id: pkg.name })
      window.open(checkout.checkout_url, '_blank')
    } catch (e) {
      setError(e.message)
    } finally {
      setPaying(false)
    }
  }

  if (!user) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <p>로그인이 필요합니다</p>
          <button onClick={() => nav('/login')} className="bg-blue-600 text-white px-4 py-2 rounded-lg mt-4">로그인</button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b bg-white">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Link to="/dashboard" className="text-slate-500 hover:text-slate-800"><ArrowLeft size={20} /></Link>
            <h1 className="text-xl font-bold">포인트 충전</h1>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Coins size={18} className="text-yellow-500" />
            <span>잔액: <b>{profile?.points_balance ?? '-'} P</b></span>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8">
        {success && (
          <div className="bg-green-50 text-green-700 rounded-lg p-4 mb-6 flex items-center gap-2">
            <CheckCircle2 size={20} /> 충전이 완료되었습니다.
          </div>
        )}
        {error && <p className="text-red-600 text-sm mb-6">{error}</p>}

        {loading ? <div className="text-center py-12"><Loader2 className="animate-spin mx-auto" /></div> : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {packages.map((pkg) => (
              <div key={pkg.name} className="bg-white rounded-xl border p-6 flex flex-col">
                <h2 className="text-lg font-bold mb-1">{pkg.name}</h2>
                <p className="text-3xl font-bold text-blue-600 mb-4">{pkg.points.toLocaleString()} P</p>
                <p className="text-sm text-slate-500 mb-6">₩{pkg.krw.toLocaleString()} / ${pkg.usd}</p>
                <div className="mt-auto space-y-2">
                  <button onClick={() => payWithToss(pkg)} disabled={paying}
                    className="w-full bg-blue-600 text-white rounded-lg py-2 font-medium hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center gap-2">
                    {paying ? <Loader2 className="animate-spin" size={16} /> : <><CreditCard size={16} /> 카드 결제 (KRW)</>}
                  </button>
                  <button onClick={() => payWithPaddle(pkg)} disabled={paying}
                    className="w-full bg-slate-800 text-white rounded-lg py-2 font-medium hover:bg-slate-900 disabled:opacity-50">
                    PayPal/Card (USD)
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
