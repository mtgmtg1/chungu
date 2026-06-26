// [Flow: Step 1 (이메일/비번 입력) -> Step 2 (Supabase 로그인/회원가입) -> Step 3 (성공 시 루트 이동)]
import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Mail, Lock, Loader2, UserPlus, LogIn } from 'lucide-react'
import { useAuth } from '../AuthContext.jsx'

export default function AuthPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isSignUp, setIsSignUp] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const nav = useNavigate()
  const { signIn, signUp } = useAuth()

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      if (isSignUp) {
        const { error } = await signUp(email, password)
        if (error) throw error
        setError('가입 확인 이메일을 확인해주세요.')
      } else {
        const { error } = await signIn(email, password)
        if (error) throw error
        nav('/')
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <form onSubmit={handleSubmit} className="bg-white rounded-xl shadow-sm border p-8 w-full max-w-sm space-y-5">
        <div className="text-center">
          {isSignUp ? <UserPlus className="mx-auto text-blue-600 mb-2" /> : <LogIn className="mx-auto text-blue-600 mb-2" />}
          <h1 className="text-lg font-bold">{isSignUp ? '회원가입' : '로그인'}</h1>
          <p className="text-sm text-slate-500 mt-1">PDF 변환을 시작하려면 로그인하세요</p>
        </div>

        <div className="relative">
          <Mail className="absolute left-3 top-2.5 text-slate-400" size={18} />
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="이메일"
            className="w-full border rounded-lg pl-10 pr-3 py-2" required />
        </div>
        <div className="relative">
          <Lock className="absolute left-3 top-2.5 text-slate-400" size={18} />
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="비밀번호"
            className="w-full border rounded-lg pl-10 pr-3 py-2" required />
        </div>

        {error && <p className="text-red-600 text-sm">{error}</p>}

        <button type="submit" disabled={loading}
          className="w-full bg-blue-600 text-white rounded-lg py-2.5 font-medium hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center gap-2">
          {loading ? <Loader2 className="animate-spin" size={18} /> : isSignUp ? '회원가입' : '로그인'}
        </button>

        <div className="text-center text-sm text-slate-500">
          {isSignUp ? '이미 계정이 있으신가요?' : '계정이 없으신가요?'}{' '}
          <button type="button" onClick={() => setIsSignUp(!isSignUp)} className="text-blue-600 hover:underline">
            {isSignUp ? '로그인' : '회원가입'}
          </button>
        </div>

        <p className="text-xs text-center text-slate-400">
          <Link to="/admin/login" className="hover:underline">관리자 로그인</Link>
        </p>
      </form>
    </div>
  )
}
