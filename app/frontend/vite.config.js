import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// [Flow: Step 1 (react 플러그인) -> Step 2 (dev 프록시로 /api -> 백엔드)]
export default defineConfig({
  plugins: [react()],
  envDir: '..',
  server: {
    proxy: {
      '/api': 'http://localhost:28181',
    },
  },
  build: {
    outDir: 'dist',
  },
})
