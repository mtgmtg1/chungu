import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// [Flow: Step 1 (react 플러그인) -> Step 2 (환경변수에서 개발 백엔드 주소 읽기)
//       -> Step 3 (/api/ai -> Node.js AI 백엔드, /api, /supabase -> Python FastAPI로 프록시)]
// 로컬 개발 시 프론트엔드는 Vite dev server를 띄우고, AI 채팅은 Node.js 백엔드로,
// 기존 API/Supabase는 Python FastAPI로 전달합니다.
const devBackendUrl = process.env.VITE_DEV_BACKEND_URL || 'http://192.168.1.50:28181'
const devAiBackendUrl = process.env.VITE_DEV_AI_BACKEND_URL || 'http://localhost:3001'

export default defineConfig({
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
})
