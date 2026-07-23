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
        '/supabase': env.VITE_DEV_SUPABASE_URL
          ? {
              target: env.VITE_DEV_SUPABASE_URL,
              changeOrigin: true,
              rewrite: (path) => path.replace(/^\/supabase/, ''),
            }
          : {
              target: devBackendUrl,
              changeOrigin: true,
            },
      },
    },
    build: {
      outDir: 'dist',
      rollupOptions: {
        output: {
          manualChunks: {
            // React 코어 (모든 페이지에서 사용)
            'react-vendor': ['react', 'react-dom', 'react-router-dom'],
            // 3D 그래픽 (GridScan에서만 사용)
            'three-vendor': ['three', 'postprocessing', 'ogl'],
            // PDF 뷰어 (JobResultPage에서만 사용)
            'pdf-viewer': ['@embedpdf/react-pdf-viewer', 'pdfjs-dist'],
            // 플로우 다이어그램 (DevEdiscoveryPage에서만 사용)
            'flow-vendor': ['@xyflow/react'],
            // TipTap 에디터 (여러 컴포넌트에서 사용)
            'tiptap-vendor': [
              '@tiptap/react',
              '@tiptap/starter-kit',
              '@tiptap/extension-bubble-menu',
              '@tiptap/extension-heading',
              '@tiptap/extension-highlight',
              '@tiptap/extension-image',
              '@tiptap/extension-link',
              '@tiptap/extension-placeholder',
              '@tiptap/extension-table',
              '@tiptap/extension-table-cell',
              '@tiptap/extension-table-header',
              '@tiptap/extension-table-of-contents',
              '@tiptap/extension-table-row',
              '@tiptap/extension-task-item',
              '@tiptap/extension-task-list',
              '@tiptap/extension-text-align',
              '@tiptap/extension-underline',
              '@tiptap/extension-unique-id',
            ],
            // AI SDK
            'ai-vendor': ['ai', '@ai-sdk/react'],
            // Supabase
            'supabase-vendor': ['@supabase/supabase-js'],
            // DnD
            'dnd-vendor': ['@dnd-kit/core', '@dnd-kit/utilities'],
            // 기타 유틸
            'utils-vendor': ['dayjs', 'moment', 'marked', 'turndown', 'i18next', 'react-i18next', 'i18next-browser-languagedetector', 'lucide-react'],
          },
        },
      },
    },
  }
})
