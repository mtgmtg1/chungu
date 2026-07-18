import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// [Flow: Step 1 (react 플러그인) -> Step 2 (loadEnv로 envDir에서 환경변수 로드)
//       -> Step 3 (/api/ai -> AI 백엔드, /api -> Python FastAPI, /supabase -> Supabase 직접 or FastAPI)]
// 로컬 개발 시 Vite dev server가 API/Supabase 요청을 a1로 프록시합니다.
// /supabase는 기본적으로 FastAPI 프록시를 사용하되, VITE_DEV_SUPABASE_URL이 설정되면
// a1 Supabase Kong으로 직접 연결해 개발 환경에서 Turnstile 등 FastAPI 보안 검증을 우회합니다.
// loadEnv를 사용해 envDir('..')에서 .env.development를 읽는다.
// process.env로는 Vite env 파일의 VITE_ 변수를 읽을 수 없다.
export default defineConfig(({ mode }) => {
  // envDir가 '..'이므로 app/ 디렉토리에서 env 로드
  const env = loadEnv(mode, process.cwd() + '/..', '')
  const devBackendUrl = env.VITE_DEV_BACKEND_URL || 'http://192.168.1.50:28181'
  const devAiBackendUrl = env.VITE_DEV_AI_BACKEND_URL || 'http://localhost:3001'
  const devSupabaseUrl = env.VITE_DEV_SUPABASE_URL || devBackendUrl

  return {
    plugins: [react()],
    envDir: '..',
    server: {
      host: true,
      proxy: {
        '/api/ai': {
          target: devAiBackendUrl,
          changeOrigin: true,
        },
        '/api': {
          target: devBackendUrl,
          changeOrigin: true,
        },
        '/supabase': {
          target: 'http://localhost:9999',
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: 'dist',
    },
  }
})
