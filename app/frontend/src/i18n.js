// [Flow: Step 1 (import i18n resources) -> Step 2 (configure language detection) -> Step 3 (init i18n with fallback)]
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import LanguageDetector from 'i18next-browser-languagedetector'

import enCommon from './locales/en/common.json'
import enPage from './locales/en/page.json'

import koCommon from './locales/ko/common.json'
import koPage from './locales/ko/page.json'

import jaCommon from './locales/ja/common.json'
import jaPage from './locales/ja/page.json'

const resources = {
  en: { common: enCommon, page: enPage },
  ko: { common: koCommon, page: koPage },
  ja: { common: jaCommon, page: jaPage },
}

const supportedLngs = ['en', 'ko', 'ja']

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    supportedLngs,
    fallbackLng: 'en',
    defaultNS: 'common',
    ns: ['common', 'page'],
    interpolation: { escapeValue: false },
    detection: {
      order: ['localStorage', 'navigator', 'htmlTag'],
      caches: ['localStorage'],
      lookupLocalStorage: 'chungu-language',
    },
    load: 'languageOnly',
  })

export default i18n
