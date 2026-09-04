import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// [Flow: Step 1 (react 플러그인) -> Step 2 (loadEnv로 envDir에서 환경변수 로드)
//       -> Step 3 (/api/ai -> AI 백엔드, /api -> Python FastAPI, /supabase -> Supabase 직접 or FastAPI)]
// 로컬 개발 시 Vite dev server가 API/Supabase 요청을 a1로 프록시합니다.
// /supabase는 기본적으로 FastAPI 프록시를 사용하되, VITE_DEV_SUPABASE_URL이 설정되면
// a1 Supabase Kong으로 직접 연결해 개발 환경에서 Turnstile 등 FastAPI 보안 검증을 우회합니다.
// loadEnv를 사용해 envDir('..')에서 .env.development를 읽는다.
// process.env로는 Vite env 파일의 VITE_ 변수를 읽을 수 없다.

// [Flow: Step 1 (node_modules 경로에서 패키지명 추출) -> Step 2 (그룹 규칙에 매칭) -> Step 3 (벤더 청크명 반환)]
//
// 객체 형태의 manualChunks 는 쓰지 않는다. 객체 형태는 나열한 패키지의 "전이 의존"까지
// 같은 청크로 빨아들이는데, 그 과정에서 react/jsx-runtime 이 tiptap-vendor 로,
// Vite 의 __vite_preload 헬퍼가 pdf-viewer 로 끌려갔다. 그 결과 진입 청크가 헬퍼 하나
// 때문에 brotli 347KB(pdf-viewer + tiptap-vendor)를 정적 import 하게 된다.
// 함수 형태로 패키지명을 직접 매칭하면 매칭되지 않은 모듈(가상 모듈·헬퍼 포함)은
// undefined 를 반환해 Rollup 기본 배치를 따르므로 이 오염이 발생하지 않는다.
const VENDOR_GROUPS = [
  // react 계열을 먼저 매칭한다. 패키지명 완전 일치로 비교하므로 react-i18next 는 걸리지 않는다.
  ['react-vendor', ['react', 'react-dom', 'react-router', 'react-router-dom', 'scheduler']],
  ['three-vendor', ['three', 'postprocessing', 'ogl']],
  // @embedpdf/pdfjs-dist 는 수동 그룹으로 묶지 않는다. 자체 dynamic import 로
  // worker-engine/direct-engine 을 쪼개는데, 강제로 한 청크에 모으면 그 분할이 무너진다.
  ['flow-vendor', [/^@xyflow\//]],
  ['tiptap-vendor', [/^@tiptap\//, /^prosemirror-/]],
  ['ai-vendor', ['ai', /^@ai-sdk\//]],
  ['supabase-vendor', [/^@supabase\//]],
  ['dnd-vendor', [/^@dnd-kit\//]],
  ['utils-vendor', [
    'dayjs', 'moment', 'marked', 'turndown',
    'i18next', 'react-i18next', 'i18next-browser-languagedetector',
    'lucide-react',
  ]],
]

/** node_modules 경로에서 (스코프 포함) 패키지명을 뽑는다. 없으면 null. */
function packageNameOf(id) {
  const match = id.replace(/\\/g, '/').match(/\/node_modules\/((?:@[^/]+\/)?[^/]+)/)
  return match ? match[1] : null
}

function manualChunks(id) {
  // Vite 의 __vite_preload 헬퍼는 가상 모듈이라 패키지명이 없다. 배치를 지정하지 않으면
  // Rollup 이 임의의 async 벤더 청크(실측: pdf-viewer)에 넣어버리고, 그러면 진입 청크가
  // 헬퍼 하나 때문에 그 청크 전체를 정적 import 하게 된다. 항상 초기 로드되는
  // react-vendor 에 고정해 추가 요청 없이 어느 청크에서든 참조 가능하게 한다.
  if (id.includes('vite/preload-helper')) return 'react-vendor'

  const pkg = packageNameOf(id)
  if (!pkg) return undefined
  for (const [chunk, rules] of VENDOR_GROUPS) {
    for (const rule of rules) {
      if (typeof rule === 'string' ? pkg === rule : rule.test(pkg)) return chunk
    }
  }
  return undefined
}

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
        // 키를 '^' 로 시작하면 Vite 가 정규식으로 취급한다. 접두사 문자열 '/api' 를 쓰면
        // /api-pricing 같은 SPA 라우트까지 백엔드로 프록시되어 로컬에서 빈 화면이 된다.
        // 실제 API 는 항상 /api/ 아래에 있으므로 슬래시까지 포함해 매칭한다.
        '^/api/ai': {
          target: devAiBackendUrl,
          changeOrigin: true,
        },
        '^/api/': {
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
          manualChunks,
        },
      },
    },
  }
})
