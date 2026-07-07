import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// [Flow: Step 1 (react 플러그인) -> Step 2 (loadEnv로 envDir에서 환경변수 로드)
//       -> Step 3 (/api/ai -> Node.js AI 백엔드, /api, /supabase -> Python FastAPI로 프록시)]
// 로컬 개발 시 프론트엔드는 Vite dev server를 띄우고, AI 채팅은 Node.js 백엔드로,
// 기존 API/Supabase는 Python FastAPI로 전달합니다.
// loadEnv를 사용해 envDir('..')에서 .env.development를 읽는다.
// process.env로는 Vite env 파일의 VITE_ 변수를 읽을 수 없다.
export default defineConfig(({ mode }) => {
  // envDir가 '..'이므로 app/ 디렉토리에서 env 로드
  const env = loadEnv(mode, process.cwd() + '/..', '')
  const devBackendUrl = env.VITE_DEV_BACKEND_URL || 'http://192.168.1.50:28181'
  const devAiBackendUrl = env.VITE_DEV_AI_BACKEND_URL || 'http://localhost:3001'

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
          target: devBackendUrl,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: 'dist',
    },
  }
})
