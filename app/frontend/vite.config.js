import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// [Flow: Step 1 (react 플러그인) -> Step 2 (VITE_DEV_BACKEND_URL 환경변수에서 개발 백엔드 주소 읽기) -> Step 3 (/api, /supabase를 해당 백엔드로 프록시)]
// 로컬 개발 시 프론트엔드는 Vite dev server를 띄우고, API/Supabase 요청을 a1(또는 SSH 터널링한 localhost)로 전달합니다.
const devBackendUrl = process.env.VITE_DEV_BACKEND_URL || 'http://192.168.1.50:28181'

export default defineConfig({
  plugins: [react()],
  envDir: '..',
  server: {
    host: true,
    proxy: {
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
