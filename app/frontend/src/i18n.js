// [Flow: Step 1 (fallback 인 en 만 정적 번들) -> Step 2 (ko/ja 는 backend 플러그인으로 동적 import)
//       -> Step 3 (language detection) -> Step 4 (i18n init, 감지된 언어만 네트워크로 로드)]
//
// 세 언어를 모두 정적 import 하면 로케일 JSON 312KB(brotli 77KB)가 통째로 진입 청크에 들어간다.
// 사용자는 한 번에 한 언어만 쓰므로, fallbackLng 인 en 만 번들에 남기고 ko/ja 는 분리한다.
// partialBundledLanguages 가 있어야 i18next 가 번들된 en 과 backend 로 읽어온 ko/ja 를 함께 쓴다.
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import LanguageDetector from 'i18next-browser-languagedetector'

import enCommon from './locales/en/common.json'
import enPage from './locales/en/page.json'

const supportedLngs = ['en', 'ko', 'ja']

// 정적 번들: fallbackLng 인 en 은 키 누락 시 항상 필요하므로 진입 청크에 남긴다.
const resources = {
  en: { common: enCommon, page: enPage },
}

// 동적 청크: 감지된 언어의 네임스페이스만 내려받는다.
const localeLoaders = {
  ko: {
    common: () => import('./locales/ko/common.json'),
    page: () => import('./locales/ko/page.json'),
  },
  ja: {
    common: () => import('./locales/ja/common.json'),
    page: () => import('./locales/ja/page.json'),
  },
}

// i18next backend 플러그인 최소 구현. read() 가 비동기이므로 changeLanguage() 가
// 리소스 도착까지 대기한다 — LanguageProvider 의 await 이 그대로 동작한다.
const dynamicLocaleBackend = {
  type: 'backend',
  init() {},
  read(language, namespace, callback) {
    const loader = localeLoaders[language]?.[namespace]
    // en 은 이미 번들되어 있고, 미지원 언어는 fallbackLng 가 처리한다.
    if (!loader) {
      callback(null, {})
      return
    }
    loader().
    then((mod) => callback(null, mod.default)).
    catch((err) => callback(err, null))
  },
}

i18n.
use(dynamicLocaleBackend).
use(LanguageDetector).
use(initReactI18next).
init({
  resources,
  partialBundledLanguages: true,
  supportedLngs,
  fallbackLng: 'en',
  defaultNS: 'common',
  ns: ['common', 'page'],
  interpolation: { escapeValue: false },
  detection: {
    order: ['localStorage', 'navigator', 'htmlTag'],
    caches: ['localStorage'],
    lookupLocalStorage: 'proof-language',
  },
  load: 'languageOnly',
  // 로케일 청크가 도착하기 전에도 트리를 렌더링한다 — Suspense 로 화면 전체를 막지 않는다.
  react: { useSuspense: false },
})

export default i18n
