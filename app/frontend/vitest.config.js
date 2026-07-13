import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// [Flow: Step 1 (Vite React 플러그인 활성화) -> Step 2 (Vitest jsdom 환경 + globals + setup 파일 지정)]
// 프론트엔드 컴포넌트/유틸리티 단위 테스트를 위한 Vitest 설정.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/setupTests.js"],
  },
});
