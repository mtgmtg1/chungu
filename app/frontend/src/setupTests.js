// [Flow: Step 1 (jest-dom matcher 등록) -> Step 2 (i18n 기본 언어 ko로 설정)
//       -> Step 3 (jsdom matchMedia mock 추가 -> react-chrono 등 미디어 쿼리 사용 컴포넌트 렌더링 가능)]
// Vitest 테스트 실행 전 공통 초기화: DOM matcher, i18n 리소스, matchMedia mock을 등록한다.

import "@testing-library/jest-dom";
import { vi } from "vitest";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import koPage from "./locales/ko/page.json";
import enPage from "./locales/en/page.json";
import jaPage from "./locales/ja/page.json";

// [Flow: Vitest jsdom 환경에 Supabase/환경 변수 기본값 주입 -> api.js 초기화 오류 방지]
// 실제 서버 호출은 테스트에서 모킹하지 않으므로 더미 값으로 충분하다.
process.env.VITE_SUPABASE_URL = "http://localhost:54321";
process.env.VITE_SUPABASE_ANON_KEY = "dummy-anon-key-for-tests";

// [Flow: jsdom에는 matchMedia가 없으므로 mock 추가 -> react-chrono가 미디어 쿼리를 사용할 수 있게 함]
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

i18n.use(initReactI18next).init({
  lng: "ko",
  fallbackLng: "ko",
  resources: {
    ko: { page: koPage },
    en: { page: enPage },
    ja: { page: jaPage },
  },
  interpolation: { escapeValue: false },
});
