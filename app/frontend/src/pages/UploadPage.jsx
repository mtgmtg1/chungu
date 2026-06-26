// [Flow: Step 1 (로그인 확인) -> Step 2 (중앙 업로드 영역) -> Step 3 (업로드 -> 비용 확인 페이지 이동) -> Step 4 (승인 -> 결과 페이지 이동)]
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { FileUp, Loader2, LogIn, Settings, Coins } from 'lucide-react'
import { useAuth } from '../AuthContext.jsx'
import { api } from '../api.js'

export default function UploadPage() {
  const { user, loading: authLoading } = useAuth()
  const nav = useNavigate()
  const [files, setFiles] = useState([])
  const [submitting, setSubmitting] = useState(false)
  const [profile, setProfile] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!user) return
    api.me().then(setProfile).catch(() => {})
  }, [user])

  async function handleDrop(e) {
    e.preventDefault()
    const dropped = Array.from(e.dataTransfer.files || [])
    if (dropped.length) setFiles(dropped)
  }

  async function handleUpload(e) {
    e.preventDefault()
    setError('')
    if (!user) return nav('/login')
    if (!files.length) return setError('파일을 선택하세요')

    const fd = new FormData()
    files.forEach((f) => fd.append('files', f))

    setSubmitting(true)
    try {
      const res = await api.uploadJob(fd)
      nav(`/jobs/${res.job_id}/confirm`)
    } catch (e) {
      setError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  if (authLoading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <Loader2 className="animate-spin text-primary" size={32} />
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background text-on-background flex flex-col overflow-x-hidden">
      <nav className="w-full bg-transparent">
        <div className="max-w-container-max mx-auto flex justify-between items-center h-20 px-gutter">
          <div className="flex items-center gap-2">
            <span className="font-headline-md text-headline-md font-bold text-primary tracking-tight">Chungu</span>
          </div>
          <div className="flex items-center gap-6">
            {user ? (
              <>
                <Link to="/dashboard" className="text-body-md text-on-surface-variant hover:text-primary transition-colors font-medium">내 작업</Link>
                <Link to="/payment" className="text-body-md flex items-center gap-1 text-primary hover:underline font-medium"><Coins size={18} /> {profile?.points_balance ?? '-'} P</Link>
              </>
            ) : (
              <Link to="/login" className="text-body-md flex items-center gap-1 text-on-surface-variant hover:text-primary transition-colors font-medium"><LogIn size={18} /> 로그인</Link>
            )}
            <a href="/admin" className="text-on-surface-variant hover:text-primary transition-colors" title="관리자"><Settings size={20} /></a>
          </div>
        </div>
      </nav>

      <main className="flex-grow flex flex-col items-center justify-center bg-grid relative pb-20">
        <div className="absolute inset-0 pointer-events-none overflow-hidden">
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] bg-primary/5 rounded-full blur-[120px]"></div>
        </div>

        <div className="w-full max-w-3xl px-gutter text-center relative z-10">
          <h1 className="text-display font-display text-on-surface mb-4 tracking-tight">
            파일을 <span className="text-primary">정밀 데이터</span>로 변환
          </h1>
          <p className="text-body-lg text-on-surface-variant mb-12 opacity-80">
            AI로 PDF, 이미지, 오디오에서 표를 자동 추출합니다
          </p>

          <form onSubmit={handleUpload}>
            <label
              onDrop={handleDrop}
              onDragOver={(e) => e.preventDefault()}
              className="group relative bg-surface border border-outline-variant/60 rounded-[32px] p-2 shadow-2xl shadow-primary/5 hover:shadow-primary/10 transition-all duration-500 block cursor-pointer"
            >
              <div className="border-2 border-dashed border-outline-variant/40 group-hover:border-primary/40 rounded-[24px] p-16 flex flex-col items-center justify-center transition-colors bg-surface-container-lowest">
                <div className="w-20 h-20 bg-primary-container/10 rounded-full flex items-center justify-center mb-6 group-hover:scale-110 transition-transform duration-300">
                  <FileUp className="text-primary" size={48} />
                </div>
                <h3 className="text-headline-md font-medium text-on-surface mb-2">여기에 파일을 놓으세요</h3>
                <p className="text-body-md text-outline">PDF, 이미지, 오디오, 비디오, 압축 파일</p>
                <button
                  type="button"
                  onClick={(e) => {
                    e.preventDefault()
                    document.getElementById('file-input').click()
                  }}
                  className="mt-8 px-8 py-3 bg-primary text-on-primary rounded-full font-headline-md hover:bg-primary-container transition-all shadow-md"
                >
                  파일 선택
                </button>
                <input
                  id="file-input"
                  type="file"
                  multiple
                  className="hidden"
                  accept=".pdf,.zip,.rar,.7z,.tar.gz,.png,.jpg,.jpeg,.gif,.webp,.mp3,.wav,.mp4,.avi,.mov,.mkv,.webm"
                  onChange={(e) => setFiles(Array.from(e.target.files || []))}
                />
              </div>
            </label>

            {files.length > 0 && (
              <div className="mt-4 bg-white rounded-xl border border-outline-variant p-4 text-left max-w-xl mx-auto">
                <p className="text-sm font-medium text-on-surface mb-2">선택된 파일</p>
                <ul className="text-sm text-on-surface-variant space-y-1">
                  {files.map((f, i) => (
                    <li key={i} className="flex items-center gap-2">
                      <span className="bg-surface-container px-2 py-0.5 rounded">{f.name}</span>
                      <span>({(f.size / 1024 / 1024).toFixed(2)} MB)</span>
                    </li>
                  ))}
                </ul>
                {error && <p className="text-red-600 text-sm mt-3">{error}</p>}
                <div className="flex gap-3 mt-4">
                  <button type="button" onClick={() => setFiles([])} className="flex-1 border border-outline-variant rounded-lg py-2.5 text-sm font-medium hover:bg-surface-container transition-colors">
                    취소
                  </button>
                  <button type="submit" disabled={submitting}
                    className="flex-1 bg-primary text-on-primary rounded-lg py-2.5 font-medium hover:bg-primary-container transition-colors disabled:opacity-50 flex items-center justify-center gap-2">
                    {submitting ? <><Loader2 className="animate-spin" size={18} /> 업로드 중…</> : '변환 시작'}
                  </button>
                </div>
              </div>
            )}
          </form>

          <div className="mt-8 flex justify-center gap-8 text-label-sm text-outline font-medium uppercase tracking-widest opacity-60">
            <span className="flex items-center gap-1.5"><span className="text-sm">보안</span> 암호화</span>
            <span className="flex items-center gap-1.5"><span className="text-sm">즉시</span> 처리</span>
            <span className="flex items-center gap-1.5"><span className="text-sm">100+</span> 언어</span>
          </div>
        </div>
      </main>

      <footer className="w-full py-8 border-t border-outline-variant/20">
        <div className="max-w-container-max mx-auto px-gutter flex flex-col md:flex-row justify-between items-center gap-4 text-label-sm text-outline">
          <div className="flex items-center gap-4">
            <p>© 2024 Chungu Technologies</p>
          </div>
          <div className="flex items-center gap-6">
            <Link to="/developer" className="hover:text-primary transition-colors">API</Link>
            <a href="/admin" className="hover:text-primary transition-colors">관리자</a>
          </div>
        </div>
      </footer>
    </div>
  )
}
